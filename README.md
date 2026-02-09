# LinkedIn Funnel Agent System (LFAS)

Локальная система агентов для ведения LinkedIn-воронки: единый data layer, 7 LLM-агентов (MVP), веб-интерфейс и CLI. Все действия строятся вокруг статусов контактов (state machine); агенты только предлагают черновики и двигают сущности по этапам на основе логов касаний.

## Ограничения

- **Нет парсинга LinkedIn**, массовых действий, автокликов. Пользователь вручную вносит ссылки/текст/заметки; система генерирует карточки и черновики.
- **Запрет на выдумывание фактов**: при отсутствии данных — «неизвестно» и список уточняющих вопросов.
- Общий «банк памяти» для всех агентов (тон, позиционирование).
- Встроенный QA-агент проверяет тон, галлюцинации, агрессивность, спам-паттерны.

## Быстрый старт

### 1. Окружение

```bash
python3 -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# Заполни OPENAI_API_KEY в .env
```

### 2. База данных

```bash
# Создание таблиц (без Alembic в MVP — создание при старте)
python3 -m app.db
# или при первом запуске сервера таблицы создадутся автоматически
```

### 3. Запуск сервера

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Открой: http://localhost:8000

### 4. CLI (опционально)

```bash
python -m app.cli daily-queue
python -m app.cli setup --product "B2B SaaS" --icp "CTO малого бизнеса"
```

## Структура репозитория

- `app/` — FastAPI приложение, роутеры, модели, схемы
- `agents/` — базовый класс агентов, LLM-клиент, 7 MVP-агентов + заглушки A8–A10
- `prompts/` — шаблоны промптов для каждого агента
- `memory/` — markdown-файлы «единой правды» (Sales Avatar, офферы, сегменты)
- `tests/` — тесты переходов состояний и QA-эвристик

## API (минимум)

- `POST /setup` — онбординг: продукт, ICP, тон, цели → SalesAvatar + сегменты/офферы
- `GET/POST /daily-queue` — очередь на день: комменты KOL, посты, warm DM
- `POST /agents/{agent_name}/run` — запуск агента с payload
- `GET /drafts`, `POST /drafts/{id}/qa`, `POST /drafts/{id}/approve`
- CRUD: `/companies`, `/people`, `/kol`, `/touches`

## Статусы контактов

`New → Connected → Engaged → Warm → DM_Sent → Replied → Call_Booked → Won | Lost`

Guardrails: в первый месяц — минимум cold DM; DM только после прогрева и наличия повода (лид-магнит/контекст).

## Деплой (Supabase + Render)

Для облачного запуска: **Supabase** (Postgres) + **Render.com** (хостинг). Пошаговая инструкция — в [DEPLOY.md](DEPLOY.md). В корне есть `render.yaml` для деплоя через Render Blueprint.

## Техстек

Python 3.11+, FastAPI, Pydantic, SQLAlchemy, SQLite (локально) / Postgres (Supabase), Jinja2+HTMX, APScheduler, OpenAI (сменяемый провайдер).
