#!/bin/bash
# =============================================================================
# SCRIPT DE DEPLOY - SISTEMA DE CONCILIAÇÃO FINANCEIRA
# Compatível com macOS (Apple Silicon M4) e Linux
# =============================================================================

echo "🚀 Iniciando deploy do Sistema de Conciliação..."

# Cores para output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Diretório do projeto
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

echo -e "${YELLOW}📂 Diretório do projeto: $PROJECT_DIR${NC}"

# Detecta sistema operacional
OS_TYPE="$(uname -s)"
if [[ "$OS_TYPE" == "Darwin" ]]; then
    echo -e "${YELLOW}💻 Sistema: macOS (Apple Silicon)${NC}"
else
    echo -e "${YELLOW}💻 Sistema: Linux${NC}"
fi

# 1. Verificar Python
echo -e "\n${YELLOW}🐍 Verificando Python...${NC}"
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}❌ Python 3 não encontrado.${NC}"
    if [[ "$OS_TYPE" == "Darwin" ]]; then
        echo -e "${YELLOW}💡 Instale via Homebrew: brew install python@3.11${NC}"
    else
        echo -e "${YELLOW}💡 Instale: sudo apt install python3${NC}"
    fi
    exit 1
fi
PYTHON_VERSION=$(python3 --version)
echo -e "${GREEN}✅ $PYTHON_VERSION encontrado${NC}"

# 2. Criar/ativar ambiente virtual
echo -e "\n${YELLOW}📦 Configurando ambiente virtual...${NC}"
if [ ! -d ".venv" ]; then
    echo "Criando novo ambiente virtual..."
    python3 -m venv .venv
fi
source .venv/bin/activate
echo -e "${GREEN}✅ Ambiente virtual ativado${NC}"

# 3. Instalar dependências
echo -e "\n${YELLOW}📥 Instalando dependências...${NC}"
pip install --upgrade pip -q
pip install -r requirements.txt -q
echo -e "${GREEN}✅ Dependências instaladas${NC}"

# 4. Verificar banco de dados
echo -e "\n${YELLOW}💾 Verificando banco de dados...${NC}"
if [ ! -f "database/conciliacao.db" ]; then
    echo "Criando banco de dados..."
    python3 -c "from database.db_manager import DatabaseManager; DatabaseManager()"
fi
echo -e "${GREEN}✅ Banco de dados OK${NC}"

# 5. Criar diretórios necessários
echo -e "\n${YELLOW}📁 Criando diretórios...${NC}"
mkdir -p data/extratos_gas
mkdir -p logs
echo -e "${GREEN}✅ Diretórios criados${NC}"

# 6. Verificar configuração Streamlit
echo -e "\n${YELLOW}⚙️  Verificando configuração...${NC}"
if [ ! -f ".streamlit/config.toml" ]; then
    echo -e "${RED}❌ Arquivo .streamlit/config.toml não encontrado${NC}"
    exit 1
fi
echo -e "${GREEN}✅ Configuração OK${NC}"

# 7. Testar importação de módulos
echo -e "\n${YELLOW}🧪 Testando módulos...${NC}"
python3 -c "
from database.db_manager import DatabaseManager
from engine.conciliacao_engine import ConciliacaoEngine
from import_.razao_parser import RazaoParser
from import_.extrato_c6bank_parser import C6BankParser
print('✅ Todos os módulos importados com sucesso')
" || {
    echo -e "${RED}❌ Erro ao importar módulos${NC}"
    exit 1
}

echo -e "\n${GREEN}════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}✅ DEPLOY CONCLUÍDO COM SUCESSO!${NC}"
echo -e "${GREEN}════════════════════════════════════════════════════════${NC}"

echo -e "\n${YELLOW}📋 Próximos passos:${NC}"
if [[ "$OS_TYPE" == "Darwin" ]]; then
    echo -e "1. ${YELLOW}[TESTE LOCAL]${NC} Inicie o servidor:"
    echo -e "   ${GREEN}./start.sh${NC}"
    echo -e ""
    echo -e "2. Acesse: ${GREEN}http://localhost:8502${NC}"
    echo -e ""
    echo -e "3. ${YELLOW}[PRODUÇÃO]${NC} Para deploy no servidor:"
    echo -e "   - Copie a pasta para o servidor Linux"
    echo -e "   - Configure Nginx (ver DEPLOY.md)"
    echo -e "   - Acesse: ${GREEN}https://c2minstituto.com.br/conciliador${NC}"
else
    echo -e "1. Configure o proxy reverso (Nginx) para:"
    echo -e "   ${GREEN}c2minstituto.com.br/conciliador${NC} → ${GREEN}localhost:8502${NC}"
    echo -e ""
    echo -e "2. Inicie o servidor:"
    echo -e "   ${GREEN}./start.sh${NC} ou ${GREEN}sudo systemctl start conciliador${NC}"
    echo -e ""
    echo -e "3. Acesse: ${GREEN}https://c2minstituto.com.br/conciliador${NC}"
fi
echo -e ""
echo -e "${YELLOW}💡 Login padrão: igp@igp.com.br / igp@123${NC}"
