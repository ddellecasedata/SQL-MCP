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

# Endpoint per servire il protocollo MCP
@app.get("/mcp/tools")
async def get_mcp_tools():
    """Endpoint per ottenere la lista dei tool MCP disponibili"""
    return {
        "tools": [
            {
                "name": "health_check",
                "description": "Check dello stato del server e database",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            },
            {
                "name": "lista_alimenti",
                "description": "Ottieni lista completa degli alimenti nell'inventario",
                "inputSchema": {
                    "type": "object", 
                    "properties": {
                        "categoria": {"type": "string", "description": "Filtra per categoria"},
                        "ubicazione": {"type": "string", "description": "Filtra per ubicazione"}
                    }
                }
            },
            {
                "name": "aggiungi_alimento",
                "description": "Aggiungi un nuovo alimento all'inventario", 
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "nome": {"type": "string", "description": "Nome alimento"},
                        "quantita": {"type": "number", "description": "Quantità"},
                        "unita_misura": {"type": "string", "enum": ["PEZZI", "KG", "LITRI", "GRAMMI"]},
                        "categoria": {"type": "string", "enum": ["LATTICINI", "VERDURE", "FRUTTA", "CARNE", "PESCE", "CONSERVE", "BEVANDE", "ALTRO"]},
                        "ubicazione": {"type": "string", "enum": ["FRIGO", "FREEZER", "DISPENSA", "CANTINA"]},
                        "data_scadenza": {"type": "string", "format": "date", "description": "Data scadenza YYYY-MM-DD"}
                    },
                    "required": ["nome", "quantita", "unita_misura", "categoria", "ubicazione"]
                }
            },
            {
                "name": "alimenti_in_scadenza",
                "description": "Ottieni alimenti in scadenza entro N giorni",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "giorni": {"type": "integer", "default": 3, "description": "Giorni limite per scadenza"}
                    }
                }
            }
        ]
    }

@app.post("/mcp/call")
async def call_mcp_tool(request: dict, api_key: str = Depends(verify_api_key)):
    """Endpoint per chiamare un tool MCP"""
    tool_name = request.get("name")
    arguments = request.get("arguments", {})
    
    if tool_name == "health_check":
        return await mcp_health_check()
    elif tool_name == "lista_alimenti":
        return await mcp_lista_alimenti(**arguments)
    elif tool_name == "aggiungi_alimento":
        return await mcp_aggiungi_alimento(**arguments)
    elif tool_name == "alimenti_in_scadenza":
        return await mcp_alimenti_in_scadenza(**arguments)
    else:
        raise HTTPException(status_code=404, detail=f"Tool '{tool_name}' non trovato")

# Implementazioni dei tool MCP
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
