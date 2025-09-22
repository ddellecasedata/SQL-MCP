#!/usr/bin/env python3
"""
MCP Server per Inventario Alimentare
Server MCP per Claude Desktop che gestisce un inventario di alimenti
"""

import asyncio
import logging
import os
from typing import Any, Dict, List
from datetime import datetime

import asyncpg
from mcp.server.fastmcp import FastMCP
from dotenv import load_dotenv

# Carica variabili d'ambiente
load_dotenv()

# Configurazione
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql:///inventario_db")

# Setup logging per stderr (non stdout per MCP STDIO)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()]  # Va su stderr di default
)
logger = logging.getLogger(__name__)

# Inizializza FastMCP server
mcp = FastMCP("inventario-alimentare")

# Pool connessioni database
db_pool = None

async def setup_database():
    """Setup database connection pool e schema"""
    global db_pool
    try:
        db_pool = await asyncpg.create_pool(
            DATABASE_URL,
            min_size=1,
            max_size=5,
            command_timeout=30
        )
        logger.info("Pool database creato con successo")
        
        # Verifica schema
        async with db_pool.acquire() as conn:
            exists = await conn.fetchval(
                "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'alimenti')"
            )
            
            if not exists:
                logger.info("Creazione schema database...")
                schema_path = os.path.join(os.path.dirname(__file__), 'database', 'schema.sql')
                if os.path.exists(schema_path):
                    with open(schema_path, 'r', encoding='utf-8') as f:
                        schema_sql = f.read()
                    await conn.execute(schema_sql)
                    logger.info("✅ Schema database creato")
                else:
                    logger.warning("File schema.sql non trovato")
            else:
                logger.info("✅ Schema database esistente")
                
    except Exception as e:
        logger.error(f"Errore setup database: {e}")
        raise

@mcp.tool()
async def cerca_alimenti(query: str) -> str:
    """Cerca alimenti nell'inventario per nome, categoria o ubicazione.

    Args:
        query: Termine di ricerca per nome, categoria o ubicazione degli alimenti
    """
    if not db_pool:
        return "Errore: Database non disponibile"
    
    try:
        async with db_pool.acquire() as conn:
            # Cerca negli alimenti
            rows = await conn.fetch("""
                SELECT id, nome, quantita, unita_misura, categoria, ubicazione, 
                       data_scadenza, data_inserimento
                FROM alimenti 
                WHERE LOWER(nome) LIKE LOWER($1) 
                   OR LOWER(categoria::text) LIKE LOWER($1)
                   OR LOWER(ubicazione::text) LIKE LOWER($1)
                ORDER BY data_inserimento DESC
                LIMIT 15
            """, f"%{query}%")
            
            if not rows:
                return f"Nessun alimento trovato per '{query}'"
            
            # Formatta risultati
            risultati = []
            for row in rows:
                scadenza = row['data_scadenza'].strftime('%d/%m/%Y') if row['data_scadenza'] else 'Non specificata'
                risultati.append(f"""
🍎 {row['nome']} (ID: {row['id']})
   Quantità: {row['quantita']} {row['unita_misura']}
   Categoria: {row['categoria']}
   Ubicazione: {row['ubicazione']}
   Scadenza: {scadenza}
""".strip())
            
            intestazione = f"🔍 Trovati {len(rows)} alimenti per '{query}':\n\n"
            return intestazione + "\n\n".join(risultati)
            
    except Exception as e:
        logger.error(f"Errore ricerca alimenti: {e}")
        return f"Errore nella ricerca: {str(e)}"

@mcp.tool()
async def dettagli_alimento(id_alimento: int) -> str:
    """Ottieni dettagli completi di un alimento specifico.

    Args:
        id_alimento: ID numerico dell'alimento da visualizzare
    """
    if not db_pool:
        return "Errore: Database non disponibile"
    
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT * FROM alimenti WHERE id = $1
            """, id_alimento)
            
            if not row:
                return f"❌ Alimento con ID {id_alimento} non trovato"
            
            # Formatta dettagli completi
            dettagli = f"""
📦 DETTAGLI ALIMENTO

🏷️  Nome: {row['nome']}
🔢  ID: {row['id']}
📊  Quantità: {row['quantita']} {row['unita_misura']}
🏪  Categoria: {row['categoria']}
📍  Ubicazione: {row['ubicazione']}

📅  Date:
   • Scadenza: {row['data_scadenza'].strftime('%d/%m/%Y') if row['data_scadenza'] else 'Non specificata'}
   • Apertura: {row['data_apertura'].strftime('%d/%m/%Y') if row['data_apertura'] else 'Non aperto'}
   • Inserimento: {row['data_inserimento'].strftime('%d/%m/%Y %H:%M') if row['data_inserimento'] else 'N/A'}
   • Ultima modifica: {row['ultima_modifica'].strftime('%d/%m/%Y %H:%M') if row['ultima_modifica'] else 'N/A'}

💰  Informazioni acquisto:
   • Prezzo: €{row['prezzo_acquisto'] if row['prezzo_acquisto'] else 'N/A'}
   • Fornitore: {row['fornitore'] if row['fornitore'] else 'Non specificato'}
   • Lotto: {row['numero_lotto'] if row['numero_lotto'] else 'N/A'}

👤  Modificato da: {row['modificato_da'] if row['modificato_da'] else 'Sistema'}

📝  Note: {row['note'] if row['note'] else 'Nessuna nota'}
""".strip()
            
            return dettagli
            
    except Exception as e:
        logger.error(f"Errore dettagli alimento: {e}")
        return f"Errore nel recupero dettagli: {str(e)}"

@mcp.tool()
async def statistiche_inventario() -> str:
    """Ottieni statistiche generali dell'inventario alimentare."""
    if not db_pool:
        return "Errore: Database non disponibile"
    
    try:
        async with db_pool.acquire() as conn:
            # Statistiche generali
            stats = await conn.fetchrow("""
                SELECT 
                    COUNT(*) as totale_alimenti,
                    COUNT(DISTINCT categoria) as categorie,
                    COUNT(DISTINCT ubicazione) as ubicazioni,
                    COUNT(CASE WHEN data_scadenza <= CURRENT_DATE + INTERVAL '7 days' THEN 1 END) as scadono_presto,
                    COUNT(CASE WHEN data_scadenza <= CURRENT_DATE THEN 1 END) as scaduti
                FROM alimenti
            """)
            
            # Top categorie
            categorie = await conn.fetch("""
                SELECT categoria, COUNT(*) as quantita
                FROM alimenti
                GROUP BY categoria
                ORDER BY quantita DESC
                LIMIT 5
            """)
            
            # Top ubicazioni
            ubicazioni = await conn.fetch("""
                SELECT ubicazione, COUNT(*) as quantita
                FROM alimenti
                GROUP BY ubicazione
                ORDER BY quantita DESC
                LIMIT 5
            """)
            
            # Formatta statistiche
            result = f"""
📊 STATISTICHE INVENTARIO ALIMENTARE

🔢 Numeri generali:
   • Totale alimenti: {stats['totale_alimenti']}
   • Categorie diverse: {stats['categorie']}
   • Ubicazioni diverse: {stats['ubicazioni']}

⚠️  Scadenze:
   • Scadono entro 7 giorni: {stats['scadono_presto']}
   • Già scaduti: {stats['scaduti']}

📈 Top categorie:
""".strip()
            
            for cat in categorie:
                result += f"\n   • {cat['categoria']}: {cat['quantita']} alimenti"
            
            result += "\n\n📍 Top ubicazioni:"
            for ub in ubicazioni:
                result += f"\n   • {ub['ubicazione']}: {ub['quantita']} alimenti"
            
            return result
            
    except Exception as e:
        logger.error(f"Errore statistiche: {e}")
        return f"Errore nel calcolo statistiche: {str(e)}"

@mcp.tool()
async def alimenti_in_scadenza(giorni: int = 7) -> str:
    """Trova alimenti che scadono entro un numero specifico di giorni.

    Args:
        giorni: Numero di giorni entro cui cercare le scadenze (default: 7)
    """
    if not db_pool:
        return "Errore: Database non disponibile"
    
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT id, nome, quantita, unita_misura, categoria, ubicazione, data_scadenza,
                       (data_scadenza - CURRENT_DATE) as giorni_rimasti
                FROM alimenti 
                WHERE data_scadenza IS NOT NULL 
                  AND data_scadenza <= CURRENT_DATE + INTERVAL '%s days'
                ORDER BY data_scadenza ASC
            """, giorni)
            
            if not rows:
                return f"✅ Nessun alimento scade nei prossimi {giorni} giorni"
            
            scaduti = []
            in_scadenza = []
            
            for row in rows:
                giorni_rimasti = row['giorni_rimasti'].days if row['giorni_rimasti'] else 0
                scadenza_str = row['data_scadenza'].strftime('%d/%m/%Y')
                
                item = f"""
🏷️  {row['nome']} (ID: {row['id']})
   📊 {row['quantita']} {row['unita_misura']} - {row['categoria']}
   📍 {row['ubicazione']}
   📅 Scade: {scadenza_str} ({abs(giorni_rimasti)} giorni {'fa' if giorni_rimasti < 0 else 'rimasti'})
""".strip()
                
                if giorni_rimasti < 0:
                    scaduti.append(item)
                else:
                    in_scadenza.append(item)
            
            result = f"⏰ CONTROLLO SCADENZE (prossimi {giorni} giorni)\n\n"
            
            if scaduti:
                result += f"❌ SCADUTI ({len(scaduti)}):\n\n"
                result += "\n\n".join(scaduti)
                result += "\n\n"
            
            if in_scadenza:
                result += f"⚠️  IN SCADENZA ({len(in_scadenza)}):\n\n"
                result += "\n\n".join(in_scadenza)
            
            return result
            
    except Exception as e:
        logger.error(f"Errore controllo scadenze: {e}")
        return f"Errore nel controllo scadenze: {str(e)}"

if __name__ == "__main__":
    # Setup database e avvio server
    async def main():
        try:
            await setup_database()
            logger.info("🚀 Server MCP Inventario avviato")
            # Avvia server con trasporto STDIO per Claude Desktop
            mcp.run(transport='stdio')
        except Exception as e:
            logger.error(f"Errore avvio server: {e}")
            raise
    
    # Esegui il server
    asyncio.run(main())
