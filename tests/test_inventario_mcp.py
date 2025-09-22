"""
Test completi per il server MCP Inventario
Compatibili con CI/CD pipeline
"""

import asyncio
import os
import pytest
import pytest_asyncio
from datetime import datetime, date, timedelta
from decimal import Decimal
from httpx import AsyncClient
import asyncpg
from fastapi.testclient import TestClient

# Import del server
import sys
sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from server_complete import app, DatabaseConfig, db_pool

# Configurazione test database
TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL", "postgresql://test_user:test_pass@localhost/test_inventario_db")
TEST_API_KEY = "test-api-key-123"

class TestConfig:
    """Configurazione per i test"""
    
    @staticmethod
    async def setup_test_db():
        """Configura database di test"""
        # Connessione per creare il database di test
        conn = await asyncpg.connect(TEST_DATABASE_URL.rsplit('/', 1)[0] + '/postgres')
        try:
            await conn.execute("DROP DATABASE IF EXISTS test_inventario_db")
            await conn.execute("CREATE DATABASE test_inventario_db")
        except:
            pass  # Database potrebbe già esistere
        finally:
            await conn.close()
        
        # Connessione al database di test per creare lo schema
        conn = await asyncpg.connect(TEST_DATABASE_URL)
        try:
            # Esegui schema di test (versione semplificata)
            await conn.execute("""
                CREATE TYPE IF NOT EXISTS unita_misura AS ENUM ('PEZZI', 'KG', 'LITRI', 'GRAMMI');
                CREATE TYPE IF NOT EXISTS categoria_alimenti AS ENUM ('LATTICINI', 'VERDURE', 'FRUTTA', 'CARNE', 'PESCE', 'CONSERVE', 'BEVANDE', 'ALTRO');
                CREATE TYPE IF NOT EXISTS ubicazione AS ENUM ('FRIGO', 'FREEZER', 'DISPENSA', 'CANTINA');
                CREATE TYPE IF NOT EXISTS priorita_task AS ENUM ('ALTA', 'MEDIA', 'BASSA');
                CREATE TYPE IF NOT EXISTS stato_task AS ENUM ('DA_FARE', 'IN_CORSO', 'COMPLETATO', 'ANNULLATO');
                CREATE TYPE IF NOT EXISTS frequenza_ricorrenza AS ENUM ('GIORNALIERA', 'SETTIMANALE', 'MENSILE');
                CREATE TYPE IF NOT EXISTS motivo_consumo AS ENUM ('CONSUMATO', 'SCADUTO', 'BUTTATO');
            """)
            
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS alimenti (
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
                    modificato_da VARCHAR(100) NOT NULL
                );
            """)
            
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS task (
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
                    task_padre_id INTEGER
                );
            """)
            
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS log_operazioni (
                    id SERIAL PRIMARY KEY,
                    tipo_operazione VARCHAR(100) NOT NULL,
                    tabella VARCHAR(50) NOT NULL,
                    id_record INTEGER NOT NULL,
                    dettagli JSONB,
                    utente VARCHAR(100) NOT NULL,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
                );
            """)
            
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS consumi_alimenti (
                    id SERIAL PRIMARY KEY,
                    alimento_id INTEGER NOT NULL REFERENCES alimenti(id) ON DELETE CASCADE,
                    quantita_consumata DECIMAL(10,3) NOT NULL CHECK (quantita_consumata > 0),
                    data_consumo TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
                    motivo motivo_consumo NOT NULL DEFAULT 'CONSUMATO',
                    note TEXT
                );
            """)
            
        finally:
            await conn.close()
    
    @staticmethod
    async def cleanup_test_db():
        """Pulisce il database di test"""
        conn = await asyncpg.connect(TEST_DATABASE_URL)
        try:
            await conn.execute("TRUNCATE alimenti, task, log_operazioni, consumi_alimenti RESTART IDENTITY CASCADE")
        finally:
            await conn.close()

@pytest_asyncio.fixture(scope="session")
async def setup_test_environment():
    """Setup dell'ambiente di test"""
    # Configura variabili d'ambiente per i test
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL
    os.environ["API_KEY"] = TEST_API_KEY
    
    await TestConfig.setup_test_db()
    yield
    # Cleanup finale se necessario

@pytest_asyncio.fixture
async def client(setup_test_environment):
    """Client HTTP per i test"""
    await TestConfig.cleanup_test_db()
    async with AsyncClient(app=app, base_url="http://test") as ac:
        yield ac

@pytest.fixture
def auth_headers():
    """Headers di autenticazione per i test"""
    return {"Authorization": f"Bearer {TEST_API_KEY}"}

class TestAlimenti:
    """Test per la gestione alimenti"""
    
    @pytest.mark.asyncio
    async def test_create_alimento_rest(self, client: AsyncClient, auth_headers):
        """Test creazione alimento via REST API"""
        alimento_data = {
            "nome": "Latte Intero",
            "quantita": 2.0,
            "unita_misura": "LITRI", 
            "categoria": "LATTICINI",
            "ubicazione": "FRIGO",
            "data_scadenza": "2024-12-31",
            "prezzo_acquisto": 1.50,
            "fornitore": "Centrale del Latte"
        }
        
        response = await client.post("/api/alimenti", json=alimento_data, headers=auth_headers)
        assert response.status_code == 200
        
        data = response.json()
        assert "id" in data
        assert data["status"] == "created"
        assert "created_at" in data
    
    @pytest.mark.asyncio
    async def test_list_alimenti_rest(self, client: AsyncClient, auth_headers):
        """Test lista alimenti via REST API"""
        # Prima crea alcuni alimenti
        alimenti_test = [
            {
                "nome": "Pane", "quantita": 1, "unita_misura": "PEZZI",
                "categoria": "ALTRO", "ubicazione": "DISPENSA"
            },
            {
                "nome": "Pomodori", "quantita": 2.5, "unita_misura": "KG", 
                "categoria": "VERDURE", "ubicazione": "FRIGO"
            }
        ]
        
        for alimento in alimenti_test:
            await client.post("/api/alimenti", json=alimento, headers=auth_headers)
        
        # Test lista completa
        response = await client.get("/api/alimenti", headers=auth_headers)
        assert response.status_code == 200
        
        data = response.json()
        assert "alimenti" in data
        assert data["count"] >= 2
        assert len(data["alimenti"]) >= 2
        
        # Test filtro per categoria
        response = await client.get("/api/alimenti?categoria=VERDURE", headers=auth_headers)
        assert response.status_code == 200
        
        data = response.json()
        assert data["count"] >= 1
        verdure = [a for a in data["alimenti"] if a["categoria"] == "VERDURE"]
        assert len(verdure) >= 1
    
    @pytest.mark.asyncio
    async def test_create_alimento_validation_error(self, client: AsyncClient, auth_headers):
        """Test validazione errori nella creazione alimenti"""
        # Test unità di misura non valida
        alimento_invalid = {
            "nome": "Test",
            "quantita": 1.0,
            "unita_misura": "INVALID",
            "categoria": "ALTRO",
            "ubicazione": "DISPENSA"
        }
        
        response = await client.post("/api/alimenti", json=alimento_invalid, headers=auth_headers)
        assert response.status_code == 422  # Validation error
        
        # Test quantità negativa
        alimento_invalid2 = {
            "nome": "Test",
            "quantita": -1.0,
            "unita_misura": "KG",
            "categoria": "ALTRO", 
            "ubicazione": "DISPENSA"
        }
        
        response = await client.post("/api/alimenti", json=alimento_invalid2, headers=auth_headers)
        assert response.status_code == 422

class TestAuthentication:
    """Test per l'autenticazione"""
    
    @pytest.mark.asyncio
    async def test_no_auth_header(self, client: AsyncClient):
        """Test richiesta senza header di autenticazione"""
        response = await client.get("/api/alimenti")
        assert response.status_code == 401
    
    @pytest.mark.asyncio 
    async def test_invalid_api_key(self, client: AsyncClient):
        """Test con API key non valida"""
        headers = {"Authorization": "Bearer wrong-key"}
        response = await client.get("/api/alimenti", headers=headers)
        assert response.status_code == 401
    
    @pytest.mark.asyncio
    async def test_valid_auth_formats(self, client: AsyncClient):
        """Test formati di autenticazione validi"""
        # Test formato Bearer
        headers1 = {"Authorization": f"Bearer {TEST_API_KEY}"}
        response = await client.get("/api/alimenti", headers=headers1)
        assert response.status_code == 200
        
        # Test formato semplice
        headers2 = {"Authorization": TEST_API_KEY}
        response = await client.get("/api/alimenti", headers=headers2)
        assert response.status_code == 200

class TestHealthCheck:
    """Test per health check"""
    
    @pytest.mark.asyncio
    async def test_health_check_endpoint(self, client: AsyncClient):
        """Test endpoint health check"""
        response = await client.get("/health")
        assert response.status_code == 200
        
        data = response.json()
        assert data["status"] == "healthy"
        assert data["database"] == "connected"
        assert "timestamp" in data
    
    @pytest.mark.asyncio
    async def test_root_endpoint(self, client: AsyncClient):
        """Test endpoint root"""
        response = await client.get("/")
        assert response.status_code == 200
        
        data = response.json()
        assert "message" in data
        assert "version" in data
        assert "endpoints" in data

class TestDatabaseOperations:
    """Test per operazioni database dirette"""
    
    @pytest.mark.asyncio
    async def test_database_connection(self):
        """Test connessione database"""
        conn = await asyncpg.connect(TEST_DATABASE_URL)
        try:
            result = await conn.fetchval("SELECT 1")
            assert result == 1
        finally:
            await conn.close()
    
    @pytest.mark.asyncio
    async def test_insert_and_query_alimento(self):
        """Test inserimento e query diretta alimento"""
        conn = await asyncpg.connect(TEST_DATABASE_URL)
        try:
            # Insert
            alimento_id = await conn.fetchval("""
                INSERT INTO alimenti (nome, quantita, unita_misura, categoria, ubicazione, modificato_da)
                VALUES ($1, $2, $3, $4, $5, $6) RETURNING id
            """, "Test Alimento", 5.0, "KG", "VERDURE", "DISPENSA", "test_user")
            
            assert alimento_id is not None
            
            # Query
            alimento = await conn.fetchrow("SELECT * FROM alimenti WHERE id = $1", alimento_id)
            assert alimento is not None
            assert alimento['nome'] == "Test Alimento"
            assert float(alimento['quantita']) == 5.0
            
        finally:
            await conn.close()
    
    @pytest.mark.asyncio
    async def test_insert_and_query_task(self):
        """Test inserimento e query task"""
        conn = await asyncpg.connect(TEST_DATABASE_URL)
        try:
            # Insert
            task_id = await conn.fetchval("""
                INSERT INTO task (titolo, priorita, creato_da, modificato_da)
                VALUES ($1, $2, $3, $3) RETURNING id
            """, "Test Task", "ALTA", "test_user")
            
            assert task_id is not None
            
            # Query
            task = await conn.fetchrow("SELECT * FROM task WHERE id = $1", task_id)
            assert task is not None
            assert task['titolo'] == "Test Task"
            assert task['priorita'] == "ALTA"
            assert task['stato'] == "DA_FARE"  # Default
            
        finally:
            await conn.close()

class TestPerformance:
    """Test di performance"""
    
    @pytest.mark.asyncio
    async def test_bulk_insert_performance(self):
        """Test performance inserimenti multipli"""
        conn = await asyncpg.connect(TEST_DATABASE_URL)
        try:
            start_time = datetime.now()
            
            # Inserisci 100 alimenti
            for i in range(100):
                await conn.execute("""
                    INSERT INTO alimenti (nome, quantita, unita_misura, categoria, ubicazione, modificato_da)
                    VALUES ($1, $2, $3, $4, $5, $6)
                """, f"Alimento Test {i}", 1.0, "PEZZI", "ALTRO", "DISPENSA", "performance_test")
            
            duration = (datetime.now() - start_time).total_seconds()
            
            # Dovrebbe completare in meno di 5 secondi
            assert duration < 5.0, f"Inserimenti troppo lenti: {duration}s"
            
            # Verifica conteggio
            count = await conn.fetchval("SELECT COUNT(*) FROM alimenti WHERE modificato_da = 'performance_test'")
            assert count == 100
            
        finally:
            await conn.close()

if __name__ == "__main__":
    # Esegui test con pytest
    pytest.main([
        __file__,
        "-v",  # Verbose
        "-s",  # No capture (mostra print)
        "--asyncio-mode=auto",  # Modo asyncio automatico
        "--tb=short"  # Traceback corto
    ])
