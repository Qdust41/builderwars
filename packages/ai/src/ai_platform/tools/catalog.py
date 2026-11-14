"""Initial tool catalogue (definitions only; executors are TODO)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ai_platform.tools.base import Tool, ToolAccess, ToolRegistry
from domain.jobs import JobType
from domain.projects import Permission


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReadProjectFileArgs(_Args):
    project_id: str
    path: str = Field(min_length=1, max_length=512)

    @field_validator("path")
    @classmethod
    def _relative_inside_project(cls, value: str) -> str:
        parts = value.replace("\\", "/").split("/")
        if "\0" in value or value.startswith("/") or ".." in parts:
            raise ValueError("path must be relative to the project root without '..'")
        return value


class ReadDeviceLogsArgs(_Args):
    device_id: str
    limit: int = Field(default=100, ge=1, le=1000)


class GetDeviceStatusArgs(_Args):
    device_id: str


class ProposePatchArgs(_Args):
    project_id: str
    summary: str = Field(max_length=500)
    unified_diff: str = Field(max_length=200_000)


class RequestJobArgs(_Args):
    project_id: str
    job_type: JobType
    device_id: str | None = None


def default_registry() -> ToolRegistry:
    return ToolRegistry(
        [
            Tool(
                "read_project_file",
                "Read a file from the project's source tree.",
                ToolAccess.READ_ONLY,
                ReadProjectFileArgs,
                Permission.VIEW_PROJECT,
            ),
            Tool(
                "read_device_logs",
                "Read recent logs from a device in the project.",
                ToolAccess.READ_ONLY,
                ReadDeviceLogsArgs,
                Permission.VIEW_PROJECT,
            ),
            Tool(
                "get_device_status",
                "Get firmware version and connection status of a device.",
                ToolAccess.READ_ONLY,
                GetDeviceStatusArgs,
                Permission.VIEW_PROJECT,
            ),
            Tool(
                "propose_patch",
                "Propose a code change. Stored as a proposal for human review; never applied.",
                ToolAccess.PROPOSAL,
                ProposePatchArgs,
                Permission.RUN_AI,
            ),
            Tool(
                "request_build_or_test_job",
                "Request a firmware build or test run in an isolated worker. Needs approval.",
                ToolAccess.PRIVILEGED,
                RequestJobArgs,
                Permission.RUN_AI,
            ),
        ]
    )
