import logging
import re
import tempfile
import uuid
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from config import settings
from db import Job, JobStatus, get_db
from schemas import BatchCreated, BatchJob, BatchStatus, JobResult
from storage import ObjectStorageError, object_storage


app = FastAPI(title="PPF Extraction Service", version="1.0.0")
logger = logging.getLogger("ppf-api")
PDF_CONTENT_TYPES = {"application/pdf", "application/x-pdf", "application/octet-stream"}
FRONTEND_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.get("/", include_in_schema=False)
def root() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


def _job_result(job: Job) -> JobResult:
    return JobResult(
        job_id=job.id,
        file_name=job.file_name,
        district_id=job.district_id,
        status=job.status,
        result=job.result,
        error=job.error,
    )


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
            if not header:
                header = chunk[:5]
            size += len(chunk)
            if size > max_bytes:
                raise HTTPException(
                    status_code=413,
                    detail=f"{original_name} exceeds {settings.max_upload_mb} MB",
                )
            output.write(chunk)
    if header != b"%PDF-":
        raise HTTPException(status_code=415, detail=f"{original_name} is not a valid PDF")


async def _delete_objects_quietly(object_keys: list[str]) -> None:
    if not object_keys:
        return
    try:
        await run_in_threadpool(object_storage.delete_objects, object_keys)
    except Exception:
        logger.exception("Could not remove MinIO objects after a failed batch")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post(
    "/districts/{district_id}/batches",
    response_model=BatchCreated,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_batch(
    district_id: str,
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
) -> BatchCreated:
    if not 1 <= len(files) <= 100:
        raise HTTPException(status_code=400, detail="Upload between 1 and 100 PDFs")
    if not district_id.strip():
        raise HTTPException(status_code=400, detail="district_id must not be empty")

    batch_id = uuid.uuid4()
    uploaded_object_keys: list[str] = []
    jobs: list[Job] = []
    try:
        with tempfile.TemporaryDirectory(prefix="ppf-upload-") as temporary_dir:
            for upload in files:
                job_id = uuid.uuid4()
                original_name = Path(upload.filename or "document.pdf").name
                safe_name = (
                    re.sub(r"[^A-Za-z0-9._-]+", "_", original_name)[:150]
                    or "document.pdf"
                )
                temporary_path = Path(temporary_dir) / f"{job_id}.pdf"
                object_key = f"batches/{batch_id}/{job_id}_{safe_name}"
                await _save_pdf(upload, temporary_path)
                await run_in_threadpool(object_storage.upload_pdf, temporary_path, object_key)
                uploaded_object_keys.append(object_key)
                jobs.append(
                    Job(
                        id=job_id,
                        batch_id=batch_id,
                        district_id=district_id,
                        file_name=original_name,
                        object_key=object_key,
                        status=JobStatus.queued,
                    )
                )

        # A single commit makes every row in the batch visible atomically.
        db.add_all(jobs)
        db.commit()
    except HTTPException:
        db.rollback()
        await _delete_objects_quietly(uploaded_object_keys)
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        await _delete_objects_quietly(uploaded_object_keys)
        raise HTTPException(status_code=503, detail="Database is unavailable") from exc
    except ObjectStorageError as exc:
        db.rollback()
        await _delete_objects_quietly(uploaded_object_keys)
        raise HTTPException(status_code=503, detail="Object storage is unavailable") from exc
    except Exception:
        db.rollback()
        await _delete_objects_quietly(uploaded_object_keys)
        raise
    finally:
        for upload in files:
            await upload.close()

    return BatchCreated(
        batch_id=batch_id,
        jobs=[BatchJob(job_id=job.id, file_name=job.file_name, status=job.status) for job in jobs],
    )


@app.get("/batches/{batch_id}", response_model=BatchStatus)
def get_batch(batch_id: uuid.UUID, db: Session = Depends(get_db)) -> BatchStatus:
    jobs = list(db.scalars(select(Job).where(Job.batch_id == batch_id).order_by(Job.created_at)))
    if not jobs:
        raise HTTPException(status_code=404, detail="Batch not found")
    counts = {state.value: 0 for state in JobStatus}
    for job in jobs:
        counts[job.status.value] += 1
    return BatchStatus(
        batch_id=batch_id,
        total=len(jobs),
        done=counts["done"],
        failed=counts["failed"],
        processing=counts["processing"],
        queued=counts["queued"],
        results=[_job_result(job) for job in jobs],
    )


@app.get("/jobs/{job_id}", response_model=JobResult)
def get_job(job_id: uuid.UUID, db: Session = Depends(get_db)) -> JobResult:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return _job_result(job)
