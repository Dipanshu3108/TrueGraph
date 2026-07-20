/**
 * Knowledge graph explorer orchestrator.
 *
 * Delegates rendering to either the 3D force-graph renderer (graph-3d.js)
 * or the 2D vis-network renderer (graph-2d.js). Both renderers share the
 * same data model and interaction state defined in graph-shared.js.
 */
(function () {
  "use strict";

  var Shared = window.GraphShared;
  var S = window.GRAPH_SHARED;

  function escapeHtml(text) { return Shared.escapeHtml(text); }
  function idOf(endpoint) { return Shared.idOf(endpoint); }

  function createKnowledgeGraph(container, options) {
    var opts = options || {};
    var detail = opts.detail || {};
    var model = Shared.buildModel(opts.nodes || [], opts.links || [], opts);
    var nodeById = new Map(model.nodes.map(function (n) { return [n.id, n]; }));
    var conceptById = new Map((opts.concepts || []).map(function (c) { return [c.id, c]; }));

    // Shared interaction state
    var mode = "3d";
    var renderer = null;
    var selectedId = null;
    var highlightNodes = new Set();
    var highlightLinks = new Set();
    var hiddenClusters = new Set();
    var searchTerm = "";
    var labelsVisible = true;
    var destroyed = false;

    // QnA state
    var qnaMode = opts.qnaMode || false;
    var searchNodes = new Set();
    var answerNodes = new Set();
    var searchPulse = 0;
    var answerPulse = 0;
    var searchRAF = null;
    var answerRAF = null;

    // Context object passed to renderers
    var ctx = {
      model: model,
      nodeById: nodeById,
      conceptById: conceptById,
      selectedId: selectedId,
      highlightNodes: highlightNodes,
      highlightLinks: highlightLinks,
      hiddenClusters: hiddenClusters,
      searchTerm: searchTerm,
      labelsVisible: labelsVisible,
      qnaMode: qnaMode,
      searchNodes: searchNodes,
      answerNodes: answerNodes,
      searchPulse: searchPulse,
      answerPulse: answerPulse,
      onNodeClick: onNodeClick,
      onBackgroundClick: clearSelection,
    };

    // ---- DOM scaffold -------------------------------------------------
    container.innerHTML = "";
    container.classList.add("kg-explorer");

    var toolbar = document.createElement("div");
    toolbar.className = "graph-toolbar";
    toolbar.innerHTML =
      '<button type="button" class="kg-view-toggle" title="Switch between 3D and 2D rendering">Switch to 2D</button>' +
      '<button type="button" class="kg-fit" title="Fit graph to view">Fit</button>' +
      '<button type="button" class="kg-labels active" title="Toggle node labels">Labels</button>' +
      '<button type="button" class="kg-reheat" title="Reset layout and fit to view">Reset</button>' +
      '<input type="text" class="kg-search" placeholder="Find concept…" />' +
      '<span class="graph-stats kg-stats"></span>' +
      '<span class="graph-hint kg-hint"></span>';
    container.appendChild(toolbar);

    var legend = document.createElement("div");
    legend.className = "graph-legend";
    container.appendChild(legend);

    var stage = document.createElement("div");
    stage.className = "graph-stage";
    container.appendChild(stage);

    var ui = {
      viewToggle: toolbar.querySelector(".kg-view-toggle"),
      fit: toolbar.querySelector(".kg-fit"),
      labels: toolbar.querySelector(".kg-labels"),
      reheat: toolbar.querySelector(".kg-reheat"),
      search: toolbar.querySelector(".kg-search"),
      stats: toolbar.querySelector(".kg-stats"),
      hint: toolbar.querySelector(".kg-hint"),
    };

    // ---- Detail panel -------------------------------------------------
    function showDetail(node) {
      if (!detail.panel) return;
      var concept = conceptById.get(node.id);
      var connections = (model.linksOf.get(node.id) || []).map(function (l) {
        var otherId = idOf(l.source) === node.id ? idOf(l.target) : idOf(l.source);
        var otherNode = nodeById.get(otherId);
        return {
          name: otherNode ? otherNode.label : otherId,
          type: l.type,
          pages: (l.page_numbers || []).join(", ") || "-",
        };
      });

      if (detail.title) detail.title.textContent = node.label;
      if (detail.body) {
        var docRow = node.doc
          ? "<p><strong>Document:</strong> " + escapeHtml(node.doc) + "</p>"
          : "";
        detail.body.innerHTML =
          '<div class="node-id">' + escapeHtml(node.id) + "</div>" +
          docRow +
          '<p><strong>Degree:</strong> ' + node.degree + '</p>' +
          '<p><strong>Cluster:</strong> ' + escapeHtml(node.clusterName || "Unconnected") + "</p>" +
          "<p>" + escapeHtml((concept && concept.description) || "No description available.") + "</p>" +
          "<h4>Pages</h4>" +
          "<p>" + ((concept && concept.page_numbers || []).join(", ") || "-") + "</p>" +
          '<div class="connection-badge"><span>' + connections.length + "</span><span>connection" +
          (connections.length !== 1 ? "s" : "") + "</span></div>" +
          "<h4>Connected Concepts</h4>" +
          '<div class="connection-list">' +
          (connections.length
            ? connections.map(function (c) {
                return (
                  '<div class="connection-item"><strong>' + escapeHtml(c.name) + "</strong>" +
                  "<span>" + escapeHtml(c.type) + " — page " + escapeHtml(c.pages) + "</span></div>"
                );
              }).join("")
            : '<div class="connection-item"><span>No connections</span></div>') +
          "</div>";
      }
      detail.panel.classList.remove("hidden");
    }

    function hideDetail() {
      if (detail.panel) detail.panel.classList.add("hidden");
    }

    // ---- Selection / highlight ----------------------------------------
    function updateSelection(id) {
      selectedId = id;
      ctx.selectedId = id;
      highlightNodes = new Set();
      highlightLinks = new Set();
      if (id) {
        highlightNodes.add(id);
        (model.neighbors.get(id) || new Set()).forEach(function (nb) { highlightNodes.add(nb); });
        (model.linksOf.get(id) || []).forEach(function (l) { highlightLinks.add(l); });
      }
      ctx.highlightNodes = highlightNodes;
      ctx.highlightLinks = highlightLinks;
      if (renderer) renderer.repaint();
    }

    function onNodeClick(node) {
      if (!node) return;
      if (selectedId === node.id) {
        clearSelection();
        return;
      }
      updateSelection(node.id);
      showDetail(node);
    }

    function clearSelection() {
      updateSelection(null);
      hideDetail();
    }

    // ---- QnA / pulses ---------------------------------------------------
    function tickSearch() {
      if (!searchNodes.size) return;
      searchPulse += 0.08;
      ctx.searchPulse = searchPulse;
      if (renderer) renderer.repaint();
      searchRAF = requestAnimationFrame(tickSearch);
    }

    function tickAnswer() {
      if (!answerNodes.size) return;
      answerPulse += 0.05;
      ctx.answerPulse = answerPulse;
      if (renderer) renderer.repaint();
      answerRAF = requestAnimationFrame(tickAnswer);
    }

    function stopSearch() {
      if (searchRAF) { cancelAnimationFrame(searchRAF); searchRAF = null; }
      searchNodes.clear();
      ctx.searchNodes = searchNodes;
      if (renderer) renderer.repaint();
    }

    function stopAnswerPulse() {
      if (answerRAF) { cancelAnimationFrame(answerRAF); answerRAF = null; }
    }

    function clearQna() {
      stopSearch();
      stopAnswerPulse();
      answerNodes.clear();
      ctx.answerNodes = answerNodes;
      if (renderer) renderer.repaint();
    }

    function startSearch(ids) {
      stopSearch();
      stopAnswerPulse();
      ids.forEach(function (id) { searchNodes.add(id); });
      ctx.searchNodes = searchNodes;
      if (searchNodes.size) {
        searchPulse = 0;
        ctx.searchPulse = searchPulse;
        searchRAF = requestAnimationFrame(tickSearch);
      }
      if (renderer) renderer.repaint();
    }

    function highlightAnswer(ids) {
      stopSearch();
      answerNodes.clear();
      ids.forEach(function (id) {
        var rawId = typeof id === "object" && id !== null ? id.id : id;
        if (rawId && nodeById.has(rawId)) answerNodes.add(rawId);
      });
      ctx.answerNodes = answerNodes;
      if (answerNodes.size) {
        answerPulse = 0;
        ctx.answerPulse = answerPulse;
        answerRAF = requestAnimationFrame(tickAnswer);
      }
      if (renderer) renderer.repaint();
    }

    function setQnaMode(enabled) {
      qnaMode = !!enabled;
      ctx.qnaMode = qnaMode;
      if (qnaMode) {
        clearSelection();
        clearQna();
      }
      updateHint();
      if (renderer) renderer.setQnaMode(qnaMode);
    }

    // ---- Filtering ------------------------------------------------------
    function visibleData() {
      var nodes = model.nodes.filter(function (n) { return !hiddenClusters.has(n.cluster); });
      var ids = new Set(nodes.map(function (n) { return n.id; }));
      var links = model.links.filter(function (l) {
        return ids.has(idOf(l.source)) && ids.has(idOf(l.target));
      });
      return { nodes: nodes, links: links };
    }

    function updateStats() {
      var data = visibleData();
      ui.stats.textContent =
        data.nodes.length + "/" + model.nodes.length + " nodes · " +
        data.links.length + " links · " +
        model.clusters.list.length + " components";
    }

    function applyFilter() {
      if (selectedId && hiddenClusters.has((model.nodes.find(function (n) { return n.id === selectedId; }) || {}).cluster)) {
        clearSelection();
      }
      if (renderer) renderer.applyFilter();
      updateStats();
    }

    // ---- Legend ---------------------------------------------------------
    function renderLegend() {
      legend.innerHTML = "";
      if (mode === "2d") {
        legend.style.display = "none";
        return;
      }
      legend.style.display = "none";
    }

    // ---- Renderers ------------------------------------------------------
    function teardownRenderer() {
      if (renderer) {
        renderer.teardown();
        renderer = null;
      }
    }

    function mount(newMode) {
      teardownRenderer();
      mode = newMode;
      stage.innerHTML = "";
      stage.style.cursor = "default";

      renderer = mode === "3d" ? window.Graph3D.create(stage, ctx) : window.Graph2D.create(stage, ctx);
      renderer.mount();

      ui.viewToggle.textContent = mode === "3d" ? "Switch to 2D" : "Switch to 3D";
      updateHint();
      if (renderer) renderer.setQnaMode(qnaMode);
      renderLegend();
      updateStats();
    }

    function updateHint() {
      if (qnaMode) {
        ui.hint.textContent = "Hover nodes for names · Scroll to zoom · Drag to orbit";
      } else {
        ui.hint.textContent = mode === "3d"
          ? "Click node for details · Scroll to zoom · Drag to orbit"
          : "Click node for details · Scroll to zoom · Drag nodes";
      }
    }

    function refresh() {
      if (renderer) renderer.refresh();
    }

    function focusNode(node) {
      if (renderer) renderer.focusNode(node);
    }

    function fitView() {
      if (renderer) renderer.fitView();
    }

    // ---- Toolbar events -------------------------------------------------
    ui.viewToggle.addEventListener("click", function () {
      mount(mode === "3d" ? "2d" : "3d");
    });

    ui.fit.addEventListener("click", fitView);

    ui.labels.addEventListener("click", function () {
      labelsVisible = !labelsVisible;
      ctx.labelsVisible = labelsVisible;
      ui.labels.classList.toggle("active", labelsVisible);
      if (renderer) renderer.repaint();
    });

    ui.reheat.addEventListener("click", function () {
      if (renderer && renderer.reset) renderer.reset();
      else if (renderer && renderer.reheat) renderer.reheat();
    });

    ui.search.addEventListener("input", function () {
      searchTerm = ui.search.value.trim();
      ctx.searchTerm = searchTerm;
      if (searchTerm && selectedId) clearSelection();
      if (renderer) renderer.repaint();
    });

    ui.search.addEventListener("keydown", function (e) {
      if (e.key !== "Enter" || !searchTerm) return;
      var term = searchTerm.toLowerCase();
      var match = model.nodes.find(function (n) {
        return n.label.toLowerCase().indexOf(term) !== -1;
      });
      if (match) {
        updateSelection(match.id);
        showDetail(match);
        focusNode(match);
      }
    });

    function onKeydown(e) {
      if (e.key === "Escape") {
        ui.search.value = "";
        searchTerm = "";
        ctx.searchTerm = "";
        clearSelection();
      }
    }
    document.addEventListener("keydown", onKeydown);

    // ---- Resize ---------------------------------------------------------
    var resizeObserver = null;
    if (typeof ResizeObserver !== "undefined") {
      resizeObserver = new ResizeObserver(function () { refresh(); });
      resizeObserver.observe(stage);
    }

    // ---- Init ------------------------------------------------------------
    if (!model.nodes.length) {
      stage.innerHTML = '<p class="muted">No graph data available.</p>';
      ui.stats.textContent = "0 nodes";
    } else {
      mount("3d");
    }
    renderLegend();
    updateStats();

    // ---- Public API -----------------------------------------------------
    function destroy() {
      destroyed = true;
      document.removeEventListener("keydown", onKeydown);
      if (resizeObserver) resizeObserver.disconnect();
      teardownRenderer();
      hideDetail();
      container.innerHTML = "";
      container.classList.remove("kg-explorer");
    }

    return {
      destroy: destroy,
      clearSelection: clearSelection,
      refresh: refresh,
      getMode: function () { return mode; },
      instance: function () { return renderer ? (renderer.instance ? renderer.instance() : null) : null; },
      setQnaMode: setQnaMode,
      startSearch: startSearch,
      stopSearch: stopSearch,
      highlightAnswer: highlightAnswer,
      clearQna: clearQna,
    };
  }

  window.createKnowledgeGraph = createKnowledgeGraph;
})();
