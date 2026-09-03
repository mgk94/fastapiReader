# PPF Extraction Service

A minimal FastAPI service that saves uploaded passport-application PDFs to disk,
uses PostgreSQL as both the durable work queue and result store, and processes
jobs in one or more standalone workers. There is no Redis, Celery, or in-process
queue.

## Run end-to-end with Docker Compose

Build and start PostgreSQL, the API, and one worker:

```bash
docker compose up -d --build
```

Apply the database migration (once per deployment/revision):

```bash
docker compose run --rm api alembic upgrade head
```

The API is now available at <http://localhost:8000>; interactive OpenAPI docs
are at <http://localhost:8000/docs>.

Upload one or more PDFs (repeat `files` up to 100 times):

```bash
curl -X POST http://localhost:8000/districts/ernakulam/batches \
  -F 'files=@/path/to/application-1.pdf;type=application/pdf' \
  -F 'files=@/path/to/application-2.pdf;type=application/pdf'
```

The response is HTTP 202 and contains a `batch_id` plus one `job_id` per PDF.
Use those IDs to query progress and results:

```bash
curl http://localhost:8000/batches/BATCH_UUID
curl http://localhost:8000/jobs/JOB_UUID
```

Scale workers without changing the queue or API:

```bash
docker compose up -d --scale worker=4
```

Every worker claims one queued row using `FOR UPDATE SKIP LOCKED`, so concurrent
copies do not normally process the same job. A claim is committed before PDF
work starts. Failed extractions retry up to three attempts, and a periodic
sweeper requeues claims older than five minutes after a worker crash. The
`locked_at` value also acts as a claim token, preventing an old timed-out worker
from overwriting a newer worker's result.

## Local development

Copy the sample environment and install dependencies:

```bash
cp .env.example .env
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Start PostgreSQL (the Compose database can be used), then run:

```bash
alembic upgrade head
uvicorn main:app --reload
```

In another terminal:

```bash
source .venv/bin/activate
python worker.py
```

`UPLOAD_DIR` must refer to storage visible to both API and workers. Compose uses
a shared named volume. The database stores only the path and extracted JSON,
never PDF bytes.

## Extraction behavior

`extract_ppf(file_path)` uses PyMuPDF for text, coordinates, and embedded images.
It first parses fixed labels from ordered text and then uses label coordinates
as a fallback for column-oriented forms. Missing fields and a missing photo are
returned as empty strings. The largest plausible embedded portrait is converted
to JPEG and returned with a `data:image/jpeg;base64,` prefix.

The parser intentionally does not perform OCR. Because PPF layouts can vary by
generator/version, validate `extract.py` against representative real PDFs and
add label or coordinate rules when a new layout appears.

## Configuration

All settings are environment variables; see `.env.example`. Notable defaults
are a 20 MB per-PDF limit, one-second idle polling, three extraction attempts,
and a five-minute stale-job threshold.
