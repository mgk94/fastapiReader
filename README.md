# PPF Extraction Service

A stateless FastAPI service that accepts one passport-application PDF and
returns the extracted fields and applicant photo as JSON. It does not use a
database, object storage, a task queue, or a background worker. Uploaded files
exist only in a temporary directory and are deleted before the request ends.

## Run with Docker

```bash
docker compose up --build
```

The API is available at <http://localhost:8000> and its OpenAPI documentation
is at <http://localhost:8000/docs>.

## Run locally

```bash
cp .env.example .env
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload
```

## API

Send one PDF per request:

```bash
curl -X POST http://localhost:8000/extract \
  -F 'file=@/path/to/application.pdf;type=application/pdf'
```

The response is the extracted JSON itself:

```json
{
  "applicationFileNumber": "...",
  "serviceType": "...",
  "surname": "...",
  "givenName": "...",
  "personImageBase64": "data:image/jpeg;base64,...",
  "fileName": "application.pdf"
}
```

Missing fields and a missing photo are returned as empty strings. Invalid or
unsupported PDFs return an HTTP error and are never retained.

### Processing larger batches

The calling application should send each PDF in a separate request, save each
successful response immediately, and retry individual failures. Use a stable
file ID in the calling application's database to make saving idempotent. A
small concurrency limit (for example, 5 requests) prevents a large upload from
exhausting CPU and memory.

The included browser UI demonstrates this approach for up to 100 files. It
runs at most five requests concurrently and retries temporary server or network
failures twice. It does not persist results.

## Configuration

| Environment variable | Default | Meaning |
| --- | ---: | --- |
| `MAX_UPLOAD_MB` | `20` | Maximum size of each uploaded PDF |

## Extraction behavior

`extract_ppf(file_path)` uses PyMuPDF for text, coordinates, and embedded
images. It first parses fixed labels from ordered text, then uses label
coordinates as a fallback for column-oriented forms. The largest plausible
embedded portrait is converted to JPEG and returned as a data URI.

The parser does not perform OCR. Validate it against representative PDFs and
extend its label or coordinate rules when a new form layout appears.
