#!/usr/bin/env python3
"""
Tool functions for task management
"""

import asyncio
import json
import logging
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional
from mcp.types import TextContent

logger = logging.getLogger(__name__)

async def log_operazione(db_pool, tipo: str, tabella: str, id_record: int, dettagli: dict, utente: str):
    """Log operation in audit table"""
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO log_operazioni (tipo_operazione, tabella, id_record, dettagli, utente) VALUES ($1, $2, $3, $4, $5)",
                tipo, tabella, id_record, json.dumps(dettagli), utente
            )
    except Exception as e:
        logger.error(f"Failed to log operation: {e}")

async def inserire_task_impl(arguments: dict, auth_info: dict, db_pool) -> List[TextContent]:
    """Crea nuovo task con gestione ricorrenza"""
    try:
        utente = auth_info.get('user_id', 'unknown')
        
        # Validazione input
        if not arguments.get('titolo'):
            raise ValueError("Il titolo è obbligatorio")
        
        # Validazione enums
        if arguments.get('priorita') and arguments['priorita'] not in ['ALTA', 'MEDIA', 'BASSA']:
            raise ValueError("Priorità non valida")
        
        if arguments.get('frequenza_ricorrenza') and arguments['frequenza_ricorrenza'] not in ['GIORNALIERA', 'SETTIMANALE', 'MENSILE']:
            raise ValueError("Frequenza ricorrenza non valida")
        
        # Validazione ricorrenza
        task_ricorrente = arguments.get('task_ricorrente', False)
        if task_ricorrente and not arguments.get('frequenza_ricorrenza'):
            raise ValueError("Frequenza ricorrenza obbligatoria per task ricorrenti")
        
        # Validazione data
        data_scadenza = None
        if arguments.get('data_scadenza'):
            try:
                data_scadenza = datetime.strptime(arguments['data_scadenza'], '%Y-%m-%d').date()
            except ValueError:
                raise ValueError("Formato data scadenza non valido (usa YYYY-MM-DD)")
        
        async with db_pool.acquire() as conn:
            result = await conn.fetchrow(
                """
                INSERT INTO task (
                    titolo, descrizione, priorita, data_scadenza, assegnatario, 
                    task_ricorrente, frequenza_ricorrenza, creato_da, modificato_da
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                RETURNING id, titolo, priorita, stato, data_creazione
                """,
                arguments['titolo'],
                arguments.get('descrizione'),
                arguments.get('priorita', 'MEDIA'),
                data_scadenza,
                arguments.get('assegnatario'),
                task_ricorrente,
                arguments.get('frequenza_ricorrenza') if task_ricorrente else None,
                utente,
                utente
            )
            
            await log_operazione(
                db_pool, "INSERIMENTO_TASK", "task", result['id'],
                {"titolo": result['titolo'], "priorita": result['priorita']}, utente
            )
            
            response = {
                "success": True,
                "message": f"Task '{result['titolo']}' creato con successo",
                "task": {
                    "id": result['id'],
                    "titolo": result['titolo'],
                    "priorita": result['priorita'],
                    "stato": result['stato'],
                    "ricorrente": task_ricorrente,
                    "data_creazione": result['data_creazione'].isoformat()
                }
            }
            
            return [TextContent(type="text", text=json.dumps(response, indent=2))]
            
    except Exception as e:
        logger.error(f"Error in inserire_task: {e}")
        return [TextContent(type="text", text=json.dumps({"success": False, "error": str(e)}))]

async def elencare_task_impl(arguments: dict, auth_info: dict, db_pool) -> List[TextContent]:
    """Lista task con filtri"""
    try:
        base_query = """
            SELECT id, titolo, descrizione, priorita, stato, data_scadenza, 
                   assegnatario, task_ricorrente, frequenza_ricorrenza, 
                   creato_da, data_creazione, modificato_da, ultima_modifica,
                   CASE 
                       WHEN data_scadenza IS NOT NULL THEN (data_scadenza - CURRENT_DATE)
                       ELSE NULL 
                   END as giorni_alla_scadenza
            FROM task WHERE 1=1
        """
        
        conditions = []
        params = []
        param_count = 0
        
        if arguments.get('stato'):
            param_count += 1
            conditions.append(f"stato = ${param_count}")
            params.append(arguments['stato'])
        
        if arguments.get('priorita'):
            param_count += 1
            conditions.append(f"priorita = ${param_count}")
            params.append(arguments['priorita'])
        
        if arguments.get('assegnatario'):
            param_count += 1
            conditions.append(f"assegnatario = ${param_count}")
            params.append(arguments['assegnatario'])
        
        if arguments.get('scadenza_entro_giorni'):
            conditions.append(f"data_scadenza IS NOT NULL AND data_scadenza <= CURRENT_DATE + INTERVAL '{arguments['scadenza_entro_giorni']} days'")
        
        if arguments.get('ricorrenti') is not None:
            param_count += 1
            conditions.append(f"task_ricorrente = ${param_count}")
            params.append(arguments['ricorrenti'])
        
        if conditions:
            base_query += " AND " + " AND ".join(conditions)
        
        base_query += " ORDER BY data_scadenza ASC NULLS LAST, priorita DESC, data_creazione DESC"
        
        limit = arguments.get('limit', 50)
        param_count += 1
        base_query += f" LIMIT ${param_count}"
        params.append(limit)
        
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(base_query, *params)
            
            tasks = []
            for row in rows:
                task = {
                    "id": row['id'],
                    "titolo": row['titolo'],
                    "descrizione": row['descrizione'],
                    "priorita": row['priorita'],
                    "stato": row['stato'],
                    "data_scadenza": row['data_scadenza'].isoformat() if row['data_scadenza'] else None,
                    "giorni_alla_scadenza": row['giorni_alla_scadenza'],
                    "assegnatario": row['assegnatario'],
                    "task_ricorrente": row['task_ricorrente'],
                    "frequenza_ricorrenza": row['frequenza_ricorrenza'],
                    "creato_da": row['creato_da'],
                    "data_creazione": row['data_creazione'].isoformat(),
                    "ultima_modifica": row['ultima_modifica'].isoformat()
                }
                
                # Alert per scadenze
                if row['giorni_alla_scadenza'] is not None:
                    if row['giorni_alla_scadenza'] < 0:
                        task['alert'] = "SCADUTO"
                    elif row['giorni_alla_scadenza'] <= 1:
                        task['alert'] = "SCADENZA_IMMINENTE"
                
                tasks.append(task)
            
            response = {
                "success": True,
                "tasks": tasks,
                "filtri_applicati": {k: v for k, v in arguments.items() if v is not None},
                "totale_risultati": len(tasks)
            }
            
            return [TextContent(type="text", text=json.dumps(response, indent=2))]
            
    except Exception as e:
        logger.error(f"Error in elencare_task: {e}")
        return [TextContent(type="text", text=json.dumps({"success": False, "error": str(e)}))]

async def completare_task_impl(arguments: dict, auth_info: dict, db_pool) -> List[TextContent]:
    """Completa task e gestisce ricorrenza"""
    try:
        utente = auth_info.get('user_id', 'unknown')
        
        if not arguments.get('task_id'):
            raise ValueError("task_id è obbligatorio")
        
        async with db_pool.acquire() as conn:
            # Get task info
            task = await conn.fetchrow(
                "SELECT * FROM task WHERE id = $1",
                arguments['task_id']
            )
            
            if not task:
                raise ValueError(f"Task con ID {arguments['task_id']} non trovato")
            
            if task['stato'] == 'COMPLETATO':
                return [TextContent(type="text", text=json.dumps({
                    "success": False,
                    "message": "Task già completato"
                }))]
            
            # Complete current task
            await conn.execute(
                "UPDATE task SET stato = 'COMPLETATO', modificato_da = $1 WHERE id = $2",
                utente, arguments['task_id']
            )
            
            # Handle recurrence
            nuovo_task_id = None
            if task['task_ricorrente']:
                next_date = None
                if task['data_scadenza']:
                    if task['frequenza_ricorrenza'] == 'GIORNALIERA':
                        next_date = task['data_scadenza'] + timedelta(days=1)
                    elif task['frequenza_ricorrenza'] == 'SETTIMANALE':
                        next_date = task['data_scadenza'] + timedelta(weeks=1)
                    elif task['frequenza_ricorrenza'] == 'MENSILE':
                        next_date = task['data_scadenza'] + timedelta(days=30)
                
                # Create new recurring task
                result = await conn.fetchrow(
                    """
                    INSERT INTO task (
                        titolo, descrizione, priorita, data_scadenza, assegnatario,
                        task_ricorrente, frequenza_ricorrenza, creato_da, modificato_da, task_padre_id
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                    RETURNING id
                    """,
                    task['titolo'], task['descrizione'], task['priorita'], next_date,
                    task['assegnatario'], True, task['frequenza_ricorrenza'],
                    utente, utente, arguments['task_id']
                )
                nuovo_task_id = result['id']
            
            await log_operazione(
                db_pool, "COMPLETAMENTO_TASK", "task", arguments['task_id'],
                {
                    "note_completamento": arguments.get('note_completamento'),
                    "ricorrente": task['task_ricorrente'],
                    "nuovo_task_id": nuovo_task_id
                }, utente
            )
            
            response = {
                "success": True,
                "message": f"Task '{task['titolo']}' completato con successo",
                "task_completato": arguments['task_id'],
                "ricorrente": task['task_ricorrente']
            }
            
            if nuovo_task_id:
                response["nuovo_task_ricorrente"] = {
                    "id": nuovo_task_id,
                    "message": f"Creato nuovo task ricorrente per {next_date}"
                }
            
            return [TextContent(type="text", text=json.dumps(response, indent=2))]
            
    except Exception as e:
        logger.error(f"Error in completare_task: {e}")
        return [TextContent(type="text", text=json.dumps({"success": False, "error": str(e)}))]
