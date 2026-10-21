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
                capture_dir = os.environ.get("FORMFILLER_UI_CAPTURE_DIR")
                def capture(name: str) -> None:
                    if capture_dir:
                        destination = Path(capture_dir)
                        destination.mkdir(parents=True, exist_ok=True)
                        page.screenshot(path=str(destination / f"{name}.png"), full_page=True)
                page.on("pageerror", lambda _error: errors.append("browser script error"))
                page.on("request", lambda request: run_calls.append("run") if request.method == "POST" and request.url.endswith("/api/run") else None)
                page.goto(base_url, wait_until="networkidle")

                assert page.locator("#mode-badge").inner_text() == "Demo · synthetic data"
                page.get_by_role("heading", name="All your forms in one place!", exact=True).wait_for()
                assert page.get_by_role("heading", name="All your forms in one place!", exact=True).count() == 1
                assert page.locator(".summary-strip").count() == 0
                assert page.locator(".form-list-row").count() == 4
                assert page.locator("#choose-workspace").count() == 0
                # Freshness: synthetic form 4 is seeded as changed on its live site.
                assert page.locator(".form-list-row .fresh-dot.current").count() == 3
                assert page.locator(".form-list-row .fresh-dot.changed").count() == 1
                assert page.locator('.nav-item[data-view="forms"] .nav-alert').count() == 1
                capture("forms")

                page.locator('.nav-item[data-view="setup"]').click()
                page.get_by_role("heading", name="Setup", exact=True).wait_for()
                assert page.get_by_role("heading", name="Setup", exact=True).count() == 1
                assert page.get_by_text("Setup never submits a response.").count() == 1
                capture("setup")
                assert page.locator(".nav-item").count() == 6
                page.get_by_role("button", name="Teacher guide", exact=True).click()
                page.get_by_role("heading", name="Teacher Guide", exact=True).wait_for()
                assert page.get_by_text("No AI account or agent is needed.").count() == 1
                capture("guide")
                assert page.locator('.nav-item[data-view="setup"]').get_attribute("class").split().count("active") == 1
                page.locator('.nav-item[data-view="attendance"]').click()
                page.get_by_role("button", name="Skyward settings", exact=True).click()
                page.get_by_role("heading", name="Skyward settings", exact=True).wait_for()
                assert page.get_by_role("heading", name="Skyward settings", exact=True).count() == 1
                assert page.get_by_text("Read only").count() == 1
                capture("skyward")
                page.locator('.nav-item[data-view="readiness"]').click()
                page.get_by_role("heading", name="Readiness", exact=True).wait_for()
                assert page.get_by_text("Not yet verified").count() >= 1
                assert page.get_by_role("button", name="Read sign-in guide").count() == 1
                assert page.locator(".content-panel .fresh-dot.changed").count() == 1  # absorbed Sync view
                page.get_by_role("button", name="Check now").click()
                page.get_by_text("Local checks completed.").wait_for()
                capture("readiness")
                page.locator('.nav-item[data-view="forms"]').click()
                page.get_by_role("heading", name="All your forms in one place!", exact=True).wait_for()
                assert not page.locator('.optional-schedule').get_attribute('open')
                assert page.get_by_role('button', name='Pause schedule', exact=True).is_hidden()
                page.locator('#find-form').fill('form 2')
                assert page.locator('.form-list-row:visible').count() == 1
                page.locator('#find-form').fill('no synthetic match')
                assert page.locator('#no-form-matches').is_visible()
                page.locator('#find-form').fill('')
                assert page.locator('.form-list-row:visible').count() == 4

                page.locator(".form-list-row").first.click()
                assert not errors, "frontend raised a browser error before editing"
                assert page.locator("#inline-answer-fields [data-answer]").count() == 2
                assert page.locator(".flow-step.done").count() == 3  # saved, approved, scheduled
                page.locator('#inline-answer-fields [data-answer="q0"]').fill("Unsaved synthetic edit")
                assert page.locator(".flow-step.current").get_by_text("Save answers").count() == 1
                page.locator('#inline-answer-fields [data-answer="q0"]').fill("Example answer")
                capture("form-editor")
                capture_path = os.environ.get("FORMFILLER_UI_CAPTURE_PATH")
                if capture_path:
                    page.screenshot(path=capture_path, full_page=True)

                page.get_by_role("button", name="Today").click()
                page.get_by_role("heading", name="Today", exact=True).wait_for()
                capture("today")
                run_button = page.get_by_role("button", name="Run today's forms")
                assert run_button.is_enabled()
                run_button.click()
                page.get_by_text("Run finished. Refreshing today’s status.").wait_for()
                assert page.locator(".tag.good").count() == 4
                assert page.get_by_role("button", name="Run today's forms").is_disabled()
                assert len(run_calls) == 1

                page.locator('.nav-item[data-view="forms"]').click()
                page.get_by_role("heading", name="All your forms in one place!", exact=True).wait_for()
                page.get_by_role("button", name="Add form").click()
                capture("form-details-dialog")
                page.get_by_role("button", name="Inspect form").click()
                page.locator("#dialog-notice").get_by_text("Paste a form URL to continue.").wait_for()
                capture("form-details-error")
                page.locator("#form-name").fill("Smoke added form")
                page.locator("#form-url").fill("https://forms.office.com/Pages/ResponsePage.aspx?id=synthetic-smoke")
                page.get_by_role("button", name="Inspect form").click()
                page.locator("#answers-step").wait_for(state="visible")
                capture("form-answers-dialog")
                page.get_by_role("button", name="Save form").click()
                page.locator('#dialog-notice').wait_for(state='visible')
                assert 'required' in page.locator('#dialog-notice').inner_text().lower()
                page.locator('#answer-fields [data-answer="q0"]').fill("Synthetic response")
                page.locator('#answer-fields [data-answer="q1"]').select_option(label="Option A")
                page.get_by_role("button", name="Save form").click()
                page.get_by_text("Form answers saved.").wait_for()

                added_form = page.locator(".form-list-row").filter(has_text="Smoke added form")
                added_form.wait_for(state="visible")
                assert added_form.count() == 1
                added_form.click()
                assert page.locator("#reviewed-answers").count() == 1
                page.locator('#inline-answer-fields [data-answer="q0"]').fill("Updated synthetic answer")
                approve = page.get_by_role("button", name="Approve saved answers")
                assert approve.is_disabled()
                assert page.locator("#reviewed-answers").is_disabled()
                review_help = page.locator("#review-save-help")
                assert review_help.is_visible(), review_help.evaluate("element => element.outerHTML")

                page.locator("#editor-name").fill("Smoke edited form")
                page.get_by_role("button", name="Save changes").click()
                page.get_by_text("Form answers saved.").wait_for()
                assert page.locator("#reviewed-answers").count() == 1
                approve = page.get_by_role("button", name="Approve saved answers")
                assert approve.is_disabled()
                page.locator("#reviewed-answers").check()
                assert approve.is_enabled()
                approve.click()
                page.get_by_text("Saved answers approved. Submit it now or add it to the schedule.").wait_for()
                assert page.locator('.optional-schedule').get_attribute('open') is not None
                page.get_by_role("button", name="Add to schedule", exact=True).click()
                page.get_by_text("Template added to the school-day schedule.").wait_for()
                page.locator('.optional-schedule summary').click()
                page.get_by_role("button", name="Pause schedule", exact=True).click()
                page.get_by_text("Template paused.").wait_for()
                page.get_by_role('button', name='Fill & submit', exact=True).click()
                page.get_by_text('Form submitted in the demo.').wait_for()
                assert page.get_by_role('button', name='Submitted today', exact=True).is_disabled()
                assert 'Pre-filled from last submission' in page.locator('.prefill-note').inner_text()
                page.reload(wait_until='networkidle')
                page.locator('.form-list-row').filter(has_text='Smoke edited form').click()
                assert page.locator('#inline-answer-fields [data-answer="q0"]').input_value() == 'Updated synthetic answer'
                assert page.locator('#inline-answer-fields [data-answer="q1"]').input_value() == 'Option A'
                assert 'Pre-filled from last submission' in page.locator('.prefill-note').inner_text()
                page.get_by_role("button", name="Refresh questions").click()
                page.get_by_role("button", name="Inspect form").click()
                page.locator("#answers-step").wait_for(state="visible")
                assert page.locator('#answer-fields [data-answer="q0"]').input_value() == "Updated synthetic answer"
                assert page.locator('#answer-fields [data-answer="q1"]').input_value() == "Option A"
                page.locator('#form-dialog [data-close-dialog]').first.click()

                page.get_by_role("button", name="Remove form").click()
                capture("remove-confirm-dialog")
                page.get_by_role("button", name="Remove form", exact=True).last.click()
                page.locator(".form-list-row").filter(has_text="Smoke edited form").wait_for(state="detached")
                assert page.locator(".form-list-row").count() == 4

                page.locator('.nav-item[data-view="attendance"]').click()
                page.get_by_role("heading", name="Attendance Preview", exact=True).wait_for()
                assert page.get_by_role("heading", name="Attendance Preview", exact=True).count() == 1
                page.get_by_role("button", name="Load roster").click()
                page.locator(".student-row").first.wait_for()
                capture("attendance-preview")
                assert page.locator(".student-row.absent").count() == 2  # pre-marked by the J rule
                page.locator(".mark-button.absent").nth(1).click()
                page.locator(".student-row.absent").nth(2).wait_for()
                page.get_by_role("button", name="Simulate attendance (demo)").click()
                page.get_by_text("Synthetic preview simulated. No attendance was sent.").wait_for()
                assert page.get_by_role("button", name="Simulate attendance (demo)").is_disabled()

                page.locator('.nav-item[data-view="history"]').click()
                page.get_by_role("heading", name="History", exact=True).wait_for()
                capture("history")

                page.set_viewport_size({"width": 390, "height": 844})
                page.locator('.nav-item[data-view="readiness"]').click()
                page.get_by_role("heading", name="Readiness", exact=True).wait_for()
                overflow = page.evaluate("""() => ({width: document.documentElement.scrollWidth, viewport: window.innerWidth,
                  elements: Array.from(document.querySelectorAll('*')).filter(e => e.getBoundingClientRect().right > window.innerWidth + 1)
                    .slice(0, 8).map(e => ({tag:e.tagName, cls:e.className, right:Math.round(e.getBoundingClientRect().right)}))})""")
                assert overflow["width"] <= overflow["viewport"], overflow
                page.set_viewport_size({"width": 195, "height": 422})  # 390 px at 200% browser zoom
                overflow = page.evaluate("""() => ({width: document.documentElement.scrollWidth, viewport: window.innerWidth,
                  elements: Array.from(document.querySelectorAll('*')).filter(e => e.getBoundingClientRect().right > window.innerWidth + 1)
                    .slice(0, 8).map(e => ({tag:e.tagName, cls:e.className, right:Math.round(e.getBoundingClientRect().right)}))})""")
                assert overflow["width"] <= overflow["viewport"], overflow

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
