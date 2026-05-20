# Relatório Financeiro com IA — Documentação Executiva

> **Status:** Prova de Conceito (POC) funcional em ambiente local
> **Autor:** Henrique Pegoraro
> **Data:** Maio/2026
> **Repositório:** [github.com/jhenriquepegoraroai/relatorio-financeiro-ia](https://github.com/jhenriquepegoraroai/relatorio-financeiro-ia)

---

## 1. Visão Executiva

### O que é
Sistema que transforma dados financeiros brutos de condomínios em **resumos executivos automáticos** e habilita um **chat interativo** sobre esses dados, usando modelos de linguagem (Claude/Anthropic).

### Para que serve
Reduzir o tempo que síndicos e gestores levam para entender a saúde financeira de um condomínio: hoje a leitura de balancete + extrato + relatório de inadimplência leva 15–30 minutos por mês. O sistema entrega o mesmo entendimento em segundos, com indicadores, alertas e capacidade de "conversar com os números".

### Status atual
- Funciona ponta a ponta com dados reais (Databricks da Lello)
- 4 funcionalidades principais validadas (resumo, chat, gráficos, alertas proativos)
- Custo médio observado: **~R$ 0,25 por relatório completo** (1 condomínio, 2 meses)
- Falta para produção: autenticação, deploy gerenciado, controle de uso por usuário, fallback de provider

---

## 2. Arquitetura

```
┌─────────────────────────────────────────────────────────────┐
│  Navegador (usuário)                                        │
└──────────────────────────┬──────────────────────────────────┘
                           │ HTTPS
┌──────────────────────────▼──────────────────────────────────┐
│  App Streamlit (Python)                                     │
│  ┌──────────┬──────────┬──────────┬──────────────────────┐ │
│  │ Resumo   │ Chat     │ Gráficos │ Alertas Proativos    │ │
│  └────┬─────┴────┬─────┴────┬─────┴───────┬──────────────┘ │
│       │          │          │             │                 │
│  ┌────▼──────────▼──────────▼─────────────▼──────────────┐ │
│  │  Camada `core/`                                       │ │
│  │  • claude.py  — chamadas à API + retry + cache        │ │
│  │  • extractor.py — Databricks/PDF/Excel                │ │
│  │  • cost.py    — cálculo de custo e comparativo        │ │
│  │  • db_log.py  — auditoria local (SQLite)              │ │
│  │  • models.py  — schemas Pydantic (ResumoFinanceiro)   │ │
│  └────┬──────────────────────┬────────────────────────────┘ │
└───────│──────────────────────│──────────────────────────────┘
        │                      │
   ┌────▼──────────┐    ┌──────▼─────────┐
   │  Anthropic    │    │  Databricks    │
   │  Claude API   │    │  (Spark SQL)   │
   │  (Sonnet/Haiku)│    │  Tabelas Lello │
   └───────────────┘    └────────────────┘
```

### Stack
| Camada | Tecnologia |
|---|---|
| UI | Streamlit 1.40+ |
| Backend | Python 3.11+ |
| IA | Anthropic Claude (Sonnet 4.6, Haiku 4.5) |
| Dados | Databricks Connect (Spark SQL) |
| Validação | Pydantic 2 |
| Visualização | Plotly |
| Logs | SQLite local |

### Princípios de design
- **Stateless por sessão:** cada usuário tem seu próprio estado; nada é compartilhado
- **Cache agressivo:** prompts e dados são cacheados no Claude (até 90% de economia em chat)
- **Fail-soft:** falhas de cluster, rate-limit e timeout são tratadas com retry automático
- **Auditável:** cada chamada à IA é registrada com tokens, custo e contexto

---

## 3. Origem dos Dados

### Hoje — Databricks (produção da Lello)
O sistema lê duas tabelas no schema `lello_datalake_bronze.4_api`:

| Tabela | Conteúdo | Uso |
|---|---|---|
| `balancete_consolidado` | Receitas e despesas agregadas por categoria/mês | Resumo executivo + indicadores |
| `portal_sindico_contacorrente` | Lançamentos individuais (data, histórico, débito, crédito) | Detalhamento + alertas |

**Fluxo:** o usuário seleciona uma referência (condomínio) → o app consulta as duas tabelas filtrando pelos N meses mais recentes → o texto consolidado é enviado para o Claude.

### Características
- **Cluster pode estar frio:** primeiro acesso do dia leva ~3 min para subir; o app espera até 5 min com mensagem "⏳ Cluster iniciando".
- **Volume médio:** 2 meses de um condomínio = ~40k tokens de contexto.
- **Cache TTL:** consultas Databricks ficam em cache local por 30 minutos.

### Futuro — Migração para API REST
A camada `core/extractor.py` é isolada — substituir Databricks por uma API REST é **mudança em um único arquivo**. Cenários:

| Cenário | Esforço | Vantagem |
|---|---|---|
| API retorna mesmo formato (lançamentos brutos) | Baixo (~4h) | Sem mudança no resto do sistema |
| API retorna dados já agregados | Baixo (~6h) | Permite usar Haiku no resumo (custo cai ~80%) |
| API com cache server-side | Médio (~16h) | Latência de extração cai de 2s → <300ms |

**Recomendação:** se a Lello vai expor uma API, vale agregá-la *antes* de devolver — o trabalho pesado de "fazer sentido do dado bruto" sai do modelo de linguagem e vira código simples e barato.

### Fallback — Upload manual
Se Databricks não estiver configurado, o app aceita upload de PDF (`pdfplumber`) ou XLSX (`openpyxl`) — útil para testes e demos sem dependência de infra.

---

## 4. Custos

### Modelos em uso

| Função | Modelo | Por que esse |
|---|---|---|
| Resumo Executivo | Claude Sonnet 4.6 | Raciocínio analítico para dados financeiros densos |
| Chat | Claude Haiku 4.5 | Respostas rápidas e baratas em Q&A |
| Classificação de gráfico | Claude Haiku 4.5 | Tarefa simples de estruturação |

### Preço unitário (Anthropic, maio/2026)

| Modelo | Input | Output | Cache read |
|---|---|---|---|
| Sonnet 4.6 | $3,00/MTok | $15,00/MTok | $0,30/MTok |
| Haiku 4.5 | $1,00/MTok | $5,00/MTok | $0,10/MTok |

### Custo observado em uso real

| Cenário | Tokens médios | Custo (USD) | Custo (BRL) |
|---|---|---|---|
| 1 resumo executivo (2 meses, Sonnet) | ~50k in / 10k out | $0,43 | R$ 2,45 |
| 1 mensagem de chat (com cache 98%) | ~3k in / 1,5k out | $0,01 | R$ 0,06 |
| 1 gráfico (classificação Haiku) | ~500 in / 100 out | $0,001 | R$ 0,01 |
| **Sessão típica completa** (1 resumo + 5 chats + 2 gráficos) | — | **$0,49** | **~R$ 2,80** |

### Projeção de custo em produção

| Volume | Custo mensal estimado |
|---|---|
| 100 condomínios × 4 acessos/mês | ~R$ 1.100 |
| 500 condomínios × 4 acessos/mês | ~R$ 5.600 |
| 2.000 condomínios × 4 acessos/mês | ~R$ 22.400 |

### Otimizações com potencial alto

1. **Trocar Sonnet por Haiku no resumo** — se o dado vier pré-estruturado (API agregada), Haiku entrega resultado equivalente a 1/3 do custo (~R$ 0,80 por relatório).
2. **Prompt caching mais agressivo** — chat já economiza 98%; o resumo pode cachear o esquema dos dados (cair de R$ 2,45 para ~R$ 1,80).
3. **Multi-provider** — comparativo já implementado (sidebar) mostra que Gemini 2.5 Pro custa ~85% menos que Sonnet para a mesma tarefa. Trocar provider em runtime é viável (feature já validada em branch).

---

## 5. Funcionalidades

### Geração de Resumo Executivo
Lê os últimos N meses de balancete + conta corrente e gera um JSON estruturado com:
- Indicadores (receita, despesa, resultado, inadimplência)
- Lista de receitas e despesas por categoria
- Inadimplentes
- Panorama em 3 bullets (sem valores monetários, foco em narrativa)
- Alertas (até 3 por período)

### Chat com os Relatórios
Interface conversacional onde o usuário faz perguntas em linguagem natural. O sistema:
- Mantém contexto da sessão
- Detecta automaticamente quando a resposta deve vir como gráfico
- Re-consulta o Databricks se o usuário pedir um período diferente
- Gera SQL automático quando necessário (e registra o SQL gerado para auditoria)

### Gráficos automáticos
6 tipos: receitas, despesas, comparativo, pizza, inadimplência, fluxo temporal. O modelo classifica o pedido e o app monta o Plotly correspondente.

### Alertas proativos
Acionados automaticamente no resumo, com 3 níveis (crítico / atenção / info):
- **Déficit financeiro** (crítico) — resultado do mês negativo
- **Inadimplência ≥ 15%** (crítico) ou **≥ 5%** (atenção) — % sobre receita total
- **Alta nas despesas ≥ 15%** (atenção) — variação entre período atual e anterior
- **Queda na receita ≥ 10%** (atenção) — variação entre período atual e anterior
- **Margem financeira estreita** (info) — resultado positivo mas < 3% da receita

### Comparativo de custo em tempo real
Sidebar mostra:
- Custo USD/BRL acumulado da sessão
- Número de chamadas
- % de cache hit
- Comparativo lado a lado: o que custaria a mesma sessão na OpenAI e no Google

### Histórico auditável
Toda interação é registrada em SQLite local com:
- Timestamp, condomínio, pergunta, resposta
- Modelo usado, tokens (input/output/cache)
- SQL executado quando aplicável

---

## 6. Desafios de Implantação em Produção

### Críticos — exigem decisão antes de subir

| Desafio | Impacto | Possível solução |
|---|---|---|
| **Autenticação** | Hoje qualquer pessoa com URL acessa | OAuth corporativo (Azure AD / Google Workspace) ou SSO Lello |
| **Multi-tenant** | Não há separação por usuário/empresa | Sessões isoladas + filtro por permissão no Databricks |
| **Chaves de API expostas** | API key no `.env` local | Cofre de segredos (Azure Key Vault, AWS Secrets Manager) |
| **Database de logs** | SQLite local não escala | PostgreSQL gerenciado (Azure Postgres, Supabase) |
| **Hospedagem** | Roda local em laptop | Streamlit Cloud (rápido), Azure App Service ou container em Kubernetes |

### Importantes — riscos operacionais

| Desafio | Impacto | Mitigação |
|---|---|---|
| **Custo descontrolado** | Usuário pode gastar muito em sessão longa | Limite de chamadas por usuário/dia; alerta visual de gasto |
| **Cluster Databricks frio** | Primeira chamada do dia leva ~3 min | Cluster sempre-ligado (custo $$$) ou aceitar latência inicial |
| **Rate limit Anthropic** | Pico de uso pode bater no limite | Tier corporativo Anthropic; fila de requisições; fallback para Gemini |
| **Dados sensíveis nos prompts** | Dados financeiros saem da rede Lello para Anthropic | Anthropic não treina em dados da API; contrato BAA disponível; ou rodar via AWS Bedrock dentro da VPC |
| **Drift do modelo** | Sonnet 4.6 pode ser depreciado em 12-18 meses | Versionamento de prompt + suite de testes regressivos |

### Operacionais — boas práticas

- **Observabilidade:** integrar com Datadog/Sentry para erros e latência
- **Métricas de negócio:** dashboard separado mostrando uso, custo por condomínio, satisfação
- **Versionamento de prompt:** prompts em `prompts/*.txt` versionados no Git; A/B test entre versões
- **Backup de logs:** SQLite → Postgres com replicação automática
- **CI/CD:** GitHub Actions para deploy automático em staging → produção
- **Testes:** suite atual cobre cost.py e formatters; precisa cobrir extractor.py e claude.py

---

## 7. Riscos e Dependências

### Dependência crítica
- **Anthropic Claude API** — se a API ficar fora do ar ou aumentar preço, todo o sistema para. Mitigação: implementar fallback para OpenAI/Google (camada já existe em branch).

### Dependências moderadas
- **Databricks Lello** — se cluster cair ou tabela mudar de schema, o app quebra. Mitigação: monitoramento + alertas.
- **Streamlit** — framework jovem, breaking changes entre versões. Mitigação: pinar versão em `requirements.txt`.

### Riscos de produto
- **Confiança do usuário em respostas geradas por IA** — síndico pode tomar decisão baseada em número errado. Mitigação: sempre exibir os dados brutos junto com o resumo; marcar respostas com "gerado por IA — confira"; auditoria via logs.
- **LGPD** — dados financeiros são pessoais sensíveis. Mitigação: contrato com Anthropic, criptografia em trânsito (já há), não armazenar dados do cliente em logs (já não armazena).

---

## 8. Roadmap Sugerido

### Fase 1 — Hardening (2-3 semanas)
- [ ] Autenticação SSO
- [ ] Cofre de segredos para chaves de API
- [ ] PostgreSQL para logs
- [ ] Deploy em ambiente gerenciado (staging)

### Fase 2 — Piloto fechado (4 semanas)
- [ ] 10-20 condomínios em piloto controlado
- [ ] Métricas de uso e satisfação
- [ ] Suite de testes regressivos para o resumo
- [ ] Controle de custo por usuário

### Fase 3 — Escala (8 semanas)
- [ ] Multi-provider em runtime (OpenAI/Gemini como fallback)
- [ ] Otimização de custo (Haiku no resumo se dado vier agregado)
- [ ] Dashboard administrativo (uso, custo, qualidade)
- [ ] Rollout gradual (10% → 50% → 100%)

### Fase 4 — Evolução
- [ ] API REST exposta para integrar com outros sistemas Lello
- [ ] Resumos comparativos entre múltiplos condomínios
- [ ] Alertas proativos por email/WhatsApp
- [ ] Versão mobile (PWA)

---

## 9. Conclusão para a Diretoria

**O que está pronto:** uma POC funcional, com dados reais, custo baixo e arquitetura limpa. Foi possível ir do dado bruto do Databricks até o relatório executivo + chat conversacional em poucas semanas.

**O que falta para produção:** essencialmente trabalho de **engenharia de plataforma** — autenticação, deploy gerenciado, banco de logs escalável. Nada de IA aqui é "experimental" — a parte de modelo já é estável e barata.

**Decisão a tomar:** continuar como **POC interna** (custo zero, valor de aprendizado) ou investir em **hardening para piloto** (custo de ~2-3 semanas de engenheiro, valor potencial de eliminar 80% do tempo de leitura de balancete para a equipe).

**Recomendação:** dado o custo operacional baixo (~R$ 2,80/sessão) e o tempo economizado (~25 min por condomínio), o ROI é positivo a partir de qualquer volume relevante de uso. O risco maior **não é técnico — é de adoção** (síndicos confiarem em respostas de IA). Sugiro um piloto fechado de 10-20 condomínios antes de qualquer escala.
