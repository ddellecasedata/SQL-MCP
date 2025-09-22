#!/usr/bin/env python3
"""
Complete tool implementations for missing functions
"""

import json
import logging
from datetime import datetime, date, timedelta
from typing import List
from decimal import Decimal
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

async def aggiornare_alimento_impl(arguments: dict, auth_info: dict, db_pool) -> List[TextContent]:
    """Modifica dati di un alimento esistente"""
    try:
        utente = auth_info.get('user_id', 'unknown')
        
        if not arguments.get('alimento_id'):
            raise ValueError("alimento_id è obbligatorio")
        
        async with db_pool.acquire() as conn:
            # Verifica esistenza
            alimento = await conn.fetchrow("SELECT * FROM alimenti WHERE id = $1", arguments['alimento_id'])
            if not alimento:
                raise ValueError(f"Alimento con ID {arguments['alimento_id']} non trovato")
            
            # Costruisci query di update dinamica
            updates = []
            params = []
            param_count = 0
            
            update_fields = ['nome', 'quantita', 'data_scadenza', 'data_apertura', 'categoria', 
                           'ubicazione', 'prezzo_acquisto', 'fornitore', 'lotto_acquisto']
            
            for field in update_fields:
                if field in arguments and arguments[field] is not None:
                    param_count += 1
                    updates.append(f"{field} = ${param_count}")
                    
                    if field in ['quantita', 'prezzo_acquisto']:
                        params.append(Decimal(str(arguments[field])))
                    elif field in ['data_scadenza', 'data_apertura']:
                        params.append(datetime.strptime(arguments[field], '%Y-%m-%d').date())
                    else:
                        params.append(arguments[field])
            
            if not updates:
                raise ValueError("Nessun campo da aggiornare specificato")
            
            # Aggiungi modificato_da
            param_count += 1
            updates.append(f"modificato_da = ${param_count}")
            params.append(utente)
            
            # Aggiungi ID per WHERE
            param_count += 1
            params.append(arguments['alimento_id'])
            
            query = f"UPDATE alimenti SET {', '.join(updates)} WHERE id = ${param_count} RETURNING *"
            
            result = await conn.fetchrow(query, *params)
            
            await log_operazione(
                db_pool, "AGGIORNAMENTO_ALIMENTO", "alimenti", arguments['alimento_id'],
                {k: v for k, v in arguments.items() if k != 'alimento_id'}, utente
            )
            
            response = {
                "success": True,
                "message": f"Alimento '{result['nome']}' aggiornato con successo",
                "alimento": {
                    "id": result['id'],
                    "nome": result['nome'],
                    "quantita": float(result['quantita']),
                    "categoria": result['categoria'],
                    "ubicazione": result['ubicazione'],
                    "ultima_modifica": result['ultima_modifica'].isoformat()
                }
            }
            
            return [TextContent(type="text", text=json.dumps(response, indent=2))]
            
    except Exception as e:
        logger.error(f"Error in aggiornare_alimento: {e}")
        return [TextContent(type="text", text=json.dumps({"success": False, "error": str(e)}))]

async def statistiche_consumi_impl(arguments: dict, auth_info: dict, db_pool) -> List[TextContent]:
    """Calcola statistiche consumi per periodo"""
    try:
        # Default dates
        data_fine = datetime.strptime(arguments.get('data_fine', datetime.now().date().isoformat()), '%Y-%m-%d').date()
        data_inizio = datetime.strptime(arguments.get('data_inizio', (data_fine - timedelta(days=30)).isoformat()), '%Y-%m-%d').date()
        raggruppa_per = arguments.get('raggruppa_per', 'categoria')
        
        async with db_pool.acquire() as conn:
            # Usa la funzione database
            rows = await conn.fetch(
                "SELECT * FROM statistiche_consumi($1, $2, $3)",
                data_inizio, data_fine, raggruppa_per
            )
            
            statistiche = []
            for row in rows:
                statistiche.append({
                    "gruppo": row['gruppo'],
                    "totale_consumato": float(row['totale_consumato']) if row['totale_consumato'] else 0,
                    "numero_operazioni": row['numero_operazioni'],
                    "media_giornaliera": float(row['media_giornaliera']) if row['media_giornaliera'] else 0
                })
            
            response = {
                "success": True,
                "parametri": {
                    "data_inizio": data_inizio.isoformat(),
                    "data_fine": data_fine.isoformat(),
                    "raggruppa_per": raggruppa_per,
                    "giorni_periodo": (data_fine - data_inizio).days + 1
                },
                "statistiche": statistiche,
                "totale_consumi": sum(s['totale_consumato'] for s in statistiche)
            }
            
            return [TextContent(type="text", text=json.dumps(response, indent=2))]
            
    except Exception as e:
        logger.error(f"Error in statistiche_consumi: {e}")
        return [TextContent(type="text", text=json.dumps({"success": False, "error": str(e)}))]

async def aggiornare_task_impl(arguments: dict, auth_info: dict, db_pool) -> List[TextContent]:
    """Modifica task esistente"""
    try:
        utente = auth_info.get('user_id', 'unknown')
        
        if not arguments.get('task_id'):
            raise ValueError("task_id è obbligatorio")
        
        async with db_pool.acquire() as conn:
            # Verifica esistenza
            task = await conn.fetchrow("SELECT * FROM task WHERE id = $1", arguments['task_id'])
            if not task:
                raise ValueError(f"Task con ID {arguments['task_id']} non trovato")
            
            # Costruisci update dinamico
            updates = []
            params = []
            param_count = 0
            
            update_fields = ['titolo', 'descrizione', 'priorita', 'stato', 'data_scadenza', 'assegnatario']
            
            for field in update_fields:
                if field in arguments and arguments[field] is not None:
                    param_count += 1
                    updates.append(f"{field} = ${param_count}")
                    
                    if field == 'data_scadenza':
                        params.append(datetime.strptime(arguments[field], '%Y-%m-%d').date())
                    else:
                        params.append(arguments[field])
            
            if not updates:
                raise ValueError("Nessun campo da aggiornare specificato")
            
            param_count += 1
            updates.append(f"modificato_da = ${param_count}")
            params.append(utente)
            
            param_count += 1
            params.append(arguments['task_id'])
            
            query = f"UPDATE task SET {', '.join(updates)} WHERE id = ${param_count} RETURNING *"
            result = await conn.fetchrow(query, *params)
            
            await log_operazione(
                db_pool, "AGGIORNAMENTO_TASK", "task", arguments['task_id'],
                {k: v for k, v in arguments.items() if k != 'task_id'}, utente
            )
            
            response = {
                "success": True,
                "message": f"Task '{result['titolo']}' aggiornato con successo",
                "task": {
                    "id": result['id'],
                    "titolo": result['titolo'],
                    "stato": result['stato'],
                    "priorita": result['priorita'],
                    "ultima_modifica": result['ultima_modifica'].isoformat()
                }
            }
            
            return [TextContent(type="text", text=json.dumps(response, indent=2))]
            
    except Exception as e:
        logger.error(f"Error in aggiornare_task: {e}")
        return [TextContent(type="text", text=json.dumps({"success": False, "error": str(e)}))]

async def cancellare_task_impl(arguments: dict, auth_info: dict, db_pool) -> List[TextContent]:
    """Cancella task (soft delete)"""
    try:
        utente = auth_info.get('user_id', 'unknown')
        
        if not arguments.get('task_id'):
            raise ValueError("task_id è obbligatorio")
        
        async with db_pool.acquire() as conn:
            task = await conn.fetchrow("SELECT * FROM task WHERE id = $1", arguments['task_id'])
            if not task:
                raise ValueError(f"Task con ID {arguments['task_id']} non trovato")
            
            await conn.execute(
                "UPDATE task SET stato = 'ANNULLATO', modificato_da = $1 WHERE id = $2",
                utente, arguments['task_id']
            )
            
            await log_operazione(
                db_pool, "CANCELLAZIONE_TASK", "task", arguments['task_id'],
                {"motivo": arguments.get('motivo_cancellazione')}, utente
            )
            
            response = {
                "success": True,
                "message": f"Task '{task['titolo']}' cancellato con successo"
            }
            
            return [TextContent(type="text", text=json.dumps(response, indent=2))]
            
    except Exception as e:
        logger.error(f"Error in cancellare_task: {e}")
        return [TextContent(type="text", text=json.dumps({"success": False, "error": str(e)}))]

async def statistiche_task_impl(arguments: dict, auth_info: dict, db_pool) -> List[TextContent]:
    """Statistiche task per periodo"""
    try:
        data_fine = datetime.strptime(arguments.get('data_fine', datetime.now().date().isoformat()), '%Y-%m-%d').date()
        data_inizio = datetime.strptime(arguments.get('data_inizio', (data_fine - timedelta(days=30)).isoformat()), '%Y-%m-%d').date()
        raggruppa_per = arguments.get('raggruppa_per', 'stato')
        
        async with db_pool.acquire() as conn:
            if raggruppa_per == 'stato':
                rows = await conn.fetch(
                    """
                    SELECT stato as gruppo, COUNT(*) as totale
                    FROM task 
                    WHERE data_creazione::date BETWEEN $1 AND $2
                    GROUP BY stato
                    ORDER BY totale DESC
                    """,
                    data_inizio, data_fine
                )
            elif raggruppa_per == 'priorita':
                rows = await conn.fetch(
                    """
                    SELECT priorita as gruppo, COUNT(*) as totale
                    FROM task 
                    WHERE data_creazione::date BETWEEN $1 AND $2
                    GROUP BY priorita
                    ORDER BY totale DESC
                    """,
                    data_inizio, data_fine
                )
            else:  # assegnatario
                rows = await conn.fetch(
                    """
                    SELECT COALESCE(assegnatario, 'NON_ASSEGNATO') as gruppo, COUNT(*) as totale
                    FROM task 
                    WHERE data_creazione::date BETWEEN $1 AND $2
                    GROUP BY assegnatario
                    ORDER BY totale DESC
                    """,
                    data_inizio, data_fine
                )
            
            statistiche = [{"gruppo": row['gruppo'], "totale": row['totale']} for row in rows]
            
            response = {
                "success": True,
                "parametri": {
                    "data_inizio": data_inizio.isoformat(),
                    "data_fine": data_fine.isoformat(),
                    "raggruppa_per": raggruppa_per
                },
                "statistiche": statistiche,
                "totale_task": sum(s['totale'] for s in statistiche)
            }
            
            return [TextContent(type="text", text=json.dumps(response, indent=2))]
            
    except Exception as e:
        logger.error(f"Error in statistiche_task: {e}")
        return [TextContent(type="text", text=json.dumps({"success": False, "error": str(e)}))]
