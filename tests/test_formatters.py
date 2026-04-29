from core.formatters import brl


def test_brl_inteiro():
    assert brl(1000.0) == "R$ 1.000,00"


def test_brl_centavos():
    assert brl(28010.50) == "R$ 28.010,50"


def test_brl_negativo():
    assert brl(-500.75) == "R$ -500,75"


def test_brl_zero():
    assert brl(0.0) == "R$ 0,00"
