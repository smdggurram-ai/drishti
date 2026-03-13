"""
NeuralTest — FastAPI backend
Run with:  uvicorn main:app --reload --port 8000
"""
import json
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from database import init_db, get_db
from models import TestSuite, TestCase, TestRun
from schemas import (
    GenerateRequest, GeneratedTestSchema,
    CreateSuiteRequest, SuiteSchema,
    CreateTestRequest, TestCaseSchema,
    RunSchema,
)
from runner import TestRunner
from ai_engine import AIEngine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("main")


# ── App lifecycle ─────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    os.makedirs("screenshots", exist_ok=True)
    yield

app = FastAPI(title="NeuralTest API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve screenshots as static files
app.mount("/screenshots", StaticFiles(directory="screenshots"), name="screenshots")


# ── Singletons ────────────────────────────────────────────────────────────────

ai_engine = AIEngine()


# ── WebSocket connection manager ──────────────────────────────────────────────

class WSManager:
    def __init__(self):
        self._sockets: dict[str, WebSocket] = {}

    async def connect(self, key: str, ws: WebSocket):
        await ws.accept()
        self._sockets[key] = ws
        logger.info(f"WS connected: {key}")

    def disconnect(self, key: str):
        self._sockets.pop(key, None)
        logger.info(f"WS disconnected: {key}")

    async def send(self, key: str, data: dict):
        ws = self._sockets.get(key)
        if ws:
            try:
                await ws.send_json(data)
            except Exception as e:
                logger.warning(f"WS send failed for {key}: {e}")

ws_manager = WSManager()


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "version": "1.0.0"}


# ── AI Generation ─────────────────────────────────────────────────────────────

@app.post("/generate", response_model=GeneratedTestSchema, tags=["AI"])
async def generate_test(req: GenerateRequest):
    """Convert a plain-English description into structured test steps."""
    try:
        result = await ai_engine.generate_test(req.description, req.url or "")
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI generation failed: {e}")


# ── Suites ────────────────────────────────────────────────────────────────────

@app.post("/suites", response_model=SuiteSchema, tags=["Suites"])
async def create_suite(req: CreateSuiteRequest):
    db = get_db()
    suite = TestSuite(name=req.name, description=req.description or "")
    db.add(suite)
    db.commit()
    db.refresh(suite)
    return suite


@app.get("/suites", response_model=list[SuiteSchema], tags=["Suites"])
async def list_suites():
    db = get_db()
    return db.query(TestSuite).order_by(TestSuite.created_at.desc()).all()


@app.get("/suites/{suite_id}", response_model=SuiteSchema, tags=["Suites"])
async def get_suite(suite_id: int):
    db = get_db()
    suite = db.query(TestSuite).filter(TestSuite.id == suite_id).first()
    if not suite:
        raise HTTPException(404, "Suite not found")
    return suite


@app.delete("/suites/{suite_id}", tags=["Suites"])
async def delete_suite(suite_id: int):
    db = get_db()
    suite = db.query(TestSuite).filter(TestSuite.id == suite_id).first()
    if not suite:
        raise HTTPException(404, "Suite not found")
    db.delete(suite)
    db.commit()
    return {"deleted": True}


# ── Tests ─────────────────────────────────────────────────────────────────────

@app.post("/suites/{suite_id}/tests", response_model=TestCaseSchema, tags=["Tests"])
async def create_test(suite_id: int, req: CreateTestRequest):
    db = get_db()
    suite = db.query(TestSuite).filter(TestSuite.id == suite_id).first()
    if not suite:
        raise HTTPException(404, "Suite not found")
    test = TestCase(
        suite_id=suite_id,
        name=req.name,
        nl_description=req.nl_description,
        steps=json.dumps(req.steps),
        base_url=req.base_url or "",
    )
    db.add(test)
    db.commit()
    db.refresh(test)
    return test


@app.get("/suites/{suite_id}/tests", response_model=list[TestCaseSchema], tags=["Tests"])
async def list_tests(suite_id: int):
    db = get_db()
    return (
        db.query(TestCase)
        .filter(TestCase.suite_id == suite_id)
        .order_by(TestCase.created_at.desc())
        .all()
    )


@app.get("/tests/{test_id}", response_model=TestCaseSchema, tags=["Tests"])
async def get_test(test_id: int):
    db = get_db()
    test = db.query(TestCase).filter(TestCase.id == test_id).first()
    if not test:
        raise HTTPException(404, "Test not found")
    return test


@app.delete("/tests/{test_id}", tags=["Tests"])
async def delete_test(test_id: int):
    db = get_db()
    test = db.query(TestCase).filter(TestCase.id == test_id).first()
    if not test:
        raise HTTPException(404)
    db.delete(test)
    db.commit()
    return {"deleted": True}


# ── Test Runs ─────────────────────────────────────────────────────────────────

@app.post("/tests/{test_id}/run", response_model=RunSchema, tags=["Runs"])
async def start_run(test_id: int, background_tasks: BackgroundTasks):
    """Kick off a real Playwright browser run for a test case."""
    db = get_db()
    test = db.query(TestCase).filter(TestCase.id == test_id).first()
    if not test:
        raise HTTPException(404, "Test not found")

    run = TestRun(test_id=test_id, status="running")
    db.add(run)
    db.commit()
    db.refresh(run)

    background_tasks.add_task(_run_test_background, run.id, test_id)
    return run


async def _run_test_background(run_id: int, test_id: int):
    """Background task: execute the test and stream events over WebSocket."""
    db = get_db()
    test = db.query(TestCase).filter(TestCase.id == test_id).first()
    run  = db.query(TestRun).filter(TestRun.id == run_id).first()

    steps = json.loads(test.steps or "[]")
    runner = TestRunner(ai_engine=ai_engine)

    try:
        async for event in runner.run(steps, test.base_url, run_id):
            # Push every event to connected WebSocket clients
            await ws_manager.send(str(run_id), event)

            if event["type"] == "complete":
                run.status          = event["status"]
                run.duration        = event["duration"]
                run.results         = json.dumps(event["results"])
                run.screenshot_path = event.get("screenshot", "")

                # Persist healed selectors back to the test definition
                if event.get("healed_steps"):
                    test.steps       = json.dumps(event["healed_steps"])
                    test.self_healed = True

                test.last_status   = event["status"]
                test.last_duration = event["duration"]
                db.commit()

    except Exception as e:
        logger.error(f"Run {run_id} crashed: {e}", exc_info=True)
        run.status = "failed"
        run.results = json.dumps([{"error": str(e)}])
        db.commit()
        await ws_manager.send(str(run_id), {"type": "complete", "status": "failed", "error": str(e)})


@app.get("/tests/{test_id}/runs", response_model=list[RunSchema], tags=["Runs"])
async def list_runs(test_id: int):
    db = get_db()
    return (
        db.query(TestRun)
        .filter(TestRun.test_id == test_id)
        .order_by(TestRun.created_at.desc())
        .limit(20)
        .all()
    )


@app.get("/runs/{run_id}", response_model=RunSchema, tags=["Runs"])
async def get_run(run_id: int):
    db = get_db()
    run = db.query(TestRun).filter(TestRun.id == run_id).first()
    if not run:
        raise HTTPException(404)
    return run


# ── Suite-level CI runs ───────────────────────────────────────────────────────

from suite_runner import SuiteRunner
from reporter import write_junit, write_json
from schemas import SuiteRunRequest, SuiteRunSchema

@app.post("/suites/{suite_id}/run", tags=["CI"])
async def run_suite(suite_id: int, req: SuiteRunRequest, background_tasks: BackgroundTasks):
    """
    Trigger a full suite run (used by CI or the UI's 'Run All' button).
    Returns immediately with a suite_run_id. Poll /suite-runs/{id} for status.
    """
    from models import SuiteRun
    db = get_db()
    suite = db.query(TestSuite).filter(TestSuite.id == suite_id).first()
    if not suite:
        raise HTTPException(404, "Suite not found")

    suite_run = SuiteRun(
        suite_id=suite_id,
        status="running",
        triggered_by=req.triggered_by or "api",
        base_url_override=req.base_url_override or "",
        git_sha=req.git_sha or "",
        git_branch=req.git_branch or "",
        git_tag=req.git_tag or "",
    )
    db.add(suite_run)
    db.commit()
    db.refresh(suite_run)

    background_tasks.add_task(_run_suite_background, suite_run.id, suite_id, req)
    return {"suite_run_id": suite_run.id, "status": "running"}


async def _run_suite_background(suite_run_id: int, suite_id: int, req):
    from models import SuiteRun
    db = get_db()
    suite_run = db.query(SuiteRun).filter(SuiteRun.id == suite_run_id).first()
    suite = db.query(TestSuite).filter(TestSuite.id == suite_id).first()
    tests_orm = db.query(TestCase).filter(TestCase.suite_id == suite_id).all()

    tests = [
        {"id": t.id, "name": t.name, "steps": t.steps,
         "base_url": t.base_url, "tags": t.tags, "retry_count": t.retry_count}
        for t in tests_orm
    ]

    runner = SuiteRunner(
        ai_engine=ai_engine,
        base_url_override=req.base_url_override or "",
        max_retries=req.retries or 1,
        parallel=req.parallel or 1,
        fail_fast=req.fail_fast or False,
        tags=req.tags or [],
        report_dir="test-results",
        triggered_by=req.triggered_by or "api",
        git_sha=req.git_sha or "",
        git_branch=req.git_branch or "",
        git_tag=req.git_tag or "",
    )

    async def on_done(tr):
        await ws_manager.send(f"suite_{suite_run_id}", {
            "type": "test_complete",
            "test_id": tr.test_id,
            "test_name": tr.test_name,
            "status": tr.status,
            "duration": tr.duration,
        })

    try:
        result = await runner.run_suite(suite.id, suite.name, tests, on_test_complete=on_done)
        os.makedirs("test-results", exist_ok=True)
        json_path  = f"test-results/suite_{suite_run_id}.json"
        junit_path = f"test-results/suite_{suite_run_id}_junit.xml"
        write_json(result, json_path)
        write_junit(result, junit_path)

        suite_run.status       = result.status
        suite_run.total        = result.total
        suite_run.passed       = result.passed
        suite_run.failed       = result.failed
        suite_run.healed       = result.healed
        suite_run.duration     = result.duration
        suite_run.report_path  = json_path
        suite_run.junit_path   = junit_path
        db.commit()

        # Persist individual run records + healed selectors
        for tr in result.test_results:
            run = TestRun(
                test_id=tr.test_id, suite_run_id=suite_run_id,
                status=tr.status, attempt=tr.attempt, duration=tr.duration,
                results=json.dumps(tr.step_results),
                screenshot_path=tr.screenshot_path,
                triggered_by=req.triggered_by or "api",
            )
            db.add(run)
            if tr.healed_steps:
                test = db.query(TestCase).filter(TestCase.id == tr.test_id).first()
                if test:
                    test.steps = json.dumps(tr.healed_steps)
                    test.self_healed = True
            test = db.query(TestCase).filter(TestCase.id == tr.test_id).first()
            if test:
                test.last_status = tr.status
                test.last_duration = tr.duration
        db.commit()

    except Exception as e:
        logger.error(f"Suite run {suite_run_id} crashed: {e}", exc_info=True)
        suite_run.status = "failed"
        db.commit()

    await ws_manager.send(f"suite_{suite_run_id}", {
        "type": "suite_complete",
        "status": suite_run.status,
        "passed": suite_run.passed,
        "failed": suite_run.failed,
        "healed": suite_run.healed,
        "duration": suite_run.duration,
    })


@app.get("/suite-runs/{suite_run_id}", tags=["CI"])
async def get_suite_run(suite_run_id: int):
    from models import SuiteRun
    db = get_db()
    sr = db.query(SuiteRun).filter(SuiteRun.id == suite_run_id).first()
    if not sr:
        raise HTTPException(404)
    return {
        "id": sr.id, "suite_id": sr.suite_id, "status": sr.status,
        "total": sr.total, "passed": sr.passed, "failed": sr.failed,
        "healed": sr.healed, "duration": sr.duration,
        "triggered_by": sr.triggered_by,
        "git_sha": sr.git_sha, "git_branch": sr.git_branch,
        "created_at": sr.created_at,
    }


@app.get("/suites/{suite_id}/history", tags=["CI"])
async def suite_run_history(suite_id: int, limit: int = 20):
    """Return the last N suite runs for a suite — useful for trend charts."""
    from models import SuiteRun
    db = get_db()
    rows = (
        db.query(SuiteRun)
        .filter(SuiteRun.suite_id == suite_id)
        .order_by(SuiteRun.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {"id": r.id, "status": r.status, "passed": r.passed,
         "failed": r.failed, "healed": r.healed, "duration": r.duration,
         "git_sha": r.git_sha, "git_branch": r.git_branch,
         "triggered_by": r.triggered_by, "created_at": r.created_at}
        for r in rows
    ]


# ── WebSocket ─────────────────────────────────────────────────────────────────

@app.websocket("/ws/{run_id}")
async def websocket_run(websocket: WebSocket, run_id: str):
    """Connect before starting a run — events stream in real-time."""
    await ws_manager.connect(run_id, websocket)
    try:
        while True:
            # Keep connection alive; client can send pings
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(run_id)
