"""The local demo web interface for LUMI: plain HTML, CSS and JavaScript served by FastAPI.

No framework, no external scripts, fonts or images. The page is split into asset files so the security policy can
allow only scripts and styles that come from this same server (no inline code).

Safety notes:
- Server data (including text read from an uploaded report) is inserted with textContent only, never as HTML.
- The page sends the API key only to this same server, from the browser. It is never stored.
- A strict Content-Security-Policy is sent with the page (see DEMO_PAGE_HEADERS).
- Only the three files in ASSETS can be requested; there is no path lookup, so nothing else can be reached.
"""

import html
from pathlib import Path

ASSET_DIR = Path(__file__).parent / "assets"

ASSETS: dict[str, str] = {
    "app.css": "text/css; charset=utf-8",
    "app.js": "text/javascript; charset=utf-8",
    "favicon.svg": "image/svg+xml",
}

DEMO_PAGE_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'none'; img-src 'self' blob: data:; style-src 'self'; script-src 'self'; "
        "connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}
ASSET_HEADERS = {"X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"}


def render_demo_page(prefill_key: str | None = None) -> str:
    """The page HTML. `prefill_key` (a throw-away local development key, if any) is escaped before use."""
    template = (ASSET_DIR / "index.html").read_text(encoding="utf-8")
    return template.replace("__PREFILL_KEY__", html.escape(prefill_key or "", quote=True))


def read_asset(name: str) -> tuple[bytes, str] | None:
    """(content, media type) for an allowed asset name, else None."""
    media_type = ASSETS.get(name)
    if media_type is None:
        return None
    return (ASSET_DIR / name).read_bytes(), media_type
