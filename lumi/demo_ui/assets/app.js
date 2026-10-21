/* LUMI demo interface. Plain JavaScript: no framework, no external scripts.
   Safety rules used throughout:
   - Everything that comes from the server (including text read from an uploaded report) is inserted with
     textContent, never as HTML, so it can never become page code.
   - The attention-map image is displayed only if it is a JPEG made of base64 characters, and only as an image source.
   - The API key is held in the page (the key box) and sent only to this same server. It is never written to storage. */
(function () {
  "use strict";

  var SVG_NS = "http://www.w3.org/2000/svg";
  var MAX_BYTES = 10 * 1024 * 1024;
  var ALLOWED_TYPES = ["image/png", "image/jpeg"];
  var PAGES = ["overview", "skin", "lab", "ask", "xray", "about"];
  var TITLES = { overview: "Overview", skin: "Skin Analysis", lab: "Lab Reports", ask: "Ask a question", xray: "Chest X-ray", about: "About LUMI" };
  var FALLBACK_LABEL = "AI attention visualisation — not a diagnosis or proof of correctness.";
  var BASE64_ONLY = new RegExp("^[A-Za-z0-9+/=]+$");
  var REQUEST_TIMEOUT_MS = 120000;
  // Already shown in plain words next to the scores, so it is not repeated in the warnings box.
  var HIDDEN_WARNINGS = ["MODEL_SCORE_NOT_CLINICAL_CERTAINTY"];

  var state = { health: null, busy: { skin: false, lab: false, ask: false }, results: { skin: null, lab: null } };
  var uploaders = {};

  /* ------------------------------------------------------------------ small DOM helpers */

  function $(id) { return document.getElementById(id); }

  function h(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function add(parent) {
    for (var i = 1; i < arguments.length; i++) {
      var child = arguments[i];
      if (child === null || child === undefined || child === false) continue;
      parent.appendChild(typeof child === "string" ? document.createTextNode(child) : child);
    }
    return parent;
  }

  function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); }

  function icon(name, extraClass) {
    var svg = document.createElementNS(SVG_NS, "svg");
    svg.setAttribute("class", "icon" + (extraClass ? " " + extraClass : ""));
    svg.setAttribute("aria-hidden", "true");
    var use = document.createElementNS(SVG_NS, "use");
    use.setAttribute("href", "#i-" + name);
    svg.appendChild(use);
    return svg;
  }

  function badge(kind, text) { return h("span", "badge " + kind, text); }
  function para(className) {
    var p = h("p", className);
    for (var i = 1; i < arguments.length; i++) add(p, arguments[i]);
    return p;
  }
  function strong(text) { return h("strong", null, text); }

  function callout(kind, iconName, content) {
    var box = h("div", "callout " + kind);
    add(box, icon(iconName), content);
    return box;
  }

  function card(title) {
    var c = h("div", "card");
    if (title) c.appendChild(h("h2", null, title));
    return c;
  }

  function pct(value) { return (value * 100).toFixed(1) + "%"; }
  function clamp01(value) { return Math.max(0, Math.min(1, value)); }
  function formatBytes(bytes) {
    if (bytes < 1024) return bytes + " bytes";
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(0) + " KB";
    return (bytes / (1024 * 1024)).toFixed(1) + " MB";
  }
  function readable(text) { return String(text).replace(/_/g, " "); }

  /* ------------------------------------------------------------------ routing */

  function currentPage() {
    var name = (location.hash || "").replace(/^#/, "");
    return PAGES.indexOf(name) >= 0 ? name : "overview";
  }

  function showPage(moveFocus) {
    var name = currentPage();
    PAGES.forEach(function (page) { $("page-" + page).hidden = page !== name; });
    document.querySelectorAll("[data-nav]").forEach(function (link) {
      if (link.getAttribute("data-nav") === name) link.setAttribute("aria-current", "page");
      else link.removeAttribute("aria-current");
    });
    document.title = TITLES[name] + " · LUMI";
    if (name === "about") renderAboutModel();
    if (moveFocus) {
      var heading = document.querySelector("#page-" + name + " h1");
      if (heading) heading.focus({ preventScroll: true });
      window.scrollTo(0, 0);
    }
  }

  /* ------------------------------------------------------------------ server health */

  var STATUS_TEXT = {
    skin_image: { ready: ["ok", "Working · research prototype"], unavailable: ["err", "Model not set up"], placeholder: ["neutral", "Placeholder only"] },
    lab_report: { ready: ["ok", "Working · synthetic reports"], unavailable: ["err", "Not available"], placeholder: ["neutral", "Placeholder only"] }
  };

  function setBadge(node, pair) {
    node.className = "badge " + pair[0];
    node.textContent = pair[1];
  }

  function renderHealth() {
    var health = state.health;
    var pill = $("server-pill");
    if (health) setBadge(pill, ["ok", "Server connected · v" + health.version]);
    else setBadge(pill, ["err", "Server not reachable"]);
    document.querySelectorAll("[data-status-for]").forEach(function (node) {
      var key = node.getAttribute("data-status-for");
      var value = health && health.pipelines ? health.pipelines[key] : null;
      var table = STATUS_TEXT[key] || {};
      setBadge(node, value && table[value] ? table[value] : ["neutral", health ? "Unknown" : "Server not reachable"]);
    });
    if (currentPage() === "about") renderAboutModel();
  }

  function loadHealth() {
    return fetch("/health", { headers: { "Accept": "application/json" } })
      .then(function (response) { if (!response.ok) throw new Error("health"); return response.json(); })
      .then(function (data) { state.health = data; })
      .catch(function () { state.health = null; })
      .then(renderHealth);
  }

  function renderAboutModel() {
    var list = $("about-model");
    clear(list);
    function row(label, value) { var item = h("div"); add(item, h("dt", null, label), h("dd", null, value)); list.appendChild(item); }
    var info = state.health && state.health.models ? state.health.models.skin_image : null;
    if (!info) {
      row("Model", state.health ? "Not set up on this server, so no skin model information is available." : "Server not reachable.");
      return;
    }
    var evaluation = info.evaluation || {};
    var trained = info.trained_on || {};
    row("Model", String(info.name) + (info.image_size ? " (" + info.image_size + " px images)" : ""));
    row("Training run", String(info.run_id));
    if (trained.name) row("Trained on", trained.name + (trained.licence ? " · " + trained.licence : ""));
    if (info.classes) row("Classes", info.classes.join(", "));
    if (typeof evaluation.held_out_test_macro_f1 === "number") {
      row("Held-out test score", "Macro-F1 " + evaluation.held_out_test_macro_f1.toFixed(2) + " on " + evaluation.held_out_test_images + " photos (1.00 would be perfect)");
    }
  }

  /* ------------------------------------------------------------------ API key box */

  function getKey() { return $("key-input").value.trim(); }

  function updateKeyState() {
    var set = getKey().length > 0;
    var node = $("key-state");
    node.className = "badge " + (set ? "ok" : "neutral");
    node.textContent = set ? "set" : "needed";
  }

  function setKeyPanel(open, message) {
    $("key-panel").hidden = !open;
    $("key-toggle").setAttribute("aria-expanded", open ? "true" : "false");
    var note = $("key-message");
    if (open && message) { note.textContent = message; note.hidden = false; } else { note.hidden = true; }
    if (open) $("key-input").focus();
  }

  /* ------------------------------------------------------------------ file chooser (drop zone) */

  function createUploader(prefix) {
    var drop = $(prefix + "-drop"), input = $(prefix + "-file"), filecard = $(prefix + "-filecard");
    var preview = $(prefix + "-preview"), nameNode = $(prefix + "-filename"), subNode = $(prefix + "-filesub");
    var errorNode = $(prefix + "-error");
    var up = { file: null, url: null };
    var depth = 0;

    function setError(message) {
      if (message) { errorNode.textContent = message; errorNode.hidden = false; } else { errorNode.hidden = true; }
    }

    function release() { if (up.url) { URL.revokeObjectURL(up.url); up.url = null; } }

    function clearFile() {
      release();
      up.file = null;
      input.value = "";
      filecard.hidden = true;
      preview.removeAttribute("src");
      setError(null);
    }

    function problem(file) {
      if (ALLOWED_TYPES.indexOf(file.type) < 0) return "That file type is not supported. Choose a PNG or JPEG image.";
      if (file.size === 0) return "That file is empty. Choose a different file.";
      if (file.size > MAX_BYTES) return "That file is " + formatBytes(file.size) + ", which is over the 10 MB limit. Choose a smaller file.";
      return null;
    }

    function setFile(file) {
      var message = problem(file);
      if (message) { setError(message); return; }
      setError(null);
      release();
      up.file = file;
      up.url = URL.createObjectURL(file);
      preview.onload = function () {
        subNode.textContent = preview.naturalWidth + " × " + preview.naturalHeight + " px · " + formatBytes(file.size);
      };
      preview.src = up.url;
      nameNode.textContent = file.name;
      subNode.textContent = formatBytes(file.size);
      filecard.hidden = false;
    }

    input.addEventListener("change", function () { if (input.files && input.files[0]) setFile(input.files[0]); });
    drop.addEventListener("dragenter", function (e) { e.preventDefault(); depth += 1; drop.classList.add("is-over"); });
    drop.addEventListener("dragover", function (e) { e.preventDefault(); });
    drop.addEventListener("dragleave", function () { depth = Math.max(0, depth - 1); if (depth === 0) drop.classList.remove("is-over"); });
    drop.addEventListener("drop", function (e) {
      e.preventDefault(); depth = 0; drop.classList.remove("is-over");
      var files = e.dataTransfer && e.dataTransfer.files;
      if (files && files[0]) setFile(files[0]);
    });
    $(prefix + "-clear").addEventListener("click", function () { clearFile(); input.focus(); });

    up.setError = setError;
    up.focus = function () { input.focus(); };
    return up;
  }

  /* ------------------------------------------------------------------ requests */

  function request(form, key) {
    var controller = new AbortController();
    var timer = setTimeout(function () { controller.abort(); }, REQUEST_TIMEOUT_MS);
    return fetch("/api/v1/analyze", { method: "POST", headers: { "Authorization": "Bearer " + key }, body: form, signal: controller.signal })
      .then(function (response) {
        clearTimeout(timer);
        return response.text().then(function (text) {
          var body = null;
          try { body = JSON.parse(text); } catch (e) { body = null; }
          return { status: response.status, body: body, retryAfter: response.headers.get("Retry-After") };
        });
      })
      .catch(function (error) { clearTimeout(timer); throw error; });
  }

  function setBusy(kind, busy, button, idleText) {
    state.busy[kind] = busy;
    button.disabled = busy;
    clear(button);
    if (busy) add(button, h("span", "spinner"), h("span", null, "Working…"));
    else button.textContent = idleText;
    button.querySelectorAll(".spinner").forEach(function (s) { s.setAttribute("aria-hidden", "true"); });
  }

  function showLoading(container, message) {
    var box = h("div", "card loading");
    var row = h("div", "loading-row");
    var spinner = h("span", "spinner");
    spinner.setAttribute("aria-hidden", "true");
    add(row, spinner, h("span", null, message));
    add(box, row, h("div", "skeleton w1"), h("div", "skeleton w2"), h("div", "skeleton w3"));
    clear(container);
    container.appendChild(box);
    container.setAttribute("aria-busy", "true");
  }

  function finish(container) {
    container.removeAttribute("aria-busy");
    container.focus({ preventScroll: true });
    container.scrollIntoView({ block: "nearest" });
  }

  /* ------------------------------------------------------------------ error display */

  var ERRORS = {
    unauthorized: ["The API key was not accepted", "Check the key in the “API key” box at the top right. In local development the key is printed in the terminal."],
    rate_limited: ["Too many requests", "Please wait a moment and try again."],
    file_too_large: ["That file is too large", "Use a file under 10 MB."],
    unsupported_media_type: ["That file type is not accepted", "Use a PNG or JPEG image."],
    unreadable_file: ["The file could not be opened", "It may be damaged. Try a different file."],
    empty_file: ["The file is empty", "Choose a different file."],
    missing_field: ["Part of the request was missing", "Choose a file and try again."],
    invalid_field: ["Part of the request was not valid", "Check your choices and try again."],
    invalid_input_type: ["That kind of file is not supported here", "Use the Skin Analysis or Lab Reports page."],
    invalid_metadata: ["Part of the request was not valid", "Try again."],
    invalid_evidence: ["The supplied result cannot be used", "Send the JSON returned by a completed skin or lab-report analysis."],
    model_unavailable: ["The skin model is not set up on this server", "No analysis was done and nothing was made up. Start LUMI with scripts/start_demo.command, or see docs/DEMO_GUIDE.md."],
    ocr_unavailable: ["Text reading is not available", "The text-reading program (Tesseract) is missing on this computer."],
    internal_error: ["Something went wrong on the server", "Try again. If it keeps happening, look at the terminal window that is running LUMI."]
  };

  function errorBox(title, hint, detail, needsKey) {
    var c = h("div", "card");
    var box = h("div", "callout err");
    var inner = h("div");
    var heading = h("div", "error-title");
    add(heading, icon("alert"), h("span", null, title));
    add(inner, heading, hint ? para(null, hint) : null, detail ? para("fine", detail) : null);
    if (needsKey) {
      var actions = h("div", "error-actions");
      var open = h("button", "btn secondary", "Enter API key");
      open.type = "button";
      open.addEventListener("click", function () { setKeyPanel(true); });
      add(actions, open);
      add(inner, actions);
    }
    add(box, inner);
    c.appendChild(box);
    return c;
  }

  function renderRequestError(container, res) {
    var error = res.body && res.body.error ? res.body.error : null;
    var code = error && typeof error.code === "string" ? error.code : null;
    var entry = code ? ERRORS[code] : null;
    if (!entry) {
      if (res.status === 401) entry = ERRORS.unauthorized;
      else if (res.status === 429) entry = ERRORS.rate_limited;
      else if (res.status >= 500) entry = ERRORS.internal_error;
      else entry = ["The request could not be completed", "Try again with a different file."];
    }
    var hint = entry[1];
    if (res.status === 429 && res.retryAfter && /^[0-9]+$/.test(res.retryAfter)) hint = "Try again in about " + res.retryAfter + " seconds.";
    var detail = "Error " + res.status + (code ? " · " + code : "");
    if (error && typeof error.message === "string" && error.message) detail += " · " + error.message;
    clear(container);
    container.appendChild(errorBox(entry[0], hint, detail, res.status === 401));
    if (res.status === 401) setKeyPanel(true, "Enter a valid API key to continue.");
  }

  function renderNetworkError(container, error) {
    clear(container);
    var timedOut = error && error.name === "AbortError";
    container.appendChild(errorBox(
      timedOut ? "The request took too long" : "Could not reach the LUMI server",
      timedOut ? "Try again with a smaller file." : "Is it still running? Start it again with scripts/start_demo.command and wait for “Application startup complete”.",
      null, false));
  }

  /* ------------------------------------------------------------------ shared result pieces */

  function warningText(raw) {
    var text = String(raw);
    var cut = text.indexOf(":");
    return cut > 0 && /^[A-Z_]+$/.test(text.slice(0, cut)) ? text.slice(cut + 1).trim() : text;
  }

  function warningsCard(warnings) {
    var shown = (warnings || []).filter(function (w) { return HIDDEN_WARNINGS.indexOf(String(w).split(":")[0]) < 0; });
    if (!shown.length) return null;
    var list = h("ul");
    shown.forEach(function (w) { list.appendChild(h("li", null, warningText(w))); });
    var inner = h("div");
    add(inner, strong("Warnings"), list);
    var c = h("div", "card");
    c.appendChild(callout("warn", "alert", inner));
    return c;
  }

  function boundaryCard(notice) {
    var c = h("div", "card");
    var inner = h("div");
    add(inner, strong("Clinical boundary. "), String(notice || ""));
    c.appendChild(callout("info", "info", inner));
    return c;
  }

  function rawCard(body) {
    var copy = JSON.parse(JSON.stringify(body));
    if (copy.result && copy.result.explanation_image && typeof copy.result.explanation_image.image_base64 === "string") {
      copy.result.explanation_image.image_base64 = "[" + copy.result.explanation_image.image_base64.length + " characters of image data omitted]";
    }
    var c = h("div", "card");
    var details = h("details");
    add(details, h("summary", null, "Technical details (raw response)"), h("pre", null, JSON.stringify(copy, null, 2)));
    c.appendChild(details);
    return c;
  }

  /* ------------------------------------------------------------------ skin result */

  function attentionCard(image, wanted, previewUrl) {
    var c = card("Attention map (experimental)");
    if (!image) {
      add(c, para("fine", wanted
        ? "No attention map was produced for this photo (see the warnings below). The scores above are unaffected."
        : "The attention map was switched off for this analysis. Switch it on in the options to see which areas influenced the model."));
      return c;
    }
    var valid = image.mime_type === "image/jpeg" && typeof image.image_base64 === "string" && BASE64_ONLY.test(image.image_base64);
    if (!valid) { add(c, para("fine", "The attention map could not be displayed.")); return c; }

    var label = h("div", "xai-label");
    add(label, icon("info"), h("span", null, image.label || FALLBACK_LABEL));
    var pair = h("div", "xai-pair");
    var left = h("figure"), right = h("figure");
    var original = h("img"), overlay = h("img");
    original.alt = "The photo you uploaded";
    overlay.alt = "The same photo with the attention map drawn on it";
    if (previewUrl) original.src = previewUrl;
    overlay.src = "data:image/jpeg;base64," + image.image_base64;
    add(left, original, h("figcaption", null, "Your photo"));
    add(right, overlay, h("figcaption", null, "Attention for " + image.target_class_name + " (" + image.target_class + ")"));
    add(pair, left, right);

    var scale = h("div", "legend-text");
    add(scale, h("span", null, "little influence"), h("span", null, "most influence"));
    var cells = image.map_cells && image.map_cells.length === 2 ? " The map has " + image.map_cells[0] + " by " + image.map_cells[1] + " cells." : "";
    add(c, label, pair, h("div", "legend"), scale, para("fine", (image.how_to_read || "") + cells));

    var details = h("details");
    var list = h("ul", "plain-list");
    (image.limitations || []).forEach(function (text) { list.appendChild(h("li", null, text)); });
    add(details, h("summary", null, "What this map can and cannot tell you"), list);
    c.appendChild(details);
    return c;
  }

  function modelCard(model) {
    var info = model || {};
    var evaluation = info.evaluation || {};
    var trained = info.trained_on || {};
    var c = card("About this model");
    var list = h("dl", "kv");
    function row(label, value) { var item = h("div"); add(item, h("dt", null, label), h("dd", null, value)); list.appendChild(item); }
    row("Model", String(info.name) + (info.run_id ? " · run " + info.run_id : ""));
    if (trained.name) row("Trained on", trained.name + (trained.licence ? " · " + trained.licence : ""));
    if (typeof evaluation.held_out_test_macro_f1 === "number") {
      row("Held-out test score", "Macro-F1 " + evaluation.held_out_test_macro_f1.toFixed(2) + " on " + evaluation.held_out_test_images + " photos");
    }
    add(c, list, para("fine", evaluation.note || "Measured on a small held-out set. This is not a clinical validation."));
    return c;
  }

  function renderSkin(container, body, wanted, previewUrl) {
    var result = body.result || {};
    clear(container);

    var summary = card(null);
    var topLine = h("div", "top-class");
    add(topLine, h("span", "name", result.predicted_class_name), badge("neutral", result.predicted_class));
    add(summary,
      h("div", "eyebrow-sm", "Highest-scoring class"),
      topLine,
      para("summary-line", "Model score ", strong(pct(clamp01(body.confidence))), ". This is the model's own relative score, not clinical certainty, and it can be wrong."));
    container.appendChild(summary);

    var scoresCard = card("Model scores for all six classes");
    var scores = h("div", "scores");
    (result.probabilities || []).forEach(function (item, index) {
      var row = h("div", "score-row" + (index === 0 ? " is-top" : ""));
      var bar = h("div", "bar"), fill = h("span");
      fill.style.width = (clamp01(item.probability) * 100).toFixed(1) + "%";
      add(bar, fill);
      add(row, h("div", "score-name", item.name), bar, h("div", "score-value", pct(clamp01(item.probability))));
      scores.appendChild(row);
    });
    add(scoresCard, scores, para("fine", "The scores add up to 100% across these six classes. They are not calibrated probabilities and do not measure clinical certainty."));
    container.appendChild(scoresCard);

    container.appendChild(attentionCard(result.explanation_image, wanted, previewUrl));
    container.appendChild(modelCard(result.model));

    var limits = card("Limitations");
    var list = h("ul", "plain-list");
    (result.limitations || []).forEach(function (text) { list.appendChild(h("li", null, text)); });
    add(limits, list);
    container.appendChild(limits);

    var warned = warningsCard(body.warnings);
    if (warned) container.appendChild(warned);
    container.appendChild(boundaryCard(body.clinical_boundary_notice));
    container.appendChild(rawCard(body));
  }

  /* ------------------------------------------------------------------ lab result */

  function valueCell(value) {
    var td = h("td", "num");
    if (value === null || value === undefined || value === "") td.appendChild(badge("warn", "Not found"));
    else td.textContent = String(value);
    return td;
  }

  function checkCell(field) {
    var td = h("td");
    if (field.needs_review) {
      add(td, badge("warn", "Check against the original"));
      var reasons = (field.missing_fields || []).length ? "Missing: " + field.missing_fields.map(readable).join(", ") : "Low text confidence";
      add(td, h("div", "fine", reasons));
    } else {
      add(td, badge("ok", "Parsed"));
    }
    add(td, h("div", "fine", "Source line " + field.line_number));
    return td;
  }

  function labTable(fields) {
    var wrap = h("div", "table-wrap");
    var table = h("table");
    var head = h("tr");
    ["Test", "Result", "Unit", "Reference range (as printed)", "Check"].forEach(function (title) {
      var th = h("th", null, title);
      th.scope = "col";
      head.appendChild(th);
    });
    var thead = h("thead");
    thead.appendChild(head);
    var tbody = h("tbody");
    fields.forEach(function (field) {
      var tr = h("tr", field.needs_review ? "needs-check" : "");
      var name = h("th", null, field.test_name);
      name.scope = "row";
      add(tr, name, valueCell(field.value), valueCell(field.unit), valueCell(field.reference_range), checkCell(field));
      tbody.appendChild(tr);
    });
    add(table, thead, tbody);
    wrap.appendChild(table);
    return wrap;
  }

  function stat(label, value) {
    var node = h("div", "stat");
    add(node, h("span", "stat-label", label), h("span", "stat-value", value));
    return node;
  }

  function renderLab(container, body) {
    var result = body.result || {};
    var fields = result.fields || [];
    clear(container);

    var inner = h("div");
    add(inner,
      strong("Check every value against the original report."),
      para(null, "Text reading can make mistakes. " + (result.reference_range_note || "LUMI copies values exactly as printed and does not say whether any result is normal or abnormal.")));
    var top = h("div", "card");
    top.appendChild(callout("warn", "alert", inner));
    container.appendChild(top);

    var tableCard = card("Result rows found");
    var chips = h("div", "chips");
    add(chips,
      stat("Rows found", String(fields.length)),
      stat("Rows to check", String(result.fields_needing_review || 0)),
      stat("Average text confidence", result.mean_ocr_confidence === null || result.mean_ocr_confidence === undefined ? "n/a" : result.mean_ocr_confidence + " / 100"),
      result.engine ? stat("Engine", result.engine.name + " " + result.engine.version) : null);
    tableCard.appendChild(chips);
    if (fields.length) tableCard.appendChild(labTable(fields));
    else tableCard.appendChild(callout("info", "info", h("div", null, "No result rows were recognised. The text that was read is shown below.")));

    var details = h("details");
    var lines = String(result.extracted_text || "").split("\n");
    var text = (result.extracted_text || "") === "" ? "(no text was found)" : lines.map(function (line, index) {
      return String(index + 1).padStart(2, " ") + "  " + line;
    }).join("\n");
    add(details, h("summary", null, "Full text that was read"), h("pre", null, text));
    tableCard.appendChild(details);
    container.appendChild(tableCard);

    var warned = warningsCard(body.warnings);
    if (warned) container.appendChild(warned);
    container.appendChild(boundaryCard(body.clinical_boundary_notice));
    container.appendChild(rawCard(body));
  }

  /* ------------------------------------------------------------------ analyze */

  var KINDS = {
    skin: { inputType: "skin_image", button: "skin-go", idle: "Analyze photo", result: "skin-result", loading: "Analyzing your photo…" },
    lab: { inputType: "lab_report", button: "lab-go", idle: "Read report", result: "lab-result", loading: "Reading your report…" }
  };

  function analyze(kind) {
    var spec = KINDS[kind];
    var up = uploaders[kind];
    if (state.busy[kind]) return;
    if (!up.file) { up.setError("Choose a file first."); up.focus(); return; }
    var key = getKey();
    if (!key) { setKeyPanel(true, "Enter your API key to continue."); return; }

    var container = $(spec.result);
    var button = $(spec.button);
    var wantsMap = kind === "skin" && $("skin-explain").checked;
    var previewUrl = up.url;
    var form = new FormData();
    form.append("input_type", spec.inputType);
    form.append("file", up.file);
    if (wantsMap) form.append("explain", "true");

    up.setError(null);
    setBusy(kind, true, button, spec.idle);
    showLoading(container, spec.loading);
    request(form, key)
      .then(function (res) {
        var body = res.body;
        if (!body || typeof body !== "object") {
          renderRequestError(container, { status: res.status, body: null, retryAfter: null });
        } else if (body.error || res.status >= 400) {
          renderRequestError(container, res);
        } else if (kind === "skin") {
          renderSkin(container, body, wantsMap, previewUrl);
          rememberResult("skin", body);
        } else {
          renderLab(container, body);
          rememberResult("lab", body);
        }
      })
      .catch(function (error) { renderNetworkError(container, error); })
      .then(function () {
        setBusy(kind, false, button, spec.idle);
        finish(container);
        loadHealth();
      });
  }

  /* ------------------------------------------------------------------ ask a question about a result */

  var EXAMPLES = {
    skin: ["What was the predicted skin class?", "What was the top score?", "What limitations apply to this result?", "Is this cancer?"],
    lab: ["Which lab values were not found?", "What was the reported haemoglobin value?", "Which fields need review?", "What limitations apply to this result?", "Is my haemoglobin normal?"]
  };
  var REFUSAL = "I cannot answer this from the available evidence.";

  // Kept only in this page's memory (never stored). The attention-map picture is left out: the answerer ignores it.
  function rememberResult(kind, body) {
    if (!body || body.error || !body.result || body.result.status !== "completed") return;
    var copy = JSON.parse(JSON.stringify(body));
    if (copy.result && copy.result.explanation_image) delete copy.result.explanation_image.image_base64;
    state.results[kind] = copy;
    refreshAskSources();
  }

  function refreshAskSources() {
    ["skin", "lab"].forEach(function (kind) {
      var radio = $("ask-src-" + kind);
      var have = !!state.results[kind];
      radio.disabled = !have;
      $("ask-" + kind + "-note").textContent = have ? "(ready)" : (kind === "skin" ? "(none yet; use Skin Analysis first)" : "(none yet; use Lab Reports first)");
      if (have && !document.querySelector("input[name=ask-source]:checked")) radio.checked = true;
    });
    renderExamples();
  }

  function chosenSource() {
    var checked = document.querySelector("input[name=ask-source]:checked");
    return checked && !checked.disabled ? checked.value : null;
  }

  function renderExamples() {
    var box = $("ask-examples");
    clear(box);
    var source = chosenSource();
    (source ? EXAMPLES[source] : []).forEach(function (text) {
      var chip = h("button", "chip", text);
      chip.type = "button";
      chip.addEventListener("click", function () { $("ask-question").value = text; $("ask-question").focus(); });
      box.appendChild(chip);
    });
  }

  function renderAnswer(container, body) {
    clear(container);
    var result = body.result || {};
    var refused = result.answerable === false;
    var c = card(refused ? "No answer from the evidence" : "Answer");
    c.appendChild(para("answer-text", String(body.answer || REFUSAL)));
    if (refused) c.appendChild(callout("info", "info", h("div", null, String(body.explanation || "The supplied result does not contain what is needed."))));
    else if (body.explanation) c.appendChild(para("fine", String(body.explanation)));
    container.appendChild(c);
    var warnings = warningsCard(body.warnings);
    if (warnings) container.appendChild(warnings);
    container.appendChild(boundaryCard(body.clinical_boundary_notice));
  }

  function ask() {
    if (state.busy.ask) return;
    var error = $("ask-error");
    error.hidden = true;
    var source = chosenSource();
    var question = $("ask-question").value.trim();
    if (!source) { error.textContent = "Analyse a skin photo or a lab report first, then choose it here."; error.hidden = false; return; }
    if (!question) { error.textContent = "Type a question first."; error.hidden = false; $("ask-question").focus(); return; }
    var key = getKey();
    if (!key) { setKeyPanel(true, "Enter your API key to continue."); return; }

    var container = $("ask-result");
    var button = $("ask-go");
    setBusy("ask", true, button, "Ask");
    showLoading(container, "Looking in the result…");
    var controller = new AbortController();
    var timer = setTimeout(function () { controller.abort(); }, 30000);
    fetch("/api/v1/ask", {
      method: "POST",
      headers: { "Authorization": "Bearer " + key, "Content-Type": "application/json" },
      body: JSON.stringify({ question: question, evidence: state.results[source] }),
      signal: controller.signal
    })
      .then(function (response) {
        clearTimeout(timer);
        return response.text().then(function (text) {
          var body = null;
          try { body = JSON.parse(text); } catch (e) { body = null; }
          return { status: response.status, body: body, retryAfter: response.headers.get("Retry-After") };
        });
      })
      .then(function (res) {
        if (!res.body || typeof res.body !== "object" || res.body.error || res.status >= 400) renderRequestError(container, res);
        else renderAnswer(container, res.body);
      })
      .catch(function (err) { clearTimeout(timer); renderNetworkError(container, err); })
      .then(function () { setBusy("ask", false, button, "Ask"); finish(container); });
  }

  /* ------------------------------------------------------------------ start-up */

  function init() {
    uploaders.skin = createUploader("skin");
    uploaders.lab = createUploader("lab");
    $("skin-go").addEventListener("click", function () { analyze("skin"); });
    $("lab-go").addEventListener("click", function () { analyze("lab"); });
    $("ask-go").addEventListener("click", ask);
    document.querySelectorAll("input[name=ask-source]").forEach(function (r) { r.addEventListener("change", renderExamples); });
    refreshAskSources();

    $("key-toggle").addEventListener("click", function () { setKeyPanel($("key-panel").hidden); });
    $("key-input").addEventListener("input", updateKeyState);
    $("key-show").addEventListener("change", function () { $("key-input").type = this.checked ? "text" : "password"; });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && !$("key-panel").hidden) { setKeyPanel(false); $("key-toggle").focus(); }
    });
    document.addEventListener("click", function (e) {
      if (!$("key-panel").hidden && !e.target.closest(".key-wrap")) setKeyPanel(false);
    });

    // A file dropped outside a drop zone must not make the browser open it.
    window.addEventListener("dragover", function (e) { e.preventDefault(); });
    window.addEventListener("drop", function (e) { e.preventDefault(); });

    window.addEventListener("hashchange", function () { showPage(true); });
    updateKeyState();
    showPage(false);
    loadHealth();
  }

  init();
})();
