# Деплой: Supabase + Render.com

Проект настроен на связку **Supabase** (Postgres) и **Render.com** (хостинг приложения).

## 1. Supabase (база данных)

1. Зайди на [supabase.com](https://supabase.com/), создай аккаунт и **New project**.
2. В проекте: **Settings** → **Database**.
3. В блоке **Connection string** выбери **URI** и скопируй строку (режим **Transaction** / порт **6543** подходит для приложения).
   - Формат: `postgresql://postgres.[project-ref]:[YOUR-PASSWORD]@aws-0-[region].pooler.supabase.com:6543/postgres`
4. Пароль к БД ты задавал при создании проекта. Если забыл — **Settings** → **Database** → **Reset database password**.
5. В строке подключения можно оставить `postgresql://` — приложение само подставит `postgresql+asyncpg://` при запуске.

**Важно:** если в пароле есть символы вроде `@`, `#`, `?`, закодируй их для URL (например `@` → `%40`).

## 2. Render.com (приложение)

1. Зайди на [render.com](https://render.com/), создай аккаунт.
2. **Dashboard** → **New** → **Web Service**.
3. Подключи репозиторий (GitHub/GitLab). Выбери репозиторий с этим проектом.
4. Настройки:
   - **Name:** например `myvoices`
   - **Region:** любой (например Frankfurt).
   - **Runtime:** Python 3.
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
5. **Environment** — добавь переменные:

   | Key             | Value / действие |
   |-----------------|------------------|
   | `DATABASE_URL`  | Вставь Connection string из Supabase (URI, см. выше). |
   | `SESSION_SECRET`| Сгенерируй случайную строку (например `openssl rand -hex 32`) или нажми **Generate** в Render. |
   | `OPENAI_API_KEY`| Твой ключ OpenAI (для агентов). |

   При необходимости добавь остальные из `.env.example` (LinkedIn OAuth, RapidAPI, Playwright path и т.д.).

6. **Create Web Service**. Render соберёт проект и запустит приложение.
7. При первом запуске приложение создаст таблицы в Supabase через `init_db()`.

## 3. Альтернатива: Blueprint (render.yaml)

Если в корне репозитория есть `render.yaml`:

1. **New** → **Blueprint**.
2. Подключи репозиторий и выбери этот репозиторий (Render подхватит `render.yaml`).
3. В среде сервиса обязательно задай **DATABASE_URL** и **OPENAI_API_KEY** (SESSION_SECRET можно сгенерировать в Render).

## 4. После деплоя

- URL приложения будет вида: `https://myvoices.onrender.com` (или как ты назвал сервис).
- Для LinkedIn OAuth в настройках приложения LinkedIn укажи Redirect URL: `https://твой-сервис.onrender.com/linkedin/oauth/callback`.
- Playwright и «Распознать по ссылке» на бесплатном Render могут быть недоступны (нет браузера). Остальной функционал (новости, Reddit, посты, агенты, настройки) работает с Supabase.

## 5. Локальная разработка с облачной БД

Чтобы локально подключаться к Supabase:

1. В `.env` задай `DATABASE_URL` со строкой из Supabase.
2. Запусти `uvicorn app.main:app --reload --port 8000`. Таблицы уже есть в облаке; при необходимости пересоздать — выполни один раз `python -m app.db` с этим же `DATABASE_URL`.

Локально можно по-прежнему использовать SQLite: не задавай `DATABASE_URL` или укажи `DATABASE_URL=sqlite+aiosqlite:///./lfas.db`.

## 6. Перенос данных из локального SQLite в Supabase

Если на проде (Render + Supabase) пустые разделы «Авторы», «Продукты», «Портрет клиента», «Сабреддиты» и т.д., можно один раз перенести данные из локальной БД в Supabase.

1. Убедись, что локально есть файл `lfas.db` с нужными данными (в корне проекта).
2. В `.env` **временно** задай строку подключения к **Supabase** (как в шаге 1), например:
   ```bash
   DATABASE_URL="postgresql://postgres.xxx:ПАРОЛЬ@aws-0-xxx.pooler.supabase.com:6543/postgres?sslmode=require"
   ```
3. Из **корня проекта** выполни:
   ```bash
   python -m scripts.migrate_local_to_supabase
   ```
4. Скрипт читает данные из `./lfas.db` (или из `LOCAL_DATABASE_URL`, если задан) и записывает их в БД из `DATABASE_URL` (Supabase). После этого обнови страницу настроек на проде — данные появятся.
5. Для дальнейшей локальной разработки с SQLite можно снова убрать или изменить `DATABASE_URL` в `.env`.
