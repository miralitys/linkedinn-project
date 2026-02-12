# Деплой MyVOICE's

## Как устроен деплой

- **База данных:** Supabase (Postgres) — облако
- **Хостинг:** Render.com — облако
- **Деплой:** push в Git → Render автоматически подтягивает и деплоит

---

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
   | `AUTH_ADMIN_EMAIL` | Email для входа админа. |
   | `AUTH_ADMIN_PASSWORD` | Пароль для входа админа. |

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

## 5. Подключение своего домена (myvoices.ai)

Чтобы проект открывался по адресу **https://myvoices.ai**:

### 5.1. Render.com — добавить домен

1. Зайди в [Render Dashboard](https://dashboard.render.com/) → выбери свой Web Service (например `myvoices`).
2. Вкладка **Settings** → блок **Custom Domains** → **Add Custom Domain**.
3. Введи `myvoices.ai` и при необходимости `www.myvoices.ai`. Render покажет, какие DNS-записи нужны.

### 5.2. DNS у регистратора домена

В панели управления доменом (где купил myvoices.ai) создай записи, как просит Render:

- **Для корня myvoices.ai (apex):**
  - если провайдер поддерживает **ANAME/ALIAS** — укажи цель: `myvoices.onrender.com` (или твой сервис);
  - иначе создай **A-запись** на IP: `216.24.57.1`;
  - если домен на **Cloudflare** — используй **CNAME** на `myvoices.onrender.com` (CNAME flattening).
- **Для www.myvoices.ai:** тип **CNAME**, цель — `myvoices.onrender.com` (или твой *.onrender.com).

Сохрани изменения; распространение DNS может занять от нескольких минут до часа. В Render статус домена станет «Verified», когда записи подтянутся. Render автоматически выдаёт SSL (HTTPS) для кастомного домена.

### 5.3. Переменные окружения на Render

В **Environment** сервиса задай redirect для своего домена (без слэша в конце):

| Key | Value |
|-----|--------|
| `LINKEDIN_REDIRECT_URI` | `https://myvoices.ai/linkedin/oauth/callback` |

Если используешь Google OAuth, добавь в Google Cloud Console redirect: `https://myvoices.ai/auth/google/callback` и при необходимости `GOOGLE_REDIRECT_URI=https://myvoices.ai/auth/google/callback`.

После сохранения переменных Render перезапустит сервис.

### 5.4. LinkedIn Developer Portal

1. Зайди в [LinkedIn Developers](https://www.linkedin.com/developers/) → своё приложение.
2. **Auth** → **Authorized redirect URLs** → добавь: `https://myvoices.ai/linkedin/oauth/callback` (можно оставить и старый URL Render для переходного периода).
3. Сохрани.

После этого вход через LinkedIn и приложение будут работать по **https://myvoices.ai**.

## 6. Локальная разработка с облачной БД

Чтобы локально подключаться к Supabase:

1. В `.env` задай `DATABASE_URL` со строкой из Supabase.
2. Запусти `uvicorn app.main:app --reload --port 8000`. Таблицы уже есть в облаке; при необходимости пересоздать — выполни один раз `python -m app.db` с этим же `DATABASE_URL`.

Локально можно по-прежнему использовать SQLite: не задавай `DATABASE_URL` или укажи `DATABASE_URL=sqlite+aiosqlite:///./lfas.db`.

## 7. Перенос данных из локального SQLite в Supabase

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

## 8. Синхронизация локальной БД с сервером (Supabase → локально)

Чтобы локально работать с теми же данными, что на сервере:

1. В `.env` задай строку подключения к Supabase:
   ```bash
   REMOTE_DATABASE_URL="postgresql://postgres.xxx:ПАРОЛЬ@aws-0-xxx.pooler.supabase.com:6543/postgres?sslmode=require"
   ```
   Или можно использовать `DATABASE_URL`, если он уже указывает на Supabase.

2. Из **корня проекта** выполни:
   ```bash
   python -m scripts.sync_from_supabase
   ```

3. Скрипт скопирует все данные из Supabase в `./lfas.db`. Локальная БД будет полностью перезаписана.

4. Для запуска приложения с локальными данными укажи в `.env`:
   ```bash
   DATABASE_URL=sqlite+aiosqlite:///./lfas.db
   ```
   Или удали `DATABASE_URL`, чтобы использовался SQLite по умолчанию.

---

## Альтернатива: деплой на свой сервер (SSH)

Если нужен свой VPS вместо Render:

1. Создай `.deploy.conf` из примера: `cp .deploy.conf.example .deploy.conf`
2. Укажи `REMOTE=user@сервер.com` и `REMOTE_PATH=/var/www/myvoices`
3. Запускай: `./scripts/deploy.sh`

На сервере должен быть `.env` с `DATABASE_URL` (Supabase или SQLite), `SESSION_SECRET`, `AUTH_ADMIN_EMAIL`, `AUTH_ADMIN_PASSWORD`.
