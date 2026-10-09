
# PPF Extraction Service

A minimal FastAPI service that saves uploaded passport-application PDFs in
MinIO, uses PostgreSQL as both the durable work queue and result store, and
processes jobs in one or more standalone workers. There is no Redis, Celery, or
in-process queue.

## Run end-to-end with Docker Compose

Build and start MinIO, PostgreSQL, the API, and one worker:

```bash
docker compose up -d --build
```

Apply the database migration (once per deployment/revision):

```bash
docker compose run --rm api alembic upgrade head
```

The API is now available at <http://localhost:8000>; interactive OpenAPI docs
are at <http://localhost:8000/docs>. The local MinIO console is available at
<http://localhost:9001> using the development credentials in
`docker-compose.yml`.

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

Start PostgreSQL and MinIO (the Compose services can be used), then run:

```bash
alembic upgrade head
uvicorn main:app --reload
```

In another terminal:

```bash
source .venv/bin/activate
python worker.py
```

The API first validates each PDF in a temporary local file and then uploads it
to MinIO. PostgreSQL stores only the MinIO object key and extracted JSON, never
PDF bytes. A worker downloads the object to a temporary file for extraction and
deletes that temporary file afterward.

For Kubernetes, configure `MINIO_ENDPOINT` with the S3 API endpoint (normally
port 9000, not the console on port 9001). Inject `MINIO_ACCESS_KEY` and
`MINIO_SECRET_KEY` from a Kubernetes Secret rather than committing them to the
repository. Set `MINIO_AUTO_CREATE_BUCKET=false` when the bucket is provisioned
separately and the application identity should not have bucket-creation access.

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
and a five-minute stale-job threshold. `MINIO_ENDPOINT` accepts either a URL
such as `https://minio.example.com` or a `host:port` value.
# fastapiReader
