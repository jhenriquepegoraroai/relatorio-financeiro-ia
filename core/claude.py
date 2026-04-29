import json
import re
from pathlib import Path

import anthropic

from config import settings
from core.models import ResumoFinanceiro

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


def _load_prompt(name: str) -> str:
    return (_PROMPTS_DIR / name).read_text(encoding="utf-8")


def gerar_resumo(api_key: str, conteudo: str) -> list[ResumoFinanceiro]:
    client = anthropic.Anthropic(api_key=api_key)
    system = _load_prompt("resumo.txt")

    for attempt in range(2):
        response = client.messages.create(
            model=settings.claude_model,
            max_tokens=settings.max_tokens_resumo,
            system=system,
            messages=[{"role": "user", "content": conteudo}],
        )
        if response.stop_reason == "max_tokens":
            raise ValueError(
                "O relatório é muito extenso: o limite de tokens foi atingido antes de "
                "o JSON ser concluído. Tente enviar menos arquivos por vez."
            )
        texto = response.content[0].text.strip()
        texto = re.sub(r"^```[a-z]*\n?", "", texto)
        texto = re.sub(r"\n?```$", "", texto)
        try:
            data = json.loads(texto)
            itens = data.get("resumos", [data]) if isinstance(data, dict) else data
            return [ResumoFinanceiro.model_validate(item) for item in itens]
        except (json.JSONDecodeError, ValueError):
            if attempt == 1:
                raise ValueError(
                    f"Claude retornou JSON inválido após 2 tentativas.\n"
                    f"Trecho recebido: {texto[:300]}"
                )


_TIPOS_GRAFICO = {
    "receitas", "despesas", "inadimplencia",
    "receitas_vs_despesas", "despesas_comparativo", "despesas_periodo",
    "pizza", "comparacao",
}

_SYSTEM_CLASSIFICAR = """\
Você é um classificador de gráficos financeiros. Dado o pedido do usuário, responda APENAS com JSON válido:
{"tipo": "...", "categoria": null, "periodo": null, "orientacao": null}

Valores possíveis para "tipo":
  receitas              → gráfico de receitas de um período
  despesas              → composição geral das despesas de um período
  inadimplencia         → inadimplência
  receitas_vs_despesas  → comparar receitas com despesas ao longo do tempo
  despesas_comparativo  → comparar categorias de despesas entre períodos
  despesas_periodo      → detalhar despesas de um mês específico
  pizza                 → gráfico de pizza de uma categoria específica (ex: "fundo de reserva")
  comparacao            → comparativo geral entre períodos

"categoria": nome da categoria financeira mencionada (ex: "fundo de reserva"), ou null se não mencionada.
"periodo": mês/ano mencionado (ex: "janeiro", "março/2026"), ou null se não mencionado.
"orientacao": "vertical" se o usuário pedir barras em pé/verticais, "horizontal" se pedir deitadas/na horizontal, null se não especificado.

Interprete perguntas retóricas como pedidos: "você consegue gerar um gráfico na vertical?" → tipo de gráfico adequado + orientacao "vertical".

Responda SOMENTE com o JSON, sem explicações.
"""

def classificar_grafico(api_key: str, mensagem: str) -> dict:
    """Retorna {"tipo": str|None, "categoria": str|None, "periodo": str|None, "orientacao": str|None}."""
    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=settings.claude_model,
        max_tokens=80,
        system=_SYSTEM_CLASSIFICAR,
        messages=[{"role": "user", "content": mensagem}],
    )
    texto = response.content[0].text.strip()
    texto = re.sub(r"^```[a-z]*\n?", "", texto)
    texto = re.sub(r"\n?```$", "", texto)
    try:
        data = json.loads(texto)
        tipo = (data.get("tipo") or "").lower()
        orientacao = (data.get("orientacao") or "").lower() or None
        if orientacao not in ("vertical", "horizontal", None):
            orientacao = None
        return {
            "tipo":       tipo if tipo in _TIPOS_GRAFICO else None,
            "categoria":  data.get("categoria"),
            "periodo":    data.get("periodo"),
            "orientacao": orientacao,
        }
    except (json.JSONDecodeError, AttributeError):
        return {"tipo": None, "categoria": None, "periodo": None, "orientacao": None}


def stream_chat(api_key: str, dados: str, historico: list[dict], mensagem: str):
    client = anthropic.Anthropic(api_key=api_key)
    system = _load_prompt("chat.txt").format(dados=dados)
    mensagens = [
        {"role": m["role"], "content": m["content"]}
        for m in historico
        if m.get("content")
    ] + [{"role": "user", "content": mensagem}]
    with client.messages.stream(
        model=settings.claude_model,
        max_tokens=settings.max_tokens_chat,
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        messages=mensagens,
    ) as stream:
        for text in stream.text_stream:
            yield text
