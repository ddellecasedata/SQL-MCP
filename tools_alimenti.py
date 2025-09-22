"""
Tool MCP per gestione alimenti del magazzino
"""

from datetime import datetime, date
from decimal import Decimal
from typing import Dict, List, Optional, Any
import asyncpg
from mcp.types import Tool, TextContent
from server import mcp_server, log_operation, serialize_datetime

@mcp_server.call_tool()
async def aggiungere_alimento(
    nome: str,
    quantita: float,
    unita_misura: str,
    categoria: str,
    ubicazione: str,
    data_scadenza: Optional[str] = None,
    data_apertura: Optional[str] = None,
    prezzo_acquisto: Optional[float] = None,
    fornitore: Optional[str] = None,
    lotto_acquisto: Optional[str] = None,
    modificato_da: str = "user"
) -> List[TextContent]:
    """
    Inserisce un nuovo alimento nel magazzino
    
    Args:
        nome: Nome dell'alimento
        quantita: Quantità disponibile
        unita_misura: Unità di misura (PEZZI, KG, LITRI, GRAMMI)
        categoria: Categoria alimento (LATTICINI, VERDURE, FRUTTA, CARNE, PESCE, CONSERVE, BEVANDE, ALTRO)
        ubicazione: Dove è conservato (FRIGO, FREEZER, DISPENSA, CANTINA)
        data_scadenza: Data di scadenza (YYYY-MM-DD)
        data_apertura: Data di apertura (YYYY-MM-DD)
        prezzo_acquisto: Prezzo di acquisto
        fornitore: Nome del fornitore
        lotto_acquisto: Codice lotto di acquisto
        modificato_da: Chi ha effettuato l'operazione
    """
    try:
        async with db_pool.acquire() as conn:
            # Validazione enum values
            valid_unita = ['PEZZI', 'KG', 'LITRI', 'GRAMMI']
            valid_categoria = ['LATTICINI', 'VERDURE', 'FRUTTA', 'CARNE', 'PESCE', 'CONSERVE', 'BEVANDE', 'ALTRO']
            valid_ubicazione = ['FRIGO', 'FREEZER', 'DISPENSA', 'CANTINA']
            
            if unita_misura not in valid_unita:
                raise ValueError(f"Unità di misura non valida. Valori accettati: {valid_unita}")
            if categoria not in valid_categoria:
                raise ValueError(f"Categoria non valida. Valori accettati: {valid_categoria}")
            if ubicazione not in valid_ubicazione:
                raise ValueError(f"Ubicazione non valida. Valori accettati: {valid_ubicazione}")
            
            # Parsing date se fornite
            scadenza_date = None
            apertura_date = None
            if data_scadenza:
                scadenza_date = datetime.strptime(data_scadenza, "%Y-%m-%d").date()
            if data_apertura:
                apertura_date = datetime.strptime(data_apertura, "%Y-%m-%d").date()
            
            # Insert alimento
            result = await conn.fetchrow("""
                INSERT INTO alimenti 
                (nome, quantita, unita_misura, data_scadenza, data_apertura, 
                 categoria, ubicazione, prezzo_acquisto, fornitore, lotto_acquisto, modificato_da)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                RETURNING id
            """, nome, quantita, unita_misura, scadenza_date, apertura_date,
                categoria, ubicazione, prezzo_acquisto, fornitore, lotto_acquisto, modificato_da)
            
            alimento_id = result['id']
            
            # Log operazione
            await log_operation(
                conn, "INSERT", "alimenti", alimento_id,
                {
                    "nome": nome, "quantita": quantita, "unita_misura": unita_misura,
                    "categoria": categoria, "ubicazione": ubicazione
                },
                modificato_da
            )
            
            return [TextContent(
                type="text",
                text=f"Alimento '{nome}' aggiunto con successo. ID: {alimento_id}"
            )]
            
    except ValueError as e:
        return [TextContent(type="text", text=f"Errore validazione: {str(e)}")]
    except Exception as e:
        return [TextContent(type="text", text=f"Errore durante l'inserimento: {str(e)}")]

@mcp_server.call_tool()
async def consultare_giacenze(
    categoria: Optional[str] = None,
    ubicazione: Optional[str] = None,
    in_scadenza_giorni: Optional[int] = None,
    quantita_minima: Optional[float] = None
) -> List[TextContent]:
    """
    Visualizza le giacenze del magazzino con filtri
    
    Args:
        categoria: Filtro per categoria
        ubicazione: Filtro per ubicazione
        in_scadenza_giorni: Mostra solo alimenti in scadenza entro X giorni
        quantita_minima: Mostra solo alimenti con quantità >= valore
    """
    try:
        async with db_pool.acquire() as conn:
            query = """
                SELECT id, nome, quantita, unita_misura, data_scadenza, 
                       categoria, ubicazione, fornitore
                FROM alimenti 
                WHERE quantita > 0
            """
            params = []
            param_count = 0
            
            if categoria:
                param_count += 1
                query += f" AND categoria = ${param_count}"
                params.append(categoria)
                
            if ubicazione:
                param_count += 1
                query += f" AND ubicazione = ${param_count}"
                params.append(ubicazione)
                
            if in_scadenza_giorni is not None:
                param_count += 1
                query += f" AND data_scadenza IS NOT NULL AND data_scadenza <= CURRENT_DATE + INTERVAL '{in_scadenza_giorni} days'"
                
            if quantita_minima is not None:
                param_count += 1
                query += f" AND quantita >= ${param_count}"
                params.append(quantita_minima)
                
            query += " ORDER BY data_scadenza ASC, nome ASC"
            
            rows = await conn.fetch(query, *params)
            
            if not rows:
                return [TextContent(type="text", text="Nessun alimento trovato con i filtri specificati")]
            
            giacenze = []
            for row in rows:
                giorni_scadenza = "N/A"
                if row['data_scadenza']:
                    delta = row['data_scadenza'] - date.today()
                    giorni_scadenza = delta.days
                
                giacenze.append({
                    "id": row['id'],
                    "nome": row['nome'],
                    "quantita": float(row['quantita']),
                    "unita_misura": row['unita_misura'],
                    "data_scadenza": row['data_scadenza'].isoformat() if row['data_scadenza'] else None,
                    "giorni_alla_scadenza": giorni_scadenza,
                    "categoria": row['categoria'],
                    "ubicazione": row['ubicazione'],
                    "fornitore": row['fornitore']
                })
            
            result_text = f"Trovati {len(giacenze)} alimenti:\n\n"
            for g in giacenze:
                result_text += f"• {g['nome']} - {g['quantita']} {g['unita_misura']}\n"
                result_text += f"  Categoria: {g['categoria']}, Ubicazione: {g['ubicazione']}\n"
                if g['data_scadenza']:
                    result_text += f"  Scade: {g['data_scadenza']} ({g['giorni_alla_scadenza']} giorni)\n"
                result_text += "\n"
            
            return [TextContent(type="text", text=result_text)]
            
    except Exception as e:
        return [TextContent(type="text", text=f"Errore durante la consultazione: {str(e)}")]

@mcp_server.call_tool()
async def scaricare_alimento(
    alimento_id: int,
    quantita_consumata: float,
    motivo: str = "CONSUMATO",
    note: Optional[str] = None,
    forza_operazione: bool = False,
    utente: str = "user"
) -> List[TextContent]:
    """
    Registra il consumo di un alimento con controllo quantità
    
    Args:
        alimento_id: ID dell'alimento
        quantita_consumata: Quantità da scaricare
        motivo: Motivo del consumo (CONSUMATO, SCADUTO, BUTTATO)
        note: Note aggiuntive
        forza_operazione: Se True, forza l'operazione anche se quantità > giacenza
        utente: Chi effettua l'operazione
    """
    try:
        valid_motivi = ['CONSUMATO', 'SCADUTO', 'BUTTATO']
        if motivo not in valid_motivi:
            return [TextContent(type="text", text=f"Motivo non valido. Valori accettati: {valid_motivi}")]
            
        async with db_pool.acquire() as conn:
            async with conn.transaction():
                # Verifica giacenza attuale
                alimento = await conn.fetchrow("""
                    SELECT id, nome, quantita, unita_misura FROM alimenti WHERE id = $1
                """, alimento_id)
                
                if not alimento:
                    return [TextContent(type="text", text=f"Alimento con ID {alimento_id} non trovato")]
                
                giacenza_attuale = float(alimento['quantita'])
                
                # Controllo quantità
                if quantita_consumata > giacenza_attuale and not forza_operazione:
                    return [TextContent(
                        type="text", 
                        text=f"ATTENZIONE: Quantità da scaricare ({quantita_consumata}) > giacenza attuale ({giacenza_attuale}). "
                             f"Per forzare l'operazione, impostare forza_operazione=True"
                    )]
                
                # Registra consumo
                await conn.execute("""
                    INSERT INTO consumi_alimenti (alimento_id, quantita_consumata, motivo, note)
                    VALUES ($1, $2, $3, $4)
                """, alimento_id, quantita_consumata, motivo, note)
                
                # Aggiorna giacenza
                nuova_quantita = max(0, giacenza_attuale - quantita_consumata)
                await conn.execute("""
                    UPDATE alimenti SET quantita = $1, modificato_da = $2
                    WHERE id = $3
                """, nuova_quantita, utente, alimento_id)
                
                # Log operazione
                await log_operation(
                    conn, "SCARICO", "alimenti", alimento_id,
                    {
                        "quantita_consumata": quantita_consumata,
                        "motivo": motivo,
                        "giacenza_precedente": giacenza_attuale,
                        "nuova_giacenza": nuova_quantita
                    },
                    utente
                )
                
                return [TextContent(
                    type="text",
                    text=f"Scaricato {quantita_consumata} {alimento['unita_misura']} di '{alimento['nome']}'. "
                         f"Giacenza aggiornata: {nuova_quantita}"
                )]
                
    except Exception as e:
        return [TextContent(type="text", text=f"Errore durante lo scarico: {str(e)}")]

@mcp_server.call_tool()
async def notifiche_scadenza(giorni_limite: int = 3) -> List[TextContent]:
    """
    Restituisce alimenti in scadenza entro X giorni
    
    Args:
        giorni_limite: Giorni entro cui considerare l'alimento in scadenza
    """
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM alimenti_in_scadenza($1)", giorni_limite)
            
            if not rows:
                return [TextContent(type="text", text=f"Nessun alimento in scadenza entro {giorni_limite} giorni")]
            
            result_text = f"⚠️  ALIMENTI IN SCADENZA entro {giorni_limite} giorni:\n\n"
            
            for row in rows:
                giorni = row['giorni_alla_scadenza']
                urgenza = "🔴 SCADUTO" if giorni < 0 else "🟡 OGGI" if giorni == 0 else f"🟠 {giorni} giorni"
                
                result_text += f"• {row['nome']} - {float(row['quantita'])} {row['unita_misura']}\n"
                result_text += f"  {urgenza} - Scade: {row['data_scadenza']}\n"
                result_text += f"  {row['categoria']} - {row['ubicazione']}\n\n"
            
            return [TextContent(type="text", text=result_text)]
            
    except Exception as e:
        return [TextContent(type="text", text=f"Errore durante la verifica scadenze: {str(e)}")]

@mcp_server.call_tool()
async def statistiche_consumi(
    data_inizio: Optional[str] = None,
    data_fine: Optional[str] = None,
    gruppo_per: str = "categoria"
) -> List[TextContent]:
    """
    Calcola statistiche consumi per periodo
    
    Args:
        data_inizio: Data inizio periodo (YYYY-MM-DD)
        data_fine: Data fine periodo (YYYY-MM-DD) 
        gruppo_per: Raggruppa per 'categoria', 'motivo' o 'totale'
    """
    try:
        # Default ultimi 30 giorni se non specificato
        if not data_inizio:
            data_inizio = (date.today() - timedelta(days=30)).isoformat()
        if not data_fine:
            data_fine = date.today().isoformat()
            
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM statistiche_consumi($1, $2, $3)",
                datetime.strptime(data_inizio, "%Y-%m-%d").date(),
                datetime.strptime(data_fine, "%Y-%m-%d").date(),
                gruppo_per
            )
            
            if not rows:
                return [TextContent(type="text", text="Nessun consumo registrato nel periodo")]
            
            result_text = f"📊 STATISTICHE CONSUMI dal {data_inizio} al {data_fine}\n"
            result_text += f"Raggruppate per: {gruppo_per}\n\n"
            
            for row in rows:
                result_text += f"• {row['gruppo']}\n"
                result_text += f"  Totale consumato: {float(row['totale_consumato'])}\n"
                result_text += f"  Operazioni: {row['numero_operazioni']}\n"
                result_text += f"  Media giornaliera: {float(row['media_giornaliera'])}\n\n"
            
            return [TextContent(type="text", text=result_text)]
            
    except Exception as e:
        return [TextContent(type="text", text=f"Errore nel calcolo statistiche: {str(e)}")]
