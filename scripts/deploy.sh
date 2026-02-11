#!/bin/bash
# Деплой на внешний сервер через SSH и rsync
# Использование: ./scripts/deploy.sh [user@host] [путь_на_сервере]
# Или создайте .deploy.conf в корне проекта с REMOTE и REMOTE_PATH — тогда просто: ./scripts/deploy.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Читаем из конфига, если нет аргументов
if [ -z "$1" ] && [ -f "$PROJECT_ROOT/.deploy.conf" ]; then
  source "$PROJECT_ROOT/.deploy.conf"
fi

REMOTE="${1:-$REMOTE}"
REMOTE_PATH="${2:-$REMOTE_PATH}"

if [ -z "$REMOTE" ] || [ -z "$REMOTE_PATH" ]; then
  echo "Использование: $0 user@host /path/on/server"
  echo "Или создайте .deploy.conf:"
  echo "  REMOTE=user@server.com"
  echo "  REMOTE_PATH=/var/www/myvoices"
  exit 1
fi

echo "→ Деплой в $REMOTE:$REMOTE_PATH"
echo "  Корень проекта: $PROJECT_ROOT"

# Исключаем лишнее при синхронизации
EXCLUDE="--exclude=.git --exclude=__pycache__ --exclude=*.pyc --exclude=.env --exclude=uploads --exclude=uploads/ --exclude=lfas.db --exclude=*.zip --exclude=Архив*"

# Синхронизация
echo "→ Синхронизация файлов..."
rsync -avz --delete $EXCLUDE \
  "$PROJECT_ROOT/" \
  "$REMOTE:$REMOTE_PATH/"

# Выполнение на сервере
echo "→ Выполнение на сервере: pip install..."
ssh "$REMOTE" "cd $REMOTE_PATH && pip install -r requirements.txt"

# Перезапуск (если RESTART_AFTER_DEPLOY=true в .deploy.conf или systemd)
if [ "${RESTART_AFTER_DEPLOY:-}" = "true" ]; then
  echo "→ Перезапуск приложения..."
  if [ -n "${SYSTEMD_SERVICE:-}" ]; then
    ssh "$REMOTE" "sudo systemctl restart $SYSTEMD_SERVICE"
  else
    ssh "$REMOTE" "cd $REMOTE_PATH && pkill -f 'uvicorn app.main' 2>/dev/null; nohup uvicorn app.main:app --host 0.0.0.0 --port 8000 > app.log 2>&1 &"
  fi
fi

echo ""
echo "✓ Деплой завершён."
echo ""
echo "Важно: на сервере должен быть .env с переменными (DATABASE_URL, SESSION_SECRET, AUTH_ADMIN_EMAIL, AUTH_ADMIN_PASSWORD и др.)."
if [ "${RESTART_AFTER_DEPLOY:-}" != "true" ]; then
  echo ""
  echo "Перезапуск вручную:"
  echo "  ssh $REMOTE 'cd $REMOTE_PATH && pkill -f uvicorn; nohup uvicorn app.main:app --host 0.0.0.0 --port 8000 > app.log 2>&1 &'"
  echo "  или: systemctl restart myvoices"
fi
