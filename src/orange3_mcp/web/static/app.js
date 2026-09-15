"use strict";

const state = {
  widgets: [],
  widgetsByQualifiedName: new Map(),
  workflows: [],
  workflowId: null,
  workflow: null, // full describe() payload for the active workflow
  selectedNodeId: null,
  pendingLink: null, // {nodeId, channel} while picking a source output port
  openaiEnabled: false,
};

const $ = (id) => document.getElementById(id);

// ---------------------------------------------------------------- fetch helper

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  let body = null;
  const text = await res.text();
  if (text) {
    try { body = JSON.parse(text); } catch { body = text; }
  }
  if (!res.ok) {
    const detail = (body && body.detail) || (typeof body === "string" ? body : res.statusText);
    throw new Error(detail);
  }
  return body;
}

function showToast(message, isError = false) {
  const toast = $("toast");
  toast.textContent = message;
  toast.classList.remove("hidden");
  toast.classList.toggle("error", isError);
  clearTimeout(showToast._t);
  showToast._t = setTimeout(() => toast.classList.add("hidden"), 4000);
}

function reportError(err) {
  console.error(err);
  showToast(err.message || String(err), true);
}

// ---------------------------------------------------------------- tabs

function initTabs() {
  const tabs = [
    ["tab-builder", "panel-builder"],
    ["tab-chat", "panel-chat"],
    ["tab-addons", "panel-addons"],
  ];
  for (const [tabId, panelId] of tabs) {
    $(tabId).addEventListener("click", () => {
      for (const [t, p] of tabs) {
        const active = t === tabId;
        $(t).classList.toggle("active", active);
        $(t).setAttribute("aria-selected", String(active));
        $(p).classList.toggle("active", active);
      }
    });
  }
}

// ---------------------------------------------------------------- widget palette

async function loadWidgets() {
  state.widgets = await api("/api/widgets");
  state.widgetsByQualifiedName = new Map(state.widgets.map((w) => [w.qualified_name, w]));

  const byCategory = new Map();
  for (const w of state.widgets) {
    if (!byCategory.has(w.category)) byCategory.set(w.category, []);
    byCategory.get(w.category).push(w);
  }

  const container = $("palette-list");
  container.innerHTML = "";
  for (const [category, widgets] of [...byCategory.entries()].sort()) {
    const details = document.createElement("details");
    details.open = category === "Data";
    const summary = document.createElement("summary");
    summary.textContent = category;
    details.appendChild(summary);
    const ul = document.createElement("ul");
    for (const w of widgets) {
      const li = document.createElement("li");
      const btn = document.createElement("button");
      btn.type = "button";
      btn.textContent = `+ ${w.name}`;
      btn.title = w.qualified_name;
      btn.addEventListener("click", () => addNode(w.id));
      li.appendChild(btn);
      ul.appendChild(li);
    }
    details.appendChild(ul);
    container.appendChild(details);
  }
}

// ---------------------------------------------------------------- workflows

async function refreshWorkflowList(selectId = null) {
  state.workflows = await api("/api/workflows");
  const select = $("workflow-select");
  select.innerHTML = "";
  for (const wf of state.workflows) {
    const opt = document.createElement("option");
    opt.value = wf.id;
    opt.textContent = `${wf.title} (${wf.id})`;
    select.appendChild(opt);
  }

  if (state.workflows.length === 0) {
    await createWorkflow();
    return;
  }

  const target = selectId || state.workflowId || state.workflows[0].id;
  if (state.workflows.some((wf) => wf.id === target)) {
    select.value = target;
    await selectWorkflow(target);
  } else {
    await selectWorkflow(state.workflows[0].id);
  }
}

async function createWorkflow() {
  const title = prompt("Workflow title:", "Untitled") || "Untitled";
  const wf = await api("/api/workflows", { method: "POST", body: JSON.stringify({ title }) });
  await refreshWorkflowList(wf.id);
}

async function selectWorkflow(id) {
  state.workflowId = id;
  state.selectedNodeId = null;
  state.workflow = await api(`/api/workflows/${id}`);
  renderWorkflow();
}

async function refreshCurrentWorkflow() {
  if (!state.workflowId) return;
  state.workflow = await api(`/api/workflows/${state.workflowId}`);
  renderWorkflow();
}

// ---------------------------------------------------------------- node/link mutation

function nextNodePosition() {
  const n = (state.workflow?.nodes.length) || 0;
  const col = n % 5;
  const row = Math.floor(n / 5);
  return { x: 40 + col * 170, y: 40 + row * 110 };
}

async function addNode(widgetId) {
  if (!state.workflowId) return;
  const { x, y } = nextNodePosition();
  try {
    await api(`/api/workflows/${state.workflowId}/nodes`, {
      method: "POST",
      body: JSON.stringify({ widget: widgetId, x, y }),
    });
    await refreshCurrentWorkflow();
  } catch (err) { reportError(err); }
}

async function deleteNode(nodeId) {
  try {
    await api(`/api/workflows/${state.workflowId}/nodes/${nodeId}`, { method: "DELETE" });
    if (state.selectedNodeId === nodeId) closeNodeEditor();
    await refreshCurrentWorkflow();
  } catch (err) { reportError(err); }
}

async function updateNodePosition(nodeId, x, y) {
  try {
    await api(`/api/workflows/${state.workflowId}/nodes/${nodeId}`, {
      method: "PATCH",
      body: JSON.stringify({ x, y }),
    });
    await refreshCurrentWorkflow();
  } catch (err) { reportError(err); }
}

async function deleteLink(linkId) {
  try {
    await api(`/api/workflows/${state.workflowId}/links/${linkId}`, { method: "DELETE" });
    await refreshCurrentWorkflow();
  } catch (err) { reportError(err); }
}

async function connectNodes(sourceNodeId, sourceChannel, sinkNodeId, sinkChannel) {
  try {
    await api(`/api/workflows/${state.workflowId}/links`, {
      method: "POST",
      body: JSON.stringify({
        source_node_id: sourceNodeId, source_channel: sourceChannel,
        sink_node_id: sinkNodeId, sink_channel: sinkChannel,
      }),
    });
    await refreshCurrentWorkflow();
  } catch (err) { reportError(err); }
}

// ---------------------------------------------------------------- node editor panel

function openNodeEditor(nodeId) {
  const node = state.workflow.nodes.find((n) => n.id === nodeId);
  if (!node) return;
  state.selectedNodeId = nodeId;
  $("node-editor-title").textContent = `"${node.title}" (#${node.id})`;
  $("node-title").value = node.title;
  $("node-x").value = node.position[0];
  $("node-y").value = node.position[1];
  $("node-properties").value = JSON.stringify(node.properties || {}, null, 2);
  $("node-editor").classList.remove("hidden");
  renderCanvas();
}

function closeNodeEditor() {
  state.selectedNodeId = null;
  $("node-editor").classList.add("hidden");
  renderCanvas();
}

$("node-editor-close").addEventListener("click", closeNodeEditor);
$("node-delete-btn").addEventListener("click", () => {
  if (state.selectedNodeId && confirm("Delete this node and any links attached to it?")) {
    deleteNode(state.selectedNodeId);
  }
});
$("node-editor-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!state.selectedNodeId) return;
  let properties;
  try {
    properties = JSON.parse($("node-properties").value || "{}");
  } catch {
    showToast("Properties must be valid JSON.", true);
    return;
  }
  try {
    await api(`/api/workflows/${state.workflowId}/nodes/${state.selectedNodeId}`, {
      method: "PATCH",
      body: JSON.stringify({
        title: $("node-title").value,
        x: Number($("node-x").value),
        y: Number($("node-y").value),
        properties,
      }),
    });
    await refreshCurrentWorkflow();
    showToast("Node updated.");
  } catch (err) { reportError(err); }
});

// ---------------------------------------------------------------- canvas (SVG)

const NODE_W = 150;

function nodeSpec(node) {
  return state.widgetsByQualifiedName.get(node.qualified_name);
}

function nodeHeight(node) {
  const spec = nodeSpec(node);
  const ports = Math.max(spec?.inputs.length || 0, spec?.outputs.length || 0, 1);
  return Math.max(50, 24 + ports * 16);
}

function renderCanvas() {
  const svg = $("canvas");
  svg.innerHTML = "";
  if (!state.workflow) return;
  const { nodes, links } = state.workflow;
  const byId = new Map(nodes.map((n) => [n.id, n]));

  const portPos = (node, direction, channel) => {
    const spec = nodeSpec(node);
    const list = direction === "out" ? spec?.outputs : spec?.inputs;
    const idx = list ? list.indexOf(channel) : 0;
    const count = list ? list.length : 1;
    const h = nodeHeight(node);
    const y = node.position[1] + (h * (idx + 1)) / (count + 1);
    const x = node.position[0] + (direction === "out" ? NODE_W : 0);
    return { x, y };
  };

  const ns = "http://www.w3.org/2000/svg";

  for (const link of links) {
    const src = byId.get(link.source_node_id);
    const dst = byId.get(link.sink_node_id);
    if (!src || !dst) continue;
    const p1 = portPos(src, "out", link.source_channel);
    const p2 = portPos(dst, "in", link.sink_channel);
    const midX = (p1.x + p2.x) / 2;
    const path = document.createElementNS(ns, "path");
    path.setAttribute("d", `M ${p1.x} ${p1.y} C ${midX} ${p1.y}, ${midX} ${p2.y}, ${p2.x} ${p2.y}`);
    path.setAttribute("class", "link-line");
    svg.appendChild(path);
  }

  for (const node of nodes) {
    const spec = nodeSpec(node);
    const h = nodeHeight(node);
    const g = document.createElementNS(ns, "g");
    g.setAttribute("transform", `translate(${node.position[0]}, ${node.position[1]})`);

    const rect = document.createElementNS(ns, "rect");
    rect.setAttribute("width", NODE_W);
    rect.setAttribute("height", h);
    rect.setAttribute("rx", 8);
    rect.setAttribute("class", "node-rect" + (state.selectedNodeId === node.id ? " selected" : ""));
    rect.setAttribute("tabindex", "0");
    rect.setAttribute("role", "button");
    rect.setAttribute("aria-label", `${node.title} node, drag to move, activate to edit`);
    g.appendChild(rect);

    const label = document.createElementNS(ns, "text");
    label.setAttribute("x", NODE_W / 2);
    label.setAttribute("y", 16);
    label.setAttribute("text-anchor", "middle");
    label.setAttribute("class", "node-label");
    label.textContent = node.title;
    g.appendChild(label);

    (spec?.inputs || []).forEach((ch, i, arr) => {
      const y = (h * (i + 1)) / (arr.length + 1);
      const c = document.createElementNS(ns, "circle");
      c.setAttribute("cx", 0); c.setAttribute("cy", y); c.setAttribute("r", 5);
      c.setAttribute("class", "port");
      const title = document.createElementNS(ns, "title");
      title.textContent = `input: ${ch}`;
      c.appendChild(title);
      c.addEventListener("click", (e) => {
        e.stopPropagation();
        completePendingLink(node.id, ch);
      });
      g.appendChild(c);
    });

    (spec?.outputs || []).forEach((ch, i, arr) => {
      const y = (h * (i + 1)) / (arr.length + 1);
      const c = document.createElementNS(ns, "circle");
      c.setAttribute("cx", NODE_W); c.setAttribute("cy", y); c.setAttribute("r", 5);
      c.setAttribute("class", "port");
      const title = document.createElementNS(ns, "title");
      title.textContent = `output: ${ch}`;
      c.appendChild(title);
      c.addEventListener("click", (e) => {
        e.stopPropagation();
        state.pendingLink = { nodeId: node.id, channel: ch };
        $("canvas-status").textContent = `Picking source "${ch}" from ${node.title} — click a target input port.`;
      });
      g.appendChild(c);
    });

    makeDraggable(g, rect, node);
    rect.addEventListener("click", (e) => { e.stopPropagation(); openNodeEditor(node.id); });
    rect.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openNodeEditor(node.id); }
    });

    svg.appendChild(g);
  }
}

async function completePendingLink(nodeId, channel) {
  if (!state.pendingLink) return;
  const { nodeId: sourceId, channel: sourceChannel } = state.pendingLink;
  state.pendingLink = null;
  $("canvas-status").textContent = "";
  await connectNodes(sourceId, sourceChannel, nodeId, channel);
}

$("canvas").addEventListener("click", () => {
  if (state.pendingLink) {
    state.pendingLink = null;
    $("canvas-status").textContent = "Cancelled.";
  }
});

function makeDraggable(g, rect, node) {
  let dragging = false;
  let start = null;

  rect.addEventListener("pointerdown", (e) => {
    dragging = true;
    rect.setPointerCapture(e.pointerId);
    const svgRect = $("canvas").getBoundingClientRect();
    const viewBox = $("canvas").viewBox.baseVal;
    const scale = viewBox.width / svgRect.width;
    start = {
      pointerX: e.clientX, pointerY: e.clientY,
      nodeX: node.position[0], nodeY: node.position[1], scale,
    };
  });
  rect.addEventListener("pointermove", (e) => {
    if (!dragging) return;
    const dx = (e.clientX - start.pointerX) * start.scale;
    const dy = (e.clientY - start.pointerY) * start.scale;
    const x = Math.round(start.nodeX + dx);
    const y = Math.round(start.nodeY + dy);
    g.setAttribute("transform", `translate(${x}, ${y})`);
  });
  rect.addEventListener("pointerup", (e) => {
    if (!dragging) return;
    dragging = false;
    const dx = (e.clientX - start.pointerX) * start.scale;
    const dy = (e.clientY - start.pointerY) * start.scale;
    const x = Math.round(start.nodeX + dx);
    const y = Math.round(start.nodeY + dy);
    if (Math.abs(dx) > 2 || Math.abs(dy) > 2) {
      updateNodePosition(node.id, x, y);
    }
  });
}

// ---------------------------------------------------------------- side lists

function renderNodeList() {
  const ul = $("node-list");
  ul.innerHTML = "";
  for (const node of state.workflow?.nodes || []) {
    const li = document.createElement("li");
    const label = document.createElement("span");
    label.textContent = `${node.title}`;
    const meta = document.createElement("span");
    meta.className = "meta";
    meta.textContent = `#${node.id}`;
    const btn = document.createElement("button");
    btn.type = "button";
    btn.textContent = "Edit";
    btn.addEventListener("click", () => openNodeEditor(node.id));
    li.append(label, meta, btn);
    ul.appendChild(li);
  }
}

function renderLinkList() {
  const ul = $("link-list");
  ul.innerHTML = "";
  const byId = new Map((state.workflow?.nodes || []).map((n) => [n.id, n]));
  for (const link of state.workflow?.links || []) {
    const li = document.createElement("li");
    const src = byId.get(link.source_node_id);
    const dst = byId.get(link.sink_node_id);
    const label = document.createElement("span");
    label.textContent = `${src?.title || link.source_node_id} (${link.source_channel}) → ${dst?.title || link.sink_node_id} (${link.sink_channel})`;
    const btn = document.createElement("button");
    btn.type = "button";
    btn.textContent = "Remove";
    btn.className = "danger";
    btn.addEventListener("click", () => deleteLink(link.id));
    li.append(label, btn);
    ul.appendChild(li);
  }
}

function renderConnectForm() {
  const nodes = state.workflow?.nodes || [];
  const sourceSel = $("link-source-node");
  const sinkSel = $("link-sink-node");
  for (const sel of [sourceSel, sinkSel]) {
    const prev = sel.value;
    sel.innerHTML = "";
    for (const n of nodes) {
      const opt = document.createElement("option");
      opt.value = n.id;
      opt.textContent = `${n.title} (#${n.id})`;
      sel.appendChild(opt);
    }
    if (nodes.some((n) => n.id === prev)) sel.value = prev;
  }
  updateChannelOptions($("link-source-channel"), sourceSel.value, "outputs");
  updateChannelOptions($("link-sink-channel"), sinkSel.value, "inputs");
}

function updateChannelOptions(select, nodeId, direction) {
  const node = (state.workflow?.nodes || []).find((n) => n.id === nodeId);
  const spec = node && nodeSpec(node);
  select.innerHTML = "";
  for (const ch of (spec ? spec[direction] : [])) {
    const opt = document.createElement("option");
    opt.value = ch;
    opt.textContent = ch;
    select.appendChild(opt);
  }
}

$("link-source-node").addEventListener("change", (e) => updateChannelOptions($("link-source-channel"), e.target.value, "outputs"));
$("link-sink-node").addEventListener("change", (e) => updateChannelOptions($("link-sink-channel"), e.target.value, "inputs"));

$("connect-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const sourceNodeId = $("link-source-node").value;
  const sourceChannel = $("link-source-channel").value;
  const sinkNodeId = $("link-sink-node").value;
  const sinkChannel = $("link-sink-channel").value;
  if (!sourceNodeId || !sinkNodeId || !sourceChannel || !sinkChannel) {
    showToast("Pick a node and channel on both sides.", true);
    return;
  }
  connectNodes(sourceNodeId, sourceChannel, sinkNodeId, sinkChannel);
});

function renderWorkflow() {
  renderCanvas();
  renderNodeList();
  renderLinkList();
  renderConnectForm();
  $("download-link").classList.toggle("hidden", !state.workflow?.path);
  if (state.workflow?.path) {
    $("download-link").href = `/api/workflows/${state.workflowId}/download`;
  }
}

// ---------------------------------------------------------------- save / load

$("save-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const filename = $("save-filename").value.trim();
  if (!filename) { showToast("Enter a filename.", true); return; }
  try {
    await api(`/api/workflows/${state.workflowId}/save`, {
      method: "POST", body: JSON.stringify({ filename }),
    });
    showToast("Saved.");
    await refreshCurrentWorkflow();
    await refreshSavedFiles();
  } catch (err) { reportError(err); }
});

async function refreshSavedFiles() {
  const files = await api("/api/files");
  const sel = $("load-select");
  sel.innerHTML = "";
  for (const f of files) {
    const opt = document.createElement("option");
    opt.value = f; opt.textContent = f;
    sel.appendChild(opt);
  }
}

$("load-btn").addEventListener("click", async () => {
  const filename = $("load-select").value;
  if (!filename) return;
  try {
    const wf = await api("/api/workflows/load", { method: "POST", body: JSON.stringify({ filename }) });
    await refreshWorkflowList(wf.id);
    showToast(`Loaded ${filename}.`);
  } catch (err) { reportError(err); }
});

$("new-workflow-btn").addEventListener("click", createWorkflow);
$("workflow-select").addEventListener("change", (e) => selectWorkflow(e.target.value));

// ---------------------------------------------------------------- chat

function appendChatMessage(role, text) {
  const log = $("chat-log");
  const div = document.createElement("div");
  div.className = `chat-msg ${role}`;
  div.textContent = text;
  log.appendChild(div);
  log.scrollTop = log.scrollHeight;
}

function appendToolCalls(calls) {
  if (!calls || calls.length === 0) return;
  const log = $("chat-log");
  for (const call of calls) {
    const div = document.createElement("div");
    div.className = "chat-msg tool";
    div.textContent = `→ ${call.name}(${JSON.stringify(call.arguments)})`;
    log.appendChild(div);
  }
  log.scrollTop = log.scrollHeight;
}

$("chat-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const input = $("chat-input");
  const message = input.value.trim();
  if (!message || !state.openaiEnabled) return;
  appendChatMessage("user", message);
  input.value = "";
  try {
    const result = await api("/api/chat", { method: "POST", body: JSON.stringify({ message }) });
    appendToolCalls(result.tool_calls);
    appendChatMessage("assistant", result.reply || "(no reply)");
    if (result.tool_calls?.length) await refreshWorkflowList(state.workflowId);
  } catch (err) { reportError(err); }
});

$("chat-reset-btn").addEventListener("click", async () => {
  try {
    await api("/api/chat/reset", { method: "POST" });
    $("chat-log").innerHTML = "";
    showToast("Conversation reset.");
  } catch (err) { reportError(err); }
});

async function loadChatConfig() {
  const config = await api("/api/config");
  state.openaiEnabled = config.openai_enabled;
  $("chat-disabled-note").classList.toggle("hidden", config.openai_enabled);
  $("chat-input").disabled = !config.openai_enabled;
  $("chat-form").querySelector("button[type=submit]").disabled = !config.openai_enabled;
}

// ---------------------------------------------------------------- add-ons

function renderAddonRow(container, addon, { installed }) {
  const li = document.createElement("li");
  const label = document.createElement("span");
  label.textContent = installed ? `${addon.name} (${addon.version})` : addon.name;
  const meta = document.createElement("span");
  meta.className = "meta";
  meta.textContent = addon.description || "";
  const btn = document.createElement("button");
  if (installed) {
    btn.textContent = "Uninstall";
    btn.className = "danger";
    btn.addEventListener("click", () => uninstallAddon(addon.name));
  } else {
    btn.textContent = addon.installed ? "Installed" : "Install";
    btn.disabled = !!addon.installed;
    btn.addEventListener("click", () => installAddon(addon.name));
  }
  li.append(label, meta, btn);
  container.appendChild(li);
}

async function loadInstalledAddons() {
  const list = await api("/api/addons/installed");
  const ul = $("installed-addons-list");
  ul.innerHTML = "";
  if (list.length === 0) {
    const li = document.createElement("li");
    li.textContent = "No Orange3 add-ons installed in this environment.";
    ul.appendChild(li);
    return;
  }
  for (const addon of list) renderAddonRow(ul, addon, { installed: true });
}

async function searchAddons(query) {
  const list = await api(`/api/addons/search?q=${encodeURIComponent(query)}`);
  const ul = $("addon-search-list");
  ul.innerHTML = "";
  for (const addon of list) renderAddonRow(ul, addon, { installed: false });
}

async function installAddon(name) {
  if (!confirm(`Install "${name}" into this server's Python environment via pip?`)) return;
  try {
    showToast(`Installing ${name}…`);
    await api("/api/addons/install", { method: "POST", body: JSON.stringify({ name }) });
    showToast(`Installed ${name}.`);
    await loadInstalledAddons();
    await searchAddons($("addon-search").value.trim());
  } catch (err) { reportError(err); }
}

async function uninstallAddon(name) {
  if (!confirm(`Uninstall "${name}" from this server's Python environment via pip?`)) return;
  try {
    showToast(`Uninstalling ${name}…`);
    await api("/api/addons/uninstall", { method: "POST", body: JSON.stringify({ name }) });
    showToast(`Uninstalled ${name}.`);
    await loadInstalledAddons();
    await searchAddons($("addon-search").value.trim());
  } catch (err) { reportError(err); }
}

$("addon-search-form").addEventListener("submit", (e) => {
  e.preventDefault();
  searchAddons($("addon-search").value.trim());
});

// ---------------------------------------------------------------- boot

async function boot() {
  initTabs();
  try {
    await loadWidgets();
    await refreshWorkflowList();
    await refreshSavedFiles();
    await loadChatConfig();
    await loadInstalledAddons();
    await searchAddons("");
  } catch (err) {
    reportError(err);
  }
}

boot();
