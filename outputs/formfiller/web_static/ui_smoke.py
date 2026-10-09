"""Playwright smoke check against FormFiller's isolated synthetic demo server."""
from __future__ import annotations

import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import os
from pathlib import Path

from playwright.sync_api import sync_playwright


OUTPUTS = Path(__file__).resolve().parents[2]


def available_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_for_server(url: str, process: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("synthetic demo server stopped during startup")
        try:
            with urllib.request.urlopen(url, timeout=1):
                return
        except (urllib.error.URLError, TimeoutError):
            time.sleep(0.15)
    raise RuntimeError("synthetic demo server did not become ready")


def main() -> None:
    port = available_port()
    base_url = f"http://127.0.0.1:{port}"
    server = subprocess.Popen(
        [sys.executable, "-m", "formfiller.web", "--port", str(port)],
        cwd=OUTPUTS,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        wait_for_server(base_url + "/api/session", server)
        with sync_playwright() as playwright:
            edge = Path(os.environ.get(
                "FORMFILLER_UI_EDGE_PATH",
                r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            ))
            launch_options = {"headless": True}
            if edge.is_file():
                launch_options["executable_path"] = str(edge)
            browser = playwright.chromium.launch(**launch_options)
            try:
                page = browser.new_page()
                errors: list[str] = []
                run_calls: list[str] = []
                page.on("pageerror", lambda _error: errors.append("browser script error"))
                page.on("request", lambda request: run_calls.append("run") if request.method == "POST" and request.url.endswith("/api/run") else None)
                page.goto(base_url, wait_until="networkidle")

                assert page.locator("#mode-badge").inner_text() == "Demo · synthetic data"
                assert page.get_by_role("heading", name="Forms", exact=True).count() == 1
                assert page.locator(".summary-strip").count() == 0
                assert page.locator(".form-list-row").count() == 4
                assert page.locator("#choose-workspace").count() == 0

                page.locator(".form-list-row").first.click()
                assert not errors, "frontend raised a browser error before editing"
                assert page.locator("#inline-answer-fields [data-answer]").count() == 2
                capture_path = os.environ.get("FORMFILLER_UI_CAPTURE_PATH")
                if capture_path:
                    page.screenshot(path=capture_path)

                page.get_by_role("button", name="Today").click()
                run_button = page.get_by_role("button", name="Run today's forms")
                assert run_button.is_enabled()
                run_button.click()
                page.get_by_text("Run finished. Refreshing today’s status.").wait_for()
                assert page.locator(".tag.good").count() == 4
                assert page.get_by_role("button", name="Run today's forms").is_disabled()
                assert len(run_calls) == 1

                page.locator('.nav-item[data-view="forms"]').click()
                page.get_by_role("button", name="Add form").click()
                page.locator("#form-name").fill("Smoke added form")
                page.locator("#form-url").fill("https://forms.office.com/Pages/ResponsePage.aspx?id=synthetic-smoke")
                page.get_by_role("button", name="Inspect form").click()
                page.locator("#answers-step").wait_for(state="visible")
                page.locator('#answer-fields [data-answer="q0"]').fill("Synthetic response")
                page.locator('#answer-fields [data-answer="q1"]').select_option(label="Option A")
                page.get_by_role("button", name="Save form").click()
                page.get_by_text("Form saved. Review its readiness before use.").wait_for()

                added_form = page.locator(".form-list-row").filter(has_text="Smoke added form")
                assert added_form.count() == 1
                added_form.click()
                assert page.locator("#reviewed-answers").count() == 1
                page.locator('#inline-answer-fields [data-answer="q0"]').fill("Updated synthetic answer")
                approve = page.get_by_role("button", name="Approve saved answers")
                assert approve.is_disabled()
                assert page.locator("#reviewed-answers").is_disabled()
                assert page.get_by_text("Save changes before reviewing these answers.").is_visible()

                page.locator("#editor-name").fill("Smoke edited form")
                page.get_by_role("button", name="Save changes").click()
                page.get_by_text("Form answers saved.").wait_for()
                assert page.locator("#reviewed-answers").count() == 1
                approve = page.get_by_role("button", name="Approve saved answers")
                assert approve.is_disabled()
                page.locator("#reviewed-answers").check()
                assert approve.is_enabled()
                approve.click()
                page.get_by_text("Saved answers approved for this form.").wait_for()

                page.get_by_role("button", name="Remove form").click()
                page.get_by_role("button", name="Remove form", exact=True).last.click()
                page.locator(".form-list-row").filter(has_text="Smoke edited form").wait_for(state="detached")
                assert page.locator(".form-list-row").count() == 4

                page.get_by_role("button", name="Attendance").click()
                page.get_by_role("button", name="Load roster").click()
                page.locator(".student-row").first.wait_for()
                assert page.locator(".student-row.absent").count() == 2  # pre-marked by the J rule
                page.locator(".mark-button.absent").nth(1).click()
                page.locator(".student-row.absent").nth(2).wait_for()
                page.get_by_role("button", name="Send attendance").click()
                page.get_by_text("Attendance sent.").wait_for()
                assert page.get_by_role("button", name="Send attendance").is_disabled()

                assert not errors, "frontend raised a browser error"
            finally:
                browser.close()
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=5)


if __name__ == "__main__":
    main()
