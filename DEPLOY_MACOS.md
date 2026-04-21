# 🍎 Guia de Deploy - macOS (Apple Silicon M4)

## 🎯 Cenários de Uso

### 1️⃣ Desenvolvimento/Teste Local (MacBook Air M4)
### 2️⃣ Deploy em Servidor Linux (Produção)

---

## 💻 Cenário 1: Teste Local no Mac

### Pré-requisitos

```bash
# Verificar Python (deve vir com macOS ou via Homebrew)
python3 --version

# Se não tiver Python 3.9+, instale via Homebrew
brew install python@3.11
```

### Instalação Rápida

```bash
# 1. Navegue até a pasta do projeto
cd /Applications/XAMPP/xamppfiles/htdocs/Automacao_lage/conciliacao_financeira

# 2. Execute o deploy
chmod +x deploy.sh start.sh
./deploy.sh

# 3. Inicie o servidor
./start.sh
```

**Acesse:** http://localhost:8502

### Comandos Úteis (macOS)

```bash
# Verificar porta em uso
lsof -i :8502

# Matar processo na porta 8502
lsof -ti :8502 | xargs kill -9

# Ver processos Python rodando
ps aux | grep streamlit

# Parar servidor
# Pressione Ctrl+C no terminal onde está rodando
```

### Manter Rodando em Background (macOS)

**Opção 1: Terminal em background**
```bash
# Inicia em background
nohup ./start.sh > logs/streamlit.log 2>&1 &

# Ver log em tempo real
tail -f logs/streamlit.log

# Parar
pkill -f streamlit
```

**Opção 2: Usando screen**
```bash
# Instalar screen (se necessário)
brew install screen

# Iniciar sessão
screen -S conciliador
./start.sh

# Desanexar: Ctrl+A, depois D
# Reanexar: screen -r conciliador
# Listar sessões: screen -ls
```

**Opção 3: Usando tmux**
```bash
# Instalar tmux
brew install tmux

# Iniciar sessão
tmux new -s conciliador
./start.sh

# Desanexar: Ctrl+B, depois D
# Reanexar: tmux attach -t conciliador
```

---

## 🌐 Cenário 2: Deploy em Servidor Linux (Produção)

### Preparar no Mac

```bash
# 1. Criar arquivo compactado (excluindo .venv e banco)
cd /Applications/XAMPP/xamppfiles/htdocs/Automacao_lage
tar -czf conciliacao_financeira.tar.gz \
    --exclude='.venv' \
    --exclude='database/*.db' \
    --exclude='*.log' \
    --exclude='__pycache__' \
    conciliacao_financeira/

# 2. Copiar para servidor via SCP
scp conciliacao_financeira.tar.gz usuario@c2minstituto.com.br:/tmp/

# Ou via SFTP (mais visual)
# Use Cyberduck, FileZilla ou Transmit
```

### No Servidor Linux

```bash
# 1. Conectar via SSH
ssh usuario@c2minstituto.com.br

# 2. Descompactar
cd /var/www
sudo tar -xzf /tmp/conciliacao_financeira.tar.gz
sudo chown -R www-data:www-data conciliacao_financeira

# 3. Executar deploy
cd conciliacao_financeira
chmod +x deploy.sh start.sh
./deploy.sh

# 4. Configurar Nginx (ver DEPLOY.md)
sudo nano /etc/nginx/sites-available/conciliador

# 5. Configurar SSL
sudo certbot --nginx -d c2minstituto.com.br

# 6. Iniciar serviço
sudo systemctl enable conciliador
sudo systemctl start conciliador
```

---

## 🔧 Configuração Específica para macOS

### Ajustar .streamlit/config.toml (Teste Local)

Para teste local, use configuração simplificada:

```toml
[server]
port = 8502
headless = true
enableCORS = false

[browser]
gatherUsageStats = false

[theme]
primaryColor = "#2563eb"
backgroundColor = "#f0f2f6"
```

Para produção, mantenha:
```toml
[server]
baseUrlPath = "/conciliador"
```

### Firewall do macOS

```bash
# Permitir porta 8502 (se necessário)
# Vá em: Preferências do Sistema > Segurança > Firewall > Opções
# Adicione Python/Streamlit à lista de apps permitidos
```

---

## 🧪 Testar Funcionalidades

```bash
# 1. Verificar banco de dados
cd /Applications/XAMPP/xamppfiles/htdocs/Automacao_lage/conciliacao_financeira
source .venv/bin/activate
python3 -c "from database.db_manager import DatabaseManager; db=DatabaseManager(); print(f'Clientes: {len(db.listar_clientes())}')"

# 2. Testar parsers
python3 -c "from import_.razao_parser import RazaoParser; print('✅ Parser OK')"

# 3. Verificar porta
lsof -i :8502
```

---

## 📦 Backup (macOS)

```bash
# Backup do banco
cp database/conciliacao.db database/backup_$(date +%Y%m%d).db

# Backup completo (excluindo .venv)
cd /Applications/XAMPP/xamppfiles/htdocs/Automacao_lage
tar -czf ~/Desktop/conciliacao_backup_$(date +%Y%m%d).tar.gz \
    --exclude='.venv' \
    --exclude='*.log' \
    conciliacao_financeira/

# Restaurar
tar -xzf ~/Desktop/conciliacao_backup_YYYYMMDD.tar.gz
```

---

## 🔄 Atualizar Sistema (macOS)

```bash
# 1. Parar servidor (se estiver rodando)
pkill -f streamlit

# 2. Atualizar código
cd /Applications/XAMPP/xamppfiles/htdocs/Automacao_lage/conciliacao_financeira
# (fazer alterações ou git pull)

# 3. Atualizar dependências
source .venv/bin/activate
pip install -r requirements.txt

# 4. Reiniciar
./start.sh
```

---

## 🆘 Troubleshooting (macOS)

### Erro: "Permission denied"
```bash
chmod +x deploy.sh start.sh
```

### Erro: "Python not found"
```bash
# Instalar Python via Homebrew
brew install python@3.11

# Ou usar Python do sistema
which python3
```

### Erro: "Port already in use"
```bash
# Ver o que está usando a porta
lsof -i :8502

# Matar processo
lsof -ti :8502 | xargs kill -9
```

### Erro: "Module not found"
```bash
# Ativar ambiente virtual
source .venv/bin/activate

# Reinstalar dependências
pip install -r requirements.txt
```

### Streamlit não abre no browser
```bash
# Abrir manualmente
open http://localhost:8502

# Ou verificar se está rodando
ps aux | grep streamlit
```

---

## 🚀 Comandos Rápidos (MacBook Air M4)

```bash
# Iniciar desenvolvimento
cd /Applications/XAMPP/xamppfiles/htdocs/Automacao_lage/conciliacao_financeira
./start.sh

# Parar
Ctrl+C

# Ver logs
tail -f logs/streamlit.log

# Backup rápido
cp database/conciliacao.db database/backup_$(date +%Y%m%d).db

# Limpar cache
rm -rf .streamlit/cache

# Verificar status
lsof -i :8502
```

---

## 📱 Acessar de Outros Dispositivos na Rede Local

```bash
# 1. Descobrir IP do Mac
ifconfig | grep "inet " | grep -v 127.0.0.1

# 2. Iniciar Streamlit permitindo acesso externo
streamlit run ui/dashboard.py --server.port=8502 --server.address=0.0.0.0

# 3. Acessar de outro dispositivo
# http://<IP_DO_MAC>:8502
# Exemplo: http://192.168.1.100:8502
```

---

## ✅ Checklist - Teste Local (Mac)

- [ ] Python 3.9+ instalado
- [ ] Deploy executado (`./deploy.sh`)
- [ ] Servidor iniciado (`./start.sh`)
- [ ] Acesso via http://localhost:8502 funcionando
- [ ] Login testado (igp@igp.com.br / igp@123)
- [ ] Upload de arquivo testado
- [ ] Conciliação testada

---

## ✅ Checklist - Deploy Produção (Servidor)

- [ ] Arquivos copiados para servidor Linux
- [ ] Deploy executado no servidor
- [ ] Nginx configurado
- [ ] SSL configurado (Let's Encrypt)
- [ ] Serviço systemd ativo
- [ ] Acesso via https://c2minstituto.com.br/conciliador funcionando
- [ ] Backup configurado

---

**🎉 Sistema rodando no seu MacBook Air M4!**

Para produção, siga o **DEPLOY.md** (configuração Linux/Nginx).
