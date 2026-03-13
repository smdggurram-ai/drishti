"""
reporter.py — Generate JUnit XML, JSON, and console reports from SuiteResult.

JUnit XML is the universal CI format supported by:
  GitHub Actions, GitLab CI, Jenkins, CircleCI, Buildkite, Azure DevOps, etc.
"""
import json
import os
import xml.etree.ElementTree as ET
from datetime import datetime

from suite_runner import SuiteResult, TestResult

# ANSI colours (disabled automatically in CI via NO_COLOR or non-TTY)
def _c(code: str, text: str) -> str:
    if os.environ.get("NO_COLOR") or not os.isatty(1):
        return text
    return f"\033[{code}m{text}\033[0m"

GREEN  = lambda t: _c("32", t)
RED    = lambda t: _c("31", t)
YELLOW = lambda t: _c("33", t)
CYAN   = lambda t: _c("36", t)
BOLD   = lambda t: _c("1",  t)
DIM    = lambda t: _c("2",  t)
RESET  = lambda t: t


# ── JUnit XML ─────────────────────────────────────────────────────────────────

def write_junit(result: SuiteResult, path: str) -> str:
    """Write a JUnit-compatible XML report. Returns the path written."""
    os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)

    testsuites = ET.Element("testsuites")
    testsuites.set("name", result.suite_name)
    testsuites.set("tests", str(result.total))
    testsuites.set("failures", str(result.failed))
    testsuites.set("errors", "0")
    testsuites.set("skipped", str(result.skipped))
    testsuites.set("time", str(round(result.duration, 3)))
    testsuites.set("timestamp", datetime.utcnow().isoformat())

    testsuite = ET.SubElement(testsuites, "testsuite")
    testsuite.set("name", result.suite_name)
    testsuite.set("id", str(result.suite_id))
    testsuite.set("tests", str(result.total))
    testsuite.set("failures", str(result.failed))
    testsuite.set("skipped", str(result.skipped))
    testsuite.set("time", str(round(result.duration, 3)))

    # Properties (CI metadata)
    props = ET.SubElement(testsuite, "properties")
    for k, v in [
        ("base_url_override", result.base_url_override),
        ("git_sha", result.git_sha),
        ("git_branch", result.git_branch),
        ("git_tag", result.git_tag),
        ("pass_rate", f"{result.pass_rate}%"),
    ]:
        if v:
            p = ET.SubElement(props, "property")
            p.set("name", k); p.set("value", str(v))

    for tr in result.test_results:
        tc = ET.SubElement(testsuite, "testcase")
        tc.set("name", tr.test_name)
        tc.set("classname", result.suite_name)
        tc.set("time", str(round(tr.duration, 3)))

        if tr.status == "skipped":
            skipped = ET.SubElement(tc, "skipped")
            skipped.set("message", "Skipped due to fail-fast or tag filter")

        elif tr.status == "failed":
            failure = ET.SubElement(tc, "failure")
            failure.set("type", "AssertionError")
            failure.set("message", tr.error[:200] if tr.error else "Test failed")

            # Full step-by-step output as the failure body
            lines = [f"Attempt: {tr.attempt}", ""]
            for i, step in enumerate(tr.step_results, 1):
                icon = "✓" if step["status"] in ("passed", "healed") else "✗"
                lines.append(f"  {icon} Step {i}: {step['action']} → {step['target']}")
                if step.get("error"):
                    lines.append(f"     Error: {step['error']}")
                if step.get("heal_note"):
                    lines.append(f"     Healed: {step['heal_note']}")
            failure.text = "\n".join(lines)

        elif tr.status == "self-healed":
            # Healed tests pass in CI but we add a system-out note
            sysout = ET.SubElement(tc, "system-out")
            healed_steps = [s for s in tr.step_results if s.get("healed")]
            notes = [f"Self-healed selector: {s['heal_note']}" for s in healed_steps]
            sysout.text = "\n".join(notes)

        # Attach screenshot path as system-err annotation
        if tr.screenshot_path:
            syserr = ET.SubElement(tc, "system-err")
            syserr.text = f"Screenshot: {tr.screenshot_path}"

    tree = ET.ElementTree(testsuites)
    ET.indent(tree, space="  ")
    tree.write(path, encoding="unicode", xml_declaration=True)
    return path


# ── JSON report ───────────────────────────────────────────────────────────────

def write_json(result: SuiteResult, path: str) -> str:
    """Write a detailed JSON report. Returns the path written."""
    os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
    with open(path, "w") as f:
        json.dump(result.to_dict(), f, indent=2, default=str)
    return path


# ── Console summary ───────────────────────────────────────────────────────────

def print_summary(result: SuiteResult, verbose: bool = False):
    """Print a human-readable summary to stdout."""
    w = 64
    print()
    print(BOLD("=" * w))
    print(BOLD(f"  NeuralTest — {result.suite_name}"))
    print(BOLD("=" * w))

    if result.base_url_override:
        print(DIM(f"  Base URL : {result.base_url_override}"))
    if result.git_branch:
        print(DIM(f"  Branch   : {result.git_branch}"))
    if result.git_sha:
        print(DIM(f"  Commit   : {result.git_sha[:12]}"))
    print()

    for tr in result.test_results:
        if tr.status == "passed":
            icon = GREEN("  ✓")
            label = GREEN("PASS")
        elif tr.status == "self-healed":
            icon = YELLOW("  ⚡")
            label = YELLOW("HEAL")
        elif tr.status == "failed":
            icon = RED("  ✗")
            label = RED("FAIL")
        else:
            icon = DIM("  ○")
            label = DIM("SKIP")

        retry_note = f" (attempt {tr.attempt})" if tr.attempt > 1 else ""
        print(f"{icon}  {label}  {tr.test_name}{retry_note}  {DIM(f'{tr.duration:.1f}s')}")

        if verbose or tr.status == "failed":
            for i, step in enumerate(tr.step_results, 1):
                s_icon = GREEN("     ✓") if step["status"] in ("passed","healed") else RED("     ✗")
                print(f"{s_icon}  {step['action']:14} {step['target']}")
                if step.get("error"):
                    print(f"        {RED('⚠')}  {step['error'][:120]}")
                if step.get("heal_note"):
                    print(f"        {YELLOW('⚡')}  {step['heal_note']}")

    print()
    print(BOLD("-" * w))

    status_str = (GREEN("PASSED") if result.status == "passed"
                  else YELLOW("PASSED WITH HEALING") if result.status == "partial" and result.failed == 0
                  else RED("FAILED"))

    print(f"  {BOLD('Result')}    {status_str}")
    print(f"  {BOLD('Tests')}     {result.total} total  "
          f"{GREEN(str(result.passed))} passed  "
          f"{YELLOW(str(result.healed))} healed  "
          f"{RED(str(result.failed))} failed  "
          f"{DIM(str(result.skipped))} skipped")
    print(f"  {BOLD('Pass rate')} {result.pass_rate}%")
    print(f"  {BOLD('Duration')}  {result.duration:.1f}s")
    print(BOLD("=" * w))
    print()
