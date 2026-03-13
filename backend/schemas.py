from pydantic import BaseModel
from typing import Optional
from datetime import datetime


# ── Requests ────────────────────────────────────────────────────────────────

class GenerateRequest(BaseModel):
    description: str
    url: Optional[str] = ""


class CreateSuiteRequest(BaseModel):
    name: str
    description: Optional[str] = ""


class CreateTestRequest(BaseModel):
    name: str
    nl_description: str
    steps: list[dict]
    base_url: Optional[str] = ""


class RunTestRequest(BaseModel):
    headless: Optional[bool] = True


class SuiteRunRequest(BaseModel):
    """Body for POST /suites/{id}/run — used by CI and the UI."""
    base_url_override: Optional[str] = ""
    retries: Optional[int] = 1
    parallel: Optional[int] = 1
    fail_fast: Optional[bool] = False
    tags: Optional[list[str]] = []
    triggered_by: Optional[str] = "api"
    git_sha: Optional[str] = ""
    git_branch: Optional[str] = ""
    git_tag: Optional[str] = ""


class SuiteRunSchema(BaseModel):
    id: int
    suite_id: int
    status: str
    total: int
    passed: int
    failed: int
    healed: int
    duration: float
    triggered_by: str
    git_sha: str
    git_branch: str
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Responses ────────────────────────────────────────────────────────────────

class StepSchema(BaseModel):
    action: str
    target: str
    value: Optional[str] = ""
    description: Optional[str] = ""


class GeneratedTestSchema(BaseModel):
    name: str
    steps: list[StepSchema]


class SuiteSchema(BaseModel):
    id: int
    name: str
    description: str
    created_at: datetime

    model_config = {"from_attributes": True}


class TestCaseSchema(BaseModel):
    id: int
    suite_id: int
    name: str
    nl_description: str
    steps: str          # raw JSON string — frontend parses it
    base_url: str
    self_healed: bool
    last_status: str
    last_duration: float
    created_at: datetime

    model_config = {"from_attributes": True}


class RunSchema(BaseModel):
    id: int
    test_id: int
    status: str
    duration: float
    results: str        # raw JSON string
    screenshot_path: str
    created_at: datetime

    model_config = {"from_attributes": True}
