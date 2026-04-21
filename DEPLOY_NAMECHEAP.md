# 🚀 Deploy para NameCheap - Guia Completo

## ✅ Pré-requisitos Verificados

- [x] Sistema testado localmente
- [x] cPanel disponível
- [x] SSH disponível
- [x] Banco: dese7735_conciliador (SQLite separado)
- [x] URL: c2minstituto.com.br/conciliador

---

## 📋 Passo a Passo Completo

### 1️⃣ No seu Mac: Execute o Deploy Automático

```bash
cd /Applications/XAMPP/xamppfiles/htdocs/Automacao_lage/conciliacao_financeira
./deploy_para_servidor.sh
```

**O que esse script faz:**
1. ✅ Cria pacote otimizado (sem .venv, sem banco local)
2. ✅ Faz upload via SCP para o servidor
3. ✅ Conecta via SSH e extrai arquivos
4. ✅ Executa instalação automática
5. ✅ Configura ambiente virtual
6. ✅ Instala todas as dependências

**Você precisará digitar a senha SSH 2 vezes.**

---

### 2️⃣ Após o Deploy: Iniciar o Servidor

O script vai pedir para você conectar via SSH:

```bash
ssh dese7735@c2minstituto.com.br
cd /home/dese7735/conciliador
./start_servidor.sh
```

**Verificar se está rodando:**
```bash
ps aux | grep streamlit
tail -f logs/streamlit.log
```

---

### 3️⃣ Configurar Proxy Reverso no cPanel

**OPÇÃO A: Via .htaccess (Mais Fácil)**

1. Acesse cPanel → File Manager
2. Vá para `public_html/`
3. Edite (ou crie) `.htaccess`
4. Adicione no final:

```apache
# Proxy para Sistema de Conciliação
<IfModule mod_proxy.c>
    ProxyPreserveHost On
    ProxyPass /conciliador http://localhost:8502/conciliador
    ProxyPassReverse /conciliador http://localhost:8502/conciliador
</IfModule>
```

5. Salvar

**OPÇÃO B: Subdomínio (Alternativa)**

Se a opção A não funcionar:

1. cPanel → Subdomains
2. Criar: `conciliador.c2minstituto.com.br`
3. Document Root: `/home/dese7735/conciliador`
4. Criar `.htaccess` dentro da pasta do subdomínio:

```apache
RewriteEngine On
RewriteRule ^(.*)$ http://localhost:8502/$1 [P,L]
```

---

### 4️⃣ Testar

**Via SSH (no servidor):**
```bash
curl http://localhost:8502/conciliador
```

**Via Browser:**
```
https://c2minstituto.com.br/conciliador
```

ou (se usou subdomínio):
```
https://conciliador.c2minstituto.com.br
```

---

## 🔧 Comandos Úteis

### No Servidor (via SSH)

```bash
# Iniciar servidor
cd /home/dese7735/conciliador
./start_servidor.sh

# Parar servidor
./stop_servidor.sh

# Ver logs em tempo real
tail -f logs/streamlit.log

# Verificar se está rodando
ps aux | grep streamlit

# Ver porta
netstat -tlnp | grep 8502

# Reiniciar
./stop_servidor.sh
./start_servidor.sh
```

### No seu Mac

```bash
# Conectar via SSH
ssh dese7735@c2minstituto.com.br

# Fazer novo deploy (após alterações)
cd /Applications/XAMPP/xamppfiles/htdocs/Automacao_lage/conciliacao_financeira
./deploy_para_servidor.sh

# Backup do banco (baixar do servidor)
scp dese7735@c2minstituto.com.br:/home/dese7735/conciliador/database/conciliacao.db ~/Desktop/backup_conciliador.db
```

---

## 🆘 Troubleshooting

### ❌ Erro: "Python not found"

O NameCheap pode não ter Python instalado. Opções:

1. **Contatar suporte:** Pedir para instalar Python 3.9+
2. **Alternativa:** Deploy no Streamlit Cloud (grátis)

### ❌ Erro 502 Bad Gateway

Streamlit não está rodando:
```bash
ssh dese7735@c2minstituto.com.br
cd /home/dese7735/conciliador
./start_servidor.sh
```

### ❌ Erro 404 Not Found

Proxy não configurado:
- Revisar `.htaccess`
- Verificar se mod_proxy está habilitado
- Tentar opção de subdomínio

### ❌ Erro 500 Internal Server Error

mod_proxy não habilitado:
- Contatar suporte NameCheap
- Usar opção de subdomínio

### ❌ Porta 8502 em uso

```bash
ssh dese7735@c2minstituto.com.br
pkill -f streamlit
./start_servidor.sh
```

---

## 🔄 Atualizar Sistema

Após fazer alterações no código:

```bash
# 1. No Mac: Fazer novo deploy
cd /Applications/XAMPP/xamppfiles/htdocs/Automacao_lage/conciliacao_financeira
./deploy_para_servidor.sh

# 2. No servidor: Reiniciar
ssh dese7735@c2minstituto.com.br
cd /home/dese7735/conciliador
./stop_servidor.sh
./start_servidor.sh
```

---

## 📊 Manter Rodando Permanentemente

O servidor já está configurado para rodar em background (nohup).

Para reiniciar automaticamente após reboot do servidor:

```bash
ssh dese7735@c2minstituto.com.br
crontab -e

# Adicionar:
@reboot /home/dese7735/conciliador/start_servidor.sh
```

---

## 🎯 Checklist Final

- [ ] Deploy executado com sucesso
- [ ] Servidor iniciado (`./start_servidor.sh`)
- [ ] Streamlit rodando (`ps aux | grep streamlit`)
- [ ] Proxy configurado no cPanel (`.htaccess`)
- [ ] Acesso via https://c2minstituto.com.br/conciliador funcionando
- [ ] Login testado (igp@igp.com.br / igp@123)
- [ ] Upload de arquivo testado
- [ ] Conciliação testada
- [ ] Cron configurado para auto-start

---

## 📞 Suporte

Se algo não funcionar:

1. **Verificar logs:**
   ```bash
   ssh dese7735@c2minstituto.com.br
   tail -f /home/dese7735/conciliador/logs/streamlit.log
   ```

2. **Contatar suporte NameCheap:**
   - Pedir para habilitar mod_proxy
   - Pedir para instalar Python 3.9+ (se não tiver)
   - Pedir ajuda com proxy reverso

3. **Alternativa:** Deploy no Streamlit Cloud (grátis, sem servidor)

---

**🎉 Boa sorte com o deploy!**
