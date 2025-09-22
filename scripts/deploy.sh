#!/bin/bash
# Script di deployment per Server MCP Inventario

set -e

echo "🚀 Deployment Server MCP Inventario"
echo "=================================="

# Verifica prerequisiti
check_requirements() {
    echo "📋 Verifica prerequisiti..."
    
    if ! command -v python3 &> /dev/null; then
        echo "❌ Python 3 non trovato"
        exit 1
    fi
    
    if ! command -v git &> /dev/null; then
        echo "❌ Git non trovato"
        exit 1
    fi
    
    echo "✅ Prerequisiti verificati"
}

# Setup ambiente locale
setup_local() {
    echo "🔧 Setup ambiente locale..."
    
    # Crea environment virtuale se non esiste
    if [ ! -d "venv" ]; then
        python3 -m venv venv
        echo "✅ Ambiente virtuale creato"
    fi
    
    # Attiva environment
    source venv/bin/activate
    
    # Installa dipendenze
    pip install --upgrade pip
    pip install -r requirements.txt
    
    echo "✅ Dipendenze installate"
}

# Setup database
setup_database() {
    echo "🗄️  Setup database..."
    
    if [ -z "$DATABASE_URL" ]; then
        echo "⚠️  DATABASE_URL non configurata, usando default locale"
        export DATABASE_URL="postgresql://user:password@localhost/inventario_db"
    fi
    
    # Verifica se PostgreSQL è in esecuzione
    if ! pg_isready &> /dev/null; then
        echo "❌ PostgreSQL non è in esecuzione"
        echo "💡 Avvialo con: brew services start postgresql (macOS) o systemctl start postgresql (Linux)"
        exit 1
    fi
    
    # Crea database se non esiste
    DB_NAME=$(echo $DATABASE_URL | sed 's/.*\///')
    if ! psql -lqt | cut -d \| -f 1 | grep -qw $DB_NAME; then
        createdb $DB_NAME
        echo "✅ Database '$DB_NAME' creato"
    fi
    
    # Esegui schema
    psql $DATABASE_URL -f database/schema.sql
    echo "✅ Schema database applicato"
}

# Esegui test
run_tests() {
    echo "🧪 Esecuzione test..."
    
    source venv/bin/activate
    
    # Setup test database
    export TEST_DATABASE_URL="postgresql://user:password@localhost/test_inventario_db"
    
    # Crea test database se necessario
    TEST_DB_NAME=$(echo $TEST_DATABASE_URL | sed 's/.*\///')
    if ! psql -lqt | cut -d \| -f 1 | grep -qw $TEST_DB_NAME; then
        createdb $TEST_DB_NAME
        echo "✅ Test database creato"
    fi
    
    # Esegui test
    python3 -m pytest tests/ -v
    echo "✅ Test completati"
}

# Deploy su Render
deploy_render() {
    echo "☁️  Deploy su Render..."
    
    # Verifica se abbiamo modifiche non committate
    if ! git diff-index --quiet HEAD --; then
        echo "⚠️  Ci sono modifiche non committate"
        read -p "Vuoi committarle? (y/n): " commit_changes
        
        if [ "$commit_changes" = "y" ]; then
            git add .
            git commit -m "Deploy: $(date '+%Y-%m-%d %H:%M:%S')"
        fi
    fi
    
    # Push su repository
    git push origin main
    echo "✅ Codice pushato su repository"
    echo "🌐 Il deploy su Render avverrà automaticamente"
    echo "📋 Verifica lo stato su: https://dashboard.render.com"
}

# Generazione API key sicura
generate_api_key() {
    echo "🔑 Generazione API Key sicura..."
    API_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
    echo "✅ API Key generata: $API_KEY"
    echo "💡 Aggiungi questa chiave alle variabili d'ambiente"
}

# Controllo salute server
health_check() {
    echo "🏥 Health check server..."
    
    SERVER_URL=${1:-"http://localhost:8000"}
    
    if curl -f "$SERVER_URL/health" > /dev/null 2>&1; then
        echo "✅ Server $SERVER_URL è online"
    else
        echo "❌ Server $SERVER_URL non risponde"
        exit 1
    fi
}

# Menu principale
main() {
    case "$1" in
        "local")
            check_requirements
            setup_local
            setup_database
            echo "✅ Setup locale completato"
            echo "🚀 Avvia server con: python3 server_complete.py"
            ;;
        "test")
            check_requirements
            setup_local
            run_tests
            ;;
        "deploy")
            check_requirements
            run_tests
            deploy_render
            ;;
        "api-key")
            generate_api_key
            ;;
        "health")
            health_check "$2"
            ;;
        "full")
            check_requirements
            setup_local
            setup_database
            run_tests
            echo "✅ Setup completo terminato"
            ;;
        *)
            echo "🔧 Script Deployment Server MCP Inventario"
            echo ""
            echo "Utilizzo: $0 [comando]"
            echo ""
            echo "Comandi disponibili:"
            echo "  local     - Setup ambiente locale completo"
            echo "  test      - Esegui test suite"
            echo "  deploy    - Deploy su Render"
            echo "  api-key   - Genera API key sicura"
            echo "  health    - Health check server"
            echo "  full      - Setup completo (local + test)"
            echo ""
            echo "Esempi:"
            echo "  $0 local              # Setup locale"
            echo "  $0 test               # Esegui test"
            echo "  $0 deploy             # Deploy su Render"
            echo "  $0 health             # Check localhost:8000"
            echo "  $0 health https://myapp.onrender.com  # Check Render"
            ;;
    esac
}

main "$@"
