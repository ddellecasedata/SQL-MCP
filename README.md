# 🌐 Server MCP Remoto per Inventario Alimentare 📦

## 🚀 Server MCP Remoto per Claude Desktop

Server MCP deployato su cloud per gestire il tuo inventario alimentare da qualsiasi dispositivo con Claude Desktop.

Server MCP completo per la gestione automatizzata tramite LLM del magazzino alimentari e delle attività (TODO list) con database PostgreSQL.

## 🚀 Caratteristiche

### Gestione Magazzino
- ✅ Aggiunta/modifica/rimozione alimenti
- 📊 Consultazione giacenze con filtri avanzati
- ⚠️ Notifiche automatiche per scadenze
- 📈 Statistiche consumi per periodo
- 🔄 Scarico alimenti con controllo quantità
- 📍 Gestione ubicazioni (FRIGO, FREEZER, DISPENSA, CANTINA)

### Gestione Task
- 📝 Creazione e modifica task con priorità
- 🔄 Task ricorrenti (giornalieri, settimanali, mensili)
- 📅 Gestione scadenze e assegnazioni
- 📊 Statistiche completamento
- ✅ Workflow completo DA_FARE → IN_CORSO → COMPLETATO

### Funzionalità Avanzate
- 🔐 Autenticazione API Key
- 📋 Logging completo di tutte le operazioni
- 🐘 Pool di connessioni PostgreSQL ottimizzato
- 🌐 API REST + protocollo MCP
- ☁️ Deploy pronto per Render.com
- 🧪 Test suite completa

## 📁 Struttura Progetto

```
SQL-MCP/
├── database/
│   └── schema.sql              # Schema completo PostgreSQL
├── tests/
│   └── test_inventario_mcp.py  # Test suite completa
├── server_complete.py          # Server principale MCP/FastAPI
├── tools_alimenti.py          # Tool MCP per gestione alimenti
├── tools_task.py              # Tool MCP per gestione task
├── requirements.txt           # Dipendenze Python
├── render.yaml               # Configurazione Render deployment
└── README.md                 # Questa documentazione
```

## 🛠️ Installazione e Setup

### 1. Prerequisiti
- Python 3.11+
- PostgreSQL 14+
- Git

### 2. Setup Locale
```bash
# Clone del repository
git clone <your-repo-url>
cd SQL-MCP

# Creazione ambiente virtuale
python3 -m venv venv
source venv/bin/activate  # Linux/Mac
# o venv\Scripts\activate  # Windows

# Installazione dipendenze
pip install -r requirements.txt
```

### 3. Configurazione Database
```bash
# Crea database PostgreSQL
createdb inventario_db

# Esegui schema
psql -d inventario_db -f database/schema.sql
```

### 4. Variabili d'Ambiente
Crea file `.env`:
```env
DATABASE_URL=postgresql://user:password@localhost/inventario_db
API_KEY=your-secure-api-key-here
PORT=8000
DEBUG=false
```

### 5. Avvio Server
```bash
python3 server_complete.py
```

Il server sarà disponibile su `http://localhost:8000`

## 🌐 Deployment su Render

### 1. Preparazione Repository
```bash
git add .
git commit -m "Initial MCP server setup"
git push origin main
```

### 2. Setup Render
1. Vai su [render.com](https://render.com)
2. Connetti il tuo repository GitHub
3. Il file `render.yaml` configurerà automaticamente:
   - Web service (server MCP)
   - Database PostgreSQL
   - Variabili d'ambiente

### 3. Configurazione Variabili
Nel dashboard Render, configura:
- `DATABASE_URL`: Auto-generato dal database PostgreSQL
- `API_KEY`: Genera una chiave sicura
- `PORT`: 10000 (default Render)

### 4. Deploy
Il deploy avviene automaticamente. Il server sarà disponibile su:
```
https://your-app-name.onrender.com
```

## 📋 API Reference

### Endpoint REST

#### Health Check
```http
GET /health
```
**Response:**
```json
{
  "status": "healthy",
  "database": "connected", 
  "timestamp": "2024-01-15T10:30:00"
}
```

#### Alimenti

**Crea Alimento**
```http
POST /api/alimenti
Authorization: Bearer YOUR_API_KEY
Content-Type: application/json

{
  "nome": "Latte Intero",
  "quantita": 2.0,
  "unita_misura": "LITRI",
  "categoria": "LATTICINI",
  "ubicazione": "FRIGO",
  "data_scadenza": "2024-01-30",
  "prezzo_acquisto": 1.50,
  "fornitore": "Centrale del Latte"
}
```

**Lista Alimenti**
```http
GET /api/alimenti?categoria=VERDURE&ubicazione=FRIGO
Authorization: Bearer YOUR_API_KEY
```

### Tool MCP Disponibili

#### Gestione Alimenti

1. **aggiungere_alimento**
   ```python
   # Parametri richiesti:
   nome: str
   quantita: float  
   unita_misura: "PEZZI|KG|LITRI|GRAMMI"
   categoria: "LATTICINI|VERDURE|FRUTTA|CARNE|PESCE|CONSERVE|BEVANDE|ALTRO"
   ubicazione: "FRIGO|FREEZER|DISPENSA|CANTINA"
   
   # Parametri opzionali:
   data_scadenza: "YYYY-MM-DD"
   data_apertura: "YYYY-MM-DD"
   prezzo_acquisto: float
   fornitore: str
   lotto_acquisto: str
   modificato_da: str (default: "user")
   ```

2. **consultare_giacenze**
   ```python
   # Tutti parametri opzionali per filtri:
   categoria: str
   ubicazione: str
   in_scadenza_giorni: int
   quantita_minima: float
   ```

3. **scaricare_alimento**
   ```python
   # Registra consumo alimento
   alimento_id: int
   quantita_consumata: float
   motivo: "CONSUMATO|SCADUTO|BUTTATO" (default: "CONSUMATO")
   note: str (opzionale)
   forza_operazione: bool (default: False)
   utente: str (default: "user")
   ```

4. **notifiche_scadenza**
   ```python
   giorni_limite: int (default: 3)
   # Restituisce alimenti in scadenza
   ```

5. **statistiche_consumi**
   ```python
   data_inizio: "YYYY-MM-DD" (default: ultimi 30 giorni)
   data_fine: "YYYY-MM-DD" (default: oggi)
   gruppo_per: "categoria|motivo|totale" (default: "categoria")
   ```

#### Gestione Task

1. **inserire_task**
   ```python
   titolo: str
   descrizione: str (opzionale)
   priorita: "ALTA|MEDIA|BASSA" (default: "MEDIA")
   data_scadenza: "YYYY-MM-DD" (opzionale)
   assegnatario: str (opzionale)
   task_ricorrente: bool (default: False)
   frequenza_ricorrenza: "GIORNALIERA|SETTIMANALE|MENSILE" (se ricorrente)
   creato_da: str (default: "user")
   ```

2. **elencare_task**
   ```python
   # Tutti parametri opzionali per filtri:
   stato: "DA_FARE|IN_CORSO|COMPLETATO|ANNULLATO"
   priorita: "ALTA|MEDIA|BASSA"
   assegnatario: str
   scadenza_entro_giorni: int
   solo_ricorrenti: bool (default: False)
   ```

3. **aggiornare_task**
   ```python
   task_id: int
   # Tutti gli altri campi opzionali per modifica:
   titolo: str
   descrizione: str
   priorita: "ALTA|MEDIA|BASSA"
   stato: "DA_FARE|IN_CORSO|COMPLETATO|ANNULLATO"
   data_scadenza: "YYYY-MM-DD"
   assegnatario: str
   modificato_da: str (default: "user")
   ```

4. **completare_task**
   ```python
   task_id: int
   modificato_da: str (default: "user")
   # Gestisce automaticamente le ricorrenze
   ```

5. **statistiche_task**
   ```python
   data_inizio: "YYYY-MM-DD" (default: ultimi 30 giorni)
   data_fine: "YYYY-MM-DD" (default: oggi)
   gruppo_per: "stato|priorita|assegnatario" (default: "stato")
   ```

## 💡 Esempi di Utilizzo con LLM

### Scenario 1: Gestione Magazzino
```
Utente: "Aggiungi 2 litri di latte che scade il 25 gennaio"

LLM chiama: aggiungere_alimento
- nome: "Latte"
- quantita: 2.0
- unita_misura: "LITRI" 
- categoria: "LATTICINI"
- ubicazione: "FRIGO"
- data_scadenza: "2024-01-25"
```

### Scenario 2: Controllo Scadenze
```
Utente: "Cosa scade nei prossimi 5 giorni?"

LLM chiama: notifiche_scadenza
- giorni_limite: 5

Output: Lista alimenti con giorni rimanenti e ubicazione
```

### Scenario 3: Task Ricorrenti
```
Utente: "Crea un promemoria settimanale per controllare le scadenze"

LLM chiama: inserire_task
- titolo: "Controllo scadenze alimenti"
- descrizione: "Verificare alimenti in scadenza e pianificare utilizzo"
- priorita: "MEDIA"
- task_ricorrente: True
- frequenza_ricorrenza: "SETTIMANALE"
```

## 🧪 Testing

### Esecuzione Test
```bash
# Test completi
python3 -m pytest tests/ -v

# Test specifici
python3 -m pytest tests/test_inventario_mcp.py::TestAlimenti -v

# Test con coverage
pip install pytest-cov
python3 -m pytest --cov=. tests/
```

### Test Database
Per i test è necessario un database separato:
```bash
createdb test_inventario_db
export TEST_DATABASE_URL="postgresql://user:password@localhost/test_inventario_db"
```

## 📊 Monitoraggio

### Logs
Il server produce log strutturati:
```
2024-01-15 10:30:00 - INFO - 🔄 POST /api/alimenti - IP: 192.168.1.100
2024-01-15 10:30:01 - INFO - ✅ POST /api/alimenti - 200 - 0.045s
```

### Metriche Database
```sql
-- Conteggio alimenti per categoria
SELECT categoria, COUNT(*) FROM alimenti GROUP BY categoria;

-- Task completati ultima settimana  
SELECT COUNT(*) FROM task 
WHERE stato = 'COMPLETATO' 
AND ultima_modifica >= NOW() - INTERVAL '7 days';

-- Log operazioni per tipo
SELECT tipo_operazione, COUNT(*) FROM log_operazioni 
GROUP BY tipo_operazione ORDER BY count DESC;
```

## 🔧 Configurazione Avanzata

### Pool Connessioni
```python
# In server_complete.py
db_pool = await asyncpg.create_pool(
    DATABASE_URL,
    min_size=2,        # Connessioni minime
    max_size=10,       # Connessioni massime
    command_timeout=30 # Timeout query
)
```

### Rate Limiting (Produzione)
```python
from slowapi import Limiter
limiter = Limiter(key_func=lambda: "global")

@app.post("/api/alimenti")
@limiter.limit("100/minute")
async def create_alimento(...):
```

## 🔐 Sicurezza

### Raccomandazioni Produzione
1. **API Key**: Usa chiavi sicure (min 32 caratteri)
2. **HTTPS**: Sempre in produzione
3. **Database**: Limita connessioni per IP
4. **Rate Limiting**: Implementa limiti per endpoint
5. **Input Validation**: Già implementata con Pydantic
6. **Logs**: Non loggare dati sensibili

### Esempio Chiave Sicura
```bash
# Genera API key sicura
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

## 🚨 Troubleshooting

### Errori Comuni

**1. Connessione Database**
```
❌ Errore: could not connect to server
✅ Soluzione: Verifica DATABASE_URL e che PostgreSQL sia avviato
```

**2. Import MCP**
```
❌ Errore: ModuleNotFoundError: No module named 'mcp'
✅ Soluzione: pip install -r requirements.txt
```

**3. Autenticazione**
```
❌ Errore: 401 Unauthorized
✅ Soluzione: Verifica header Authorization con API_KEY corretta
```

### Debug Mode
```bash
export DEBUG=true
python3 server_complete.py
```

## 📞 Supporto

- **Issues**: Apri un issue su GitHub
- **Email**: [il-tuo-email]
- **Documentazione**: Questa README

## 📄 Licenza

MIT License - vedi file LICENSE per dettagli.

---

**Sviluppato per l'automazione intelligente della gestione inventario tramite LLM** 🤖📦
