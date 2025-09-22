#!/usr/bin/env python3
"""
Remote MCP Server for Inventory Management
Implements OAuth 2.1 authentication and supports both modern and legacy transport protocols
"""

import asyncio
import json
import logging
import os
import uuid
import hashlib
import base64
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Union
from urllib.parse import urlparse, parse_qs

import asyncpg
from fastapi import FastAPI, Request, Response, HTTPException, Header, Depends, Form
from fastapi.responses import JSONResponse, HTMLResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from dotenv import load_dotenv
from pydantic import BaseModel

# MCP imports - simplified for HTTP server
from mcp.types import (
    Tool, TextContent, CallToolRequest, CallToolResult,
    ListToolsResult, GetPromptResult, PromptMessage,
    Implementation, ServerCapabilities, ToolsCapability
)

# Import tool implementations
from tools_magazzino import (
    aggiungere_alimento_impl, consultare_giacenze_impl, 
    scaricare_alimento_impl, notifiche_scadenza_impl
)
from tools_task import (
    inserire_task_impl, elencare_task_impl, completare_task_impl
)
from tools_complete import (
    aggiornare_alimento_impl, statistiche_consumi_impl,
    aggiornare_task_impl, cancellare_task_impl, statistiche_task_impl
)

# Load environment variables
load_dotenv()

# Configuration
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql:///inventario_db")
PORT = int(os.getenv("PORT", "10000"))
BASE_URL = os.getenv("BASE_URL", f"http://localhost:{PORT}")
AUTH_SECRET = os.getenv("AUTH_SECRET", secrets.token_hex(32))
DISABLE_AUTH = os.getenv("DISABLE_AUTH", "false").lower() == "true"  # Per debug/test

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Database pool
db_pool = None

# In-memory stores
mcp_sessions = {}  # session_id -> transport instance
auth_codes = {}   # code -> {user_info, expires_at, code_challenge, etc}
access_tokens = {}  # token -> {user_info, expires_at, scopes, etc}
registered_clients = {}  # client_id -> client_info

# Pydantic models for requests
class TokenRequest(BaseModel):
    grant_type: str
    code: Optional[str] = None
    redirect_uri: Optional[str] = None
    client_id: Optional[str] = None
    code_verifier: Optional[str] = None

class ClientRegistration(BaseModel):
    client_name: str
    redirect_uris: List[str] = []
    
class AuthInfo(BaseModel):
    token: str
    client_id: str
    scopes: List[str] = []
    expires_at: Optional[datetime] = None

# Lifespan event handler (replaces deprecated on_event)
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await setup_database()
    logger.info(f"🚀 Remote MCP Server started on port {PORT}")
    logger.info(f"🔗 OAuth Discovery: {BASE_URL}/.well-known/oauth-protected-resource")
    logger.info(f"🔐 Authorization endpoint: {BASE_URL}/authorize") 
    logger.info(f"🎯 MCP endpoint: {BASE_URL}/mcp")
    yield
    # Shutdown - cleanup if needed
    if db_pool:
        await db_pool.close()
    logger.info("Server shutdown complete")

# FastAPI app setup
app = FastAPI(
    title="Remote MCP Inventory Server",
    description="Production-ready MCP server with OAuth 2.1 authentication",
    version="3.0.0",
    lifespan=lifespan
)

# CORS middleware with proper MCP headers
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS", "DELETE"],
    allow_headers=[
        "Content-Type", 
        "Authorization", 
        "Mcp-Session-Id",
        "Accept",
        "Cache-Control"
    ],
    expose_headers=[
        "Mcp-Session-Id", 
        "WWW-Authenticate",
        "Content-Type"
    ]
)

# Add static files and templates for auth UI
templates = Jinja2Templates(directory="templates") if os.path.exists("templates") else None

# Root endpoint per evitare 404
@app.get("/")
async def root():
    """Root endpoint con info sul server MCP"""
    return {
        "name": "Remote MCP Inventory Server",
        "version": "3.0.0",
        "mcp_endpoint": "/mcp",
        "debug_endpoint": "/mcp-debug",
        "oauth_discovery": "/.well-known/oauth-protected-resource",
        "health_check": "/health"
    }

# Utility functions
def get_base_url(request: Request) -> str:
    """Get base URL from request or environment"""
    if os.getenv("RENDER"):
        return "https://sql-mcp-server.onrender.com"
    
    # Build from request
    scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("host", request.url.netloc)
    return f"{scheme}://{host}"

def generate_code_challenge():
    """Generate PKCE code verifier and challenge"""
    code_verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode('utf-8').rstrip('=')
    code_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode('utf-8')).digest()
    ).decode('utf-8').rstrip('=')
    return code_verifier, code_challenge

# Database setup
async def setup_database():
    """Setup database connection pool and schema"""
    global db_pool
    try:
        db_pool = await asyncpg.create_pool(
            DATABASE_URL,
            min_size=1,
            max_size=10,
            command_timeout=60
        )
        logger.info("Database pool created successfully")
        
        # Setup schema if needed
        async with db_pool.acquire() as conn:
            exists = await conn.fetchval(
                "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'alimenti')"
            )
            
            if not exists:
                logger.info("Creating database schema...")
                schema_path = os.path.join(os.path.dirname(__file__), 'database', 'schema.sql')
                if os.path.exists(schema_path):
                    with open(schema_path, 'r', encoding='utf-8') as f:
                        schema_sql = f.read()
                    await conn.execute(schema_sql)
                    logger.info("✅ Database schema created")
                    
    except Exception as e:
        logger.error(f"Database setup error: {e}")
        raise

# Authentication helper
async def authenticate_token(request: Request, rpc_id: Optional[str] = None) -> dict:
    """Authenticate Bearer token and return auth info"""
    auth_header = request.headers.get("authorization", "")
    token = auth_header.replace("Bearer ", "").strip() if auth_header.startswith("Bearer ") else ""
    base_url = get_base_url(request)
    
    if not token:
        www_auth_header = f'Bearer realm="MCP Server", resource_metadata_uri="{base_url}/.well-known/oauth-protected-resource"'
        return {
            "success": False,
            "response": JSONResponse(
                status_code=401,
                headers={"WWW-Authenticate": www_auth_header},
                content={
                    "jsonrpc": "2.0",
                    "error": {"code": -32000, "message": "Missing Bearer token"},
                    "id": rpc_id
                }
            )
        }
    
    # Check if token exists and is valid
    token_data = access_tokens.get(token)
    if not token_data:
        return {
            "success": False,
            "response": JSONResponse(
                status_code=403,
                content={
                    "jsonrpc": "2.0", 
                    "error": {"code": -32001, "message": "Invalid or expired token"},
                    "id": rpc_id
                }
            )
        }
    
    # Check if token is expired
    if token_data.get("expires_at") and datetime.now() > token_data["expires_at"]:
        del access_tokens[token]
        return {
            "success": False,
            "response": JSONResponse(
                status_code=403,
                content={
                    "jsonrpc": "2.0",
                    "error": {"code": -32001, "message": "Token expired"},
                    "id": rpc_id
                }
            )
        }
    
    # Return auth info for MCP tools
    return {
        "success": True,
        "auth_info": {
            "token": token,
            "client_id": str(token_data.get("client_id", "")),
            "scopes": token_data.get("scopes", []),
            "user_id": token_data.get("user_id")
        }
    }

# OAuth 2.1 Discovery Endpoints
@app.get("/.well-known/oauth-protected-resource")
async def oauth_protected_resource(request: Request):
    """OAuth 2.1 protected resource discovery"""
    base_url = get_base_url(request)
    
    return {
        "authorization_servers": [
            {
                "issuer": base_url,
                "authorization_endpoint": f"{base_url}/authorize"
            }
        ]
    }

@app.get("/.well-known/oauth-authorization-server")
async def oauth_authorization_server(request: Request):
    """OAuth 2.1 authorization server metadata"""
    base_url = get_base_url(request)
    
    return {
        "issuer": base_url,
        "authorization_endpoint": f"{base_url}/authorize",
        "token_endpoint": f"{base_url}/token", 
        "registration_endpoint": f"{base_url}/register",
        "token_endpoint_auth_methods_supported": ["none"],
        "scopes_supported": ["inventory"],
        "response_types_supported": ["code"],
        "response_modes_supported": ["query"],
        "grant_types_supported": ["authorization_code"],
        "code_challenge_methods_supported": ["S256"]
    }

# OAuth Authorization and Token Endpoints
@app.get("/authorize")
async def authorize_endpoint(
    request: Request,
    client_id: str,
    redirect_uri: str,
    response_type: str = "code",
    state: Optional[str] = None,
    code_challenge: Optional[str] = None,
    code_challenge_method: str = "S256",
    scope: str = "inventory"
):
    """OAuth authorization endpoint - simplified for demo"""
    if response_type != "code":
        raise HTTPException(400, "Only 'code' response type supported")
    
    # For demo, auto-approve and generate code
    # In production, you'd show login UI and get user consent
    auth_code = secrets.token_urlsafe(32)
    
    auth_codes[auth_code] = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "code_challenge": code_challenge,
        "code_challenge_method": code_challenge_method,
        "scopes": ["inventory"],
        "user_id": "demo-user",  # In production, get from authenticated user
        "expires_at": datetime.now() + timedelta(minutes=10),
        "created_at": datetime.now()
    }
    
    # Build redirect URL
    redirect_url = f"{redirect_uri}?code={auth_code}"
    if state:
        redirect_url += f"&state={state}"
    
    return JSONResponse(
        status_code=302,
        headers={"Location": redirect_url},
        content={"message": "Redirecting to client"}
    )

@app.post("/token")
async def token_endpoint(
    grant_type: str = Form(),
    code: Optional[str] = Form(None),
    redirect_uri: Optional[str] = Form(None),
    client_id: Optional[str] = Form(None),
    code_verifier: Optional[str] = Form(None)
):
    """OAuth token endpoint with PKCE support"""
    if grant_type != "authorization_code":
        return JSONResponse(
            status_code=400,
            content={"error": "unsupported_grant_type"}
        )
    
    if not code:
        return JSONResponse(
            status_code=400,
            content={"error": "invalid_request", "error_description": "Missing code"}
        )
    
    # Look up authorization code
    auth_data = auth_codes.get(code)
    if not auth_data:
        return JSONResponse(
            status_code=400,
            content={"error": "invalid_grant"}
        )
    
    # Check expiration
    if datetime.now() > auth_data["expires_at"]:
        del auth_codes[code]
        return JSONResponse(
            status_code=400,
            content={"error": "invalid_grant", "error_description": "Code expired"}
        )
    
    # Validate PKCE if present
    if auth_data.get("code_challenge"):
        if not code_verifier:
            return JSONResponse(
                status_code=400,
                content={"error": "invalid_request", "error_description": "code_verifier required"}
            )
        
        # Verify code challenge
        calculated_challenge = base64.urlsafe_b64encode(
            hashlib.sha256(code_verifier.encode()).digest()
        ).decode().rstrip('=')
        
        if calculated_challenge != auth_data["code_challenge"]:
            return JSONResponse(
                status_code=400,
                content={"error": "invalid_grant", "error_description": "Invalid code_verifier"}
            )
    
    # Generate access token
    access_token = secrets.token_urlsafe(32)
    
    access_tokens[access_token] = {
        "client_id": auth_data["client_id"],
        "user_id": auth_data["user_id"],
        "scopes": auth_data["scopes"],
        "expires_at": datetime.now() + timedelta(hours=1),
        "created_at": datetime.now()
    }
    
    # Clean up authorization code
    del auth_codes[code]
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": 3600,
        "scope": " ".join(auth_data["scopes"])
    }

@app.post("/register")  
async def client_registration(registration: ClientRegistration):
    """Dynamic client registration endpoint"""
    client_id = str(uuid.uuid4())
    
    registered_clients[client_id] = {
        "client_id": client_id,
        "client_name": registration.client_name,
        "redirect_uris": registration.redirect_uris,
        "created_at": datetime.now().isoformat()
    }
    
    return JSONResponse(
        status_code=201,
        content={
            "client_id": client_id,
            "client_name": registration.client_name,
            "redirect_uris": registration.redirect_uris,
            "token_endpoint_auth_method": "none"
        }
    )

# MCP Tool Implementations
async def handle_search_tool(query: str, auth_info: dict):
    """Search tool with authentication"""
    try:
        logger.info(f"Search tool called by user {auth_info.get('user_id')} with query: {query}")
        
        if not query:
            return [TextContent(type="text", text=json.dumps({"results": []}))]
        
        async with db_pool.acquire() as conn:
            results = []
            
            # Search food items
            rows = await conn.fetch("""
                SELECT id, nome, quantita, unita_misura, categoria, ubicazione
                FROM alimenti 
                WHERE LOWER(nome) LIKE LOWER($1) 
                   OR LOWER(categoria::text) LIKE LOWER($1)
                   OR LOWER(ubicazione::text) LIKE LOWER($1)
                ORDER BY nome
                LIMIT 10
            """, f"%{query}%")
            
            for row in rows:
                results.append({
                    "id": f"alimento-{row['id']}",
                    "title": f"{row['nome']} ({row['quantita']} {row['unita_misura']})",
                    "category": row['categoria'],
                    "location": row['ubicazione']
                })
        
        return [TextContent(type="text", text=json.dumps({
            "results": results,
            "count": len(results),
            "query": query
        }))]
        
    except Exception as e:
        logger.error(f"Search tool error: {e}")
        return [TextContent(type="text", text=json.dumps({
            "results": [], 
            "error": str(e)
        }))]

async def handle_fetch_tool(item_id: str, auth_info: dict):
    """Fetch tool with authentication"""
    try:
        logger.info(f"Fetch tool called by user {auth_info.get('user_id')} for item: {item_id}")
        
        if not item_id.startswith("alimento-"):
            raise ValueError("Invalid ID format - must start with 'alimento-'")
        
        alimento_id = int(item_id.replace("alimento-", ""))
        
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM alimenti WHERE id = $1", alimento_id)
            
            if not row:
                raise ValueError(f"Item not found: {item_id}")
            
            # Format complete document
            document = {
                "id": item_id,
                "name": row['nome'],
                "quantity": f"{row['quantita']} {row['unita_misura']}",
                "category": row['categoria'],
                "location": row['ubicazione'],
                "expiry_date": str(row['data_scadenza']) if row['data_scadenza'] else None,
                "created": str(row['data_inserimento']),
                "modified": str(row['ultima_modifica'])
            }
            
            return [TextContent(type="text", text=json.dumps(document, indent=2))]
            
    except Exception as e:
        logger.error(f"Fetch tool error: {e}")
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]

# Complete MCP Server Implementation con tutti i tool richiesti
available_tools = [
    # === GESTIONE MAGAZZINO ===
    {
        "name": "aggiungere_alimento",
        "description": "Inserisce un nuovo alimento nel magazzino specificando tutti i campi richiesti",
        "inputSchema": {
            "type": "object",
            "properties": {
                "nome": {"type": "string", "description": "Nome del prodotto"},
                "quantita": {"type": "number", "description": "Quantità disponibile"},
                "unita_misura": {"type": "string", "enum": ["PEZZI", "KG", "LITRI", "GRAMMI"], "description": "Unità di misura"},
                "data_scadenza": {"type": "string", "format": "date", "description": "Data di scadenza (YYYY-MM-DD)"},
                "data_apertura": {"type": "string", "format": "date", "description": "Data di apertura (YYYY-MM-DD, opzionale)"},
                "categoria": {"type": "string", "enum": ["LATTICINI", "VERDURE", "FRUTTA", "CARNE", "PESCE", "CONSERVE", "BEVANDE", "ALTRO"], "description": "Categoria prodotto"},
                "ubicazione": {"type": "string", "enum": ["FRIGO", "FREEZER", "DISPENSA", "CANTINA"], "description": "Dove è conservato"},
                "prezzo_acquisto": {"type": "number", "description": "Prezzo di acquisto (opzionale)"},
                "fornitore": {"type": "string", "description": "Fornitore (opzionale)"},
                "lotto_acquisto": {"type": "string", "description": "Lotto di acquisto (opzionale)"}
            },
            "required": ["nome", "quantita", "unita_misura", "categoria", "ubicazione"]
        }
    },
    {
        "name": "consultare_giacenze",
        "description": "Visualizza le giacenze con filtri per categoria, ubicazione, scadenza",
        "inputSchema": {
            "type": "object",
            "properties": {
                "categoria": {"type": "string", "enum": ["LATTICINI", "VERDURE", "FRUTTA", "CARNE", "PESCE", "CONSERVE", "BEVANDE", "ALTRO"], "description": "Filtra per categoria (opzionale)"},
                "ubicazione": {"type": "string", "enum": ["FRIGO", "FREEZER", "DISPENSA", "CANTINA"], "description": "Filtra per ubicazione (opzionale)"},
                "in_scadenza_giorni": {"type": "integer", "description": "Mostra solo prodotti in scadenza entro X giorni (opzionale)"},
                "quantita_minima": {"type": "number", "description": "Mostra solo prodotti con quantità >= valore (opzionale)"},
                "limit": {"type": "integer", "default": 50, "description": "Numero massimo risultati"}
            }
        }
    },
    {
        "name": "scaricare_alimento",
        "description": "Registra il consumo di un alimento con controllo quantità disponibile",
        "inputSchema": {
            "type": "object",
            "properties": {
                "alimento_id": {"type": "integer", "description": "ID dell'alimento da scaricare"},
                "quantita_consumata": {"type": "number", "description": "Quantità da scaricare"},
                "motivo": {"type": "string", "enum": ["CONSUMATO", "SCADUTO", "BUTTATO"], "default": "CONSUMATO", "description": "Motivo del consumo"},
                "note": {"type": "string", "description": "Note aggiuntive (opzionale)"},
                "forza_scarico": {"type": "boolean", "default": false, "description": "Forza scarico anche se quantità > giacenza"}
            },
            "required": ["alimento_id", "quantita_consumata"]
        }
    },
    {
        "name": "scartare_alimento",
        "description": "Registra alimenti scaduti o da buttare con motivazione",
        "inputSchema": {
            "type": "object",
            "properties": {
                "alimento_id": {"type": "integer", "description": "ID dell'alimento da scartare"},
                "quantita_scartata": {"type": "number", "description": "Quantità da scartare"},
                "motivo": {"type": "string", "enum": ["SCADUTO", "BUTTATO"], "description": "Motivo dello scarto"},
                "note": {"type": "string", "description": "Dettagli sullo scarto"}
            },
            "required": ["alimento_id", "quantita_scartata", "motivo"]
        }
    },
    {
        "name": "aggiornare_alimento",
        "description": "Modifica dati di un alimento esistente",
        "inputSchema": {
            "type": "object",
            "properties": {
                "alimento_id": {"type": "integer", "description": "ID dell'alimento da modificare"},
                "nome": {"type": "string", "description": "Nuovo nome (opzionale)"},
                "quantita": {"type": "number", "description": "Nuova quantità (opzionale)"},
                "data_scadenza": {"type": "string", "format": "date", "description": "Nuova data scadenza (opzionale)"},
                "data_apertura": {"type": "string", "format": "date", "description": "Nuova data apertura (opzionale)"},
                "categoria": {"type": "string", "enum": ["LATTICINI", "VERDURE", "FRUTTA", "CARNE", "PESCE", "CONSERVE", "BEVANDE", "ALTRO"], "description": "Nuova categoria (opzionale)"},
                "ubicazione": {"type": "string", "enum": ["FRIGO", "FREEZER", "DISPENSA", "CANTINA"], "description": "Nuova ubicazione (opzionale)"},
                "prezzo_acquisto": {"type": "number", "description": "Nuovo prezzo (opzionale)"},
                "fornitore": {"type": "string", "description": "Nuovo fornitore (opzionale)"},
                "lotto_acquisto": {"type": "string", "description": "Nuovo lotto (opzionale)"}
            },
            "required": ["alimento_id"]
        }
    },
    {
        "name": "notifiche_scadenza",
        "description": "Restituisce alimenti in scadenza entro X giorni",
        "inputSchema": {
            "type": "object",
            "properties": {
                "giorni_limite": {"type": "integer", "default": 3, "description": "Giorni entro cui cercare scadenze"},
                "categoria": {"type": "string", "enum": ["LATTICINI", "VERDURE", "FRUTTA", "CARNE", "PESCE", "CONSERVE", "BEVANDE", "ALTRO"], "description": "Filtra per categoria (opzionale)"},
                "ubicazione": {"type": "string", "enum": ["FRIGO", "FREEZER", "DISPENSA", "CANTINA"], "description": "Filtra per ubicazione (opzionale)"}
            }
        }
    },
    {
        "name": "statistiche_consumi",
        "description": "Calcola consumi per periodo con raggruppamento per categoria o motivo",
        "inputSchema": {
            "type": "object",
            "properties": {
                "data_inizio": {"type": "string", "format": "date", "description": "Data inizio periodo (default: 30 giorni fa)"},
                "data_fine": {"type": "string", "format": "date", "description": "Data fine periodo (default: oggi)"},
                "raggruppa_per": {"type": "string", "enum": ["categoria", "motivo", "totale"], "default": "categoria", "description": "Come raggruppare i dati"}
            }
        }
    },
    
    # === GESTIONE TASK ===
    {
        "name": "inserire_task",
        "description": "Crea nuovo task con gestione ricorrenza",
        "inputSchema": {
            "type": "object",
            "properties": {
                "titolo": {"type": "string", "description": "Titolo del task"},
                "descrizione": {"type": "string", "description": "Descrizione dettagliata (opzionale)"},
                "priorita": {"type": "string", "enum": ["ALTA", "MEDIA", "BASSA"], "default": "MEDIA", "description": "Priorità del task"},
                "data_scadenza": {"type": "string", "format": "date", "description": "Scadenza del task (opzionale)"},
                "assegnatario": {"type": "string", "description": "A chi è assegnato (opzionale)"},
                "task_ricorrente": {"type": "boolean", "default": false, "description": "Se il task è ricorrente"},
                "frequenza_ricorrenza": {"type": "string", "enum": ["GIORNALIERA", "SETTIMANALE", "MENSILE"], "description": "Frequenza ricorrenza (solo se ricorrente)"}
            },
            "required": ["titolo"]
        }
    },
    {
        "name": "aggiornare_task",
        "description": "Modifica task esistente con tracciamento modifiche",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "integer", "description": "ID del task da modificare"},
                "titolo": {"type": "string", "description": "Nuovo titolo (opzionale)"},
                "descrizione": {"type": "string", "description": "Nuova descrizione (opzionale)"},
                "priorita": {"type": "string", "enum": ["ALTA", "MEDIA", "BASSA"], "description": "Nuova priorità (opzionale)"},
                "stato": {"type": "string", "enum": ["DA_FARE", "IN_CORSO", "COMPLETATO", "ANNULLATO"], "description": "Nuovo stato (opzionale)"},
                "data_scadenza": {"type": "string", "format": "date", "description": "Nuova scadenza (opzionale)"},
                "assegnatario": {"type": "string", "description": "Nuovo assegnatario (opzionale)"}
            },
            "required": ["task_id"]
        }
    },
    {
        "name": "completare_task",
        "description": "Marca task come completato e gestisce ricorrenza automatica",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "integer", "description": "ID del task da completare"},
                "note_completamento": {"type": "string", "description": "Note sul completamento (opzionale)"}
            },
            "required": ["task_id"]
        }
    },
    {
        "name": "elencare_task",
        "description": "Lista task con filtri per stato, priorità, assegnatario, scadenza",
        "inputSchema": {
            "type": "object",
            "properties": {
                "stato": {"type": "string", "enum": ["DA_FARE", "IN_CORSO", "COMPLETATO", "ANNULLATO"], "description": "Filtra per stato (opzionale)"},
                "priorita": {"type": "string", "enum": ["ALTA", "MEDIA", "BASSA"], "description": "Filtra per priorità (opzionale)"},
                "assegnatario": {"type": "string", "description": "Filtra per assegnatario (opzionale)"},
                "scadenza_entro_giorni": {"type": "integer", "description": "Solo task in scadenza entro X giorni (opzionale)"},
                "ricorrenti": {"type": "boolean", "description": "Solo task ricorrenti (opzionale)"},
                "limit": {"type": "integer", "default": 50, "description": "Numero massimo risultati"}
            }
        }
    },
    {
        "name": "cancellare_task",
        "description": "Elimina task (soft delete cambiando stato ad ANNULLATO)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "integer", "description": "ID del task da cancellare"},
                "motivo_cancellazione": {"type": "string", "description": "Motivo della cancellazione"}
            },
            "required": ["task_id"]
        }
    },
    {
        "name": "statistiche_task",
        "description": "Report su completamento task per periodo",
        "inputSchema": {
            "type": "object",
            "properties": {
                "data_inizio": {"type": "string", "format": "date", "description": "Data inizio periodo (default: 30 giorni fa)"},
                "data_fine": {"type": "string", "format": "date", "description": "Data fine periodo (default: oggi)"},
                "raggruppa_per": {"type": "string", "enum": ["stato", "priorita", "assegnatario"], "default": "stato", "description": "Come raggruppare i dati"}
            }
        }
    }
]

async def call_mcp_tool(name: str, arguments: dict, auth_info: dict) -> List[dict]:
    """Handle tool calls with authentication context"""
    try:
        # GESTIONE MAGAZZINO
        if name == "aggiungere_alimento":
            result_content = await aggiungere_alimento_impl(arguments, auth_info, db_pool)
        elif name == "consultare_giacenze":
            result_content = await consultare_giacenze_impl(arguments, auth_info, db_pool)
        elif name == "scaricare_alimento":
            result_content = await scaricare_alimento_impl(arguments, auth_info, db_pool)
        elif name == "notifiche_scadenza":
            result_content = await notifiche_scadenza_impl(arguments, auth_info, db_pool)
        elif name == "scartare_alimento":
            result_content = await scaricare_alimento_impl({**arguments, "motivo": "SCADUTO"}, auth_info, db_pool)
        elif name == "aggiornare_alimento":
            result_content = await aggiornare_alimento_impl(arguments, auth_info, db_pool)
        elif name == "statistiche_consumi":
            result_content = await statistiche_consumi_impl(arguments, auth_info, db_pool)
            
        # GESTIONE TASK
        elif name == "inserire_task":
            result_content = await inserire_task_impl(arguments, auth_info, db_pool)
        elif name == "elencare_task":
            result_content = await elencare_task_impl(arguments, auth_info, db_pool)
        elif name == "completare_task":
            result_content = await completare_task_impl(arguments, auth_info, db_pool)
        elif name == "aggiornare_task":
            result_content = await aggiornare_task_impl(arguments, auth_info, db_pool)
        elif name == "cancellare_task":
            result_content = await cancellare_task_impl(arguments, auth_info, db_pool)
        elif name == "statistiche_task":
            result_content = await statistiche_task_impl(arguments, auth_info, db_pool)
            
        # LEGACY TOOLS (backward compatibility)
        elif name == "search":
            result_content = await handle_search_tool(arguments.get("query", ""), auth_info)
        elif name == "fetch":
            result_content = await handle_fetch_tool(arguments.get("id", ""), auth_info)
        else:
            raise ValueError(f"Unknown tool: {name}")
        
        return [{"type": c.type, "text": c.text} for c in result_content]
        
    except Exception as e:
        logger.error(f"Tool execution error for {name}: {e}")
        error_content = [TextContent(type="text", text=json.dumps({
            "success": False,
            "error": f"Tool execution failed: {str(e)}",
            "tool": name
        }))]
        return [{"type": c.type, "text": c.text} for c in error_content]

# Main MCP endpoint with authentication  
@app.post("/mcp")
async def mcp_endpoint(request: Request):
    """Main MCP endpoint with OAuth authentication"""
    try:
        body = await request.json()
        rpc_id = body.get("id")
        
        # Authenticate request (skip if auth disabled for debug)
        if DISABLE_AUTH:
            auth_info = {
                "token": "debug-token",
                "client_id": "debug-client", 
                "scopes": ["inventory"],
                "user_id": "debug-user"
            }
            logger.info("🚧 Authentication disabled for debug/testing")
        else:
            auth_result = await authenticate_token(request, rpc_id)
            if not auth_result["success"]:
                return auth_result["response"]
            auth_info = auth_result["auth_info"]
        
        # Handle session management - more flexible
        session_id = request.headers.get("mcp-session-id")
        method = body.get("method")
        
        if method == "initialize":
            # Always create new session for initialize
            session_id = str(uuid.uuid4())
            mcp_sessions[session_id] = {
                "created_at": datetime.now(),
                "auth_info": auth_info
            }
            logger.info(f"Created new session: {session_id}")
        elif not session_id:
            # Create session for requests without session_id
            session_id = str(uuid.uuid4())
            mcp_sessions[session_id] = {
                "created_at": datetime.now(),
                "auth_info": auth_info
            }
            logger.info(f"Created session for non-initialize request: {session_id}")
        elif session_id not in mcp_sessions:
            # Recreation session if not found
            mcp_sessions[session_id] = {
                "created_at": datetime.now(),
                "auth_info": auth_info
            }
            logger.info(f"Recreated missing session: {session_id}")
        
        params = body.get("params", {})
        
        # Handle MCP methods
        if method == "initialize":
            response_data = {
                "jsonrpc": "2.0", 
                "id": rpc_id,
                "result": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {
                        "tools": {"listChanged": False}
                    },
                    "serverInfo": {
                        "name": "Remote MCP Inventory Server",
                        "version": "3.0.0"
                    },
                    "instructions": "Use this server to search and retrieve food inventory items. Use 'search' to find items and 'fetch' to get detailed information."
                }
            }
            
        elif method == "tools/list":
            response_data = {
                "jsonrpc": "2.0",
                "id": rpc_id, 
                "result": {"tools": available_tools}
            }
            
        elif method == "tools/call":
            tool_name = params.get("name")
            arguments = params.get("arguments", {})
            
            try:
                result_content = await call_mcp_tool(tool_name, arguments, auth_info)
                response_data = {
                    "jsonrpc": "2.0",
                    "id": rpc_id,
                    "result": {
                        "content": result_content
                    }
                }
            except Exception as tool_error:
                logger.error(f"Tool call error: {tool_error}")
                response_data = {
                    "jsonrpc": "2.0",
                    "id": rpc_id,
                    "error": {
                        "code": -32603,
                        "message": f"Tool execution failed: {str(tool_error)}"
                    }
                }
                
        else:
            response_data = {
                "jsonrpc": "2.0",
                "id": rpc_id,
                "error": {"code": -32601, "message": f"Unknown method: {method}"}
            }
        
        # Return response with session header
        response = JSONResponse(content=response_data)
        response.headers["Mcp-Session-Id"] = session_id
        return response
        
    except Exception as e:
        logger.error(f"MCP endpoint error: {e}")
        return JSONResponse(
            status_code=500,
            content={
                "jsonrpc": "2.0",
                "error": {"code": -32603, "message": "Internal server error"},
                "id": body.get("id") if 'body' in locals() else None
            }
        )

# Session cleanup endpoint
@app.delete("/mcp")
async def cleanup_mcp_session(
    mcp_session_id: Optional[str] = Header(None)
):
    """Clean up MCP session"""
    if mcp_session_id and mcp_session_id in mcp_sessions:
        del mcp_sessions[mcp_session_id]
        logger.info(f"Cleaned up session: {mcp_session_id}")
    
    return Response(status_code=204)

# Debug endpoint per test senza auth
@app.post("/mcp-debug") 
async def mcp_debug_endpoint(request: Request):
    """Debug MCP endpoint senza autenticazione"""
    logger.info("🚧 Debug endpoint called - no auth required")
    
    # Forza auth_info di debug
    global DISABLE_AUTH
    old_disable_auth = DISABLE_AUTH
    DISABLE_AUTH = True
    
    try:
        # Chiama l'endpoint normale
        response = await mcp_endpoint(request)
        return response
    finally:
        # Ripristina il flag originale
        DISABLE_AUTH = old_disable_auth

# Health check
@app.get("/health")
async def health_check():
    """Health check endpoint"""
    try:
        async with db_pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        
        return {
            "status": "healthy", 
            "database": "connected",
            "mcp_server": "initialized",
            "sessions": len(mcp_sessions),
            "tokens": len(access_tokens),
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }


# Main execution
if __name__ == "__main__":
    import uvicorn
    
    # Update BASE_URL for production
    if os.getenv("RENDER"):
        BASE_URL = "https://sql-mcp-server.onrender.com"
    
    uvicorn.run(
        "mcp_server_openai:app",
        host="0.0.0.0",
        port=PORT,
        reload=False,
        log_level="info"
    )
