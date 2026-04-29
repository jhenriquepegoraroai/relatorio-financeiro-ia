# Relatório Financeiro por IA

POC de leitura e análise automática dos relatórios financeiros de condomínios (Balancete + Conta Corrente) usando Claude AI.

## O que o app faz

- Extrai texto dos PDFs do Balancete Mensal e da Conta Corrente via `pdfplumber`
- Envia os dados para o Claude, que retorna um resumo executivo estruturado em JSON
- Exibe indicadores-chave: receita total, despesa total, resultado (superávit/déficit) e inadimplência
- Lista as 5 maiores receitas e despesas do mês
- Gera alertas automáticos para o síndico
- Disponibiliza um chat para perguntas livres sobre os relatórios

## Pré-requisitos

- Python 3.10+
- [Anthropic API Key](https://console.anthropic.com/)

## Instalação

```bash
pip install -r requirements.txt
```

## Configuração

Crie um arquivo `.env` na raiz do projeto:

```
ANTHROPIC_API_KEY=sk-ant-...
```

Ou informe a chave diretamente no sidebar do app ao abrir.

## Como usar

```bash
streamlit run app.py
```

1. Abra `http://localhost:8501` no navegador
2. No sidebar, escolha **Usar arquivos padrão** (se os PDFs já estão nos caminhos configurados) ou **Fazer upload** para enviar os arquivos manualmente
3. Clique em **Gerar Resumo Executivo**
4. Use o chat na parte inferior para fazer perguntas sobre os relatórios

## Estrutura do projeto

```
resolva-facil-IA-poc/
├── app.py            # Aplicação Streamlit completa
├── requirements.txt  # Dependências Python
└── .env              # Chave da API (não versionar)
```

## Stack

| Componente | Tecnologia |
|---|---|
| Interface | Streamlit |
| IA | Claude (claude-sonnet-4-6) via Anthropic SDK |
| Leitura de PDF | pdfplumber |
| Variáveis de ambiente | python-dotenv |
