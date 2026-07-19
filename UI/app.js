// Knowledge Store Explorer frontend -----------------------------------------

const state = {
  bundles: [],
  registry: null,
  currentBundle: null,
  bundleData: null,
  concepts: [],
  graph: null,
  indexes: null,
  pages: {},
  activeTab: "overview",
  isAllDocuments: false,
  allDocumentsData: null,
  loading: false,
  qnaMode: false,
};

// Graph explorer instance (created by graph.js) and a dirty flag that
// triggers a (re)build the next time the graph tab is rendered.
let graphExplorer = null;
let graphDirty = true;

// DOM elements
const els = {
  docSelect: document.getElementById("doc-select"),
  docSelectTrigger: document.getElementById("doc-select-trigger"),
  docSelectValue: document.getElementById("doc-select-value"),
  docSelectList: document.getElementById("doc-select-list"),
  registryStats: document.getElementById("registry-stats"),
  emptyState: document.getElementById("empty-state"),
  documentView: document.getElementById("document-view"),
  docTitle: document.getElementById("doc-title"),
  docSubtitle: document.getElementById("doc-subtitle"),
  tabButtons: document.querySelectorAll(".tab-btn"),
  tabPanels: document.querySelectorAll(".tab-panel"),
  overviewStats: document.getElementById("overview-stats"),
  overviewMetadata: document.getElementById("overview-metadata"),
  conceptSearch: document.getElementById("concept-search"),
  conceptCount: document.getElementById("concept-count"),
  conceptGrid: document.getElementById("concept-grid"),
  graphContainer: document.getElementById("graph-container"),
  graphDetail: document.getElementById("graph-detail"),
  detailTitle: document.getElementById("detail-title"),
  detailBody: document.getElementById("detail-body"),
  detailClose: document.getElementById("detail-close"),
  pageCount: document.getElementById("page-count"),
  pageList: document.getElementById("page-list"),
  indexNav: document.getElementById("index-nav"),
  indexContent: document.getElementById("index-content"),
  conceptModal: document.getElementById("concept-modal"),
  conceptModalBody: document.getElementById("concept-modal-body"),
  modalClose: document.querySelector(".modal-close"),
  askPanel: document.getElementById("ask-panel"),
  askInput: document.getElementById("ask-input"),
  askBtn: document.getElementById("ask-btn"),
  askStatus: document.getElementById("ask-status"),
  askAnswer: document.getElementById("ask-answer"),
  askCitations: document.getElementById("ask-citations"),
};

// API helpers ---------------------------------------------------------------
async function api(path) {
  const res = await fetch(path);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ error: res.statusText }));
    throw new Error(err.error || res.statusText);
  }
  return res.json();
}

async function postJson(path, body) {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({ error: res.statusText }));
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
}

async function init() {
  try {
    const [{ bundles }, registry] = await Promise.all([
      api("/api/bundles"),
      api("/api/registry").catch(() => null),
    ]);
    state.bundles = bundles;
    state.registry = registry;
    renderDocSelect();
    renderRegistry();
    setupEventListeners();
  } catch (e) {
    els.registryStats.innerHTML = `<p class="error">Failed to load: ${escapeHtml(e.message)}</p>`;
    console.error(e);
  }
}

function setupEventListeners() {
  // Custom document dropdown
  els.docSelectTrigger.addEventListener("click", () => {
    toggleDocList();
  });

  els.docSelectTrigger.addEventListener("keydown", (e) => {
    const opts = docOptions();
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      if (!docListOpen) {
        openDocList();
        return;
      }
      const delta = e.key === "ArrowDown" ? 1 : -1;
      docHighlight = (docHighlight + delta + opts.length) % opts.length;
      applyDocHighlight();
    } else if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      if (!docListOpen) {
        openDocList();
        return;
      }
      if (docHighlight >= 0 && opts[docHighlight]) {
        chooseDoc(opts[docHighlight].value);
      }
    } else if (e.key === "Escape") {
      closeDocList();
    } else if (e.key === "Tab") {
      closeDocList();
    }
  });

  document.addEventListener("click", (e) => {
    if (docListOpen && !els.docSelect.contains(e.target)) {
      closeDocList();
    }
  });

  // Detail panel close button
  els.detailClose.addEventListener("click", () => {
    if (graphExplorer) graphExplorer.clearSelection();
    else hideGraphDetail();
  });

  // Tab buttons
  els.tabButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
      const tab = btn.dataset.tab;
      setActiveTab(tab);
    });
  });

  // Concept search
  els.conceptSearch.addEventListener("input", (e) => renderConcepts(e.target.value));

  // Modal close
  els.modalClose.addEventListener("click", () => els.conceptModal.classList.add("hidden"));
  els.conceptModal.addEventListener("click", (e) => {
    if (e.target === els.conceptModal) els.conceptModal.classList.add("hidden");
  });

  // Ask / QnA
  els.askBtn.addEventListener("click", submitQuestion);
  els.askInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submitQuestion();
    }
  });
}

// Custom document dropdown state
let docListOpen = false;
let docHighlight = -1;

function docOptions() {
  return [
    { value: "__all__", label: "All documents" },
    ...state.bundles.map((b) => ({ value: b.id, label: b.title })),
  ];
}

function renderDocSelect() {
  els.docSelectList.innerHTML = "";
  docOptions().forEach((opt, idx) => {
    const li = document.createElement("li");
    li.className = "custom-select-item";
    li.id = `doc-opt-${idx}`;
    li.dataset.value = opt.value;
    li.textContent = opt.label;
    li.setAttribute("role", "option");
    li.addEventListener("click", () => chooseDoc(opt.value));
    els.docSelectList.appendChild(li);
  });
  syncDocSelectUI();
}

function syncDocSelectUI() {
  const selected = docOptions().find((o) => o.value === state.currentBundle);
  els.docSelectValue.textContent = selected ? selected.label : "Choose a document…";
  els.docSelectValue.classList.toggle("placeholder", !selected);
  els.docSelectList.querySelectorAll(".custom-select-item").forEach((li) => {
    const isSelected = li.dataset.value === state.currentBundle;
    li.classList.toggle("selected", isSelected);
    li.setAttribute("aria-selected", isSelected ? "true" : "false");
  });
}

function openDocList() {
  if (docListOpen) return;
  docListOpen = true;
  els.docSelect.classList.add("open");
  els.docSelectTrigger.setAttribute("aria-expanded", "true");
  const opts = docOptions();
  docHighlight = Math.max(0, opts.findIndex((o) => o.value === state.currentBundle));
  if (docHighlight < 0) docHighlight = 0;
  applyDocHighlight();
}

function closeDocList() {
  if (!docListOpen) return;
  docListOpen = false;
  els.docSelect.classList.remove("open");
  els.docSelectTrigger.setAttribute("aria-expanded", "false");
  docHighlight = -1;
  applyDocHighlight();
}

function toggleDocList() {
  if (docListOpen) closeDocList();
  else openDocList();
}

function applyDocHighlight() {
  const items = els.docSelectList.querySelectorAll(".custom-select-item");
  items.forEach((li, idx) => {
    li.classList.toggle("highlighted", idx === docHighlight);
  });
  if (docHighlight >= 0 && items[docHighlight]) {
    items[docHighlight].scrollIntoView({ block: "nearest" });
  }
}

function chooseDoc(value) {
  closeDocList();
  if (!value || value === state.currentBundle) return;
  if (value === "__all__") selectAllDocuments();
  else selectBundle(value);
  syncDocSelectUI();
}

function renderRegistry() {
  if (!state.registry) {
    els.registryStats.innerHTML = "<p class='muted'>Registry unavailable</p>";
    return;
  }
  const stats = [
    { key: "documents", label: "Docs" },
    { key: "concepts", label: "Concepts" },
    { key: "relationships", label: "Relations" },
    { key: "pages", label: "Pages" },
  ];
  els.registryStats.innerHTML = stats
    .map(
      (s) => `
      <div class="stat-pill">
        <span class="value">${state.registry[s.key] ?? "-"}</span>
        <span class="label">${s.label}</span>
      </div>`
    )
    .join("");
}

let bundleLoadToken = 0;
let pagesRenderToken = 0;

async function selectBundle(bundleId) {
  const token = ++bundleLoadToken;
  state.currentBundle = bundleId;
  state.isAllDocuments = false;
  state.allDocumentsData = null;
  state.loading = true;
  
  els.emptyState.classList.add("hidden");
  els.documentView.classList.remove("hidden");
  hideGraphDetail();
  teardownGraph();

  try {
    const [bundleData, conceptsData, graph, indexesData] = await Promise.all([
      api(`/api/bundle/${bundleId}`),
      api(`/api/bundle/${bundleId}/concepts`),
      api(`/api/bundle/${bundleId}/graph`),
      api(`/api/bundle/${bundleId}/indexes`),
    ]);

    if (token !== bundleLoadToken) return;

    state.bundleData = bundleData;
    state.concepts = conceptsData.concepts.sort((a, b) => a.name.localeCompare(b.name));
    state.graph = graph;
    state.indexes = indexesData.indexes;
    state.pages = {};
    state.loading = false;

    renderOverview();
    renderConcepts();
    renderGraph();
    renderPages();
    renderIndexes();
    updateTabVisibility();
  } catch (e) {
    if (token !== bundleLoadToken) return;
    state.loading = false;
    alert("Failed to load bundle: " + e.message);
    console.error(e);
  }
}

async function selectAllDocuments() {
  const token = ++bundleLoadToken;
  state.currentBundle = "__all__";
  state.isAllDocuments = true;
  state.loading = true;
  
  els.emptyState.classList.add("hidden");
  els.documentView.classList.remove("hidden");
  hideGraphDetail();
  teardownGraph();

  try {
    const data = await api("/api/graph/all");

    if (token !== bundleLoadToken) return;

    state.allDocumentsData = data;
    state.concepts = data.concepts.sort((a, b) => a.name.localeCompare(b.name));
    
    // Transform merged graph data to match expected format
    state.graph = {
      nodes: data.nodes.map(n => n.id),
      edges: data.edges,
      nodeData: data.nodes, // Keep full node data with doc info
    };
    
    // Create a pseudo bundle data for overview
    state.bundleData = {
      document: {
        id: "__all__",
        title: "All Documents",
        file_name: `${data.documents.length} documents merged`,
        pages_total: data.documents.reduce((sum, d) => sum + (d.nodes || 0), 0),
        pages_extracted: data.nodes.length,
        concepts_count: data.concepts.length,
        relationships_count: data.edges.length,
        dropped_pages: [],
        version: 1,
        generated_at: new Date().toISOString(),
      },
      metadata: {
        documents: data.documents,
        merged: true,
      },
    };
    
    state.indexes = null;
    state.pages = {};
    state.loading = false;

    renderOverview();
    renderConcepts();
    renderGraph();
    renderPages();
    renderIndexes();
    updateTabVisibility();
  } catch (e) {
    if (token !== bundleLoadToken) return;
    state.loading = false;
    alert("Failed to load all documents: " + e.message);
    console.error(e);
  }
}

// Tabs ----------------------------------------------------------------------
function setActiveTab(tab) {
  state.activeTab = tab;
  els.tabButtons.forEach((btn) => btn.classList.toggle("active", btn.dataset.tab === tab));

  if (tab === "ask") {
    // Ask reuses the graph view: show the graph panel but swap the side panel.
    els.tabPanels.forEach((panel) => panel.classList.toggle("active", panel.id === "tab-graph"));
    els.graphDetail.classList.add("hidden");
    els.askPanel.classList.remove("hidden");
    state.qnaMode = true;
    if (graphExplorer) graphExplorer.setQnaMode(true);
    if (state.graph) requestAnimationFrame(() => renderGraph());
    return;
  }

  // Leaving Ask mode: restore normal graph interactions and reset highlights.
  if (state.qnaMode) {
    state.qnaMode = false;
    if (graphExplorer) {
      graphExplorer.setQnaMode(false);
      graphExplorer.clearQna();
    }
    els.askPanel.classList.add("hidden");
    resetAskPanel();
  }

  els.tabPanels.forEach((panel) => panel.classList.toggle("active", panel.id === `tab-${tab}`));
  if (tab === "graph" && state.graph) {
    // Defer to next frame so container has dimensions
    requestAnimationFrame(() => renderGraph());
  }
}

function updateTabVisibility() {
  const pagesBtn = document.querySelector('.tab-btn[data-tab="pages"]');
  if (!pagesBtn) return;
  if (state.isAllDocuments) {
    pagesBtn.classList.add("hidden");
    // If pages tab is currently active, redirect to overview
    if (state.activeTab === "pages") setActiveTab("overview");
  } else {
    pagesBtn.classList.remove("hidden");
  }
}

// Overview ------------------------------------------------------------------
function renderOverview() {
  const doc = state.bundleData.document;
  const meta = state.bundleData.metadata;

  els.docTitle.textContent = doc.title || doc.id;
  els.docSubtitle.textContent = state.isAllDocuments 
    ? `Merged view of ${meta.documents?.length || 0} documents`
    : `ID: ${doc.id} • File: ${doc.file_name || "-"}`;

  const stats = [
    { label: "Total Pages", value: doc.pages_total },
    { label: "Extracted Pages", value: doc.pages_extracted },
    { label: "Concepts", value: doc.concepts_count },
    { label: "Relationships", value: doc.relationships_count },
    { label: "Dropped Pages", value: doc.dropped_pages?.length || 0 },
    { label: "Version", value: doc.version || 1 },
  ];

  els.overviewStats.innerHTML = stats
    .map(
      (s) => `
      <div class="stat-card">
        <div class="value">${s.value ?? 0}</div>
        <div class="label">${s.label}</div>
      </div>`
    )
    .join("");

  const dropped = doc.dropped_pages?.length
    ? doc.dropped_pages.join(", ")
    : "None";

  if (state.isAllDocuments) {
    // Show documents list for merged view
    els.overviewMetadata.innerHTML = `
      <h3>Merged Documents</h3>
      <div class="meta-row"><span class="key">Total Documents</span><span>${meta.documents?.length || 0}</span></div>
      <div class="meta-row"><span class="key">Total Concepts</span><span>${doc.concepts_count}</span></div>
      <div class="meta-row"><span class="key">Total Relationships</span><span>${doc.relationships_count}</span></div>
      <h3 style="margin-top: 20px;">Documents</h3>
      <ul class="compact">
        ${(meta.documents || []).map(d => `<li><strong>${escapeHtml(d.title)}</strong> — ${d.nodes} nodes</li>`).join("")}
      </ul>
    `;
  } else {
    els.overviewMetadata.innerHTML = `
      <h3>Metadata</h3>
      <div class="meta-row"><span class="key">Generated</span><span>${formatDate(doc.generated_at)}</span></div>
      <div class="meta-row"><span class="key">Document ID</span><span>${doc.id}</span></div>
      <div class="meta-row"><span class="key">Dropped pages</span><span>${dropped}</span></div>
      <div class="meta-row"><span class="key">Append metadata</span><span>${JSON.stringify(doc.append_metadata || meta.append_metadata || {})}</span></div>
      <pre>${JSON.stringify(meta, null, 2)}</pre>
    `;
  }
}

// Concepts ------------------------------------------------------------------
function renderConcepts(filter = "") {
  const term = filter.toLowerCase();
  const filtered = state.concepts.filter(
    (c) =>
      c.name.toLowerCase().includes(term) ||
      (c.description || "").toLowerCase().includes(term) ||
      (c.keywords || []).some((k) => k.toLowerCase().includes(term))
  );

  els.conceptCount.textContent = `${filtered.length} of ${state.concepts.length}`;
  els.conceptGrid.innerHTML = "";

  if (!filtered.length) {
    els.conceptGrid.innerHTML = `<p class="muted">No concepts match "${escapeHtml(filter)}".</p>`;
    return;
  }

  filtered.forEach((concept) => {
    const card = document.createElement("div");
    card.className = "concept-card";
    const docBadge = state.isAllDocuments && concept.doc 
      ? `<span class="tag doc-tag">${escapeHtml(concept.doc)}</span>` 
      : "";
    card.innerHTML = `
      <h3>${escapeHtml(concept.name)}</h3>
      <p>${escapeHtml(truncate(concept.description || "", 140))}</p>
      <div class="tags">
        ${docBadge}
        ${(concept.keywords || [])
          .slice(0, 4)
          .map((k) => `<span class="tag">${escapeHtml(k)}</span>`)
          .join("")}
      </div>
    `;
    card.addEventListener("click", () => showConceptModal(concept));
    els.conceptGrid.appendChild(card);
  });
}

function showConceptModal(concept) {
  const related = (state.graph?.edges || [])
    .filter((e) => e.source === concept.id || e.target === concept.id)
    .map((e) => {
      const otherId = e.source === concept.id ? e.target : e.source;
      const other = state.concepts.find((c) => c.id === otherId);
      return { edge: e, other, otherId };
    });

  const docInfo = state.isAllDocuments && concept.doc 
    ? `<p><strong>Document:</strong> ${escapeHtml(concept.doc)}</p>` 
    : "";

  els.conceptModalBody.innerHTML = `
    <h2>${escapeHtml(concept.name)}</h2>
    <p><strong>ID:</strong> ${escapeHtml(concept.id)}</p>
    ${docInfo}
    <p>${escapeHtml(concept.description || "")}</p>
    <h3>Pages</h3>
    <p>${(concept.page_numbers || []).join(", ") || "-"}</p>
    ${renderListSection("Aliases", concept.aliases)}
    ${renderListSection("Keywords", concept.keywords)}
    <h3>Related concepts</h3>
    ${related.length ? "<ul class=\"compact\">" + related.map((r) => {
      const name = r.other ? r.other.name : r.otherId;
      return `<li><strong>${escapeHtml(name)}</strong> <em>(${r.edge.type})</em> — page ${(r.edge.page_numbers || []).join(", ")}</li>`;
    }).join("") + "</ul>" : "<p>None</p>"}
  `;
  els.conceptModal.classList.remove("hidden");
}

function renderListSection(title, items) {
  if (!items || !items.length) return "";
  return `
    <h3>${title}</h3>
    <ul class="compact">
      ${items.map((i) => `<li>${escapeHtml(i)}</li>`).join("")}
    </ul>
  `;
}

// ==========================================================================
// GRAPH (2D/3D force-directed explorer — rendering lives in graph.js)
// ==========================================================================

/** Translate the loaded bundle data into the graph module's data model. */
function buildGraphData() {
  let rawNodes;
  let rawEdges;
  if (state.isAllDocuments && state.graph.nodeData) {
    rawNodes = state.graph.nodeData;
    rawEdges = state.graph.edges;
  } else {
    rawNodes = state.graph.nodes.map((id) => ({ id }));
    rawEdges = state.graph.edges;
  }

  const nodes = rawNodes.map((nd) => {
    const concept = state.concepts.find((c) => c.id === nd.id) || null;
    return {
      id: nd.id,
      label: concept ? concept.name : nd.id,
      concept,
      doc: nd.doc || null,
    };
  });

  const links = rawEdges.map((e) => ({
    source: e.source,
    target: e.target,
    type: e.type,
    weight: Math.max(1, (e.page_numbers || []).length || 1),
    page_numbers: e.page_numbers || [],
    doc: e.doc || null,
  }));

  return { nodes, links };
}

function docTitleMap() {
  const docs = state.bundleData?.metadata?.documents || [];
  const map = {};
  docs.forEach((d) => {
    map[d.id] = d.title;
  });
  return map;
}

/** Destroy the current graph explorer and mark it for rebuild. */
function teardownGraph() {
  if (graphExplorer) {
    graphExplorer.destroy();
    graphExplorer = null;
  }
  graphDirty = true;
}

function renderGraph() {
  if (state.loading) return; // document switch in flight — rendered on completion
  const container = els.graphContainer;
  if (!state.graph || !state.graph.nodes?.length) {
    teardownGraph();
    container.innerHTML = '<p class="muted">No graph data available.</p>';
    return;
  }
  if (!graphDirty && graphExplorer) {
    // Same data, e.g. re-entering the tab — just re-measure.
    graphExplorer.refresh();
    return;
  }
  if (!container.clientWidth || !container.clientHeight) {
    // Tab hidden — setActiveTab() re-triggers once it becomes visible.
    return;
  }
  teardownGraph();
  container.innerHTML = "";

  const { nodes, links } = buildGraphData();
  graphExplorer = createKnowledgeGraph(container, {
    nodes,
    links,
    concepts: state.concepts,
    isAllDocuments: state.isAllDocuments,
    docTitles: docTitleMap(),
    qnaMode: state.qnaMode,
    detail: {
      panel: els.graphDetail,
      title: els.detailTitle,
      body: els.detailBody,
    },
  });
  graphDirty = false;
}

function hideGraphDetail() {
  els.graphDetail.classList.add("hidden");
}

// Pages ----------------------------------------------------------------------
async function renderPages() {
  const token = ++pagesRenderToken;
  const bundleId = state.currentBundle;
  const doc = state.bundleData.document;
  
  if (state.isAllDocuments) {
    els.pageCount.textContent = "Pages not available in merged view";
    els.pageList.innerHTML = "<p class='muted'>Select a specific document to view its pages.</p>";
    return;
  }
  
  const total = doc.pages_total || 0;
  els.pageCount.textContent = `${total} pages`;
  els.pageList.innerHTML = "";

  for (let i = 1; i <= total; i++) {
    if (token !== pagesRenderToken) return;

    let card = document.createElement("div");
    card.className = "page-card";

    try {
      const page = await api(`/api/bundle/${bundleId}/page/${i}`);
      if (token !== pagesRenderToken) return;
      state.pages[i] = page;

      let content = "";
      if (typeof page === "string") {
        content = page;
      } else if (page && typeof page.content === "string") {
        content = page.content;
      } else {
        content = JSON.stringify(page, null, 2);
      }

      if (content.trim()) {
        card.innerHTML = `
          <h3>Page ${i}</h3>
          <pre>${escapeHtml(content)}</pre>
        `;
      } else {
        card.innerHTML = `<h3>Page ${i}</h3><p class="muted">No content available.</p>`;
      }
    } catch (e) {
      if (token !== pagesRenderToken) return;
      card.innerHTML = `<h3>Page ${i}</h3><p class="muted">No content available.</p>`;
    }

    els.pageList.appendChild(card);
  }
}

// Indexes --------------------------------------------------------------------
function renderIndexes(indexName = null) {
  if (state.isAllDocuments) {
    els.indexNav.innerHTML = "";
    els.indexContent.innerHTML = "<p class='muted'>Indexes not available in merged view. Select a specific document.</p>";
    return;
  }
  
  if (!state.indexes || !Object.keys(state.indexes).length) {
    els.indexNav.innerHTML = "";
    els.indexContent.innerHTML = "<p class=\"muted\">No indexes available.</p>";
    return;
  }

  const names = Object.keys(state.indexes);
  const active = indexName || names[0];

  els.indexNav.innerHTML = names
    .map(
      (name) =>
        `<button class="${name === active ? "active" : ""}" data-index="${escapeHtml(name)}">${
          name.replace(/_/g, " ")
        }</button>`
    )
    .join("");

  els.indexNav.querySelectorAll("button").forEach((btn) => {
    btn.addEventListener("click", () => renderIndexes(btn.dataset.index));
  });

  const data = state.indexes[active];
  els.indexContent.innerHTML = renderIndexTable(active, data);
}

function renderIndexTable(name, data) {
  if (Array.isArray(data)) {
    return `
      <table class="index-table">
        <tbody>
          ${data.map((item) => `<tr><td>${escapeHtml(String(item))}</td></tr>`).join("")}
        </tbody>
      </table>`;
  }
  if (typeof data === "object") {
    const entries = Object.entries(data);
    return `
      <table class="index-table">
        <thead><tr><th>Key</th><th>Value(s)</th></tr></thead>
        <tbody>
          ${entries
            .map(
              ([key, value]) => `
              <tr>
                <td>${escapeHtml(key)}</td>
                <td>${renderIndexValue(value)}</td>
              </tr>`
            )
            .join("")}
        </tbody>
      </table>`;
  }
  return `<pre>${escapeHtml(JSON.stringify(data, null, 2))}</pre>`;
}

function renderIndexValue(value) {
  if (Array.isArray(value)) {
    return `<ul class="compact"><li>${value.map((v) => escapeHtml(String(v))).join("</li><li>")}</li></ul>`;
  }
  return escapeHtml(String(value));
}

// Ask / QnA ------------------------------------------------------------------
function getQueryWords(query) {
  return query
    .toLowerCase()
    .split(/[^a-z0-9]+/)
    .filter((w) => w.length > 2);
}

function findSearchNodeIds(query) {
  const words = getQueryWords(query);
  if (!words.length || !state.graph) return [];
  const ids = new Set();
  state.concepts.forEach((c) => {
    const hay = `${c.name || ""} ${(c.keywords || []).join(" ")} ${c.description || ""}`.toLowerCase();
    if (words.some((w) => hay.includes(w))) ids.add(c.id);
  });
  return Array.from(ids);
}

function formatAnswer(text) {
  return text
    .split(/\n\n+/)
    .map((p) => `<p>${escapeHtml(p).replace(/\n/g, "<br>")}</p>`)
    .join("");
}

function renderCitations(citations) {
  if (!citations || !citations.length) return "";
  const items = citations.map(
    (c) => `
      <li>
        <strong>${escapeHtml(c.document_id)}</strong> — page ${c.page_number}
        <span class="muted">(${c.concepts?.length || 0} concept${c.concepts?.length === 1 ? "" : "s"})</span>
      </li>`
  );
  return `<h4>Citations</h4><ul>${items.join("")}</ul>`;
}

async function submitQuestion() {
  const query = els.askInput.value.trim();
  if (!query) {
    showAskStatus("Please enter a question.", true);
    return;
  }

  const scope = state.isAllDocuments ? "all" : [state.currentBundle];

  els.askAnswer.classList.add("hidden");
  els.askCitations.classList.add("hidden");
  showAskStatus("Searching graph…");
  setAskLoading(true);

  const searchIds = findSearchNodeIds(query);
  if (graphExplorer) graphExplorer.startSearch(searchIds);

  try {
    const result = await postJson("/api/ask", { query, scope });
    if (graphExplorer) graphExplorer.stopSearch();

    if (result.concepts_used && result.concepts_used.length && graphExplorer) {
      graphExplorer.highlightAnswer(result.concepts_used);
    }

    els.askAnswer.innerHTML = formatAnswer(result.answer || "No answer returned.");
    els.askAnswer.classList.remove("hidden");
    els.askCitations.innerHTML = renderCitations(result.citations);
    els.askCitations.classList.toggle("hidden", !result.citations?.length);
    showAskStatus("");
  } catch (e) {
    if (graphExplorer) graphExplorer.stopSearch();
    showAskStatus("Failed to get answer: " + e.message, true);
  } finally {
    setAskLoading(false);
  }
}

function showAskStatus(message, isError = false) {
  if (!message) {
    els.askStatus.classList.add("hidden");
    return;
  }
  els.askStatus.textContent = message;
  els.askStatus.classList.toggle("error", isError);
  els.askStatus.classList.remove("hidden");
}

function resetAskPanel() {
  showAskStatus("");
  els.askAnswer.innerHTML = "";
  els.askAnswer.classList.add("hidden");
  els.askCitations.innerHTML = "";
  els.askCitations.classList.add("hidden");
}

function setAskLoading(loading) {
  els.askInput.disabled = loading;
  els.askBtn.disabled = loading;
}

// Utilities -----------------------------------------------------------------
function escapeHtml(text) {
  if (text == null) return "";
  return String(text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function truncate(text, max) {
  if (!text) return "";
  return text.length > max ? text.slice(0, max) + "…" : text;
}

function formatDate(iso) {
  if (!iso) return "-";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

// Start ----------------------------------------------------------------------
init();
