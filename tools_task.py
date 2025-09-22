"""
Tool MCP per gestione task e TODO list
"""

from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Any
import asyncpg
from mcp.types import Tool, TextContent
from server import mcp_server, log_operation, serialize_datetime

@mcp_server.call_tool()
async def inserire_task(
    titolo: str,
    descrizione: Optional[str] = None,
    priorita: str = "MEDIA",
    data_scadenza: Optional[str] = None,
    assegnatario: Optional[str] = None,
    task_ricorrente: bool = False,
    frequenza_ricorrenza: Optional[str] = None,
    creato_da: str = "user"
) -> List[TextContent]:
    """
    Crea nuovo task con gestione ricorrenza
    
    Args:
        titolo: Titolo del task
        descrizione: Descrizione dettagliata
        priorita: Priorità (ALTA, MEDIA, BASSA)
        data_scadenza: Data di scadenza (YYYY-MM-DD)
        assegnatario: Chi deve svolgere il task
        task_ricorrente: Se il task è ricorrente
        frequenza_ricorrenza: Frequenza (GIORNALIERA, SETTIMANALE, MENSILE)
        creato_da: Chi ha creato il task
    """
    try:
        # Validazioni
        valid_priorita = ['ALTA', 'MEDIA', 'BASSA']
        valid_frequenze = ['GIORNALIERA', 'SETTIMANALE', 'MENSILE']
        
        if priorita not in valid_priorita:
            return [TextContent(type="text", text=f"Priorità non valida. Valori accettati: {valid_priorita}")]
            
        if task_ricorrente and not frequenza_ricorrenza:
            return [TextContent(type="text", text="Per task ricorrenti è obbligatorio specificare la frequenza")]
            
        if frequenza_ricorrenza and frequenza_ricorrenza not in valid_frequenze:
            return [TextContent(type="text", text=f"Frequenza non valida. Valori accettati: {valid_frequenze}")]
        
        # Parsing data scadenza
        scadenza_date = None
        if data_scadenza:
            scadenza_date = datetime.strptime(data_scadenza, "%Y-%m-%d").date()
        
        async with db_pool.acquire() as conn:
            # Insert task
            result = await conn.fetchrow("""
                INSERT INTO task 
                (titolo, descrizione, priorita, data_scadenza, assegnatario, 
                 task_ricorrente, frequenza_ricorrenza, creato_da, modificato_da)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $8)
                RETURNING id
            """, titolo, descrizione, priorita, scadenza_date, assegnatario,
                task_ricorrente, frequenza_ricorrenza, creato_da)
            
            task_id = result['id']
            
            # Log operazione
            await log_operation(
                conn, "INSERT", "task", task_id,
                {
                    "titolo": titolo, "priorita": priorita,
                    "task_ricorrente": task_ricorrente,
                    "frequenza_ricorrenza": frequenza_ricorrenza
                },
                creato_da
            )
            
            return [TextContent(
                type="text",
                text=f"Task '{titolo}' creato con successo. ID: {task_id}"
            )]
            
    except ValueError as e:
        return [TextContent(type="text", text=f"Errore validazione data: {str(e)}")]
    except Exception as e:
        return [TextContent(type="text", text=f"Errore durante la creazione: {str(e)}")]

@mcp_server.call_tool()
async def elencare_task(
    stato: Optional[str] = None,
    priorita: Optional[str] = None,
    assegnatario: Optional[str] = None,
    scadenza_entro_giorni: Optional[int] = None,
    solo_ricorrenti: bool = False
) -> List[TextContent]:
    """
    Lista task con filtri
    
    Args:
        stato: Filtro per stato (DA_FARE, IN_CORSO, COMPLETATO, ANNULLATO)
        priorita: Filtro per priorità
        assegnatario: Filtro per assegnatario
        scadenza_entro_giorni: Mostra solo task in scadenza entro X giorni
        solo_ricorrenti: Mostra solo task ricorrenti
    """
    try:
        async with db_pool.acquire() as conn:
            query = """
                SELECT id, titolo, descrizione, priorita, stato, data_scadenza, 
                       assegnatario, task_ricorrente, frequenza_ricorrenza, 
                       creato_da, data_creazione
                FROM task 
                WHERE 1=1
            """
            params = []
            param_count = 0
            
            if stato:
                param_count += 1
                query += f" AND stato = ${param_count}"
                params.append(stato)
                
            if priorita:
                param_count += 1
                query += f" AND priorita = ${param_count}"
                params.append(priorita)
                
            if assegnatario:
                param_count += 1
                query += f" AND assegnatario = ${param_count}"
                params.append(assegnatario)
                
            if scadenza_entro_giorni is not None:
                query += f" AND data_scadenza IS NOT NULL AND data_scadenza <= CURRENT_DATE + INTERVAL '{scadenza_entro_giorni} days'"
                
            if solo_ricorrenti:
                query += " AND task_ricorrente = TRUE"
                
            query += " ORDER BY priorita DESC, data_scadenza ASC, data_creazione ASC"
            
            rows = await conn.fetch(query, *params)
            
            if not rows:
                return [TextContent(type="text", text="Nessun task trovato con i filtri specificati")]
            
            result_text = f"📋 Trovati {len(rows)} task:\n\n"
            
            for row in rows:
                # Emoji per priorità
                priority_emoji = {"ALTA": "🔴", "MEDIA": "🟡", "BASSA": "🟢"}
                status_emoji = {
                    "DA_FARE": "📌", "IN_CORSO": "⏳", 
                    "COMPLETATO": "✅", "ANNULLATO": "❌"
                }
                
                result_text += f"{priority_emoji.get(row['priorita'], '')} {status_emoji.get(row['stato'], '')} "
                result_text += f"**{row['titolo']}** (ID: {row['id']})\n"
                
                if row['descrizione']:
                    result_text += f"   {row['descrizione']}\n"
                
                result_text += f"   Stato: {row['stato']} | Priorità: {row['priorita']}\n"
                
                if row['data_scadenza']:
                    giorni_scadenza = (row['data_scadenza'] - date.today()).days
                    urgenza = "🔴 SCADUTO" if giorni_scadenza < 0 else "🟡 OGGI" if giorni_scadenza == 0 else f"📅 {giorni_scadenza} giorni"
                    result_text += f"   Scadenza: {row['data_scadenza']} ({urgenza})\n"
                
                if row['assegnatario']:
                    result_text += f"   Assegnato a: {row['assegnatario']}\n"
                
                if row['task_ricorrente']:
                    result_text += f"   🔄 Ricorrente: {row['frequenza_ricorrenza']}\n"
                
                result_text += f"   Creato da: {row['creato_da']} il {row['data_creazione'].date()}\n\n"
            
            return [TextContent(type="text", text=result_text)]
            
    except Exception as e:
        return [TextContent(type="text", text=f"Errore durante l'elenco: {str(e)}")]

@mcp_server.call_tool()
async def aggiornare_task(
    task_id: int,
    titolo: Optional[str] = None,
    descrizione: Optional[str] = None,
    priorita: Optional[str] = None,
    stato: Optional[str] = None,
    data_scadenza: Optional[str] = None,
    assegnatario: Optional[str] = None,
    modificato_da: str = "user"
) -> List[TextContent]:
    """
    Modifica task esistente con tracciamento modifiche
    
    Args:
        task_id: ID del task da modificare
        titolo: Nuovo titolo
        descrizione: Nuova descrizione 
        priorita: Nuova priorità
        stato: Nuovo stato
        data_scadenza: Nuova data scadenza (YYYY-MM-DD)
        assegnatario: Nuovo assegnatario
        modificato_da: Chi effettua la modifica
    """
    try:
        # Validazioni
        if priorita:
            valid_priorita = ['ALTA', 'MEDIA', 'BASSA']
            if priorita not in valid_priorita:
                return [TextContent(type="text", text=f"Priorità non valida. Valori accettati: {valid_priorita}")]
        
        if stato:
            valid_stati = ['DA_FARE', 'IN_CORSO', 'COMPLETATO', 'ANNULLATO']
            if stato not in valid_stati:
                return [TextContent(type="text", text=f"Stato non valido. Valori accettati: {valid_stati}")]
        
        async with db_pool.acquire() as conn:
            async with conn.transaction():
                # Verifica esistenza task
                task_esistente = await conn.fetchrow("SELECT * FROM task WHERE id = $1", task_id)
                if not task_esistente:
                    return [TextContent(type="text", text=f"Task con ID {task_id} non trovato")]
                
                # Prepara update dinamico
                updates = []
                params = [modificato_da]
                param_count = 1
                
                if titolo:
                    param_count += 1
                    updates.append(f"titolo = ${param_count}")
                    params.append(titolo)
                
                if descrizione is not None:  # Permette di settare a NULL
                    param_count += 1
                    updates.append(f"descrizione = ${param_count}")
                    params.append(descrizione)
                
                if priorita:
                    param_count += 1
                    updates.append(f"priorita = ${param_count}")
                    params.append(priorita)
                
                if stato:
                    param_count += 1
                    updates.append(f"stato = ${param_count}")
                    params.append(stato)
                
                if data_scadenza:
                    param_count += 1
                    updates.append(f"data_scadenza = ${param_count}")
                    scadenza_date = datetime.strptime(data_scadenza, "%Y-%m-%d").date()
                    params.append(scadenza_date)
                
                if assegnatario is not None:
                    param_count += 1
                    updates.append(f"assegnatario = ${param_count}")
                    params.append(assegnatario)
                
                if not updates:
                    return [TextContent(type="text", text="Nessun campo da aggiornare specificato")]
                
                # Update query
                updates.append("modificato_da = $1")
                query = f"UPDATE task SET {', '.join(updates)} WHERE id = ${param_count + 1}"
                params.append(task_id)
                
                await conn.execute(query, *params)
                
                # Log operazione
                await log_operation(
                    conn, "UPDATE", "task", task_id,
                    {
                        "campi_modificati": {k: v for k, v in [
                            ("titolo", titolo), ("descrizione", descrizione),
                            ("priorita", priorita), ("stato", stato),
                            ("data_scadenza", data_scadenza), ("assegnatario", assegnatario)
                        ] if v is not None},
                        "valori_precedenti": dict(task_esistente)
                    },
                    modificato_da
                )
                
                return [TextContent(type="text", text=f"Task ID {task_id} aggiornato con successo")]
                
    except ValueError as e:
        return [TextContent(type="text", text=f"Errore validazione data: {str(e)}")]
    except Exception as e:
        return [TextContent(type="text", text=f"Errore durante l'aggiornamento: {str(e)}")]

@mcp_server.call_tool()
async def completare_task(
    task_id: int,
    modificato_da: str = "user"
) -> List[TextContent]:
    """
    Marca task come completato e gestisce ricorrenze
    
    Args:
        task_id: ID del task da completare
        modificato_da: Chi completa il task
    """
    try:
        async with db_pool.acquire() as conn:
            async with conn.transaction():
                # Verifica task esistente
                task = await conn.fetchrow("SELECT * FROM task WHERE id = $1", task_id)
                if not task:
                    return [TextContent(type="text", text=f"Task con ID {task_id} non trovato")]
                
                if task['stato'] == 'COMPLETATO':
                    return [TextContent(type="text", text=f"Task ID {task_id} è già completato")]
                
                # Completa task corrente
                await conn.execute("""
                    UPDATE task SET stato = 'COMPLETATO', modificato_da = $1 
                    WHERE id = $2
                """, modificato_da, task_id)
                
                # Log operazione
                await log_operation(
                    conn, "COMPLETE", "task", task_id,
                    {"stato_precedente": task['stato']},
                    modificato_da
                )
                
                result_text = f"Task '{task['titolo']}' completato con successo."
                
                # Gestione ricorrenza
                if task['task_ricorrente']:
                    next_date = None
                    oggi = date.today()
                    
                    if task['frequenza_ricorrenza'] == 'GIORNALIERA':
                        next_date = oggi + timedelta(days=1)
                    elif task['frequenza_ricorrenza'] == 'SETTIMANALE':
                        next_date = oggi + timedelta(weeks=1)
                    elif task['frequenza_ricorrenza'] == 'MENSILE':
                        next_date = oggi + timedelta(days=30)
                    
                    if next_date:
                        # Crea nuovo task ricorrente
                        new_task = await conn.fetchrow("""
                            INSERT INTO task 
                            (titolo, descrizione, priorita, data_scadenza, assegnatario,
                             task_ricorrente, frequenza_ricorrenza, creato_da, modificato_da, task_padre_id)
                            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $8, $9)
                            RETURNING id
                        """, task['titolo'], task['descrizione'], task['priorita'], next_date,
                            task['assegnatario'], True, task['frequenza_ricorrenza'], 
                            modificato_da, task_id)
                        
                        result_text += f"\n🔄 Nuovo task ricorrente creato (ID: {new_task['id']}) con scadenza {next_date}"
                
                return [TextContent(type="text", text=result_text)]
                
    except Exception as e:
        return [TextContent(type="text", text=f"Errore durante il completamento: {str(e)}")]

@mcp_server.call_tool()
async def statistiche_task(
    data_inizio: Optional[str] = None,
    data_fine: Optional[str] = None,
    gruppo_per: str = "stato"
) -> List[TextContent]:
    """
    Report su completamento task per periodo
    
    Args:
        data_inizio: Data inizio periodo (YYYY-MM-DD)
        data_fine: Data fine periodo (YYYY-MM-DD)
        gruppo_per: Raggruppa per 'stato', 'priorita', 'assegnatario'
    """
    try:
        # Default ultimi 30 giorni se non specificato
        if not data_inizio:
            data_inizio = (date.today() - timedelta(days=30)).isoformat()
        if not data_fine:
            data_fine = date.today().isoformat()
        
        async with db_pool.acquire() as conn:
            # Query base per statistiche
            if gruppo_per == "stato":
                query = """
                    SELECT stato as gruppo, COUNT(*) as totale
                    FROM task 
                    WHERE data_creazione::date BETWEEN $1 AND $2
                    GROUP BY stato
                    ORDER BY totale DESC
                """
            elif gruppo_per == "priorita":
                query = """
                    SELECT priorita as gruppo, COUNT(*) as totale
                    FROM task 
                    WHERE data_creazione::date BETWEEN $1 AND $2
                    GROUP BY priorita
                    ORDER BY CASE priorita WHEN 'ALTA' THEN 1 WHEN 'MEDIA' THEN 2 ELSE 3 END
                """
            elif gruppo_per == "assegnatario":
                query = """
                    SELECT COALESCE(assegnatario, 'Non assegnato') as gruppo, COUNT(*) as totale
                    FROM task 
                    WHERE data_creazione::date BETWEEN $1 AND $2
                    GROUP BY assegnatario
                    ORDER BY totale DESC
                """
            else:
                return [TextContent(type="text", text="gruppo_per non valido. Usare: stato, priorita, assegnatario")]
            
            rows = await conn.fetch(query, 
                datetime.strptime(data_inizio, "%Y-%m-%d").date(),
                datetime.strptime(data_fine, "%Y-%m-%d").date()
            )
            
            if not rows:
                return [TextContent(type="text", text="Nessun task trovato nel periodo specificato")]
            
            # Calcola totale
            totale_task = sum(row['totale'] for row in rows)
            
            result_text = f"📊 STATISTICHE TASK dal {data_inizio} al {data_fine}\n"
            result_text += f"Raggruppate per: {gruppo_per}\n"
            result_text += f"Totale task: {totale_task}\n\n"
            
            for row in rows:
                percentuale = (row['totale'] / totale_task * 100) if totale_task > 0 else 0
                result_text += f"• {row['gruppo']}: {row['totale']} ({percentuale:.1f}%)\n"
            
            # Statistiche aggiuntive per task completati
            if gruppo_per == "stato":
                completati = await conn.fetchval("""
                    SELECT COUNT(*) FROM task 
                    WHERE stato = 'COMPLETATO' 
                    AND ultima_modifica::date BETWEEN $1 AND $2
                """, datetime.strptime(data_inizio, "%Y-%m-%d").date(),
                    datetime.strptime(data_fine, "%Y-%m-%d").date())
                
                result_text += f"\n✅ Task completati nel periodo: {completati}"
                
                # Task in scadenza
                in_scadenza = await conn.fetchval("""
                    SELECT COUNT(*) FROM task 
                    WHERE stato IN ('DA_FARE', 'IN_CORSO')
                    AND data_scadenza <= CURRENT_DATE + INTERVAL '7 days'
                """)
                
                if in_scadenza > 0:
                    result_text += f"\n⚠️  Task in scadenza (prossimi 7 giorni): {in_scadenza}"
            
            return [TextContent(type="text", text=result_text)]
            
    except Exception as e:
        return [TextContent(type="text", text=f"Errore nel calcolo statistiche: {str(e)}")]
