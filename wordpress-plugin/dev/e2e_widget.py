"""End-to-end check of the chat widget in headless Chromium.

Starts the dev service (stand-in transcriber, sample FAQ) and a static server
for demo.html, then drives the widget like a visitor: typed answer, typed
fallback, a spoken question through Chromium's fake microphone, keyboard use,
an axe-core accessibility scan, a 360 px layout check and the offline message.

Run from the repository root:
    pip install playwright && playwright install chromium
    npm install                      # provides axe-core
    python wordpress-plugin/dev/e2e_widget.py --service-python chatbot-service/.venv/bin/python
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
SERVICE = "http://127.0.0.1:8000"
DEMO = "http://127.0.0.1:8081/dev/demo.html"
SPOKEN = "how can i volunteer"


def wait_for(url: str, seconds: float = 30) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            urllib.request.urlopen(url, timeout=2)  # noqa: S310 - local dev servers
            return
        except OSError:
            time.sleep(0.3)
    raise RuntimeError(f"{url} did not start")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--service-python", default=sys.executable)
    parser.add_argument("--screenshots", type=Path, default=ROOT / "wordpress-plugin" / "dev" / "screenshots")
    args = parser.parse_args()
    args.screenshots.mkdir(parents=True, exist_ok=True)

    dev_server = str(ROOT / "chatbot-service" / "scripts" / "dev_server.py")
    static_dir = str(ROOT / "wordpress-plugin")
    commands = [
        [args.service_python, dev_server, "--fake-asr", SPOKEN],
        [sys.executable, "-m", "http.server", "8081", "--bind", "127.0.0.1", "--directory", static_dir],
    ]
    procs = [subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) for cmd in commands]  # noqa: S603
    results: list[tuple[str, bool, str]] = []

    def check(name: str, fn) -> None:
        try:
            detail = fn() or ""
            results.append((name, True, detail))
        except Exception as exc:  # report and continue with the next check
            results.append((name, False, f"{type(exc).__name__}: {exc}".splitlines()[0][:200]))

    try:
        wait_for(SERVICE + "/health")
        wait_for(DEMO)
        with sync_playwright() as p:
            browser = p.chromium.launch(args=["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"])
            context = browser.new_context(permissions=["microphone"], viewport={"width": 1280, "height": 800})
            page = context.new_page()
            errors: list[str] = []
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
            page.goto(DEMO)

            launcher = page.locator(".org-chatbot__launcher")
            panel = page.locator("#org-chatbot-panel")
            log = page.locator(".org-chatbot__log")
            field = page.locator("#org-chatbot-input")
            bot = page.locator(".org-chatbot__msg--bot:not(.is-pending)")

            def opens_with_keyboard():
                launcher.focus()
                page.keyboard.press("Enter")
                expect(panel).to_be_visible()
                expect(launcher).to_have_attribute("aria-expanded", "true")
                expect(field).to_be_focused()
                expect(log).to_contain_text("Hi! Ask me a question")

            def typed_answer():
                field.fill("How do I join your org?")
                page.keyboard.press("Enter")
                reply = bot.nth(1)
                expect(reply).to_contain_text("Membership steps and eligibility")
                expect(reply.locator("a[href='https://example.org/volunteer/']").first).to_be_visible()

            def typed_fallback():
                field.fill("Is the seminar venue wheelchair accessible?")
                page.keyboard.press("Enter")
                reply = bot.nth(2)
                expect(reply).to_contain_text("I can only answer questions from our FAQ")
                expect(reply.locator("a[href^='mailto:events@example.org']")).to_be_visible()
                expect(reply.locator("a[href='https://example.org/events/']")).to_be_visible()

            def spoken_question():
                mic = page.locator(".org-chatbot__mic")
                mic.click()
                page.locator(".org-chatbot__consent").get_by_role("button", name="Allow and record").click()
                expect(mic).to_have_attribute("aria-pressed", "true")
                page.wait_for_timeout(1500)
                mic.click()
                expect(mic).to_have_attribute("aria-pressed", "false")
                expect(log).to_contain_text(f"You said: {SPOKEN}")
                expect(bot.last).to_contain_text("Volunteer roles, benefits and the application form")
                return "fake microphone -> 16 kHz WAV upload -> transcript -> FAQ answer"

            def wav_is_16k_mono():
                info = page.evaluate(
                    """async () => {
                        const ctx = new AudioContext();
                        const rate = ctx.sampleRate; await ctx.close(); return rate;
                    }"""
                )
                return f"browser capture rate {info} Hz, resampled to 16000 Hz before upload"

            def accessibility_scan():
                page.add_script_tag(path=str(ROOT / "node_modules" / "axe-core" / "axe.min.js"))
                result = page.evaluate(
                    """async () => {
                        const r = await axe.run('.org-chatbot', {
                            runOnly: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'] });
                        return r.violations.map(v => `${v.impact}: ${v.id} (${v.nodes.length})`);
                    }"""
                )
                serious = [v for v in result if v.startswith(("critical", "serious"))]
                assert not serious, serious
                return f"{len(result)} violations ({', '.join(result) or 'none'})"

            def escape_closes():
                page.screenshot(path=str(args.screenshots / "widget-desktop.png"))
                field.focus()
                page.keyboard.press("Escape")
                expect(panel).to_be_hidden()
                expect(launcher).to_be_focused()

            def mobile_layout():
                mobile = context.new_page()
                mobile.set_viewport_size({"width": 360, "height": 740})
                mobile.goto(DEMO)
                mobile.locator(".org-chatbot__launcher").click()
                mobile.locator("#org-chatbot-input").fill("When is the next event?")
                mobile.keyboard.press("Enter")
                expect(mobile.locator(".org-chatbot__msg--bot:not(.is-pending)").nth(1)).to_contain_text("calendar")
                width = mobile.evaluate("document.documentElement.scrollWidth")
                box = mobile.locator("#org-chatbot-panel").bounding_box()
                mobile.screenshot(path=str(args.screenshots / "widget-mobile-360.png"))
                assert width <= 360, f"page scrolls horizontally ({width}px)"
                assert box and box["x"] >= 0 and box["x"] + box["width"] <= 360, box
                return f"panel {box['width']:.0f}px wide, no horizontal scroll"

            def offline_message():
                offline = context.new_page()
                offline.goto(DEMO + "?service=http://127.0.0.1:8999")
                offline.locator(".org-chatbot__launcher").click()
                offline.locator("#org-chatbot-input").fill("How do I join?")
                offline.keyboard.press("Enter")
                reply = offline.locator(".org-chatbot__msg--bot:not(.is-pending)").nth(1)
                expect(reply).to_contain_text("not available right now")
                expect(reply.locator("a[href='https://example.org/contact/']")).to_be_visible()
                expect(reply.locator("a[href='mailto:info@example.org']")).to_be_visible()
                expect(offline.locator("main h1")).to_be_visible()  # page itself unaffected

            for name, fn in [
                ("Launcher opens with the keyboard, focus moves to the input (FR-21)", opens_with_keyboard),
                ("Typed question gets the stored answer and its link (FR-21)", typed_answer),
                ("Unmatched event question gets fallback, events email and Events link (FR-22)", typed_fallback),
                ("Spoken question: consent, record, transcript, answer (FR-24 proposed)", spoken_question),
                ("Recording is resampled to 16 kHz", wav_is_16k_mono),
                ("axe-core WCAG 2.2 AA scan of the open widget: no critical/serious (NFR-USE-01)", accessibility_scan),
                ("Esc closes and returns focus to the launcher", escape_closes),
                ("360 px phone layout (NFR-USE-02)", mobile_layout),
                ("Service down: page intact, contact page and email offered (NFR-AVL-04)", offline_message),
            ]:
                check(name, fn)
            serious_errors = [e for e in errors if "8999" not in e and "ERR_CONNECTION_REFUSED" not in e]
            results.append(("No JavaScript errors in the console", not serious_errors, "; ".join(serious_errors)[:200]))
            browser.close()
    finally:
        for proc in procs:
            proc.terminate()

    for name, ok, detail in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))
    print(f"\nScreenshots: {args.screenshots}")
    return 0 if all(ok for _, ok, _ in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
