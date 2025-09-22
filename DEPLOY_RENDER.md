# 🚀 Deploy su Render - Istruzioni Step-by-Step

## Prerequisiti
- Account Render (gratuito): https://render.com
- Repository GitHub: https://github.com/ddellecasedata/SQL-MCP

## 📊 Passo 1: Crea Database PostgreSQL

1. **Login su Render** → Dashboard
2. **New +** → **PostgreSQL**
3. **Configurazione**:
   - **Name**: `sql-mcp-db`
   - **Database Name**: `inventario_db`
   - **User**: `inventario_user`
   - **Region**: Frankfurt (Europa)
   - **Plan**: Free
4. **Create Database**
5. **COPIA l'External Database URL** (servirà dopo)

## 🌐 Passo 2: Crea Web Service

1. **New +** → **Web Service**
2. **Connect Repository**: 
   - **GitHub**: `ddellecasedata/SQL-MCP`
   - **Connect**
3. **Configurazione**:
   - **Name**: `sql-mcp-server`
   - **Region**: Frankfurt
   - **Branch**: `main`
   - **Root Directory**: `/` (lascia vuoto)
   - **Environment**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `python3 server_complete.py`
   - **Plan**: Free

## ⚙️ Passo 3: Environment Variables

Nella sezione **Environment**, aggiungi:

```
DATABASE_URL = [INCOLLA L'URL DEL DATABASE DAL PASSO 1]
API_KEY = GenuinMiglioreAgenteDelMondo
PORT = 10000
RENDER = true
```

## 🗄️ Passo 4: Setup Database Schema

Dopo il deploy del web service:

1. Vai al **database PostgreSQL** creato
2. **Connect** → **psql**
3. **Copia e incolla** tutto il contenuto di `database/schema.sql`
4. **Esegui** per creare le tabelle

## ✅ Passo 5: Test

Il tuo server sarà disponibile a:
- **URL**: `https://sql-mcp-server.onrender.com`
- **Health Check**: `https://sql-mcp-server.onrender.com/health`
- **API Key**: `GenuinMiglioreAgenteDelMondo`

### Test API:
```bash
curl -H "Authorization: GenuinMiglioreAgenteDelMondo" \
  https://sql-mcp-server.onrender.com/api/alimenti
```

## 🎯 Risultato Finale

- ✅ **Server MCP pubblico** accessibile da qualsiasi LLM
- ✅ **Database PostgreSQL** in cloud
- ✅ **API sicura** con autenticazione
- ✅ **Documentazione** completa disponibile su `/docs`

## 🚨 Troubleshooting

### Errore "Application failed to start":
1. Controlla i **logs** nel dashboard Render
2. Verifica che `DATABASE_URL` sia corretto
3. Controlla che il database sia online

### Errore di connessione database:
1. Verifica che lo schema SQL sia stato eseguito
2. Controlla che `DATABASE_URL` includa credenziali corrette

## 🔄 Aggiornamenti

Per aggiornare il server:
1. **Push** su GitHub
2. Render **auto-deploy** automaticamente
3. Monitor nei logs di Render

---

**🎉 Il tuo server MCP è ora accessibile da qualsiasi LLM cloud!**
