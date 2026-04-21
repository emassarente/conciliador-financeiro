# ⚡ Início Rápido - Deploy em 5 Minutos

## 🍎 Teste Local (MacBook Air M4)

```bash
# 1. Navegue até a pasta
cd /Applications/XAMPP/xamppfiles/htdocs/Automacao_lage/conciliacao_financeira

# 2. Execute o deploy (primeira vez)
chmod +x deploy.sh start.sh
./deploy.sh

# 3. Inicie o servidor
./start.sh
```

**Acesse:** http://localhost:8502

**Parar:** Pressione `Ctrl+C` no terminal

---

## 🚀 Deploy em Produção (Servidor Linux)

```bash
# 1. No Mac: Criar pacote
cd /Applications/XAMPP/xamppfiles/htdocs/Automacao_lage
tar -czf conciliacao.tar.gz --exclude='.venv' --exclude='database/*.db' conciliacao_financeira/

# 2. Copiar para servidor
scp conciliacao.tar.gz usuario@c2minstituto.com.br:/tmp/

# 3. No servidor: Descompactar e instalar
ssh usuario@c2minstituto.com.br
cd /var/www
sudo tar -xzf /tmp/conciliacao.tar.gz
cd conciliacao_financeira
chmod +x deploy.sh start.sh
./deploy.sh

# 4. Configurar Nginx e SSL (ver DEPLOY.md)
```

**Acesse:** https://c2minstituto.com.br/conciliador

---

## 👤 Login Padrão

**Administrador (IGP):**
- Email: `igp@igp.com.br`
- Senha: `igp@123`

**Contabilidade (União):**
- Email: `uniao@uniaoac.com.br`
- Senha: `uniao@123`

---

## 📁 Estrutura de Pastas

```
conciliacao_financeira/
├── ui/dashboard.py          # Interface Streamlit
├── database/
│   ├── db_manager.py        # Gerenciador do banco
│   └── conciliacao.db       # Banco SQLite
├── engine/                  # Motores de conciliação
├── import_/                 # Parsers de arquivos
├── .streamlit/config.toml   # Configuração
├── deploy.sh                # Script de deploy
├── start.sh                 # Script de inicialização
└── requirements.txt         # Dependências
```

---

## 🔧 Comandos Úteis

### Iniciar/Parar

```bash
# Iniciar
./start.sh

# Parar
Ctrl + C

# Com systemd (produção)
sudo systemctl start conciliador
sudo systemctl stop conciliador
sudo systemctl restart conciliador
```

### Ver Logs

```bash
# Desenvolvimento
# (logs aparecem no terminal)

# Produção (systemd)
sudo journalctl -u conciliador -f
```

### Backup

```bash
# Banco de dados
cp database/conciliacao.db database/backup_$(date +%Y%m%d).db

# Arquivos importados
tar -czf backup_data_$(date +%Y%m%d).tar.gz data/
```

---

## 🆘 Problemas Comuns (macOS)

### Porta 8502 em uso
```bash
# Ver o que está usando
lsof -i :8502

# Matar processo
lsof -ti :8502 | xargs kill -9
```

### Módulos não encontrados
```bash
source .venv/bin/activate
pip install -r requirements.txt
```

### Erro de permissão
```bash
chmod +x deploy.sh start.sh
```

### Python não encontrado
```bash
# Instalar via Homebrew
brew install python@3.11
```

---

## 📚 Documentação Completa

- **DEPLOY_MACOS.md** - 🍎 Guia específico para MacBook Air M4
- **DEPLOY.md** - Guia completo de deploy em produção (Linux)
- **RESUMO_DEPLOY.md** - Resumo das alterações e funcionalidades
- **SENHAS_SISTEMA.md** - Credenciais de acesso (não versionar!)

---

**🎯 Pronto! Sistema rodando em 5 minutos.**
