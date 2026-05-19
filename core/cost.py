# Preços em USD por 1M tokens (maio/2025)
_PRICING: dict[str, dict[str, float]] = {
    # ── Anthropic ─────────────────────────────────────────────────────────────
    "claude-sonnet-4-6": {
        "input":       3.00,
        "output":     15.00,
        "cache_write": 3.75,
        "cache_read":  0.30,
    },
    "claude-haiku-4-5-20251001": {
        "input":       1.00,
        "output":      5.00,
        "cache_write": 1.25,
        "cache_read":  0.10,
    },
    # ── OpenAI ────────────────────────────────────────────────────────────────
    # Cache automático (sem cache_write premium); cache_read = cached input price
    "gpt-5.1": {
        "input":       1.25,
        "output":     10.00,
        "cache_write": 1.25,   # mesmo que input (sem sobretaxa)
        "cache_read":  0.125,
    },
    "gpt-5-mini": {
        "input":       0.25,
        "output":      2.00,
        "cache_write": 0.25,
        "cache_read":  0.025,
    },
    # ── Google Gemini ─────────────────────────────────────────────────────────
    # Preços para prompts > 200k tokens (pior caso); armazenamento de cache
    # (~$1/MTok/hora para Flash, ~$4.50/MTok/hora para Pro) não incluído aqui.
    "gemini-2.5-flash": {
        "input":       0.30,
        "output":      2.50,
        "cache_write": 0.03,
        "cache_read":  0.03,
    },
    "gemini-2.5-pro": {
        "input":       2.50,
        "output":     15.00,
        "cache_write": 0.25,
        "cache_read":  0.25,
    },
}

_DEFAULT_PRICING = _PRICING["claude-haiku-4-5-20251001"]

# Taxa de câmbio fixa para estimativa (não é financeiramente precisa)
USD_TO_BRL: float = 5.70

# Modelos equivalentes por caso de uso
# (chave = modelo Claude usado, valor = [modelo_openai, modelo_gemini])
EQUIVALENCIAS: dict[str, tuple[str, str]] = {
    "claude-sonnet-4-6":          ("gpt-5.1",    "gemini-2.5-flash"),
    "claude-haiku-4-5-20251001":  ("gpt-5-mini", "gemini-2.5-flash"),
}

# Rótulos de exibição
LABELS: dict[str, str] = {
    "claude-sonnet-4-6":         "Sonnet 4.6",
    "claude-haiku-4-5-20251001": "Haiku 4.5",
    "gpt-5.1":                   "GPT-5.1",
    "gpt-5-mini":                "GPT-5 mini",
    "gemini-2.5-flash":          "Gemini 2.5 Flash",
    "gemini-2.5-pro":            "Gemini 2.5 Pro",
}


def calcular_custo_usd(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_creation_tokens: int = 0,
    cache_read_tokens: int = 0,
) -> float:
    p = _PRICING.get(model, _DEFAULT_PRICING)
    return (
        input_tokens            * p["input"]
        + output_tokens         * p["output"]
        + cache_creation_tokens * p["cache_write"]
        + cache_read_tokens     * p["cache_read"]
    ) / 1_000_000


def custo_brl(cost_usd: float) -> float:
    return cost_usd * USD_TO_BRL


def comparar_provedores(by_model: dict[str, dict]) -> list[dict]:
    """Retorna lista de linhas para a tabela comparativa de provedores.

    Cada linha: {uso, modelo_anthropic, modelo_openai, modelo_gemini,
                 custo_anthropic, custo_openai, custo_gemini}

    `by_model` é o dict session_usage["by_model"]:
        {"claude-haiku-4-5-20251001": {tokens...}, "claude-sonnet-4-6": {tokens...}}
    """
    linhas = []
    for claude_model, tokens in by_model.items():
        if not any(tokens.values()):
            continue
        eq_openai, eq_gemini = EQUIVALENCIAS.get(
            claude_model, ("gpt-5.1", "gemini-2.5-flash")
        )
        def _custo(model):
            return calcular_custo_usd(
                model,
                tokens.get("input_tokens", 0),
                tokens.get("output_tokens", 0),
                tokens.get("cache_creation_tokens", 0),
                tokens.get("cache_read_tokens", 0),
            )
        linhas.append({
            "uso":              "Extração" if "sonnet" in claude_model else "Chat",
            "modelo_anthropic": LABELS[claude_model],
            "modelo_openai":    LABELS[eq_openai],
            "modelo_gemini":    LABELS[eq_gemini],
            "custo_anthropic":  _custo(claude_model),
            "custo_openai":     _custo(eq_openai),
            "custo_gemini":     _custo(eq_gemini),
        })
    return linhas
