#!/usr/bin/env python3
"""
Tool functions for inventory management
Implements all magazzino-related MCP tools with full business logic
"""

import asyncio
import json
import logging
from datetime import datetime, date
from typing import Dict, List, Optional, Any
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

async def aggiungere_alimento_impl(arguments: dict, auth_info: dict, db_pool) -> List[TextContent]:
    """Inserisce un nuovo alimento nel magazzino"""
    try:
        utente = auth_info.get('user_id', 'unknown')
        
        # Validazione input
        required_fields = ['nome', 'quantita', 'unita_misura', 'categoria', 'ubicazione']
        for field in required_fields:
            if field not in arguments or arguments[field] is None:
                raise ValueError(f"Campo obbligatorio mancante: {field}")
        
        # Validazione enums
        valid_unita = ['PEZZI', 'KG', 'LITRI', 'GRAMMI']
        valid_categorie = ['LATTICINI', 'VERDURE', 'FRUTTA', 'CARNE', 'PESCE', 'CONSERVE', 'BEVANDE', 'ALTRO']
        valid_ubicazioni = ['FRIGO', 'FREEZER', 'DISPENSA', 'CANTINA']
        
        if arguments['unita_misura'] not in valid_unita:
            raise ValueError(f"Unità di misura non valida: {arguments['unita_misura']}")
        if arguments['categoria'] not in valid_categorie:
            raise ValueError(f"Categoria non valida: {arguments['categoria']}")
        if arguments['ubicazione'] not in valid_ubicazioni:
            raise ValueError(f"Ubicazione non valida: {arguments['ubicazione']}")
        
        if arguments['quantita'] <= 0:
            raise ValueError("La quantità deve essere maggiore di 0")
        
        # Validazione date
        data_scadenza = None
        data_apertura = None
        
        if 'data_scadenza' in arguments and arguments['data_scadenza']:
            try:
                data_scadenza = datetime.strptime(arguments['data_scadenza'], '%Y-%m-%d').date()
            except ValueError:
                raise ValueError("Formato data scadenza non valido (usa YYYY-MM-DD)")
        
        if 'data_apertura' in arguments and arguments['data_apertura']:
            try:
                data_apertura = datetime.strptime(arguments['data_apertura'], '%Y-%m-%d').date()
                if data_apertura > datetime.now().date():
                    raise ValueError("La data di apertura non può essere futura")
            except ValueError as e:
                if "non può essere futura" in str(e):
                    raise
                raise ValueError("Formato data apertura non valido (usa YYYY-MM-DD)")
        
        async with db_pool.acquire() as conn:
            # Inserimento nuovo alimento
            result = await conn.fetchrow(
                """
                INSERT INTO alimenti (
                    nome, quantita, unita_misura, data_scadenza, data_apertura, 
                    categoria, ubicazione, prezzo_acquisto, fornitore, lotto_acquisto, modificato_da
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                RETURNING id, nome, quantita, unita_misura, categoria, ubicazione, data_inserimento
                """,
                arguments['nome'],
                Decimal(str(arguments['quantita'])),
                arguments['unita_misura'],
                data_scadenza,
                data_apertura,
                arguments['categoria'],
                arguments['ubicazione'],
                Decimal(str(arguments['prezzo_acquisto'])) if arguments.get('prezzo_acquisto') else None,
                arguments.get('fornitore'),
                arguments.get('lotto_acquisto'),
                utente
            )
            
            # Log dell'operazione
            await log_operazione(
                db_pool,
                "INSERIMENTO_ALIMENTO",
                "alimenti",
                result['id'],
                {
                    "nome": result['nome'],
                    "quantita": float(result['quantita']),
                    "categoria": result['categoria'],
                    "ubicazione": result['ubicazione']
                },
                utente
            )
            
            response = {
                "success": True,
                "message": f"Alimento '{result['nome']}' aggiunto con successo",
                "alimento": {
                    "id": result['id'],
                    "nome": result['nome'],
                    "quantita": float(result['quantita']),
                    "unita_misura": result['unita_misura'],
                    "categoria": result['categoria'],
                    "ubicazione": result['ubicazione'],
                    "data_inserimento": result['data_inserimento'].isoformat()
                }
            }
            
            return [TextContent(type="text", text=json.dumps(response, indent=2))]
            
    except Exception as e:
        logger.error(f"Error in aggiungere_alimento: {e}")
        return [TextContent(type="text", text=json.dumps({
            "success": False,
            "error": str(e)
        }))]

async def consultare_giacenze_impl(arguments: dict, auth_info: dict, db_pool) -> List[TextContent]:
    """Visualizza le giacenze con filtri"""
    try:
        utente = auth_info.get('user_id', 'unknown')
        
        # Costruzione query dinamica
        base_query = """
            SELECT id, nome, quantita, unita_misura, data_scadenza, categoria, ubicazione,
                   prezzo_acquisto, fornitore, data_inserimento, ultima_modifica,
                   CASE 
                       WHEN data_scadenza IS NOT NULL THEN (data_scadenza - CURRENT_DATE)
                       ELSE NULL 
                   END as giorni_alla_scadenza
            FROM alimenti 
            WHERE quantita > 0
        """
        
        conditions = []
        params = []
        param_count = 0
        
        if arguments.get('categoria'):
            param_count += 1
            conditions.append(f"categoria = ${param_count}")
            params.append(arguments['categoria'])
        
        if arguments.get('ubicazione'):
            param_count += 1
            conditions.append(f"ubicazione = ${param_count}")
            params.append(arguments['ubicazione'])
        
        if arguments.get('quantita_minima'):
            param_count += 1
            conditions.append(f"quantita >= ${param_count}")
            params.append(Decimal(str(arguments['quantita_minima'])))
        
        if arguments.get('in_scadenza_giorni'):
            param_count += 1
            conditions.append(f"data_scadenza IS NOT NULL AND data_scadenza <= CURRENT_DATE + INTERVAL '{arguments['in_scadenza_giorni']} days'")
        
        if conditions:
            base_query += " AND " + " AND ".join(conditions)
        
        base_query += " ORDER BY data_scadenza ASC NULLS LAST, nome ASC"
        
        limit = arguments.get('limit', 50)
        param_count += 1
        base_query += f" LIMIT ${param_count}"
        params.append(limit)
        
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(base_query, *params)
            
            giacenze = []
            for row in rows:
                giacenza = {
                    "id": row['id'],
                    "nome": row['nome'],
                    "quantita": float(row['quantita']),
                    "unita_misura": row['unita_misura'],
                    "categoria": row['categoria'],
                    "ubicazione": row['ubicazione'],
                    "data_scadenza": row['data_scadenza'].isoformat() if row['data_scadenza'] else None,
                    "giorni_alla_scadenza": row['giorni_alla_scadenza'],
                    "prezzo_acquisto": float(row['prezzo_acquisto']) if row['prezzo_acquisto'] else None,
                    "fornitore": row['fornitore'],
                    "data_inserimento": row['data_inserimento'].isoformat(),
                    "ultima_modifica": row['ultima_modifica'].isoformat()
                }
                
                # Aggiungi alert per scadenze
                if row['giorni_alla_scadenza'] is not None:
                    if row['giorni_alla_scadenza'] < 0:
                        giacenza['alert'] = "SCADUTO"
                    elif row['giorni_alla_scadenza'] <= 3:
                        giacenza['alert'] = "IN_SCADENZA"
                
                giacenze.append(giacenza)
            
            # Statistiche riassuntive
            stats_query = """
                SELECT 
                    COUNT(*) as totale_prodotti,
                    SUM(CASE WHEN data_scadenza IS NOT NULL AND data_scadenza <= CURRENT_DATE THEN 1 ELSE 0 END) as scaduti,
                    SUM(CASE WHEN data_scadenza IS NOT NULL AND data_scadenza <= CURRENT_DATE + INTERVAL '3 days' AND data_scadenza > CURRENT_DATE THEN 1 ELSE 0 END) as in_scadenza,
                    COUNT(DISTINCT categoria) as categorie_diverse,
                    COUNT(DISTINCT ubicazione) as ubicazioni_diverse
                FROM alimenti WHERE quantita > 0
            """
            
            if conditions:
                stats_query = stats_query.replace("WHERE quantita > 0", "WHERE quantita > 0 AND " + " AND ".join(conditions[:-1]))  # Remove limit condition
            
            stats_row = await conn.fetchrow(stats_query, *params[:-1])  # Remove limit param
            
            response = {
                "success": True,
                "giacenze": giacenze,
                "statistiche": {
                    "totale_prodotti": stats_row['totale_prodotti'],
                    "scaduti": stats_row['scaduti'],
                    "in_scadenza_3_giorni": stats_row['in_scadenza'],
                    "categorie_diverse": stats_row['categorie_diverse'],
                    "ubicazioni_diverse": stats_row['ubicazioni_diverse']
                },
                "filtri_applicati": {k: v for k, v in arguments.items() if v is not None},
                "risultati_mostrati": len(giacenze)
            }
            
            return [TextContent(type="text", text=json.dumps(response, indent=2))]
            
    except Exception as e:
        logger.error(f"Error in consultare_giacenze: {e}")
        return [TextContent(type="text", text=json.dumps({
            "success": False,
            "error": str(e)
        }))]

async def scaricare_alimento_impl(arguments: dict, auth_info: dict, db_pool) -> List[TextContent]:
    """Registra il consumo di un alimento con controllo quantità"""
    try:
        utente = auth_info.get('user_id', 'unknown')
        
        # Validazione input
        if not arguments.get('alimento_id') or not arguments.get('quantita_consumata'):
            raise ValueError("alimento_id e quantita_consumata sono obbligatori")
        
        if arguments['quantita_consumata'] <= 0:
            raise ValueError("La quantità consumata deve essere maggiore di 0")
        
        async with db_pool.acquire() as conn:
            # Verifica esistenza e quantità disponibile
            alimento = await conn.fetchrow(
                "SELECT id, nome, quantita, unita_misura, categoria, ubicazione FROM alimenti WHERE id = $1",
                arguments['alimento_id']
            )
            
            if not alimento:
                raise ValueError(f"Alimento con ID {arguments['alimento_id']} non trovato")
            
            quantita_richiesta = Decimal(str(arguments['quantita_consumata']))
            quantita_disponibile = alimento['quantita']
            
            # Controllo quantità disponibile
            if quantita_richiesta > quantita_disponibile and not arguments.get('forza_scarico', False):
                return [TextContent(type="text", text=json.dumps({
                    "success": False,
                    "warning": "QUANTITA_INSUFFICIENTE",
                    "message": f"Quantità richiesta ({float(quantita_richiesta)}) maggiore della disponibile ({float(quantita_disponibile)})",
                    "quantita_disponibile": float(quantita_disponibile),
                    "quantita_richiesta": float(quantita_richiesta),
                    "suggerimento": "Usa 'forza_scarico': true per procedere comunque"
                }))]
            
            # Registra il consumo
            await conn.execute(
                """
                INSERT INTO consumi_alimenti (alimento_id, quantita_consumata, motivo, note)
                VALUES ($1, $2, $3, $4)
                """,
                arguments['alimento_id'],
                quantita_richiesta,
                arguments.get('motivo', 'CONSUMATO'),
                arguments.get('note')
            )
            
            # Aggiorna la quantità nell'inventario
            nuova_quantita = max(Decimal('0'), quantita_disponibile - quantita_richiesta)
            await conn.execute(
                "UPDATE alimenti SET quantita = $1, modificato_da = $2 WHERE id = $3",
                nuova_quantita,
                utente,
                arguments['alimento_id']
            )
            
            # Log dell'operazione
            await log_operazione(
                db_pool,
                "SCARICO_ALIMENTO",
                "alimenti",
                arguments['alimento_id'],
                {
                    "quantita_prima": float(quantita_disponibile),
                    "quantita_consumata": float(quantita_richiesta),
                    "quantita_dopo": float(nuova_quantita),
                    "motivo": arguments.get('motivo', 'CONSUMATO'),
                    "forzato": arguments.get('forza_scarico', False)
                },
                utente
            )
            
            response = {
                "success": True,
                "message": f"Scaricato {float(quantita_richiesta)} {alimento['unita_misura']} di {alimento['nome']}",
                "alimento": {
                    "id": alimento['id'],
                    "nome": alimento['nome'],
                    "quantita_prima": float(quantita_disponibile),
                    "quantita_consumata": float(quantita_richiesta),
                    "quantita_dopo": float(nuova_quantita),
                    "unita_misura": alimento['unita_misura']
                },
                "dettagli_consumo": {
                    "motivo": arguments.get('motivo', 'CONSUMATO'),
                    "note": arguments.get('note'),
                    "data_consumo": datetime.now().isoformat()
                }
            }
            
            # Avviso se quantità è finita
            if nuova_quantita == 0:
                response['warning'] = "QUANTITA_ESAURITA"
                response['message'] += " - PRODOTTO ESAURITO"
            
            return [TextContent(type="text", text=json.dumps(response, indent=2))]
            
    except Exception as e:
        logger.error(f"Error in scaricare_alimento: {e}")
        return [TextContent(type="text", text=json.dumps({
            "success": False,
            "error": str(e)
        }))]

async def notifiche_scadenza_impl(arguments: dict, auth_info: dict, db_pool) -> List[TextContent]:
    """Restituisce alimenti in scadenza entro X giorni"""
    try:
        giorni_limite = arguments.get('giorni_limite', 3)
        
        async with db_pool.acquire() as conn:
            # Usa la funzione database ottimizzata
            query = "SELECT * FROM alimenti_in_scadenza($1)"
            params = [giorni_limite]
            
            # Aggiungi filtri se specificati
            if arguments.get('categoria') or arguments.get('ubicazione'):
                base_query = """
                    SELECT a.* FROM alimenti_in_scadenza($1) a
                    JOIN alimenti al ON a.id = al.id
                    WHERE 1=1
                """
                if arguments.get('categoria'):
                    base_query += " AND al.categoria = $2"
                    params.append(arguments['categoria'])
                if arguments.get('ubicazione'):
                    if arguments.get('categoria'):
                        base_query += " AND al.ubicazione = $3"
                        params.append(arguments['ubicazione'])
                    else:
                        base_query += " AND al.ubicazione = $2"
                        params.append(arguments['ubicazione'])
                query = base_query
            
            rows = await conn.fetch(query, *params)
            
            alimenti_scadenza = []
            for row in rows:
                item = {
                    "id": row['id'],
                    "nome": row['nome'],
                    "quantita": float(row['quantita']),
                    "unita_misura": row['unita_misura'],
                    "data_scadenza": row['data_scadenza'].isoformat(),
                    "giorni_alla_scadenza": row['giorni_alla_scadenza'],
                    "categoria": row['categoria'],
                    "ubicazione": row['ubicazione']
                }
                
                # Priorità basata sui giorni alla scadenza
                if row['giorni_alla_scadenza'] < 0:
                    item['priorita'] = "CRITICA_SCADUTO"
                elif row['giorni_alla_scadenza'] == 0:
                    item['priorita'] = "ALTA_SCADE_OGGI"
                elif row['giorni_alla_scadenza'] <= 1:
                    item['priorita'] = "ALTA_SCADE_DOMANI"
                else:
                    item['priorita'] = "MEDIA"
                
                alimenti_scadenza.append(item)
            
            # Raggruppa per priorità
            raggruppati = {}
            for item in alimenti_scadenza:
                priorita = item['priorita']
                if priorita not in raggruppati:
                    raggruppati[priorita] = []
                raggruppati[priorita].append(item)
            
            response = {
                "success": True,
                "parametri": {
                    "giorni_limite": giorni_limite,
                    "categoria_filtro": arguments.get('categoria'),
                    "ubicazione_filtro": arguments.get('ubicazione')
                },
                "totale_prodotti": len(alimenti_scadenza),
                "alimenti_per_priorita": raggruppati,
                "tutti_alimenti": alimenti_scadenza,
                "data_controllo": datetime.now().isoformat()
            }
            
            return [TextContent(type="text", text=json.dumps(response, indent=2))]
            
    except Exception as e:
        logger.error(f"Error in notifiche_scadenza: {e}")
        return [TextContent(type="text", text=json.dumps({
            "success": False,
            "error": str(e)
        }))]
