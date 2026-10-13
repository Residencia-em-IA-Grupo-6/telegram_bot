import sys
from pathlib import Path

# Garante importação do bot.py a partir da raiz do repositório
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from bot import (
    format_raw_output,
    clean_accessible_text,
    clean_accessible_sources,
    mock_check,
    call_backend,
    stream_backend_analysis,
    check_backend_health,
)


def test_format_raw_output_standard():
    data = {
        "claim": "Governo vai confiscar a poupança",
        "verdict": "FAKE",
        "confidence": 0.94,
        "summary": "Afirmação falsa sem respaldo oficial.",
        "reasons": ["Boato antigo reciclado", "Ministério desmentiu"],
        "sources": ["Agência Lupa", "Aos Fatos"],
    }
    result = format_raw_output(data)

    assert "📋 Fato Analisado:" in result
    assert '"Governo vai confiscar a poupança"' in result
    assert "⚖️ Veredito: 🔴 BOATO (FALSO) (94% de certeza)" in result
    assert "📝 Resumo do Julgamento:" in result
    assert "Afirmação falsa sem respaldo oficial." in result
    assert "🔍 Detalhamento por Alegação:" in result
    assert '• "Governo vai confiscar a poupança" ➔ 🔴 Falso (94%)' in result
    assert "🌐 Fontes Consultadas:" in result
    assert "• Agência Lupa" in result
    assert "• Aos Fatos" in result


def test_format_raw_output_with_sub_claims_and_risks():
    data = {
        "claim": "Existe adesivo de Mounjaro por 39 reais que queima gordura",
        "verdict": "FAKE",
        "confidence": 0.98,
        "summary": "Golpe comercial envolvendo medicamento de uso controlado.",
        "reasons": ["Droga é exclusivamente injetável"],
        "sources": ["Anvisa", "Wikipedia"],
        "sub_claims": [
            {
                "statement": "Existe adesivo de Mounjaro",
                "verdict": "FAKE",
                "confidence": 0.99,
                "justification": "Medicamento comercializado apenas em canetas injetáveis.",
            },
            {
                "statement": "Custa 39 reais",
                "verdict": "FAKE",
                "confidence": 0.95,
                "justification": "Preço incompatível com substância autêntica.",
            },
        ],
        "risks_assessment": [
            "Risco de fraude financeira",
            "Risco toxicológico por substância clandestina",
        ],
    }
    result = format_raw_output(data)

    assert "🔍 Detalhamento por Alegação:" in result
    assert '• "Existe adesivo de Mounjaro" ➔ 🔴 Falso (99%)' in result
    assert "└─ Medicamento comercializado apenas em canetas injetáveis." in result
    assert '• "Custa 39 reais" ➔ 🔴 Falso (95%)' in result
    assert "└─ Preço incompatível com substância autêntica." in result
    assert "⚠️ Alertas e Cuidados:" in result
    assert "• Risco de fraude financeira" in result
    assert "• Risco toxicológico por substância clandestina" in result


def test_format_raw_output_strict_no_vector_db_or_technical_jargon():
    """Garante que 'Base Vetorial FactChkBR', 'ChromaDB' e jargões NUNCA apareçam na saída."""
    data = {
        "claim": "Base Vetorial FactChkBR (ChromaDB): Chá de picão cura hepatite C",
        "verdict": "FAKE",
        "confidence": 0.91,
        "summary": "sob o princípio de ônus da prova, afirmações sobre cura milagrosa por ervas são tratadas como provavelmente falsas.",
        "reasons": [
            "Base Vetorial FactChkBR (Similaridade: 89%): Chá cura hepatite",
            "Extração concluída: texto com padrões estilísticos neutros.",
            "Prevalência de checagem oficial: Anvisa não autoriza fitoterápico para este fim.",
        ],
        "sources": [
            "Base Vetorial FactChkBR (ChromaDB)",
            "ChromaDB",
            "vector_cache",
            "Anvisa",
            "Ministério da Saúde",
        ],
    }
    result = format_raw_output(data)

    # Termos proibidos que nunca podem aparecer
    forbidden = [
        "base vetorial", "chromadb", "chroma", "vector", "vetorial",
        "similaridade:", "padrões estilísticos", "ônus da prova", "spacy",
    ]
    res_lower = result.lower()
    for f in forbidden:
        assert f not in res_lower, f"Termo proibido encontrado no resultado: {f}"

    # Deve conter as fontes válidas
    assert "• Anvisa" in result
    assert "• Ministério da Saúde" in result


def test_clean_accessible_sources_fallback():
    """Garante que fontes apenas com termos técnicos retornem fontes oficiais de segurança."""
    sources = ["Base Vetorial FactChkBR (ChromaDB)", "vector_cache"]
    cleaned = clean_accessible_sources(sources)
    assert len(cleaned) >= 1
    assert "Base Vetorial" not in cleaned[0]
    assert "ChromaDB" not in cleaned[0]
    assert any("Ministério da Saúde" in s or "Anvisa" in s for s in cleaned)


def test_format_raw_output_error():
    data = {"error": "Não foi possível conectar ao back-end em 'http://localhost:8000'"}
    result = format_raw_output(data)
    assert "⚠️ Não foi possível concluir a análise" in result
    assert "Não foi possível conectar ao back-end" in result


def test_mock_check_detection():
    fake_res = mock_check("Urgente! Repasse essa cura milagrosa de adesivo com Mounjaro")
    assert fake_res["verdict"] == "FAKE"
    assert fake_res["confidence"] >= 0.90
    assert len(fake_res["sources"]) > 0
    assert len(fake_res["sub_claims"]) >= 1

    true_res = mock_check("Ministério da Saúde divulga calendário nacional de vacinação para 2026")
    assert true_res["verdict"] == "VERDADEIRO"
    assert true_res["confidence"] >= 0.80
    assert len(true_res["sub_claims"]) >= 1


@pytest.mark.asyncio
async def test_call_backend_mock_mode():
    with patch("bot.USE_MOCK", True):
        res = await call_backend("Texto qualquer para mock")
        assert "verdict" in res
        assert "confidence" in res


@pytest.mark.asyncio
async def test_call_backend_http_success():
    expected_response = {
        "claim": "Adesivo de Mounjaro",
        "verdict": "FAKE",
        "confidence": 0.97,
        "summary": "Não existe registro de adesivo.",
        "reasons": ["Incompatibilidade farmacológica"],
        "sources": ["Anvisa"],
    }

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = expected_response

    mock_client_instance = AsyncMock()
    mock_client_instance.post.return_value = mock_resp
    mock_client_instance.__aenter__.return_value = mock_client_instance
    mock_client_instance.__aexit__.return_value = None

    with patch("bot.USE_MOCK", False), patch("bot.httpx.AsyncClient", return_value=mock_client_instance):
        result = await call_backend(
            "Existe adesivo de Mounjaro? Veja em https://exemplo.com/golpe",
            user_id=123,
            chat_id=456,
        )

        assert result == expected_response
        mock_client_instance.post.assert_called_once()
        call_kwargs = mock_client_instance.post.call_args[1]
        assert call_kwargs["json"]["text"] == "Existe adesivo de Mounjaro? Veja em https://exemplo.com/golpe"
        assert call_kwargs["json"]["urls"] == ["https://exemplo.com/golpe"]
        assert call_kwargs["json"]["user_id"] == 123
        assert call_kwargs["json"]["chat_id"] == 456


@pytest.mark.asyncio
async def test_call_backend_connection_error():
    import httpx

    mock_client_instance = AsyncMock()
    mock_client_instance.post.side_effect = httpx.ConnectError("Connection refused")
    mock_client_instance.__aenter__.return_value = mock_client_instance
    mock_client_instance.__aexit__.return_value = None

    with patch("bot.USE_MOCK", False), patch("bot.httpx.AsyncClient", return_value=mock_client_instance):
        result = await call_backend("Qualquer texto")
        assert "error" in result
        assert "Não foi possível conectar ao back-end" in result["error"]


@pytest.mark.asyncio
async def test_check_backend_health():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "status": "ok",
        "version": "1.0.0",
        "active_analyzers": ["claim_extractor", "fact_check_api", "llm_judge"],
    }

    mock_client_instance = AsyncMock()
    mock_client_instance.get.return_value = mock_resp
    mock_client_instance.__aenter__.return_value = mock_client_instance
    mock_client_instance.__aexit__.return_value = None

    with patch("bot.httpx.AsyncClient", return_value=mock_client_instance):
        health = await check_backend_health()
        assert health["status"] == "ok"
        assert health["version"] == "1.0.0"
        assert "latency_ms" in health
        assert len(health["active_analyzers"]) == 3


@pytest.mark.asyncio
async def test_stream_backend_analysis_mock():
    mock_msg = AsyncMock()
    with patch("bot.USE_MOCK", True):
        res = await stream_backend_analysis("Adesivo de Mounjaro emagrece", mock_msg)
        assert res["verdict"] == "FAKE"
        assert mock_msg.edit_text.call_count >= 1

