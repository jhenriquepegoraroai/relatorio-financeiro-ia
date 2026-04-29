import json
from unittest.mock import MagicMock, patch

import pytest

from core.claude import gerar_resumo
from core.models import ResumoFinanceiro

_RESUMO_VALIDO = {
    "periodo": "Fevereiro/2024",
    "condominio": "Condomínio Teste",
    "panorama": "O mês apresentou superávit.",
    "indicadores": {
        "receita_total": 30000.0,
        "despesa_total": 28000.0,
        "resultado": 2000.0,
        "inadimplencia_total": 1500.0,
    },
    "receitas": [{"descricao": "Taxa condominial", "valor": 30000.0}],
    "despesas": [{"descricao": "Manutenção", "valor": 28000.0}],
    "inadimplencia": [{"conta": "Unidade 101", "valor": 1500.0}],
    "alertas": ["Inadimplência acima de 5%"],
}


def _mock_response(texto: str):
    mock = MagicMock()
    mock.content = [MagicMock(text=texto)]
    return mock


def test_gerar_resumo_retorna_lista_com_um_periodo(tmp_path):
    with patch("core.claude.anthropic.Anthropic") as mock_client:
        mock_client.return_value.messages.create.return_value = _mock_response(
            json.dumps({"resumos": [_RESUMO_VALIDO]})
        )
        result = gerar_resumo("fake-key", "balancete text\nconta text")

    assert isinstance(result, list)
    assert len(result) == 1
    assert isinstance(result[0], ResumoFinanceiro)
    assert result[0].periodo == "Fevereiro/2024"
    assert result[0].indicadores.resultado == 2000.0


def test_gerar_resumo_retorna_multiplos_periodos(tmp_path):
    resumo2 = {**_RESUMO_VALIDO, "periodo": "Março/2024"}
    with patch("core.claude.anthropic.Anthropic") as mock_client:
        mock_client.return_value.messages.create.return_value = _mock_response(
            json.dumps({"resumos": [_RESUMO_VALIDO, resumo2]})
        )
        result = gerar_resumo("fake-key", "dois meses de documentos")

    assert len(result) == 2
    assert result[1].periodo == "Março/2024"


def test_gerar_resumo_remove_bloco_markdown(tmp_path):
    texto_com_markdown = "```json\n" + json.dumps({"resumos": [_RESUMO_VALIDO]}) + "\n```"
    with patch("core.claude.anthropic.Anthropic") as mock_client:
        mock_client.return_value.messages.create.return_value = _mock_response(
            texto_com_markdown
        )
        result = gerar_resumo("fake-key", "bal\ncc")

    assert result[0].condominio == "Condomínio Teste"


def test_gerar_resumo_levanta_erro_apos_retries():
    with patch("core.claude.anthropic.Anthropic") as mock_client:
        mock_client.return_value.messages.create.return_value = _mock_response(
            "não é json válido"
        )
        with pytest.raises(ValueError, match="JSON inválido"):
            gerar_resumo("fake-key", "bal\ncc")
