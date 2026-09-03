from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from db import JobStatus


class BatchJob(BaseModel):
    job_id: UUID
    file_name: str
    status: JobStatus


class BatchCreated(BaseModel):
    batch_id: UUID
    jobs: list[BatchJob]


class JobResult(BatchJob):
    district_id: str
    result: dict[str, Any] | None = None
    error: str | None = None

    model_config = ConfigDict(from_attributes=True)


class BatchStatus(BaseModel):
    batch_id: UUID
    total: int
    done: int
    failed: int
    processing: int
    queued: int
    results: list[JobResult]
