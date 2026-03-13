import asyncio
import time
import os
import logging
from typing import AsyncGenerator
from playwright.async_api import async_playwright, Page, TimeoutError as PWTimeout

logger = logging.getLogger("runner")

STEP_TIMEOUT = 12_000   # ms per locator action
NAV_TIMEOUT  = 30_000   # ms for page.goto


class TestRunner:
    def __init__(self, ai_engine):
        self.ai = ai_engine

    # ── Public entry point ────────────────────────────────────────────────────

    async def run(
        self,
        steps: list[dict],
        base_url: str,
        run_id: int,
        headless: bool = True,
    ) -> AsyncGenerator[dict, None]:
        """
        Async generator that yields WebSocket-ready event dicts as steps execute.

        Event shapes:
          {"type": "step_start",   "step": i, "action": ..., "target": ...}
          {"type": "step_pass",    "step": i, "healed": bool, "heal_note": str, "duration": float}
          {"type": "step_fail",    "step": i, "error": str,  "duration": float}
          {"type": "complete",     "status": ..., "duration": float,
                                   "results": [...], "healed_steps": [...] | None,
                                   "screenshot": path | ""}
        """
        wall_start = time.time()
        results: list[dict] = []
        healed_steps = [dict(s) for s in steps]   # copy — modified in-place when healed
        overall_status = "passed"

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=headless)
            ctx = await browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent=(
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                ),
            )
            page = await ctx.new_page()

            for i, step in enumerate(steps):
                action = step["action"]
                target = step["target"]
                value  = step.get("value", "")

                yield {
                    "type": "step_start",
                    "step": i,
                    "action": action,
                    "target": target,
                    "value": value,
                }

                t0 = time.time()
                ok, error, healed, heal_note, new_target = await self._execute(
                    page, action, target, value, base_url
                )
                elapsed = round(time.time() - t0, 2)

                result = {
                    "index":     i,
                    "action":    action,
                    "target":    target,
                    "value":     value,
                    "status":    "passed" if ok and not healed else ("healed" if ok else "failed"),
                    "healed":    healed,
                    "heal_note": heal_note,
                    "error":     error,
                    "duration":  elapsed,
                }
                results.append(result)

                if ok:
                    if healed and new_target:
                        healed_steps[i] = {**healed_steps[i], "target": new_target}
                    yield {
                        "type":      "step_pass",
                        "step":      i,
                        "healed":    healed,
                        "heal_note": heal_note,
                        "duration":  elapsed,
                    }
                else:
                    overall_status = "failed"
                    yield {
                        "type":     "step_fail",
                        "step":     i,
                        "error":    error,
                        "duration": elapsed,
                    }
                    break   # Stop on first failure

                await asyncio.sleep(0.2)

            # Screenshot
            screenshot_path = ""
            try:
                os.makedirs("screenshots", exist_ok=True)
                screenshot_path = f"screenshots/run_{run_id}.png"
                await page.screenshot(path=screenshot_path, full_page=True)
            except Exception as e:
                logger.warning(f"Screenshot failed: {e}")
                screenshot_path = ""

            await browser.close()

        # Determine final status
        if overall_status == "passed":
            if any(r["healed"] for r in results):
                overall_status = "self-healed"

        any_healed = any(r["healed"] for r in results)

        yield {
            "type":         "complete",
            "status":       overall_status,
            "duration":     round(time.time() - wall_start, 2),
            "results":      results,
            "healed_steps": healed_steps if any_healed else None,
            "screenshot":   screenshot_path,
        }

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _execute(
        self,
        page: Page,
        action: str,
        target: str,
        value: str,
        base_url: str,
    ) -> tuple[bool, str, bool, str, str | None]:
        """Try to execute a step. On selector failure, attempt self-healing via AI.

        Returns: (success, error_msg, healed, heal_note, new_target)
        """
        # First attempt
        try:
            await self._do(page, action, target, value, base_url)
            return True, "", False, "", None
        except Exception as first_err:
            # Only attempt healing for actions that use locators
            if action not in ("click", "type", "assert_text", "assert_visible",
                              "hover", "select", "scroll", "wait"):
                return False, _fmt(first_err), False, "", None

            # Self-healing: ask AI for alternative selectors
            logger.info(f"Self-healing triggered for '{target}' ({action})")
            try:
                html = await page.content()
                alternatives = await self.ai.suggest_healings(target, action, html)
            except Exception as ai_err:
                logger.warning(f"AI healing failed: {ai_err}")
                return False, _fmt(first_err), False, "", None

            for alt in alternatives:
                try:
                    await self._do(page, action, alt, value, base_url)
                    note = f'"{target}" → "{alt}"'
                    logger.info(f"Self-healed: {note}")
                    return True, "", True, note, alt
                except Exception:
                    continue

            # All alternatives exhausted
            return False, _fmt(first_err), False, "", None

    async def _do(self, page: Page, action: str, target: str, value: str, base_url: str):
        """Execute a single action on the page. Raises on any failure."""

        if action == "navigate":
            if target.startswith("http://") or target.startswith("https://"):
                url = target
            else:
                url = base_url.rstrip("/") + "/" + target.lstrip("/")
            await page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT)

        elif action == "click":
            loc = self._locator(page, target)
            await loc.first.click(timeout=STEP_TIMEOUT)

        elif action == "type":
            loc = self._locator(page, target)
            await loc.first.fill(value, timeout=STEP_TIMEOUT)

        elif action == "assert_text":
            loc = self._locator(page, target)
            await loc.first.wait_for(timeout=STEP_TIMEOUT)
            actual = await loc.first.inner_text()
            if value.lower() not in actual.lower():
                raise AssertionError(
                    f"Expected text \"{value}\" not found in \"{actual[:120]}\""
                )

        elif action == "assert_visible":
            loc = self._locator(page, target)
            await loc.first.wait_for(state="visible", timeout=STEP_TIMEOUT)

        elif action == "press":
            await page.keyboard.press(target)

        elif action == "wait":
            # Numeric string → sleep; anything else → wait for selector
            try:
                ms = int(target)
                await asyncio.sleep(ms / 1000)
            except ValueError:
                await self._locator(page, target).first.wait_for(timeout=STEP_TIMEOUT)

        elif action == "scroll":
            loc = self._locator(page, target)
            await loc.first.scroll_into_view_if_needed(timeout=STEP_TIMEOUT)

        elif action == "hover":
            loc = self._locator(page, target)
            await loc.first.hover(timeout=STEP_TIMEOUT)

        elif action == "select":
            loc = self._locator(page, target)
            await loc.first.select_option(value, timeout=STEP_TIMEOUT)

        else:
            raise ValueError(f"Unknown action: {action!r}")

    @staticmethod
    def _locator(page: Page, target: str):
        """Convert a target string to a Playwright locator."""
        if target.startswith("text="):
            return page.get_by_text(target[5:], exact=False)
        if target.startswith("role="):
            # e.g. "role=button[name=Submit]"
            return page.locator(f"[role]").filter(has_text="")   # fallback
        return page.locator(target)


def _fmt(err: Exception) -> str:
    return str(err)[:300]
