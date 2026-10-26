/* IVAO VMR generator GUI. Talks to vmr_gui.py through the /api/... endpoints. */
(function () {
  "use strict";

  const state = {
    presets: [],
    selectedPresets: new Set(),
    rules: [],            // {callsign, type, models: [..]}
    selectedRule: -1,
    liveries: new Map(),  // mtl id -> livery
    mtlRules: { all: [], standard: [] },   // the rules create_vmr.py generates from the MTL
    mtl: { enabled: false, mode: "standard", liveryList: false },
    catalogSearch: "https://mtl.ivao.aero/catalog?textureName={name}",
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
        mtl: state.mtl,
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
      if (draft.mtl) state.mtl = { ...state.mtl, ...draft.mtl };
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

  // ---------------------------------------------------------------- models
  function catalogLink(mtlId, text) {
    return el("a", { href: state.catalogSearch.replace("{name}", encodeURIComponent(mtlId)), target: "_blank", rel: "noreferrer", title: "Open " + mtlId + " in the MTL catalog" }, text);
  }

  // A small label for one model of a rule: its id (linked to the MTL catalog) and its livery name.
  function modelChip(mtlId) {
    const livery = state.liveries.get(mtlId);
    const missing = state.liveries.size > 0 && !livery;
    const chip = el("span", { class: "chip" + (missing ? " missing" : ""), title: missing ? "Not installed in your MTL" : (livery && livery.name) || mtlId }, catalogLink(mtlId, mtlId + " ↗"));
    if (livery && livery.name) chip.append(" ", el("span", { class: "muted" }, livery.name));
    if (missing) chip.append(" ", el("span", { class: "muted" }, "(not installed)"));
    return chip;
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
      const chips = el("div", { class: "chips" }, ...rule.models.map((m) => modelChip(m)));
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
        el("td", { class: "models" }, models, chips, warnings.length ? el("div", { class: "warning" }, warnings.join(" ")) : null),
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

  // ---------------------------------------------------------------- IVAO MTL
  function mtlRulesSelected() {
    if (!state.mtl.enabled) return [];
    return state.mtlRules[state.mtl.mode] || [];
  }

  function renderMtl() {
    const have = state.liveries.size > 0;
    $("mtlEnabled").checked = state.mtl.enabled && have;
    $("mtlEnabled").disabled = !have;
    $("mtlLabel").textContent = have ? "Add the rules generated from my MTL" : "Add the rules generated from my MTL (no MTL found)";
    $("mtlStandard").checked = state.mtl.mode === "standard";
    $("mtlAll").checked = state.mtl.mode === "all";
    $("mtlStandardLabel").textContent = "standard liveries only (" + state.mtlRules.standard.length + " rules, like ivaomtl_standard.vmr)";
    $("mtlAllLabel").textContent = "all liveries (" + state.mtlRules.all.length + " rules, like ivaomtl.vmr)";
    $("mtlLiveryList").checked = state.mtl.liveryList;
    for (const input of document.querySelectorAll("#mtl .indent input")) input.disabled = !(have && state.mtl.enabled);
  }

  // ---------------------------------------------------------------- output
  // Order in the file = priority in vPilot: presets, then my rules, then the rules generated from the MTL.
  function combinedRules() {
    const rules = [];
    for (const preset of state.presets) {
      if (state.selectedPresets.has(preset.id)) rules.push(...preset.rules);
    }
    rules.push(...state.rules.map(normaliseRule).filter((r) => r.type && r.models.length));
    rules.push(...mtlRulesSelected());
    return rules;
  }

  function outputComment() {
    const parts = [];
    if (state.selectedPresets.size) parts.push("Presets: " + [...state.selectedPresets].join(", "));
    if (state.mtl.enabled) parts.push("IVAO MTL: " + (state.mtl.mode === "standard" ? "standard liveries only" : "all liveries"));
    return parts.join("; ");
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
    const own = rules.length - mtlRulesSelected().length;
    $("vmrText").textContent = buildVmr(rules);
    $("save").textContent = "Save to output folder (" + rules.length + " rules)";
    $("outputSummary").textContent = state.mtl.enabled
      ? own + " rules from presets and my rules, then " + mtlRulesSelected().length + " rules generated from the MTL. In vPilot this file replaces the MTL VMR."
      : own + " rules from presets and my rules. In vPilot put this file above the IVAO MTL VMR.";
    saveDraft();
  }

  function savedMessage(files) {
    const where = state.mtl.enabled ? "use this file in vPilot (Settings → Model Matching → Custom Rules) instead of the IVAO MTL VMR." : "add this file in vPilot (Settings → Model Matching → Custom Rules) above the IVAO MTL VMR.";
    return "Saved: " + files.join(", ") + " – " + where;
  }

  async function save() {
    const rules = combinedRules();
    if (rules.length === 0) { $("saveResult").textContent = "Nothing to save: tick a preset or add a rule."; return; }
    $("saveResult").textContent = "Saving…";
    try {
      const result = await api("/api/save", { fileName: $("fileName").value, rules: rules, comment: outputComment(), liveryList: state.mtl.enabled && state.mtl.liveryList });
      $("saveResult").textContent = savedMessage(result.files || [result.path]);
    } catch (err) {
      $("saveResult").textContent = "Error: " + err.message;
    }
  }

  const inWindow = () => Boolean(window.pywebview && window.pywebview.api);

  async function download() {
    const rules = combinedRules();
    if (inWindow()) {
      // Running in the application window: use the Windows "Save as" dialog instead of a browser download.
      try {
        const result = await window.pywebview.api.save_as($("fileName").value || "custom.vmr", buildVmr(rules));
        if (result.error) $("saveResult").textContent = "Error: " + result.error;
        else if (!result.cancelled) $("saveResult").textContent = savedMessage([result.path]);
      } catch (err) {
        $("saveResult").textContent = "Error: " + err;
      }
      return;
    }
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
      const link = catalogLink(livery.id, "↗");
      link.className = "catalog";
      link.addEventListener("click", (e) => e.stopPropagation());
      card.append(
        el("div", { class: "head" }, el("div", { class: "id" }, livery.id), link),
        el("div", { class: "name" + (livery.standard ? "" : " special") }, livery.name || livery.model),
        el("div", { class: "meta" }, livery.type + " · " + (livery.airline || "any airline") + (livery.standard ? "" : " · special livery"))
      );
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
  async function importText(text, name) {
    try {
      const result = await api("/api/parse-vmr", { text: text });
      state.rules.push(...result.rules.map(normaliseRule));
      renderRules();
      setStatus("Imported " + result.rules.length + " rules from " + name);
    } catch (err) {
      setStatus("Import failed: " + err.message, true);
    }
  }

  function importFile(file) {
    const reader = new FileReader();
    reader.onload = () => importText(reader.result, file.name);
    reader.readAsText(file);
  }

  async function importFromDialog() {
    const result = await window.pywebview.api.open_file();
    if (result.error) setStatus("Import failed: " + result.error, true);
    else if (!result.cancelled) importText(result.text, result.name);
  }

  // In the application window the file input is replaced by a button that opens the Windows "Open" dialog.
  window.addEventListener("pywebviewready", () => {
    const input = $("importFile");
    const button = el("button", { class: "secondary", onclick: importFromDialog }, "Open a VMR file…");
    input.replaceWith(button);
    $("download").textContent = "Save as…";
  });

  // ---------------------------------------------------------------- init
  async function init() {
    loadDraft();
    try {
      const data = await api("/api/state");
      state.presets = data.presets;
      state.catalogSearch = data.catalogSearch;
      state.liveries = new Map(data.liveries.map((l) => [l.id, l]));
      state.mtlRules = data.mtlRules;
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
    renderMtl();
    renderRules();
    renderLibrary();
  }

  $("mtlEnabled").addEventListener("change", () => { state.mtl.enabled = $("mtlEnabled").checked; renderMtl(); updateOutput(); });
  $("mtlStandard").addEventListener("change", () => { state.mtl.mode = "standard"; updateOutput(); });
  $("mtlAll").addEventListener("change", () => { state.mtl.mode = "all"; updateOutput(); });
  $("mtlLiveryList").addEventListener("change", () => { state.mtl.liveryList = $("mtlLiveryList").checked; saveDraft(); });

  $("addRule").addEventListener("click", () => addRule());
  $("clearRules").addEventListener("click", () => { if (state.rules.length === 0 || confirm("Remove all your rules?")) { state.rules = []; state.selectedRule = -1; renderRules(); } });
  $("save").addEventListener("click", save);
  $("download").addEventListener("click", download);
  $("fileName").addEventListener("input", saveDraft);
  $("search").addEventListener("input", renderLibrary);
  $("importFile").addEventListener("change", (e) => { if (e.target.files[0]) importFile(e.target.files[0]); e.target.value = ""; });
  init();
})();
