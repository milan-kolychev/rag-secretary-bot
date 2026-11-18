# RAG persistence and deployment

## Audit and scope

The original project had aiogram handlers, a bearer-protected FastAPI `/ask`, a synchronous
in-process RAG worker, BGE-M3 dense embeddings, Qdrant retrieval, Ollama generation and
TXT/DOCX/PDF extraction. PostgreSQL existed only as a Compose service. There were no
SQLAlchemy models, Alembic migrations, history, shared queue or implemented `/documents`.
The previous indexing CLI deleted old chunks before writing replacements and used a
checksum-derived integer as its version.

The architecture is still Bot → HTTP API → in-process Worker → Qdrant/Ollama. API and
Worker use PostgreSQL. The bot imports neither persistence nor model code. Redis and
additional model weights have not been introduced. `core/` holds only shared settings,
SQLAlchemy persistence and request orchestration; document processing stays in `worker/`.

## Configuration

Copy `.env.example` to `.env` only if you do not already have one. Never overwrite an
existing secrets file. All settings are environment variables, also read from `.env`.

| Variable | Default | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | unset in code | SQLAlchemy PostgreSQL URL; required for real RAG; example URL contains a placeholder password |
| `CHAT_HISTORY_MESSAGES` | `5` | Individual prior messages, including user and assistant, never five pairs |
| `CHAT_HISTORY_RETENTION_HOURS` | `48` | Retention for history and terminal request text/results |
| `CHAT_HISTORY_MAX_TOKENS` | `400` | Qwen token budget for retained history and its template overhead |
| `RAG_CONTEXT_MAX_TOKENS` | `1200` | Qwen token budget for labeled document fragments |
| `NUM_CTX` | `4096` | Fixed Ollama context size, including reserved output |
| `NUM_PREDICT` | `256` | Maximum generated tokens; must be smaller than context |
| `QWEN_TOKENIZER` | `Qwen/Qwen3.5-9B` | Official tokenizer repository or a local tokenizer-only directory |
| `QUEUE_MAX_SIZE` | `20` | Maximum accepted queued plus running requests |
| `QUEUE_POLL_INTERVAL` | `0.25` | Idle worker poll interval in seconds |
| `DELIVERY_TIMEOUT` | `120` | Terminal delivery lease expiry when a bot crashes before acknowledgement |
| `OLLAMA_TIMEOUT` | `120` | Model HTTP read timeout in seconds |
| `RAG_TIMEOUT` | `130` | Processing deadline after dequeue, excludes time waiting in the queue |
| `ANSWER_TIMEOUT` | `30` | Per HTTP operation for the bot, not total queue wait |
| `OLLAMA_URL` | `http://127.0.0.1:11434` | Change to the other PC's Ollama address |
| `QDRANT_URL` | `http://127.0.0.1:6333` | Change to the vector server address |
| `EMBED_DEVICE` | `cpu` | Keeps BGE-M3 off the 12 GB GPU used by Qwen |

`RETRIEVAL_LIMIT=20`, `PROMPT_CHUNKS=4` and the existing `MIN_DENSE_SCORE=0.60`
remain supported. The score threshold is provisional and needs calibration on faculty
documents; it is not a probability of correctness.

Use a PostgreSQL URL such as
`postgresql+psycopg://fpi:URL_ENCODED_PASSWORD@192.168.1.50:5432/fpi_rag`.
Use the appropriate private-network addresses for Ollama and Qdrant too. Ensure those
services accept connections from the API machine. Use TLS or a trusted private tunnel
when traffic crosses an untrusted network. Do not expose bearer-protected endpoints or
database/model ports publicly without transport and access controls.

## Windows startup with services on the other PC

Run these commands from the extracted repository directory, with Python 3.12 and uv installed:

```powershell
uv sync --frozen
if (-not (Test-Path -LiteralPath .env)) { Copy-Item -LiteralPath .env.example -Destination .env }
notepad .env
```

Fill `BOT_TOKEN`, `API_TOKEN`, `DATABASE_URL`, `QDRANT_URL`, and `OLLAMA_URL`.
Keep `RAG_ENGINE=worker.rag:create_engine`. API and bot must use the same service token.
Keep `API_URL=http://127.0.0.1:8000` if the bot and API run together, even when the
database and model are remote. Leave `EMBED_DEVICE=cpu` for the target hardware.

Apply migrations once during deployment, then start API:

```powershell
uv run alembic upgrade head
uv run python -m api
```

In another PowerShell window in the same repository:

```powershell
uv run python -m bot
```

There is no separate worker process: `worker.rag:create_engine` is loaded inside API,
as in the original architecture. Use one API process on the specified 16 GB machine to
avoid loading multiple BGE-M3 instances. PostgreSQL locks coordinate requests if multiple
API processes are deployed deliberately; they must share one PostgreSQL database, one
Qdrant collection and the same models/settings. Run migrations once before all replicas.

On the Ollama PC, set `OLLAMA_NUM_PARALLEL=1` before starting its server. This also
prevents overlapping remote generation if an HTTP client disconnects while Ollama is
still working. Example for a trusted LAN (adjust the bind address to that PC):

```powershell
$env:OLLAMA_HOST = "192.168.1.50:11434"
$env:OLLAMA_NUM_PARALLEL = "1"
ollama serve
```

In a second window on that PC, provision the required model if it is not already present:

```powershell
ollama pull qwen3.5:9b
```

Confirm the deployed model is the intended Q4_K_M variant using its model information.
The local API downloads BGE-M3 weights and tokenizer files on first real startup, and
Qwen tokenizer files only; it does not load Qwen weights into Python. Provision/cache
these files before an offline deployment. `QWEN_TOKENIZER` can point to a local directory.

For an optional all-local infrastructure setup, Compose includes PostgreSQL and Qdrant:

```powershell
docker compose up -d postgres qdrant
```

This command is unnecessary when services are hosted elsewhere. Compose API settings
override endpoints for its own network; for remote services use native commands above
or adjust the Compose environment explicitly. The Docker API image now includes `core`,
`worker` and migrations, which were missing before.

## Queue and delivery API

Every endpoint below requires `Authorization: Bearer <API_TOKEN>`.

* `POST /requests` accepts `{question, user_id, chat_id}` and returns `202` with
  `request_id`. Signed chat IDs support groups. Omitting `chat_id` preserves legacy
  private-chat behavior by using `user_id`.
* `GET /requests/{request_id}` returns `queued`, `running`, `done`, `failed` or
  `cancelled`, plus `result` or an error code. A successful result has the existing
  `/ask` response shape. Polling has no total generation/queue deadline.
* `DELETE /requests/{request_id}` acknowledges final delivery. Queued work is cancelled;
  running work is acknowledged and releases busy state when it finishes. Calls are
  idempotent. The bot invokes this in `finally` after handling final Telegram delivery.
* Admission returns `409 conflict` for a busy chat/user or `429 queue_full` when full.
* `POST /ask` remains compatible and uses the same queue, but is a long-lived request;
  clients must account for queue time. The production bot uses the polling endpoints.

Admission, capacity check and busy state are atomic under a PostgreSQL advisory lock.
The worker claims the oldest committed sequence under a different global execution lock.
Only one generation is active. Failures do not stop subsequent jobs. Python thread
timeouts publish an error, but the execution lock remains held until the thread exits.
Requests left in `running` after a process crash are failed rather than blindly replayed
with an ambiguous generation outcome. Queued jobs survive API restarts. Delivery locks
expire after the configured terminal lease if the bot disappears.

The bot sets its local busy guard before its first await, sends the progress message,
suppresses repeated spam notifications, and edits progress into the final answer or error.
Long messages respect Telegram UTF-16 limits. Flood-control edit retries are bounded.
If editing fails, it attempts to delete progress and send the answer. If Telegram denies
both editing and deletion, a stale progress message cannot be removed by the application;
the failure is logged and user locks are still released.

## Documents

Upload using multipart `file` and `title`; include `doc_id` only for an intentional
update. Equal filenames or titles never trigger replacement. Without `doc_id`, a separate
logical document is created. Retry deduplication is scoped to `(doc_id, SHA-256 bytes)`.
Keep the returned document ID for subsequent updates.

```powershell
$headers = @{ Authorization = "Bearer $env:API_TOKEN" }
# PowerShell 7; set API_TOKEN in this terminal or enter it securely before this example.
$first = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/documents `
  -Headers $headers -Form @{ file = Get-Item .\documents\session_2027_demo.txt; title = "Academic calendar" }
$docId = $first.document_id
Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8000/documents/$docId/versions" -Headers $headers
# Upload an edited file to the SAME logical document:
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/documents `
  -Headers $headers -Form @{ file = Get-Item .\documents\session_2027_demo.txt; title = "Academic calendar"; doc_id = $docId }
```

The upload endpoint is synchronous and returns `201` with `status=indexed` or
`status=failed`; allow time for waiting for inference/indexing and embeddings. There was
no implemented `/documents` endpoint to break; the original design-only contract planned
an asynchronous `202` response and filename/title replacement, and has been updated.
Do not retry an ambiguous new-document upload without its stable ID. Supply a client-chosen
UUID as `doc_id` on the first upload when client retries must also be idempotent.

* `GET /documents/{document_id}` and `GET /documents/{document_id}/versions` return
  the authoritative active version and version metadata.
* `POST /documents/{document_id}/versions/{version}/retry` processes the durable original
  after an indexing failure/interruption. Re-uploading the same bytes and `doc_id` also
  retries the same version. Successful duplicate uploads do not create new versions.
* `POST /documents/{document_id}/versions/{version}/restore` rebuilds an indexed historical
  version from its original source before activating it. Restoring the current version is
  a no-op. A failure before activation leaves the previous SQL pointer intact.

CLI uses the same pipeline:

```powershell
uv run python -m worker.index_document --file .\documents\session_2027_demo.txt
uv run python -m worker.index_document --file .\documents\session_2027_demo.txt --doc-id "RETURNED-UUID"
```

The unsafe `--replace` deletion path is rejected. Legacy Qdrant points without matching
PostgreSQL metadata are intentionally excluded. Reingest their original files through this
pipeline; pass their original UUID as `--doc-id` if stable source identifiers must remain.
No existing vectors or database records are deleted for this transition.

New chunks are acknowledged and counted before SQL activation. Retrieval filters Qdrant
by the SQL `(doc_id, active_version)` pairs as well as payload `is_active`. A staging
version therefore cannot leak, even if its flags are true, and stale flags on old versions
cannot make old text visible. SQL activation is the visibility boundary; a failed cleanup
of historical Qdrant flags does not expose stale versions. The same lock serializes
retrieval snapshots and activation. Original files and old versions remain stored for
retry and restoration. Metadata listings defer loading original file blobs.

## Token budgets and model behavior

`PromptBuilder` renders the official Qwen3.5-9B chat template with
`enable_thinking=False`, counts its actual token IDs, reserves `NUM_PREDICT`, and removes
old history messages before low-ranked fragments when the overall window is tight. It
does not truncate the current question or system instructions, and it never increases
`NUM_CTX`. A request that cannot fit those essentials fails explicitly. History/fragment
caps may remove more context than the nominal five-message count.

The rendered prompt is sent to Ollama `/api/generate` with `raw=true`, `think=false`,
and explicit context/output limits, so Ollama does not apply a second chat template.
History provides topic context only; current documents remain the authority for facts.
Follow-up retrieval includes the current question first and previous user questions,
which helps resolve references without an additional rewriting model.

Sources: [official Qwen tokenizer and template](https://huggingface.co/Qwen/Qwen3.5-9B/blob/main/tokenizer_config.json),
[Ollama generate API](https://docs.ollama.com/api/generate).
The deployed GGUF must use the tokenizer matching the configured official model; quantization
does not require different tokenization. Model quality and deployed GGUF equivalence still
need validation on the hosting PC.

Logs record queue/processing durations, input token counts, retained history/chunk counts,
retrieved and used document IDs/versions, and Ollama `prompt_eval_count`/`eval_count`.
They exclude full student questions, answer text and credentials.

## Verification policy

Run isolated tests without external services:

```powershell
uv run pytest -q
uv run python -m compileall -q api bot core worker migrations
```

Tests use in-memory persistence/vector substitutes, deterministic embedding/model doubles,
mocked PostgreSQL connections and Telegram sessions, and HTTP ASGI/MockTransport clients.
They do not connect to PostgreSQL, Ollama, Qdrant or Telegram servers. An optional tokenizer-only
test is skipped unless `TEST_QWEN_TOKENIZER` points at locally provisioned official tokenizer
files. It loads no model weights. Migration operations are checked with mocked Alembic operations;
no database migration is executed in the test suite.

Live migration execution, remote process failover, model/tokenizer equivalence, retrieval
quality and Telegram delivery are deployment checks on the hosting machines, not claims
made by these mock tests. The original feedback/ticket/search design endpoints outside
this task are not implemented by this change. `worker.qwen_only` remains a legacy diagnostic
engine and is not the production RAG configuration.
