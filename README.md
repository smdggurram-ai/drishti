# ⚗ NeuralTest

**AI-powered web testing with natural language authoring, self-healing selectors, and CI/CD pipeline integration.**

---

## Table of Contents

1. [What It Does](#what-it-does)
2. [Architecture](#architecture)
3. [Local Setup](#local-setup)
4. [Writing Your First Test](#writing-your-first-test)
5. [Tagging Tests for CI](#tagging-tests-for-ci)
6. [CI/CD Integration](#cicd-integration)
7. [CLI Reference](#cli-reference)
8. [Self-Healing Engine](#self-healing-engine)
9. [Reports](#reports)
10. [REST API Reference](#rest-api-reference)
11. [Project Structure](#project-structure)
12. [Common Issues](#common-issues)

---

## What It Does

NeuralTest turns plain English into Playwright browser tests, runs them against real URLs, and auto-repairs broken selectors using AI — all with a web UI and a CI-ready CLI.

| Feature | Description |
|---|---|
| **Natural language authoring** | Describe a test in plain English → Claude generates Playwright steps |
| **Real browser execution** | Playwright + Chromium runs steps against live URLs |
| **Self-healing selectors** | When a selector breaks, AI inspects the DOM and suggests fixes automatically |
| **CI/CD CLI** | `python ci_runner.py --suite Regression` exits 0 (pass) or 1 (fail) |
| **JUnit XML output** | Compatible with GitHub Actions, GitLab CI, Jenkins, CircleCI, Azure DevOps |
| **Parallel execution** | Run N tests concurrently with `--parallel N` |
| **Retry logic** | Configurable per-test retries with exponential backoff |
| **Tag filtering** | Run only `smoke` or `critical` tests on PRs |
| **Screenshot capture** | Every run saves a full-page screenshot |
| **Run history** | All results persisted in SQLite, viewable in the web UI |

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│  Web UI (React + Vite)      :5173                   │
│  CI CLI (ci_runner.py)      — no server needed      │
└────────────────┬────────────────────────────────────┘
                 │ HTTP / WebSocket
┌────────────────▼────────────────────────────────────┐
│  FastAPI Backend             :8000                  │
│  ├─ /generate          NL → steps (Claude API)      │
│  ├─ /suites            CRUD suites                  │
│  ├─ /tests             CRUD test cases              │
│  ├─ /tests/{id}/run    single test run              │
│  ├─ /suites/{id}/run   full suite run (CI)          │
│  └─ /ws/{run_id}       WebSocket live stream        │
└──────┬─────────────────────┬───────────────────────┘
       │                     │
┌──────▼──────┐    ┌─────────▼──────────┐
│  SQLite DB  │    │  Playwright Engine │
│  (ORM)      │    │  + Self-Heal AI    │
└─────────────┘    └────────────────────┘
```

The **CI runner** (`ci_runner.py`) talks **directly** to the database and Playwright — it does **not** require the FastAPI server to be running. This makes it suitable for ephemeral CI environments.

---

## Local Setup

### Prerequisites

| Tool | Version | Check |
|---|---|---|
| Python | 3.11+ | `python --version` |
| Node.js | 18+ | `node --version` |
| Anthropic API key | — | [console.anthropic.com](https://console.anthropic.com) |

### Installation

```bash
# 1. Enter the project directory
cd neuraltest

# 2. Create and activate a Python virtual environment (strongly recommended)
python -m venv .venv
source .venv/bin/activate         # macOS / Linux
# .venv\Scripts\activate          # Windows

# 3. Install Python dependencies
pip install -r requirements.txt

# 4. Install Playwright's Chromium browser
playwright install chromium --with-deps

# 5. Install frontend dependencies
cd frontend && npm install && cd ..

# 6. Set your API key
export ANTHROPIC_API_KEY=sk-ant-YOUR_KEY_HERE
```

> **Never commit your API key.** Add `.env` to `.gitignore` and use `export` or a secret manager.

### Running the App

**One-command start:**
```bash
export ANTHROPIC_API_KEY=sk-ant-...
chmod +x start.sh && ./start.sh
```

**Or manually in two terminals:**

```bash
# Terminal 1 — backend
source .venv/bin/activate
export ANTHROPIC_API_KEY=sk-ant-...
cd backend && uvicorn main:app --reload --port 8000

# Terminal 2 — frontend
cd frontend && npm run dev
```

Open **http://localhost:5173** — API docs at **http://localhost:8000/docs**.

---

## Writing Your First Test

### In the Web UI

1. Click **+** next to the suite dropdown → create a suite called `Regression`
2. Click the **✦ Composer** tab
3. Set the base URL (e.g. `https://example.com`) and describe your test:
   > "Navigate to the homepage, verify the heading says 'Example Domain', and check the More information link is visible"
4. Click **Generate Steps** — Claude returns structured Playwright steps
5. Click **Add to Suite**
6. Select the test, click **▶ Run Test** — watch it execute in a real browser

### Via the API

```bash
# 1. Create a suite
curl -X POST http://localhost:8000/suites \
  -H "Content-Type: application/json" \
  -d '{"name": "Regression", "description": "Release regression suite"}'

# 2. Generate steps from natural language
curl -X POST http://localhost:8000/generate \
  -H "Content-Type: application/json" \
  -d '{"description": "Go to example.com, verify the h1 heading is visible", "url": "https://example.com"}'

# 3. Create a test in the suite (use the steps from step 2)
curl -X POST http://localhost:8000/suites/1/tests \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Homepage check",
    "nl_description": "Go to example.com and verify the heading",
    "steps": [
      {"action": "navigate", "target": "https://example.com"},
      {"action": "assert_visible", "target": "h1"}
    ],
    "base_url": "https://example.com",
    "tags": ["smoke", "homepage"]
  }'
```

### Supported step actions

| Action | `target` | `value` | Description |
|---|---|---|---|
| `navigate` | URL or path | — | Go to a URL |
| `click` | CSS selector or `text=Label` | — | Click an element |
| `type` | CSS selector | Text to enter | Fill a field |
| `assert_text` | CSS selector | Expected substring | Assert element contains text |
| `assert_visible` | CSS selector | — | Assert element is visible |
| `press` | Key name (`Enter`, `Tab`, …) | — | Press a keyboard key |
| `wait` | CSS selector or ms as string | — | Wait for element or sleep |
| `scroll` | CSS selector | — | Scroll element into view |
| `hover` | CSS selector | — | Hover over element |
| `select` | `<select>` CSS selector | Option text/value | Pick a dropdown option |

---

## Tagging Tests for CI

Tags control which tests run at each stage of your pipeline.

**Recommended tag strategy:**

| Tag | When it runs | Examples |
|---|---|---|
| `smoke` | Every PR — must be fast (< 2 min total) | Homepage loads, login works |
| `critical` | Every regression + post-deploy | Checkout, account creation |
| `login` | Any run touching auth flows | Login, logout, password reset |
| `checkout` | Any run touching purchase flows | Cart, payment, confirmation |
| `admin` | Staging only — never production | Admin dashboard, user management |
| `slow` | Nightly only — excluded from PRs | Full data-heavy flows |

Set tags when creating a test via the API (`"tags": ["smoke", "login"]`). The UI tag editor is coming in a future release.

---

## CI/CD Integration

### GitHub Actions

**One-time setup:**
1. **Settings → Secrets → Actions → New secret:** `ANTHROPIC_API_KEY`
2. **Settings → Variables → Actions → New variable:** `STAGING_URL` = `https://staging.yourapp.com`

The included `.github/workflows/regression.yml` configures three stages:

| Job | Trigger | Tests run | Target |
|---|---|---|---|
| `smoke` | Every pull request | `--tags smoke` | Staging |
| `regression:staging` | Push to `main` / `release/**` | Full suite | Staging |
| `post-deploy:production` | Version tag `v*` | `--tags smoke critical` | Production |
| Nightly | 02:00 UTC cron | Full suite | Staging |

Results appear in GitHub's **Checks** tab. A commit comment is posted automatically with the pass rate summary.

**Manual trigger:** Actions → `Release Regression` → `Run workflow` → enter base URL.

---

### GitLab CI

**One-time setup:**
1. **Settings → CI/CD → Variables:**
   - `ANTHROPIC_API_KEY` — your key, **masked**
   - `STAGING_URL` — staging base URL
   - `PRODUCTION_URL` — production base URL

The included `.gitlab-ci.yml` provides identical stages. JUnit results appear in merge request widgets automatically.

---

### Running the CLI Manually

The CLI works without the web server. From the `backend/` directory:

```bash
source ../.venv/bin/activate
export ANTHROPIC_API_KEY=sk-ant-...

# See available suites
python ci_runner.py --list-suites

# Full suite against staging
python ci_runner.py --suite "Regression" --base-url https://staging.yourapp.com

# PR smoke check — fast, stop on first failure
python ci_runner.py --suite "Regression" --tags smoke --fail-fast

# 3 parallel browsers, retry each failure up to 2 times
python ci_runner.py --suite "Regression" --parallel 3 --retries 2

# Debug locally — headed browser, verbose step output
python ci_runner.py --suite "Regression" --headed --verbose

# Run against local dev server
python ci_runner.py --suite "Regression" --base-url http://localhost:3000

# Custom report directory
python ci_runner.py --suite "Regression" --report-dir ./ci-reports
```

**Exit codes:**

| Code | Meaning |
|---|---|
| `0` | All tests passed or self-healed |
| `1` | One or more tests failed |
| `2` | Config error (missing key, suite not found) |

---

## CLI Reference

```
python ci_runner.py [options]

Targeting:
  --suite NAME        Suite name to run (partial match OK)
  --suite-id ID       Suite ID to run
  --list-suites       Print all suites and exit

Environment:
  --base-url URL      Override base URL for all tests
  --tags TAG ...      Only run tests tagged with these values

Execution:
  --retries N         Max retry attempts per failing test (default: 1)
  --parallel N        Concurrent test runners (default: 1, max: 8)
  --fail-fast         Stop after first test failure
  --headed            Run in headed (visible) browser — for debugging

Output:
  --report-dir DIR    Report output directory (default: test-results)
  --verbose           Print every step for every test
  --no-color          Disable ANSI colors (set NO_COLOR=1 alternatively)
```

**CI environment variables automatically read:**

| Variable | Set by |
|---|---|
| `ANTHROPIC_API_KEY` | You (required) |
| `GITHUB_SHA` | GitHub Actions |
| `GITHUB_REF_NAME` | GitHub Actions |
| `CI_COMMIT_SHA` | GitLab CI |
| `CI_COMMIT_BRANCH` | GitLab CI |
| `CI_TRIGGERED_BY` | Your pipeline (optional label) |

---

## Self-Healing Engine

When a selector fails during a run:

```
Step 3 | click → .checkout-btn
        ✗ Timeout 12000ms waiting for .checkout-btn
```

The engine automatically:
1. Captures the full page DOM via `page.content()`
2. Sends the broken selector + DOM to Claude: *"This selector failed. Here's the current DOM. Suggest up to 4 alternatives."*
3. Tries each suggestion in order until one works
4. **Persists the healed selector** back to the test definition in the database

```
Step 3 | click → .checkout-btn
        ⚡ Self-healed: ".checkout-btn" → "[data-testid='checkout-button']"
```

**To make healings permanent across CI runs:** commit `neuraltest.db` to your repository, or point all environments at a shared SQLite file (or Postgres — change `DATABASE_URL` in `database.py`).

---

## Reports

Every suite run writes to `--report-dir` (default: `test-results/`):

### `junit.xml`
Standard JUnit format, consumed by all major CI systems. Contains step-by-step failure details, self-healing notes, screenshot paths, and Git metadata as properties.

### `report.json`
Full structured report:
```json
{
  "suite_name": "Regression",
  "status": "failed",
  "summary": {
    "total": 10, "passed": 8, "failed": 1,
    "healed": 1, "skipped": 0,
    "pass_rate": 90.0, "duration": 47.3
  },
  "environment": {
    "base_url_override": "https://staging.yourapp.com",
    "git_sha": "abc123def", "git_branch": "main"
  },
  "tests": [...]
}
```

---

## REST API Reference

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/generate` | NL → test steps (AI) |
| `GET/POST` | `/suites` | List / create suites |
| `DELETE` | `/suites/{id}` | Delete suite |
| `GET/POST` | `/suites/{id}/tests` | List / create tests |
| `GET` | `/suites/{id}/history` | Suite run history |
| `POST` | `/suites/{id}/run` | Run full suite (CI) |
| `GET` | `/suite-runs/{id}` | Poll suite run status |
| `GET/DELETE` | `/tests/{id}` | Get / delete test |
| `POST` | `/tests/{id}/run` | Run single test |
| `GET` | `/tests/{id}/runs` | Run history |
| `GET` | `/runs/{id}` | Get run result |
| `WS` | `/ws/{run_id}` | Live step-by-step stream |

---

## Project Structure

```
neuraltest/
├── backend/
│   ├── main.py            FastAPI app — all routes + WebSocket
│   ├── ci_runner.py       ★ CLI for CI/CD pipelines
│   ├── suite_runner.py    Parallel suite execution + retries
│   ├── runner.py          Per-test Playwright executor + self-healing
│   ├── ai_engine.py       Claude API — NL→steps + selector repair
│   ├── reporter.py        JUnit XML + JSON + console output
│   ├── database.py        SQLAlchemy engine
│   ├── models.py          ORM: TestSuite, TestCase, TestRun, SuiteRun
│   ├── schemas.py         Pydantic models
│   └── screenshots/       Auto-created — stores run screenshots
├── frontend/
│   └── src/
│       ├── App.jsx        Full React UI
│       └── api.js         HTTP + WebSocket client
├── test-results/          Auto-created by CI runner
│   ├── junit.xml          JUnit XML (for CI)
│   └── report.json        Detailed JSON report
├── .github/workflows/
│   └── regression.yml     GitHub Actions pipeline
├── .gitlab-ci.yml         GitLab CI pipeline
├── neuraltest.config.json Environment configuration
├── requirements.txt
├── start.sh
└── README.md
```

---

## Common Issues

**`playwright install` fails on Linux CI:**
```bash
playwright install chromium --with-deps
# If that fails, install browser deps manually:
apt-get install -y libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
  libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 libxrandr2 libgbm1
```

**Tests time out on slow CI environments:**
Increase `STEP_TIMEOUT` in `runner.py` to `20000` and pass `--retries 2`.

**Self-healing not working:**
Check that `ANTHROPIC_API_KEY` is set correctly. Look for `AI healing failed:` in backend logs.

**`database is locked` with parallel runners:**
SQLite has limited write concurrency. Use `--parallel 1` or migrate to PostgreSQL by changing `DATABASE_URL` in `database.py` to `postgresql://user:pass@host/dbname` and adding `psycopg2-binary` to `requirements.txt`.

**Suite not found in CI:**
Run `python ci_runner.py --list-suites` locally to confirm the DB has been populated. Ensure CI uses the same `neuraltest.db` file (commit it to the repo or use a shared remote DB).
