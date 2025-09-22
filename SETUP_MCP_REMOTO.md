# 🌐 Setup Server MCP Remoto per Claude Desktop

## 🎯 **Perché Server Remoto?**

✅ **Vantaggi:**
- 🌍 Accesso da qualsiasi dispositivo
- 🔄 Aggiornamenti automatici
- 📱 Funziona su mobile (se Claude supporta)
- ⚡ Nessuna installazione locale
- 🔒 Database centralizzato

❌ **Svantaggi:**
- 🌐 Richiede connessione internet
- ⏰ Leggera latenza di rete
- 💸 Costi di hosting (free tier Render disponibile)

## 🚀 **Deployment Server Remoto**

### 1. Deploy su Render.com

```bash
# Commit il nuovo server
git add -A
git commit -m "Add remote MCP server"
git push
```

**Su Render.com:**
1. **New Web Service** → **Connect GitHub** → `ddellecasedata/SQL-MCP`
2. **Configurazione:**
   - **Name**: `sql-mcp-server`
   - **Start Command**: `python3 inventario_mcp_remote.py`
   - **Environment Variables**:
     ```
     DATABASE_URL = postgresql://postgres:InventoryDB2024!@dpg-cstiqn3gbbvc73crrht0-a.frankfurt-postgres.render.com/inventario_postgresql_db
     PORT = 10000
     ```

### 2. Verifica Deploy

Aspetta 3-5 minuti, poi testa:

```bash
# Test health check
curl https://sql-mcp-server.onrender.com/health

# Test MCP endpoint
curl https://sql-mcp-server.onrender.com/mcp/health
```

## ⚙️ **Configurazione Claude Desktop**

### Opzione A: mcp-remote Bridge (Consigliato)

Copia il contenuto di `claude_desktop_config_remote.json`:

```json
{
  "mcpServers": {
    "inventario-alimentare-remoto": {
      "command": "npx",
      "args": [
        "-y",
        "mcp-remote",
        "https://sql-mcp-server.onrender.com/mcp",
        "--transport",
        "http-only"
      ]
    }
  }
}
```

**Dove incollare:**
- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

### Opzione B: Server HTTP Diretto

Se Claude Desktop supporta server HTTP nativamente:

```json
{
  "mcpServers": {
    "inventario-remoto": {
      "url": "https://sql-mcp-server.onrender.com/mcp",
      "transport": "http"
    }
  }
}
```

## 🔧 **Installazione mcp-remote**

Il tool `mcp-remote` fa da bridge tra Claude Desktop e il server remoto:

```bash
# Installa globalmente
npm install -g mcp-remote

# Oppure lascia che npx lo scarichi automaticamente
# (come nel config JSON sopra)
```

## ✅ **Test Funzionamento**

### 1. Riavvia Claude Desktop

Chiudi completamente Claude Desktop e riaprilo.

### 2. Cerca l'icona Tools 🔧

Dovresti vedere l'icona nella barra di Claude Desktop.

### 3. Test Comandi

```
"Cerca pomodori nell'inventario remoto"
"Mostrami le statistiche dell'inventario"  
"Cosa scade nei prossimi 7 giorni?"
"Dettagli dell'alimento ID 1"
```

## 🐛 **Troubleshooting**

### Server non risponde

```bash
# Check server status
curl https://sql-mcp-server.onrender.com/health

# Check logs Render
# Vai su render.com → il tuo servizio → Logs
```

### mcp-remote non funziona

```bash
# Test mcp-remote manualmente
npx mcp-remote https://sql-mcp-server.onrender.com/mcp --transport http-only

# Check versione Node.js
node --version  # Deve essere 16+
```

### Claude Desktop non trova il server

1. **Verifica sintassi JSON** del config file
2. **Controlla percorso corretto** del config file
3. **Check logs Claude Desktop**:
   ```bash
   tail -f ~/Library/Logs/Claude/mcp*.log
   ```

### Errori di connessione

1. **Verifica URL server**: `https://sql-mcp-server.onrender.com/mcp`
2. **Check database**: Deve essere raggiungibile dal server
3. **Render free tier**: Può andare in sleep, aspetta 30 secondi

## 📊 **Monitoraggio**

### Server Logs

**Render.com Dashboard:**
- Vai al tuo servizio
- Tab **Logs** per vedere attività in tempo reale
- Tab **Metrics** per performance

### Claude Desktop Logs

```bash
# macOS
tail -f ~/Library/Logs/Claude/mcp*.log

# Windows  
tail -f %APPDATA%\Claude\Logs\mcp*.log
```

## 🔐 **Sicurezza (Opzionale)**

Se vuoi aggiungere autenticazione al server remoto:

```python
# In inventario_mcp_remote.py
from fastapi import Depends, HTTPException, Header

async def verify_api_key(x_api_key: str = Header(None)):
    if x_api_key != "tua-api-key-segreta":
        raise HTTPException(status_code=401, detail="Invalid API key")
    return x_api_key

# Applica a tutti gli endpoint MCP
app.mount("/mcp", mcp.create_app(dependencies=[Depends(verify_api_key)]))
```

E nel config Claude Desktop:

```json
{
  "mcpServers": {
    "inventario-remoto": {
      "command": "npx",
      "args": [
        "-y", 
        "mcp-remote",
        "https://sql-mcp-server.onrender.com/mcp",
        "--header",
        "X-API-Key:tua-api-key-segreta",
        "--transport",
        "http-only"
      ]
    }
  }
}
```

## 🎉 **Vantaggi Server Remoto**

- **🌍 Multi-device**: Usa da Mac, Windows, Linux
- **🔄 Auto-updates**: Aggiornamenti senza reinstallare
- **📊 Centralized data**: Un solo database per tutti
- **⚡ Always available**: Non devi avviare nulla localmente
- **👥 Team sharing**: Condividi con colleghi (con auth)

**Il tuo inventario alimentare è ora accessibile da ovunque!** 🎊
