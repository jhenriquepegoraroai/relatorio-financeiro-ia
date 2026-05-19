# Preços Anthropic em USD por 1M tokens (maio/2025)
_PRICING: dict[str, dict[str, float]] = {
    "claude-sonnet-4-6": {
        "input":       3.00,
        "output":     15.00,
        "cache_write": 3.75,  # +25% sobre input
        "cache_read":  0.30,  # 10% do input
    },
    "claude-haiku-4-5-20251001": {
        "input":       0.80,
        "output":      4.00,
        "cache_write": 1.00,
        "cache_read":  0.08,
    },
}

_DEFAULT_PRICING = _PRICING["claude-haiku-4-5-20251001"]

# Taxa de câmbio fixa para estimativa (não é financeiramente precisa)
USD_TO_BRL: float = 5.70


def calcular_custo_usd(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_creation_tokens: int = 0,
    cache_read_tokens: int = 0,
) -> float:
    p = _PRICING.get(model, _DEFAULT_PRICING)
    return (
        input_tokens       * p["input"]
        + output_tokens    * p["output"]
        + cache_creation_tokens * p["cache_write"]
        + cache_read_tokens     * p["cache_read"]
    ) / 1_000_000


def custo_brl(cost_usd: float) -> float:
    return cost_usd * USD_TO_BRL
