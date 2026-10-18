"""Real-browser check of the LUMI demo interface (headless Google Chrome, driven over the DevTools protocol).

What it checks: every page and the navigation, the skin and lab workflows end to end against the running server,
the attention-map toggle, error states (wrong key, bad files, faked server failures), keyboard focus, layout at
four screen widths (no sideways scrolling), console errors, and that nothing is requested from other websites.

Needs: Google Chrome installed, the LUMI server running (scripts/run_dev.sh), and `pip install websocket-client`
(already listed in requirements-dev.txt). Screenshots are written to --out (default data/processed/ui_smoke, which
Git ignores, because they can contain dataset photos).

Usage:
  .venv/bin/python scripts/ui_smoke_test.py --skin-image PATH_TO_PNG --lab-image data/synthetic/lab_reports/syn_0001_complete.png
"""

import argparse
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import websocket

ROOT = Path(__file__).resolve().parent.parent
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PORT = 9333
results: list[tuple[bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((bool(ok), name))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail and not ok else ""))


class Browser:
    def __init__(self, base: str):
        self.base = base.rstrip("/")
        self.profile = tempfile.mkdtemp()
        self.proc = subprocess.Popen(
            [CHROME, "--headless=new", f"--remote-debugging-port={PORT}", "--remote-allow-origins=*", f"--user-data-dir={self.profile}",
             "--no-first-run", "--no-default-browser-check", "--disable-gpu", "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(60):
            try:
                urllib.request.urlopen(f"http://localhost:{PORT}/json/version", timeout=1)
                break
            except Exception:
                time.sleep(0.5)
        target = json.load(urllib.request.urlopen(urllib.request.Request(f"http://localhost:{PORT}/json/new?about:blank", method="PUT")))
        self.ws = websocket.create_connection(target["webSocketDebuggerUrl"], timeout=60)
        self.next_id = 0
        self.problems: list[str] = []
        self.requests: list[str] = []
        self.fake: dict | None = None  # when set, /api/ requests are answered with this instead of reaching the server
        for domain in ("Page", "Runtime", "DOM", "Log", "Network"):
            self.send(f"{domain}.enable")
        self.send("Fetch.enable", patterns=[{"urlPattern": "*/api/v1/analyze*"}])

    def _event(self, msg: dict) -> None:
        method, params = msg.get("method"), msg.get("params", {})
        if method == "Runtime.exceptionThrown":
            self.problems.append("JS exception: " + params["exceptionDetails"]["text"])
        elif method == "Log.entryAdded" and params["entry"]["level"] in ("error", "warning"):
            self.problems.append("browser log: " + params["entry"]["text"][:140])
        elif method == "Network.requestWillBeSent":
            self.requests.append(params["request"]["url"])
        elif method == "Fetch.requestPaused":
            self.next_id += 1
            rid = params["requestId"]
            if self.fake is None:
                command = {"id": self.next_id, "method": "Fetch.continueRequest", "params": {"requestId": rid}}
            elif self.fake.get("fail"):
                command = {"id": self.next_id, "method": "Fetch.failRequest", "params": {"requestId": rid, "errorReason": "ConnectionRefused"}}
            else:
                body = base64.b64encode(self.fake["body"].encode()).decode()
                headers = [{"name": "Content-Type", "value": "application/json"}] + [{"name": k, "value": v} for k, v in self.fake.get("headers", {}).items()]
                command = {"id": self.next_id, "method": "Fetch.fulfillRequest", "params": {"requestId": rid, "responseCode": self.fake["status"], "responseHeaders": headers, "body": body}}
            self.ws.send(json.dumps(command))  # fire and forget: never wait inside the event loop

    def send(self, method: str, **params):
        self.next_id += 1
        mid = self.next_id
        self.ws.send(json.dumps({"id": mid, "method": method, "params": params}))
        while True:
            msg = json.loads(self.ws.recv())
            if "method" in msg:
                self._event(msg)
            if msg.get("id") == mid:
                return msg.get("result", {})

    def js(self, expression: str):
        out = self.send("Runtime.evaluate", expression=expression, returnByValue=True, awaitPromise=True)
        return out.get("result", {}).get("value")

    def wait(self, expression: str, seconds: float = 20) -> bool:
        end = time.time() + seconds
        while time.time() < end:
            if self.js(expression):
                return True
            time.sleep(0.2)
        return False

    def goto(self, url: str) -> None:
        self.send("Page.navigate", url=url)
        self.wait("document.readyState === 'complete'")
        self.wait("document.querySelectorAll('[data-nav]').length === 5")
        time.sleep(0.4)

    def viewport(self, width: int, height: int = 900, mobile: bool = False) -> None:
        self.send("Emulation.setDeviceMetricsOverride", width=width, height=height, deviceScaleFactor=2 if mobile else 1, mobile=mobile)

    def shot(self, out: Path, name: str) -> None:
        data = self.send("Page.captureScreenshot", format="png", captureBeyondViewport=True)["data"]
        (out / f"{name}.png").write_bytes(base64.b64decode(data))

    def choose_file(self, selector: str, path: str) -> None:
        root = self.send("DOM.getDocument")["root"]["nodeId"]
        node = self.send("DOM.querySelector", nodeId=root, selector=selector)["nodeId"]
        self.send("DOM.setFileInputFiles", files=[str(Path(path).resolve())], nodeId=node)

    def click(self, selector: str) -> None:
        self.js(f"document.querySelector({json.dumps(selector)}).click()")

    def press_tab(self, shift: bool = False) -> None:
        for kind in ("keyDown", "keyUp"):
            self.send("Input.dispatchKeyEvent", type=kind, key="Tab", code="Tab", windowsVirtualKeyCode=9, modifiers=8 if shift else 0)

    def close(self) -> None:
        self.proc.terminate()
        shutil.rmtree(self.profile, ignore_errors=True)


def text(b: Browser, selector: str) -> str:
    return b.js(f"(document.querySelector({json.dumps(selector)})||{{}}).innerText || ''") or ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8000")
    ap.add_argument("--out", default=str(ROOT / "data" / "processed" / "ui_smoke"))
    ap.add_argument("--key", default="local-dev-key-not-for-production")
    ap.add_argument("--skin-image", required=True)
    ap.add_argument("--lab-image", required=True)
    ap.add_argument("--lab-missing-image", default=str(ROOT / "data/synthetic/lab_reports/syn_0002_missing_value.png"))
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    scratch = Path(tempfile.mkdtemp())
    (scratch / "notes.txt").write_text("not an image")
    (scratch / "broken.png").write_bytes(b"\x89PNG\r\n\x1a\nthis is not really a png")

    b = Browser(args.url)
    try:
        b.viewport(1440, 900)
        print("PAGES AND NAVIGATION")
        b.goto(args.url + "/")
        check("opening / lands on the demo page", b.js("location.pathname") == "/demo", b.js("location.pathname"))
        check("overview is the first page and the others are hidden", b.js("!document.getElementById('page-overview').hidden && ['skin','lab','xray','about'].every(p => document.getElementById('page-'+p).hidden)"))
        labels = b.js("Array.from(document.querySelectorAll('[data-nav]')).map(a => a.innerText.replace(/\\s+/g,' ').trim())")
        check("navigation has the five required entries", [x.split(" In development")[0] for x in labels] == ["Overview", "Skin Analysis", "Lab Reports", "Chest X-ray", "About LUMI"], str(labels))
        b.wait("document.getElementById('server-pill').textContent.includes('connected')")
        check("server status shows connected", "connected" in text(b, "#server-pill"), text(b, "#server-pill"))
        badges = b.js("Array.from(document.querySelectorAll('[data-status-for]')).map(n => n.textContent)")
        check("overview shows real tool status from the server", badges == ["Working · research prototype", "Working · synthetic reports"], str(badges))
        check("overview says the chest X-ray is in development and questions are API only", "In development" in text(b, "#page-overview") and "API only" in text(b, "#page-overview"))
        b.shot(out, "01_overview_desktop")

        for page, heading in (("skin", "Skin photo analysis"), ("lab", "Lab report reading"), ("xray", "Chest X-ray analysis"), ("about", "About LUMI")):
            b.js(f"location.hash = '#{page}'")
            time.sleep(0.4)
            visible = b.js(f"!document.getElementById('page-{page}').hidden && ['overview','skin','lab','xray','about'].filter(p => p !== '{page}').every(p => document.getElementById('page-'+p).hidden)")
            check(f"#{page} shows only its own page", visible)
            check(f"#{page} heading is correct", heading in text(b, f"#page-{page} h1"), text(b, f"#page-{page} h1"))
            check(f"#{page} marks its navigation entry as current", b.js(f"document.querySelector('[data-nav={page}]').getAttribute('aria-current') === 'page'"))
        b.js("location.hash = '#xray'")
        time.sleep(0.3)
        check("chest X-ray page says it is unfinished and offers no upload", "not available yet" in text(b, "#page-xray") and b.js("document.querySelectorAll('#page-xray input[type=file]').length") == 0 and b.js("document.querySelectorAll('#page-xray button').length") == 0)
        b.shot(out, "02_xray_desktop")
        b.js("location.hash = '#about'")
        time.sleep(0.5)
        about = text(b, "#page-about")
        check("about page lists limitations, the dataset and the missing pediatric validation", all(s in about for s in ("PAD-UFES-20", "Not validated for children", "Not clinically validated", "experimental") if s != "experimental") and "attention map" in about.lower())
        check("about page shows the real model facts from the server", "efficientnet_b0" in text(b, "#about-model") and "Macro-F1" in text(b, "#about-model"), text(b, "#about-model"))
        b.shot(out, "03_about_desktop")

        print("SKIN ANALYSIS (real server, real model)")
        b.js("location.hash = '#skin'")
        time.sleep(0.4)
        check("API key is pre-filled in local dev mode (and hidden)", b.js("document.getElementById('key-input').value.length") > 10 and b.js("document.getElementById('key-input').type") == "password")
        b.choose_file("#skin-file", args.skin_image)
        time.sleep(0.6)
        check("choosing a photo shows a preview card", b.js("!document.getElementById('skin-filecard').hidden") and "px" in text(b, "#skin-filesub"), text(b, "#skin-filesub"))
        b.click("#skin-go")
        check("loading state appears while analysing", b.wait("document.getElementById('skin-go').disabled === true || document.querySelector('#skin-result .loading')", 3))
        done = b.wait("document.querySelectorAll('#skin-result .score-row').length === 6", 40)
        check("skin result shows six class scores", done)
        check("button is enabled again after the analysis", b.js("!document.getElementById('skin-go').disabled"))
        check("highest-scoring class is shown", len(text(b, "#skin-result .top-class .name")) > 3, text(b, "#skin-result .top-class .name"))
        check("scores are labelled as not clinical probabilities", "not calibrated probabilities" in text(b, "#skin-result") and "not clinical certainty" in text(b, "#skin-result"))
        pair = b.js("(function(){var i=document.querySelectorAll('#skin-result .xai-pair img'); return Array.from(i).map(x => x.naturalWidth)})()")
        check("original photo and attention map are shown side by side (both decoded)", isinstance(pair, list) and len(pair) == 2 and all(w > 0 for w in pair), str(pair))
        label = text(b, "#skin-result .xai-label")
        check("the attention-map disclaimer is visible", "AI attention visualisation" in label and "not a diagnosis or proof of correctness" in label, label)
        check("limitations and the clinical boundary are shown", "children" in text(b, "#skin-result") and "Clinical boundary" in text(b, "#skin-result"))
        b.shot(out, "04_skin_result_desktop")

        b.js("document.getElementById('skin-explain').click()")  # switch the attention map off
        b.click("#skin-go")
        b.wait("document.querySelectorAll('#skin-result .score-row').length === 6", 40)
        check("with the attention map switched off, no map image is requested or shown", b.js("document.querySelectorAll('#skin-result .xai-pair').length") == 0 and "switched off" in text(b, "#skin-result"))
        b.js("document.getElementById('skin-explain').click()")

        print("LAB REPORT (real server, OCR)")
        b.js("location.hash = '#lab'")
        time.sleep(0.4)
        b.choose_file("#lab-file", args.lab_image)
        time.sleep(0.4)
        b.click("#lab-go")
        b.wait("document.querySelectorAll('#lab-result tbody tr').length > 0", 40)
        rows = b.js("document.querySelectorAll('#lab-result tbody tr').length")
        check("lab report result shows a table of 6 rows", rows == 6, str(rows))
        first = b.js("Array.from(document.querySelectorAll('#lab-result tbody tr')[0].children).map(c => c.innerText.split('\\n')[0])")
        check("first row is read correctly (test, result, unit, range)", first and first[:4] == ["Haemoglobin", "12.1", "g/dL", "11.5 - 15.5"], str(first))
        check("lab page warns that values must be checked", "Check every value against the original report" in text(b, "#lab-result"))
        b.shot(out, "05_lab_result_desktop")
        b.choose_file("#lab-file", args.lab_missing_image)
        time.sleep(0.4)
        b.click("#lab-go")
        b.wait("document.querySelectorAll('#lab-result .badge.warn').length > 0", 40)
        check("a missing value is clearly labelled 'Not found'", "Not found" in text(b, "#lab-result tbody") and "Check against the original" in text(b, "#lab-result tbody"))
        b.shot(out, "06_lab_missing_desktop")

        print("ERROR HANDLING")
        b.js("location.hash = '#skin'")
        time.sleep(0.3)
        b.js("document.getElementById('skin-clear').click()")
        b.choose_file("#skin-file", str(scratch / "notes.txt"))
        time.sleep(0.4)
        check("a text file is rejected in the browser with a clear message", "not supported" in text(b, "#skin-error"), text(b, "#skin-error"))
        b.click("#skin-go")
        check("analysing with no file says to choose one", "Choose a file" in text(b, "#skin-error"), text(b, "#skin-error"))
        b.choose_file("#skin-file", str(scratch / "broken.png"))
        time.sleep(0.4)
        b.click("#skin-go")
        b.wait("document.querySelector('#skin-result .callout.err')", 20)
        check("a damaged image gets a friendly server error", "could not be opened" in text(b, "#skin-result") or "not accepted" in text(b, "#skin-result"), text(b, "#skin-result")[:120])

        b.js("document.getElementById('key-input').value = 'wrong-key'; document.getElementById('key-input').dispatchEvent(new Event('input'))")
        b.choose_file("#skin-file", args.skin_image)
        time.sleep(0.4)
        b.click("#skin-go")
        b.wait("document.querySelector('#skin-result .callout.err')", 20)
        check("a wrong API key shows an explanation and opens the key box", "API key was not accepted" in text(b, "#skin-result") and b.js("!document.getElementById('key-panel').hidden"))
        b.js("document.getElementById('key-input').value = ''; document.getElementById('key-input').dispatchEvent(new Event('input'))")
        b.click("#skin-go")
        check("a missing key asks for it without sending anything", "Enter your API key" in text(b, "#key-panel") and "needed" in text(b, "#key-state"))
        b.js("document.getElementById('key-input').value = " + json.dumps(args.key) + "; document.getElementById('key-input').dispatchEvent(new Event('input'))")
        b.js("document.getElementById('key-toggle').click()")

        faked = (
            ("server error 500", {"status": 500, "body": json.dumps({"error": {"code": "internal_error", "message": "An internal error occurred."}})}, "Something went wrong"),
            ("model not set up 503", {"status": 503, "body": json.dumps({"error": {"code": "model_unavailable", "message": "not set up"}})}, "not set up on this server"),
            ("rate limit 429", {"status": 429, "headers": {"Retry-After": "12"}, "body": json.dumps({"error": {"code": "rate_limited", "message": "slow down"}})}, "about 12 seconds"),
            ("too large 413", {"status": 413, "body": json.dumps({"error": {"code": "file_too_large", "message": "big"}})}, "too large"),
            ("proxy HTML instead of JSON", {"status": 502, "body": "<html><script>alert(1)</script>Bad gateway</html>"}, "Something went wrong"),
            ("server unreachable", {"fail": True}, "Could not reach the LUMI server"),
        )
        for label_text, fake, expected in faked:
            b.fake = fake
            b.click("#skin-go")
            b.wait("document.querySelector('#skin-result .callout.err')", 20)
            shown = text(b, "#skin-result")
            check(f"faked failure ({label_text}) shows a friendly message", expected in shown, shown[:140])
            check(f"faked failure ({label_text}) shows no stack trace or raw HTML", "Traceback" not in shown and "<script" not in shown and "Bad gateway" not in shown)
        b.fake = None

        print("SAFETY OF DISPLAYED CONTENT")
        evil = {"error": None, "result": {"pipeline": "lab_report_ocr", "status": "completed", "engine": {"name": "<img src=x onerror=window.__pwned=1>", "version": "1"},
                "mean_ocr_confidence": 50, "fields_needing_review": 1, "extracted_text": "<script>window.__pwned=1</script>\n<b>bold</b>",
                "fields": [{"test_name": "<img src=x onerror=window.__pwned=1>", "value": "<b>1</b>", "unit": None, "reference_range": None, "missing_fields": ["unit"], "needs_review": True, "line_number": 1, "source_text": "x", "ocr_confidence": 50}],
                "reference_range_note": "<i>note</i>"}, "warnings": ["OCR_NOT_VALIDATED: <script>window.__pwned=1</script>"], "clinical_boundary_notice": "<b>notice</b>"}
        b.js("location.hash = '#lab'")
        time.sleep(0.3)
        b.choose_file("#lab-file", args.lab_image)
        b.fake = {"status": 200, "body": json.dumps(evil)}
        b.click("#lab-go")
        b.wait("document.querySelectorAll('#lab-result tbody tr').length > 0", 20)
        time.sleep(0.4)
        b.fake = None
        check("hostile text from the server is displayed as plain text, never run", b.js("window.__pwned") is None and b.js("document.querySelectorAll('#lab-result img, #lab-result script, #lab-result b, #lab-result i').length") == 0)
        check("the hostile text is still visible to the user as text", "<script>" in text(b, "#lab-result"))

        print("KEYBOARD")
        b.viewport(1440, 900)
        b.goto(args.url + "/")  # a fresh page load, as a keyboard user would start
        b.press_tab()
        first_focus = b.js("document.activeElement.className + '|' + document.activeElement.textContent.trim().slice(0,20)")
        check("the first Tab stop is the 'Skip to main content' link", "skip-link" in str(first_focus), str(first_focus))
        seen = 0
        for _ in range(8):
            b.press_tab()
            outline = b.js("getComputedStyle(document.activeElement).outlineStyle + ' ' + getComputedStyle(document.activeElement).outlineWidth")
            if outline and not str(outline).startswith("none"):
                seen += 1
        check("keyboard focus is visibly outlined on the next controls", seen >= 6, f"{seen} of 8")

        print("CONSOLE, NETWORK AND SECURITY")
        origin = args.url.rstrip("/")
        external = [u for u in b.requests if not (u.startswith(origin) or u.startswith("data:") or u.startswith("blob:") or u.startswith("about:"))]
        check("no request went to any other website", not external, str(external[:3]))
        scripts = b.js("Array.from(document.scripts).map(s => s.src || '(inline)')")
        check("only one script is used and it comes from this server", scripts == [origin + "/demo/assets/app.js"], str(scripts))
        expected_noise = ("401", "429", "413", "500", "502", "503", "ERR_CONNECTION_REFUSED", "Failed to load resource")
        unexpected = [p for p in b.problems if not any(e in p for e in expected_noise)]
        check("no JavaScript errors or security-policy violations", not unexpected, str(unexpected[:3]))

        print("RESPONSIVE LAYOUT (no sideways scrolling)")
        for width, height, mobile in ((1440, 900, False), (1024, 800, False), (768, 1000, False), (390, 844, True)):
            b.viewport(width, height, mobile)
            for page in ("overview", "skin", "lab", "xray", "about"):
                b.js(f"location.hash = '#{page}'")
                time.sleep(0.25)
                overflow = b.js("document.documentElement.scrollWidth - document.documentElement.clientWidth")
                check(f"{width}px wide, {page} page: no horizontal overflow", overflow is not None and overflow <= 1, f"overflow {overflow}px")
            b.js("location.hash = '#skin'")
            time.sleep(0.3)
            b.shot(out, f"07_skin_{width}")
        b.js("location.hash = '#overview'")
        time.sleep(0.3)
        b.shot(out, "08_overview_mobile")
    finally:
        b.close()
        shutil.rmtree(scratch, ignore_errors=True)

    failed = [name for ok, name in results if not ok]
    print(f"\n{len(results) - len(failed)} of {len(results)} browser checks passed.")
    for name in failed:
        print("  FAILED:", name)
    print(f"Screenshots: {out}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
