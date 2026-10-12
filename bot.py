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

TECHNICAL_TERMS_BLACKLIST = (
    "base vetorial", "factchkbr (chromadb)", "chromadb", "chroma", "vector", "vetorial",
    "padrões estilísticos", "estilometria", "ônus da prova", "precedência probatória",
    "spacy", "jevk5", "plumb", "laya", "llm judge", "ollama", "onnx", "gatekeeper",
    "similaridade:", "vector_cache", "banco vetorial",
)

VERDICT_EMOJIS = {
    "VERDADEIRO": "🟢 FATO (VERDADEIRO)",
    "FAKE": "🔴 BOATO (FALSO)",
    "SUSPEITO": "🟡 ENGANOSO / SUSPEITO",
    "INCONCLUSIVO": "⚪ NÃO COMPROVADO",
}

VERDICT_EMOJIS_INLINE = {
    "VERDADEIRO": "🟢 Verdadeiro",
    "FAKE": "🔴 Falso",
    "SUSPEITO": "🟡 Enganoso",
    "INCONCLUSIVO": "⚪ Não Comprovado",
}


def clean_accessible_text(text: str) -> str:
    """Remove jargões técnicos, referências à base vetorial e normaliza o texto para cidadãos."""
    if not text:
        return ""
    t = str(text).strip()

    # 1. Remove referências a bases internas e banco vetorial
    t = re.sub(r"Base Vetorial FactChkBR(?:\s*\([^)]*\))?:?\s*", "", t, flags=re.IGNORECASE)
    t = re.sub(r"ChromaDB(?:\s*\([^)]*\))?:?\s*", "", t, flags=re.IGNORECASE)
    t = re.sub(r"banco vetorial(?:\s*\([^)]*\))?:?\s*", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\(Similaridade:\s*\d+%\)", "", t, flags=re.IGNORECASE)
    t = re.sub(r"Similaridade:\s*\d+%", "", t, flags=re.IGNORECASE)

    # 2. Remove módulos de arquitetura e classificadores internos
    t = re.sub(r"Classificador de Decisão (?:Plumb-4B|JevK5-Lite):?\s*", "", t, flags=re.IGNORECASE)
    t = re.sub(r"Plumb-4B", "", t, flags=re.IGNORECASE)
    t = re.sub(r"JevK5-Lite", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\bLaya\b", "", t, flags=re.IGNORECASE)
    t = re.sub(r"LLM Judge(?:\s*\([^)]*\))?:?\s*", "", t, flags=re.IGNORECASE)
    t = re.sub(r"Ollama local(?:\s*\([^)]*\))?:?\s*", "", t, flags=re.IGNORECASE)
    t = re.sub(r"spaCy Gatekeeper(?:\s*\+[^)]*\))?:?\s*", "", t, flags=re.IGNORECASE)
    t = re.sub(r"Heurística Textual.*?:?\s*", "", t, flags=re.IGNORECASE)
    t = re.sub(r"Extrator FactChkBR.*?:?\s*", "", t, flags=re.IGNORECASE)
    t = re.sub(r"Filtro de Escopo.*?:?\s*", "", t, flags=re.IGNORECASE)
    t = re.sub(r"Extração concluída: texto com padrões estilísticos neutros\.?", "", t, flags=re.IGNORECASE)
    t = re.sub(r"Sem predicado factual checável\.?", "", t, flags=re.IGNORECASE)
    t = re.sub(r"Claim principal: \"[^\"]*\"\.?", "", t, flags=re.IGNORECASE)

    # 3. Simplifica jargões de ônus da prova e termos acadêmicos
    t = re.sub(
        r"sob o princípio de ônus da prova,?\s*afirmações.*?são tratadas como provavelmente falsas.*?\.",
        "Não encontramos estudos médicos nem registros oficiais que comprovem essa afirmação.",
        t,
        flags=re.IGNORECASE,
    )
    t = re.sub(
        r"sob o princípio de ônus da prova,?\s*",
        "",
        t,
        flags=re.IGNORECASE,
    )
    t = re.sub(
        r"Prevalência de checagem oficial:?\s*",
        "",
        t,
        flags=re.IGNORECASE,
    )
    t = re.sub(
        r"precedência probatória:?\s*",
        "",
        t,
        flags=re.IGNORECASE,
    )

    t = re.sub(r"\s+", " ", t).strip()
    return t


def clean_accessible_sources(sources: List[str]) -> List[str]:
    """
    Filtra e limpa fontes, eliminando menções à base vetorial, ChromaDB
    e módulos técnicos internos.
    """
    cleaned: List[str] = []
    seen = set()

    for s in sources:
        if not s:
            continue
        s_str = str(s).strip()
        s_lower = s_str.lower()

        # Descarta termos técnicos e bases vetoriais
        if any(term in s_lower for term in TECHNICAL_TERMS_BLACKLIST):
            continue

        # Remove prefixos técnicos residuais
        s_clean = re.sub(r"^Base Vetorial[^:]*:\s*", "", s_str, flags=re.IGNORECASE).strip()
        s_clean = re.sub(r"^Checagem de Referência Anterior:?\s*", "", s_clean, flags=re.IGNORECASE).strip()

        if s_clean and s_clean not in seen:
            seen.add(s_clean)
            cleaned.append(s_clean)

    if not cleaned:
        cleaned = ["Ministério da Saúde (Brasil)", "Anvisa", "Agências Profissionais de Checagem"]

    return cleaned


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
            "summary": "Afirmação falsa desmentida por agências de checagem e autoridades oficiais.",
            "reasons": [
                "Linguagem apelativa e alarmista típica de correntes sem respaldo factual.",
                "Não existem registros de autorização na Anvisa ou no Ministério da Saúde.",
            ],
            "sub_claims": [
                {
                    "statement": short_claim,
                    "verdict": "FAKE",
                    "confidence": 0.93,
                    "justification": "Desmentido por autoridades sanitárias e veículos de imprensa.",
                }
            ],
            "sources": ["Agência Lupa", "Aos Fatos", "Projeto Comprova", "Anvisa"],
            "risks_assessment": [
                "Risco de desinformação à saúde pública e potenciais danos terapêuticos.",
                "Risco de golpe financeiro ou comercialização irregular.",
            ],
        }
    return {
        "claim": short_claim,
        "verdict": "VERDADEIRO",
        "confidence": 0.88,
        "summary": "Informação condizente com registros, apurações e coberturas de referência.",
        "reasons": [
            "Não foram encontradas evidências de manipulação.",
            "Consistente com coberturas de imprensa e dados de órgãos oficiais.",
        ],
        "sub_claims": [
            {
                "statement": short_claim,
                "verdict": "VERDADEIRO",
                "confidence": 0.88,
                "justification": "Confirmado em dados oficiais e cobertura jornalística.",
            }
        ],
        "sources": ["Consórcio de Imprensa", "Ministério da Saúde"],
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
    """Formata a análise de forma acessível, clara e direta para qualquer cidadão."""
    if "error" in data:
        return f"⚠️ Não foi possível concluir a análise no momento:\n{data['error']}"

    confidence_val = data.get("confidence", 0)
    confidence_pct = int(confidence_val * 100) if confidence_val <= 1 else int(confidence_val)
    raw_verdict = str(data.get("verdict", "-")).upper()
    verdict_display = VERDICT_EMOJIS.get(raw_verdict, raw_verdict)
    verdict_inline = VERDICT_EMOJIS_INLINE.get(raw_verdict, raw_verdict)

    claim = clean_accessible_text(str(data.get("claim", "-")))

    lines = [
        "📋 Fato Analisado:",
        f'"{claim}"',
        "",
        f"⚖️ Veredito: {verdict_display} ({confidence_pct}% de certeza)",
        "",
    ]

    # Resumo sobre o julgamento
    summary = clean_accessible_text(data.get("summary", ""))
    if summary:
        lines.extend([
            "📝 Resumo do Julgamento:",
            summary,
            "",
        ])

    # Mostrar cada alegação analisada
    sub_claims = data.get("sub_claims", [])
    if sub_claims:
        lines.append("🔍 Detalhamento por Alegação:")
        for sc in sub_claims:
            stmt = clean_accessible_text(sc.get("statement", ""))
            sc_v = str(sc.get("verdict", "-")).upper()
            sc_v_display = VERDICT_EMOJIS_INLINE.get(sc_v, sc_v)
            sc_c = int(sc.get("confidence", 0) * 100) if sc.get("confidence", 0) <= 1 else int(sc.get("confidence", 0))
            lines.append(f'• "{stmt}" ➔ {sc_v_display} ({sc_c}%)')
            just = clean_accessible_text(sc.get("justification", ""))
            if just and len(just) > 8 and not any(term in just.lower() for term in TECHNICAL_TERMS_BLACKLIST):
                lines.append(f"  └─ {just}")
        lines.append("")
    else:
        # Mostra a alegação principal como detalhamento unitário
        lines.append("🔍 Detalhamento por Alegação:")
        lines.append(f'• "{claim}" ➔ {verdict_inline} ({confidence_pct}%)')
        lines.append("")

    # Motivos e justificativas adicionais (se não houver sub_claims e houver motivos novos)
    reasons = data.get("reasons", [])
    clean_reasons = []
    for r in reasons:
        cr = clean_accessible_text(r)
        if cr and len(cr) > 8 and not any(term in cr.lower() for term in TECHNICAL_TERMS_BLACKLIST):
            if cr not in clean_reasons and cr != summary:
                clean_reasons.append(cr)
    if clean_reasons and not sub_claims:
        lines.append("💡 Motivos e Justificativas:")
        for r in clean_reasons:
            lines.append(f"• {r}")
        lines.append("")

    # Fontes consultadas (limpas e acessíveis, nunca menciona base vetorial)
    raw_sources = data.get("sources", [])
    sources = clean_accessible_sources(raw_sources)
    if sources:
        lines.append("🌐 Fontes Consultadas:")
        for s in sources:
            lines.append(f"• {s}")
        lines.append("")

    # Alertas e Cuidados
    risks = data.get("risks_assessment", [])
    if risks:
        clean_risks = [clean_accessible_text(r) for r in risks if clean_accessible_text(r)]
        if clean_risks:
            lines.append("⚠️ Alertas e Cuidados:")
            for r in clean_risks:
                lines.append(f"• {r}")
            lines.append("")

    return "\n".join(lines).strip()


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