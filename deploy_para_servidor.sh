#!/bin/bash
# =============================================================================
# SCRIPT DE DEPLOY PARA SERVIDOR - EXECUTE NO SEU MAC
# =============================================================================

echo "🚀 Deploy para Servidor NameCheap"
echo "=================================="

# CONFIGURAÇÕES - AJUSTE AQUI
USUARIO_SSH="dese7735"
SERVIDOR="c2minstituto.com.br"
PASTA_DESTINO="/home/dese7735/conciliador"

# Cores
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${YELLOW}📋 Configurações:${NC}"
echo "   Servidor: $SERVIDOR"
echo "   Usuário: $USUARIO_SSH"
echo "   Destino: $PASTA_DESTINO"
echo ""

# 1. Verificar se está na pasta correta
if [ ! -f "ui/dashboard.py" ]; then
    echo -e "${RED}❌ Execute este script da pasta conciliacao_financeira${NC}"
    exit 1
fi

# 2. Criar pacote
echo -e "${YELLOW}📦 Criando pacote...${NC}"
cd ..
tar -czf conciliacao_producao.tar.gz \
    --exclude='conciliacao_financeira/.venv' \
    --exclude='conciliacao_financeira/database/*.db' \
    --exclude='conciliacao_financeira/logs/*.log' \
    --exclude='conciliacao_financeira/__pycache__' \
    --exclude='conciliacao_financeira/*/__pycache__' \
    --exclude='conciliacao_financeira/data/extratos_gas/*.pdf' \
    --exclude='conciliacao_financeira/data/extratos_gas/*.xlsx' \
    conciliacao_financeira/

TAMANHO=$(ls -lh conciliacao_producao.tar.gz | awk '{print $5}')
echo -e "${GREEN}✅ Pacote criado: $TAMANHO${NC}"

# 3. Upload para servidor
echo -e "\n${YELLOW}📤 Fazendo upload para servidor...${NC}"
echo -e "${YELLOW}💡 Você precisará digitar a senha SSH${NC}"

scp conciliacao_producao.tar.gz $USUARIO_SSH@$SERVIDOR:~/

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✅ Upload concluído${NC}"
else
    echo -e "${RED}❌ Erro no upload${NC}"
    exit 1
fi

# 4. Conectar e executar instalação
echo -e "\n${YELLOW}🔧 Executando instalação no servidor...${NC}"
echo -e "${YELLOW}💡 Você precisará digitar a senha SSH novamente${NC}"

ssh $USUARIO_SSH@$SERVIDOR << 'ENDSSH'
echo "📍 Conectado ao servidor"

# Criar pasta e mover arquivo
mkdir -p /home/dese7735/conciliador
mv ~/conciliacao_producao.tar.gz /home/dese7735/conciliador/
cd /home/dese7735/conciliador

# Extrair
echo "📦 Extraindo arquivos..."
tar -xzf conciliacao_producao.tar.gz
mv conciliacao_financeira/* .
mv conciliacao_financeira/.streamlit .
rmdir conciliacao_financeira
rm conciliacao_producao.tar.gz

# Dar permissão
chmod +x install_servidor.sh

# Executar instalação
echo "🚀 Iniciando instalação..."
./install_servidor.sh

ENDSSH

if [ $? -eq 0 ]; then
    echo -e "\n${GREEN}════════════════════════════════════════════════════════${NC}"
    echo -e "${GREEN}✅ DEPLOY CONCLUÍDO COM SUCESSO!${NC}"
    echo -e "${GREEN}════════════════════════════════════════════════════════${NC}"
    
    echo -e "\n${YELLOW}📋 Próximos passos:${NC}"
    echo -e "1. Conecte via SSH:"
    echo -e "   ${GREEN}ssh $USUARIO_SSH@$SERVIDOR${NC}"
    echo -e ""
    echo -e "2. Vá para a pasta:"
    echo -e "   ${GREEN}cd $PASTA_DESTINO${NC}"
    echo -e ""
    echo -e "3. Inicie o servidor:"
    echo -e "   ${GREEN}./start_servidor.sh${NC}"
    echo -e ""
    echo -e "4. Configure proxy no cPanel (veja INSTRUCOES_CPANEL.txt)"
    echo -e ""
    echo -e "5. Acesse: ${GREEN}https://$SERVIDOR/conciliador${NC}"
else
    echo -e "${RED}❌ Erro na instalação${NC}"
    exit 1
fi

# Limpar arquivo local
rm conciliacao_producao.tar.gz
