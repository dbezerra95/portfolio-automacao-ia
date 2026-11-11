import json
import time
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError, sync_playwright


def collect(url: str, username: str, password: str, competencia: str, output: Path, timeout_ms: int = 3000, attempts: int = 3) -> Path:
    """Download the report and append operational events without participant data."""
    output.mkdir(parents=True, exist_ok=True)
    audit = output / "audit.jsonl"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(accept_downloads=True, locale="pt-BR", timezone_id="America/Sao_Paulo")
        page.set_default_timeout(timeout_ms)
        page.set_default_navigation_timeout(timeout_ms)
        try:
            def run(step: str, action: object) -> None:
                for attempt in range(attempts):
                    start = time.monotonic()
                    try:
                        action()  # type: ignore[operator]
                    except Exception as exc:
                        with audit.open("a", encoding="utf-8") as stream:
                            stream.write(json.dumps({"step": step, "timestamp": datetime.now(timezone.utc).isoformat(), "outcome": "failure", "duration": round(time.monotonic() - start, 3)}) + "\n")
                        if isinstance(exc, PlaywrightTimeoutError) and attempt + 1 < attempts:
                            time.sleep(0.25 * 2**attempt)
                            continue
                        raise
                    with audit.open("a", encoding="utf-8") as stream:
                        stream.write(json.dumps({"step": step, "timestamp": datetime.now(timezone.utc).isoformat(), "outcome": "success", "duration": round(time.monotonic() - start, 3)}) + "\n")
                    return

            def login() -> None:
                page.goto(url, wait_until="domcontentloaded")
                page.locator('[name="username"]').fill(username)
                page.locator('[name="password"]').fill(password)
                page.get_by_role("button", name="Entrar").click()
                page.locator('[name="competencia"]').wait_for()

            def search() -> None:
                page.locator('[name="competencia"]').fill(competencia)
                page.get_by_role("button", name="Consultar").click()
                page.get_by_role("link", name="Exportar relatório").wait_for()

            def download() -> None:
                with page.expect_download() as event:
                    page.get_by_role("link", name="Exportar relatório").click()
                event.value.save_as(output / "sistema.csv")

            run("login", login)
            run("consulta", search)
            run("exportacao", download)
            return output / "sistema.csv"
        except Exception:
            page.screenshot(path=str(output / "falha.png"), full_page=True, timeout=5000)
            raise
        finally:
            browser.close()
