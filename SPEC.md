# SPEC — Relatório Financeiro por IA

## Objetivo

Processar dois documentos financeiros de condomínio (Balancete Mensal + Conta Corrente) e gerar um resumo executivo estruturado, acompanhado de um chat para consultas livres.

---

## Entradas

| Entrada | Formato | Obrigatório |
|---|---|---|
| Balancete Mensal | PDF | Sim |
| Conta Corrente | PDF | Sim |
| Anthropic API Key | string (`sk-ant-...`) | Sim |

---

## Schema de saída (JSON)

O Claude retorna exatamente este JSON, validado via Pydantic (`ResumoFinanceiro`):

```json
{
  "periodo": "string — ex: Fevereiro/2024",
  "condominio": "string — nome extraído do documento",
  "panorama": "string — 2 a 3 frases sobre o resultado do mês",
  "indicadores": {
    "receita_total": 30000.00,
    "despesa_total": 28000.00,
    "resultado": 2000.00,
    "inadimplencia_total": 1500.00
  },
  "receitas": [
    { "descricao": "Taxa condominial", "valor": 30000.00 }
  ],
  "despesas": [
    { "descricao": "Manutenção", "valor": 28000.00 }
  ],
  "inadimplencia": [
    { "conta": "Unidade 101", "valor": 1500.00 }
  ],
  "alertas": [
    "Inadimplência acima de 5%"
  ]
}
```

### Regras de negócio do schema

- `receitas` e `despesas`: máximo 5 itens, ordenados do maior para o menor
- `alertas`: máximo 3 itens — apenas pontos que exigem atenção do síndico
- Todos os valores monetários são `float` sem formatação (ex: `28010.50`, não `"R$ 28.010,50"`)
- O Claude nunca deve inventar valores — apenas extrair dos documentos

---

## Comportamento do chat

- Responde somente com base nos dados dos relatórios carregados na sessão
- Se a pergunta não puder ser respondida, o assistente informa claramente
- Respostas limitadas a 200 palavras
- Valores monetários formatados como `R$ XX.XXX,XX`
- Usa prompt caching (`cache_control: ephemeral`) para reduzir custo em conversas longas

---

## Casos de borda

| Situação | Comportamento esperado |
|---|---|
| PDF corrompido ou ilegível | `extrair_texto_pdf` levanta exceção; UI exibe erro |
| Claude retorna JSON inválido | `gerar_resumo` faz retry (1x); se falhar, levanta `ValueError` com trecho do texto |
| Validação Pydantic falha | `ValueError` propagado para a UI com mensagem clara |
| API Key ausente | UI exibe erro e interrompe execução (`st.stop()`) |
| Um dos PDFs não selecionado | UI exibe erro antes de chamar a API |

---

## Arquitetura

```
app.py                  ← UI Streamlit (único arquivo com imports de st.*)
config.py               ← Settings via Pydantic (lê .env)
core/
  models.py             ← Modelos Pydantic (contrato de dados)
  extractor.py          ← Extração de texto de PDFs via pdfplumber
  claude.py             ← Chamadas à API Anthropic
  formatters.py         ← Helpers de formatação (ex: brl)
prompts/
  resumo.txt            ← System prompt para geração do resumo executivo
  chat.txt              ← System prompt para o chat financeiro
tests/
  test_formatters.py    ← Testes de formatação monetária
  test_extractor.py     ← Testes de extração de PDF (com mocks)
  test_claude.py        ← Testes de integração com Claude (com mocks)
```

---

## Variáveis de ambiente

| Variável | Obrigatório | Default | Descrição |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | Sim | — | Chave da API Anthropic |
| `DEFAULT_BALANCETE` | Não | `None` | Caminho padrão do PDF de balancete |
| `DEFAULT_CONTA_CORRENTE` | Não | `None` | Caminho padrão do PDF de conta corrente |
| `CLAUDE_MODEL` | Não | `claude-sonnet-4-6` | Modelo Claude a usar |
| `MAX_TOKENS_RESUMO` | Não | `1200` | Max tokens para o resumo executivo |
| `MAX_TOKENS_CHAT` | Não | `400` | Max tokens por resposta do chat |
