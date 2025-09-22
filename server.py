#!/usr/bin/env python3
"""
Server MCP per gestione inventario alimentari e task management
Basato su postgres-mcp con funzionalità avanzate
"""

import asyncio
import json
import logging
import os
from datetime import datetime, date, timedelta
from decimal import Decimal
from typing import Dict, List, Optional, Any, Union
from contextlib import asynccontextmanager

import asyncpg
import uvicorn
from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, validator
from mcp import Tool, types
from mcp.server import Server
from mcp.types import TextContent, ImageContent, EmbeddedResource

# Configurazione logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configurazione da variabili d'ambiente
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:password@localhost/inventario_db")
API_KEY = os.getenv("API_KEY", "your-secret-api-key-here")
PORT = int(os.getenv("PORT", "8000"))

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
                min_size=2,
                max_size=10,
                command_timeout=30,
                server_settings={
                    'application_name': 'inventario_mcp_server',
                    'timezone': 'Europe/Rome'
                }
            )
            logger.info("Pool di connessioni database creato con successo")
        except Exception as e:
            logger.error(f"Errore nella creazione del pool database: {e}")
            raise
    
    @staticmethod
    async def close_pool():
        global db_pool
        if db_pool:
            await db_pool.close()
            logger.info("Pool di connessioni database chiuso")

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Gestione del ciclo di vita dell'applicazione"""
    await DatabaseConfig.create_pool()
    yield
    await DatabaseConfig.close_pool()

# Inizializzazione FastAPI con CORS
app = FastAPI(
    title="Inventario MCP Server",
    description="Server MCP per gestione inventario alimentari e task management",
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
async def verify_api_key(x_api_key: str = Header(None)):
    """Verifica l'API key nelle richieste"""
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="API Key non valida")
    return x_api_key

# Dependency per connessione database
async def get_db_connection():
    """Ottiene connessione dal pool"""
    if not db_pool:
        raise HTTPException(status_code=500, detail="Pool database non disponibile")
    return await db_pool.acquire()

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
        """, tipo_operazione, tabella, id_record, json.dumps(dettagli), utente)
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

# Custom JSON encoder per response
class CustomJSONResponse:
    @staticmethod
    def serialize(data):
        return json.dumps(data, default=serialize_datetime, ensure_ascii=False)
