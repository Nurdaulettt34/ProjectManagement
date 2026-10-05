# UniFlow — Intelligent University Document Management Assistant

AI-портал, который помогает студентам и абитуриентам разбираться с университетскими документами:
загрузка, автоматическое определение типа, извлечение ключевых полей с проверкой пользователем
и краткое summary. Реализованы user stories **US1–US5**; схема БД заложена под US6–US14.

**Все данные — пользователи, документы, оригиналы файлов, результаты AI — хранятся в PostgreSQL.**
JSON-файлов и папки `uploads/` в проекте больше нет.

## Стек
Flask 3 · PostgreSQL 16 · Flask-SQLAlchemy · Flask-Migrate (Alembic) · psycopg 3 · pdfplumber · python-docx ·
vanilla JS · pytest · Docker Compose · gunicorn. Опционально — Anthropic API.

## Быстрый старт (Docker, рекомендовано)
```bash
cp .env.example .env          # необязательно для локальной разработки, но лучше сразу
docker compose up --build
```
Открыть http://localhost:5000. При старте контейнер сам выполняет `flask db upgrade` и `flask seed`.

**Код подтверждения email при локальном запуске.** Если `MAIL_SERVER` не задан, письмо не отправляется,
а печатается в лог контейнера. Код видно в терминале с `docker compose up` или командой
`docker compose logs -f web`. Чтобы письма приходили на настоящую почту, заполните `MAIL_*` в `.env`
(см. раздел «Почта»).
Код смонтирован в контейнер, Flask перезапускается при изменениях.

Тесты в Docker:
```bash
docker compose run --rm web pytest
```
База `uniflow_test` создаётся автоматически при первом запуске volume (`docker/init-test-db.sql`).
Если volume был создан раньше: `docker compose exec postgres createdb -U uniflow uniflow_test`.

## Запуск без Docker
Нужны Python 3.11+ и PostgreSQL 16.
```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                    # заполнить SECRET_KEY
createdb -U postgres -O uniflow uniflow                 # или через pgAdmin
createdb -U postgres -O uniflow uniflow_test
flask db upgrade
flask seed
flask run
```
`SECRET_KEY` сгенерировать: `python -c "import secrets; print(secrets.token_hex(32))"`.
Только PostgreSQL можно поднять и в Docker: `docker compose up -d postgres`.

Тесты: `pytest` (берёт `TEST_DATABASE_URL`, по умолчанию `localhost:5432/uniflow_test`).
Фикстура создаёт таблицы один раз за сессию и делает `TRUNCATE` перед каждым тестом.
Тесты откажутся запускаться, если `TEST_DATABASE_URL` совпадает с `DATABASE_URL`.

## Конфигурация (`.env`)
| Переменная | Назначение |
|---|---|
| `APP_ENV` | `development` / `testing` / `production` (классы в `config.py`) |
| `SECRET_KEY` | обязателен; без него приложение не стартует. В production ключи `dev-…` и короче 32 символов отклоняются |
| `DATABASE_URL` | `postgresql+psycopg://user:pass@host:5432/db` (формат `postgres://` от Render/Neon конвертируется автоматически) |
| `TEST_DATABASE_URL` | отдельная БД для pytest |
| `SEED_STAFF_EMAIL/PASSWORD`, `SEED_ADMIN_EMAIL/PASSWORD` | аккаунты для `flask seed` (в production пароли обязательны) |
| `ANTHROPIC_API_KEY` | пусто → rule-based AI; задан → LLM с fallback на правила |
| `ANTHROPIC_MODEL`, `AI_CONFIDENCE_THRESHOLD` | модель и порог уверенности (по умолчанию 0.5) |

## Регистрация и подтверждение email
- **Студент** регистрируется только с почтой университета: `…@sdu.edu.kz` или поддомен (`…@stu.sdu.edu.kz`).
  Внешние адреса (gmail, mail.ru) и похожие домены (`notsdu.edu.kz`, `sdu.edu.kz.evil.com`) отклоняются.
  Домен задаётся `STUDENT_EMAIL_DOMAIN`.
- **Абитуриент** может использовать любую почту.
- После регистрации на почту приходит 6-значный код. Пока email не подтверждён, войти нельзя (`403`).
  Код действует 15 минут, даётся 5 попыток, повторная отправка не чаще раза в 60 секунд.
  В БД хранится только HMAC-SHA256 кода (таблица `email_verifications`).
- Если неподтверждённый аккаунт заброшен (код истёк), владелец почты может зарегистрироваться заново.
- После подтверждения пользователь попадает на ознакомительный тур `/welcome`, затем в рабочее пространство `/app`.

## Почта
| Переменная | Назначение |
|---|---|
| `MAIL_SERVER`, `MAIL_PORT` | SMTP-сервер; пусто → письма печатаются в лог (только development) |
| `MAIL_USERNAME`, `MAIL_PASSWORD` | логин SMTP; для Gmail нужен App Password (16 символов, требует 2-Step Verification) |
| `MAIL_USE_TLS` / `MAIL_USE_SSL` | STARTTLS на 587 (по умолчанию) или SSL на 465 |
| `MAIL_FROM` | адрес отправителя (по умолчанию `MAIL_USERNAME`) |
| `MAIL_BACKEND` | `smtp` / `console`; в production по умолчанию всегда `smtp` |

Пример для Gmail в `.env`:
```
MAIL_SERVER=smtp.gmail.com
MAIL_PORT=587
MAIL_USERNAME=uniflow.team@gmail.com
MAIL_PASSWORD=abcdefghijklmnop
```

## Страницы
| URL | Что |
|---|---|
| `/` | главная (публичная): что такое UniFlow, как работает, для кого |
| `/register`, `/login`, `/verify` | регистрация, вход, ввод кода |
| `/welcome` | ознакомительный тур для новых пользователей (показывается один раз, потом доступен из сайдбара) |
| `/app` | рабочее пространство: документы |
| `/profile` | профиль: данные, статистика документов, смена имени и пароля; блок «My requests» — заготовка под Requests |

## Миграции
```bash
flask db upgrade                         # применить
flask db migrate -m "add requests table" # после изменения uniflow/models.py
flask db downgrade                       # откатить последнюю
```
Каждую сгенерированную миграцию нужно просмотреть и закоммитить в `migrations/versions/`.

## Seed
`flask seed` (идемпотентно): 8 департаментов (`ADM`, `REG`, `DEAN`, …) и аккаунты staff/admin.
Через регистрацию можно создать только `student` и `applicant`.
Эти аккаунты сразу подтверждены и не проходят тур. Для разработки, если пароли не заданы: `staff@uniflow.edu / Staff-Password-2026`, `admin@uniflow.edu / Admin-Password-2026`.

## Деплой: Render + Neon
1. **Neon**: создать проект → скопировать connection string (`postgresql://…?sslmode=require`).
2. **Render** → New → Web Service → репозиторий, Runtime **Docker** (Dockerfile уже есть).
3. Environment: `APP_ENV=production`, `SECRET_KEY` (64 hex-символа), `DATABASE_URL` (строка Neon),
   `SEED_STAFF_PASSWORD`, `SEED_ADMIN_PASSWORD`, при желании `ANTHROPIC_API_KEY`.
4. Deploy. Entrypoint применит миграции и seed, затем gunicorn слушает `$PORT`.
Можно использовать и Render PostgreSQL — достаточно подставить его Internal Database URL.

## AI-архитектура (`ai/`)
| Функция | Возвращает |
|---|---|
| `classify(text)` | `{type, confidence}` (+ `method`) |
| `extract(text, doc_type)` | `{field: {value, state}}` |
| `summarize(text)` | `[bullets]` |

- **rules** (по умолчанию): ключевые слова и regex на RU/KZ/EN. Детерминированно, офлайн, тесты без API-ключа.
- **llm** (если задан `ANTHROPIC_API_KEY`): ответ проверяется; при ошибке API или невалидном ответе — fallback на rules.
  Значения полей, которых нет в тексте документа, отбрасываются; пункты summary с числами, которых нет в тексте, удаляются.
- Уверенность ниже порога → тип `other`. Метод (`rules`/`llm`) сохраняется в БД.
- Summary в режиме rules — экстрактивный: каждый пункт — предложение из самого документа.

Типы: `certificate`, `application_form`, `request`, `transcript`, `id_document`, `internal_form`, `other`.
Поля по типам — `ai/schema.py` (`FIELD_SCHEMAS`).

## API
Все ответы JSON, ошибки — `{"error": "..."}`. Всё, кроме auth, требует входа (иначе 401);
чужой документ → 404.

| Метод | URL | Описание |
|---|---|---|
| POST | `/api/register` | `{full_name, email, password, role: student\|applicant}` → 201 + код на почту (вход не выполняется); 400 валидация (студент не с SDU-почтой); 409 email занят; 503 письмо не отправлено |
| POST | `/api/verify-email` | `{email, code}` → 200 и вход; 400 неверный/истёкший код; 429 превышены попытки |
| POST | `/api/resend-code` | `{email}` → 200; 429 слишком рано |
| POST | `/api/login` | `{email, password}` → 200 / 401; 403 `verification_required`, если email не подтверждён |
| POST | `/api/logout` | выход |
| GET | `/api/profile` | пользователь, статистика документов, 5 последних документов |
| PATCH | `/api/profile` | `{full_name}` (email и роль не меняются) |
| POST | `/api/profile/password` | `{current_password, new_password}` |
| POST | `/api/onboarding/complete` | отметить тур пройденным |
| GET | `/api/me` | текущий пользователь |
| POST | `/api/documents` | multipart `file` (PDF/DOCX ≤ 20 MB, проверка сигнатуры) → 201 + классификация + поля |
| GET | `/api/documents?q=` | мои документы, кратко (без текста); `q` — поиск по имени и тексту |
| GET | `/api/documents/<id>` | детали: текст, классификация, поля, summary |
| DELETE | `/api/documents/<id>` | удалить документ и все результаты |
| GET | `/api/documents/<id>/file` | оригинал из БД; браузер без входа → редирект на `/login` |
| PATCH | `/api/documents/<id>/fields` | `{"fields": {"issue_date": "15.09.2026"}}` → state `corrected` (пустое значение → `missing`) |
| POST | `/api/documents/<id>/review` | «Mark as reviewed» |
| POST | `/api/documents/<id>/summary` | создать/пересоздать summary (422, если нет текста) |
| GET | `/api/documents/<id>/summary` | получить summary (404, если ещё нет) |

## Схема БД
```
users ──1:1── email_verifications
users ──< documents ──┬── document_classifications (1:1)
                      ├──< extracted_fields
                      └── document_summaries (1:1)
departments  (для US11/US14)
```
- `users`: UUID, `email` UNIQUE + CHECK lower, `role` ENUM(student, applicant, staff, admin), `email_verified_at`, `onboarded_at`.
- `email_verifications`: один активный код на пользователя (UNIQUE user_id), `code_hash`, `expires_at`, `attempts`, `sent_at`.
- `documents`: `file_data` BYTEA (оригинал), `sha256`, `status` ENUM(uploaded, processed, failed), `reviewed_at`; FK ON DELETE CASCADE.
- `document_classifications`: CHECK на допустимые типы и `0 ≤ confidence ≤ 1`.
- `extracted_fields`: UNIQUE(document_id, field_name); CHECK `state <> 'missing' OR value IS NULL` — «missing» не может иметь значение.
- `document_summaries`: `bullets` JSONB.
- Индексы: `ix_users_email`, `ix_documents_user_id`.

## Структура
```
├── app.py                 # точка входа (flask / gunicorn)
├── config.py              # Development / Testing / Production
├── uniflow/               # Flask-приложение
│   ├── __init__.py        # create_app()
│   ├── models.py          # SQLAlchemy-модели
│   ├── auth.py            # US1
│   ├── documents.py       # US2–US5 API
│   ├── services.py        # конвейер: текст → классификация → поля; summary
│   ├── files.py           # проверка сигнатуры, извлечение текста (в памяти)
│   ├── verification.py    # коды подтверждения email
│   ├── mailer.py          # отправка почты (smtp / console / memory)
│   ├── profile.py         # профиль и онбординг API
│   ├── errors.py, pages.py, cli.py (flask seed)
├── ai/                    # schema, rules, llm, service (fallback + валидация)
├── migrations/            # Alembic
├── templates/, static/    # UI в стиле UniFlow
├── tests/                 # pytest: test_us1…test_us5, verification, profile/onboarding, legacy, platform
├── design/                # исходный макет
├── Dockerfile, docker-compose.yml, docker/
└── .env.example
```

## Дальше (US6–US14)
Smart search, Requests и Workflows отмечены в сайдбаре как «soon». Таблица `departments` и роли staff/admin уже есть.
