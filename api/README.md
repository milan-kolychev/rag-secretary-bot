# api

REST API ядра (FastAPI). Контракт с ботом: `openapi.yaml`.

В MVP v1.0 реализованы `GET /health` и `POST /ask`. RAG-движок подключается переменной
`RAG_ENGINE` (см. `engine.py`); по умолчанию работает заглушка `stub`.

Ответственный: участник B. RAG-движок: участник A.
