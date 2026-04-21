#!/bin/bash
# =============================================================================
# SCRIPT DE INSTALAÇÃO AUTOMÁTICA NO SERVIDOR
# Execute este script VIA SSH no servidor NameCheap
# =============================================================================

echo "🚀 Instalação Automática - Sistema de Conciliação"
echo "=================================================="

# Cores
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

# Configurações do servidor (AJUSTE CONFORME SEU SERVIDOR)
USUARIO_CPANEL="dese7735"  # Seu usuário do cPanel
DOMINIO="c2minstituto.com.br"
PASTA_INSTALACAO="/home/$USUARIO_CPANEL/conciliador"
PORTA_STREAMLIT=8502

echo -e "${YELLOW}📋 Configurações:${NC}"
echo "   Usuário: $USUARIO_CPANEL"
echo "   Domínio: $DOMINIO/conciliador"
echo "   Pasta: $PASTA_INSTALACAO"
echo "   Porta: $PORTA_STREAMLIT"
echo ""

# 1. Verificar se está no servidor
if [ ! -d "/home/$USUARIO_CPANEL" ]; then
    echo -e "${RED}❌ Este script deve ser executado NO SERVIDOR via SSH${NC}"
    echo -e "${YELLOW}💡 Conecte via SSH primeiro:${NC}"
    echo "   ssh $USUARIO_CPANEL@$DOMINIO"
    exit 1
fi

# 2. Verificar Python
echo -e "${YELLOW}🐍 Verificando Python...${NC}"
if command -v python3.11 &> /dev/null; then
    PYTHON_CMD="python3.11"
elif command -v python3.10 &> /dev/null; then
    PYTHON_CMD="python3.10"
elif command -v python3.9 &> /dev/null; then
    PYTHON_CMD="python3.9"
elif command -v python3 &> /dev/null; then
    PYTHON_CMD="python3"
else
    echo -e "${RED}❌ Python 3.9+ não encontrado${NC}"
    echo -e "${YELLOW}💡 Entre em contato com o suporte NameCheap para instalar Python${NC}"
    exit 1
fi

PYTHON_VERSION=$($PYTHON_CMD --version)
echo -e "${GREEN}✅ $PYTHON_VERSION encontrado${NC}"

# 3. Criar diretório de instalação
echo -e "\n${YELLOW}📁 Criando diretórios...${NC}"
mkdir -p $PASTA_INSTALACAO
cd $PASTA_INSTALACAO

# 4. Verificar se o arquivo tar.gz foi enviado
if [ ! -f "conciliacao_producao.tar.gz" ]; then
    echo -e "${RED}❌ Arquivo conciliacao_producao.tar.gz não encontrado${NC}"
    echo -e "${YELLOW}💡 Faça upload do arquivo primeiro:${NC}"
    echo "   scp conciliacao_producao.tar.gz $USUARIO_CPANEL@$DOMINIO:$PASTA_INSTALACAO/"
    exit 1
fi

# 5. Extrair arquivos
echo -e "${YELLOW}📦 Extraindo arquivos...${NC}"
tar -xzf conciliacao_producao.tar.gz
mv conciliacao_financeira/* .
rmdir conciliacao_financeira
rm conciliacao_producao.tar.gz
echo -e "${GREEN}✅ Arquivos extraídos${NC}"

# 6. Criar ambiente virtual
echo -e "\n${YELLOW}🔧 Criando ambiente virtual...${NC}"
$PYTHON_CMD -m venv .venv
source .venv/bin/activate
echo -e "${GREEN}✅ Ambiente virtual criado${NC}"

# 7. Instalar dependências
echo -e "\n${YELLOW}📥 Instalando dependências...${NC}"
pip install --upgrade pip -q
pip install -r requirements.txt -q
echo -e "${GREEN}✅ Dependências instaladas${NC}"

# 8. Configurar banco de dados SQLite
echo -e "\n${YELLOW}💾 Configurando banco de dados...${NC}"
mkdir -p database
# O banco será criado automaticamente na primeira execução
echo -e "${GREEN}✅ Banco configurado (dese7735_conciliador via SQLite)${NC}"

# 9. Criar script de inicialização
echo -e "\n${YELLOW}📝 Criando script de inicialização...${NC}"
cat > start_servidor.sh << 'EOFSTART'
#!/bin/bash
cd /home/dese7735/conciliador
source .venv/bin/activate
nohup streamlit run ui/dashboard.py \
    --server.port=8502 \
    --server.headless=true \
    --server.baseUrlPath="/conciliador" \
    --server.address=0.0.0.0 \
    --browser.gatherUsageStats=false \
    > logs/streamlit.log 2>&1 &
echo "🚀 Servidor iniciado na porta 8502"
echo "📋 Ver logs: tail -f logs/streamlit.log"
EOFSTART

chmod +x start_servidor.sh

# 10. Criar script de parada
cat > stop_servidor.sh << 'EOFSTOP'
#!/bin/bash
pkill -f "streamlit run"
echo "⛔ Servidor parado"
EOFSTOP

chmod +x stop_servidor.sh

# 11. Criar diretório de logs
mkdir -p logs

echo -e "\n${GREEN}════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}✅ INSTALAÇÃO CONCLUÍDA COM SUCESSO!${NC}"
echo -e "${GREEN}════════════════════════════════════════════════════════${NC}"

echo -e "\n${YELLOW}📋 Próximos passos:${NC}"
echo -e "1. Iniciar o servidor:"
echo -e "   ${GREEN}./start_servidor.sh${NC}"
echo -e ""
echo -e "2. Configurar proxy reverso no cPanel (veja INSTRUCOES_CPANEL.txt)"
echo -e ""
echo -e "3. Acessar: ${GREEN}https://$DOMINIO/conciliador${NC}"
echo -e ""
echo -e "${YELLOW}💡 Comandos úteis:${NC}"
echo -e "   Iniciar:  ./start_servidor.sh"
echo -e "   Parar:    ./stop_servidor.sh"
echo -e "   Ver logs: tail -f logs/streamlit.log"
echo -e "   Status:   ps aux | grep streamlit"
