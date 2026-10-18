"""The local demo page and the pipeline status shown on /health."""

import dataclasses
import re

import pytest
from fastapi.testclient import TestClient

from lumi.config import Settings
from lumi.demo_ui import DEMO_PAGE_HEADERS, render_demo_page
from lumi.main import create_app
from tests.conftest import build_test_service


def make_client(settings: Settings, **overrides) -> TestClient:
    return TestClient(create_app(settings=dataclasses.replace(settings, **overrides), service=build_test_service()))


# ---------------------------------------------------------------- on / off


def test_demo_page_is_off_by_default(settings):
    client = make_client(settings)
    assert client.get("/demo").status_code == 404
    assert client.get("/", follow_redirects=False).status_code == 404


def test_demo_page_is_served_when_enabled(settings):
    client = make_client(settings, demo_ui=True)
    response = client.get("/demo")
    assert response.status_code == 200 and response.headers["content-type"].startswith("text/html")
    assert "LUMI" in response.text and "Research prototype" in response.text
    root = client.get("/", follow_redirects=False)
    assert root.status_code in (301, 302, 307, 308) and root.headers["location"] == "/demo"


def test_demo_page_is_not_listed_in_the_api_schema(settings):
    paths = make_client(settings, demo_ui=True).get("/openapi.json").json()["paths"]
    assert "/demo" not in paths and "/" not in paths


# ---------------------------------------------------------------- security properties of the page


def test_page_is_sent_with_a_strict_content_security_policy(settings):
    response = make_client(settings, demo_ui=True).get("/demo")
    for name, value in DEMO_PAGE_HEADERS.items():
        assert response.headers[name] == value
    policy = response.headers["content-security-policy"]
    assert "default-src 'none'" in policy and "connect-src 'self'" in policy and "frame-ancestors 'none'" in policy
    assert "http" not in policy  # no external hosts are allowed


def test_page_loads_nothing_from_other_websites():
    page = render_demo_page()
    assert not re.search(r"""(src|href|action)\s*=\s*["']?(https?:)?//""", page)
    # The only allowed "http://" text is the SVG format's XML namespace name inside the built-in tab icon.
    # It is an identifier, not an address anything is loaded from.
    remaining = page.replace("http://www.w3.org/2000/svg", "")
    assert "https://" not in remaining and "http://" not in remaining
    assert page.count("http://www.w3.org/2000/svg") == 1


def test_page_never_inserts_server_text_as_html():
    page = render_demo_page()
    for dangerous in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function"):
        assert dangerous not in page


def test_no_key_appears_in_the_page_unless_one_is_configured(settings):
    assert 'value=""' in make_client(settings, demo_ui=True).get("/demo").text


def test_configured_demo_key_is_prefilled_and_html_escaped():
    page = render_demo_page('abc"><script>alert(1)</script>')
    assert '<script>alert(1)</script>' not in page
    assert 'value="abc&quot;&gt;&lt;script&gt;alert(1)&lt;/script&gt;"' in page


def test_demo_page_does_not_bypass_api_authentication(settings):
    client = make_client(settings, demo_ui=True)
    response = client.post("/api/v1/analyze", data={"input_type": "skin_image"})
    assert response.status_code == 401


# ---------------------------------------------------------------- settings from the environment


def test_demo_settings_from_environment():
    on = Settings.from_env({"LUMI_DEMO_UI": "1", "LUMI_DEMO_UI_KEY": "k" * 20})
    assert on.demo_ui is True and on.demo_ui_key == "k" * 20
    assert Settings.from_env({}).demo_ui is False
    assert Settings.from_env({"LUMI_DEMO_UI": "yes"}).demo_ui is False  # only the exact value "1" turns it on


# ---------------------------------------------------------------- /health shows what is real


def test_health_reports_pipeline_status_for_each_input_type(settings):
    body = make_client(settings).get("/health").json()
    assert body["status"] == "ok"
    assert body["pipelines"] == {"skin_image": "placeholder", "chest_xray": "placeholder", "lab_report": "ready"}


def test_health_says_unavailable_when_no_skin_model_is_configured(settings):
    client = TestClient(create_app(settings=settings))  # built the production way: from settings only
    assert client.get("/health").json()["pipelines"]["skin_image"] == "unavailable"


@pytest.mark.parametrize("path", ["/health", "/demo"])
def test_health_and_page_need_no_api_key(settings, path):
    assert make_client(settings, demo_ui=True).get(path).status_code == 200
