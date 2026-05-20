"""Implementações de gerar_resumo para OpenAI e Google Gemini."""
from __future__ import annotations

import json
import re
from pathlib import Path

from core.models import ResumoFinanceiro

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


def _load_prompt(name: str) -> str:
    return (_PROMPTS_DIR / name).read_text(encoding="utf-8")


def _parse_resumo(texto: str) -> list[ResumoFinanceiro]:
    texto = re.sub(r"^```[a-z]*\n?", "", texto.strip())
    texto = re.sub(r"\n?```$", "", texto)
    data = json.loads(texto)
    itens = data.get("resumos", [data]) if isinstance(data, dict) else data
    return [ResumoFinanceiro.model_validate(item) for item in itens]


def gerar_resumo_openai(
    conteudo: str,
    api_key: str,
    model: str,
    usage_out: dict | None = None,
) -> list[ResumoFinanceiro]:
    from openai import OpenAI

    system = _load_prompt("resumo.txt")
    client = OpenAI(api_key=api_key)

    for attempt in range(2):
        response = client.chat.completions.create(
            model=model,
            max_tokens=16384,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": conteudo},
            ],
        )
        if usage_out is not None:
            u = response.usage
            cached = 0
            if hasattr(u, "prompt_tokens_details") and u.prompt_tokens_details:
                cached = getattr(u.prompt_tokens_details, "cached_tokens", 0) or 0
            usage_out["input_tokens"]          = usage_out.get("input_tokens", 0)  + (u.prompt_tokens or 0)
            usage_out["output_tokens"]         = usage_out.get("output_tokens", 0) + (u.completion_tokens or 0)
            usage_out["cache_creation_tokens"] = 0
            usage_out["cache_read_tokens"]     = usage_out.get("cache_read_tokens", 0) + cached

        texto = response.choices[0].message.content or ""
        try:
            return _parse_resumo(texto)
        except (json.JSONDecodeError, ValueError):
            if attempt == 1:
                raise ValueError(f"OpenAI retornou JSON inválido.\nTrecho: {texto[:300]}")
    return []


def gerar_resumo_gemini(
    conteudo: str,
    api_key: str,
    model: str,
    usage_out: dict | None = None,
) -> list[ResumoFinanceiro]:
    from google import genai
    from google.genai import types

    system = _load_prompt("resumo.txt")
    client = genai.Client(api_key=api_key)

    for attempt in range(2):
        response = client.models.generate_content(
            model=model,
            contents=conteudo,
            config=types.GenerateContentConfig(
                system_instruction=system,
                response_mime_type="application/json",
                max_output_tokens=16384,
            ),
        )
        if usage_out is not None and response.usage_metadata:
            u = response.usage_metadata
            usage_out["input_tokens"]          = usage_out.get("input_tokens", 0)  + (u.prompt_token_count or 0)
            usage_out["output_tokens"]         = usage_out.get("output_tokens", 0) + (u.candidates_token_count or 0)
            usage_out["cache_creation_tokens"] = 0
            usage_out["cache_read_tokens"]     = 0

        texto = response.text or ""
        try:
            return _parse_resumo(texto)
        except (json.JSONDecodeError, ValueError):
            if attempt == 1:
                raise ValueError(f"Gemini retornou JSON inválido.\nTrecho: {texto[:300]}")
    return []
