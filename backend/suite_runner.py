"""
suite_runner.py — Coordinates running an entire suite of tests.
Used by both the CI CLI and the FastAPI backend.
"""
import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Optional

from runner import TestRunner
from ai_engine import AIEngine

logger = logging.getLogger("suite_runner")


@dataclass
class TestResult:
    test_id: int
    test_name: str
    status: str           # passed / failed / self-healed / skipped
    duration: float
    attempt: int          # which retry attempt succeeded (or last attempt if failed)
    step_results: list[dict] = field(default_factory=list)
    healed_steps: Optional[list[dict]] = None
    screenshot_path: str = ""
    error: str = ""


@dataclass
class SuiteResult:
    suite_id: int
    suite_name: str
    status: str           # passed / failed / partial
    total: int
    passed: int
    failed: int
    healed: int
    skipped: int
    duration: float
    test_results: list[TestResult] = field(default_factory=list)
    base_url_override: str = ""
    git_sha: str = ""
    git_branch: str = ""
    git_tag: str = ""

    @property
    def pass_rate(self) -> float:
        if self.total == 0:
            return 0.0
        return round((self.passed + self.healed) / self.total * 100, 1)

    def to_dict(self) -> dict:
        return {
            "suite_id": self.suite_id,
            "suite_name": self.suite_name,
            "status": self.status,
            "summary": {
                "total": self.total,
                "passed": self.passed,
                "failed": self.failed,
                "healed": self.healed,
                "skipped": self.skipped,
                "pass_rate": self.pass_rate,
                "duration": round(self.duration, 2),
            },
            "environment": {
                "base_url_override": self.base_url_override,
                "git_sha": self.git_sha,
                "git_branch": self.git_branch,
                "git_tag": self.git_tag,
            },
            "tests": [
                {
                    "test_id": t.test_id,
                    "name": t.test_name,
                    "status": t.status,
                    "duration": round(t.duration, 2),
                    "attempt": t.attempt,
                    "error": t.error,
                    "screenshot": t.screenshot_path,
                    "steps": t.step_results,
                }
                for t in self.test_results
            ],
        }


class SuiteRunner:
    def __init__(
        self,
        ai_engine: AIEngine,
        base_url_override: str = "",
        max_retries: int = 1,
        parallel: int = 1,
        fail_fast: bool = False,
        tags: Optional[list[str]] = None,
        report_dir: str = "test-results",
        headless: bool = True,
        triggered_by: str = "cli",
        git_sha: str = "",
        git_branch: str = "",
        git_tag: str = "",
    ):
        self.ai = ai_engine
        self.base_url_override = base_url_override
        self.max_retries = max_retries
        self.parallel = max(1, min(parallel, 8))   # cap at 8 parallel browsers
        self.fail_fast = fail_fast
        self.tags = set(tags) if tags else set()
        self.report_dir = report_dir
        self.headless = headless
        self.triggered_by = triggered_by
        self.git_sha = git_sha
        self.git_branch = git_branch
        self.git_tag = git_tag
        self._abort = False   # set to True by fail-fast

    async def run_suite(
        self,
        suite_id: int,
        suite_name: str,
        tests: list[dict],
        on_test_complete=None,   # optional async callback(TestResult)
    ) -> SuiteResult:
        """
        Run all tests in a suite, respecting parallelism and fail-fast settings.
        `tests` is a list of dicts with keys: id, name, steps (JSON str), base_url, tags, retry_count.
        `on_test_complete` is an optional async callback called after each test finishes.
        """
        os.makedirs(self.report_dir, exist_ok=True)
        os.makedirs("screenshots", exist_ok=True)

        # Filter by tag if requested
        filtered = [
            t for t in tests
            if not self.tags or self.tags.intersection(set(json.loads(t.get("tags", "[]"))))
        ]
        if not filtered:
            logger.warning("No tests matched the specified tags — nothing to run")

        wall_start = time.time()
        results: list[TestResult] = []
        self._abort = False

        # Run in parallel batches
        semaphore = asyncio.Semaphore(self.parallel)

        async def run_one(test: dict) -> TestResult:
            if self._abort:
                return TestResult(
                    test_id=test["id"], test_name=test["name"],
                    status="skipped", duration=0, attempt=0,
                )
            async with semaphore:
                result = await self._run_with_retry(test)
                if self._abort:
                    return result
                if self.fail_fast and result.status == "failed":
                    logger.warning(f"Fail-fast triggered by: {test['name']}")
                    self._abort = True
                if on_test_complete:
                    await on_test_complete(result)
                return result

        tasks = [run_one(t) for t in filtered]
        results = list(await asyncio.gather(*tasks))

        total_duration = time.time() - wall_start
        passed  = sum(1 for r in results if r.status in ("passed", "self-healed") and not r.healed_steps or r.status == "passed")
        healed  = sum(1 for r in results if r.status == "self-healed")
        failed  = sum(1 for r in results if r.status == "failed")
        skipped = sum(1 for r in results if r.status == "skipped")

        # Recalculate properly
        passed = sum(1 for r in results if r.status == "passed")
        healed = sum(1 for r in results if r.status == "self-healed")
        failed = sum(1 for r in results if r.status == "failed")
        skipped = sum(1 for r in results if r.status == "skipped")

        overall = "passed" if failed == 0 and skipped == 0 else (
            "partial" if (passed + healed) > 0 else "failed"
        )
        if failed > 0:
            overall = "failed"

        suite_result = SuiteResult(
            suite_id=suite_id,
            suite_name=suite_name,
            status=overall,
            total=len(results),
            passed=passed,
            failed=failed,
            healed=healed,
            skipped=skipped,
            duration=total_duration,
            test_results=results,
            base_url_override=self.base_url_override,
            git_sha=self.git_sha,
            git_branch=self.git_branch,
            git_tag=self.git_tag,
        )
        return suite_result

    async def _run_with_retry(self, test: dict) -> TestResult:
        """Run a single test, retrying up to max_retries times on failure."""
        max_attempts = max(1, test.get("retry_count") or self.max_retries)
        steps = json.loads(test.get("steps", "[]"))
        base_url = self.base_url_override or test.get("base_url", "")
        runner = TestRunner(ai_engine=self.ai)
        last_result = None

        for attempt in range(1, max_attempts + 1):
            if attempt > 1:
                wait = 2 ** (attempt - 1)   # exponential backoff: 2s, 4s
                logger.info(f"Retry {attempt}/{max_attempts} for '{test['name']}' (waiting {wait}s)")
                await asyncio.sleep(wait)

            # Collect events from the generator
            step_results = []
            healed_steps = None
            screenshot_path = ""
            status = "failed"
            error = ""

            try:
                run_id = f"{test['id']}_{attempt}_{int(time.time())}"
                async for event in runner.run(steps, base_url, run_id, headless=self.headless):
                    if event["type"] == "step_fail":
                        error = event.get("error", "")
                    if event["type"] == "complete":
                        status = event["status"]
                        step_results = event["results"]
                        healed_steps = event.get("healed_steps")
                        screenshot_path = event.get("screenshot", "")
            except Exception as e:
                error = str(e)[:300]
                status = "failed"

            last_result = TestResult(
                test_id=test["id"],
                test_name=test["name"],
                status=status,
                duration=sum(r.get("duration", 0) for r in step_results),
                attempt=attempt,
                step_results=step_results,
                healed_steps=healed_steps,
                screenshot_path=screenshot_path,
                error=error,
            )

            if status in ("passed", "self-healed"):
                if attempt > 1:
                    logger.info(f"Test '{test['name']}' passed on attempt {attempt}")
                return last_result

        return last_result
