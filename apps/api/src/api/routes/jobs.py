from __future__ import annotations

from fastapi import APIRouter, status

from api.dependencies import JobServiceDep, UserDep
from api.schemas import JobCreate, JobOut

router = APIRouter(tags=["jobs"])


@router.post(
    "/projects/{project_id}/jobs", response_model=JobOut, status_code=status.HTTP_202_ACCEPTED
)
def create_job(project_id: str, body: JobCreate, user: UserDep, service: JobServiceDep) -> JobOut:
    """Queue a job. Execution happens in workers; no executors are implemented yet."""
    job = service.create_job(
        user_id=user.user_id,
        project_id=project_id,
        job_type=body.job_type,
        device_id=body.device_id,
        input_reference=body.input_reference,
    )
    return JobOut.of(job)


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: str, user: UserDep, service: JobServiceDep) -> JobOut:
    return JobOut.of(service.get_job(user_id=user.user_id, job_id=job_id))
