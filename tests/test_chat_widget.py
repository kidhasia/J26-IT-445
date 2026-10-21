"""The floating "Ask LUMI" helper: markup, accessibility, honesty, endpoints used, and styles.

These are static checks of the shipped HTML, JavaScript and CSS. How the widget actually behaves (opening, Escape, quick
actions, answers, refusals, errors, the phone layout) is checked in a real browser by scripts/ui_smoke_test.py.
"""

import re

import pytest

from lumi.demo_ui import ASSET_DIR, render_demo_page


@pytest.fixture(scope="module")
def html() -> str:
    return render_demo_page()


@pytest.fixture(scope="module")
def js() -> str:
    return (ASSET_DIR / "app.js").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def css() -> str:
    return (ASSET_DIR / "app.css").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def widget_js(js) -> str:
    start = js.index("floating helper")
    return js[start : js.index("/* ------------------------------------------------------------------ start-up */")]


@pytest.fixture(scope="module")
def widget_html(html) -> str:
    return html[html.index('<div class="chat" id="chat">') : html.index('<script src="/demo/assets/app.js"')]


# ---------------------------------------------------------------- markup and accessibility


def test_there_is_exactly_one_launcher_and_it_starts_closed(html):
    assert html.count('id="chat-launcher"') == 1 and html.count('id="chat-panel"') == 1
    launcher = re.search(r'<button[^>]*id="chat-launcher"[^>]*>', html).group(0)
    assert 'type="button"' in launcher and 'aria-expanded="false"' in launcher and 'aria-controls="chat-panel"' in launcher
    assert "Ask LUMI" in re.search(r'id="chat-launcher".*?</button>', html, re.S).group(0)
    panel = re.search(r'<div[^>]*id="chat-panel"[^>]*>', html).group(0)
    assert 'role="dialog"' in panel and 'aria-labelledby="chat-title"' in panel and " hidden" in panel and 'id="chat-title"' in html


def test_the_widget_sits_in_the_shared_shell_outside_every_page(html):
    assert html.index("</main>") < html.index('<div class="chat" id="chat">') < html.index('<script src="/demo/assets/app.js"')
    assert "</section>" not in html[html.index('<div class="chat" id="chat">') :]  # it is not inside any page section, so it shows on all of them


def test_every_widget_control_has_a_name_and_the_input_has_a_label(widget_html):
    for button_id in ("chat-clear", "chat-min", "chat-close"):
        assert re.search(rf'<button[^>]*id="{button_id}"[^>]*aria-label="[^"]{{8,}}"', widget_html), button_id
    assert 'for="chat-input"' in widget_html and 'id="chat-input"' in widget_html
    assert re.search(r'<button[^>]*type="submit"[^>]*id="chat-send"[^>]*>Send</button>', widget_html)
    assert 'role="log"' in widget_html and 'aria-live="polite"' in widget_html and 'role="group"' in widget_html
    assert widget_html.count("aria-pressed") == 2  # the two mode buttons announce which one is chosen
    assert "aria-hidden=\"true\"" in re.search(r'<span class="chat-tip"[^>]*>', widget_html).group(0)  # the hover tip is not read twice


def test_minimise_and_close_are_described_honestly(widget_html):
    assert "keeps the messages" in widget_html and "clears the messages" in widget_html


def test_the_widget_says_what_it_is_and_is_not(widget_html, widget_js):
    assert "does not write its own answers" in widget_html
    text = (widget_html + widget_js).lower()
    for claim in ("powered by", "ai-powered", "gpt", "generative", "artificial intelligence", "clinically validated by", "approved by"):
        assert claim not in text, claim
    assert "does not diagnose" in widget_js and "make up answers" in widget_js
    assert "not medical sources" in widget_js and "not my own words" not in widget_js.replace("quotes, not my own words", "")


# ---------------------------------------------------------------- behaviour wired to the real endpoints


def test_the_widget_uses_only_the_two_existing_endpoints(widget_js):
    paths = set(re.findall(r'path = "(/api/v1/[a-z-]+)"', widget_js))
    assert paths == {"/api/v1/ask", "/api/v1/rag-demo"}
    assert re.findall(r"fetch\(", widget_js) == ["fetch("]  # one shared request helper, nothing else
    assert "/api/v1/analyze" not in widget_js
    assert "evidence: state.results[kind]" in widget_js  # the existing question endpoint gets a real result from this page
    assert "payload = { question: question };" in widget_js  # the document search gets only the question


def test_without_a_result_nothing_is_invented(widget_js):
    assert "I don't have a result to look at yet" in widget_js
    block = widget_js[widget_js.index('if (mode === "result") {') : widget_js.index('path = "/api/v1/rag-demo"')]
    assert "if (!kind) { noResultMessage(); return; }" in block  # no request is sent when there is no result


def test_answers_labels_and_refusals_come_from_the_server(widget_js):
    assert 'String(body.answer || REFUSAL)' in widget_js  # the refusal shown is the server's own sentence
    assert "answerable === false" in widget_js
    assert '"From your result"' in widget_js and '"From LUMI documents"' in widget_js and '"No answer found"' in widget_js and '"Guide"' in widget_js
    assert "source.citation" in widget_js and "source.passage_id" in widget_js and "source.lines" in widget_js and "source.excerpt" in widget_js
    assert "read back by fixed rules" in widget_js


def test_loading_error_and_empty_states_exist(widget_js):
    assert "Searching LUMI's documents…" in widget_js and "Looking in your result…" in widget_js
    assert "I could not reach the LUMI server" in widget_js and "That took too long" in widget_js
    assert "Document search is switched off on this server" in widget_js
    assert 'setAttribute("aria-busy"' in widget_js and "describeError(res)" in widget_js
    assert "I need your API key" in widget_js and "setKeyPanel(true" in widget_js  # authentication is never bypassed


def test_all_five_quick_actions_exist(widget_js):
    for label in ("How do I use LUMI?", "What can LUMI do?", "Help me understand my analysis result", "Search LUMI research documents", "What are LUMI's limitations?"):
        assert f'label: "{label}"' in widget_js, label


def test_the_helper_never_stores_messages_or_medical_information(js):
    for storage in ("localStorage", "sessionStorage", "indexedDB", "document.cookie", "caches."):
        assert storage not in js, storage


def test_server_text_is_only_ever_inserted_as_text(widget_js):
    for dangerous in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval("):
        assert dangerous not in widget_js
    assert "textContent" in widget_js or 'h("' in widget_js  # built with the page's text-only helpers


def test_keyboard_support_escape_enter_and_focus(widget_js):
    assert 'e.key === "Escape" && chat.open' in widget_js and 'hideChat(true)' in widget_js  # Escape closes and returns focus to the launcher
    assert 'e.key === "Enter" && !e.shiftKey' in widget_js
    assert '$("chat-input").focus()' in widget_js and '$("chat-launcher").focus()' in widget_js
    assert 'setAttribute("aria-expanded"' in widget_js


def test_the_helper_hides_document_search_when_the_server_has_it_off(widget_js):
    assert "reference_search" in widget_js and "referenceSearchOff()" in widget_js


# ---------------------------------------------------------------- styles


def test_the_launcher_is_fixed_bottom_right_and_does_not_cover_content(css):
    rule = re.search(r"\.chat \{([^}]*)\}", css).group(1)
    assert "position: fixed" in rule and "right:" in rule and "bottom:" in rule and "safe-area-inset" in rule
    assert re.search(r"#main \{ padding-bottom: (\d+)px", css) and int(re.search(r"#main \{ padding-bottom: (\d+)px", css).group(1)) >= 96


def test_motion_is_gentle_and_stops_when_the_user_asks(css):
    frames = re.search(r"@keyframes lumi-float \{(.*?)\}\s*\}", css, re.S).group(1)
    assert max(int(n) for n in re.findall(r"translateY\(-(\d+)px\)", frames)) <= 6  # a small bob, not a bounce
    assert "animation-play-state: paused" in css  # it stops while hovered, focused or open
    reduced = css[css.index("@media (prefers-reduced-motion: reduce)") :].split("}\n}")[0]
    assert ".chat-launcher { animation: none; }" in reduced and "transition: none" in reduced


def test_touch_targets_and_phone_layout(css):
    assert int(re.search(r"\.chat-launcher \{[^}]*min-height: (\d+)px", css).group(1)) >= 44
    assert int(re.search(r"\.chat-icon-btn \{[^}]*width: (\d+)px; height: (\d+)px", css).group(1)) >= 40
    assert int(re.search(r"\.chat-mode \{[^}]*min-height: (\d+)px", css).group(1)) >= 40
    phone = css[css.index("@media (max-width: 600px) {\n  .chat {") :]
    assert ".chat-panel { width: 100%" in phone and "max-height: calc(100vh" in phone
    assert "@media print { .chat { display: none; } }" in css


def test_the_widget_uses_the_existing_palette_only(css):
    block = css[css.index("/* Floating helper") :]
    for colour in re.findall(r"#[0-9a-fA-F]{3,8}\b", block):
        pytest.fail(f"a colour is hard-coded instead of using the page's tested palette: {colour}")
    assert "var(--on-accent)" in block and "var(--accent)" in block and "var(--ink)" in block
