"""The local demo interface: serving, security policy, safe display, honesty about unfinished tools, accessibility,
and consistency with the server's own rules. (The page is also exercised in real Chrome by scripts/ui_smoke_test.py.)"""

import dataclasses
import re
from html.parser import HTMLParser

import pytest
import torch
from fastapi.testclient import TestClient

from lumi.config import Settings
from lumi.demo_ui import ASSET_DIR, ASSET_HEADERS, ASSETS, DEMO_PAGE_HEADERS, read_asset, render_demo_page
from lumi.main import create_app
from lumi.ml.gradcam import LABEL as SERVER_ATTENTION_LABEL
from lumi.ml.skin_data import CLASSES
from lumi.ml.skin_model import build_model, save_checkpoint
from lumi.schemas import ErrorCode, InputType
from lumi.validation import ALLOWED_MIME_TYPES
from tests.conftest import AUTH_HEADERS, build_test_service

SVG_NAMESPACE = "http://www.w3.org/2000/svg"  # an XML identifier inside inline icons, not an address anything loads from


def make_client(settings: Settings, **overrides) -> TestClient:
    return TestClient(create_app(settings=dataclasses.replace(settings, **overrides), service=build_test_service()))


def asset_text(name: str) -> str:
    return (ASSET_DIR / name).read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def html_text() -> str:
    return render_demo_page()


@pytest.fixture(scope="module")
def js() -> str:
    return asset_text("app.js")


@pytest.fixture(scope="module")
def css() -> str:
    return asset_text("app.css")


# ---------------------------------------------------------------- serving


def test_everything_is_off_by_default(settings):
    client = make_client(settings)
    for path in ("/", "/demo", "/demo/assets/app.js", "/demo/assets/app.css", "/demo/assets/favicon.svg"):
        assert client.get(path, follow_redirects=False).status_code == 404, path


def test_page_and_assets_are_served_when_enabled(settings):
    client = make_client(settings, demo_ui=True)
    root = client.get("/", follow_redirects=False)
    assert root.status_code in (301, 302, 307, 308) and root.headers["location"] == "/demo"
    page = client.get("/demo")
    assert page.status_code == 200 and page.headers["content-type"].startswith("text/html")
    for name, media_type in ASSETS.items():
        response = client.get(f"/demo/assets/{name}")
        assert response.status_code == 200 and response.headers["content-type"].startswith(media_type.split(";")[0]), name
        for header, value in ASSET_HEADERS.items():
            assert response.headers[header] == value


@pytest.mark.parametrize("path", ["/demo/assets/index.html", "/demo/assets/app.py", "/demo/assets/..%2Fmain.py", "/demo/assets/%2e%2e/main.py", "/demo/assets/../../config.py", "/demo/assets/APP.JS", "/demo/assets/app.js/"])
def test_only_the_three_listed_assets_can_be_requested(settings, path):
    assert make_client(settings, demo_ui=True).get(path, follow_redirects=False).status_code in (404, 307)
    # 307 only for the trailing-slash redirect form; the redirect target must also not leak anything
    response = make_client(settings, demo_ui=True).get(path)
    assert response.status_code == 404 or b"def " not in response.content


def test_read_asset_is_a_strict_allow_list():
    assert read_asset("app.js") is not None and read_asset("app.css") is not None and read_asset("favicon.svg") is not None
    for bad in ("index.html", "../main.py", "app.js/", "", "app.JS", "assets/app.js", "..", "__init__.py"):
        assert read_asset(bad) is None, bad


def test_assets_cannot_be_posted_to_and_are_not_in_the_api_schema(settings):
    client = make_client(settings, demo_ui=True)
    assert client.post("/demo/assets/app.js").status_code == 405
    paths = client.get("/openapi.json").json()["paths"]
    assert not any(path.startswith("/demo") or path == "/" for path in paths)


# ---------------------------------------------------------------- security policy


def test_content_security_policy_allows_only_this_server(settings):
    response = make_client(settings, demo_ui=True).get("/demo")
    for name, value in DEMO_PAGE_HEADERS.items():
        assert response.headers[name] == value
    policy = response.headers["content-security-policy"]
    for required in ("default-src 'none'", "script-src 'self'", "style-src 'self'", "connect-src 'self'", "object-src 'none'",
                     "base-uri 'none'", "form-action 'none'", "frame-ancestors 'none'", "img-src 'self' blob: data:"):
        assert required in policy, required
    assert "unsafe-inline" not in policy and "unsafe-eval" not in policy and "http" not in policy and "*" not in policy


def test_page_has_no_inline_code_so_the_strict_policy_does_not_break_it(html_text):
    assert not re.search(r"<script(?![^>]*\bsrc=)", html_text), "inline <script> found"
    assert "<style" not in html_text.lower()
    assert not re.search(r"\sstyle\s*=", html_text), "inline style attribute found"
    assert not re.search(r"\son[a-z]+\s*=", html_text, re.IGNORECASE), "inline event handler found"
    assert "javascript:" not in html_text.lower()
    assert re.findall(r"<script[^>]*>", html_text) == ['<script src="/demo/assets/app.js" defer>']


def test_javascript_never_turns_server_text_into_page_code(js):
    for dangerous in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function", "setTimeout(\"", "setInterval(\"",
                      "createContextualFragment", "DOMParser", "srcdoc", "javascript:", "importScripts", "postMessage"):
        assert dangerous not in js, dangerous
    assert "textContent" in js
    assert 'setAttribute("style"' not in js and ".cssText" not in js  # would be blocked by the policy anyway


def test_the_api_key_is_never_stored_or_written_into_source(js, html_text, css):
    for storage in ("localStorage", "sessionStorage", "document.cookie", "indexedDB", "navigator.sendBeacon"):
        assert storage not in js, storage
    for text in (js, css, asset_text("favicon.svg"), html_text):
        assert "local-dev-key" not in text
    assert 'value=""' in html_text  # empty unless the server was configured with a key


def test_a_configured_demo_key_is_prefilled_once_and_html_escaped():
    page = render_demo_page('abc"><script>alert(1)</script>')
    assert "<script>alert(1)</script>" not in page
    assert page.count('value="abc&quot;&gt;&lt;script&gt;alert(1)&lt;/script&gt;"') == 1


def test_nothing_is_loaded_from_other_websites(html_text, js, css):
    for name, text in (("html", html_text), ("js", js), ("css", css)):
        remaining = text.replace(SVG_NAMESPACE, "")
        assert not re.search(r"https?://", remaining), f"external address in {name}"
        assert not re.search(r"""(src|href|action)\s*=\s*["']\s*//""", remaining), name
        assert "@import" not in remaining and "@font-face" not in remaining and "url(" not in remaining.replace("url(#", "")
    assert asset_text("favicon.svg").count("http") == 1 and SVG_NAMESPACE in asset_text("favicon.svg")


def test_the_page_calls_only_the_servers_own_relative_endpoints(js):
    assert re.findall(r"""fetch\(\s*["']([^"']+)["']""", js) == ["/health", "/api/v1/analyze", "/api/v1/ask"]
    assert 'headers: { "Authorization": "Bearer " + key }' in js


def test_the_page_does_not_bypass_api_authentication(settings):
    client = make_client(settings, demo_ui=True)
    assert client.post("/api/v1/analyze", data={"input_type": "skin_image"}).status_code == 401
    assert client.get("/health").status_code == 200


# ---------------------------------------------------------------- consistency with the server's rules


def test_browser_side_limits_match_the_servers(js):
    size = re.search(r"var MAX_BYTES = (\d+) \* (\d+) \* (\d+);", js)
    assert size and int(size[1]) * int(size[2]) * int(size[3]) == Settings().max_upload_bytes
    types = re.search(r"var ALLOWED_TYPES = \[([^\]]+)\];", js)
    assert types and set(re.findall(r'"([^"]+)"', types[1])) == set(ALLOWED_MIME_TYPES[InputType.SKIN_IMAGE])
    assert set(re.findall(r'"([^"]+)"', types[1])) <= set(ALLOWED_MIME_TYPES[InputType.LAB_REPORT])


def test_every_error_code_the_server_can_send_has_a_friendly_message(js):
    block = js[js.index("var ERRORS = {") : js.index("function errorBox")]
    for code in ErrorCode:
        assert re.search(rf"\b{code.value}:", block), f"no friendly message for {code.value}"


def test_the_page_only_ever_submits_skin_and_lab_requests(js):
    assert re.findall(r'inputType: "([a-z_]+)"', js) == ["skin_image", "lab_report"]
    assert "chest_xray" not in js and "medical_question" not in js


def test_the_attention_map_label_is_required_and_images_are_validated(js):
    assert SERVER_ATTENTION_LABEL == "AI attention visualisation — not a diagnosis or proof of correctness."
    assert f'var FALLBACK_LABEL = "{SERVER_ATTENTION_LABEL}";' in js  # the page's fallback wording matches the server's
    assert "image.label || FALLBACK_LABEL" in js
    assert 'image.mime_type === "image/jpeg"' in js and "BASE64_ONLY.test(image.image_base64)" in js
    assert '"data:image/jpeg;base64," + image.image_base64' in js
    assert 'form.append("explain", "true")' in js and "image_base64 = \"[\"" in js  # raw view omits the image data


def test_scores_are_never_presented_as_clinical_probabilities(js, html_text):
    assert "not calibrated probabilities" in js and "not clinical certainty" in js
    assert "Model scores for all six classes" in js and "Highest-scoring class" in js
    assert "diagnos" not in js.lower().replace("not a diagnosis", "").replace("does not diagnose", "")


# ---------------------------------------------------------------- honesty about what exists


class Page(HTMLParser):
    """Collects what the accessibility and honesty tests need from the page HTML."""

    def __init__(self, text: str):
        super().__init__()
        self.ids, self.label_for, self.inputs, self.images, self.buttons = set(), set(), [], [], []
        self.nav, self.sections, self.link_hrefs = [], {}, []
        self._label_depth, self._section, self._button = 0, None, None
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if "id" in a:
            self.ids.add(a["id"])
        if tag == "label":
            self._label_depth += 1
            if "for" in a:
                self.label_for.add(a["for"])
        elif tag == "input":
            self.inputs.append((a, self._label_depth > 0))
        elif tag == "img":
            self.images.append(a)
        elif tag == "button":
            self._button = {"attrs": a, "text": ""}
            self.buttons.append(self._button)
        elif tag == "section":
            self._section = a.get("id")
            self.sections[self._section] = {"attrs": a, "h1": 0, "html": ""}
        elif tag == "h1" and self._section:
            self.sections[self._section]["h1"] += 1
        elif tag == "a":
            self.link_hrefs.append(a.get("href"))
            if "data-nav" in a:
                self.nav.append(a["data-nav"])
        if self._section:
            self.sections[self._section]["html"] += f"<{tag}"

    def handle_endtag(self, tag):
        if tag == "label":
            self._label_depth -= 1
        elif tag == "button":
            self._button = None
        elif tag == "section":
            self._section = None

    def handle_data(self, data):
        if self._button is not None:
            self._button["text"] += data
        if self._section:
            self.sections[self._section]["html"] += " " + data


@pytest.fixture(scope="module")
def page(html_text) -> Page:
    return Page(html_text)


def test_navigation_has_the_six_required_entries(page):
    assert page.nav == ["overview", "skin", "lab", "ask", "xray", "about"]
    for name in page.nav:
        assert f"#{name}" in page.link_hrefs and f"page-{name}" in page.sections


def test_chest_xray_page_is_honest_and_offers_nothing_to_run(page):
    section = page.sections["page-xray"]["html"]
    assert "In development" in section and "not available yet" in section and "makes no predictions" in section
    for control in ("<input", "<button", "<form", "<textarea", "<select", "dropzone"):
        assert control not in section, control
    assert page.sections["page-xray"]["html"].count("Not started") >= 3
    assert "Chest X-ray" in render_demo_page() and "nav-tag" in render_demo_page()


def test_overview_states_the_real_status_of_every_tool(html_text, page):
    overview = page.sections["page-overview"]["html"]
    for phrase in ("Not for clinical use", "Skin Analysis", "Lab Reports", "Chest X-ray", "Medical questions", "In development", "Small prototype"):
        assert phrase in overview, phrase
    assert html_text.count("data-status-for=") == 2  # skin and lab come from the live server; chest and questions are fixed text


def test_about_page_states_the_limits_the_project_requires(page):
    about = page.sections["page-about"]["html"]
    for phrase in ("Not clinically validated", "Not validated for children", "39 of the 2,298", "all of those show benign nevus", "Six classes only",
                   "PAD-UFES-20", "CC BY 4.0", "Experimental", "Grad-CAM", "8 by 8", "not a diagnosis", "Synthetic only", "not saved by LUMI"):
        assert phrase in about, phrase


def test_no_page_invents_numbers_or_approvals(page, html_text):
    text = " ".join(section["html"] for section in page.sections.values())
    for claim in ("approved by", "validated by", "FDA", "CE mark", "certified", "clinically proven", "accuracy of", "% accurate", "sensitivity", "specificity"):
        assert claim.lower() not in text.lower(), claim
    assert "Not clinically validated" in text


# ---------------------------------------------------------------- accessibility


def test_document_basics_and_landmarks(html_text, page):
    assert '<html lang="en">' in html_text
    assert 'name="viewport" content="width=device-width, initial-scale=1"' in html_text
    assert '<main id="main" tabindex="-1">' in html_text and 'class="skip-link" href="#main"' in html_text
    assert html_text.index("skip-link") < html_text.index("<nav")
    assert 'aria-label="Main"' in html_text and html_text.count("<nav") == 1


def test_each_page_has_exactly_one_heading_that_labels_it(page):
    for name, section in page.sections.items():
        assert section["h1"] == 1, name
        labelled_by = section["attrs"].get("aria-labelledby")
        assert labelled_by in page.ids, name


def test_every_form_control_has_a_label_and_every_image_has_alt_text(page, js):
    for attrs, inside_label in page.inputs:
        assert inside_label or attrs.get("id") in page.label_for or attrs.get("aria-label"), attrs
    for attrs in page.images:
        assert attrs.get("alt"), attrs
    for button in page.buttons:
        assert button["text"].strip() or button["attrs"].get("aria-label"), button
    assert js.count(".alt = ") >= 2  # images created by the script also get alt text


def test_results_are_announced_and_errors_are_alerts(html_text, js):
    assert html_text.count('aria-live="polite"') == 3
    assert html_text.count('role="alert"') >= 3 and 'role="status"' in html_text
    assert 'setAttribute("aria-busy", "true")' in js and 'removeAttribute("aria-busy")' in js


def test_keyboard_focus_is_always_visible_on_real_controls(css):
    assert re.search(r":focus-visible\s*\{[^}]*outline:\s*3px solid", css)
    allowed_without_outline = {"main:focus, h1:focus, .result-area:focus"}  # script-focused containers, not controls
    rules = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)  # ignore comments
    for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", rules):
        if re.search(r"outline:\s*(none|0)\b", body):
            assert selector.strip() in allowed_without_outline, selector.strip()


def test_motion_and_touch_targets_are_considerate(css):
    assert "@media (prefers-reduced-motion: reduce)" in css
    assert len(re.findall(r"animation:\s+(?!none)\w", css)) == 1  # only the loading spinner moves (and it stops when asked)
    assert re.search(r"\.btn \{[^}]*min-height: 4\d+px", css)


def test_layout_adapts_to_tablet_and_phone_widths(css, html_text):
    assert "@media (max-width: 1100px)" in css and "@media (max-width: 900px)" in css and "@media (max-width: 600px)" in css
    assert "overflow-x: auto" in css  # wide tables scroll inside their own box instead of widening the page
    assert "@font-face" not in css and "system" not in css.lower() or "-apple-system" in css  # system fonts only


def channel(value: int) -> float:
    v = value / 255
    return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4


def luminance(hex_color: str) -> float:
    r, g, b = (int(hex_color[i : i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast(first: str, second: str) -> float:
    high, low = sorted((luminance(first), luminance(second)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def test_the_wcag_contrast_formula_is_right():
    assert contrast("#000000", "#ffffff") == pytest.approx(21.0)
    assert contrast("#777777", "#ffffff") == pytest.approx(4.48, abs=0.02)  # the well-known borderline grey


def test_every_text_and_background_colour_pair_meets_wcag_aa(css):
    root = css[css.index(":root {") : css.index("}", css.index(":root {"))]
    colours = dict(re.findall(r"--([a-z0-9-]+):\s*(#[0-9a-fA-F]{6});", root))
    pairs = [
        ("ink", "bg"), ("ink", "surface"), ("ink-2", "surface"), ("ink-2", "bg"), ("muted", "surface"), ("muted", "bg"), ("muted", "neutral-soft"),
        ("accent", "surface"), ("accent-strong", "surface"), ("accent-strong", "accent-soft"), ("ink", "accent-soft"), ("ink-2", "accent-soft"),
        ("on-accent", "accent"), ("on-accent", "accent-hover"), ("ok", "ok-soft"), ("warn", "warn-soft"), ("err", "err-soft"),
        ("info", "info-soft"), ("neutral", "neutral-soft"), ("neutral", "surface"), ("on-accent", "ink"),
    ]
    failures = []
    for text_colour, background in pairs:
        ratio = contrast(colours[text_colour], colours[background] if background != "on-accent" else colours[background])
        if ratio < 4.5:
            failures.append((text_colour, background, round(ratio, 2)))
    assert not failures, failures
    # colours used directly in rules (not variables) are also checked: white text on the navy notice bar and skip link
    assert contrast("#ffffff", colours["ink"]) >= 4.5


# ---------------------------------------------------------------- /health feeds the Overview and About pages


@pytest.fixture(scope="module")
def tiny_checkpoint(tmp_path_factory):
    torch.manual_seed(0)
    path = tmp_path_factory.mktemp("ui_ckpt") / "tiny.pt"
    info = {"run_id": "ui-test-run", "created_utc": "2026-01-01T00:00:00+00:00", "dataset": {"name": "SYNTHETIC-TEST", "licence": "n/a"},
            "test_macro_f1": 0.4321, "test_images": 77}
    save_checkpoint(path, build_model("mobilenetv3_small_050", len(CLASSES), pretrained=False), "mobilenetv3_small_050", CLASSES, 64, info)
    return path


def test_health_reports_pipeline_status_and_no_models_when_none_is_set_up(settings):
    body = make_client(settings).get("/health").json()
    assert body["status"] == "ok"
    assert body["pipelines"] == {"skin_image": "placeholder", "chest_xray": "placeholder", "lab_report": "ready"}
    assert body["models"] == {}


def test_health_says_unavailable_when_the_skin_model_is_not_configured(settings):
    body = TestClient(create_app(settings=settings)).get("/health").json()  # built the production way
    assert body["pipelines"]["skin_image"] == "unavailable" and body["models"] == {}


def test_health_describes_the_loaded_skin_model_for_the_about_page(settings, tiny_checkpoint):
    configured = dataclasses.replace(settings, skin_model_path=str(tiny_checkpoint))
    body = TestClient(create_app(settings=configured), headers=AUTH_HEADERS).get("/health").json()
    model = body["models"]["skin_image"]
    assert body["pipelines"]["skin_image"] == "ready"
    assert model["name"] == "mobilenetv3_small_050" and model["run_id"] == "ui-test-run" and model["classes"] == list(CLASSES)
    assert model["evaluation"]["held_out_test_macro_f1"] == 0.4321 and model["evaluation"]["held_out_test_images"] == 77
    assert "state_dict" not in str(model) and "checkpoint" not in str(model).lower()  # facts only, never weights or paths


@pytest.mark.parametrize("path", ["/health", "/demo", "/demo/assets/app.js"])
def test_health_and_page_need_no_api_key(settings, path):
    assert make_client(settings, demo_ui=True).get(path).status_code == 200


def test_demo_settings_from_environment():
    on = Settings.from_env({"LUMI_DEMO_UI": "1", "LUMI_DEMO_UI_KEY": "k" * 20})
    assert on.demo_ui is True and on.demo_ui_key == "k" * 20
    assert Settings.from_env({}).demo_ui is False and Settings.from_env({"LUMI_DEMO_UI": "yes"}).demo_ui is False
