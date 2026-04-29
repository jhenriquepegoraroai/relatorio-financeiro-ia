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
