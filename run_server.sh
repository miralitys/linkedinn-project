#!/bin/bash
# Запуск локального сервера MyVOICE's
# Использование: ./run_server.sh

cd "$(dirname "$0")"

# Проверка uvicorn
if python3 -c "import uvicorn" 2>/dev/null; then
    echo "Запуск сервера на http://localhost:8000"
    python3 -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
else
    echo "Сначала установите зависимости:"
    echo "  pip3 install -r requirements.txt"
    echo ""
    echo "Или с venv:"
    echo "  python3 -m venv venv"
    echo "  source venv/bin/activate"
    echo "  pip install -r requirements.txt"
    echo "  uvicorn app.main:app --reload --host 0.0.0.0 --port 8000"
    exit 1
fi
