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
        self.wait("document.querySelectorAll('[data-nav]').length === 7")
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
        check("navigation has the seven required entries", [x.split(" In development")[0].split(" Prototype")[0] for x in labels] == ["Overview", "Skin Analysis", "Lab Reports", "Ask a question", "Reference search", "Chest X-ray", "About LUMI"], str(labels))
        b.wait("document.getElementById('server-pill').textContent.includes('connected')")
        check("server status shows connected", "connected" in text(b, "#server-pill"), text(b, "#server-pill"))
        badges = b.js("Array.from(document.querySelectorAll('[data-status-for]')).map(n => n.textContent)")
        check("overview shows real tool status from the server", badges == ["Working · research prototype", "Working · synthetic reports"], str(badges))
        check("overview says the chest X-ray is in development and questions are a small prototype", "In development" in text(b, "#page-overview") and "Small prototype" in text(b, "#page-overview"))
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

        print("FLOATING HELPER (Ask LUMI) before any analysis")
        b.js("location.hash = '#overview'")
        time.sleep(0.4)
        launcher = "document.getElementById('chat-launcher')"
        check("the floating launcher is visible on the overview page", b.js(f"(function(){{var r={launcher}.getBoundingClientRect(); return r.width>40 && r.height>40 && r.right<=window.innerWidth && r.bottom<=window.innerHeight}})()"))
        check("the launcher says Ask LUMI and starts closed", "Ask LUMI" in text(b, "#chat-launcher") and b.js(f"{launcher}.getAttribute('aria-expanded')") == "false" and b.js("document.getElementById('chat-panel').hidden"))
        check("the launcher is in the bottom-right corner", b.js(f"(function(){{var r={launcher}.getBoundingClientRect(); return r.left>window.innerWidth/2 && r.top>window.innerHeight/2}})()"))
        b.js("location.hash = '#skin'"); time.sleep(0.3)
        check("the launcher stays visible after changing pages", b.js(f"!!{launcher} && {launcher}.getBoundingClientRect().width > 40"))
        b.click("#chat-launcher")
        check("clicking the launcher opens the panel and focuses the question box", b.wait("!document.getElementById('chat-panel').hidden && document.activeElement && document.activeElement.id === 'chat-input'", 3) and b.js(f"{launcher}.getAttribute('aria-expanded')") == "true")
        check("the page did not change when the panel opened", b.js("location.hash") == "#skin")
        welcome = text(b, "#chat-log")
        check("the welcome message says what it can and cannot do", "does not diagnose" in welcome and "make up answers" in welcome and "quote" in welcome, welcome)
        check("quick actions are offered", b.js("document.querySelectorAll('#chat-actions .chip').length") >= 4)
        def chat_ask(question):
            b.js(f"document.getElementById('chat-input').value = {json.dumps(question)}")
            before = b.js("document.querySelectorAll('#chat-log .chat-msg.bot').length")
            b.click("#chat-send")
            return b.wait(f"document.querySelectorAll('#chat-log .chat-msg.bot').length > {before} && !document.querySelector('#chat-log [aria-busy=true]') && document.getElementById('chat-send').disabled === false", 20)
        def last_bot():
            return b.js("(function(){var m=document.querySelectorAll('#chat-log .chat-msg.bot'); return m.length ? m[m.length-1].innerText : ''})()") or ""
        def click_action(label):
            b.js(f"Array.from(document.querySelectorAll('#chat-actions .chip')).filter(c => c.innerText.trim() === {json.dumps(label)})[0].click()")
            time.sleep(0.4)
        click_action("How do I use LUMI?")
        check("'How do I use LUMI?' gives a labelled guide, not an answer", "Guide" in last_bot() and "Skin Analysis" in last_bot() and "synthetic" in last_bot(), last_bot())
        click_action("What can LUMI do?")
        check("'What can LUMI do?' is honest about status", "does not diagnose" in last_bot() and "Chest X-ray: still in development" in last_bot() and "not been clinically validated" in last_bot(), last_bot())
        click_action("Help me understand my analysis result")
        check("with no result yet, the helper says so and links to the analysis pages", "don't have a result" in last_bot() and b.js("document.querySelectorAll('#chat-log .chat-links a').length") == 2, last_bot())
        check("the document question is answered with cited, labelled passages", chat_ask("Was the model trained from scratch?") and "From LUMI documents" in last_bot() and "R1" in last_bot() and "passage panel-defence:" in last_bot() and "lines" in last_bot(), last_bot())
        check("quoted passages are marked as quotes, not medical advice", "quotes, not my own words" in last_bot() and "not medical advice" in last_bot().lower(), last_bot())
        b.shot(out, "06d_helper_documents_desktop")
        check("an unrelated question gets the exact refusal", chat_ask("What is the capital of France?") and "I cannot answer this from the available evidence." in last_bot() and "No answer found" in last_bot(), last_bot())
        check("a diagnosis request is refused", chat_ask("Tell me if this photo shows melanoma.") and "I cannot answer this from the available evidence." in last_bot(), last_bot())
        b.js("document.getElementById('chat-mode-result').click()"); time.sleep(0.2)
        check("in My result mode with no result, nothing is invented", chat_ask("What was the predicted skin class?") and "don't have a result" in last_bot(), last_bot())
        b.js("document.getElementById('chat-mode-docs').click()")
        click_action("What are LUMI's limitations?")
        time.sleep(1.5)
        check("'What are LUMI's limitations?' searches the documents", "From LUMI documents" in last_bot() and "imitation" in last_bot(), last_bot())
        b.js("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true}))"); time.sleep(0.3)
        check("Escape closes the panel and returns focus to the launcher", b.js("document.getElementById('chat-panel').hidden") and b.js("document.activeElement.id") == "chat-launcher")
        b.click("#chat-launcher"); time.sleep(0.3)
        check("reopening keeps the messages (minimise/Escape does not clear)", b.js("document.querySelectorAll('#chat-log .chat-msg').length") > 8)
        b.click("#chat-min"); time.sleep(0.3)
        check("minimise hides the panel", b.js("document.getElementById('chat-panel').hidden"))
        b.click("#chat-launcher"); time.sleep(0.3); b.click("#chat-close"); time.sleep(0.3)
        b.click("#chat-launcher"); time.sleep(0.3)
        check("close clears the conversation (only the welcome message remains)", b.js("document.querySelectorAll('#chat-log .chat-msg').length") == 1, str(b.js("document.querySelectorAll('#chat-log .chat-msg').length")))
        check("nothing from the chat is kept in browser storage", b.js("localStorage.length + sessionStorage.length") == 0)
        b.click("#chat-min")

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
        check("skin result shows six class scores", done, str(b.js("document.querySelectorAll('#skin-result .score-row').length")))
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

        print("ASK A QUESTION (uses the results produced above)")
        b.js("location.hash = '#ask'")
        time.sleep(0.4)
        check("both results are offered as sources", b.js("!document.getElementById('ask-src-skin').disabled && !document.getElementById('ask-src-lab').disabled"))
        check("example questions are shown", b.js("document.querySelectorAll('#ask-examples .chip').length") >= 3)

        def ask_question(source, question):
            b.js(f"document.getElementById('ask-src-{source}').click()")
            b.js(f"document.getElementById('ask-question').value = {json.dumps(question)}")
            b.js("document.getElementById('ask-result').textContent = ''")  # so an old answer cannot be mistaken for the new one
            b.click("#ask-go")
            return b.wait("!!(document.querySelector('#ask-result .answer-text') || document.querySelector('#ask-result .callout.err'))", 20)

        check("a lab question is answered from the evidence", ask_question("lab", "Which lab values were not found?") and "Haemoglobin" in text(b, "#ask-result .answer-text"), text(b, "#ask-result"))
        check("the evidence-not-verified warning is shown", "genuine or unchanged" in text(b, "#ask-result"))
        check("the clinical boundary is shown with the answer", "Clinical boundary" in text(b, "#ask-result") or "decision support" in text(b, "#ask-result"))
        b.shot(out, "06b_ask_answer_desktop")
        check("a skin question is answered from the evidence", ask_question("skin", "What was the predicted skin class?") and "model's own relative score" in text(b, "#ask-result .answer-text"), text(b, "#ask-result"))
        check("a diagnosis question is refused with the exact sentence", ask_question("skin", "Is this cancer?") and text(b, "#ask-result .answer-text") == "I cannot answer this from the available evidence.", text(b, "#ask-result .answer-text"))
        check("a question about a test that is not on the report is refused", ask_question("lab", "What was the creatinine value?") and text(b, "#ask-result .answer-text") == "I cannot answer this from the available evidence.")
        check("a reworded skin question is answered through the page", ask_question("skin", "Which lesion type did the model pick?") and "highest-scoring class" in text(b, "#ask-result .answer-text"), text(b, "#ask-result .answer-text"))
        check("a reworded lab question is answered through the page", ask_question("lab", "Which results should I double check?") and "Haemoglobin" in text(b, "#ask-result .answer-text"), text(b, "#ask-result .answer-text"))
        check("a judging question is refused through the page", ask_question("lab", "Is the haemoglobin within the reference range?") and text(b, "#ask-result .answer-text") == "I cannot answer this from the available evidence.", text(b, "#ask-result .answer-text"))
        b.js("document.getElementById('ask-question').value = ''")
        b.click("#ask-go")
        check("an empty question shows a message and sends nothing", b.js("!document.getElementById('ask-error').hidden"))
        print("FLOATING HELPER (Ask LUMI) with results on the page")
        b.js("location.hash = '#lab'"); time.sleep(0.3)
        b.click("#chat-launcher"); time.sleep(0.4)
        check("on a page that has a result, the helper starts in My result mode", b.js("document.getElementById('chat-mode-result').getAttribute('aria-pressed')") == "true" and "latest lab report result" in text(b, "#chat-context"), text(b, "#chat-context"))
        check("a result question is answered from the result and labelled", chat_ask("Which lab values were not found?") and "From your result" in last_bot() and "Haemoglobin" in last_bot(), last_bot())
        check("the answer says it comes from the user's own result by fixed rules", "read back by fixed rules" in last_bot(), last_bot())
        check("an unsafe question about the result gets the exact refusal", chat_ask("Is my haemoglobin normal?") and "I cannot answer this from the available evidence." in last_bot(), last_bot())
        click_action("Help me understand my analysis result")
        check("'Help me understand my analysis result' offers questions about the result", b.js("document.querySelectorAll('#chat-log .chat-msg.bot:last-child .chip').length") >= 2, last_bot())
        b.js("document.querySelector('#chat-log .chat-msg.bot:last-child .chip').click()"); time.sleep(1.0)
        check("choosing a suggested result question sends it to the result endpoint", "From your result" in last_bot() or "No answer found" in last_bot(), last_bot())
        b.shot(out, "06e_helper_result_desktop")
        b.js("document.getElementById('key-input').value = 'wrong-key-0000000000'; document.getElementById('key-input').dispatchEvent(new Event('input'))")
        check("a wrong API key shows a friendly problem message in the chat", chat_ask("Which fields need review?") and "Problem" in last_bot() and "API key" in last_bot(), last_bot())
        b.click("#chat-min")

        b.js("document.getElementById('key-input').value = 'wrong-key-0000000000'; document.getElementById('key-input').dispatchEvent(new Event('input'))")
        b.js("document.getElementById('ask-question').value = 'What limitations apply?'")
        b.js("document.getElementById('ask-result').textContent = ''")
        b.click("#ask-go")
        check("a wrong API key shows the key hint on this page too", b.wait("!!document.querySelector('#ask-result .callout.err')", 10) and "API key" in text(b, "#ask-result"))
        b.js("location.reload()")
        time.sleep(1.5)

        print("REFERENCE SEARCH (extractive retrieval demo; needs LUMI_RAG_DEMO=1, which scripts/run_dev.sh sets)")
        b.js("location.hash = '#rag'")
        time.sleep(0.4)
        check("example questions are shown on the reference search page", b.js("document.querySelectorAll('#rag-examples .chip').length") >= 3)

        def rag_question(question):
            b.js(f"document.getElementById('rag-question').value = {json.dumps(question)}")
            b.js("document.getElementById('rag-result').textContent = ''")
            b.click("#rag-go")
            return b.wait("!!(document.querySelector('#rag-result .source-card') || document.querySelector('#rag-result .callout'))", 20)

        check("a project question returns cited passages", rag_question("Was the model trained from scratch?") and b.js("document.querySelectorAll('#rag-result .source-card').length") >= 1, text(b, "#rag-result"))
        check("each passage shows its document, section, passage id and lines", "passage panel-defence:" in text(b, "#rag-result .source-card") and "lines" in text(b, "#rag-result .source-card"), text(b, "#rag-result .source-card"))
        check("the page labels the sources as project documents, not medical advice", "not medical advice" in text(b, "#rag-result") and "not an approved medical" in text(b, "#rag-result"), text(b, "#rag-result"))
        b.shot(out, "06c_reference_search_desktop")
        check("an unrelated question gets the exact refusal", rag_question("What is the capital of France?") and "I cannot answer this from the available evidence." in text(b, "#rag-result"), text(b, "#rag-result"))
        check("a personal medical question is refused", rag_question("Do I have melanoma?") and "I cannot answer this from the available evidence." in text(b, "#rag-result"), text(b, "#rag-result"))

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
            for page in ("overview", "skin", "lab", "ask", "rag", "xray", "about"):
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
        print("FLOATING HELPER on a phone-sized screen")
        b.viewport(390, 844, True)
        b.js("location.hash = '#overview'"); time.sleep(0.3)
        b.click("#chat-launcher"); time.sleep(0.4)
        check("on a phone the open panel fits inside the screen", b.js("(function(){var r=document.getElementById('chat-panel').getBoundingClientRect(); return r.left>=0 && r.right<=window.innerWidth && r.top>=0 && r.bottom<=window.innerHeight})()"))
        check("on a phone the page still does not scroll sideways with the helper open", (b.js("document.documentElement.scrollWidth - document.documentElement.clientWidth") or 0) <= 1)
        check("on a phone the launcher and panel send button are easy to tap", b.js("document.getElementById('chat-send').getBoundingClientRect().height") >= 40 and b.js("document.getElementById('chat-close').getBoundingClientRect().width") >= 40)
        b.shot(out, "08b_helper_mobile")
        b.click("#chat-min")
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
