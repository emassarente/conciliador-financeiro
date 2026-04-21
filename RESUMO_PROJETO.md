# Sistema de Conciliação Financeira — Resumo de Desenvolvimento

**Projeto:** Automação Lage — Conciliação Financeira  
**Empresa:** Afrika Consultoria e Tecnologia da Informação Ltda  
**Stack:** Python · Streamlit · pandas · SQLite · pdfplumber · scikit-learn · rapidfuzz

---

## Visão Geral

Foi desenvolvido do zero um sistema completo de conciliação financeira automatizada, capaz de cruzar lançamentos do Razão Contábil (gerado pelo Domínio) com extratos bancários de múltiplos bancos e formatos. O sistema reduz drasticamente o trabalho manual de conciliação, que antes era feito 100% em planilhas Excel.

---

## O que foi construído

### 1. Infraestrutura e Banco de Dados
Criação de uma base SQLite com estrutura completa para armazenar:
- Lançamentos do Razão (com hash de deduplicação)
- Lançamentos de Extrato bancário
- Resultado das conciliações (com nível de confiança)
- Padrões aprendidos pelo sistema (histórico de conciliações confirmadas)
- Log de importações com rastreabilidade por arquivo

A base mantém histórico de até 3 anos sem apagar dados, e evita duplicação automática por hash.

---

### 2. Parsers de Importação

#### Razão Contábil (Domínio)
Parser desenvolvido especificamente para o formato real do Domínio exportado pela empresa:
- Linha 1: Empresa | Linha 2: CNPJ | Linha 3: Período
- Linha 7: cabeçalho de colunas
- Linha 8: conta (código + nome)
- Detecta e ignora linhas de saldo anterior, totalizadores e linhas em branco
- Suporta `.xls` e `.xlsx`

#### Extratos Bancários
Foram desenvolvidos parsers para **7 bancos/formatos**, cada um com suas particularidades:

| Banco | Formato | Particularidade |
|---|---|---|
| **Itaú** (antigo) | PDF com tabelas | Data no formato `02 / jan`, valor em coluna separada |
| **Itaú** (novo, set/2025+) | PDF texto corrido | Sem tabelas; valor negativo = débito; inclui CNPJ do favorecido |
| **Itaú** | Excel (.xlsx) | Cabeçalho de metadados nas primeiras linhas |
| **Banco do Brasil** | PDF com tabela 8 colunas | Valor e tipo (D/C) juntos na mesma célula: `73,80 D` |
| **Bradesco** | PDF texto livre | Linhas com/sem data, PIX como linha só com doc+valor |
| **CEF** | PDF | Prefixo na descrição define D/C |
| **XP Investimentos** | PDF | Valor com sinal |
| **Nexoos** | PDF | Caracteres duplicados por extração |

O dispatcher detecta o banco automaticamente pelo nome do arquivo, sem necessidade de configuração manual.

---

### 3. Engine de Conciliação — 4 Níveis

O coração do sistema executa quatro níveis de match em sequência, do mais preciso ao mais inteligente:

#### Nível 0 — Match Aprendido (ML)
Usa TF-IDF + Regressão Logística treinada com os pares confirmados manualmente ao longo do tempo. Conforme o usuário valida conciliações, o sistema aprende os padrões e passa a sugerir automaticamente nas próximas rodadas.

#### Nível 1 — Match Exato
Cruzamento por data + valor idêntico + similaridade de texto ≥ 85%. Rápido e de alta precisão para lançamentos rotineiros.

#### Nível 2 — Match por Combinação
Dois cenários cobertos:
- **1 Razão → N Extrato**: um lançamento do razão é coberto por múltiplos extratos (ex: uma nota fiscal paga em duas parcelas)
- **N Razão → 1 Extrato**: vários lançamentos do razão somam um único extrato (ex: IRPJ + CSLL pagos juntos via SISPAG)

#### Nível 3 — Match por Similaridade
Usa `rapidfuzz` para comparar descrições com tolerância configurável de data (±3 dias) e valor (±0,5%). Captura variações de nomenclatura entre sistemas.

---

### 4. Dashboard Streamlit

Interface web completa com:
- **Upload múltiplo**: aceita N arquivos de Razão + N arquivos de Extrato simultaneamente (ex: 1 razão anual + 12 extratos mensais)
- **Execução da conciliação** com barra de progresso
- **Tabela de resultados** com filtros por status, banco, conta e período
- **Badges visuais** por nível de match: Exato, Combinação, Similaridade, Aprendido, Não Conciliado
- **Conciliação manual**: lançamentos não conciliados automaticamente podem ser confirmados manualmente — e o par confirmado é salvo para treinar o modelo ML
- **Expansão de linha**: clique para ver detalhes completos do par razão/extrato
- Sem dados fictícios ou botão de demonstração — trabalha apenas com dados reais

---

### 5. Aprendizado de Máquina

O sistema acumula padrões de conciliação confirmados (automáticos e manuais) na base de dados. A cada nova execução, o modelo ML é retreinado com os pares conhecidos e passa a sugerir conciliações com base no histórico — aumentando a taxa de acerto automaticamente com o uso.

---

## Tabela de Tempo de Desenvolvimento

| Módulo / Tarefa | Estimativa de Tempo |
|---|---|
| Análise dos formatos reais dos arquivos (Razão + Extratos) | 6h |
| Estrutura do banco de dados SQLite + migrations | 4h |
| Parser do Razão Contábil (Domínio) | 5h |
| Parser Itaú PDF formato antigo (tabelas) | 4h |
| Parser Itaú PDF formato novo (texto corrido, set/2025+) | 3h |
| Parser Itaú Excel | 2h |
| Parser Banco do Brasil PDF | 3h |
| Parser Bradesco PDF | 4h |
| Parser CEF, XP, Nexoos | 4h |
| Dispatcher automático por nome de arquivo | 1h |
| Engine de match exato (Nível 1) | 5h |
| Engine de match por combinação 1→N e N→1 (Nível 2) | 8h |
| Engine de match por similaridade (Nível 3) | 4h |
| Engine de aprendizado ML — TF-IDF + Logistic Regression (Nível 0) | 10h |
| Dashboard Streamlit — layout, filtros, badges, tabela | 12h |
| Upload múltiplo + merge de DataFrames | 3h |
| Conciliação manual + salvamento de padrões aprendidos | 4h |
| Testes e ajustes nos parsers com arquivos reais | 6h |
| **Total estimado** | **~88 horas** |

---

## O que falta para funcionar perfeitamente

### Alta prioridade

| Item | Descrição |
|---|---|
| **Testes com arquivos reais completos** | Rodar uma conciliação real com Razão anual + 12 extratos e validar os resultados de ponta a ponta |
| **Ajuste fino dos thresholds de similaridade** | Os limites de % de match (hoje 85% texto, 0,5% valor) podem precisar de calibração com os dados reais da empresa |
| **Tratamento do Daycoval** | Extratos são imagens escaneadas — necessário solicitar ao banco o formato OFX/CSV ou contratar OCR |
| **Exportação de relatório** | Gerar Excel/PDF com o resultado da conciliação para auditoria e entrega ao contador |

### Média prioridade

| Item | Descrição |
|---|---|
| **Normalização de nomes de favorecidos** | Itaú novo traz razão social completa; Itaú antigo traz abreviado — o match de similaridade pode não cruzar corretamente |
| **Suporte a OFX/CSV genérico** | Alguns bancos oferecem OFX — suportar esse formato cobriria bancos não listados |
| **Tela de configuração de contas** | Associar cada conta bancária a um código do Razão para pré-filtrar os lançamentos antes da conciliação |
| **Performance em grandes volumes** | Para arquivos com 1.000+ lançamentos, a conciliação pode levar alguns segundos — avaliar otimização |

### Baixa prioridade

| Item | Descrição |
|---|---|
| **Autenticação de usuário** | Hoje sem login — adequado para uso local, mas necessário se for acessado em rede |
| **Multi-empresa** | Hoje configurado para AFRIKA — parametrizar para outras empresas do grupo |
| **Integração direta com Domínio** | Automatizar a exportação do Razão via RPA, eliminando o passo manual de baixar o arquivo |

---

## Status atual

O sistema está **funcional e operacional** para uso com os arquivos reais da empresa. Todos os bancos com que a empresa opera (Itaú, Banco do Brasil, Bradesco) têm parsers testados e validados com os PDFs reais. A conciliação automática opera em 4 níveis e aprende com o uso. O próximo passo natural é rodar a primeira conciliação real completa e calibrar os resultados.
