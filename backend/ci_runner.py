#!/usr/bin/env python3
"""
ci_runner.py — NeuralTest CLI for CI/CD regression pipelines.

Usage:
  python ci_runner.py --suite "Regression" --base-url https://staging.myapp.com

Exit codes:
  0  All tests passed (or self-healed)
  1  One or more tests failed
  2  Configuration / setup error (missing API key, suite not found, etc.)

Examples:
  # Run all tests in a suite against staging
  python ci_runner.py --suite "Regression" --base-url https://staging.myapp.com

  # Run only tests tagged 'smoke'
  python ci_runner.py --suite "Regression" --tags smoke --base-url https://staging.myapp.com

  # Run 3 tests in parallel, retry each failing test up to 2 times
  python ci_runner.py --suite "Regression" --parallel 3 --retries 2

  # Stop immediately on first failure (fast feedback)
  python ci_runner.py --suite "Regression" --fail-fast

  # Output JUnit XML + JSON to a custom directory
  python ci_runner.py --suite "Regression" --report-dir ./ci-reports

  # Run headed browser (useful for local debugging)
  python ci_runner.py --suite "Regression" --headed

  # List available suites and exit
  python ci_runner.py --list-suites
"""
import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

# ── Bootstrap path so imports resolve from backend/ ──────────────────────────
sys.path.insert(0, str(Path(__file__).parent))

from database import init_db, get_db
from models import TestSuite, TestCase, TestRun, SuiteRun
from ai_engine import AIEngine
from suite_runner import SuiteRunner
from reporter import write_junit, write_json, print_summary

logging.basicConfig(
    level=logging.WARNING,  # CI: only show warnings and errors by default
    format="%(levelname)s  %(name)s — %(message)s",
)
logger = logging.getLogger("ci_runner")


# ── CLI argument parser ───────────────────────────────────────────────────────

def make_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="NeuralTest CI runner — run regression suites from the command line",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Targeting
    g = p.add_mutually_exclusive_group()
    g.add_argument("--suite",      metavar="NAME",  help="Suite name to run (partial match OK)")
    g.add_argument("--suite-id",   metavar="ID",    type=int, help="Suite ID to run")
    g.add_argument("--list-suites", action="store_true", help="Print all suites and exit")

    # Environment
    p.add_argument("--base-url",   metavar="URL",   help="Override base URL for all tests (e.g. https://staging.myapp.com)")
    p.add_argument("--tags",       metavar="TAG",   nargs="+", help="Only run tests with these tags")

    # Execution behaviour
    p.add_argument("--retries",    metavar="N",     type=int, default=1, help="Max retry attempts per failing test (default: 1)")
    p.add_argument("--parallel",   metavar="N",     type=int, default=1, help="Number of tests to run concurrently (default: 1)")
    p.add_argument("--fail-fast",  action="store_true", help="Stop suite after first test failure")
    p.add_argument("--headed",     action="store_true", help="Run browser in headed (visible) mode — useful for local debugging")

    # Output
    p.add_argument("--report-dir", metavar="DIR",   default="test-results", help="Directory for JUnit XML and JSON reports (default: test-results)")
    p.add_argument("--verbose",    action="store_true", help="Print every step for every test")
    p.add_argument("--no-color",   action="store_true", help="Disable ANSI color output")

    return p


# ── Helpers ───────────────────────────────────────────────────────────────────

def _check_api_key() -> bool:
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        print("ERROR: ANTHROPIC_API_KEY environment variable is not set.", file=sys.stderr)
        print("       The self-healing engine requires a Claude API key.", file=sys.stderr)
        print("       Export it: export ANTHROPIC_API_KEY=sk-ant-...", file=sys.stderr)
        return False
    return True


def _find_suite(db, name: str | None, suite_id: int | None):
    if suite_id:
        s = db.query(TestSuite).filter(TestSuite.id == suite_id).first()
        if not s:
            print(f"ERROR: No suite found with id={suite_id}", file=sys.stderr)
        return s
    if name:
        # Case-insensitive partial match
        s = db.query(TestSuite).filter(
            TestSuite.name.ilike(f"%{name}%")
        ).first()
        if not s:
            print(f"ERROR: No suite found matching '{name}'", file=sys.stderr)
            _list_suites(db)
        return s
    print("ERROR: Specify --suite or --suite-id", file=sys.stderr)
    return None


def _list_suites(db):
    suites = db.query(TestSuite).all()
    if not suites:
        print("No suites in database. Use the web UI to create test suites.")
        return
    print("\nAvailable suites:")
    print(f"  {'ID':>4}  {'Name':<40}  Tests")
    print(f"  {'—'*4}  {'—'*40}  ——————")
    for s in suites:
        count = db.query(TestCase).filter(TestCase.suite_id == s.id).count()
        print(f"  {s.id:>4}  {s.name:<40}  {count}")
    print()


def _persist_suite_run(db, result, suite_id, args, report_path, junit_path):
    """Save the SuiteRun record to the database."""
    sr = SuiteRun(
        suite_id=suite_id,
        status=result.status,
        total=result.total,
        passed=result.passed,
        failed=result.failed,
        healed=result.healed,
        duration=result.duration,
        base_url_override=args.base_url or "",
        triggered_by=os.environ.get("CI_TRIGGERED_BY", "cli"),
        git_sha=os.environ.get("GITHUB_SHA", os.environ.get("CI_COMMIT_SHA", "")),
        git_branch=os.environ.get("GITHUB_REF_NAME", os.environ.get("CI_COMMIT_BRANCH", "")),
        git_tag=os.environ.get("GITHUB_REF_TYPE", os.environ.get("CI_COMMIT_TAG", "")),
        report_path=report_path,
        junit_path=junit_path,
    )
    db.add(sr)
    db.flush()   # get sr.id

    # Persist individual test runs linked to this suite run
    for tr in result.test_results:
        run = TestRun(
            test_id=tr.test_id,
            suite_run_id=sr.id,
            status=tr.status,
            attempt=tr.attempt,
            duration=tr.duration,
            results=json.dumps(tr.step_results),
            screenshot_path=tr.screenshot_path,
            triggered_by=os.environ.get("CI_TRIGGERED_BY", "cli"),
            git_sha=sr.git_sha,
            git_branch=sr.git_branch,
        )
        db.add(run)

        # Persist healed selectors back to the test definition
        if tr.healed_steps:
            test = db.query(TestCase).filter(TestCase.id == tr.test_id).first()
            if test:
                test.steps = json.dumps(tr.healed_steps)
                test.self_healed = True

        # Update last_status on the test
        test = db.query(TestCase).filter(TestCase.id == tr.test_id).first()
        if test:
            test.last_status = tr.status
            test.last_duration = tr.duration

    db.commit()
    return sr


# ── Main async entry point ────────────────────────────────────────────────────

async def _run(args: argparse.Namespace) -> int:
    """Returns exit code: 0 = success, 1 = test failures, 2 = config error."""

    if args.no_color:
        os.environ["NO_COLOR"] = "1"

    # DB
    init_db()
    db = get_db()

    # List suites mode
    if args.list_suites:
        _list_suites(db)
        return 0

    # Validate API key
    if not _check_api_key():
        return 2

    # Find suite
    suite = _find_suite(db, args.suite, getattr(args, "suite_id", None))
    if not suite:
        return 2

    # Load tests
    tests_orm = (
        db.query(TestCase)
        .filter(TestCase.suite_id == suite.id)
        .order_by(TestCase.created_at)
        .all()
    )
    if not tests_orm:
        print(f"WARNING: Suite '{suite.name}' has no tests.")
        return 0

    tests = [
        {
            "id": t.id,
            "name": t.name,
            "steps": t.steps,
            "base_url": t.base_url,
            "tags": t.tags,
            "retry_count": t.retry_count or args.retries,
        }
        for t in tests_orm
    ]

    # Print header
    print(f"\n⚗  NeuralTest — Release Regression")
    print(f"   Suite    : {suite.name}")
    print(f"   Tests    : {len(tests)}")
    if args.base_url:
        print(f"   Base URL : {args.base_url}")
    if args.tags:
        print(f"   Tags     : {', '.join(args.tags)}")
    print(f"   Parallel : {args.parallel}  |  Retries: {args.retries}  |  Fail-fast: {args.fail_fast}")
    print()

    # Progress callback — print a dot per completed test in non-verbose mode
    completed = 0
    total = len(tests)

    async def on_test_done(tr):
        nonlocal completed
        completed += 1
        icons = {"passed": "✓", "self-healed": "⚡", "failed": "✗", "skipped": "○"}
        icon = icons.get(tr.status, "?")
        colors = {"passed": "\033[32m", "self-healed": "\033[33m", "failed": "\033[31m"}
        c = colors.get(tr.status, "")
        reset = "\033[0m" if not args.no_color else ""
        c = c if not args.no_color else ""
        suffix = f" ← attempt {tr.attempt}" if tr.attempt > 1 else ""
        print(f"  {c}{icon}{reset}  [{completed}/{total}] {tr.test_name}{suffix}")
        if tr.status == "failed" and tr.error:
            print(f"       {tr.error[:100]}")

    # Build runner
    runner = SuiteRunner(
        ai_engine=AIEngine(),
        base_url_override=args.base_url or "",
        max_retries=args.retries,
        parallel=args.parallel,
        fail_fast=args.fail_fast,
        tags=args.tags,
        report_dir=args.report_dir,
        headless=not args.headed,
        triggered_by=os.environ.get("CI_TRIGGERED_BY", "cli"),
        git_sha=os.environ.get("GITHUB_SHA", os.environ.get("CI_COMMIT_SHA", "")),
        git_branch=os.environ.get("GITHUB_REF_NAME", os.environ.get("CI_COMMIT_BRANCH", "")),
        git_tag=os.environ.get("GITHUB_REF_TYPE", os.environ.get("CI_COMMIT_TAG", "")),
    )

    # Execute
    result = await runner.run_suite(
        suite_id=suite.id,
        suite_name=suite.name,
        tests=tests,
        on_test_complete=on_test_done,
    )

    # Write reports
    junit_path = os.path.join(args.report_dir, "junit.xml")
    json_path  = os.path.join(args.report_dir, "report.json")
    write_junit(result, junit_path)
    write_json(result, json_path)

    # Persist to DB
    _persist_suite_run(db, result, suite.id, args, json_path, junit_path)

    # Print summary
    print_summary(result, verbose=args.verbose)
    print(f"  Reports written to: {args.report_dir}/")
    print(f"    junit.xml  → {junit_path}")
    print(f"    report.json → {json_path}")
    print()

    # Exit code
    return 0 if result.status in ("passed", "partial") and result.failed == 0 else 1


def main():
    parser = make_parser()
    args = parser.parse_args()

    # If no action specified, show help
    if not any([args.suite, getattr(args, "suite_id", None), args.list_suites]):
        parser.print_help()
        sys.exit(2)

    try:
        exit_code = asyncio.run(_run(args))
    except KeyboardInterrupt:
        print("\nInterrupted.")
        exit_code = 2
    except Exception as e:
        print(f"\nFATAL: {e}", file=sys.stderr)
        logger.exception("Unexpected error")
        exit_code = 2

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
