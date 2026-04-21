#!/bin/bash
# =============================================================================
# SCRIPT DE INICIALIZAÇÃO - SISTEMA DE CONCILIAÇÃO FINANCEIRA
# =============================================================================

# Diretório do projeto
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

# Ativa ambiente virtual
source .venv/bin/activate

# Inicia Streamlit
echo "🚀 Iniciando Sistema de Conciliação Financeira..."
echo "📍 URL: https://c2minstituto.com.br/conciliador"
echo "🔌 Porta: 8502"
echo ""
echo "Pressione Ctrl+C para parar o servidor"
echo ""

streamlit run ui/dashboard.py \
    --server.port=8502 \
    --server.headless=true \
    --server.baseUrlPath="/conciliador" \
    --browser.gatherUsageStats=false
