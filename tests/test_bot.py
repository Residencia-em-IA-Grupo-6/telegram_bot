import sys
from pathlib import Path

# Garante importação do bot.py a partir da raiz do repositório
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from bot import (
    format_raw_output,
    mock_check,
    call_backend,
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

    assert "Fato/Texto: Governo vai confiscar a poupança" in result
    assert "Veredito: 🔴 FAKE" in result
    assert "Confiança: 94%" in result
    assert "Resumo: Afirmação falsa sem respaldo oficial." in result
    assert "Motivos:" in result
    assert "- Boato antigo reciclado" in result
    assert "Fontes:" in result
    assert "- Agência Lupa" in result


def test_format_raw_output_with_sub_claims_and_risks():
    data = {
        "claim": "Existe adesivo de Mounjaro por 39 reais que queima gordura",
        "verdict": "FAKE",
        "confidence": 0.98,
        "summary": "Golpe comercial envolvendo medicamento de uso controlado.",
        "reasons": ["Droga é exclusivamente injetável"],
        "sources": ["Anvisa", "Wikipedia"],
        "sub_claims": [
            {"statement": "Existe adesivo de Mounjaro", "verdict": "FAKE", "confidence": 0.99},
            {"statement": "Custa 39 reais", "verdict": "FAKE", "confidence": 0.95},
        ],
        "risks_assessment": [
            "Risco de fraude financeira",
            "Risco toxicológico por substância clandestina",
        ],
    }
    result = format_raw_output(data)

    assert "Detalhamento por Alegação:" in result
    assert '- "Existe adesivo de Mounjaro" -> 🔴 FAKE (99%)' in result
    assert "Avaliação de Riscos:" in result
    assert "- Risco de fraude financeira" in result


def test_format_raw_output_error():
    data = {"error": "Não foi possível conectar ao back-end em 'http://localhost:8000'"}
    result = format_raw_output(data)
    assert "[ERRO]" in result
    assert "Não foi possível conectar ao back-end" in result


def test_mock_check_detection():
    fake_res = mock_check("Urgente! Repasse essa cura milagrosa de adesivo com Mounjaro")
    assert fake_res["verdict"] == "FAKE"
    assert fake_res["confidence"] >= 0.90
    assert len(fake_res["sources"]) > 0

    true_res = mock_check("Ministério da Saúde divulga calendário nacional de vacinação para 2026")
    assert true_res["verdict"] == "VERDADEIRO"
    assert true_res["confidence"] >= 0.80


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
