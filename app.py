"""
POC — Relatório Financeiro por IA
Uso: streamlit run app.py
"""

import re
import streamlit as st
import streamlit.components.v1 as components
import plotly.express as px
import plotly.graph_objects as go

from config import settings
from core.claude import gerar_resumo, stream_chat, classificar_grafico, strip_code_blocks
from core.db_log import registrar_log, listar_logs
from core.cost import calcular_custo_usd, custo_brl, USD_TO_BRL, comparar_provedores
from core.extractor import (
    extrair_texto, extrair_de_databricks, extrair_balancete_compacto,
    listar_referencias, _databricks_configurado, descrever_colunas_balancete,
    aguardar_cluster, _is_erro_transiente,
    get_recent_sql, clear_recent_sql,
)
from core.formatters import brl
from core.models import ResumoFinanceiro

st.set_page_config(
    page_title="Relatório Financeiro com IA",
    page_icon="🏢",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─── Design System: Heritage Corporate ───────────────────────────────────────

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Work+Sans:wght@500;600;700&family=Inter:wght@400;500;600&display=swap');

/* ── Fontes ── */
h1, h2, h3 { font-family: 'Work Sans', sans-serif !important; color: #C5002D !important; }
html, body, .stMarkdown, p, input, textarea, label, .stChatMessage, table, td, th, li {
    font-family: 'Inter', sans-serif !important;
}

/* ── Só esconde o botão Deploy, sem tocar no header ── */
[data-testid="stToolbar"] { visibility: hidden !important; }

/* ── Sidebar ── */
[data-testid="stSidebar"] { background: #ffffff !important; border-right: 2px solid #f0f0f0 !important; }
[data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3 {
    font-family: 'Inter', sans-serif !important; color: #C5002D !important;
    font-size: 0.82rem !important; font-weight: 700 !important;
    text-transform: uppercase; letter-spacing: 0.08em;
}
[data-testid="stSelectbox"] label {
    font-family: 'Inter', sans-serif !important; font-size: 0.82rem !important;
    font-weight: 700 !important; color: #C5002D !important;
    text-transform: uppercase; letter-spacing: 0.08em;
}

/* ── Botão primário ── */
button[data-testid="baseButton-primary"] {
    background: #C5002D !important; color: white !important;
    border: none !important; border-radius: 6px !important;
    font-weight: 600 !important;
}
button[data-testid="baseButton-primary"]:hover { background: #9A001F !important; }

/* ── Métricas como cards ── */
[data-testid="stMetric"] {
    background: white; border: 1px solid #e8e8e8;
    border-top: 3px solid #C5002D; border-radius: 8px;
    padding: 12px 14px !important; box-shadow: 0 1px 4px rgba(0,0,0,0.06);
}
[data-testid="stMetricLabel"] {
    font-size: 0.72rem !important; font-weight: 600 !important;
    color: #888 !important; text-transform: uppercase; letter-spacing: 0.05em;
}

/* ── Expanders ── */
[data-testid="stExpander"] { border: 1px solid #e8e8e8 !important; border-radius: 8px !important; }
[data-testid="stExpander"] summary {
    font-weight: 600 !important; font-size: 0.85rem !important;
    background: #f8f8f8 !important;
}
[data-testid="stExpander"] summary:hover { background: #FDEEF1 !important; color: #C5002D !important; }

/* ── Chat input ── */
[data-testid="stChatInput"] textarea:focus {
    border-color: #C5002D !important;
    box-shadow: 0 0 0 2px rgba(197,0,45,0.1) !important;
}
</style>
""", unsafe_allow_html=True)

# ─── Auto-scroll ──────────────────────────────────────────────────────────────

_SCROLL_JS = """
<script>
(function() {
    var SELECTORS = ['[data-testid="stAppViewContainer"]', 'section.main', '.main'];
    function getTarget() {
        for (var i = 0; i < SELECTORS.length; i++) {
            var el = window.parent.document.querySelector(SELECTORS[i]);
            if (el) return el;
        }
        return null;
    }
    function scrollDown(t) {
        if (t) t.scrollTop = t.scrollHeight;
        else window.parent.scrollTo(0, window.parent.document.body.scrollHeight);
    }
    var target = getTarget();
    scrollDown(target);
    if (target) {
        var obs = new MutationObserver(function() { scrollDown(target); });
        obs.observe(target, { childList: true, subtree: true, characterData: true });
        setTimeout(function() { obs.disconnect(); }, 15000);
    }
})();
</script>
"""

# ─── API key ──────────────────────────────────────────────────────────────────

def _api_key() -> str:
    key = settings.anthropic_api_key
    if not key:
        st.error("ANTHROPIC_API_KEY não encontrada. Adicione ao arquivo .env e reinicie o app.")
        st.stop()
    return key

# ─── Ordenação de períodos ────────────────────────────────────────────────────

_MESES_PT = {
    "jan": 1, "janeiro": 1, "fev": 2, "fevereiro": 2,
    "mar": 3, "março": 3, "marco": 3, "abr": 4, "abril": 4,
    "mai": 5, "maio": 5, "jun": 6, "junho": 6,
    "jul": 7, "julho": 7, "ago": 8, "agosto": 8,
    "set": 9, "setembro": 9, "out": 10, "outubro": 10,
    "nov": 11, "novembro": 11, "dez": 12, "dezembro": 12,
}

def _sort_key(r: ResumoFinanceiro) -> tuple[int, int]:
    texto = r.periodo.lower()
    mes = next((n for nome, n in _MESES_PT.items() if nome in texto), 0)
    m = re.search(r'\d{2,4}', texto)
    ano = int(m.group()) if m else 0
    if ano < 100:
        ano += 2000
    return (ano, mes)

# ─── Alinhamento de itens entre períodos ─────────────────────────────────────

def _alinhar(listas: list, key_fn) -> dict[str, list[float]]:
    """Retorna {nome: [valor_p1, valor_p2, ...]} alinhado entre períodos."""
    seen: set = set()
    ordem: list = []
    for lst in listas:
        for item in lst:
            k = key_fn(item)
            if k not in seen:
                ordem.append(k)
                seen.add(k)
    return {
        k: [next((item.valor for item in lst if key_fn(item) == k), 0.0) for lst in listas]
        for k in ordem
    }

# ─── Helpers de estilo HTML ───────────────────────────────────────────────────

_C = {
    "titulo":    "background:#C5002D;color:white;font-weight:bold;text-align:center;padding:10px 8px;font-size:1.05em;",
    "subtitulo": "background:#9A001F;color:white;text-align:center;padding:4px 8px;font-size:0.88em;",
    "sec_blu":   "background:#9A001F;color:white;font-weight:bold;padding:5px 10px;",
    "sec_red":   "background:#C5002D;color:white;font-weight:bold;padding:5px 10px;",
    "col_hdr":   "background:#C5002D;color:white;font-weight:bold;padding:5px 10px;text-align:right;white-space:nowrap;",
    "col_hdr_l": "background:#C5002D;color:white;font-weight:bold;padding:5px 10px;text-align:left;",
    "tot":       "background:#e2e2e2;font-weight:bold;padding:5px 10px;text-align:right;",
    "tot_l":     "background:#e2e2e2;font-weight:bold;padding:5px 10px;text-align:left;",
    "res":       "background:#C5002D;color:white;font-weight:bold;padding:5px 10px;text-align:right;",
    "res_l":     "background:#C5002D;color:white;font-weight:bold;padding:5px 10px;text-align:left;",
    "d0":        "background:#ffffff;padding:4px 10px;text-align:right;border-bottom:1px solid #e1bebf;",
    "d0l":       "background:#ffffff;padding:4px 10px;text-align:left;border-bottom:1px solid #e1bebf;",
    "d1":        "background:#f3f3f3;padding:4px 10px;text-align:right;border-bottom:1px solid #e1bebf;",
    "d1l":       "background:#f3f3f3;padding:4px 10px;text-align:left;border-bottom:1px solid #e1bebf;",
}

def _var_css(v: float) -> str:
    if v > 0: return "color:#006d2f;font-weight:bold;"
    if v < 0: return "color:#ba1a1a;font-weight:bold;"
    return ""

def _fmt_var(v: float) -> str:
    return ("+" if v > 0 else "") + brl(v)

def _fmt_pct(v: float) -> str:
    return ("+" if v > 0 else "") + f"{v:.1f}%"

def _th(t, s="col_hdr"): return f'<th style="{_C[s]}">{t}</th>'
def _td(t, s, extra=""): return f'<td style="{_C[s]}{extra}">{t}</td>'

def _row_span(texto, n, s):
    return f'<tr><td colspan="{n}" style="{_C[s]}">{texto}</td></tr>'

def _row_headers(labels, com_var):
    tr = f'<tr>{_th("Categoria","col_hdr_l")}'
    for l in labels: tr += _th(l)
    if com_var: tr += _th("Variação R$") + _th("Var %")
    return tr + "</tr>"

def _row_data(label, vals, com_var, alt=False):
    s = "d1" if alt else "d0"
    tr = f'<tr>{_td(label, s+"l")}'
    for v in vals: tr += _td(brl(v), s)
    if com_var:
        var = vals[-1] - vals[-2]
        pct = (var / vals[-2] * 100) if vals[-2] else 0.0
        css = _var_css(var)
        tr += _td(_fmt_var(var), s, css) + _td(_fmt_pct(pct), s, css)
    return tr + "</tr>"

def _row_total(label, vals, com_var):
    tr = f'<tr>{_td(label,"tot_l")}'
    for v in vals: tr += _td(brl(v), "tot")
    if com_var:
        var = vals[-1] - vals[-2]
        pct = (var / vals[-2] * 100) if vals[-2] else 0.0
        css = _var_css(var)
        tr += _td(_fmt_var(var), "tot", css) + _td(_fmt_pct(pct), "tot", css)
    return tr + "</tr>"

def _row_resultado(label, vals, com_var):
    tr = f'<tr>{_td(label,"res_l")}'
    for v in vals: tr += _td(brl(v), "res")
    if com_var:
        var = vals[-1] - vals[-2]
        pct = (var / vals[-2] * 100) if vals[-2] else 0.0
        tr += _td(_fmt_var(var), "res", "color:white;font-weight:bold;")
        tr += _td(_fmt_pct(pct), "res", "color:white;font-weight:bold;")
    return tr + "</tr>"

def _tabela(inner):
    return (
        '<div style="overflow-x:auto;margin-bottom:12px;">'
        '<table style="min-width:100%;border-collapse:collapse;'
        'font-size:0.83em;font-family:Inter,sans-serif;">'
        + inner + "</table></div>"
    )

# ─── Alertas Proativos ────────────────────────────────────────────────────────

_ALERTA_ESTILO = {
    "critico": ("background:#fff0f0;border-left:5px solid #ba1a1a;", "#ba1a1a"),
    "atencao": ("background:#fff8e1;border-left:5px solid #e65100;", "#e65100"),
    "info":    ("background:#e8f4fd;border-left:5px solid #1565c0;", "#1565c0"),
}

def _alertas_proativos(periodos: list[ResumoFinanceiro]) -> list[dict]:
    alertas = []
    periodos_ord = sorted(periodos, key=_sort_key)
    ultimo = periodos_ord[-1]
    ind = ultimo.indicadores

    if ind.resultado < 0:
        alertas.append({
            "nivel": "critico", "icon": "🚨",
            "titulo": "Déficit Financeiro",
            "detalhe": (
                f"O condomínio encerrou {ultimo.periodo} com resultado negativo de "
                f"{brl(ind.resultado)}. As despesas superam as receitas."
            ),
        })

    if ind.receita_total > 0:
        pct_inad = (ind.inadimplencia_total / ind.receita_total) * 100
        if pct_inad >= 15:
            alertas.append({
                "nivel": "critico", "icon": "⚠️",
                "titulo": "Inadimplência Crítica",
                "detalhe": (
                    f"Inadimplência de {brl(ind.inadimplencia_total)} representa "
                    f"{pct_inad:.1f}% da receita total em {ultimo.periodo}."
                ),
            })
        elif pct_inad >= 5:
            alertas.append({
                "nivel": "atencao", "icon": "⚠️",
                "titulo": "Inadimplência Elevada",
                "detalhe": (
                    f"Inadimplência de {brl(ind.inadimplencia_total)} representa "
                    f"{pct_inad:.1f}% da receita total em {ultimo.periodo}."
                ),
            })

    if len(periodos_ord) >= 2:
        ant = periodos_ord[-2].indicadores

        if ant.despesa_total > 0:
            var_desp = (ind.despesa_total - ant.despesa_total) / ant.despesa_total * 100
            if var_desp >= 15:
                alertas.append({
                    "nivel": "atencao", "icon": "📈",
                    "titulo": "Alta nas Despesas",
                    "detalhe": (
                        f"Despesas cresceram {var_desp:.1f}% entre "
                        f"{periodos_ord[-2].periodo} e {ultimo.periodo} "
                        f"({brl(ant.despesa_total)} → {brl(ind.despesa_total)})."
                    ),
                })

        if ant.receita_total > 0:
            var_rec = (ind.receita_total - ant.receita_total) / ant.receita_total * 100
            if var_rec <= -10:
                alertas.append({
                    "nivel": "atencao", "icon": "📉",
                    "titulo": "Queda na Receita",
                    "detalhe": (
                        f"Receita caiu {abs(var_rec):.1f}% entre "
                        f"{periodos_ord[-2].periodo} e {ultimo.periodo} "
                        f"({brl(ant.receita_total)} → {brl(ind.receita_total)})."
                    ),
                })

    if ind.resultado >= 0 and ind.receita_total > 0:
        margem = ind.resultado / ind.receita_total * 100
        if 0 < margem < 3:
            alertas.append({
                "nivel": "info", "icon": "ℹ️",
                "titulo": "Margem Financeira Estreita",
                "detalhe": (
                    f"Resultado positivo de {brl(ind.resultado)}, mas representa apenas "
                    f"{margem:.1f}% da receita. Pouca folga para imprevistos."
                ),
            })

    return alertas


def _exibir_alertas_proativos(alertas: list[dict]) -> None:
    n = len(alertas)
    n_criticos = sum(1 for a in alertas if a["nivel"] == "critico")
    label = (
        f"🔔 {n} alerta(s) identificado(s)" + (f" — {n_criticos} crítico(s)" if n_criticos else "")
        if n else "✅ Nenhum alerta crítico identificado neste período"
    )
    with st.expander(label, expanded=bool(n)):
        if not alertas:
            st.markdown(
                '<p style="font-family:Inter,sans-serif;color:#2e7d32;font-size:14px;">'
                'Os indicadores financeiros estão dentro dos parâmetros esperados.</p>',
                unsafe_allow_html=True,
            )
            return
        for a in sorted(alertas, key=lambda x: {"critico": 0, "atencao": 1, "info": 2}[x["nivel"]]):
            css, cor = _ALERTA_ESTILO[a["nivel"]]
            st.markdown(
                f'<div style="{css}padding:10px 14px;border-radius:4px;margin-bottom:8px;">'
                f'<span style="color:{cor};font-weight:600;font-family:Inter,sans-serif;font-size:14px;">'
                f'{a["icon"]} {a["titulo"]}</span>'
                f'<p style="margin:4px 0 0;font-size:13px;color:#333;font-family:Inter,sans-serif;">'
                f'{a["detalhe"]}</p></div>',
                unsafe_allow_html=True,
            )

# ─── Relatório comparativo ────────────────────────────────────────────────────

def exibir_relatorio(periodos: list[ResumoFinanceiro]):
    periodos = sorted(periodos, key=_sort_key)
    n = len(periodos)
    labels = [p.periodo for p in periodos]
    cv = n == 2
    nc = 1 + n + (2 if cv else 0)

    nome = periodos[-1].condominio
    faixa = labels[0] if n == 1 else f"{labels[0]} a {labels[-1]}"

    rec_tot  = [p.indicadores.receita_total      for p in periodos]
    desp_tot = [p.indicadores.despesa_total       for p in periodos]
    inad_tot = [p.indicadores.inadimplencia_total for p in periodos]
    rec_ord  = [sum(i.valor for i in p.receitas)  for p in periodos]

    # ── TABELA 1: INDICADORES-CHAVE ───────────────────────────────────────────
    html = (
        _row_span(f"{nome} – BALANCETE RESUMO EXECUTIVO", nc, "titulo")
        + _row_span(f"Período: {faixa}", nc, "subtitulo")
        + _row_span("INDICADORES-CHAVE", nc, "sec_blu")
        + _row_headers(labels, cv)
        + _row_data("🔼 RECEITA TOTAL (Arrecadação)", rec_tot,  cv)
        + _row_data("🔽 DESPESA TOTAL (Ordinária)",   desp_tot, cv, alt=True)
        + _row_data("📊 REC. ORDINÁRIAS",             rec_ord,  cv)
        + _row_data("⚠️ INADIMPLÊNCIA TOTAL",         inad_tot, cv, alt=True)
    )
    st.markdown(_tabela(html), unsafe_allow_html=True)

    # ── TABELA 2: COMPARATIVO MENSAL ──────────────────────────────────────────
    rec_al  = _alinhar([p.receitas  for p in periodos], lambda i: i.descricao)
    desp_al = _alinhar([p.despesas  for p in periodos], lambda i: i.descricao)

    total_rec  = [sum(i.valor for i in p.receitas)  for p in periodos]
    total_desp = [sum(i.valor for i in p.despesas)  for p in periodos]
    resultado  = [r - d for r, d in zip(total_rec, total_desp)]

    html = (
        _row_span("COMPARATIVO MENSAL – RECEITAS E DESPESAS ORDINÁRIAS", nc, "sec_blu")
        + _row_headers(labels, cv)
        + _row_span("RECEITAS ORDINÁRIAS", nc, "sec_blu")
    )
    for i, (desc, vals) in enumerate(rec_al.items()):
        html += _row_data(desc, vals, cv, alt=(i % 2 == 1))
    html += _row_total("TOTAL RECEITAS ORDINÁRIAS", total_rec, cv)

    html += _row_span("DESPESAS ORDINÁRIAS", nc, "sec_red")
    for i, (desc, vals) in enumerate(desp_al.items()):
        html += _row_data(desc, vals, cv, alt=(i % 2 == 1))
    html += _row_total("TOTAL DESPESAS ORDINÁRIAS", total_desp, cv)
    html += _row_resultado("RESULTADO ORDINÁRIO", resultado, cv)

    st.markdown(_tabela(html), unsafe_allow_html=True)

    # ── TABELA 3: INADIMPLÊNCIA ───────────────────────────────────────────────
    inad_al = _alinhar([p.inadimplencia for p in periodos], lambda i: i.conta)
    if inad_al:
        html = (
            _row_span("RESUMO DE INADIMPLÊNCIA", nc, "sec_red")
            + _row_headers(labels, cv)
        )
        for i, (conta, vals) in enumerate(inad_al.items()):
            html += _row_data(conta, vals, cv, alt=(i % 2 == 1))
        html += _row_total("TOTAL INADIMPLÊNCIA", inad_tot, cv)
        st.markdown(_tabela(html), unsafe_allow_html=True)

    # ── ALERTAS PROATIVOS ─────────────────────────────────────────────────────
    _exibir_alertas_proativos(_alertas_proativos(periodos))

    # ── PANORAMA E ALERTAS (expandido por padrão) ─────────────────────────────
    with st.expander("📝 Análise e Alertas", expanded=True):
        for p in periodos:
            if n > 1:
                st.markdown(f"<p style='font-family:Inter,sans-serif;font-weight:600;"
                            f"color:#C5002D;margin:8px 0 4px;'>{p.periodo}</p>",
                            unsafe_allow_html=True)
            # Une panorama (3 bullets) + alertas, limitado a 5 itens no total
            linhas_panorama = [l.lstrip("• ").strip() for l in p.panorama.splitlines() if l.strip()]
            extras = p.alertas[: max(0, 5 - len(linhas_panorama))]
            itens = linhas_panorama + extras
            bullets_html = "".join(
                f'<li style="margin-bottom:5px;">{item}</li>' for item in itens
            )
            st.markdown(
                f'<ul style="font-family:Inter,sans-serif;font-size:14px;line-height:1.7;'
                f'padding-left:20px;margin:4px 0 12px;">'
                f'{bullets_html}</ul>',
                unsafe_allow_html=True,
            )

# ─── Gráficos no chat ────────────────────────────────────────────────────────

# Pré-filtro rápido: se nenhuma dessas palavras aparecer, não chama o Claude.
_CHART_KEYWORDS = {
    "gráfico", "grafico", "chart", "visualiz", "plotar", "plote",
    "gere um", "crie um", "faça um", "faz um", "gera um",
    "compare", "comparar", "comparativo", "evolução", "evolucao",
    "pizza", "barra", "barras", "linha", "linhas",
    "mostre o gráfico", "mostra o gráfico", "mostrar gráfico",
    "exibir gráfico", "exibe gráfico",
}

_MESES = [
    "jan", "fev", "mar", "abr", "mai", "jun",
    "jul", "ago", "set", "out", "nov", "dez",
    "janeiro", "fevereiro", "março", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
]

def _extrair_periodo_da_mensagem(m: str) -> str | None:
    for mes in _MESES:
        if mes in m:
            return mes
    return None

def _detectar_tipo_grafico(msg: str, api_key: str, usage_out: dict | None = None) -> tuple[str | None, str | None, str | None, str | None]:
    """Pré-filtra por keywords e delega ao Claude para entender o contexto.
    Retorna (tipo, periodo_hint, categoria_filtro, orientacao)."""
    m = msg.lower()
    if not any(k in m for k in _CHART_KEYWORDS):
        return None, None, None, None
    resultado = classificar_grafico(api_key, msg, usage_out=usage_out)
    tipo = resultado.get("tipo")
    if tipo is None:
        return None, None, None, None
    periodo_hint = resultado.get("periodo") or (
        _extrair_periodo_da_mensagem(m) if tipo in ("despesas_periodo", "pizza") else None
    )
    return tipo, periodo_hint, resultado.get("categoria"), resultado.get("orientacao")


def _detectar_n_meses_pedido(mensagem: str) -> int | None:
    """Detecta se a mensagem pede dados de mais meses do que os carregados."""
    m = mensagem.lower()
    match = re.search(r'[uú]ltimos?\s+(\d+)\s*m[eê]s', m)
    if match:
        return min(int(match.group(1)), 12)
    if re.search(r'\b(12|doze)\s*m[eê]s|\bano\s*(todo|inteiro|completo|atual)\b|\b(1|um)\s*ano\b', m):
        return 12
    if re.search(r'\b(9|nove)\s*m[eê]s', m):
        return 9
    if re.search(r'\b(6|seis)\s*m[eê]s|\bsemestre\b', m):
        return 6
    if re.search(r'\b(3|tr[eê]s)\s*m[eê]s|\btrimestre\b', m):
        return 3
    return None


_MES_NOME_NUM: dict[str, int] = {
    "jan": 1, "janeiro": 1,
    "fev": 2, "fevereiro": 2,
    "mar": 3, "marco": 3,
    "abr": 4, "abril": 4,
    "mai": 5, "maio": 5,
    "jun": 6, "junho": 6,
    "jul": 7, "julho": 7,
    "ago": 8, "agosto": 8,
    "set": 9, "setembro": 9,
    "out": 10, "outubro": 10,
    "nov": 11, "novembro": 11,
    "dez": 12, "dezembro": 12,
}

def _detectar_periodo_explicito(mensagem: str) -> tuple[str, ...] | None:
    """Detecta 'de <mês> a <mês> de <ano>' e retorna períodos MM/yyyy.

    Exemplos reconhecidos:
      'de outubro a dezembro de 2025' → ('10/2025', '11/2025', '12/2025')
      'entre jan e mar 2025'          → ('01/2025', '02/2025', '03/2025')
      'outubro até dezembro 2025'     → ('10/2025', '11/2025', '12/2025')
    """
    import unicodedata

    def _norm(s: str) -> str:
        return unicodedata.normalize("NFD", s.lower()).encode("ascii", "ignore").decode()

    m = _norm(mensagem)
    nomes = "|".join(sorted(_MES_NOME_NUM.keys(), key=len, reverse=True))
    pat = (
        rf'(?:de\s+|entre\s+)?({nomes})'
        rf'\s+(?:ao?|e|ate|a)\s+'
        rf'({nomes})'
        rf'(?:\s+de)?\s+(\d{{4}})'
    )
    match = re.search(pat, m)
    if not match:
        return None
    mes_ini = _MES_NOME_NUM.get(match.group(1))
    mes_fim = _MES_NOME_NUM.get(match.group(2))
    ano = int(match.group(3))
    if not mes_ini or not mes_fim or mes_ini > mes_fim:
        return None
    return tuple(f"{mes:02d}/{ano}" for mes in range(mes_ini, mes_fim + 1))


def _grafico_por_tipo(
    tipo: str,
    periodos: list[ResumoFinanceiro],
    periodo_hint: str | None = None,
    categoria_filtro: str | None = None,
    orientacao: str | None = None,
):
    import pandas as pd
    from collections import defaultdict
    periodos_ord = sorted(periodos, key=_sort_key)
    ultimo = periodos_ord[-1]
    # Orientação: vertical = "v" (padrão para barras), horizontal = "h"
    _vert = orientacao == "vertical"
    _horiz = orientacao == "horizontal"

    if tipo == "receitas":
        orient = "v" if _vert else "h"
        x_vals = [i.descricao for i in ultimo.receitas] if _vert else [i.valor for i in ultimo.receitas]
        y_vals = [i.valor for i in ultimo.receitas] if _vert else [i.descricao for i in ultimo.receitas]
        fig = px.bar(
            x=x_vals, y=y_vals,
            orientation=orient, title=f"Receitas — {ultimo.periodo}",
            color_discrete_sequence=["#006d2f"],
            labels={"x": "Valor (R$)" if _vert else "", "y": "" if _vert else "Valor (R$)"},
        )
        if _vert:
            fig.update_layout(xaxis_tickangle=-30)
    elif tipo == "despesas":
        fig = go.Figure(go.Pie(
            labels=[i.descricao for i in ultimo.despesas],
            values=[i.valor for i in ultimo.despesas],
            hole=0.45, textinfo="percent+label",
        ))
        fig.update_layout(title=f"Composição das Despesas — {ultimo.periodo}", showlegend=False)
    elif tipo == "inadimplencia":
        orient = "v" if _vert else "h"
        x_vals = [i.conta for i in ultimo.inadimplencia] if _vert else [i.valor for i in ultimo.inadimplencia]
        y_vals = [i.valor for i in ultimo.inadimplencia] if _vert else [i.conta for i in ultimo.inadimplencia]
        fig = px.bar(
            x=x_vals, y=y_vals,
            orientation=orient, title=f"Inadimplência — {ultimo.periodo}",
            color_discrete_sequence=["#C5002D"],
            labels={"x": "Valor (R$)" if _vert else "", "y": "" if _vert else "Valor (R$)"},
        )
        if _vert:
            fig.update_layout(xaxis_tickangle=-30)
    elif tipo == "receitas_vs_despesas":
        # Padrão: vertical. Horizontal se pedido explicitamente.
        if _horiz:
            fig = go.Figure([
                go.Bar(name="Receitas", y=[p.periodo for p in periodos_ord],
                       x=[p.indicadores.receita_total for p in periodos_ord],
                       marker_color="#006d2f", orientation="h"),
                go.Bar(name="Despesas", y=[p.periodo for p in periodos_ord],
                       x=[p.indicadores.despesa_total for p in periodos_ord],
                       marker_color="#C5002D", orientation="h"),
            ])
            fig.update_layout(barmode="group", title="Receitas vs Despesas por Período",
                              xaxis_title="Valor (R$)")
        else:
            fig = go.Figure([
                go.Bar(name="Receitas", x=[p.periodo for p in periodos_ord],
                       y=[p.indicadores.receita_total for p in periodos_ord],
                       marker_color="#006d2f"),
                go.Bar(name="Despesas", x=[p.periodo for p in periodos_ord],
                       y=[p.indicadores.despesa_total for p in periodos_ord],
                       marker_color="#C5002D"),
            ])
            fig.update_layout(barmode="group", title="Receitas vs Despesas por Período",
                              yaxis_title="Valor (R$)")
    elif tipo == "receitas_comparativo":
        rows = [
            {"periodo": p.periodo, "categoria": i.descricao, "valor": i.valor}
            for p in periodos_ord for i in p.receitas
        ]
        df = pd.DataFrame(rows)
        if _horiz:
            fig = px.bar(df, x="valor", y="categoria", color="periodo", barmode="group",
                         orientation="h", title="Receitas por Categoria entre Períodos",
                         color_discrete_sequence=px.colors.sequential.Greens_r,
                         labels={"valor": "Valor (R$)", "categoria": ""})
        else:
            fig = px.bar(df, x="categoria", y="valor", color="periodo", barmode="group",
                         title="Receitas por Categoria entre Períodos",
                         color_discrete_sequence=px.colors.sequential.Greens_r,
                         labels={"valor": "Valor (R$)", "categoria": ""})
            fig.update_layout(xaxis_tickangle=-30)
    elif tipo == "despesas_comparativo":
        rows = [
            {"periodo": p.periodo, "categoria": i.descricao, "valor": i.valor}
            for p in periodos_ord for i in p.despesas
        ]
        df = pd.DataFrame(rows)
        if _horiz:
            fig = px.bar(df, x="valor", y="categoria", color="periodo", barmode="group",
                         orientation="h", title="Despesas por Categoria entre Períodos",
                         labels={"valor": "Valor (R$)", "categoria": ""})
        else:
            fig = px.bar(df, x="categoria", y="valor", color="periodo", barmode="group",
                         title="Despesas por Categoria entre Períodos",
                         labels={"valor": "Valor (R$)", "categoria": ""})
            fig.update_layout(xaxis_tickangle=-30)
    elif tipo == "despesas_periodo":
        if periodo_hint:
            matches = [p for p in periodos_ord if periodo_hint in p.periodo.lower()]
            target = matches[0] if matches else ultimo
        else:
            target = ultimo
        fig = go.Figure(go.Pie(
            labels=[i.descricao for i in target.despesas],
            values=[i.valor for i in target.despesas],
            hole=0.45, textinfo="percent+label",
        ))
        fig.update_layout(title=f"Detalhamento das Despesas — {target.periodo}", showlegend=False)
    elif tipo == "pizza":
        cat = (categoria_filtro or "").lower()
        totais: dict[str, float] = defaultdict(float)
        for p in periodos_ord:
            for item in p.despesas + p.receitas:
                if not cat or cat in item.descricao.lower():
                    totais[item.descricao] += item.valor
        if totais:
            titulo = f"Pizza — {categoria_filtro.title()}" if categoria_filtro else "Pizza — Todas as Categorias"
            fig = go.Figure(go.Pie(
                labels=list(totais.keys()),
                values=list(totais.values()),
                hole=0.35, textinfo="percent",
            ))
            fig.update_layout(title=titulo, showlegend=True, legend=dict(orientation="v"))
        else:
            fig = go.Figure()
            fig.update_layout(title=f"Nenhum item encontrado para '{categoria_filtro}'")
    else:
        # Comparação entre períodos (receitas + despesas) — padrão horizontal
        rows = []
        for p in periodos_ord:
            for i in p.receitas:
                rows.append({"periodo": p.periodo, "categoria": i.descricao, "valor": i.valor, "tipo": "Receita"})
            for i in p.despesas:
                rows.append({"periodo": p.periodo, "categoria": i.descricao, "valor": i.valor, "tipo": "Despesa"})
        df = pd.DataFrame(rows)
        orient = "v" if _vert else "h"
        if _vert:
            fig = px.bar(df, x="categoria", y="valor", color="periodo",
                         barmode="group", title="Comparativo por Período",
                         labels={"valor": "Valor (R$)", "categoria": ""})
            fig.update_layout(xaxis_tickangle=-30)
        else:
            fig = px.bar(df, x="valor", y="categoria", color="periodo", orientation="h",
                         barmode="group", title="Comparativo por Período",
                         labels={"valor": "Valor (R$)", "categoria": ""})
    fig.update_layout(margin=dict(l=0, r=0, t=40, b=0), height=340)
    return fig

# ─── Chips de sugestão ───────────────────────────────────────────────────────

_SUGESTOES_UNICO = [
    ("Resumo do período",           "Faça um resumo executivo do período, destacando os pontos mais importantes."),
    ("Principais alertas",          "Quais são os principais alertas financeiros que devo me preocupar neste período?"),
    ("Gráfico receitas vs despesas","Mostre um gráfico de receitas vs despesas deste período."),
    ("Analisar inadimplência",      "Analise a inadimplência: quem são os maiores devedores e qual o impacto no caixa?"),
]

_SUGESTOES_MULTI = [
    ("Evolução receitas vs despesas","Mostre um gráfico comparando a evolução de receitas vs despesas entre os períodos."),
    ("Comparativo de despesas",      "Compare as categorias de despesas entre os períodos e identifique variações relevantes."),
    ("Tendência da inadimplência",   "Como a inadimplência evoluiu entre os períodos? Há tendência de piora ou melhora?"),
    ("Melhor e pior período",        "Qual foi o melhor e o pior período financeiro e por quê?"),
    ("Recomendações de gestão",      "Com base em todos os períodos, quais recomendações de gestão financeira você sugere?"),
]

_CHIP_CSS = """
<style>
.chip-anchor + div [data-testid="stButton"] button {
    background: linear-gradient(135deg, #C5002D 0%, #9A001F 100%);
    color: white !important;
    border: none;
    border-radius: 20px;
    font-family: 'Inter', sans-serif;
    font-size: 0.78em;
    font-weight: 500;
    padding: 6px 16px;
    cursor: pointer;
    transition: opacity 0.15s ease, transform 0.1s ease;
    white-space: nowrap;
    letter-spacing: 0.01em;
    width: auto !important;
    min-width: 0 !important;
}
.chip-anchor + div [data-testid="stButton"] button:hover {
    opacity: 0.82;
    transform: translateY(-1px);
}
.chip-anchor + div [data-testid="stButton"] button:active {
    opacity: 1;
    transform: translateY(0);
}
</style>
"""

def _chips_sugestao(n_periodos: int) -> None:
    if st.session_state["chat_historico"]:
        return
    sugestoes = _SUGESTOES_UNICO if n_periodos == 1 else _SUGESTOES_MULTI
    st.markdown(_CHIP_CSS, unsafe_allow_html=True)
    st.markdown(
        '<p style="font-family:Inter,sans-serif;font-size:0.82em;'
        'color:#888;margin:6px 0 4px;">Sugestões para começar:</p>',
        unsafe_allow_html=True,
    )
    st.markdown('<div class="chip-anchor"></div>', unsafe_allow_html=True)
    cols = st.columns(len(sugestoes))
    for col, (label, pergunta_completa) in zip(cols, sugestoes):
        with col:
            if st.button(label, key=f"chip_{label}", use_container_width=True):
                st.session_state["sugestao_pendente"] = pergunta_completa
                st.rerun()


# ─── UI ───────────────────────────────────────────────────────────────────────

# Título alinhado à esquerda com tipografia Lello
st.markdown(
    '<div style="padding:20px 0 18px;border-bottom:3px solid #C5002D;margin-bottom:2rem;">'
    '<div style="font-family:Georgia,serif;font-style:italic;font-weight:700;font-size:1.9rem;color:#C5002D;line-height:1.1;">Relat&#243;rio Financeiro com IA</div>'
    '</div>',
    unsafe_allow_html=True,
)

with st.sidebar:
    # ── Logo Lello ────────────────────────────────────────────────────────────
    st.markdown(
        '<div style="padding:4px 0 14px;border-bottom:2px solid #f0f0f0;margin-bottom:0;">'
        '<div style="font-family:Georgia,serif;font-style:italic;font-weight:700;font-size:2rem;color:#C5002D;line-height:1;">lello</div>'
        '<div style="font-family:Inter,sans-serif;font-size:0.55rem;font-weight:700;color:#C5002D;letter-spacing:0.22em;text-transform:uppercase;margin-top:2px;">CONDOM&#205;NIOS</div>'
        '</div>',
        unsafe_allow_html=True,
    )

    # ── Seção 1: Condomínio ───────────────────────────────────────────────────
    st.markdown('<div style="height:14px;"></div>', unsafe_allow_html=True)
    if _databricks_configurado():
        # Tenta conectar apenas uma vez por sessão; erros ficam guardados no estado
        if "refs_ok" not in st.session_state:
            try:
                st.session_state["refs_ok"] = listar_referencias()
                st.session_state["refs_erro"] = None
            except Exception as _e_lista:
                st.session_state["refs_ok"] = []
                st.session_state["refs_erro"] = _e_lista

        refs = st.session_state["refs_ok"]
        _erro_refs = st.session_state.get("refs_erro")

        if _erro_refs and not refs:
            if _is_erro_transiente(_erro_refs):
                st.warning("⏳ Cluster Databricks não disponível.")
                if st.button("🔌 Aguardar cluster (até 5 min)", use_container_width=True):
                    with st.status("Iniciando cluster Databricks…", expanded=True) as _status:
                        st.write("Aguardando até 5 minutos…")
                        _ok = aguardar_cluster(max_wait=300, step=30)
                        if _ok:
                            _status.update(label="✅ Cluster pronto!", state="complete")
                            st.cache_data.clear()
                            try:
                                refs = listar_referencias()
                                st.session_state["refs_ok"] = refs
                                st.session_state["refs_erro"] = None
                            except Exception:
                                pass
                        else:
                            _status.update(label="❌ Cluster não respondeu em 5 min", state="error")
            else:
                st.error(f"Erro Databricks: {_erro_refs}")

        if refs:
            ref_selecionada = st.selectbox("Condomínio", options=refs, index=0)
        else:
            ref_selecionada = None

        arquivos = None
    else:
        ref_selecionada = None
        arquivos = st.file_uploader(
            "Envie os relatórios (PDF ou XLSX)",
            type=["pdf", "xlsx"],
            accept_multiple_files=True,
            key="upload_arquivos",
        )
    gerar = st.button("Gerar Resumo Executivo", type="primary", use_container_width=True)

    # ── Seção 2: Custo da sessão ─────────────────────────────────────────────
    st.markdown('<div style="border-top:1px solid #eee;margin:18px 0 10px;"></div>', unsafe_allow_html=True)
    st.markdown('<div style="font-size:0.72rem;font-weight:700;color:#C5002D;text-transform:uppercase;letter-spacing:0.1em;margin-bottom:10px;">Custo da Sess&#227;o</div>', unsafe_allow_html=True)
    _su = st.session_state.setdefault("session_usage", {
        "input_tokens": 0, "output_tokens": 0,
        "cache_creation_tokens": 0, "cache_read_tokens": 0,
        "cost_usd": 0.0, "n_calls": 0, "by_model": {},
    })
    _su.setdefault("by_model", {})
    _cost_brl = custo_brl(_su["cost_usd"])

    def _mini_card(col, label, value, delta=None, delta_color=None):
        delta_html = ""
        if delta:
            if delta_color == "off":
                delta_html = f'<div style="font-size:0.65rem;color:#888;margin-top:2px">{delta}</div>'
            elif delta and delta != "—":
                c = "#e03131" if str(delta).startswith("+") else "#2f9e44"
                delta_html = f'<div style="font-size:0.65rem;color:{c};margin-top:2px">{delta}</div>'
        col.markdown(
            f'<div style="background:#f9f9f9;border:1px solid #eee;border-radius:6px;'
            f'padding:5px 6px;text-align:center;min-width:0">'
            f'<div style="font-size:0.62rem;color:#666;margin-bottom:2px;white-space:nowrap;'
            f'overflow:hidden;text-overflow:ellipsis">{label}</div>'
            f'<div style="font-size:0.82rem;font-weight:700;color:#222;'
            f'word-break:break-all;line-height:1.2">{value}</div>'
            f'{delta_html}</div>',
            unsafe_allow_html=True,
        )

    _c1, _c2, _c3 = st.columns(3)
    _mini_card(_c1, "USD",     f"$ {_su['cost_usd']:.4f}")
    _mini_card(_c2, "BRL",     f"R$ {_cost_brl:.4f}")
    _mini_card(_c3, "Chamadas", str(_su["n_calls"]))
    _cache_pct = (
        round(_su["cache_read_tokens"] / max(_su["input_tokens"] + _su["cache_read_tokens"], 1) * 100)
        if _su["n_calls"] > 0 else 0
    )
    st.caption(
        f"Input: {_su['input_tokens']:,} tok · "
        f"Output: {_su['output_tokens']:,} tok · "
        f"Cache: {_su['cache_read_tokens']:,} tok ({_cache_pct}%)"
    )

    # ── Seção 3: Comparativo de provedores ───────────────────────────────────
    st.markdown('<div style="border-top:1px solid #eee;margin:14px 0 10px;"></div>', unsafe_allow_html=True)
    st.markdown('<div style="font-size:0.72rem;font-weight:700;color:#C5002D;text-transform:uppercase;letter-spacing:0.1em;margin-bottom:10px;">Comparativo de Provedores</div>', unsafe_allow_html=True)
    _linhas = comparar_provedores(_su.get("by_model", {})) if _su["n_calls"] > 0 else []
    with st.expander("Ver comparativo", expanded=False):
        if not _linhas:
            st.caption("Nenhuma chamada na sessão ainda.")
        else:
            _total_a = sum(r["custo_anthropic"] for r in _linhas)
            _total_o = sum(r["custo_openai"]    for r in _linhas)
            _total_g = sum(r["custo_gemini"]    for r in _linhas)

            def _delta(alt, base):
                if base == 0:
                    return "—"
                pct = (alt - base) / base * 100
                sinal = "+" if pct > 0 else ""
                return f"{sinal}{pct:.0f}%"

            # Tabela por uso (Extração / Chat / Gráfico)
            for r in _linhas:
                st.markdown(
                    f'<div style="font-size:0.9rem;font-weight:700;color:#C5002D;margin:6px 0 4px">{r["uso"]}</div>',
                    unsafe_allow_html=True,
                )
                _ca, _co, _cg = st.columns(3)
                _mini_card(_ca, "Anthropic", f"${r['custo_anthropic']:.4f}", r['modelo_anthropic'], delta_color="off")
                _mini_card(_co, "OpenAI",    f"${r['custo_openai']:.4f}",    r['modelo_openai'],    delta_color="off")
                _mini_card(_cg, "Google",    f"${r['custo_gemini']:.4f}",    r['modelo_gemini'],    delta_color="off")

            st.divider()
            # Linha de totais com deltas
            _ta, _to, _tg = st.columns(3)
            _mini_card(_ta, "Total Anthropic", f"${_total_a:.4f}", "atual",                   delta_color="off")
            _mini_card(_to, "Total OpenAI",    f"${_total_o:.4f}", _delta(_total_o, _total_a))
            _mini_card(_tg, "Total Google",    f"${_total_g:.4f}", _delta(_total_g, _total_a))
            st.caption("⚠️ Estimativa: mesmos tokens, modelos equivalentes. "
                       "Cache do Gemini exclui custo de armazenamento/hora.")

    # ── Seção 4: Histórico ───────────────────────────────────────────────────
    st.markdown('<div style="border-top:1px solid #eee;margin:14px 0 10px;"></div>', unsafe_allow_html=True)
    st.markdown('<div style="font-size:0.72rem;font-weight:700;color:#C5002D;text-transform:uppercase;letter-spacing:0.1em;margin-bottom:10px;">Hist&#243;rico</div>', unsafe_allow_html=True)
    with st.expander("Ver interações da sessão", expanded=False):
        import pandas as _pd
        _session_start = st.session_state.get("session_start")
        if not _session_start:
            st.info("Nenhuma interação nesta sessão ainda.")
        else:
            _logs = listar_logs(limit=500)
            _logs = [r for r in _logs if r["timestamp"] >= _session_start]
            _logs = list(reversed(_logs))  # mais antiga primeiro
            if _logs:
                _df_logs = _pd.DataFrame(_logs)[
                    ["timestamp", "referencia", "pergunta", "resposta",
                     "modelo", "input_tokens", "output_tokens",
                     "cache_creation_tokens", "cache_read_tokens", "sql_usado"]
                ]
                st.dataframe(_df_logs, use_container_width=True)
            else:
                st.info("Nenhuma interação nesta sessão ainda.")


# ─── Estado da sessão ─────────────────────────────────────────────────────────

for k, v in [
    ("resumos", []),
    ("resumos_chat", []),
    ("dados_chat", ""),
    ("chat_historico", []),
    ("resumo_gerado", False),
    ("sugestao_pendente", None),
    ("referencia_atual", None),
    ("n_meses_carregados", 2),
    ("session_usage", {"input_tokens": 0, "output_tokens": 0,
                       "cache_creation_tokens": 0, "cache_read_tokens": 0,
                       "cost_usd": 0.0, "n_calls": 0, "by_model": {}}),
    ("session_start", None),
    ("periodos_chat", None),
]:
    if k not in st.session_state:
        st.session_state[k] = v


def _preparar_historico(dados: str, historico: list[dict]) -> list[dict]:
    """Retorna histórico trimado para garantir que o contexto total caiba em 180k tokens.

    Estimativa: 1 token ≈ 4 chars. Reservamos 180k tokens para dados + histórico,
    deixando 20k para a resposta e overhead do system prompt.
    Remove os pares de mensagens mais antigas até caber.
    """
    _LIMITE_CHARS = 180_000 * 4  # 180k tokens × 4 chars/token
    _OVERHEAD_SYSTEM = 2_000 * 4  # ~2k tokens para o template do system prompt

    disponivel = _LIMITE_CHARS - len(dados) - _OVERHEAD_SYSTEM
    if disponivel <= 0:
        return []  # dados sozinhos já tomam tudo — histórico zerado

    trimado = [m for m in historico if m.get("content")]
    while trimado:
        tamanho = sum(len(str(m["content"])) for m in trimado)
        if tamanho <= disponivel:
            break
        # Remove o par mais antigo (user + assistant)
        trimado = trimado[2:]

    return trimado


def _accumulate_usage(usage: dict, model: str, uso: str = "Chat") -> None:
    from datetime import datetime, timezone
    su = st.session_state["session_usage"]
    if st.session_state["session_start"] is None:
        st.session_state["session_start"] = datetime.now(timezone.utc).isoformat()
    su["input_tokens"]          += usage.get("input_tokens", 0)
    su["output_tokens"]         += usage.get("output_tokens", 0)
    su["cache_creation_tokens"] += usage.get("cache_creation_tokens", 0)
    su["cache_read_tokens"]     += usage.get("cache_read_tokens", 0)
    su["cost_usd"] += calcular_custo_usd(
        model,
        usage.get("input_tokens", 0),
        usage.get("output_tokens", 0),
        usage.get("cache_creation_tokens", 0),
        usage.get("cache_read_tokens", 0),
    )
    su["n_calls"] += 1
    # Acumula por "uso:modelo" para o comparativo de provedores
    key = f"{uso}:{model}"
    bm = su.setdefault("by_model", {}).setdefault(key, {
        "input_tokens": 0, "output_tokens": 0,
        "cache_creation_tokens": 0, "cache_read_tokens": 0,
    })
    bm["input_tokens"]          += usage.get("input_tokens", 0)
    bm["output_tokens"]         += usage.get("output_tokens", 0)
    bm["cache_creation_tokens"] += usage.get("cache_creation_tokens", 0)
    bm["cache_read_tokens"]     += usage.get("cache_read_tokens", 0)

# ─── Ação: gerar ──────────────────────────────────────────────────────────────

import json as _json


def _resumos_para_chat(resumos: list) -> str:
    """Converte os resumos para texto compacto para uso como contexto no chat.

    Formato texto (em vez de JSON) reduz tokens em ~3x e é mais natural para o modelo.
    Omite panorama/alertas — são textos gerados pela IA, não dados primários.
    """
    def _brl(v: float) -> str:
        return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    linhas = []
    nome = resumos[-1].condominio if resumos else "Condomínio"
    periodos = ", ".join(r.periodo for r in resumos)
    linhas.append(f"DADOS FINANCEIROS — {nome}")
    linhas.append(f"Períodos analisados: {periodos}")

    for r in resumos:
        linhas.append(f"\n=== {r.periodo} ===")
        ind = r.indicadores
        linhas.append(
            f"Receita Total: {_brl(ind.receita_total)} | "
            f"Despesa Total: {_brl(ind.despesa_total)} | "
            f"Resultado: {_brl(ind.resultado)} | "
            f"Inadimplência: {_brl(ind.inadimplencia_total)}"
        )
        if r.receitas:
            linhas.append("Receitas: " + " | ".join(
                f"{i.descricao}: {_brl(i.valor)}" for i in r.receitas
            ))
        if r.despesas:
            linhas.append("Despesas: " + " | ".join(
                f"{i.descricao}: {_brl(i.valor)}" for i in r.despesas
            ))
        if r.inadimplencia:
            linhas.append("Inadimplência por unidade: " + " | ".join(
                f"{i.conta}: {_brl(i.valor)}" for i in r.inadimplencia
            ))

    return "\n".join(linhas)

if gerar:
    resumos = []
    erros = []
    progress = st.progress(0, text="Iniciando...")

    if _databricks_configurado():
        if not ref_selecionada:
            progress.empty()
            st.error("Selecione uma referência antes de gerar.")
        else:
            try:
                progress.progress(0.2, text="Conectando ao Databricks…")
                clear_recent_sql()
                try:
                    texto = extrair_de_databricks(ref_selecionada, n_meses=2)
                except Exception as _e_fetch:
                    if _is_erro_transiente(_e_fetch):
                        progress.progress(0.2, text="⏳ Cluster iniciando — aguardando até 5 min…")
                        _ok = aguardar_cluster(max_wait=300, step=30)
                        if not _ok:
                            raise TimeoutError("Cluster Databricks não ficou disponível em 5 minutos.") from _e_fetch
                        texto = extrair_de_databricks(ref_selecionada, n_meses=2)
                    else:
                        raise
                progress.progress(0.7, text="Analisando documentos…")
                _resumo_usage: dict = {}
                resumos = gerar_resumo(_api_key(), texto, usage_out=_resumo_usage)
                _accumulate_usage(_resumo_usage, settings.claude_model, uso="Extração")
                try:
                    registrar_log(
                        referencia=ref_selecionada,
                        pergunta="[RESUMO EXECUTIVO]",
                        resposta=", ".join(r.periodo for r in resumos),
                        modelo=settings.claude_model,
                        input_tokens=_resumo_usage.get("input_tokens", 0),
                        output_tokens=_resumo_usage.get("output_tokens", 0),
                        sql_usado="\n---\n".join(get_recent_sql()),
                        cache_creation_tokens=_resumo_usage.get("cache_creation_tokens", 0),
                        cache_read_tokens=_resumo_usage.get("cache_read_tokens", 0),
                    )
                except Exception:
                    pass
            except Exception as e:
                erros.append(str(e))
            progress.empty()
            if erros:
                for err in erros:
                    st.error(err)
            if not resumos:
                st.stop()
            st.session_state["referencia_atual"]   = ref_selecionada
            st.session_state["n_meses_carregados"] = 2
    else:
        if not arquivos:
            progress.empty()
            st.error("Envie ao menos um arquivo antes de gerar.")
        else:
            secoes_resumo = []
            for idx, arq in enumerate(arquivos):
                frac = (idx + 1) / (len(arquivos) + 1)
                progress.progress(frac, text=f"Extraindo {arq.name}…")
                texto = extrair_texto(arq)
                secoes_resumo.append(f"=== {arq.name} ===\n{texto}")
            progress.progress(len(arquivos) / (len(arquivos) + 1), text="Analisando documentos…")
            try:
                _resumo_usage: dict = {}
                resumos = gerar_resumo(_api_key(), "\n\n".join(secoes_resumo), usage_out=_resumo_usage)
                _accumulate_usage(_resumo_usage, settings.claude_model, uso="Extração")
                try:
                    registrar_log(
                        referencia=", ".join(a.name for a in arquivos),
                        pergunta="[RESUMO EXECUTIVO]",
                        resposta=", ".join(r.periodo for r in resumos),
                        modelo=settings.claude_model,
                        input_tokens=_resumo_usage.get("input_tokens", 0),
                        output_tokens=_resumo_usage.get("output_tokens", 0),
                        sql_usado="",
                        cache_creation_tokens=_resumo_usage.get("cache_creation_tokens", 0),
                        cache_read_tokens=_resumo_usage.get("cache_read_tokens", 0),
                    )
                except Exception:
                    pass
            except ValueError as e:
                erros.append(str(e))
            progress.empty()
            if erros:
                for err in erros:
                    st.error(err)
            if not resumos:
                st.stop()
            st.session_state["referencia_atual"]   = None
            st.session_state["n_meses_carregados"] = len(resumos)

    if resumos:
        st.session_state["resumos"]           = resumos
        st.session_state["resumos_chat"]      = resumos
        st.session_state["dados_chat"]        = _resumos_para_chat(resumos)
        st.session_state["chat_historico"]    = []
        st.session_state["sugestao_pendente"] = None
        st.session_state["resumo_gerado"]     = True
        st.session_state["periodos_chat"]     = None
        st.rerun()

# ─── Exibição ─────────────────────────────────────────────────────────────────

if st.session_state["resumo_gerado"] and st.session_state["resumos"]:
    st.divider()
    exibir_relatorio(st.session_state["resumos"])


    st.divider()
    st.subheader("Chat com os Relatórios")
    _chips_sugestao(len(st.session_state["resumos"]))

    for i, msg in enumerate(st.session_state["chat_historico"]):
        with st.chat_message(msg["role"]):
            if msg.get("chart_type") and st.session_state["resumos_chat"]:
                st.plotly_chart(
                    _grafico_por_tipo(
                        msg["chart_type"],
                        st.session_state["resumos_chat"],
                        msg.get("periodo_hint"),
                        msg.get("categoria_filtro"),
                        msg.get("orientacao"),
                    ),
                    use_container_width=True,
                    key=f"chart_hist_{i}",
                )
            if msg.get("content"):
                st.markdown(msg["content"])

    if st.session_state["chat_historico"]:
        components.html(_SCROLL_JS, height=0)

    pergunta = st.session_state.pop("sugestao_pendente", None) or st.chat_input(
        "Pergunte sobre os relatórios financeiros…"
    )
    if pergunta:
        # Re-fetch se o usuário pede mais meses ou período explícito e Databricks está configurado.
        # Atualiza apenas o contexto do chat (dados_chat); o quadro do resumo
        # executivo (resumos) permanece fixo com os 2 meses iniciais.
        n_pedido = _detectar_n_meses_pedido(pergunta)
        periodos_exp = _detectar_periodo_explicito(pergunta)
        ref = st.session_state.get("referencia_atual")
        precisa_refetch = ref and (
            periodos_exp
            or (n_pedido and n_pedido > st.session_state.get("n_meses_carregados", 0))
        )
        if precisa_refetch:
            with st.spinner("Buscando dados no Databricks…"):
                try:
                    if periodos_exp:
                        texto = extrair_balancete_compacto(ref, periodos_fixos=periodos_exp)
                        label = f"{periodos_exp[0]} a {periodos_exp[-1]}" if len(periodos_exp) > 1 else periodos_exp[0]
                        msg_ctx = f"📊 Contexto do chat atualizado com o período **{label}**."
                        st.session_state["periodos_chat"] = label
                    else:
                        texto = extrair_balancete_compacto(ref, n_meses=n_pedido)
                        st.session_state["n_meses_carregados"] = n_pedido
                        msg_ctx = f"📊 Contexto do chat atualizado com **{n_pedido} meses**."
                        _periodos_raw = re.findall(r'\[(\d{2}/\d{4})\]', texto)
                        st.session_state["periodos_chat"] = ", ".join(sorted(set(_periodos_raw))) or f"últimos {n_pedido} meses"
                    st.session_state["dados_chat"] = texto
                    st.session_state["chat_historico"].append({
                        "role": "assistant",
                        "content": msg_ctx,
                    })
                except Exception as e:
                    st.warning(f"Não foi possível buscar mais dados: {e}")

        _grafico_usage: dict = {}
        tipo_grafico, periodo_hint, categoria_filtro, orientacao = _detectar_tipo_grafico(pergunta, _api_key(), usage_out=_grafico_usage)
        if _grafico_usage:
            _accumulate_usage(_grafico_usage, settings.claude_model_chat, uso="Gráfico")
        components.html(_SCROLL_JS, height=0)

        with st.chat_message("user"):
            st.markdown(pergunta)

        with st.chat_message("assistant"):
            if tipo_grafico:
                st.plotly_chart(
                    _grafico_por_tipo(tipo_grafico, st.session_state["resumos_chat"], periodo_hint, categoria_filtro, orientacao),
                    use_container_width=True,
                    key=f"chart_hist_{len(st.session_state['chat_historico'])}",
                )
            _box = st.empty()
            _status_box = st.empty()
            resposta = ""
            _usage: dict = {}
            clear_recent_sql()
            import anthropic as _ant
            import time as _time
            _resumos_c = st.session_state.get("resumos_chat") or []
            _nome_cond = _resumos_c[-1].condominio if _resumos_c else "Condomínio"
            _periodos_c = st.session_state.get("periodos_chat") or ", ".join(r.periodo for r in _resumos_c)

            _dados_chat = st.session_state["dados_chat"]
            _historico_chat = _preparar_historico(_dados_chat, st.session_state["chat_historico"])

            _rate_waits = [60, 120]
            for _attempt in range(len(_rate_waits) + 1):
                try:
                    for _chunk in stream_chat(
                        api_key=_api_key(),
                        dados=_dados_chat,
                        historico=_historico_chat,
                        mensagem=pergunta,
                        usage_out=_usage,
                        nome=_nome_cond,
                        periodos=_periodos_c,
                    ):
                        resposta += _chunk
                        _box.markdown(resposta.replace("R$", "R\\$"))
                    resposta = strip_code_blocks(resposta)
                    _box.markdown(resposta.replace("R$", "R\\$"))
                    _status_box.empty()
                    break
                except _ant.RateLimitError:
                    if _attempt < len(_rate_waits):
                        _w = _rate_waits[_attempt]
                        resposta = ""
                        _box.empty()
                        _status_box.warning(f"⏳ Limite de taxa atingido. Aguardando {_w}s…")
                        _time.sleep(_w)
                        _status_box.empty()
                    else:
                        _status_box.error("Limite de taxa atingido após várias tentativas. Aguarde alguns minutos.")
                        resposta = ""
                        break
                except _ant.BadRequestError:
                    # Último recurso: zera histórico e tenta de novo com contexto limpo
                    if _attempt == 0:
                        st.session_state["chat_historico"] = []
                        _historico_chat = []
                        continue
                    _status_box.error("Não foi possível processar. Tente recarregar a página.")
                    resposta = ""
                    break

        if _usage:
            _accumulate_usage(_usage, settings.claude_model_chat, uso="Chat")
        try:
            registrar_log(
                referencia=str(st.session_state.get("referencia_atual") or "arquivo"),
                pergunta=pergunta,
                resposta=resposta,
                modelo=settings.claude_model_chat,
                input_tokens=_usage.get("input_tokens", 0),
                output_tokens=_usage.get("output_tokens", 0),
                sql_usado="\n---\n".join(get_recent_sql()),
                cache_creation_tokens=_usage.get("cache_creation_tokens", 0),
                cache_read_tokens=_usage.get("cache_read_tokens", 0),
            )
        except Exception:
            pass  # log nunca deve quebrar o fluxo principal

        st.session_state["chat_historico"].append({"role": "user", "content": pergunta})
        st.session_state["chat_historico"].append({
            "role": "assistant",
            "content": resposta,
            "chart_type": tipo_grafico,
            "periodo_hint": periodo_hint,
            "categoria_filtro": categoria_filtro,
            "orientacao": orientacao,
        })
        st.rerun()

else:
    if _databricks_configurado():
        st.info("Selecione uma referência no sidebar e clique em **Gerar Resumo Executivo** para começar.")
    else:
        st.info("Envie os arquivos no sidebar e clique em **Gerar Resumo Executivo** para começar.")
