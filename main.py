import logging
import tempfile
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from config import settings
from extract import extract_ppf


app = FastAPI(title="PPF Extraction Service", version="2.0.0")
logger = logging.getLogger("ppf-api")
PDF_CONTENT_TYPES = {"application/pdf", "application/x-pdf", "application/octet-stream"}
FRONTEND_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.get("/", include_in_schema=False)
def root() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


async def _save_pdf(upload: UploadFile, destination: Path) -> None:
    original_name = Path(upload.filename or "").name
    if not original_name or not original_name.lower().endswith(".pdf"):
        raise HTTPException(status_code=415, detail=f"{original_name or 'file'} is not a PDF")
    if upload.content_type and upload.content_type not in PDF_CONTENT_TYPES:
        raise HTTPException(status_code=415, detail=f"{original_name} is not a PDF")

    max_bytes = settings.max_upload_mb * 1024 * 1024
    size = 0
    header = b""
    with destination.open("wb") as output:
        while chunk := await upload.read(1024 * 1024):
            if len(header) < 5:
                header = (header + chunk)[:5]
            size += len(chunk)
            if size > max_bytes:
                raise HTTPException(
                    status_code=413,
                    detail=f"{original_name} exceeds {settings.max_upload_mb} MB",
                )
            output.write(chunk)

    if header != b"%PDF-":
        raise HTTPException(status_code=415, detail=f"{original_name} is not a valid PDF")


@app.post("/extract", response_model=dict[str, str])
async def extract_pdf(file: UploadFile = File(...)) -> dict[str, str]:
    """Extract fields and the embedded photo from one PDF without retaining it."""
    original_name = Path(file.filename or "document.pdf").name
    try:
        with tempfile.TemporaryDirectory(prefix="ppf-extract-") as temporary_dir:
            temporary_path = Path(temporary_dir) / "document.pdf"
            await _save_pdf(file, temporary_path)
            try:
                result = await run_in_threadpool(extract_ppf, str(temporary_path))
            except (RuntimeError, ValueError) as exc:
                raise HTTPException(status_code=422, detail=str(exc) or "PDF extraction failed") from exc
            except Exception as exc:
                logger.exception("Could not extract %s", original_name)
                raise HTTPException(status_code=422, detail="PDF extraction failed") from exc
    finally:
        await file.close()

    result["fileName"] = original_name
    return result
