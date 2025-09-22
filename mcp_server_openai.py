#!/usr/bin/env python3
"""
OpenAI-compatible MCP Server for Inventory Management
Implements the Model Context Protocol with proper OAuth 2.1 authentication
"""

import asyncio
import json
import logging
import os
import secrets
import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from urllib.parse import parse_qs, urlencode, urlparse

import asyncpg
import httpx
from fastapi import FastAPI, Request, Response, HTTPException, Depends, Header
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
import orjson

# Load environment variables
load_dotenv()

# Configuration
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql:///inventario_db")
API_KEY = os.getenv("API_KEY", "GenuinMiglioreAgenteDelMondo")
PORT = int(os.getenv("PORT", "10000"))
BASE_URL = os.getenv("BASE_URL", f"http://localhost:{PORT}")

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Database pool
db_pool = None

# In-memory stores for OAuth and sessions
oauth_codes = {}  # authorization_code -> {user_info, expires, pkce, etc}
access_tokens = {}  # access_token -> {user_info, expires, scopes}
mcp_sessions = {}  # session_id -> {transport_info, created_at}

# OAuth 2.1 Models
class AuthorizeRequest(BaseModel):
    response_type: str = "code"
    client_id: str
    redirect_uri: str
    scope: Optional[str] = "inventory"
    state: Optional[str] = None
    code_challenge: Optional[str] = None
    code_challenge_method: Optional[str] = "S256"

class TokenRequest(BaseModel):
    grant_type: str = "authorization_code"
    client_id: str
    code: str
    redirect_uri: str
    code_verifier: Optional[str] = None

# FastAPI app setup
app = FastAPI(
    title="MCP Inventory Server",
    description="OpenAI-compatible MCP server for inventory management",
    version="2.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Mcp-Session-Id", "WWW-Authenticate"]
)

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

# OAuth 2.1 Discovery Endpoints
@app.get("/.well-known/oauth-protected-resource")
async def oauth_protected_resource(request: Request):
    """OAuth 2.1 Protected Resource Discovery"""
    base_url = str(request.base_url).rstrip('/')
    
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
    """OAuth 2.1 Authorization Server Metadata"""
    base_url = str(request.base_url).rstrip('/')
    
    return {
        "issuer": base_url,
        "authorization_endpoint": f"{base_url}/authorize",
        "token_endpoint": f"{base_url}/token",
        "registration_endpoint": f"{base_url}/register",
        "token_endpoint_auth_methods_supported": ["none"],
        "scopes_supported": ["inventory", "search", "fetch"],
        "response_types_supported": ["code"],
        "response_modes_supported": ["query"],
        "grant_types_supported": ["authorization_code"],
        "code_challenge_methods_supported": ["S256", "plain"]
    }

# OAuth 2.1 Authorization Flow
@app.get("/authorize")
async def authorize_endpoint(request: Request):
    """OAuth 2.1 Authorization Endpoint - Shows login form"""
    
    # Parse query parameters
    params = dict(request.query_params)
    
    # Validate required parameters
    if not params.get("client_id") or not params.get("redirect_uri"):
        raise HTTPException(status_code=400, detail="Missing required parameters")
    
    # For demo purposes, auto-approve with a simple form
    # In production, this would show a proper login UI
    
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>MCP Inventory Server - Authorization</title>
        <style>
            body {{ font-family: Arial, sans-serif; max-width: 600px; margin: 50px auto; padding: 20px; }}
            .form-group {{ margin: 15px 0; }}
            button {{ background: #007cba; color: white; padding: 10px 20px; border: none; border-radius: 4px; cursor: pointer; }}
            button:hover {{ background: #005a87; }}
            .info {{ background: #f0f8ff; padding: 15px; border-radius: 4px; margin: 20px 0; }}
        </style>
    </head>
    <body>
        <h1>🔐 MCP Inventory Server</h1>
        <div class="info">
            <p><strong>Client:</strong> {params.get('client_id', 'Unknown')}</p>
            <p><strong>Scopes:</strong> {params.get('scope', 'inventory')}</p>
            <p><strong>State:</strong> {params.get('state', 'None')}</p>
        </div>
        
        <h2>Authorize Access</h2>
        <p>This will grant the AI application access to your inventory data.</p>
        
        <form method="POST" action="/callback">
            <input type="hidden" name="client_id" value="{params.get('client_id', '')}">
            <input type="hidden" name="redirect_uri" value="{params.get('redirect_uri', '')}">
            <input type="hidden" name="scope" value="{params.get('scope', 'inventory')}">
            <input type="hidden" name="state" value="{params.get('state', '')}">
            <input type="hidden" name="code_challenge" value="{params.get('code_challenge', '')}">
            <input type="hidden" name="code_challenge_method" value="{params.get('code_challenge_method', 'S256')}">
            
            <div class="form-group">
                <button type="submit" name="action" value="approve">✅ Approve Access</button>
                <button type="submit" name="action" value="deny" style="background: #dc3545; margin-left: 10px;">❌ Deny</button>
            </div>
        </form>
        
        <p><small>Demo server - in production this would require proper authentication</small></p>
    </body>
    </html>
    """
    
    return HTMLResponse(content=html_content)

@app.post("/callback")
async def oauth_callback(request: Request):
    """Handle authorization response and redirect with code"""
    
    form_data = await request.form()
    action = form_data.get("action")
    
    if action != "approve":
        # User denied access
        redirect_uri = form_data.get("redirect_uri")
        error_params = {
            "error": "access_denied",
            "error_description": "User denied access"
        }
        if form_data.get("state"):
            error_params["state"] = form_data.get("state")
            
        redirect_url = f"{redirect_uri}?{urlencode(error_params)}"
        return Response(
            content=f'<script>window.location.href = "{redirect_url}";</script>',
            media_type="text/html"
        )
    
    # Generate authorization code
    auth_code = secrets.token_urlsafe(32)
    
    # Store authorization data
    oauth_codes[auth_code] = {
        "client_id": form_data.get("client_id"),
        "redirect_uri": form_data.get("redirect_uri"),
        "scope": form_data.get("scope", "inventory"),
        "expires_at": datetime.now() + timedelta(minutes=10),
        "code_challenge": form_data.get("code_challenge"),
        "code_challenge_method": form_data.get("code_challenge_method"),
        "user_id": "demo_user"  # In production, get from authenticated session
    }
    
    # Redirect with authorization code
    redirect_params = {
        "code": auth_code
    }
    if form_data.get("state"):
        redirect_params["state"] = form_data.get("state")
    
    redirect_url = f"{form_data.get('redirect_uri')}?{urlencode(redirect_params)}"
    
    return Response(
        content=f'<script>window.location.href = "{redirect_url}";</script>',
        media_type="text/html"
    )

@app.post("/token")
async def token_endpoint(request: Request):
    """OAuth 2.1 Token Exchange Endpoint"""
    
    try:
        form_data = await request.form()
        
        grant_type = form_data.get("grant_type")
        if grant_type != "authorization_code":
            raise HTTPException(status_code=400, detail="Unsupported grant type")
        
        auth_code = form_data.get("code")
        if not auth_code or auth_code not in oauth_codes:
            raise HTTPException(status_code=400, detail="Invalid authorization code")
        
        code_data = oauth_codes[auth_code]
        
        # Check expiration
        if datetime.now() > code_data["expires_at"]:
            del oauth_codes[auth_code]
            raise HTTPException(status_code=400, detail="Authorization code expired")
        
        # Validate PKCE if provided
        if code_data.get("code_challenge"):
            code_verifier = form_data.get("code_verifier")
            if not code_verifier:
                raise HTTPException(status_code=400, detail="code_verifier required for PKCE")
            
            # Verify PKCE challenge
            import hashlib
            import base64
            
            if code_data.get("code_challenge_method") == "S256":
                calculated = base64.urlsafe_b64encode(
                    hashlib.sha256(code_verifier.encode()).digest()
                ).decode().rstrip('=')
            else:
                calculated = code_verifier
            
            if calculated != code_data["code_challenge"]:
                raise HTTPException(status_code=400, detail="Invalid code_verifier")
        
        # Generate access token
        access_token = secrets.token_urlsafe(32)
        
        # Store access token
        access_tokens[access_token] = {
            "user_id": code_data["user_id"],
            "client_id": code_data["client_id"],
            "scope": code_data["scope"],
            "expires_at": datetime.now() + timedelta(days=30),
            "created_at": datetime.now()
        }
        
        # Clean up authorization code
        del oauth_codes[auth_code]
        
        return {
            "access_token": access_token,
            "token_type": "Bearer",
            "expires_in": 2592000,  # 30 days
            "scope": code_data["scope"]
        }
        
    except Exception as e:
        logger.error(f"Token endpoint error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.post("/register")
async def client_registration(request: Request):
    """Dynamic client registration (optional but helpful)"""
    
    try:
        data = await request.json()
        client_id = str(uuid.uuid4())
        
        return {
            "client_id": client_id,
            "token_endpoint_auth_method": "none",
            "redirect_uris": data.get("redirect_uris", [])
        }
    except Exception as e:
        logger.error(f"Client registration error: {e}")
        raise HTTPException(status_code=500, detail="Registration failed")

# Authentication helper
async def verify_access_token(authorization: Optional[str] = Header(None)):
    """Verify Bearer token and return auth info"""
    
    if not authorization:
        raise HTTPException(
            status_code=401,
            detail="Missing authorization header",
            headers={"WWW-Authenticate": f'Bearer realm="MCP Server", resource_metadata_uri="{BASE_URL}/.well-known/oauth-protected-resource"'}
        )
    
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header format")
    
    token = authorization[7:]  # Remove "Bearer "
    
    if token not in access_tokens:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    
    token_data = access_tokens[token]
    
    # Check expiration
    if datetime.now() > token_data["expires_at"]:
        del access_tokens[token]
        raise HTTPException(status_code=401, detail="Token expired")
    
    return {
        "token": token,
        "user_id": token_data["user_id"],
        "client_id": token_data["client_id"],
        "scopes": token_data["scope"].split()
    }

# MCP Protocol Implementation
@app.post("/mcp")
async def mcp_endpoint(
    request: Request,
    auth_info: dict = Depends(verify_access_token),
    mcp_session_id: Optional[str] = Header(None)
):
    """Main MCP endpoint following JSON-RPC 2.0"""
    
    try:
        body = await request.json()
        
        # Validate JSON-RPC 2.0
        if body.get("jsonrpc") != "2.0":
            return JSONResponse(
                status_code=400,
                content={
                    "jsonrpc": "2.0",
                    "error": {"code": -32600, "message": "Invalid JSON-RPC version"},
                    "id": body.get("id")
                }
            )
        
        method = body.get("method")
        request_id = body.get("id")
        params = body.get("params", {})
        
        # Handle session management
        if method == "initialize":
            session_id = str(uuid.uuid4())
            mcp_sessions[session_id] = {
                "auth_info": auth_info,
                "created_at": datetime.now(),
                "transport": "streamable_http"
            }
            
            # Set session header in response
            response_content = {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {
                        "tools": {"listChanged": False}
                    },
                    "serverInfo": {
                        "name": "MCP Inventory Server",
                        "version": "2.0.0"
                    }
                }
            }
            
            response = JSONResponse(content=response_content)
            response.headers["Mcp-Session-Id"] = session_id
            return response
        
        # For other methods, validate session
        if not mcp_session_id or mcp_session_id not in mcp_sessions:
            return JSONResponse(
                status_code=400,
                content={
                    "jsonrpc": "2.0",  
                    "error": {"code": -32001, "message": "Invalid or missing session"},
                    "id": request_id
                }
            )
        
        # Handle MCP methods
        if method == "tools/list":
            tools = [
                {
                    "name": "search",
                    "description": "Search for food items and tasks in the inventory database",
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
                    "description": "Retrieve complete details of a specific food item or task by ID",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "id": {
                                "type": "string",
                                "description": "Unique identifier (format: 'alimento-{id}' or 'task-{id}')"
                            }
                        },
                        "required": ["id"]
                    }
                }
            ]
            
            response_content = {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {"tools": tools}
            }
            
        elif method == "tools/call":
            tool_name = params.get("name")
            arguments = params.get("arguments", {})
            
            if tool_name == "search":
                result = await handle_search_tool(arguments.get("query", ""))
            elif tool_name == "fetch":
                result = await handle_fetch_tool(arguments.get("id", ""))
            else:
                return JSONResponse(
                    content={
                        "jsonrpc": "2.0",
                        "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"},
                        "id": request_id
                    }
                )
            
            response_content = {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": result
            }
            
        else:
            response_content = {
                "jsonrpc": "2.0",
                "error": {"code": -32601, "message": f"Unknown method: {method}"},
                "id": request_id
            }
        
        # Return response with session header
        response = JSONResponse(content=response_content)
        if mcp_session_id:
            response.headers["Mcp-Session-Id"] = mcp_session_id
        return response
        
    except Exception as e:
        logger.error(f"MCP endpoint error: {e}")
        return JSONResponse(
            status_code=500,
            content={
                "jsonrpc": "2.0",
                "error": {"code": -32603, "message": "Internal error"},
                "id": body.get("id") if 'body' in locals() else None
            }
        )

# MCP Tool Implementations
async def handle_search_tool(query: str):
    """OpenAI-compatible search tool"""
    try:
        if not query:
            return {"content": [{"type": "text", "text": json.dumps({"results": []})}]}
        
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
                    "url": f"{BASE_URL}/api/alimenti/{row['id']}"
                })
        
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps({"results": results})
                }
            ]
        }
        
    except Exception as e:
        logger.error(f"Search tool error: {e}")
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps({"results": [], "error": str(e)})
                }
            ]
        }

async def handle_fetch_tool(item_id: str):
    """OpenAI-compatible fetch tool"""
    try:
        if not item_id.startswith("alimento-"):
            raise ValueError("Invalid ID format")
        
        alimento_id = int(item_id.replace("alimento-", ""))
        
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM alimenti WHERE id = $1", alimento_id)
            
            if not row:
                raise ValueError(f"Item not found: {item_id}")
            
            # Format complete document
            document = {
                "id": item_id,
                "title": f"Alimento: {row['nome']}",
                "text": f"""
ALIMENTO: {row['nome']}

Dettagli:
- Quantità: {row['quantita']} {row['unita_misura']}
- Categoria: {row['categoria']}
- Ubicazione: {row['ubicazione']}
- Data scadenza: {row['data_scadenza'] or 'Non specificata'}
- Inserito il: {row['data_inserimento']}
- Modificato il: {row['ultima_modifica']}
""",
                "url": f"{BASE_URL}/api/alimenti/{alimento_id}",
                "metadata": {
                    "type": "alimento",
                    "categoria": row['categoria'],
                    "ubicazione": row['ubicazione']
                }
            }
            
            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(document)
                    }
                ]
            }
            
    except Exception as e:
        logger.error(f"Fetch tool error: {e}")
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps({"error": str(e)})
                }
            ]
        }

# Session cleanup endpoint
@app.delete("/mcp")
async def cleanup_mcp_session(
    mcp_session_id: Optional[str] = Header(None),
    auth_info: dict = Depends(verify_access_token)
):
    """Clean up MCP session"""
    if mcp_session_id and mcp_session_id in mcp_sessions:
        del mcp_sessions[mcp_session_id]
    
    return Response(status_code=204)

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
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }

# Startup event
@app.on_event("startup")
async def startup_event():
    """Initialize database on startup"""
    await setup_database()
    logger.info(f"🚀 MCP Server started on port {PORT}")
    logger.info(f"🔗 OAuth Discovery: {BASE_URL}/.well-known/oauth-protected-resource")

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
