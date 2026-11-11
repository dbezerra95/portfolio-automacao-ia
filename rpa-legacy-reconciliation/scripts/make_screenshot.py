"""Generate the screenshot of the fictional legacy system."""
import os
import socket
import threading
import time
from pathlib import Path

import uvicorn
from playwright.sync_api import sync_playwright
from rpa_legacy.app import app

os.environ["LEGACY_USER"] = "demo"
os.environ["LEGACY_PASSWORD"] = "demo"
sock = socket.socket()
sock.bind(("127.0.0.1", 0))
sock.listen(128)
url = f"http://127.0.0.1:{sock.getsockname()[1]}"
server = uvicorn.Server(uvicorn.Config(app, log_level="error"))
thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
thread.start()
try:
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    else:
        raise RuntimeError("Server did not start")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(env={**os.environ, "LC_ALL": "pt_BR.UTF-8"})
        page = browser.new_page(locale="pt-BR", timezone_id="America/Sao_Paulo", viewport={"width": 1280, "height": 720})
        page.goto(url)
        page.locator('[name="username"]').fill("demo")
        page.locator('[name="password"]').fill("demo")
        page.get_by_role("button", name="Entrar").click()
        page.screenshot(path=str(Path(__file__).resolve().parent.parent / "docs/sistema.png"), full_page=True)
        browser.close()
finally:
    server.should_exit = True
    thread.join(timeout=5)
