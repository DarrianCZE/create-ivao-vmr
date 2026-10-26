/* IVAO VMR generator GUI. Talks to vmr_gui.py through the /api/... endpoints. */
(function () {
  "use strict";

  const state = {
    presets: [],
    selectedPresets: new Set(),
    rules: [],            // {callsign, type, models: [..]}
    selectedRule: -1,
    liveries: new Map(),  // mtl id -> livery
    hasApiKey: false,
    catalogSearch: "https://mtl.ivao.aero/catalog?textureName={name}",
    notAvailableImage: "https://static.ivao.aero/mtl/clouds.jpg",
  };
  const DRAFT_KEY = "ivao-vmr-generator-draft";

  const $ = (id) => document.getElementById(id);

  // ---------------------------------------------------------------- helpers
  async function api(path, body) {
    const options = body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {};
    const response = await fetch(path, options);
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || (response.status + " " + response.statusText));
    return data;
  }

  function el(tag, attrs, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs || {})) {
      if (key === "class") node.className = value;
      else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
      else if (value !== null && value !== undefined) node.setAttribute(key, value);
    }
    for (const child of children) {
      if (child === null || child === undefined) continue;
      node.append(child.nodeType ? child : document.createTextNode(String(child)));
    }
    return node;
  }

  function setStatus(text, isError) {
    $("status").textContent = text;
    $("status").className = "status" + (isError ? " error" : "");
  }

  function saveDraft() {
    try {
      localStorage.setItem(DRAFT_KEY, JSON.stringify({
        rules: state.rules,
        selectedPresets: [...state.selectedPresets],
        fileName: $("fileName").value,
      }));
    } catch (e) { /* ignore */ }
  }

  function loadDraft() {
    try {
      const draft = JSON.parse(localStorage.getItem(DRAFT_KEY) || "null");
      if (!draft) return;
      state.rules = (draft.rules || []).map(normaliseRule);
      state.selectedPresets = new Set(draft.selectedPresets || []);
      if (draft.fileName) $("fileName").value = draft.fileName;
    } catch (e) { /* ignore */ }
  }

  function normaliseRule(rule) {
    return {
      callsign: (rule.callsign || "").trim().toUpperCase(),
      type: (rule.type || "").trim().toUpperCase(),
      models: (rule.models || []).map((m) => m.trim()).filter(Boolean),
    };
  }

  function modelsFromText(text) {
    return text.split("//").map((m) => m.trim()).filter(Boolean);
  }

  // ---------------------------------------------------------------- previews
  function thumbnail(mtlId, size) {
    const livery = state.liveries.get(mtlId);
    const missing = !livery;
    const img = el("img", { alt: mtlId, loading: "lazy" });
    // Preferred source: picture from the MTL catalog (needs the API key). Fallbacks: local thumbnail, placeholder.
    const sources = [];
    if (state.hasApiKey) sources.push("/api/catalog-image/" + encodeURIComponent(mtlId));
    if (livery && livery.hasThumbnail) sources.push("/api/thumbnail/" + encodeURIComponent(mtlId));
    sources.push(state.notAvailableImage);
    let index = 0;
    img.src = sources[index];
    img.addEventListener("error", () => {
      index += 1;
      if (index < sources.length) img.src = sources[index];
    });
    const caption = livery ? (livery.name || mtlId) : mtlId + " (not installed)";
    const link = el("a", { href: state.catalogSearch.replace("{name}", encodeURIComponent(mtlId)), target: "_blank", rel: "noreferrer", title: "Open in the MTL catalog" }, img);
    return el("div", { class: "thumb" + (missing ? " missing" : ""), title: caption }, link, el("div", { class: "cap" }, mtlId + (livery && livery.name ? " – " + livery.name : "")));
  }

  // ---------------------------------------------------------------- presets
  function renderPresets() {
    const container = $("presets");
    container.innerHTML = "";
    if (state.presets.length === 0) {
      container.append(el("div", { class: "hint" }, "No presets found. Put .vmr files into the presets folder next to vmr_gui.py."));
      return;
    }
    for (const preset of state.presets) {
      const checkbox = el("input", { type: "checkbox" });
      checkbox.checked = state.selectedPresets.has(preset.id);
      checkbox.addEventListener("change", () => {
        if (checkbox.checked) state.selectedPresets.add(preset.id); else state.selectedPresets.delete(preset.id);
        updateOutput();
      });
      const list = el("ul");
      for (const rule of preset.rules) {
        const line = el("li", {}, (rule.callsign || "*") + " " + rule.type + " → ");
        rule.models.forEach((model, i) => {
          const known = state.liveries.size === 0 || state.liveries.has(model);
          line.append(el("span", { class: "model" + (known ? "" : " missing"), title: known ? "Show in the library" : "Not installed in your MTL", onclick: () => { $("search").value = model; renderLibrary(); } }, model));
          if (i < rule.models.length - 1) line.append(" // ");
        });
        list.append(line);
      }
      container.append(el("div", { class: "preset" },
        el("label", {}, checkbox, preset.name + " (" + preset.rules.length + " rules)"),
        preset.description ? el("div", { class: "desc" }, preset.description) : null,
        el("details", {}, el("summary", {}, "Rules"), list,
          el("button", { class: "small secondary", onclick: () => { state.rules.push(...preset.rules.map(normaliseRule)); renderRules(); } }, "Copy into my rules"))
      ));
    }
  }

  // ---------------------------------------------------------------- rules
  function renderRules() {
    const body = $("rulesBody");
    body.innerHTML = "";
    state.rules.forEach((rule, index) => {
      const row = el("tr", { class: index === state.selectedRule ? "selected" : "" });
      const select = () => { if (state.selectedRule !== index) { state.selectedRule = index; renderRules(); } };
      const callsign = el("input", { type: "text", value: rule.callsign, placeholder: "TVS", maxlength: 3, list: "airlines", onfocus: select, oninput: () => { rule.callsign = callsign.value.toUpperCase(); updateOutput(); } });
      const type = el("input", { type: "text", value: rule.type, placeholder: "B738", maxlength: 4, list: "types", onfocus: select, oninput: () => { rule.type = type.value.toUpperCase(); updateOutput(); } });
      const models = el("input", { type: "text", value: rule.models.join("//"), placeholder: "B738TVSWL//B738TVSWL3", list: "models", onfocus: select });
      models.addEventListener("change", () => { rule.models = modelsFromText(models.value); renderRules(); });
      models.addEventListener("input", () => { rule.models = modelsFromText(models.value); updateOutput(); });
      const preview = el("div", { class: "thumbs" }, ...rule.models.map((m) => thumbnail(m)));
      const warnings = [];
      if (!rule.type) warnings.push("Type is required.");
      if (rule.models.length === 0) warnings.push("At least one model is required.");
      if (state.liveries.size > 0) {
        const missing = rule.models.filter((m) => !state.liveries.has(m));
        if (missing.length) warnings.push("Not installed: " + missing.join(", "));
      }
      row.append(
        el("td", { class: "callsign" }, callsign),
        el("td", { class: "type" }, type),
        el("td", { class: "models" }, models, warnings.length ? el("div", { class: "warning" }, warnings.join(" ")) : null),
        el("td", { class: "preview" }, preview),
        el("td", {}, el("button", { class: "small danger", title: "Remove rule", onclick: () => { state.rules.splice(index, 1); if (state.selectedRule >= state.rules.length) state.selectedRule = state.rules.length - 1; renderRules(); } }, "✕"))
      );
      body.append(row);
    });
    updateOutput();
  }

  function addRule(rule) {
    state.rules.push(normaliseRule(rule || {}));
    state.selectedRule = state.rules.length - 1;
    renderRules();
    const inputs = $("rulesBody").querySelectorAll("tr:last-child input");
    if (inputs.length) inputs[0].focus();
  }

  function addModelToSelectedRule(livery) {
    if (state.selectedRule < 0 || state.selectedRule >= state.rules.length) {
      addRule({ callsign: livery.airline, type: livery.type, models: [livery.id] });
      return;
    }
    const rule = state.rules[state.selectedRule];
    if (!rule.type) rule.type = livery.type;
    if (!rule.callsign && rule.models.length === 0) rule.callsign = livery.airline;
    if (!rule.models.includes(livery.id)) rule.models.push(livery.id);
    renderRules();
  }

  // ---------------------------------------------------------------- output
  function combinedRules() {
    const rules = [];
    for (const preset of state.presets) {
      if (state.selectedPresets.has(preset.id)) rules.push(...preset.rules);
    }
    rules.push(...state.rules.map(normaliseRule).filter((r) => r.type && r.models.length));
    return rules;
  }

  function buildVmr(rules) {
    const escape = (s) => s.replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    const lines = ['<?xml version="1.0" encoding="utf-8"?>', "<ModelMatchRuleSet>"];
    for (const rule of rules) {
      const attrs = (rule.callsign ? ' CallsignPrefix="' + escape(rule.callsign) + '"' : "") +
        ' TypeCode="' + escape(rule.type) + '" ModelName="' + escape(rule.models.join("//")) + '"';
      lines.push("<ModelMatchRule" + attrs + " />");
    }
    lines.push("</ModelMatchRuleSet>");
    lines.push("<!-- VMR created by create-ivao-vmr GUI https://github.com/vojta48/create-ivao-vmr -->");
    return lines.join("\r\n") + "\r\n";
  }

  function updateOutput() {
    const rules = combinedRules();
    $("vmrText").textContent = buildVmr(rules);
    $("save").textContent = "Save to output folder (" + rules.length + " rules)";
    saveDraft();
  }

  async function save() {
    const rules = combinedRules();
    if (rules.length === 0) { $("saveResult").textContent = "Nothing to save: tick a preset or add a rule."; return; }
    $("saveResult").textContent = "Saving…";
    try {
      const result = await api("/api/save", { fileName: $("fileName").value, rules: rules, comment: "Presets: " + [...state.selectedPresets].join(", ") });
      $("saveResult").textContent = "Saved: " + result.path + " – add this file in vPilot (Settings → Model Matching → Custom Rules) above the IVAO MTL VMR.";
    } catch (err) {
      $("saveResult").textContent = "Error: " + err.message;
    }
  }

  function download() {
    const rules = combinedRules();
    const blob = new Blob([buildVmr(rules)], { type: "text/xml" });
    const link = el("a", { href: URL.createObjectURL(blob), download: $("fileName").value || "custom.vmr" });
    document.body.append(link);
    link.click();
    link.remove();
  }

  // ---------------------------------------------------------------- library
  function renderLibrary() {
    const grid = $("library");
    grid.innerHTML = "";
    const query = $("search").value.trim().toUpperCase();
    const terms = query.split(/\s+/).filter(Boolean);
    const all = [...state.liveries.values()];
    const matches = all.filter((l) => terms.every((t) => (l.id + " " + l.airline + " " + l.type + " " + l.name).toUpperCase().includes(t)));
    const limit = 120;
    $("libraryInfo").textContent = all.length === 0
      ? "No liveries found. Run vmr_gui.py from the IVAO_MTL folder (or use -d) to see your installed liveries."
      : matches.length + " of " + all.length + " liveries" + (matches.length > limit ? " (showing the first " + limit + ", refine the search)" : "");
    for (const livery of matches.slice(0, limit)) {
      const card = el("div", { class: "card", title: "Add " + livery.id + " to the selected rule", onclick: () => addModelToSelectedRule(livery) });
      const thumb = thumbnail(livery.id);
      const img = thumb.querySelector("img");
      card.append(img, el("div", { class: "id" }, livery.id), el("div", { class: "name" }, livery.name || livery.model));
      grid.append(card);
    }
  }

  function renderDatalists() {
    const airlines = new Set(), types = new Set();
    for (const l of state.liveries.values()) { if (l.airline) airlines.add(l.airline); if (l.type) types.add(l.type); }
    const make = (id, values) => {
      let list = $(id);
      if (!list) { list = el("datalist", { id: id }); document.body.append(list); }
      list.innerHTML = "";
      for (const v of [...values].sort()) list.append(el("option", { value: v }));
    };
    make("airlines", airlines);
    make("types", types);
    make("models", [...state.liveries.keys()]);
  }

  // ---------------------------------------------------------------- import
  function importFile(file) {
    const reader = new FileReader();
    reader.onload = async () => {
      try {
        const result = await api("/api/parse-vmr", { text: reader.result });
        state.rules.push(...result.rules.map(normaliseRule));
        renderRules();
        setStatus("Imported " + result.rules.length + " rules from " + file.name);
      } catch (err) {
        setStatus("Import failed: " + err.message, true);
      }
    };
    reader.readAsText(file);
  }

  // ---------------------------------------------------------------- init
  async function init() {
    loadDraft();
    try {
      const data = await api("/api/state");
      state.presets = data.presets;
      state.hasApiKey = data.settings.hasApiKey;
      state.catalogSearch = data.catalogSearch;
      state.notAvailableImage = data.notAvailableImage;
      state.liveries = new Map(data.liveries.map((l) => [l.id, l]));
      $("apiKeyState").textContent = state.hasApiKey ? "API key saved: previews come from the MTL catalog." : "No API key: previews use the local thumbnails of your MTL.";
      if (data.libraryFound) {
        setStatus(data.liveries.length + " liveries found in " + data.airplanesFolder + " · output folder: " + data.outputDir);
      } else {
        setStatus("MTL not found in " + data.airplanesFolder + ". Run the script from the IVAO_MTL folder or pass -d. Presets and manual rules still work.", true);
      }
      if (data.errors.length) console.warn("aircraft.cfg problems:", data.errors);
    } catch (err) {
      setStatus("Could not load data from the server: " + err.message, true);
    }
    renderPresets();
    renderDatalists();
    renderRules();
    renderLibrary();
  }

  $("addRule").addEventListener("click", () => addRule());
  $("clearRules").addEventListener("click", () => { if (state.rules.length === 0 || confirm("Remove all your rules?")) { state.rules = []; state.selectedRule = -1; renderRules(); } });
  $("save").addEventListener("click", save);
  $("download").addEventListener("click", download);
  $("fileName").addEventListener("input", saveDraft);
  $("search").addEventListener("input", renderLibrary);
  $("importFile").addEventListener("change", (e) => { if (e.target.files[0]) importFile(e.target.files[0]); e.target.value = ""; });
  $("saveApiKey").addEventListener("click", async () => {
    try {
      const result = await api("/api/settings", { apiKey: $("apiKey").value });
      state.hasApiKey = result.hasApiKey;
      $("apiKey").value = "";
      $("apiKeyState").textContent = state.hasApiKey ? "API key saved: previews come from the MTL catalog." : "API key removed: previews use the local thumbnails.";
      renderRules();
      renderLibrary();
    } catch (err) {
      $("apiKeyState").textContent = "Error: " + err.message;
    }
  });

  init();
})();
