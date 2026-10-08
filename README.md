# RAG-система для секретарей ФПИ

Telegram-бот отвечает студентам факультета прикладной информатики на вопросы об учёбе.
Ответы строятся по документам факультета с помощью RAG; если ответа в документах нет,
вопрос передаётся секретарю.

Состояние на спринт 2 (MVP v1.0): бот задаёт вопросы API ядра через `POST /ask`
(контракт: `api/openapi.yaml`). API подключает RAG-движок участника A через переменную
`RAG_ENGINE`; пока движок не подключён, отвечает заглушка `stub`.

## Структура репозитория

```
bot/                 Telegram-бот (aiogram 3)
  __main__.py        точка входа: python -m bot
  app.py             сборка Bot и Dispatcher
  config.py          настройки из .env (pydantic-settings)
  texts.py           все тексты для пользователя
  formatting.py      текст ответа, разбиение длинных сообщений
  validation.py      проверка вопроса
  states.py          состояния FSM
  keyboards.py       клавиатуры и callback data
  handlers/          обработчики; порядок регистрации: handlers/__init__.py
  middlewares/       логирование, роль пользователя
  services/          клиенты сервиса ответов: HTTP к API и заглушка
api/                 REST API ядра (FastAPI)
  __main__.py        точка входа: python -m api
  openapi.yaml       контракт API (бот, n8n, ядро)
  app.py             эндпоинты /health и /ask, формат ошибок
  engine.py          интерфейс RAG-движка, загрузка по RAG_ENGINE, заглушка
  config.py          настройки из .env
  schemas.py         модели запросов и ответов
worker/              загрузка и индексация документов, RAG-движок (участник A)
docs/                артефакты курса, диаграммы
tests/bot/           тесты бота, в т. ч. связка бот и API (test_mvp_integration.py)
tests/api/           тесты API и контракта
tests/contract.py    проверка JSON по схемам openapi.yaml
docker/              Dockerfile бота и API
```

## Требования

- Python 3.12;
- [uv](https://docs.astral.sh/uv/);
- Docker с Compose v2 (только для запуска в контейнерах);
- токен бота от [@BotFather](https://t.me/BotFather).

## Установка и запуск локально

Установка uv.

Windows (PowerShell):

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Linux:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Установка зависимостей (uv сам скачает Python 3.12, если его нет):

```bash
uv sync
uv run pre-commit install
```

Файл настроек. Windows (PowerShell): `Copy-Item .env.example .env`, Linux: `cp .env.example .env`.
В `.env` нужно вписать `BOT_TOKEN` и `API_TOKEN` (любая длинная случайная строка,
команда для генерации есть в `.env.example`).

Запуск API и бота в двух терминалах:

```bash
uv run python -m api
uv run python -m bot
```

API слушает `http://localhost:8000`, документация Swagger UI: `http://localhost:8000/docs`.
Чтобы запустить бота без API, оставьте `API_URL` пустым: бот будет отвечать заглушкой.

Остановка: Ctrl+C.

## Запуск в Docker

```bash
docker compose up --build
```

Поднимаются `postgres`, затем `api` (ждёт готовности базы), затем `bot` (ждёт, пока
`GET /health` ответит). Все сервисы читают один `.env`; в `.env` должны быть заданы
`BOT_TOKEN`, `API_TOKEN` и `POSTGRES_PASSWORD`, иначе Compose или сервис не запустится
с понятной ошибкой. `API_URL` для бота внутри Compose подменяется на `http://api:8000`.

API и PostgreSQL открыты только на этой машине (`127.0.0.1:8000` и `127.0.0.1:5432`).
Данные PostgreSQL хранятся в томе `postgres_data`. Сервисы `qdrant` и `llm` добавляет
участник A (задача 15). Когда к API подключится настоящий RAG-движок (BGE-M3 через
PyTorch), в `docker-compose.yml` нужно раскомментировать блок `deploy` у `api`, чтобы
контейнер получил GPU.

## Переменные окружения

| Переменная | По умолчанию | Описание |
|---|---|---|
| `BOT_TOKEN` | нет | Токен бота, обязателен. Без него бот не запустится. |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` или `CRITICAL` (бот и API). |
| `SECRETARY_IDS` | пусто | Telegram ID секретарей через запятую, например `123, 456`. |
| `MAX_QUESTION_LENGTH` | `1000` | Максимальная длина вопроса в символах, не больше 1000. |
| `API_URL` | пусто | Адрес API для бота. Пусто: бот отвечает заглушкой. |
| `API_TOKEN` | нет | Сервисный токен API. Обязателен для API и для бота, если задан `API_URL`. |
| `ANSWER_TIMEOUT` | `30` | Сколько секунд бот ждёт ответ `POST /ask`. |
| `RAG_ENGINE` | `stub` | RAG-движок для API: `stub` или `модуль:фабрика`. |
| `RAG_TIMEOUT` | `25` | Сколько секунд API ждёт движок. Меньше `ANSWER_TIMEOUT`. |
| `API_HOST`, `API_PORT` | `127.0.0.1`, `8000` | Адрес и порт API; в контейнере `0.0.0.0`. |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | `fpi`, нет, `fpi_rag` | Учётные данные PostgreSQL для Compose. |

Свой Telegram ID можно узнать, например, у бота [@userinfobot](https://t.me/userinfobot).
Роль секретаря пока только определяется (`is_secretary` в данных обработчика), но
нигде не используется.

## Контракт API

`api/openapi.yaml` (OpenAPI 3.1) описывает `/ask`, `/answers/{answer_id}/feedback`,
`/tickets`, `/documents`, `/search` и `/health`, статусы ответа (`answered`, `no_answer`,
`escalated`) и единый формат ошибок `{"error": {"code": ..., "message": ...}}`.
Поле `x-sprint` у операции показывает спринт реализации; в MVP v1.0 работают `/health`
и `/ask`. Тесты `tests/api/test_contract.py` проверяют, что код API и бота не расходится
с контрактом.

## Подключение RAG-движка (для участника A)

API вызывает движок через интерфейс `RagEngine` из `api/engine.py`: синхронный метод
`answer(question) -> RagAnswer` (`status` = `answered` или `no_answer`, `text`, `sources`).
API запускает его в пуле потоков. Если LLM, Qdrant или модель эмбеддингов недоступны,
движок выбрасывает `RagUnavailableError`, и API отвечает 503.

Подключение: в `worker/` пишется фабрика без аргументов, например
`worker/rag.py: create_engine()`, и в `.env` задаётся `RAG_ENGINE=worker.rag:create_engine`.

## Заглушки

Если `API_URL` не задан, бот работает с `StubAnswerClient` (`bot/services/answer_client.py`).
Если API запущен с `RAG_ENGINE=stub`, отвечает `StubRagEngine` (`api/engine.py`) с теми же
словами-переключателями, кроме «секретарь» (статус `escalated` API начнёт возвращать в
спринте 3).

Заглушка бота отвечает через 1 секунду, а поведение зависит от слов в вопросе.
Регистр не важен, слова проверяются в таком порядке:

| Вопрос содержит | Результат |
|---|---|
| «ошибка» | техническая ошибка, бот извиняется и предлагает повторить позже |
| «нет ответа» | статус `no_answer`: «ответа в документах нет» и кнопка «Позвать секретаря» |
| «секретарь» | статус `escalated`: «вопрос передан секретарю» |
| что угодно другое | статус `answered`: ответ с цитатой вопроса, один выдуманный источник, кнопки 👍, 👎, «Позвать секретаря» |

Слово нужно именно в этой форме: «секретаря» или «секретарю» не сработают.

Обработчики получают клиент через данные диспетчера (`bot/app.py`), поэтому от выбора
клиента они не зависят.

## Тесты и линтеры

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy bot api
uv run pytest --cov=bot --cov=api
```

Тесты не обращаются к Telegram и к сети: бот связывается с API напрямую через
ASGI-транспорт httpx. Если покрытие меньше 70%, pytest завершится с ошибкой.

Pre-commit перед каждым коммитом запускает ruff и базовые проверки файлов. Запустить вручную
для всего репозитория: `uv run pre-commit run --all-files`.

## Документация по коду

```bash
uv run pdoc bot api -d google -o docs/api
```

HTML появится в `docs/api/` (в git не попадает). Флаг `-d google` нужен, чтобы разделы
`Args`, `Returns` и `Raises` в docstring отображались как разделы, а не как обычный текст.

## Соглашения о коммитах

[Conventional Commits](https://www.conventionalcommits.org/ru/) на английском:

```
feat(bot): add rating buttons
fix(bot): keep state after answer service error
test(bot): cover message splitting
chore(repo): update dependencies
docs: describe environment variables
```

## Команда

| Участник | Зона ответственности |
|---|---|
| Неищенко А.А. (A) | LLM, эмбеддинги, Qdrant, PostgreSQL, загрузка документов, n8n (`worker/`) |
| Колычев М.Н. (B) | Telegram-бот, API, интерфейс, передача вопросов секретарю, тесты, развёртывание (`bot/`, `api/`) |
