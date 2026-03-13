import httpx
import json
import os
import logging

logger = logging.getLogger("ai_engine")

ANTHROPIC_API = "https://api.anthropic.com/v1/messages"
MODEL = "claude-sonnet-4-20250514"


class AIEngine:
    def __init__(self):
        self.api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not self.api_key:
            logger.warning("ANTHROPIC_API_KEY not set — AI features will fail")

    def _headers(self):
        return {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
        }

    async def generate_test(self, description: str, url: str = "") -> dict:
        """Convert a plain-English test description into structured steps."""
        system = (
            "You are an expert test automation engineer. Convert natural language test descriptions "
            "into precise, structured test steps for a Playwright-based runner. "
            "Respond ONLY with valid JSON — no markdown fences, no explanation."
        )
        prompt = f"""Convert this test description into steps.
Base URL / context: {url or 'not specified'}
Description: "{description}"

Return this exact JSON shape:
{{
  "name": "Short descriptive test name (max 60 chars)",
  "steps": [
    {{
      "action": "navigate|click|type|assert_text|assert_visible|press|wait|scroll|hover|select",
      "target": "CSS selector, URL, key name, or ms as string",
      "value": "text to type / expected text / option value (omit if unused)"
    }}
  ]
}}

Action reference:
- navigate  : target = full URL or path (e.g. "/login")
- click     : target = CSS selector or "text=Button Label"
- type      : target = CSS selector, value = text to enter
- assert_text     : target = CSS selector, value = substring to find in element text
- assert_visible  : target = CSS selector (element must be in DOM and visible)
- press     : target = key name ("Enter", "Tab", "Escape", "ArrowDown" …)
- wait      : target = CSS selector to wait for, OR milliseconds as string (e.g. "2000")
- scroll    : target = CSS selector to scroll into view
- hover     : target = CSS selector
- select    : target = <select> CSS selector, value = option text or value

Use realistic, robust selectors (prefer IDs, data-testid attrs, semantic roles).
Generate between 3 and 10 steps. Keep it atomic."""

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                ANTHROPIC_API,
                headers=self._headers(),
                json={
                    "model": MODEL,
                    "max_tokens": 1200,
                    "system": system,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            resp.raise_for_status()
            text = resp.json()["content"][0]["text"]
            return json.loads(text.replace("```json", "").replace("```", "").strip())

    async def suggest_healings(
        self, failed_selector: str, action: str, page_html: str
    ) -> list[str]:
        """Given a broken selector and current DOM, return up to 4 alternative selectors."""
        prompt = f"""A Playwright test step failed because this selector was not found on the page:
Selector: "{failed_selector}"
Action: {action}

Current page HTML (truncated to 4 000 chars):
{page_html[:4000]}

Suggest up to 4 alternative CSS selectors or Playwright locators that likely match the intended element.
You may use:
  - Standard CSS selectors  (#id, .class, [attr=value], tag, combinators)
  - Playwright text locators ("text=Label")
  - ARIA role locators      ("role=button[name=Submit]")

Respond ONLY with a JSON array of strings, e.g.:
["#submit-btn", "button[type=\\"submit\\"]", "text=Sign in", ".login-form button"]
No explanation — only the JSON array."""

        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                ANTHROPIC_API,
                headers=self._headers(),
                json={
                    "model": MODEL,
                    "max_tokens": 200,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            resp.raise_for_status()
            text = resp.json()["content"][0]["text"]
            return json.loads(text.replace("```json", "").replace("```", "").strip())
