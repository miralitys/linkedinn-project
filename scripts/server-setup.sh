#!/bin/bash
# Запуск на сервере — скопируйте и выполните на удалённом сервере
# Вариант 1: простой запуск (nohup)
# cd /path/to/project
# pip install -r requirements.txt
# export DATABASE_URL="postgresql://..."  # или оставьте SQLite
# nohup uvicorn app.main:app --host 0.0.0.0 --port 8000 > app.log 2>&1 &

# Вариант 2: systemd (создайте /etc/systemd/system/myvoices.service)
cat << 'EOF'
[Unit]
Description=MyVOICE's LFAS
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/var/www/myvoices
Environment="PATH=/usr/local/bin:/usr/bin"
EnvironmentFile=/var/www/myvoices/.env
ExecStart=/usr/bin/python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
EOF
