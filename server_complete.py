#!/usr/bin/env python3
"""
Server MCP completo per gestione inventario e task management
Integrazione completa con FastAPI e MCP
"""

import asyncio
import json
import logging
import os
import sys
from contextlib import asynccontextmanager
from datetime import datetime, date, timedelta
from decimal import Decimal
from typing import Dict, List, Optional, Any, Union

import asyncpg
import uvicorn
from fastapi import FastAPI, HTTPException, Depends, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from mcp.server import Server
from mcp.types import Tool, TextContent
from dotenv import load_dotenv

# Carica variabili d'ambiente dal file .env
load_dotenv()

# Configurazione logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configurazione da variabili d'ambiente
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:password@localhost/inventario_db")
API_KEY = os.getenv("API_KEY", "your-secret-api-key-here")
PORT = int(os.getenv("PORT", "10000"))

# Pool di connessioni PostgreSQL
db_pool: Optional[asyncpg.Pool] = None

class DatabaseConfig:
    """Configurazione database con pool di connessioni"""
    
    @staticmethod
    async def create_pool():
        global db_pool
        try:
            db_pool = await asyncpg.create_pool(
                DATABASE_URL,
                min_size=1,
                max_size=10,
                command_timeout=60
            )
            logger.info("Pool di connessioni database creato con successo")
            
            # Test connessione e setup schema
            async with db_pool.acquire() as conn:
                version = await conn.fetchval("SELECT version()")
                logger.info(f"Connesso a PostgreSQL: {version}")
                
                # Verifica se le tabelle esistono, altrimenti crea lo schema
                await DatabaseConfig.setup_schema(conn)
                
        except Exception as e:
            logger.error(f"Errore nella creazione del pool database: {e}")
            raise

    @staticmethod
    async def setup_schema(conn):
        """Setup automatico dello schema database"""
        try:
            # Verifica se la tabella alimenti esiste
            exists = await conn.fetchval(
                "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'alimenti')"
            )
            
            if not exists:
                logger.info("Schema database non trovato, creazione in corso...")
                
                # Leggi e esegui lo schema SQL
                import os
                schema_path = os.path.join(os.path.dirname(__file__), 'database', 'schema.sql')
                
                if os.path.exists(schema_path):
                    with open(schema_path, 'r', encoding='utf-8') as f:
                        schema_sql = f.read()
                    
                    # Esegui lo schema in una transazione
                    await conn.execute(schema_sql)
                    logger.info("✅ Schema database creato con successo!")
                else:
                    logger.warning("File schema.sql non trovato, continuazione senza setup automatico")
            else:
                logger.info("✅ Schema database già esistente")
                
        except Exception as e:
            logger.error(f"Errore nel setup schema: {e}")
            # Non bloccare l'avvio se il setup fallisce

    @staticmethod
    async def close_pool():
        global db_pool
        if db_pool:
            await db_pool.close()
            logger.info("Pool di connessioni database chiuso")

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Gestione del ciclo di vita dell'applicazione"""
    logger.info("Avvio server MCP Inventario...")
    await DatabaseConfig.create_pool()
    yield
    logger.info("Chiusura server MCP Inventario...")
    await DatabaseConfig.close_pool()

# Inizializzazione FastAPI
app = FastAPI(
    title="Inventario MCP Server",
    description="Server MCP per gestione inventario alimentari e task management con PostgreSQL",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,  
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Inizializzazione MCP Server
mcp_server = Server("inventario-mcp")

# Dependency per autenticazione API Key
async def verify_api_key(authorization: Optional[str] = Header(None)):
    """Verifica l'API key nelle richieste"""
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header mancante")
    
    # Supporta formato "Bearer API_KEY" o solo "API_KEY"  
    token = authorization.replace("Bearer ", "") if authorization.startswith("Bearer ") else authorization
    
    if token != API_KEY:
        raise HTTPException(status_code=401, detail="API key non valida")
    
    return token

# Endpoint MCP JSON-RPC 2.0 
@app.post("/mcp")
async def mcp_endpoint(request: dict, api_key: str = Depends(verify_api_key)):
    """Endpoint principale MCP che implementa JSON-RPC 2.0"""
    try:
        # Verifica formato JSON-RPC 2.0
        if request.get("jsonrpc") != "2.0":
            raise HTTPException(status_code=400, detail="Richiede JSON-RPC 2.0")
        
        method = request.get("method")
        request_id = request.get("id")
        params = request.get("params", {})
        
        if method == "tools/list":
            # Lista dei tool MCP disponibili per OpenAI ChatGPT
            result = {
                "tools": [
                    {
                        "name": "search",
                        "title": "Search Inventory Database",
                        "description": "Search for food items and tasks in the inventory database. Returns relevant results based on keywords.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "query": {
                                    "type": "string", 
                                    "description": "Search query for food items, categories, locations, or tasks"
                                }
                            },
                            "required": ["query"]
                        }
                    },
                    {
                        "name": "fetch",
                        "title": "Fetch Item Details",
                        "description": "Retrieve complete details of a specific food item or task by ID",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "id": {
                                    "type": "string",
                                    "description": "Unique identifier for the food item or task (format: 'alimento-{id}' or 'task-{id}')"
                                }
                            },
                            "required": ["id"]
                        }
                    }
                ]
            }
            
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": result
            }
            
        elif method == "tools/call":
            # Chiamata di un tool specifico per OpenAI ChatGPT
            tool_name = params.get("name")
            arguments = params.get("arguments", {})
            
            if tool_name == "search":
                content = await openai_search_tool(**arguments)
            elif tool_name == "fetch":
                content = await openai_fetch_tool(**arguments)
            else:
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {
                        "code": -32601,
                        "message": f"Tool '{tool_name}' non trovato"
                    }
                }
            
            return {
                "jsonrpc": "2.0", 
                "id": request_id,
                "result": {
                    "content": content,
                    "isError": False
                }
            }
            
        else:
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": -32601,
                    "message": f"Metodo '{method}' non supportato"
                }
            }
            
    except Exception as e:
        logger.error(f"Errore MCP endpoint: {e}")
        return {
            "jsonrpc": "2.0",
            "id": request.get("id"),
            "error": {
                "code": -32603,
                "message": f"Errore interno: {str(e)}"
            }
        }

# Implementazioni dei tool MCP per OpenAI ChatGPT
async def openai_search_tool(query: str):
    """
    Tool search richiesto da OpenAI ChatGPT.
    Cerca nel database degli alimenti e task restituendo risultati in formato OpenAI.
    """
    try:
        async with db_pool.acquire() as conn:
            results = []
            
            # Cerca negli alimenti
            alimenti_rows = await conn.fetch("""
                SELECT id, nome, quantita, unita_misura, categoria, ubicazione, data_scadenza
                FROM alimenti 
                WHERE LOWER(nome) LIKE LOWER($1) 
                   OR LOWER(categoria::text) LIKE LOWER($1)
                   OR LOWER(ubicazione::text) LIKE LOWER($1)
                ORDER BY data_inserimento DESC
                LIMIT 10
            """, f"%{query}%")
            
            for row in alimenti_rows:
                scadenza_info = f" - Scade: {row['data_scadenza']}" if row['data_scadenza'] else ""
                results.append({
                    "id": f"alimento-{row['id']}",
                    "title": f"{row['nome']} ({row['quantita']} {row['unita_misura']})",
                    "url": f"https://sql-mcp-server.onrender.com/api/alimenti/{row['id']}"
                })
            
            # Cerca nei task (se esistono)
            try:
                task_rows = await conn.fetch("""
                    SELECT id, titolo, descrizione, priorita, stato
                    FROM task 
                    WHERE LOWER(titolo) LIKE LOWER($1) 
                       OR LOWER(descrizione) LIKE LOWER($1)
                    ORDER BY data_creazione DESC
                    LIMIT 5
                """, f"%{query}%")
                
                for row in task_rows:
                    results.append({
                        "id": f"task-{row['id']}",
                        "title": f"Task: {row['titolo']} ({row['stato']})",
                        "url": f"https://sql-mcp-server.onrender.com/api/task/{row['id']}"
                    })
            except:
                # Task table might not exist yet
                pass
            
            # Formato richiesto da OpenAI: JSON string nel content
            results_json = json.dumps({"results": results})
            
            return [
                {
                    "type": "text",
                    "text": results_json
                }
            ]
            
    except Exception as e:
        logger.error(f"Errore search tool: {e}")
        return [
            {
                "type": "text", 
                "text": json.dumps({"results": [], "error": str(e)})
            }
        ]

async def openai_fetch_tool(id: str):
    """
    Tool fetch richiesto da OpenAI ChatGPT.
    Recupera i dettagli completi di un alimento o task specifico.
    """
    try:
        if id.startswith("alimento-"):
            alimento_id = int(id.replace("alimento-", ""))
            
            async with db_pool.acquire() as conn:
                row = await conn.fetchrow("""
                    SELECT * FROM alimenti WHERE id = $1
                """, alimento_id)
                
                if not row:
                    raise ValueError(f"Alimento ID {alimento_id} non trovato")
                
                # Prepara il documento completo
                text_content = f"""
ALIMENTO: {row['nome']}

Dettagli:
- Quantità: {row['quantita']} {row['unita_misura']}
- Categoria: {row['categoria']}
- Ubicazione: {row['ubicazione']}
- Data scadenza: {row['data_scadenza'] or 'Non specificata'}
- Data apertura: {row['data_apertura'] or 'Non aperto'}
- Prezzo acquisto: €{row['prezzo_acquisto'] or 'N/A'}
- Fornitore: {row['fornitore'] or 'Non specificato'}
- Lotto: {row['lotto_acquisto'] or 'Non specificato'}
- Inserito il: {row['data_inserimento']}
- Modificato il: {row['ultima_modifica']}
- Modificato da: {row['modificato_da']}
"""
                
                document = {
                    "id": id,
                    "title": f"Alimento: {row['nome']}",
                    "text": text_content,
                    "url": f"https://sql-mcp-server.onrender.com/api/alimenti/{alimento_id}",
                    "metadata": {
                        "type": "alimento",
                        "categoria": row['categoria'],
                        "ubicazione": row['ubicazione']
                    }
                }
                
        elif id.startswith("task-"):
            task_id = int(id.replace("task-", ""))
            
            async with db_pool.acquire() as conn:
                row = await conn.fetchrow("""
                    SELECT * FROM task WHERE id = $1
                """, task_id)
                
                if not row:
                    raise ValueError(f"Task ID {task_id} non trovato")
                
                text_content = f"""
TASK: {row['titolo']}

Dettagli:
- Descrizione: {row['descrizione'] or 'Nessuna descrizione'}
- Priorità: {row['priorita']}
- Stato: {row['stato']}
- Data scadenza: {row['data_scadenza'] or 'Non specificata'}
- Assegnatario: {row['assegnatario'] or 'Non assegnato'}
- Ricorrente: {'Sì' if row['task_ricorrente'] else 'No'}
- Frequenza: {row['frequenza_ricorrenza'] or 'N/A'}
- Creato il: {row['data_creazione']}
- Creato da: {row['creato_da']}
- Modificato il: {row['ultima_modifica']}
"""
                
                document = {
                    "id": id,
                    "title": f"Task: {row['titolo']}",
                    "text": text_content,
                    "url": f"https://sql-mcp-server.onrender.com/api/task/{task_id}",
                    "metadata": {
                        "type": "task",
                        "priorita": row['priorita'],
                        "stato": row['stato']
                    }
                }
        else:
            raise ValueError(f"ID format non valido: {id}")
        
        # Formato richiesto da OpenAI: JSON string nel content
        document_json = json.dumps(document)
        
        return [
            {
                "type": "text",
                "text": document_json
            }
        ]
        
    except Exception as e:
        logger.error(f"Errore fetch tool: {e}")
        return [
            {
                "type": "text",
                "text": json.dumps({"error": str(e)})
            }
        ]

# Implementazioni dei tool MCP legacy (mantenuti per compatibilità)
async def mcp_health_check():
    """Tool MCP per health check"""
    try:
        async with db_pool.acquire() as conn:
            version = await conn.fetchval("SELECT version()")
            db_status = "🟢 Database connesso"
    except Exception as e:
        db_status = f"🔴 Database errore: {e}"
    
    return {
        "content": [
            {
                "type": "text", 
                "text": f"🏥 **Stato Server MCP Inventario**\n\n{db_status}\n🕒 Timestamp: {datetime.now().isoformat()}\n🔑 API Key configurata: ✅"
            }
        ]
    }

async def mcp_lista_alimenti(**kwargs):
    """Tool MCP per lista alimenti"""
    try:
        async with db_pool.acquire() as conn:
            query = "SELECT * FROM alimenti WHERE quantita > 0"
            params = []
            
            if kwargs.get("categoria"):
                query += " AND categoria = $" + str(len(params) + 1)
                params.append(kwargs["categoria"])
                
            if kwargs.get("ubicazione"):
                query += " AND ubicazione = $" + str(len(params) + 1)
                params.append(kwargs["ubicazione"])
            
            query += " ORDER BY data_inserimento DESC"
            
            rows = await conn.fetch(query, *params)
            alimenti = [dict(row) for row in rows]
            
            text = f"📋 **Lista Alimenti** ({len(alimenti)} trovati)\n\n"
            for alimento in alimenti:
                text += f"• **{alimento['nome']}**: {alimento['quantita']} {alimento['unita_misura']} - {alimento['categoria']} ({alimento['ubicazione']})\n"
                if alimento['data_scadenza']:
                    text += f"  📅 Scadenza: {alimento['data_scadenza']}\n"
                text += "\n"
            
            return {"content": [{"type": "text", "text": text}]}
            
    except Exception as e:
        return {"content": [{"type": "text", "text": f"❌ Errore: {e}"}]}

async def mcp_aggiungi_alimento(**kwargs):
    """Tool MCP per aggiungere alimento"""
    try:
        async with db_pool.acquire() as conn:
            result = await conn.fetchrow("""
                INSERT INTO alimenti (nome, quantita, unita_misura, categoria, ubicazione, data_scadenza, modificato_da)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                RETURNING id, data_inserimento
            """, 
            kwargs['nome'], 
            kwargs['quantita'], 
            kwargs['unita_misura'], 
            kwargs['categoria'], 
            kwargs['ubicazione'], 
            kwargs.get('data_scadenza'),
            'mcp_tool'
            )
            
            return {
                "content": [
                    {
                        "type": "text", 
                        "text": f"✅ **Alimento Aggiunto**\n\n📦 {kwargs['nome']}\n🔢 Quantità: {kwargs['quantita']} {kwargs['unita_misura']}\n📂 Categoria: {kwargs['categoria']}\n📍 Ubicazione: {kwargs['ubicazione']}\n🆔 ID: {result['id']}"
                    }
                ]
            }
            
    except Exception as e:
        return {"content": [{"type": "text", "text": f"❌ Errore aggiunta alimento: {e}"}]}

async def mcp_alimenti_in_scadenza(**kwargs):
    """Tool MCP per alimenti in scadenza"""
    try:
        giorni = kwargs.get('giorni', 3)
        async with db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT * FROM alimenti_in_scadenza($1)
            """, giorni)
            
            text = f"⚠️ **Alimenti in Scadenza** (entro {giorni} giorni)\n\n"
            
            if not rows:
                text += "🎉 Nessun alimento in scadenza!"
            else:
                for row in rows:
                    giorni_rimanenti = row['giorni_alla_scadenza']
                    stato = "🔴 SCADUTO" if giorni_rimanenti < 0 else f"⚠️ {giorni_rimanenti} giorni"
                    text += f"• **{row['nome']}**: {row['quantita']} {row['unita_misura']} - {stato}\n"
                    text += f"  📅 Scadenza: {row['data_scadenza']} ({row['categoria']} - {row['ubicazione']})\n\n"
            
            return {"content": [{"type": "text", "text": text}]}
            
    except Exception as e:
        return {"content": [{"type": "text", "text": f"❌ Errore: {e}"}]}

# Dependency per autenticazione API Key
async def verify_api_key(authorization: Optional[str] = Header(None)):
    """Verifica l'API key nelle richieste"""
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header mancante")
    
    # Supporta formato "Bearer API_KEY" o solo "API_KEY"  
    token = authorization.replace("Bearer ", "") if authorization.startswith("Bearer ") else authorization
    
    if token != API_KEY:
        raise HTTPException(status_code=401, detail="API Key non valida")
    return token

# Utility per logging operazioni
async def log_operation(
    conn: asyncpg.Connection,
    tipo_operazione: str,
    tabella: str,
    id_record: int,
    dettagli: Dict[str, Any],
    utente: str
):
    """Registra operazione nel log"""
    try:
        await conn.execute("""
            INSERT INTO log_operazioni (tipo_operazione, tabella, id_record, dettagli, utente)
            VALUES ($1, $2, $3, $4, $5)
        """, tipo_operazione, tabella, id_record, json.dumps(dettagli, default=str), utente)
    except Exception as e:
        logger.error(f"Errore nel logging operazione: {e}")

# Utility per conversione date/datetime
def serialize_datetime(obj):
    """Serializza date e datetime per JSON"""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")

# Modelli Pydantic per API REST
class AlimentoModel(BaseModel):
    nome: str
    quantita: float = Field(gt=0)
    unita_misura: str = Field(pattern="^(PEZZI|KG|LITRI|GRAMMI)$")  
    categoria: str = Field(pattern="^(LATTICINI|VERDURE|FRUTTA|CARNE|PESCE|CONSERVE|BEVANDE|ALTRO)$")
    ubicazione: str = Field(pattern="^(FRIGO|FREEZER|DISPENSA|CANTINA)$")
    data_scadenza: Optional[str] = None
    data_apertura: Optional[str] = None
    prezzo_acquisto: Optional[float] = Field(None, ge=0)
    fornitore: Optional[str] = None
    lotto_acquisto: Optional[str] = None

class TaskModel(BaseModel):
    titolo: str = Field(max_length=500)
    descrizione: Optional[str] = None
    priorita: str = Field(default="MEDIA", pattern="^(ALTA|MEDIA|BASSA)$")
    data_scadenza: Optional[str] = None
    assegnatario: Optional[str] = None
    task_ricorrente: bool = False
    frequenza_ricorrenza: Optional[str] = Field(None, pattern="^(GIORNALIERA|SETTIMANALE|MENSILE)$")

# Registrazione dei tool MCP - Import dinamico per evitare dipendenze circolari
def register_mcp_tools():
    """Registra tutti i tool MCP"""
    # Qui importiamo e registriamo i tool dai file separati
    # Per semplicità, li includiamo direttamente nel main file
    
    @mcp_server.call_tool()
    async def health_check() -> List[TextContent]:
        """Check dello stato del server e database"""
        try:
            async with db_pool.acquire() as conn:
                result = await conn.fetchval("SELECT 'OK' as status")
                db_status = "✅ Database connesso"
        except Exception as e:
            db_status = f"❌ Errore database: {str(e)}"
        
        return [TextContent(
            type="text",
            text=f"🏥 **Stato Server MCP Inventario**\n\n"
                 f"{db_status}\n"
                 f"🕒 Timestamp: {datetime.now().isoformat()}\n"
                 f"🔑 API Key configurata: {'✅' if API_KEY != 'your-secret-api-key-here' else '❌'}\n"
                 f"🐘 Pool database: {db_pool.get_size() if db_pool else 0} connessioni"
        )]

# Routes FastAPI per compatibilità REST
@app.get("/")
async def root():
    """Endpoint di benvenuto"""
    return {
        "message": "Server MCP Inventario e Task Management",
        "version": "1.0.0",
        "endpoints": {
            "health": "/health",
            "mcp": "/mcp/*",
            "docs": "/docs"
        }
    }

@app.get("/health")
async def health_check_rest():
    """Health check REST"""
    try:
        async with db_pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        return {"status": "healthy", "database": "connected", "timestamp": datetime.now()}
    except Exception as e:
        return JSONResponse(
            status_code=503, 
            content={"status": "unhealthy", "error": str(e), "timestamp": datetime.now()}
        )

@app.post("/api/alimenti")
async def create_alimento_rest(alimento: AlimentoModel, auth: str = Depends(verify_api_key)):
    """Crea alimento via REST API"""
    try:
        async with db_pool.acquire() as conn:
            # Parsing date
            scadenza_date = datetime.strptime(alimento.data_scadenza, "%Y-%m-%d").date() if alimento.data_scadenza else None
            apertura_date = datetime.strptime(alimento.data_apertura, "%Y-%m-%d").date() if alimento.data_apertura else None
            
            result = await conn.fetchrow("""
                INSERT INTO alimenti 
                (nome, quantita, unita_misura, data_scadenza, data_apertura, 
                 categoria, ubicazione, prezzo_acquisto, fornitore, lotto_acquisto, modificato_da)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, 'rest_api')
                RETURNING id, data_inserimento
            """, alimento.nome, alimento.quantita, alimento.unita_misura, 
                scadenza_date, apertura_date, alimento.categoria, alimento.ubicazione,
                alimento.prezzo_acquisto, alimento.fornitore, alimento.lotto_acquisto)
            
            await log_operation(conn, "INSERT_REST", "alimenti", result['id'], alimento.dict(), "rest_api")
            
            return {"id": result['id'], "created_at": result['data_inserimento'], "status": "created"}
            
    except Exception as e:
        logger.error(f"Errore creazione alimento REST: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/alimenti")
async def list_alimenti_rest(
    categoria: Optional[str] = None,
    ubicazione: Optional[str] = None,
    auth: str = Depends(verify_api_key)
):
    """Lista alimenti via REST API"""
    try:
        async with db_pool.acquire() as conn:
            query = "SELECT * FROM alimenti WHERE quantita > 0"
            params = []
            
            if categoria:
                query += " AND categoria = $1"
                params.append(categoria)
            if ubicazione:
                param_num = len(params) + 1
                query += f" AND ubicazione = ${param_num}"
                params.append(ubicazione)
                
            query += " ORDER BY nome"
            
            rows = await conn.fetch(query, *params)
            
            alimenti = []
            for row in rows:
                alimento_dict = dict(row)
                # Serializza date e decimali
                if alimento_dict['data_scadenza']:
                    alimento_dict['data_scadenza'] = alimento_dict['data_scadenza'].isoformat()
                if alimento_dict['data_apertura']:
                    alimento_dict['data_apertura'] = alimento_dict['data_apertura'].isoformat()
                if alimento_dict['quantita']:
                    alimento_dict['quantita'] = float(alimento_dict['quantita'])
                if alimento_dict['prezzo_acquisto']:
                    alimento_dict['prezzo_acquisto'] = float(alimento_dict['prezzo_acquisto'])
                alimento_dict['data_inserimento'] = alimento_dict['data_inserimento'].isoformat()
                alimento_dict['ultima_modifica'] = alimento_dict['ultima_modifica'].isoformat()
                
                alimenti.append(alimento_dict)
            
            return {"alimenti": alimenti, "count": len(alimenti)}
            
    except Exception as e:
        logger.error(f"Errore lista alimenti REST: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Middleware per logging delle richieste MCP
@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log delle richieste HTTP"""
    start_time = datetime.now()
    
    # Log richiesta
    logger.info(f"🔄 {request.method} {request.url.path} - IP: {request.client.host}")
    
    response = await call_next(request)
    
    # Log risposta
    duration = (datetime.now() - start_time).total_seconds()
    logger.info(f"✅ {request.method} {request.url.path} - {response.status_code} - {duration:.3f}s")
    
    return response

# Gestione errori globale
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Gestore errori globale"""
    logger.error(f"❌ Errore non gestito: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": "Errore interno del server",
            "detail": str(exc) if os.getenv("DEBUG", "false").lower() == "true" else "Errore generico",
            "timestamp": datetime.now().isoformat()
        }
    )

if __name__ == "__main__":
    # Registrazione tool MCP
    register_mcp_tools()
    
    logger.info("🚀 Avvio server MCP Inventario...")
    logger.info(f"📊 Porta: {PORT}")
    logger.info(f"🗄️  Database: {DATABASE_URL.split('/')[-1] if '/' in DATABASE_URL else 'localhost'}")
    logger.info(f"🔑 API Key configurata: {'✅' if API_KEY != 'your-secret-api-key-here' else '❌'}")
    
    # Configurazione per produzione (Render) vs sviluppo
    is_production = os.getenv("RENDER") is not None
    
    uvicorn.run(
        "server_complete:app" if is_production else app,
        host="0.0.0.0",
        port=PORT,
        reload=False,
        log_level="info",
        access_log=True
    )
