from pydantic import BaseModel


class ItemFinanceiro(BaseModel):
    descricao: str
    valor: float


class ItemInadimplencia(BaseModel):
    conta: str
    valor: float


class Indicadores(BaseModel):
    receita_total: float
    despesa_total: float
    resultado: float
    inadimplencia_total: float


class ResumoFinanceiro(BaseModel):
    periodo: str
    condominio: str
    panorama: str
    indicadores: Indicadores
    receitas: list[ItemFinanceiro]
    despesas: list[ItemFinanceiro]
    inadimplencia: list[ItemInadimplencia]
    alertas: list[str]
