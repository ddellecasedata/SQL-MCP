# 🍎 Setup MCP Server per Claude Desktop

## 📋 **Prerequisiti**

1. **Claude Desktop installato** - [Scarica qui](https://claude.ai/download)
2. **Python 3.10+** installato
3. **Database PostgreSQL** già configurato

## ⚙️ **Setup Ambiente**

### 1. Installa dipendenze

```bash
cd /Users/daniele/SQL-MCP
pip3 install -r requirements.txt
```

### 2. Verifica variabili d'ambiente

Crea/modifica `.env`:

```env
DATABASE_URL=postgresql://postgres:InventoryDB2024!@dpg-cstiqn3gbbvc73crrht0-a.frankfurt-postgres.render.com/inventario_postgresql_db
```

### 3. Testa il server localmente

```bash
# Testa che il server si avvii
python3 inventario_mcp.py
```

Il server dovrebbe avviarsi e rimanere in attesa (modalità STDIO).

## 🔧 **Configurazione Claude Desktop**

### 1. Trova il file di configurazione

**macOS:**
```bash
~/Library/Application Support/Claude/claude_desktop_config.json
```

**Windows:**
```bash
%APPDATA%\Claude\claude_desktop_config.json
```

### 2. Modifica la configurazione

Apri il file e aggiungi/sostituisci con:

```json
{
  "mcpServers": {
    "inventario-alimentare": {
      "command": "python3",
      "args": [
        "/Users/daniele/SQL-MCP/inventario_mcp.py"
      ],
      "env": {
        "DATABASE_URL": "postgresql://postgres:InventoryDB2024!@dpg-cstiqn3gbbvc73crrht0-a.frankfurt-postgres.render.com/inventario_postgresql_db"
      }
    }
  }
}
```

**⚠️ IMPORTANTE:** Usa il percorso assoluto completo al file `inventario_mcp.py`

### 3. Riavvia Claude Desktop

Chiudi completamente Claude Desktop e riaprilo.

## 🎯 **Verifica Funzionamento**

### 1. Check icona MCP

Cerca l'icona "🔧" nella barra degli strumenti di Claude Desktop.

### 2. Tools disponibili

Dovresti vedere 5 tool:
- `cerca_alimenti` - Cerca per nome/categoria/ubicazione
- `dettagli_alimento` - Dettagli completi di un alimento
- `statistiche_inventario` - Statistiche generali
- `alimenti_in_scadenza` - Controllo scadenze
- (altri tool eventuali)

### 3. Test comandi

Prova questi comandi in Claude Desktop:

```
🔍 Cerca "pomodori" nell'inventario
📊 Mostrami le statistiche dell'inventario  
⏰ Quali alimenti scadono questa settimana?
📦 Dettagli dell'alimento ID 1
```

## 🐛 **Troubleshooting**

### Server non si avvia

1. **Controlla i log di Claude:**
   ```bash
   tail -f ~/Library/Logs/Claude/mcp*.log
   ```

2. **Verifica Python:**
   ```bash
   python3 --version  # Deve essere 3.10+
   which python3      # Percorso corretto?
   ```

3. **Test connessione database:**
   ```bash
   python3 -c "
   import asyncpg, asyncio
   async def test():
       conn = await asyncpg.connect('postgresql://postgres:InventoryDB2024!@dpg-cstiqn3gbbvc73crrht0-a.frankfurt-postgres.render.com/inventario_postgresql_db')
       print('✅ Database connesso!')
       await conn.close()
   asyncio.run(test())
   "
   ```

### Tools non appaiono

1. **Controlla sintassi JSON** del config file
2. **Riavvia Claude Desktop completamente**
3. **Verifica percorso assoluto** nel config

### Errori durante l'uso

1. **Controlla i log MCP** di Claude Desktop
2. **Verifica che il database sia raggiungibile**
3. **Controlla che lo schema database esista**

## 📝 **File di Log**

**Claude Desktop logs:**
- `~/Library/Logs/Claude/mcp.log` - Log generali MCP
- `~/Library/Logs/Claude/mcp-server-inventario-alimentare.log` - Log specifici del server

**Check logs:**
```bash
tail -f ~/Library/Logs/Claude/mcp*.log
```

## ✅ **Esempio di Utilizzo**

Una volta configurato, potrai usare Claude Desktop con comandi come:

```
"Cerca tutti i prodotti nella categoria VERDURE"
"Mostrami cosa scade nei prossimi 3 giorni" 
"Dammi i dettagli dell'alimento con ID 5"
"Quali sono le statistiche del mio inventario?"
```

Claude userà automaticamente i tool MCP per interrogare il tuo database inventario! 🎉
