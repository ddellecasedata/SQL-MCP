-- Schema completo del database per gestione inventario e task management
-- Creazione ENUM types

-- ENUM per unità di misura alimenti
CREATE TYPE unita_misura AS ENUM ('PEZZI', 'KG', 'LITRI', 'GRAMMI');

-- ENUM per categoria alimenti
CREATE TYPE categoria_alimenti AS ENUM ('LATTICINI', 'VERDURE', 'FRUTTA', 'CARNE', 'PESCE', 'CONSERVE', 'BEVANDE', 'ALTRO');

-- ENUM per ubicazione alimenti
CREATE TYPE ubicazione AS ENUM ('FRIGO', 'FREEZER', 'DISPENSA', 'CANTINA');

-- ENUM per priorità task
CREATE TYPE priorita_task AS ENUM ('ALTA', 'MEDIA', 'BASSA');

-- ENUM per stato task
CREATE TYPE stato_task AS ENUM ('DA_FARE', 'IN_CORSO', 'COMPLETATO', 'ANNULLATO');

-- ENUM per frequenza ricorrenza task
CREATE TYPE frequenza_ricorrenza AS ENUM ('GIORNALIERA', 'SETTIMANALE', 'MENSILE');

-- ENUM per motivo consumo alimenti
CREATE TYPE motivo_consumo AS ENUM ('CONSUMATO', 'SCADUTO', 'BUTTATO');

-- Tabella Alimenti
CREATE TABLE alimenti (
    id SERIAL PRIMARY KEY,
    nome VARCHAR(255) NOT NULL,
    quantita DECIMAL(10,3) NOT NULL CHECK (quantita >= 0),
    unita_misura unita_misura NOT NULL,
    data_scadenza DATE,
    data_apertura DATE,
    categoria categoria_alimenti NOT NULL,
    ubicazione ubicazione NOT NULL,
    prezzo_acquisto DECIMAL(10,2),
    fornitore VARCHAR(255),
    lotto_acquisto VARCHAR(100),
    data_inserimento TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    ultima_modifica TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    modificato_da VARCHAR(100) NOT NULL,
    CONSTRAINT check_data_apertura CHECK (data_apertura IS NULL OR data_apertura >= data_inserimento::date),
    CONSTRAINT check_prezzo_positivo CHECK (prezzo_acquisto IS NULL OR prezzo_acquisto >= 0)
);

-- Tabella Task
CREATE TABLE task (
    id SERIAL PRIMARY KEY,
    titolo VARCHAR(500) NOT NULL,
    descrizione TEXT,
    priorita priorita_task NOT NULL DEFAULT 'MEDIA',
    stato stato_task NOT NULL DEFAULT 'DA_FARE',
    data_scadenza DATE,
    assegnatario VARCHAR(100),
    task_ricorrente BOOLEAN DEFAULT FALSE NOT NULL,
    frequenza_ricorrenza frequenza_ricorrenza,
    creato_da VARCHAR(100) NOT NULL,
    data_creazione TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    modificato_da VARCHAR(100) NOT NULL,
    ultima_modifica TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    task_padre_id INTEGER REFERENCES task(id),
    CONSTRAINT check_ricorrenza_frequenza CHECK (
        (task_ricorrente = FALSE AND frequenza_ricorrenza IS NULL) OR
        (task_ricorrente = TRUE AND frequenza_ricorrenza IS NOT NULL)
    )
);

-- Tabella Log Operazioni
CREATE TABLE log_operazioni (
    id SERIAL PRIMARY KEY,
    tipo_operazione VARCHAR(100) NOT NULL,
    tabella VARCHAR(50) NOT NULL,
    id_record INTEGER NOT NULL,
    dettagli JSONB,
    utente VARCHAR(100) NOT NULL,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
);

-- Tabella Consumi Alimenti
CREATE TABLE consumi_alimenti (
    id SERIAL PRIMARY KEY,
    alimento_id INTEGER NOT NULL REFERENCES alimenti(id) ON DELETE CASCADE,
    quantita_consumata DECIMAL(10,3) NOT NULL CHECK (quantita_consumata > 0),
    data_consumo TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    motivo motivo_consumo NOT NULL DEFAULT 'CONSUMATO',
    note TEXT
);

-- INDICI per ottimizzare le query più frequenti

-- Indici per tabella alimenti
CREATE INDEX idx_alimenti_categoria ON alimenti(categoria);
CREATE INDEX idx_alimenti_ubicazione ON alimenti(ubicazione);
CREATE INDEX idx_alimenti_data_scadenza ON alimenti(data_scadenza);
CREATE INDEX idx_alimenti_nome ON alimenti(nome);
CREATE INDEX idx_alimenti_quantita ON alimenti(quantita);

-- Indici per tabella task
CREATE INDEX idx_task_stato ON task(stato);
CREATE INDEX idx_task_priorita ON task(priorita);
CREATE INDEX idx_task_data_scadenza ON task(data_scadenza);
CREATE INDEX idx_task_assegnatario ON task(assegnatario);
CREATE INDEX idx_task_ricorrente ON task(task_ricorrente);
CREATE INDEX idx_task_creato_da ON task(creato_da);

-- Indici per tabella log_operazioni
CREATE INDEX idx_log_timestamp ON log_operazioni(timestamp);
CREATE INDEX idx_log_tipo_operazione ON log_operazioni(tipo_operazione);
CREATE INDEX idx_log_tabella ON log_operazioni(tabella);
CREATE INDEX idx_log_utente ON log_operazioni(utente);

-- Indici per tabella consumi_alimenti
CREATE INDEX idx_consumi_alimento_id ON consumi_alimenti(alimento_id);
CREATE INDEX idx_consumi_data ON consumi_alimenti(data_consumo);
CREATE INDEX idx_consumi_motivo ON consumi_alimenti(motivo);

-- TRIGGER per aggiornare automaticamente ultima_modifica

-- Funzione per aggiornare timestamp ultima_modifica
CREATE OR REPLACE FUNCTION update_ultima_modifica()
RETURNS TRIGGER AS $$
BEGIN
    NEW.ultima_modifica = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger per tabella alimenti
CREATE TRIGGER trigger_alimenti_ultima_modifica
    BEFORE UPDATE ON alimenti
    FOR EACH ROW
    EXECUTE FUNCTION update_ultima_modifica();

-- Trigger per tabella task
CREATE TRIGGER trigger_task_ultima_modifica
    BEFORE UPDATE ON task
    FOR EACH ROW
    EXECUTE FUNCTION update_ultima_modifica();

-- FUNZIONI UTILITY

-- Funzione per calcolare alimenti in scadenza
CREATE OR REPLACE FUNCTION alimenti_in_scadenza(giorni_limite INTEGER DEFAULT 3)
RETURNS TABLE (
    id INTEGER,
    nome VARCHAR(255),
    quantita DECIMAL(10,3),
    unita_misura unita_misura,
    data_scadenza DATE,
    giorni_alla_scadenza INTEGER,
    categoria categoria_alimenti,
    ubicazione ubicazione
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        a.id,
        a.nome,
        a.quantita,
        a.unita_misura,
        a.data_scadenza,
        (a.data_scadenza - CURRENT_DATE)::INTEGER as giorni_alla_scadenza,
        a.categoria,
        a.ubicazione
    FROM alimenti a
    WHERE a.data_scadenza IS NOT NULL 
    AND a.data_scadenza <= CURRENT_DATE + INTERVAL '1 day' * giorni_limite
    AND a.quantita > 0
    ORDER BY a.data_scadenza ASC;
END;
$$ LANGUAGE plpgsql;

-- Funzione per generare statistiche consumi
CREATE OR REPLACE FUNCTION statistiche_consumi(
    data_inizio DATE DEFAULT CURRENT_DATE - INTERVAL '30 days',
    data_fine DATE DEFAULT CURRENT_DATE,
    gruppo_per VARCHAR(20) DEFAULT 'categoria'
)
RETURNS TABLE (
    gruppo VARCHAR(255),
    totale_consumato DECIMAL(15,3),
    numero_operazioni BIGINT,
    media_giornaliera DECIMAL(15,3)
) AS $$
DECLARE
    giorni_periodo INTEGER;
BEGIN
    giorni_periodo := (data_fine - data_inizio) + 1;
    
    IF gruppo_per = 'categoria' THEN
        RETURN QUERY
        SELECT 
            a.categoria::VARCHAR(255) as gruppo,
            SUM(c.quantita_consumata) as totale_consumato,
            COUNT(*) as numero_operazioni,
            ROUND(SUM(c.quantita_consumata) / giorni_periodo, 3) as media_giornaliera
        FROM consumi_alimenti c
        JOIN alimenti a ON c.alimento_id = a.id
        WHERE c.data_consumo::DATE BETWEEN data_inizio AND data_fine
        GROUP BY a.categoria
        ORDER BY totale_consumato DESC;
    ELSIF gruppo_per = 'motivo' THEN
        RETURN QUERY
        SELECT 
            c.motivo::VARCHAR(255) as gruppo,
            SUM(c.quantita_consumata) as totale_consumato,
            COUNT(*) as numero_operazioni,
            ROUND(SUM(c.quantita_consumata) / giorni_periodo, 3) as media_giornaliera
        FROM consumi_alimenti c
        WHERE c.data_consumo::DATE BETWEEN data_inizio AND data_fine
        GROUP BY c.motivo
        ORDER BY totale_consumato DESC;
    ELSE
        RETURN QUERY
        SELECT 
            'TOTALE'::VARCHAR(255) as gruppo,
            SUM(c.quantita_consumata) as totale_consumato,
            COUNT(*) as numero_operazioni,
            ROUND(SUM(c.quantita_consumata) / giorni_periodo, 3) as media_giornaliera
        FROM consumi_alimenti c
        WHERE c.data_consumo::DATE BETWEEN data_inizio AND data_fine;
    END IF;
END;
$$ LANGUAGE plpgsql;

-- Dati di esempio per testing (opzionali)
-- INSERT INTO alimenti (nome, quantita, unita_misura, data_scadenza, categoria, ubicazione, modificato_da)
-- VALUES 
--     ('Latte Intero', 2.0, 'LITRI', '2024-01-15', 'LATTICINI', 'FRIGO', 'system'),
--     ('Pomodori San Marzano', 3.0, 'KG', '2024-01-20', 'VERDURE', 'DISPENSA', 'system'),
--     ('Petto di Pollo', 1.5, 'KG', '2024-01-12', 'CARNE', 'FRIGO', 'system');

-- COMMENTI
-- Schema ottimizzato per:
-- 1. Prestazioni con indici su campi più utilizzati
-- 2. Integrità referenziale con foreign keys
-- 3. Validazione dati con constraints e check
-- 4. Audit trail completo con log_operazioni
-- 5. Funzioni utility per query complesse
-- 6. Trigger automatici per timestamp
