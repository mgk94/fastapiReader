import logging
import tempfile
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.exc import DBAPIError

from config import settings
from db import Job, JobStatus, SessionLocal, engine
from extract import extract_ppf
from storage import object_storage


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("ppf-worker")
MAX_ATTEMPTS = 3


def claim_job() -> tuple[uuid.UUID, str, str, datetime, int] | None:
    """Claim exactly one job; SKIP LOCKED lets other worker copies proceed."""
    with SessionLocal.begin() as session:
        job = session.scalar(
            select(Job)
            .where(Job.status == JobStatus.queued)
            .order_by(Job.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if job is None:
            return None
        claimed_at = datetime.now(timezone.utc)
        job.status = JobStatus.processing
        job.locked_at = claimed_at
        job.attempts += 1
        job.error = None
        return job.id, job.object_key, job.file_name, claimed_at, job.attempts


def complete_job(job_id: uuid.UUID, claimed_at: datetime, result: dict[str, str]) -> None:
    with SessionLocal.begin() as session:
        session.execute(
            update(Job)
            .where(
                Job.id == job_id,
                Job.status == JobStatus.processing,
                Job.locked_at == claimed_at,
            )
            .values(
                status=JobStatus.done,
                result=result,
                error=None,
                locked_at=None,
                updated_at=datetime.now(timezone.utc),
            )
        )


def fail_or_retry_job(
    job_id: uuid.UUID, claimed_at: datetime, attempts: int, error: Exception
) -> None:
    message = str(error).strip() or error.__class__.__name__
    # Avoid unbounded database rows while retaining useful diagnostics.
    message = message[:4000]
    final_failure = attempts >= MAX_ATTEMPTS
    with SessionLocal.begin() as session:
        session.execute(
            update(Job)
            .where(
                Job.id == job_id,
                Job.status == JobStatus.processing,
                Job.locked_at == claimed_at,
            )
            .values(
                status=JobStatus.failed if final_failure else JobStatus.queued,
                error=message if final_failure else None,
                locked_at=None,
                updated_at=datetime.now(timezone.utc),
            )
        )


def sweep_stale_jobs() -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=settings.stale_job_seconds)
    with SessionLocal.begin() as session:
        result = session.execute(
            update(Job)
            .where(Job.status == JobStatus.processing, Job.locked_at < cutoff)
            .values(
                status=JobStatus.queued,
                locked_at=None,
                updated_at=datetime.now(timezone.utc),
            )
        )
        return result.rowcount


def run() -> None:
    next_sweep = 0.0
    logger.info("Worker started")
    while True:
        try:
            now = time.monotonic()
            if now >= next_sweep:
                swept = sweep_stale_jobs()
                if swept:
                    logger.warning("Reset %d stale processing job(s)", swept)
                next_sweep = now + settings.sweeper_interval_seconds

            claimed = claim_job()
            if claimed is None:
                time.sleep(settings.worker_poll_seconds)
                continue

            job_id, object_key, file_name, claimed_at, attempts = claimed
            logger.info("Processing job %s (attempt %d)", job_id, attempts)
            try:
                with tempfile.TemporaryDirectory(prefix="ppf-worker-") as temporary_dir:
                    local_pdf = Path(temporary_dir) / "document.pdf"
                    object_storage.download_pdf(object_key, local_pdf)
                    result = extract_ppf(str(local_pdf))
                result["fileName"] = file_name
                complete_job(job_id, claimed_at, result)
                logger.info("Completed job %s", job_id)
            except DBAPIError:
                # Let the outer handler reconnect. The stale sweeper will recover
                # the processing row if completion was not committed.
                raise
            except Exception as exc:
                fail_or_retry_job(job_id, claimed_at, attempts, exc)
                logger.exception("Job %s extraction failed", job_id)
        except DBAPIError as exc:
            logger.warning("Database unavailable (%s); reconnecting shortly", exc)
            engine.dispose()
            time.sleep(settings.database_retry_seconds)
        except KeyboardInterrupt:
            logger.info("Worker stopped")
            return
        except Exception:
            # A malformed job or unexpected bug must not terminate the worker.
            logger.exception("Unexpected worker-loop error")
            time.sleep(settings.worker_poll_seconds)


if __name__ == "__main__":
    run()
