# RAG-система для секретарей ФПИ

Telegram-бот отвечает студентам факультета прикладной информатики на вопросы об учёбе.
Ответы строятся по документам факультета с помощью RAG; если ответа в документах нет,
вопрос передаётся секретарю. Сейчас готов прототип бота: вместо RAG-ядра подключена
заглушка.

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
  handlers/          обработчики; порядок регистрации — в handlers/__init__.py
  middlewares/       логирование, роль пользователя
  services/          клиент сервиса ответов (сейчас заглушка)
api/                 REST API ядра (FastAPI), появится в спринте 3
worker/              загрузка и индексация документов
docs/                артефакты курса, диаграммы
tests/bot/           тесты бота
docker/              Dockerfile
```

## Требования

- Python 3.12;
- [uv](https://docs.astral.sh/uv/);
- Docker с Compose v2 — только для запуска в контейнере;
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
В `.env` нужно вписать `BOT_TOKEN`.

Запуск:

```bash
uv run python -m bot
```

Остановка — Ctrl+C.

## Запуск в Docker

```bash
docker compose up --build bot
```

Контейнер читает настройки из того же `.env`. Сервисы `api`, `postgres`, `qdrant` и `llm`
в `docker-compose.yml` пока закомментированы.

## Переменные окружения

| Переменная | По умолчанию | Описание |
|---|---|---|
| `BOT_TOKEN` | — | Токен бота, обязателен. Без него бот не запустится. |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` или `CRITICAL`. |
| `SECRETARY_IDS` | пусто | Telegram ID секретарей через запятую, например `123, 456`. |
| `MAX_QUESTION_LENGTH` | `1000` | Максимальная длина вопроса в символах. |

Свой Telegram ID можно узнать, например, у бота [@userinfobot](https://t.me/userinfobot).
Роль секретаря пока только определяется (`is_secretary` в данных обработчика), но
нигде не используется.

## Заглушка сервиса ответов

Пока ядра нет, бот работает с `StubAnswerClient` (`bot/services/answer_client.py`). Он отвечает
через 1 секунду, а поведение зависит от слов в вопросе. Регистр не важен, слова проверяются
в таком порядке:

| Вопрос содержит | Результат |
|---|---|
| «ошибка» | техническая ошибка, бот извиняется и предлагает повторить позже |
| «нет ответа» | статус `no_answer`: «ответа в документах нет» и кнопка «Позвать секретаря» |
| «секретарь» | статус `escalated`: «вопрос передан секретарю» |
| что угодно другое | статус `answered`: ответ с цитатой вопроса, один выдуманный источник, кнопки 👍, 👎, «Позвать секретаря» |

Слово нужно именно в этой форме: «секретаря» или «секретарю» не сработают.

В спринте 3 заглушку заменит HTTP-клиент к `POST /ask`. Обработчики получают клиент через
данные диспетчера (`bot/app.py`), поэтому менять их не придётся.

## Тесты и линтеры

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy bot
uv run pytest --cov=bot
```

Тесты не обращаются к Telegram. Если покрытие пакета `bot` меньше 70%, pytest завершится с ошибкой.

Pre-commit перед каждым коммитом запускает ruff и базовые проверки файлов. Запустить вручную
для всего репозитория: `uv run pre-commit run --all-files`.

## Документация по коду

```bash
uv run pdoc bot -d google -o docs/api
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

Коммиты небольшие, по одной логической правке. `.env` и токены не коммитятся.

## Команда

| Участник | Зона ответственности |
|---|---|
| Неищенко А.А. (A) | LLM, эмбеддинги, Qdrant, PostgreSQL, загрузка документов, n8n (`worker/`) |
| Колычев М.Н. (B) | Telegram-бот, API, интерфейс, передача вопросов секретарю, тесты, развёртывание (`bot/`, `api/`) |
