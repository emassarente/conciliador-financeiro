# 🚀 Guia de Deploy - Sistema de Conciliação Financeira

## 📋 Pré-requisitos

- **Servidor:** Linux (Ubuntu/Debian recomendado) ou macOS
- **Python:** 3.9 ou superior
- **Nginx ou Apache:** Para proxy reverso
- **Domínio:** c2minstituto.com.br configurado

---

## 🔧 Instalação

### 1. Fazer upload dos arquivos

Copie a pasta `conciliacao_financeira` para o servidor:

```bash
# Via SCP/SFTP
scp -r conciliacao_financeira/ usuario@c2minstituto.com.br:/var/www/

# Ou via Git
cd /var/www/
git clone <seu-repositorio>
```

### 2. Executar deploy

```bash
cd /var/www/conciliacao_financeira
chmod +x deploy.sh start.sh
./deploy.sh
```

O script irá:
- ✅ Verificar Python
- ✅ Criar ambiente virtual
- ✅ Instalar dependências
- ✅ Configurar banco de dados
- ✅ Criar diretórios necessários

---

## 🌐 Configuração do Nginx

Crie o arquivo `/etc/nginx/sites-available/conciliador`:

```nginx
server {
    listen 80;
    server_name c2minstituto.com.br;
    
    # Redireciona HTTP para HTTPS
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name c2minstituto.com.br;
    
    # Certificado SSL (Let's Encrypt recomendado)
    ssl_certificate /etc/letsencrypt/live/c2minstituto.com.br/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/c2minstituto.com.br/privkey.pem;
    
    # Configurações SSL
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    
    # Proxy para Streamlit em /conciliador
    location /conciliador {
        proxy_pass http://localhost:8502;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # Timeouts para uploads grandes
        proxy_read_timeout 300s;
        proxy_connect_timeout 75s;
        client_max_body_size 100M;
    }
    
    # WebSocket para Streamlit
    location /conciliador/_stcore/stream {
        proxy_pass http://localhost:8502/conciliador/_stcore/stream;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
    }
}
```

Ative o site:

```bash
sudo ln -s /etc/nginx/sites-available/conciliador /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

---

## 🔐 Certificado SSL (Let's Encrypt)

```bash
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d c2minstituto.com.br
```

---

## ▶️ Iniciar o Sistema

### Opção 1: Manualmente (teste)

```bash
cd /var/www/conciliacao_financeira
./start.sh
```

### Opção 2: Com Screen (produção)

```bash
screen -S conciliador
cd /var/www/conciliacao_financeira
./start.sh

# Desanexar: Ctrl+A, depois D
# Reanexar: screen -r conciliador
```

### Opção 3: Systemd Service (recomendado)

Crie `/etc/systemd/system/conciliador.service`:

```ini
[Unit]
Description=Sistema de Conciliação Financeira
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/var/www/conciliacao_financeira
Environment="PATH=/var/www/conciliacao_financeira/.venv/bin"
ExecStart=/var/www/conciliacao_financeira/.venv/bin/streamlit run ui/dashboard.py --server.port=8502 --server.headless=true --server.baseUrlPath="/conciliador" --browser.gatherUsageStats=false
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Ative o serviço:

```bash
sudo systemctl daemon-reload
sudo systemctl enable conciliador
sudo systemctl start conciliador
sudo systemctl status conciliador
```

---

## 🧪 Testar

1. **Acesse:** https://c2minstituto.com.br/conciliador
2. **Login padrão:**
   - Email: `igp@igp.com.br`
   - Senha: `igp@123`

---

## 📊 Monitoramento

### Ver logs do Streamlit

```bash
# Com systemd
sudo journalctl -u conciliador -f

# Com screen
screen -r conciliador
```

### Verificar status

```bash
# Serviço
sudo systemctl status conciliador

# Porta
sudo netstat -tlnp | grep 8502

# Nginx
sudo nginx -t
sudo systemctl status nginx
```

---

## 🔄 Atualizar Sistema

```bash
cd /var/www/conciliacao_financeira
git pull  # ou copie novos arquivos
source .venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart conciliador
```

---

## 🛡️ Segurança

### Firewall

```bash
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

### Backup do banco de dados

```bash
# Criar backup
cp database/conciliacao.db database/conciliacao_backup_$(date +%Y%m%d).db

# Automatizar (crontab)
0 2 * * * cp /var/www/conciliacao_financeira/database/conciliacao.db /var/www/conciliacao_financeira/database/backup_$(date +\%Y\%m\%d).db
```

---

## 🆘 Troubleshooting

### Erro: Porta 8502 em uso

```bash
sudo lsof -i :8502
sudo kill -9 <PID>
```

### Erro: Permissões

```bash
sudo chown -R www-data:www-data /var/www/conciliacao_financeira
sudo chmod -R 755 /var/www/conciliacao_financeira
```

### Erro: Módulos não encontrados

```bash
cd /var/www/conciliacao_financeira
source .venv/bin/activate
pip install -r requirements.txt
```

---

## 📞 Suporte

- **Logs:** `/var/www/conciliacao_financeira/logs/`
- **Banco:** `/var/www/conciliacao_financeira/database/conciliacao.db`
- **Config:** `/var/www/conciliacao_financeira/.streamlit/config.toml`

---

## ✅ Checklist Final

- [ ] Deploy executado com sucesso
- [ ] Nginx configurado e rodando
- [ ] SSL ativo (HTTPS)
- [ ] Streamlit rodando na porta 8502
- [ ] Acesso via https://c2minstituto.com.br/conciliador funcionando
- [ ] Login testado
- [ ] Upload de arquivos testado
- [ ] Backup configurado
- [ ] Firewall configurado
