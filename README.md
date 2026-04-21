# 💰 Sistema de Conciliação Financeira Automatizada

Sistema inteligente de conciliação entre o **Razão Contábil** (exportado do sistema Domínio) e o **Extrato Bancário**, com múltiplos níveis de match automático e dashboard visual.

---

## 📁 Estrutura de Pastas

```
conciliacao_financeira/
│
├── rpa/
│   └── dominio_bot.py        # Robô RPA que faz login no Domínio e baixa o Razão
│
├── import_/
│   ├── razao_parser.py       # Lê e processa o arquivo do Razão Contábil
│   └── extrato_parser.py     # Lê e processa o Extrato Bancário
│
├── engine/
│   ├── exact_match.py        # Nível 1: Match exato (valor + data)
│   ├── combination_match.py  # Nível 2: Soma de múltiplos lançamentos
│   ├── similarity_match.py   # Nível 3: Similaridade de texto (rapidfuzz)
│   └── conciliacao_engine.py # Orquestrador dos 3 níveis
│
├── ui/
│   └── dashboard.py          # Interface visual Streamlit
│
├── data/
│   ├── gerar_amostras.py     # Gera arquivos de exemplo para teste
│   └── samples/              # Pasta onde ficam os arquivos de dados
│
├── main.py                   # Ponto de entrada via linha de comando
├── requirements.txt          # Dependências Python
└── README.md                 # Este arquivo
```

---

##  Instalação

### 1. Criar ambiente virtual (recomendado)
```bash
python -m venv venv
source venv/bin/activate        # Mac/Linux
venv\Scripts\activate           # Windows
```

### 2. Instalar dependências
```bash
pip install -r requirements.txt
```

### 3. Instalar o navegador para o RPA (somente se for usar o robô)
```bash
playwright install chromium
```

---

## ▶️ Como Usar

### Opção 1 — Dashboard Visual (recomendado para iniciantes)
```bash
streamlit run ui/dashboard.py
```
Abre no navegador em `http://localhost:8501`. Faça upload dos arquivos e clique em **Executar Conciliação**.

### Opção 2 — Dados de demonstração (para testar sem arquivos reais)
```bash
# Gera os arquivos de exemplo primeiro:
python data/gerar_amostras.py

# Depois abre o dashboard e use os arquivos gerados em data/samples/
streamlit run ui/dashboard.py
```

### Opção 3 — Linha de Comando (para automação/agendamento)
```bash
# Conciliação direta com arquivos locais:
python main.py --razao data/samples/razao_exemplo.xlsx \
               --extrato data/samples/extrato_exemplo.xlsx

# Filtrar por conta específica:
python main.py --razao data/razao.xlsx --extrato data/extrato.xlsx --conta 1.1.1.01

# Com o robô RPA (baixa automaticamente do Domínio):
python main.py --rpa \
               --usuario SEU_LOGIN \
               --senha SUA_SENHA \
               --conta 1.1.1.01 \
               --data-ini 01/01/2024 \
               --data-fim 31/01/2024 \
               --extrato data/extrato.xlsx
```

---

## 🎨 Cores no Dashboard

| Cor | Status | Significado |
|-----|--------|-------------|
| 🟢 Verde | CONCILIADO | Match exato (valor + data) — confiança 100% |
| 🟡 Amarelo | MATCH_COMBINADO | Soma de 2-3 lançamentos do extrato = 1 do Razão — confiança 85% |
| 🔵 Azul | MATCH_PROVAVEL | Similaridade de texto (≥80%) — confiança variável |
| 🔴 Vermelho | NÃO CONCILIADO | Sem correspondente encontrado — revisão manual necessária |

---

## 🔧 Níveis de Conciliação

### Nível 1 — Match Exato
- Valor igual (tolerância: R$ 0,01)
- Diferença de data: até **3 dias**
- Resultado: `CONCILIADO` | 100% de confiança

### Nível 2 — Match Combinado
- Soma de **até 3 lançamentos** do extrato = 1 lançamento do Razão
- Tolerância de valor: **zero** — a soma deve bater exatamente
- Exemplo: Razão R$ 1.000 = Extrato R$ 600 + R$ 400
- Resultado: `MATCH_COMBINADO` | 85% de confiança

### Nível 3 — Match por Similaridade
- Compara a descrição/histórico usando **fuzzy matching** (rapidfuzz)
- Score mínimo: **80%** (configurável no dashboard)
- Exemplo: "PIX JOAO SILVA SANTOS" ≈ "PIX J SILVA"
- Resultado: `MATCH_PROVAVEL` | confiança = score de similaridade

### Nível 4 — Não Conciliado
- Lançamentos que não encontraram par em nenhum dos 3 níveis
- Exibidos lado a lado (Razão × Extrato) para revisão manual

---

## 🤖 Configurando o RPA do Domínio

O arquivo `rpa/dominio_bot.py` foi criado com a estrutura do robô. Para funcionar com **seu** Domínio Web, você precisa ajustar os seletores HTML:

1. Abra o Domínio Web no Chrome
2. Pressione **F12** → aba **Inspetor**
3. Inspecione os campos de login, menus e botões
4. Atualize os seletores no `dominio_bot.py` (marcados com `⚠️`)

Campos a ajustar:
- `_fazer_login()` → seletores do campo usuário, senha e botão entrar
- `_navegar_para_razao()` → texto/ID do menu e submenu
- `_baixar_razao()` → campos de filtro (conta, datas) e botão exportar Excel

---

## 📋 Formato dos Arquivos de Entrada

### Razão Contábil (exportado do Domínio)
O sistema detecta automaticamente:
- Linhas de **identificação de conta** (ex: `CONTA: 1.1.1.01 - BANCO BB`)
- Linhas de **lançamento** (tem data válida na primeira coluna)
- Linhas de **totalizador** (TOTAL, SALDO, etc.) — ignoradas automaticamente

Colunas esperadas: `Data | Histórico | Documento | Débito | Crédito | Saldo`

### Extrato Bancário
O sistema detecta automaticamente as colunas por nome. Aceita variações como:
- `Data` / `Dt` / `Data Lançamento`
- `Descrição` / `Histórico` / `Memo` / `Complemento`
- `Valor` / `Vlr` / `Amount`
- `Tipo` / `D/C` / `Natureza`
- `Documento` / `Doc` / `Referência` / `TXID`

---

## ⚙️ Requisitos

- Python 3.9+
- Ver `requirements.txt` para pacotes

---

## 💡 Dicas

- **Primeiro teste**: Use os dados de demonstração clicando em "Carregar Dados de Demonstração" no dashboard
- **Ajuste o score**: Se o sistema estiver sendo muito conservador, reduza o score mínimo de similaridade para 70-75%
- **Tolerância de datas**: Se seus lançamentos têm muita diferença de data, aumente a tolerância no `exact_match.py`
- **Performance**: Para bases grandes (>500 lançamentos), desative a similaridade de texto para agilizar
