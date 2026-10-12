import os
import re
import time
import logging
from typing import Dict, Any, List, Optional
from pathlib import Path

ENV_FILE = (
    Path(__file__).resolve().parent / ".env"
    if "__file__" in globals()
    else Path(".env").resolve()
)


def load_env() -> None:
    """Injeta as variáveis do arquivo .env de forma resiliente."""
    try:
        from dotenv import load_dotenv
        load_dotenv(dotenv_path=ENV_FILE, override=True)
        return
    except ImportError:
        pass

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
BACKEND_HEALTH_URL = os.getenv("BACKEND_HEALTH_URL", "http://localhost:8000/api/health").strip()
BACKEND_TIMEOUT = float(os.getenv("BACKEND_TIMEOUT", "60.0").strip())
USE_MOCK = os.getenv("USE_MOCK", "false").strip().lower() in ("true", "1", "yes")
OUTPUT_MODE = os.getenv("OUTPUT_MODE", "raw").strip().lower()

try:
    import httpx
except ImportError:
    httpx = None

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("telegram_bot")

URL_REGEX = re.compile(r"https?://[^\s<>\"']+")

VERDICT_EMOJIS = {
    "VERDADEIRO": "🟢 VERDADEIRO",
    "FAKE": "🔴 FAKE",
    "SUSPEITO": "🟡 SUSPEITO",
    "INCONCLUSIVO": "⚪ INCONCLUSIVO",
}


def mock_check(text: str) -> Dict[str, Any]:
    """Gera resposta simulada para checagem de fatos/mensagens."""
    lower_text = text.lower()
    keywords_fake = [
        "urgente", "repasse", "compartilhe", "cura milagrosa", "boato", "fake",
        "confisco", "segredo revelado", "adesivo", "reais",
    ]
    is_fake = any(kw in lower_text for kw in keywords_fake)

    short_claim = text.strip().replace("\n", " ")
    if len(short_claim) > 80:
        short_claim = short_claim[:77] + "..."

    if is_fake:
        return {
            "claim": short_claim,
            "verdict": "FAKE",
            "confidence": 0.93,
            "summary": "Afirmação falsa ou desmentida por agências de checagem e bases científicas.",
            "reasons": [
                "Linguagem apelativa ou alarmista com pedidos de repasse.",
                "Inconsistência factual com dados públicos e órgãos oficiais.",
            ],
            "sources": ["Agência Lupa", "Aos Fatos", "Projeto Comprova", "Anvisa"],
            "risks_assessment": [
                "Risco de desinformação à saúde pública e potenciais danos terapêuticos.",
                "Risco de fraude ou comercialização irregular.",
            ],
        }
    return {
        "claim": short_claim,
        "verdict": "VERDADEIRO",
        "confidence": 0.88,
        "summary": "Informação condizente com registros, apurações e coberturas de referência.",
        "reasons": [
            "Não foram encontradas evidências de manipulação.",
            "Consistente com coberturas de imprensa e fontes primárias.",
        ],
        "sources": ["Consórcio de Imprensa", "Fontes Oficiais"],
    }


async def check_backend_health() -> Dict[str, Any]:
    """Consulta a rota de integridade da API FactChkBR."""
    if httpx is None:
        return {"status": "error", "message": "httpx não instalado"}

    try:
        t0 = time.perf_counter()
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(BACKEND_HEALTH_URL)
            latency_ms = int((time.perf_counter() - t0) * 1000)
            if resp.status_code == 200:
                data = resp.json()
                data["latency_ms"] = latency_ms
                return data
            return {
                "status": "error",
                "message": f"HTTP {resp.status_code}: {resp.text}",
                "latency_ms": latency_ms,
            }
    except Exception as exc:
        return {"status": "offline", "message": str(exc)}


async def call_backend(text: str, user_id: Optional[int] = None, chat_id: Optional[int] = None) -> Dict[str, Any]:
    """Envia o texto/fato para a API do back-end FactChkBR ou roda o mock."""
    if USE_MOCK:
        return mock_check(text)

    if httpx is None:
        return {"error": "Biblioteca 'httpx' não instalada. Instale com: pip install httpx"}

    # Extrai URLs auxiliares caso o usuário envie links junto com o texto
    urls: List[str] = [u.rstrip(".,;!?") for u in URL_REGEX.findall(text)]

    payload = {
        "text": text,
        "urls": urls,
        "user_id": user_id,
        "chat_id": chat_id,
    }

    try:
        async with httpx.AsyncClient(timeout=BACKEND_TIMEOUT) as client:
            resp = await client.post(BACKEND_URL, json=payload)
            if resp.status_code == 200:
                return resp.json()
            return {
                "error": f"Erro do back-end (HTTP {resp.status_code}): {resp.text[:300]}"
            }
    except httpx.ConnectError:
        return {
            "error": (
                f"Não foi possível conectar ao back-end em '{BACKEND_URL}'. "
                "Verifique se o servidor FactChkBR está rodando (ex: uvicorn app.main:app --port 8000)."
            )
        }
    except httpx.TimeoutException:
        return {
            "error": f"Tempo limite ({int(BACKEND_TIMEOUT)}s) excedido ao aguardar análise do back-end."
        }
    except Exception as exc:
        return {"error": f"Exceção inesperada na comunicação: {str(exc)}"}


def format_raw_output(data: Dict[str, Any]) -> str:
    """Formata a análise de forma crua e direta conforme especificação."""
    if "error" in data:
        return f"[ERRO]\n{data['error']}"

    confidence_val = data.get("confidence", 0)
    confidence_pct = int(confidence_val * 100) if confidence_val <= 1 else int(confidence_val)
    raw_verdict = str(data.get("verdict", "-")).upper()
    verdict_display = VERDICT_EMOJIS.get(raw_verdict, raw_verdict)

    lines = [
        f"Fato/Texto: {data.get('claim', '-')}",
        f"Veredito: {verdict_display}",
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

    sub_claims = data.get("sub_claims", [])
    if sub_claims and len(sub_claims) > 1:
        lines.append("Detalhamento por Alegação:")
        for sc in sub_claims:
            stmt = sc.get("statement", "")
            sc_v = str(sc.get("verdict", "-")).upper()
            sc_v_display = VERDICT_EMOJIS.get(sc_v, sc_v)
            sc_c = int(sc.get("confidence", 0) * 100) if sc.get("confidence", 0) <= 1 else int(sc.get("confidence", 0))
            lines.append(f"- \"{stmt}\" -> {sc_v_display} ({sc_c}%)")

    risks = data.get("risks_assessment", [])
    if risks:
        lines.append("Avaliação de Riscos:")
        for r in risks:
            lines.append(f"- {r}")

    return "\n".join(lines)


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message:
        welcome_text = (
            "🤖 *FactChkBR Bot - Checagem de Mensagens e Fatos*\n\n"
            "Envie ou encaminhe qualquer texto, afirmação, notícia ou link para análise.\n\n"
            "Comandos disponíveis:\n"
            "• `/start` - Inicia o bot e exibe esta mensagem\n"
            "• `/health` - Verifica o status da API FactChkBR\n"
            "• `/help` - Instruções detalhadas de uso"
        )
        await update.message.reply_text(welcome_text, parse_mode="Markdown")


async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message:
        help_text = (
            "ℹ️ *Como utilizar o FactChkBR Bot:*\n\n"
            "1. Copie ou encaminhe uma mensagem suspeita (de WhatsApp, Telegram, redes sociais ou sites).\n"
            "2. O bot enviará o texto para a esteira de análise de IA e bases de checagem do FactChkBR.\n"
            "3. Você receberá o veredito oficial com nível de confiança, justificativa e fontes apuradas.\n\n"
            f"Configuração atual: Backend `{BACKEND_URL}` (Mock: `{USE_MOCK}`)."
        )
        await update.message.reply_text(help_text, parse_mode="Markdown")


async def health_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message:
        status_msg = await update.message.reply_text("Consultando status do back-end FactChkBR...")
        health_data = await check_backend_health()

        if health_data.get("status") == "ok":
            active_analyzers = ", ".join(health_data.get("active_analyzers", [])) or "Padrão"
            text = (
                "✅ *Back-end FactChkBR Online*\n\n"
                f"• URL: `{BACKEND_HEALTH_URL}`\n"
                f"• Versão: `{health_data.get('version', '1.0.0')}`\n"
                f"• Latência: `{health_data.get('latency_ms', 0)} ms`\n"
                f"• Analisadores Ativos: `{active_analyzers}`\n"
                f"• Modo do Bot: `{'Simulação (Mock)' if USE_MOCK else 'Conexão Direta (API Real)'}`"
            )
        else:
            text = (
                "⚠️ *Back-end FactChkBR Inacessível*\n\n"
                f"• URL: `{BACKEND_HEALTH_URL}`\n"
                f"• Detalhes: `{health_data.get('message', 'Sem resposta')}`\n"
                f"• Modo do Bot: `{'Simulação (Mock)' if USE_MOCK else 'Aguardando Servidor'}`"
            )
        await status_msg.edit_text(text, parse_mode="Markdown")


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

    # Feedback de digitação imediato
    if update.effective_chat:
        try:
            await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
        except Exception:
            pass

    status_msg = await message.reply_text("🔍 Analisando mensagem no FactChkBR...")
    result = await call_backend(text, user_id=user_id, chat_id=chat_id)

    # Se modo rich estiver habilitado e houver texto HTML do backend
    if OUTPUT_MODE == "rich" and result.get("telegram_formatted_text") and "error" not in result:
        await status_msg.edit_text(result["telegram_formatted_text"], parse_mode="HTML")
    else:
        formatted = format_raw_output(result)
        await status_msg.edit_text(formatted)


def main() -> None:
    if not TOKEN:
        print("Erro: TELEGRAM_BOT_TOKEN não definido no .env ou nas variáveis de ambiente.")
        print("Configure o token no arquivo .env (conforme .env.example) para executar.")
        return

    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("help", help_handler))
    app.add_handler(CommandHandler("health", health_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    print("=" * 60)
    print("🤖 FactChkBR Telegram Bot Iniciado")
    print(f"📡 Backend URL: {BACKEND_URL}")
    print(f"⚙️ Modo Mock: {USE_MOCK} | Modo Saída: {OUTPUT_MODE}")
    print("=" * 60)
    app.run_polling()


if __name__ == "__main__":
    main()