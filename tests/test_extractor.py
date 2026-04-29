import io
from unittest.mock import MagicMock, patch

import openpyxl

from core.extractor import extrair_texto, extrair_texto_pdf, extrair_texto_xlsx


def _mock_pdf(pages_text: list[str]):
    mock_page = [MagicMock(extract_text=MagicMock(return_value=t)) for t in pages_text]
    mock_pdf = MagicMock()
    mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
    mock_pdf.__exit__ = MagicMock(return_value=False)
    mock_pdf.pages = mock_page
    return mock_pdf


def test_extrair_texto_caminho(tmp_path):
    fake_pdf = tmp_path / "test.pdf"
    fake_pdf.write_bytes(b"")
    with patch("core.extractor.pdfplumber.open", return_value=_mock_pdf(["página um", "página dois"])):
        result = extrair_texto_pdf(str(fake_pdf))
    assert result == "página um\npágina dois"


def test_extrair_texto_upload():
    upload = MagicMock()
    upload.read.return_value = b""
    with patch("core.extractor.pdfplumber.open", return_value=_mock_pdf(["conteúdo upload"])):
        result = extrair_texto_pdf(upload)
    assert result == "conteúdo upload"


def test_extrair_texto_pagina_vazia():
    with patch("core.extractor.pdfplumber.open", return_value=_mock_pdf([None, "segunda"])):
        result = extrair_texto_pdf("/fake/path.pdf")
    assert result == "segunda"


# ─── XLSX ─────────────────────────────────────────────────────────────────────

def _criar_xlsx(tmp_path, dados: dict[str, list[list]]) -> str:
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for nome_aba, linhas in dados.items():
        ws = wb.create_sheet(nome_aba)
        for linha in linhas:
            ws.append(linha)
    path = tmp_path / "test.xlsx"
    wb.save(path)
    return str(path)


def test_extrair_texto_xlsx_caminho(tmp_path):
    path = _criar_xlsx(tmp_path, {"Balancete": [["Conta", "Valor"], ["Receitas", 1000]]})
    result = extrair_texto_xlsx(path)
    assert "=== Planilha: Balancete ===" in result
    assert "Conta | Valor" in result
    assert "Receitas | 1000" in result


def test_extrair_texto_xlsx_multiplas_abas(tmp_path):
    path = _criar_xlsx(tmp_path, {
        "Receitas": [["item", "valor"], ["taxa", 500]],
        "Despesas": [["item", "valor"], ["manutenção", 300]],
    })
    result = extrair_texto_xlsx(path)
    assert "=== Planilha: Receitas ===" in result
    assert "=== Planilha: Despesas ===" in result


def test_extrair_texto_xlsx_ignora_linhas_vazias(tmp_path):
    path = _criar_xlsx(tmp_path, {"Aba": [["A", "B"], [None, None], ["C", "D"]]})
    result = extrair_texto_xlsx(path)
    lines = [l for l in result.splitlines() if "|" in l]
    assert len(lines) == 2


def test_dispatcher_roteia_xlsx(tmp_path):
    path = _criar_xlsx(tmp_path, {"S": [["x", "1"]]})
    result = extrair_texto(path)
    assert "=== Planilha: S ===" in result


def test_dispatcher_roteia_pdf():
    with patch("core.extractor.pdfplumber.open", return_value=_mock_pdf(["texto pdf"])):
        result = extrair_texto("/arquivo.pdf")
    assert result == "texto pdf"
