#!/usr/bin/env python3
"""
OpenAI-compatible MCP Server for Inventory Management
Simplified version without authentication for OpenAI compatibility
"""

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Any

import asyncpg
from fastapi import FastAPI, Request, Response, HTTPException, Header
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configuration
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql:///inventario_db")
PORT = int(os.getenv("PORT", "10000"))
BASE_URL = os.getenv("BASE_URL", f"http://localhost:{PORT}")

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Database pool
db_pool = None

# In-memory sessions store
mcp_sessions = {}  # session_id -> {created_at, transport_info}

# FastAPI app setup
app = FastAPI(
    title="MCP Inventory Server",
    description="OpenAI-compatible MCP server for inventory management (no auth)",
    version="2.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Mcp-Session-Id"]
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

# MCP Protocol Implementation (No Authentication)
@app.post("/mcp")
async def mcp_endpoint(
    request: Request,
    mcp_session_id: Optional[str] = Header(None)
):
    """Main MCP endpoint following JSON-RPC 2.0 (no authentication)"""
    
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
                        "name": "MCP Inventory Server (No Auth)",
                        "version": "2.0.0"
                    }
                }
            }
            
            response = JSONResponse(content=response_content)
            response.headers["Mcp-Session-Id"] = session_id
            return response
        
        # For other methods, create session if needed
        if not mcp_session_id:
            # Create a default session if none provided
            session_id = str(uuid.uuid4())
            mcp_sessions[session_id] = {
                "created_at": datetime.now(),
                "transport": "streamable_http"
            }
            mcp_session_id = session_id
        
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
    mcp_session_id: Optional[str] = Header(None)
):
    """Clean up MCP session (no authentication required)"""
    if mcp_session_id and mcp_session_id in mcp_sessions:
        del mcp_sessions[mcp_session_id]
        logger.info(f"Cleaned up session: {mcp_session_id}")
    
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
