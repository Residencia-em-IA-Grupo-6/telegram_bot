import os
import re
import logging
from typing import Dict, Any, List

from pathlib import Path

ENV_FILE = (
    Path(__file__).resolve().parent / ".env"
    if "__file__" in globals()
    else Path(".env").resolve()
)



def load_env() -> None:
    """Injeta as variáveis do arquivo .env de forma resiliente."""
    # 1. Tenta carregar com python-dotenv se estiver disponível
    try:
        from dotenv import load_dotenv
        load_dotenv(dotenv_path=ENV_FILE, override=True)
        return
    except ImportError:
        pass

    # 2. Fallback nativo (sem dependências externas) caso python-dotenv não esteja no ambiente
    if ENV_FILE.is_file():
        with open(ENV_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, val = line.split("=", 1)
                os.environ[key.strip()] = val.strip().strip("'\"")


load_env()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
BACKEND_URL = os.getenv("BACKEND_API_URL", "http://localhost:8000/api/analyze").strip()
USE_MOCK = os.getenv("USE_MOCK", "true").strip().lower() in ("true", "1", "yes")

try:
    import httpx
except ImportError:
    httpx = None

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

URL_REGEX = re.compile(r"https?://[^\s<>\"']+")



def mock_check(text: str) -> Dict[str, Any]:
    """Gera resposta simulada para checagem de fatos/mensagens."""
    lower_text = text.lower()
    keywords_fake = ["urgente", "repasse", "compartilhe", "cura milagrosa", "boato", "fake", "confisco", "segredo revelado"]
    is_fake = any(kw in lower_text for kw in keywords_fake)

    short_claim = text.strip().replace("\n", " ")
    if len(short_claim) > 80:
        short_claim = short_claim[:77] + "..."

    if is_fake:
        return {
            "claim": short_claim,
            "verdict": "FAKE",
            "confidence": 0.93,
            "summary": "Afirmação falsa ou desmentida por agências de checagem.",
            "reasons": [
                "Linguagem apelativa ou alarmista com pedidos de repasse.",
                "Inconsistência factual com dados públicos e órgãos oficiais.",
            ],
            "sources": ["Agência Lupa", "Aos Fatos", "Projeto Comprova"],
        }
    return {
        "claim": short_claim,
        "verdict": "VERDADEIRO",
        "confidence": 0.88,
        "summary": "Informação condizente com registros e apurações confiáveis.",
        "reasons": [
            "Não foram encontradas evidências de manipulação.",
            "Consistente com coberturas de imprensa e fontes primárias.",
        ],
        "sources": ["Consórcio de Imprensa", "Fontes Oficiais"],
    }


async def call_backend(text: str, user_id: int = None, chat_id: int = None) -> Dict[str, Any]:
    """Envia o texto/fato para a API do back-end ou roda o mock."""
    if USE_MOCK:
        return mock_check(text)

    if httpx is None:
        return {"error": "httpx não instalado. Instale com pip install httpx"}

    # Extrai URLs auxiliares caso o usuário envie links junto com o texto
    urls: List[str] = [u.rstrip(".,;!?") for u in URL_REGEX.findall(text)]

    payload = {
        "text": text,
        "urls": urls,
        "user_id": user_id,
        "chat_id": chat_id,
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(BACKEND_URL, json=payload)
            if resp.status_code == 200:
                return resp.json()
            return {"error": f"HTTP {resp.status_code}: {resp.text}"}
    except Exception as exc:
        return {"error": str(exc)}


def format_raw_output(data: Dict[str, Any]) -> str:
    """Formata a análise de forma crua e direta."""
    if "error" in data:
        return f"[ERRO]\n{data['error']}"

    confidence_val = data.get("confidence", 0)
    confidence_pct = int(confidence_val * 100) if confidence_val <= 1 else int(confidence_val)

    lines = [
        f"Fato/Texto: {data.get('claim', '-')}",
        f"Veredito: {data.get('verdict', '-')}",
        f"Confiança: {confidence_pct}%",
    ]

    if data.get("summary"):
        lines.append(f"Resumo: {data['summary']}")

    reasons = data.get("reasons", [])
    if reasons:
        lines.append("Motivos:")
        for r in reasons:
            lines.append(f"- {r}")

    sources = data.get("sources", [])
    if sources:
        lines.append("Fontes:")
        for s in sources:
            lines.append(f"- {s}")

    return "\n".join(lines)


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message:
        await update.message.reply_text("Envie uma mensagem, notícia ou fato para análise.")


async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    if not message:
        return

    text = message.text or message.caption or ""
    text = text.strip()

    if not text or len(text) < 4:
        await message.reply_text("Envie uma mensagem, notícia ou fato com mais detalhes para análise.")
        return

    user_id = update.effective_user.id if update.effective_user else None
    chat_id = update.effective_chat.id if update.effective_chat else None

    status_msg = await message.reply_text("Analisando mensagem...")
    result = await call_backend(text, user_id=user_id, chat_id=chat_id)
    formatted = format_raw_output(result)
    await status_msg.edit_text(formatted)


def main() -> None:
    if not TOKEN:
        print("Erro: TELEGRAM_BOT_TOKEN não definido no .env ou nas variáveis de ambiente.")
        return

    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    print(f"Bot iniciado (análise de fatos/mensagens). Backend: {BACKEND_URL} (Mock: {USE_MOCK})")
    app.run_polling()


if __name__ == "__main__":
    main()