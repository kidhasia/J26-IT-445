"""A small local demo page for LUMI (one self-contained HTML file; no external scripts, fonts or images).

Safety notes:
- Everything that comes back from the API (including text read from an uploaded report) is inserted with
  textContent, never as HTML, so uploaded content cannot inject script into the page.
- The page sends the API key only to this same server, from the browser. It is held in the page, not stored.
- A strict Content-Security-Policy is sent with the page (see DEMO_PAGE_HEADERS).
"""

import html

DEMO_PAGE_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'none'; img-src 'self' blob: data:; style-src 'unsafe-inline'; script-src 'unsafe-inline'; "
        "connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}


def render_demo_page(prefill_key: str | None = None) -> str:
    return _PAGE.replace("__PREFILL_KEY__", html.escape(prefill_key or "", quote=True))


_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>LUMI demo</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='7' fill='%230f766e'/%3E%3Ctext x='16' y='23' font-size='20' text-anchor='middle' fill='white' font-family='Arial' font-weight='bold'%3EL%3C/text%3E%3C/svg%3E">
<style>
  :root { --ink:#16202a; --muted:#5b6b7a; --line:#d9e1e8; --bg:#f3f6f9; --card:#fff; --accent:#0f766e;
          --warn-bg:#fff7e0; --warn-line:#e6c65c; --err-bg:#fdecec; --err-line:#e08a8a; --ok:#1f7a3d; }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--ink); font:16px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif; }
  header { background:var(--accent); color:#fff; padding:18px 20px; }
  header h1 { margin:0; font-size:1.5rem; letter-spacing:.04em; }
  header p { margin:2px 0 0; opacity:.92; font-size:.95rem; }
  main { max-width:900px; margin:0 auto; padding:18px 16px 60px; }
  .banner { background:var(--warn-bg); border:1px solid var(--warn-line); border-radius:10px; padding:10px 14px; margin:0 0 16px; font-size:.95rem; }
  .card { background:var(--card); border:1px solid var(--line); border-radius:12px; padding:16px; margin-bottom:16px; }
  .card h2 { margin:0 0 10px; font-size:1.1rem; }
  .chips { display:flex; flex-wrap:wrap; gap:8px; }
  .chip { border-radius:999px; padding:3px 12px; font-size:.85rem; border:1px solid var(--line); background:#eef2f5; }
  .chip.ready { background:#e4f5ea; border-color:#9fd3b0; color:var(--ok); }
  .chip.placeholder { background:#eef2f5; color:var(--muted); }
  .chip.unavailable { background:var(--err-bg); border-color:var(--err-line); color:#9b2c2c; }
  label { display:block; font-weight:600; margin:12px 0 4px; }
  select, input[type=text], input[type=password], input[type=file], textarea { width:100%; padding:9px 10px; border:1px solid var(--line); border-radius:8px; font:inherit; background:#fff; }
  textarea { min-height:60px; resize:vertical; }
  .row { display:grid; grid-template-columns:1fr 1fr; gap:14px; }
  @media (max-width:640px) { .row { grid-template-columns:1fr; } }
  .hint { color:var(--muted); font-size:.85rem; margin-top:3px; }
  button { background:var(--accent); color:#fff; border:0; border-radius:10px; padding:11px 22px; font:inherit; font-weight:600; cursor:pointer; margin-top:16px; }
  button:disabled { opacity:.55; cursor:progress; }
  #preview { max-width:100%; max-height:260px; border-radius:8px; border:1px solid var(--line); margin-top:10px; display:none; }
  .big { font-size:1.6rem; font-weight:700; margin:2px 0; }
  .sub { color:var(--muted); font-size:.9rem; }
  .bars { margin:12px 0; }
  .bar-row { display:grid; grid-template-columns:230px 1fr 56px; gap:8px; align-items:center; margin:4px 0; font-size:.92rem; }
  @media (max-width:640px) { .bar-row { grid-template-columns:120px 1fr 48px; } }
  .bar { background:#e8edf1; border-radius:6px; height:14px; overflow:hidden; }
  .bar > span { display:block; height:100%; background:var(--accent); }
  .bar-row.top .bar > span { background:#0b4f4a; }
  table { border-collapse:collapse; width:100%; font-size:.92rem; }
  th, td { border-bottom:1px solid var(--line); padding:6px 8px; text-align:left; vertical-align:top; }
  th { background:#f0f4f7; }
  .flag { color:#9b5b00; font-weight:600; }
  pre { background:#f0f4f7; padding:10px; border-radius:8px; overflow:auto; font-size:.85rem; white-space:pre-wrap; }
  .notice { background:#eaf4f3; border:1px solid #a8d3cf; border-radius:10px; padding:10px 14px; font-size:.92rem; }
  .warnbox { background:var(--warn-bg); border:1px solid var(--warn-line); border-radius:10px; padding:8px 14px; }
  .errbox { background:var(--err-bg); border:1px solid var(--err-line); border-radius:10px; padding:10px 14px; }
  ul { margin:6px 0 6px 18px; padding:0; }
  .xai { border-top:1px solid var(--line); margin-top:14px; padding-top:12px; }
  .xai h3 { margin:0 0 6px; font-size:1rem; }
  .xai-label { background:#eef0ff; border:1px solid #b9bff0; border-radius:8px; padding:6px 12px; font-weight:600; font-size:.92rem; margin-bottom:10px; }
  .xai-pair { display:grid; grid-template-columns:1fr 1fr; gap:12px; }
  @media (max-width:640px) { .xai-pair { grid-template-columns:1fr; } }
  .xai-pair figure { margin:0; }
  .xai-pair img { width:100%; border-radius:8px; border:1px solid var(--line); display:block; }
  .xai-pair figcaption { color:var(--muted); font-size:.85rem; margin-top:3px; }
  .legend { height:12px; border-radius:6px; margin:10px 0 2px; background:linear-gradient(90deg,#1d2cff,#19e0e0,#7bff4f,#ffe53a,#ff2a1a); }
  .legend-text { display:flex; justify-content:space-between; color:var(--muted); font-size:.8rem; }
  details { margin-top:12px; }
  .inline { display:flex; align-items:center; gap:6px; font-weight:400; margin:6px 0 0; }
  .inline input { width:auto; }
</style>
</head>
<body>
<header>
  <h1>LUMI</h1>
  <p>Multimodal AI/ML backend for pediatric healthcare decision support: local demo</p>
</header>
<main>
  <div class="banner"><strong>Research prototype.</strong> Decision support only. It does not diagnose and does not replace a licensed
  healthcare professional. The skin model was trained on a mostly adult public dataset, has not been clinically validated, and has not
  been shown to be reliable for children. Use only practice files: photos from the public PAD-UFES-20 dataset and the synthetic lab
  reports made by this project. Never upload a real patient's photo or report.</div>

  <div class="card">
    <h2>What is working on this server</h2>
    <div class="chips" id="chips"><span class="chip">checking...</span></div>
    <div class="hint">Green = real analysis. Grey = placeholder that makes no prediction. Red = needs set-up.</div>
  </div>

  <form class="card" id="form" autocomplete="off">
    <h2>Try it</h2>
    <div class="row">
      <div>
        <label for="type">1. What are you uploading?</label>
        <select id="type">
          <option value="skin_image">Skin photo (trained model)</option>
          <option value="lab_report">Lab report image (reads text)</option>
          <option value="chest_xray">Chest X-ray (not built yet)</option>
        </select>
      </div>
      <div>
        <label for="file">2. Choose a file</label>
        <input id="file" type="file" accept="image/png,image/jpeg">
        <div class="hint" id="filehint">PNG or JPEG, up to 10 MB.</div>
      </div>
    </div>
    <img id="preview" alt="Preview of the chosen file">
    <label for="question">3. Question (optional; questions are not answered yet)</label>
    <textarea id="question" maxlength="1000" placeholder="For example: What does this show?"></textarea>
    <label class="inline" id="explainrow"><input type="checkbox" id="explain" checked> Also show the AI attention map (Grad-CAM) for skin photos</label>
    <label for="key">API key</label>
    <input id="key" type="password" value="__PREFILL_KEY__" placeholder="Paste your API key">
    <label class="inline"><input type="checkbox" id="showkey"> show key</label>
    <button type="submit" id="go">Analyze</button>
  </form>

  <div id="result" aria-live="polite"></div>
</main>

<script>
(function () {
  "use strict";
  var MAX_BYTES = 10 * 1024 * 1024;
  var wantedExplain = false;  // whether the last request asked for an attention map
  var NAMES = { skin_image: "Skin photo", lab_report: "Lab report reading", chest_xray: "Chest X-ray" };
  var STATE_TEXT = { ready: "working", placeholder: "not built yet", unavailable: "model not set up" };
  function $(id) { return document.getElementById(id); }
  // Build elements with textContent only, so nothing from the server can become HTML.
  function h(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }
  function add(parent) { for (var i = 1; i < arguments.length; i++) parent.appendChild(arguments[i]); return parent; }
  function card(title) { var c = h("div", "card"); if (title) c.appendChild(h("h2", null, title)); return c; }
  function pct(p) { return (p * 100).toFixed(1) + "%"; }

  function loadHealth() {
    fetch("/health").then(function (r) { return r.json(); }).then(function (data) {
      var chips = $("chips"); chips.textContent = "";
      var pipes = data.pipelines || {};
      Object.keys(NAMES).forEach(function (k) {
        var state = pipes[k] || "unavailable";
        chips.appendChild(h("span", "chip " + state, NAMES[k] + ": " + (STATE_TEXT[state] || state)));
      });
    }).catch(function () {
      var chips = $("chips"); chips.textContent = "";
      chips.appendChild(h("span", "chip unavailable", "Cannot reach the server"));
    });
  }

  function onTypeChange() {
    var type = $("type").value;
    $("file").accept = type === "lab_report" ? "image/png,image/jpeg,application/pdf" : "image/png,image/jpeg";
    $("explainrow").style.display = type === "skin_image" ? "flex" : "none";
    $("filehint").textContent = type === "lab_report"
      ? "PNG or JPEG image (a PDF is accepted but not analysed yet), up to 10 MB."
      : "PNG or JPEG, up to 10 MB.";
  }

  function onFileChange() {
    var preview = $("preview"), file = $("file").files[0];
    if (preview.dataset.url) { URL.revokeObjectURL(preview.dataset.url); preview.dataset.url = ""; }
    if (file && file.type.indexOf("image/") === 0) {
      var url = URL.createObjectURL(file);
      preview.dataset.url = url; preview.src = url; preview.style.display = "block";
    } else { preview.removeAttribute("src"); preview.style.display = "none"; }
  }

  var HINTS = {
    unauthorized: "The API key is missing or wrong. Paste the key printed in the terminal.",
    file_too_large: "The file is too big. Use a photo under 10 MB.",
    unsupported_media_type: "That file type is not accepted for this choice. Use a PNG or JPEG image.",
    unreadable_file: "The file could not be opened. It may be damaged.",
    empty_file: "The file is empty.",
    model_unavailable: "The skin model is not set up on this server, so no analysis was done (and nothing was made up).",
    ocr_unavailable: "The text-reading program (Tesseract) is not available on this computer.",
    rate_limited: "Too many requests in a minute. Wait a moment and try again."
  };

  function showError(title, detail, hint) {
    var out = $("result"); out.textContent = "";
    var c = card(null), box = h("div", "errbox");
    add(box, h("strong", null, title));
    if (detail) add(box, h("div", null, detail));
    if (hint) add(box, h("div", "sub", hint));
    out.appendChild(add(c, box));
  }

  function renderSkin(result, body) {
    var c = card("Skin photo: model result");
    add(c, h("div", "sub", "Best match among the 6 classes the model knows"));
    add(c, h("div", "big", result.predicted_class_name + " (" + result.predicted_class + ")"));
    add(c, h("div", "sub", "Model score " + pct(body.confidence) + ". This is the model's own relative score, NOT clinical certainty, and it can be wrong."));
    var bars = h("div", "bars");
    result.probabilities.forEach(function (p, i) {
      var row = h("div", "bar-row" + (i === 0 ? " top" : ""));
      var track = h("div", "bar"), fill = h("span");
      fill.style.width = Math.max(0, Math.min(100, p.probability * 100)) + "%";
      add(row, h("div", null, p.name), add(track, fill), h("div", null, pct(p.probability)));
      bars.appendChild(row);
    });
    add(c, bars);
    add(c, renderAttention(result.explanation_image));
    var m = result.model || {}, ev = m.evaluation || {};
    add(c, h("div", "sub", "Model: " + m.name + ", run " + m.run_id + ". Measured on a small held-out test set: macro-F1 " +
      ev.held_out_test_macro_f1 + " over " + ev.held_out_test_images + " images. That is not a clinical validation."));
    var lim = h("details"); lim.open = true;
    add(lim, h("summary", null, "Limitations (please read)"));
    var ul = h("ul"); (result.limitations || []).forEach(function (t) { ul.appendChild(h("li", null, t)); });
    add(lim, ul); add(c, lim);
    return c;
  }

  var BASE64_ONLY = new RegExp("^[A-Za-z0-9+/=]+$");
  var FALLBACK_LABEL = "AI attention visualisation \u2014 not a diagnosis or proof of correctness.";

  function renderAttention(img) {
    var box = h("div", "xai");
    if (!img) {
      if (wantedExplain) add(box, h("div", "sub", "No attention map was produced for this photo (see the warnings below). The prediction above is unaffected."));
      return box.childNodes.length ? box : document.createDocumentFragment();
    }
    // Server data is untrusted: only accept a JPEG made of base64 characters, and set it only as an image source.
    if (img.mime_type !== "image/jpeg" || typeof img.image_base64 !== "string" || !BASE64_ONLY.test(img.image_base64)) {
      add(box, h("div", "sub", "The attention map could not be displayed."));
      return box;
    }
    add(box, h("h3", null, "Where the model looked"));
    add(box, h("div", "xai-label", img.label || FALLBACK_LABEL));
    var pair = h("div", "xai-pair");
    var left = h("figure"), right = h("figure");
    var original = h("img"), overlay = h("img");
    original.alt = "The photo you uploaded";
    overlay.alt = "The same photo with the attention map drawn on it";
    original.src = $("preview").dataset.url || "";
    overlay.src = "data:image/jpeg;base64," + img.image_base64;
    add(left, original, h("figcaption", null, "Your photo"));
    add(right, overlay, h("figcaption", null, "Attention map for " + img.target_class_name + " (" + img.target_class + ")"));
    add(pair, left, right); add(box, pair);
    add(box, h("div", "legend"));
    var scale = h("div", "legend-text"); add(scale, h("span", null, "little influence"), h("span", null, "most influence"));
    add(box, scale);
    add(box, h("div", "sub", img.how_to_read + " Map detail: " + img.map_cells[0] + " by " + img.map_cells[1] + " cells."));
    var lim = h("details"); add(lim, h("summary", null, "What this map can and cannot tell you"));
    var ul = h("ul"); (img.limitations || []).forEach(function (x) { ul.appendChild(h("li", null, x)); });
    add(lim, ul); add(box, lim);
    return box;
  }

  function renderOcr(result) {
    var c = card("Lab report: text read from the image");
    add(c, h("div", "sub", "Engine: " + result.engine.name + " " + result.engine.version + ". Average text confidence " + result.mean_ocr_confidence + " out of 100."));
    if (result.fields.length) {
      var table = h("table"), head = h("tr");
      ["Test", "Result", "Unit", "Reference range (as printed)", "Check"].forEach(function (t) { head.appendChild(h("th", null, t)); });
      table.appendChild(head);
      result.fields.forEach(function (f) {
        var tr = h("tr");
        add(tr, h("td", null, f.test_name), h("td", null, f.value === null ? "(not found)" : f.value),
            h("td", null, f.unit === null ? "(not found)" : f.unit),
            h("td", null, f.reference_range === null ? "(not found)" : f.reference_range),
            h("td", f.needs_review ? "flag" : "", f.needs_review ? "Check against the original" : "ok"));
        table.appendChild(tr);
      });
      add(c, table);
    } else { add(c, h("div", "sub", "No result rows were recognised.")); }
    add(c, h("div", "sub", result.reference_range_note));
    var det = h("details"); add(det, h("summary", null, "Full extracted text"), h("pre", null, result.extracted_text || "(no text found)"));
    return add(c, det);
  }

  function render(body, status) {
    var out = $("result"); out.textContent = "";
    if (body.error) {
      var code = body.error.code;
      showError("Request not completed (" + status + " " + code + ")", body.error.message, HINTS[code]);
      return;
    }
    var result = body.result || {};
    var main;
    if (result.pipeline === "skin_lesion_classifier") main = renderSkin(result, body);
    else if (result.pipeline === "lab_report_ocr") main = renderOcr(result);
    else {
      main = card("Not built yet");
      add(main, h("div", null, "This input type has no real analysis yet. No prediction was made."));
    }
    out.appendChild(main);
    if (body.explanation) { var e = card("About this result"); add(e, h("div", null, body.explanation)); out.appendChild(e); }
    if (body.warnings && body.warnings.length) {
      var w = card("Warnings"), box = h("div", "warnbox"), ul = h("ul");
      body.warnings.forEach(function (t) { ul.appendChild(h("li", null, t)); });
      out.appendChild(add(w, add(box, ul)));
    }
    var n = card(null); add(n, add(h("div", "notice"), h("strong", null, "Clinical boundary: "), document.createTextNode(body.clinical_boundary_notice)));
    out.appendChild(n);
    var raw = card(null), det = h("details");
    add(det, h("summary", null, "Technical details (raw response)"), h("pre", null, JSON.stringify(body, null, 2)));
    out.appendChild(add(raw, det));
  }

  function submit(event) {
    event.preventDefault();
    var file = $("file").files[0], key = $("key").value.trim(), type = $("type").value;
    if (!file) return showError("Choose a file first.", null, null);
    if (!key) return showError("Enter the API key first.", null, HINTS.unauthorized);
    if (file.size > MAX_BYTES) return showError("That file is larger than 10 MB.", null, HINTS.file_too_large);
    var form = new FormData();
    form.append("input_type", type); form.append("file", file);
    var q = $("question").value.trim(); if (q) form.append("question", q);
    wantedExplain = type === "skin_image" && $("explain").checked;
    if (wantedExplain) form.append("explain", "true");
    var button = $("go"); button.disabled = true; button.textContent = "Analyzing...";
    fetch("/api/v1/analyze", { method: "POST", headers: { "Authorization": "Bearer " + key }, body: form })
      .then(function (r) { return r.json().then(function (body) { return { status: r.status, body: body }; }); })
      .then(function (res) { render(res.body, res.status); })
      .catch(function () { showError("Cannot reach the LUMI server.", "Is it still running?", "In the terminal, run ./scripts/run_dev.sh and wait for 'Application startup complete'."); })
      .then(function () { button.disabled = false; button.textContent = "Analyze"; loadHealth(); });
  }

  $("type").addEventListener("change", onTypeChange);
  $("file").addEventListener("change", onFileChange);
  $("form").addEventListener("submit", submit);
  $("showkey").addEventListener("change", function () { $("key").type = this.checked ? "text" : "password"; });
  onTypeChange(); loadHealth();
})();
</script>
</body>
</html>
"""
