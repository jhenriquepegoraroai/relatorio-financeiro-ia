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
from core.claude import gerar_resumo, stream_chat
from core.extractor import extrair_texto
from core.formatters import brl
from core.models import ResumoFinanceiro

st.set_page_config(
    page_title="Relatório Financeiro por IA",
    page_icon="📊",
    layout="wide",
)

# ─── Auto-scroll ──────────────────────────────────────────────────────────────

_SCROLL_JS = """
<script>
setTimeout(function() {
    var sel = ['[data-testid="stAppViewContainer"]', 'section.main', '.main'];
    for (var i = 0; i < sel.length; i++) {
        var el = window.parent.document.querySelector(sel[i]);
        if (el) { el.scrollTop = el.scrollHeight; return; }
    }
    window.parent.scrollTo(0, window.parent.document.body.scrollHeight);
}, 150);
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
    "titulo":    "background:#1a3a6b;color:white;font-weight:bold;text-align:center;padding:10px 8px;font-size:1.05em;",
    "subtitulo": "background:#2a4a8b;color:white;text-align:center;padding:4px 8px;font-size:0.88em;",
    "sec_blu":   "background:#2e6da4;color:white;font-weight:bold;padding:5px 10px;",
    "sec_red":   "background:#8b2222;color:white;font-weight:bold;padding:5px 10px;",
    "col_hdr":   "background:#1a3a6b;color:white;font-weight:bold;padding:5px 10px;text-align:right;white-space:nowrap;",
    "col_hdr_l": "background:#1a3a6b;color:white;font-weight:bold;padding:5px 10px;text-align:left;",
    "tot":       "background:#c8d8e8;font-weight:bold;padding:5px 10px;text-align:right;",
    "tot_l":     "background:#c8d8e8;font-weight:bold;padding:5px 10px;text-align:left;",
    "res":       "background:#1a3a6b;color:white;font-weight:bold;padding:5px 10px;text-align:right;",
    "res_l":     "background:#1a3a6b;color:white;font-weight:bold;padding:5px 10px;text-align:left;",
    "d0":        "background:white;padding:4px 10px;text-align:right;border-bottom:1px solid #eee;",
    "d0l":       "background:white;padding:4px 10px;text-align:left;border-bottom:1px solid #eee;",
    "d1":        "background:#f4f7fb;padding:4px 10px;text-align:right;border-bottom:1px solid #eee;",
    "d1l":       "background:#f4f7fb;padding:4px 10px;text-align:left;border-bottom:1px solid #eee;",
}

def _var_css(v: float) -> str:
    if v > 0: return "color:#006400;font-weight:bold;"
    if v < 0: return "color:#cc0000;font-weight:bold;"
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
        '<table style="width:100%;border-collapse:collapse;'
        'font-size:0.83em;margin-bottom:12px;">'
        + inner + "</table>"
    )

# ─── Relatório comparativo ────────────────────────────────────────────────────

def exibir_relatorio(periodos: list[ResumoFinanceiro]):
    periodos = sorted(periodos, key=_sort_key)
    n = len(periodos)
    labels = [p.periodo for p in periodos]
    cv = n >= 2
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

    # ── PANORAMA E ALERTAS (colapsado) ────────────────────────────────────────
    with st.expander("📝 Análise e Alertas"):
        for p in periodos:
            if n > 1:
                st.caption(f"**{p.periodo}**")
            st.info(p.panorama)
            for alerta in p.alertas:
                st.warning(alerta)

# ─── Gráficos no chat ────────────────────────────────────────────────────────

_CHART_KEYWORDS = {"gráfico", "grafico", "chart", "visualiz", "plotar", "plote"}

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

def _detectar_tipo_grafico(msg: str) -> tuple[str | None, str | None]:
    m = msg.lower()
    if not any(k in m for k in _CHART_KEYWORDS):
        return None, None
    if "inadimpl" in m:
        return "inadimplencia", None
    if "vs" in m or "versus" in m or ("receita" in m and "despesa" in m):
        return "receitas_vs_despesas", None
    if "comparativ" in m and "despesa" in m:
        return "despesas_comparativo", None
    if "detalh" in m and "despesa" in m:
        return "despesas_periodo", _extrair_periodo_da_mensagem(m)
    if "receita" in m:
        return "receitas", None
    if "despesa" in m or "custo" in m:
        return "despesas", None
    return "comparacao", None

def _grafico_por_tipo(tipo: str, periodos: list[ResumoFinanceiro], periodo_hint: str | None = None):
    import pandas as pd
    periodos_ord = sorted(periodos, key=_sort_key)
    ultimo = periodos_ord[-1]
    if tipo == "receitas":
        fig = px.bar(
            x=[i.valor for i in ultimo.receitas],
            y=[i.descricao for i in ultimo.receitas],
            orientation="h", title=f"Receitas — {ultimo.periodo}",
            color_discrete_sequence=["#2ecc71"],
            labels={"x": "Valor (R$)", "y": ""},
        )
    elif tipo == "despesas":
        fig = go.Figure(go.Pie(
            labels=[i.descricao for i in ultimo.despesas],
            values=[i.valor for i in ultimo.despesas],
            hole=0.45, textinfo="percent+label",
        ))
        fig.update_layout(title=f"Composição das Despesas — {ultimo.periodo}", showlegend=False)
    elif tipo == "inadimplencia":
        fig = px.bar(
            x=[i.valor for i in ultimo.inadimplencia],
            y=[i.conta  for i in ultimo.inadimplencia],
            orientation="h", title=f"Inadimplência — {ultimo.periodo}",
            color_discrete_sequence=["#e74c3c"],
            labels={"x": "Valor (R$)", "y": ""},
        )
    elif tipo == "receitas_vs_despesas":
        fig = go.Figure([
            go.Bar(
                name="Receitas",
                x=[p.periodo for p in periodos_ord],
                y=[p.indicadores.receita_total for p in periodos_ord],
                marker_color="#2ecc71",
            ),
            go.Bar(
                name="Despesas",
                x=[p.periodo for p in periodos_ord],
                y=[p.indicadores.despesa_total for p in periodos_ord],
                marker_color="#e74c3c",
            ),
        ])
        fig.update_layout(barmode="group", title="Receitas vs Despesas por Período",
                          yaxis_title="Valor (R$)")
    elif tipo == "despesas_comparativo":
        rows = [
            {"periodo": p.periodo, "categoria": i.descricao, "valor": i.valor}
            for p in periodos_ord for i in p.despesas
        ]
        df = pd.DataFrame(rows)
        fig = px.bar(
            df, x="categoria", y="valor", color="periodo", barmode="group",
            title="Despesas por Categoria entre Períodos",
            labels={"valor": "Valor (R$)", "categoria": ""},
        )
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
    else:
        # Comparação entre períodos (receitas + despesas)
        rows = []
        for p in periodos_ord:
            for i in p.receitas:
                rows.append({"periodo": p.periodo, "categoria": i.descricao, "valor": i.valor, "tipo": "Receita"})
            for i in p.despesas:
                rows.append({"periodo": p.periodo, "categoria": i.descricao, "valor": i.valor, "tipo": "Despesa"})
        df = pd.DataFrame(rows)
        fig = px.bar(
            df, x="valor", y="categoria", color="periodo", orientation="h",
            barmode="group", title="Comparativo por Período",
            labels={"valor": "Valor (R$)", "categoria": ""},
        )
    fig.update_layout(margin=dict(l=0, r=0, t=40, b=0), height=340)
    return fig

# ─── UI ───────────────────────────────────────────────────────────────────────

st.title("📊 Relatório Financeiro por IA")
st.caption("POC — leitura de PDF/XLSX · Análise com IA")

with st.sidebar:
    st.header("Relatórios")
    arquivos = st.file_uploader(
        "Envie os relatórios (PDF ou XLSX)",
        type=["pdf", "xlsx"],
        accept_multiple_files=True,
        key="upload_arquivos",
    )
    gerar = st.button("Gerar Resumo Executivo", type="primary", use_container_width=True)

# ─── Estado da sessão ─────────────────────────────────────────────────────────

for k, v in [("resumos", []), ("dados_chat", ""), ("chat_historico", []), ("resumo_gerado", False)]:
    if k not in st.session_state:
        st.session_state[k] = v

# ─── Ação: gerar ──────────────────────────────────────────────────────────────

if gerar:
    if not arquivos:
        st.error("Envie ao menos um arquivo antes de gerar.")
    else:
        resumos = []
        secoes_chat = []
        erros = []

        progress = st.progress(0, text="Iniciando...")

        # Fase 1: extrai texto de todos os arquivos
        secoes_resumo = []
        for idx, arq in enumerate(arquivos):
            frac = (idx + 1) / (len(arquivos) + 1)
            progress.progress(frac, text=f"Extraindo {arq.name}…")
            texto = extrair_texto(arq)
            bloco = f"=== {arq.name} ===\n{texto}"
            secoes_resumo.append(bloco)
            secoes_chat.append(bloco)

        # Fase 2: uma única chamada ao Claude com todos os documentos
        progress.progress(len(arquivos) / (len(arquivos) + 1), text="Analisando documentos…")
        conteudo_completo = "\n\n".join(secoes_resumo)
        try:
            resumos = gerar_resumo(_api_key(), conteudo_completo)
        except ValueError as e:
            erros.append(str(e))

        progress.empty()

        if erros:
            for err in erros:
                st.error(err)
        if not resumos:
            st.stop()

        import json as _json
        st.session_state["resumos"]        = resumos
        st.session_state["dados_chat"]     = _json.dumps(
            [r.model_dump() for r in resumos], ensure_ascii=False, indent=2
        )
        st.session_state["chat_historico"] = []
        st.session_state["resumo_gerado"]  = True

# ─── Exibição ─────────────────────────────────────────────────────────────────

if st.session_state["resumo_gerado"] and st.session_state["resumos"]:
    st.divider()
    exibir_relatorio(st.session_state["resumos"])

    st.divider()
    st.subheader("Chat com os Relatórios")

    for msg in st.session_state["chat_historico"]:
        with st.chat_message(msg["role"]):
            if msg.get("chart_type") and st.session_state["resumos"]:
                st.plotly_chart(
                    _grafico_por_tipo(
                        msg["chart_type"],
                        st.session_state["resumos"],
                        msg.get("periodo_hint"),
                    ),
                    use_container_width=True,
                )
            if msg.get("content"):
                st.markdown(msg["content"])

    if st.session_state["chat_historico"]:
        components.html(_SCROLL_JS, height=0)

    pergunta = st.chat_input("Pergunte sobre os relatórios financeiros…")
    if pergunta:
        tipo_grafico, periodo_hint = _detectar_tipo_grafico(pergunta)

        with st.chat_message("user"):
            st.markdown(pergunta)

        with st.chat_message("assistant"):
            if tipo_grafico:
                st.plotly_chart(
                    _grafico_por_tipo(tipo_grafico, st.session_state["resumos"], periodo_hint),
                    use_container_width=True,
                )
            resposta = st.write_stream(
                stream_chat(
                    api_key=_api_key(),
                    dados=st.session_state["dados_chat"],
                    historico=st.session_state["chat_historico"],
                    mensagem=pergunta,
                )
            )

        st.session_state["chat_historico"].append({"role": "user", "content": pergunta})
        st.session_state["chat_historico"].append({
            "role": "assistant",
            "content": resposta,
            "chart_type": tipo_grafico,
            "periodo_hint": periodo_hint,
        })
        st.rerun()

else:
    st.info("Envie os arquivos no sidebar e clique em **Gerar Resumo Executivo** para começar.")
