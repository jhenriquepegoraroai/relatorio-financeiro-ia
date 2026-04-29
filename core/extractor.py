import io
import os

import openpyxl
import pdfplumber


def extrair_texto(source) -> str:
    """Dispatcher: detecta o tipo pelo nome/extensão e chama o extrator correto."""
    nome = source if isinstance(source, (str, os.PathLike)) else getattr(source, "name", "")
    if str(nome).lower().endswith(".xlsx"):
        return extrair_texto_xlsx(source)
    return extrair_texto_pdf(source)


def extrair_texto_pdf(source) -> str:
    """Aceita caminho (str/Path) ou objeto de upload do Streamlit."""
    if isinstance(source, (str, os.PathLike)):
        ctx = pdfplumber.open(source)
    else:
        ctx = pdfplumber.open(io.BytesIO(source.read()))
    with ctx as pdf:
        return "\n".join(
            page.extract_text() or "" for page in pdf.pages
        ).strip()


def extrair_texto_xlsx(source) -> str:
    """Lê todas as abas do XLSX e retorna o conteúdo como texto estruturado."""
    if isinstance(source, (str, os.PathLike)):
        wb = openpyxl.load_workbook(source, read_only=True, data_only=True)
    else:
        wb = openpyxl.load_workbook(io.BytesIO(source.read()), read_only=True, data_only=True)

    partes = []
    for nome_aba in wb.sheetnames:
        ws = wb[nome_aba]
        partes.append(f"=== Planilha: {nome_aba} ===")
        for row in ws.iter_rows(values_only=True):
            if any(cell is not None for cell in row):
                partes.append(" | ".join("" if cell is None else str(cell) for cell in row))
    wb.close()
    return "\n".join(partes).strip()
