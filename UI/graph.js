/**
 * Interactive knowledge graph explorer.
 *
 * A self-contained module that renders a force-directed knowledge graph in
 * either 3D (WebGL, via 3d-force-graph / three.js) or 2D (canvas, via
 * force-graph). Both views share the same data model and the same force
 * configuration.
 *
 * Visual encoding: color = degree-based gradient, node size = degree,
 * edge thickness = relationship weight.
 *
 * Interactions: drag nodes, zoom/pan/orbit, click to highlight a node's
 * neighborhood (dimming the rest), search by label, 3D <-> 2D toggle.
 */
(function () {
  "use strict";

  // ---------------------------------------------------------------------
  // Constants
  // ---------------------------------------------------------------------

  // Expanded vibrant color palette for individual nodes
  var PALETTE = [
    "#FF6B6B", "#4ECDC4", "#45B7D1", "#96CEB4", "#FFEAA7",
    "#DDA0DD", "#FF8A5C", "#A29BFE", "#FD79A8", "#00CEC9",
    "#FDCB6E", "#E17055", "#6C5CE7", "#00B894", "#E84393",
    "#0984E3", "#F9A825", "#26A69A", "#AB47BC", "#EF5350",
    "#26C6DA", "#FFA726", "#66BB6A", "#EC407A", "#42A5F5",
    "#FFCA28", "#8D6E63", "#78909C", "#D4E157", "#FF7043",
  ];
  
  var TOP_LABELED = 30;           // nodes that always get a label (increased)
  var BG_COLOR = "#09090b";
  var LINK_COLOR = "180, 200, 230";  // Much brighter links
  var LINK_HI = "255, 255, 255";      // Highlight links
  var LINK_ALPHA = 0.5;               // Base link opacity (more visible)
  var LINK_ALPHA_DIM = 0.1;           // Dimmed link opacity

  var QNA_ANSWER_COLOR = "#10b981";   // Green highlight for answer concepts
  var QNA_SEARCH_COLOR = "#22d3ee";   // Cyan pulse for search preview

  // ---------------------------------------------------------------------
  // Small utilities
  // ---------------------------------------------------------------------

  function escapeHtml(text) {
    if (text == null) return "";
    return String(text)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function hexToRgb(hex) {
    var h = hex.replace("#", "");
    if (h.length === 3) h = h[0] + h[0] + h[1] + h[1] + h[2] + h[2];
    var n = parseInt(h, 16);
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  }

  function rgba(hex, alpha) {
    var c = hexToRgb(hex);
    return "rgba(" + c[0] + "," + c[1] + "," + c[2] + "," + alpha + ")";
  }

  /** Link endpoints are id strings before the simulation runs and node
   *  object references afterwards — normalize either form to the id. */
  function idOf(endpoint) {
    return typeof endpoint === "object" && endpoint !== null ? endpoint.id : endpoint;
  }

  // Get a deterministic color based on node id or degree
  function getNodeColor(node, idx) {
    var degree = node.degree || 0;
    var paletteIdx = (degree * 7 + idx * 3) % PALETTE.length;
    return PALETTE[paletteIdx];
  }

  // ---------------------------------------------------------------------
  // Data model
  // ---------------------------------------------------------------------

  /**
   * Enrich the raw node/link lists into the graph model.
   * No clustering - just degree-based sizing and coloring.
   */
  function buildModel(rawNodes, rawLinks, opts) {
    // Deduplicate nodes by id.
    var byId = new Map();
    rawNodes.forEach(function (n, idx) {
      if (n && n.id != null && !byId.has(n.id)) {
        byId.set(n.id, {
          id: n.id,
          label: n.label || String(n.id),
          concept: n.concept || null,
          doc: n.doc || null,
          degree: 0,
          radius: 0,
          color: "",
          top: false,
          idx: idx,
        });
      }
    });
    var nodes = Array.from(byId.values());

    // Keep only links whose endpoints both exist.
    var links = [];
    rawLinks.forEach(function (e) {
      var s = idOf(e.source);
      var t = idOf(e.target);
      if (s == null || t == null || s === t) return;
      if (!byId.has(s) || !byId.has(t)) return;
      links.push({
        source: s,
        target: t,
        type: e.type || "related",
        weight: Math.max(1, Number(e.weight) || 1),
        page_numbers: e.page_numbers || [],
        doc: e.doc || null,
        curvature: 0,
      });
    });

    // Degree (importance -> node size).
    links.forEach(function (l) {
      byId.get(idOf(l.source)).degree += 1;
      byId.get(idOf(l.target)).degree += 1;
    });
    
    // Calculate node size based on degree (more natural scaling)
    var maxDegree = Math.max(1, ...nodes.map(n => n.degree));
    nodes.forEach(function (n, idx) {
      // Size: 6-32px based on degree
      var sizeScale = 6 + (n.degree / (maxDegree || 1)) * 26;
      n.radius = Math.min(32, Math.max(6, sizeScale));
      n.color = getNodeColor(n, idx);
    });

    // Parallel edges between the same pair get increasing curvature so
    // they fan out instead of overlapping.
    var pairGroups = new Map();
    links.forEach(function (l) {
      var a = idOf(l.source);
      var b = idOf(l.target);
      var key = a < b ? a + "|" + b : b + "|" + a;
      if (!pairGroups.has(key)) pairGroups.set(key, []);
      pairGroups.get(key).push(l);
    });
    pairGroups.forEach(function (group) {
      if (group.length < 2) return;
      group.forEach(function (l, i) {
        l.curvature = 0.25 * (i - (group.length - 1) / 2);
      });
    });

    // Simple cluster assignment based on connected components for legend
    var clusterOf = detectCommunities(nodes, links);
    var clusters = collectClusters(nodes, clusterOf, opts);
    nodes.forEach(function (n) {
      n.cluster = clusterOf.get(n.id);
      var c = clusters.byId.get(n.cluster);
      n.clusterName = c ? c.name : "Unconnected";
    });

    // Adjacency for neighborhood highlighting.
    var neighbors = new Map(nodes.map(function (n) { return [n.id, new Set()]; }));
    var linksOf = new Map(nodes.map(function (n) { return [n.id, []]; }));
    links.forEach(function (l) {
      var s = idOf(l.source);
      var t = idOf(l.target);
      neighbors.get(s).add(t);
      neighbors.get(t).add(s);
      linksOf.get(s).push(l);
      linksOf.get(t).push(l);
    });

    // Top-degree nodes always get a label.
    var ranked = nodes.slice().sort(function (a, b) { return b.degree - a.degree; });
    ranked.slice(0, TOP_LABELED).forEach(function (n) { n.top = true; });
    
    // Also label nodes with degree > 3
    nodes.forEach(function (n) {
      if (n.degree >= 4) n.top = true;
    });

    return { nodes: nodes, links: links, clusters: clusters, neighbors: neighbors, linksOf: linksOf };
  }

  /**
   * Simple connected component detection for visual grouping
   */
  function detectCommunities(nodes, links) {
    var adj = new Map(nodes.map(function (n) { return [n.id, []]; }));
    links.forEach(function (l) {
      var s = idOf(l.source);
      var t = idOf(l.target);
      if (adj.has(s) && adj.has(t)) {
        adj.get(s).push(t);
        adj.get(t).push(s);
      }
    });

    var visited = new Set();
    var componentMap = new Map();
    var componentId = 0;
    
    nodes.forEach(function (n) {
      if (visited.has(n.id)) return;
      var queue = [n.id];
      visited.add(n.id);
      while (queue.length > 0) {
        var current = queue.shift();
        componentMap.set(current, componentId);
        var neighbors = adj.get(current) || [];
        neighbors.forEach(function (nb) {
          if (!visited.has(nb)) {
            visited.add(nb);
            queue.push(nb);
          }
        });
      }
      componentId++;
    });
    
    return componentMap;
  }

  /**
   * Build cluster metadata (name/color/size) for legend only.
   */
  function collectClusters(nodes, clusterOf, opts) {
    var members = new Map();
    nodes.forEach(function (n) {
      var c = clusterOf.get(n.id);
      if (!members.has(c)) members.set(c, []);
      members.get(c).push(n);
    });

    var ids = Array.from(members.keys()).sort(function (a, b) {
      return members.get(b).length - members.get(a).length || a - b;
    });

    var byId = new Map();
    var list = [];

    function clusterName(memberNodes) {
      if (opts.isAllDocuments) {
        var tally = new Map();
        memberNodes.forEach(function (n) {
          var d = n.doc || "?";
          tally.set(d, (tally.get(d) || 0) + 1);
        });
        var topDoc = null;
        var topCount = -1;
        tally.forEach(function (count, doc) {
          if (count > topCount) { topDoc = doc; topCount = count; }
        });
        if (topDoc) {
          var titles = opts.docTitles || {};
          return titles[topDoc] || topDoc;
        }
      }
      if (memberNodes.length === 1 && memberNodes[0].degree === 0) {
        return "Isolated";
      }
      return "Component " + (ids.indexOf(clusterOf.get(memberNodes[0].id)) + 1);
    }

    ids.forEach(function (cid) {
      var memberNodes = members.get(cid) || [];
      var meta = {
        id: cid,
        name: clusterName(memberNodes),
        color: memberNodes.length > 0 ? getNodeColor(memberNodes[0], 0) : "#64748b",
        size: memberNodes.length,
      };
      byId.set(cid, meta);
      list.push(meta);
    });

    list.sort(function (a, b) { return b.size - a.size; });
    return { list: list, byId: byId };
  }

  // ---------------------------------------------------------------------
  // Forces - NO CLUSTER FORCE
  // ---------------------------------------------------------------------

  /** Apply the shared force configuration to a renderer instance. */
  function applyForces(fg, model, dims) {
    fg.d3Force("center", d3.forceCenter(0, 0, 0));
    
    fg.d3Force(
      "collide",
      d3.forceCollide(function (n) { return n.radius + 4; }).strength(0.8).iterations(3)
    );

    var link = fg.d3Force("link");
    if (link) {
      link.distance(function (l) { 
        return 35 + 25 / (l.weight || 1); 
      }).strength(0.6);
    }
    
    var charge = fg.d3Force("charge");
    if (charge) {
      charge
        .strength(function (n) { 
          return n.degree === 0 ? -60 : -200 - n.degree * 3; 
        })
        .distanceMax(500);
    }

    fg.d3AlphaDecay(0.025);
    fg.d3VelocityDecay(0.35);
  }

  // ---------------------------------------------------------------------
  // Explorer factory
  // ---------------------------------------------------------------------

  function createKnowledgeGraph(container, options) {
    var opts = options || {};
    var detail = opts.detail || {};
    var model = buildModel(opts.nodes || [], opts.links || [], opts);
    var nodeById = new Map(model.nodes.map(function (n) { return [n.id, n]; }));
    var conceptById = new Map((opts.concepts || []).map(function (c) { return [c.id, c]; }));

    // Interaction state
    var mode = "3d";
    var fg = null;
    var selectedId = null;
    var highlightNodes = new Set();
    var highlightLinks = new Set();
    var hiddenClusters = new Set();
    var searchTerm = "";
    var labelsVisible = true;
    var fitOnNextStop = true;
    var destroyed = false;
    var labelOverlay3D = null;
    var labelEls3D = new Map();
    var labelRAF3D = null;

    // QnA state
    var qnaMode = opts.qnaMode || false;
    var searchNodes = new Set();
    var answerNodes = new Set();
    var searchPulse = 0;
    var searchRAF = null;
    var answerPulse = 0;
    var answerRAF = null;

    // ---- DOM scaffold -------------------------------------------------
    container.innerHTML = "";
    container.classList.add("kg-explorer");

    var toolbar = document.createElement("div");
    toolbar.className = "graph-toolbar";
    toolbar.innerHTML =
      '<button type="button" class="kg-view-toggle" title="Switch between 3D and 2D rendering">Switch to 2D</button>' +
      '<button type="button" class="kg-fit" title="Fit graph to view">Fit</button>' +
      '<button type="button" class="kg-labels active" title="Toggle node labels">Labels</button>' +
      '<button type="button" class="kg-reheat" title="Restart the layout simulation">Reheat</button>' +
      '<input type="text" class="kg-search" placeholder="Find concept…" />' +
      '<span class="graph-stats kg-stats"></span>' +
      '<span class="graph-hint kg-hint"></span>';
    container.appendChild(toolbar);

    // Legend container - but we'll keep it hidden in 2D mode
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

    // ---- Visual encoding ----------------------------------------------
    function isDimmed(node) {
      if (selectedId) return !highlightNodes.has(node.id);
      if (answerNodes.size) return !answerNodes.has(node.id);
      if (searchNodes.size) return !searchNodes.has(node.id);
      if (searchTerm) {
        var term = searchTerm.toLowerCase();
        var hit = node.label.toLowerCase().indexOf(term) !== -1;
        return !hit;
      }
      return false;
    }

    function nodeColor(node) {
      if (answerNodes.has(node.id)) {
        var aPulse = 0.55 + 0.45 * Math.sin(answerPulse + node.idx * 0.7);
        return rgba(QNA_ANSWER_COLOR, aPulse);
      }
      if (searchNodes.has(node.id)) {
        var alpha = 0.55 + 0.45 * Math.sin(searchPulse);
        return rgba(QNA_SEARCH_COLOR, alpha);
      }
      if (isDimmed(node)) {
        return mode === "3d" ? "#16161c" : rgba(node.color, 0.12);
      }
      return node.color;
    }

    function linkColor(link) {
      if (answerNodes.size || searchNodes.size) {
        var s = idOf(link.source);
        var t = idOf(link.target);
        var active = answerNodes.size
          ? (answerNodes.has(s) && answerNodes.has(t))
          : (searchNodes.has(s) && searchNodes.has(t));
        return active
          ? "rgba(" + LINK_HI + ",0.9)"
          : "rgba(" + LINK_COLOR + ",0.06)";
      }
      if (highlightLinks.size) {
        return highlightLinks.has(link)
          ? "rgba(" + LINK_HI + ",0.95)"
          : "rgba(" + LINK_COLOR + ",0.08)";
      }
      if (searchTerm) return "rgba(" + LINK_COLOR + ",0.15)";
      // Brighter links with more alpha
      var alpha = 0.3 + 0.4 * Math.min(link.weight / 3, 1);
      return "rgba(" + LINK_COLOR + "," + alpha + ")";
    }

    function linkWidth(link) {
      var w = 1.2 + 2.0 * Math.min(link.weight - 1, 4);
      if (highlightLinks.has(link)) w += 2.0;
      return Math.min(w, 8);
    }

    // No tooltips - removed nodeLabel and linkLabel

    // ---- Highlight / selection ----------------------------------------
    function updateSelection(id) {
      selectedId = id;
      highlightNodes = new Set();
      highlightLinks = new Set();
      if (id) {
        highlightNodes.add(id);
        (model.neighbors.get(id) || new Set()).forEach(function (nb) { highlightNodes.add(nb); });
        (model.linksOf.get(id) || []).forEach(function (l) { highlightLinks.add(l); });
      }
      repaint();
    }

    function repaint() {
      if (!fg) return;
      fg.nodeColor(fg.nodeColor());
      fg.linkColor(fg.linkColor());
      fg.linkWidth(fg.linkWidth());
      if (mode === "2d") fg.nodeCanvasObject(fg.nodeCanvasObject());
    }

    // ---- Detail panel ---------------------------------------------------
    function showDetail(node) {
      if (!detail.panel) return;
      var concept = conceptById.get(node.id);
      var connections = (model.linksOf.get(node.id) || []).map(function (l) {
        var otherId = idOf(l.source) === node.id ? idOf(l.target) : idOf(l.source);
        var otherNode = model.nodes.find(function (n) { return n.id === otherId; });
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

    // ---- QnA mode / traversal / highlighting ----------------------------
    function applyQnaMode() {
      if (!fg) return;
      if (qnaMode) {
        fg.nodeLabel(function (n) { return n.label; });
        fg.linkLabel(function (l) { return l.type; });
        fg.onNodeClick(function () {});
        fg.onBackgroundClick(function () {});
        ui.hint.textContent = "Hover nodes for names · Scroll to zoom · Drag to orbit";
      } else {
        fg.nodeLabel(null);
        fg.linkLabel(null);
        fg.onNodeClick(onNodeClick);
        fg.onBackgroundClick(clearSelection);
        ui.hint.textContent = mode === "3d"
          ? "Click node for details · Scroll to zoom · Drag to orbit"
          : "Click node for details · Scroll to zoom · Drag nodes";
      }
      stage.style.cursor = "default";
    }

    function setQnaMode(enabled) {
      qnaMode = !!enabled;
      if (qnaMode) {
        clearSelection();
        clearQna();
      }
      applyQnaMode();
      repaint();
    }

    function refreshRenderer() {
      if (!fg) return;
      fg.nodeColor(fg.nodeColor());
      fg.linkColor(fg.linkColor());
      fg.linkWidth(fg.linkWidth());
      if (mode === "2d") fg.nodeCanvasObject(fg.nodeCanvasObject());
    }

    function tickSearch() {
      if (!searchNodes.size) return;
      searchPulse += 0.08;
      refreshRenderer();
      searchRAF = requestAnimationFrame(tickSearch);
    }

    function startSearch(ids) {
      stopSearch();
      stopAnswerPulse();
      ids.forEach(function (id) { searchNodes.add(id); });
      if (searchNodes.size) {
        searchPulse = 0;
        searchRAF = requestAnimationFrame(tickSearch);
      }
      refreshRenderer();
    }

    function stopSearch() {
      if (searchRAF) { cancelAnimationFrame(searchRAF); searchRAF = null; }
      searchNodes.clear();
      refreshRenderer();
    }

    function tickAnswer() {
      if (!answerNodes.size) return;
      answerPulse += 0.05;
      refreshRenderer();
      answerRAF = requestAnimationFrame(tickAnswer);
    }

    function startAnswerPulse() {
      if (answerRAF) { cancelAnimationFrame(answerRAF); answerRAF = null; }
      answerPulse = 0;
      answerRAF = requestAnimationFrame(tickAnswer);
    }

    function stopAnswerPulse() {
      if (answerRAF) { cancelAnimationFrame(answerRAF); answerRAF = null; }
    }

    function highlightAnswer(ids) {
      stopSearch();
      answerNodes.clear();
      ids.forEach(function (id) {
        var rawId = typeof id === "object" && id !== null ? id.id : id;
        if (rawId && nodeById.has(rawId)) answerNodes.add(rawId);
      });
      if (answerNodes.size) startAnswerPulse();
      refreshRenderer();
    }

    function clearQna() {
      stopSearch();
      stopAnswerPulse();
      answerNodes.clear();
      refreshRenderer();
    }

    // ---- Focus / fit ----------------------------------------------------
    function focusNode(node) {
      if (!fg || !node) return;
      if (mode === "3d") {
        var distance = 140;
        var distRatio = 1 + distance / Math.hypot(node.x || 1, node.y || 1, node.z || 1);
        fg.cameraPosition(
          { x: (node.x || 0) * distRatio, y: (node.y || 0) * distRatio, z: (node.z || 0) * distRatio },
          { x: node.x || 0, y: node.y || 0, z: node.z || 0 },
          1200
        );
      } else {
        fg.centerAt(node.x, node.y, 800);
        fg.zoom(2.5, 800);
      }
    }

    function fitView() {
      if (fg) fg.zoomToFit(700, 45);
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

    function applyFilter() {
      if (selectedId && hiddenClusters.has((model.nodes.find(function (n) { return n.id === selectedId; }) || {}).cluster)) {
        clearSelection();
      }
      if (fg) {
        fg.graphData(visibleData());
        fitOnNextStop = true;
        fg.d3ReheatSimulation();
      }
      updateStats();
    }

    function updateStats() {
      var data = visibleData();
      ui.stats.textContent =
        data.nodes.length + "/" + model.nodes.length + " nodes · " +
        data.links.length + " links · " +
        model.clusters.list.length + " components";
    }

    // ---- Legend - HIDDEN in 2D mode -----------------------------------------
    function renderLegend() {
      legend.innerHTML = "";
      // Only show legend in 3D mode
      if (mode === "2d") {
        legend.style.display = "none";
        return;
      }
      // In 3D mode, show simplified legend or keep it minimal
      legend.style.display = "none"; // Hide legend in 3D too for cleaner look
      // If you want to keep legend in 3D, uncomment below:
      /*
      if (model.clusters.list.length < 2) {
        legend.style.display = "none";
        return;
      }
      legend.style.display = "";
      model.clusters.list.slice(0, 8).forEach(function (c) {
        var chip = document.createElement("button");
        chip.type = "button";
        chip.className = "legend-chip" + (hiddenClusters.has(c.id) ? " off" : "");
        chip.title = "Toggle component: " + c.name;
        chip.innerHTML =
          '<span class="legend-dot" style="background:' + c.color + '"></span>' +
          "<span>" + escapeHtml(c.name) + "</span>" +
          '<span class="legend-count">' + c.size + "</span>";
        chip.addEventListener("click", function () {
          if (hiddenClusters.has(c.id)) hiddenClusters.delete(c.id);
          else hiddenClusters.add(c.id);
          chip.classList.toggle("off");
          applyFilter();
        });
        legend.appendChild(chip);
      });
      */
    }

    // ---- 2D canvas painting ---------------------------------------------
    function paintNode(node, ctx, globalScale) {
      var r = node.radius;
      var dim = isDimmed(node);
      
      // Glow effect for nodes
      if (!dim) {
        var glow = ctx.createRadialGradient(node.x, node.y, 0, node.x, node.y, r * 2.5);
        glow.addColorStop(0, rgba(node.color, 0.2));
        glow.addColorStop(1, "transparent");
        ctx.fillStyle = glow;
        ctx.beginPath();
        ctx.arc(node.x, node.y, r * 2.5, 0, 2 * Math.PI, false);
        ctx.fill();
      }
      
      ctx.beginPath();
      ctx.arc(node.x, node.y, r, 0, 2 * Math.PI, false);
      ctx.fillStyle = dim ? rgba(node.color, 0.12) : node.color;
      ctx.fill();
      
      // Border
      ctx.lineWidth = 1.5 / globalScale;
      ctx.strokeStyle = dim ? "rgba(255,255,255,0.05)" : "rgba(255,255,255,0.25)";
      ctx.stroke();

      if (node.id === selectedId) {
        ctx.lineWidth = 2.5 / globalScale;
        ctx.strokeStyle = "#f8fafc";
        ctx.shadowColor = "rgba(255,255,255,0.3)";
        ctx.shadowBlur = 10;
        ctx.stroke();
        ctx.shadowBlur = 0;
      }

      if (answerNodes.has(node.id)) {
        var aPulse = 0.35 + 0.65 * Math.sin(answerPulse + node.idx * 0.7);
        ctx.beginPath();
        ctx.arc(node.x, node.y, r + 5 / globalScale, 0, 2 * Math.PI, false);
        ctx.strokeStyle = rgba(QNA_ANSWER_COLOR, aPulse);
        ctx.lineWidth = 2 / globalScale;
        ctx.stroke();
      }

      if (searchNodes.has(node.id)) {
        var pulse = 0.55 + 0.45 * Math.sin(searchPulse);
        ctx.beginPath();
        ctx.arc(node.x, node.y, r + 4 / globalScale, 0, 2 * Math.PI, false);
        ctx.strokeStyle = rgba(QNA_SEARCH_COLOR, pulse);
        ctx.lineWidth = 1.5 / globalScale;
        ctx.stroke();
      }

      // ALWAYS show labels for all nodes (not just top ones)
      var showLabel = labelsVisible && !dim;
      if (showLabel) {
        var fontSize = Math.max(9, Math.min(13, 12 / globalScale));
        ctx.font = fontSize + "px Inter, sans-serif";
        ctx.textAlign = "center";
        ctx.textBaseline = "top";
        var tx = node.x;
        var ty = node.y + r + 4 / globalScale;
        ctx.lineWidth = 3 / globalScale;
        ctx.strokeStyle = "rgba(9,9,11,0.92)";
        ctx.strokeText(node.label, tx, ty);
        ctx.fillStyle = "#e2e8f0";
        ctx.fillText(node.label, tx, ty);
      }
    }

    function paintNodeArea(node, color, ctx) {
      ctx.fillStyle = color;
      ctx.beginPath();
      ctx.arc(node.x, node.y, node.radius + 3, 0, 2 * Math.PI, false);
      ctx.fill();
    }

    function paintLinkLabel(link, ctx, globalScale) {
      if (!highlightLinks.has(link)) return;
      var s = link.source;
      var t = link.target;
      if (typeof s !== "object" || typeof t !== "object") return;
      var mx = (s.x + t.x) / 2;
      var my = (s.y + t.y) / 2;
      var fontSize = Math.max(8, 10 / globalScale);
      ctx.font = "italic " + fontSize + "px Inter, sans-serif";
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.lineWidth = 3 / globalScale;
      ctx.strokeStyle = "rgba(9,9,11,0.85)";
      ctx.strokeText(link.type, mx, my);
      ctx.fillStyle = "#cbd5f5";
      ctx.fillText(link.type, mx, my);
    }

    // ---- Renderers --------------------------------------------------------
    function commonProps(instance) {
      return instance
        .backgroundColor(BG_COLOR)
        .nodeColor(nodeColor)
        .nodeVal(function (n) { return Math.pow(n.radius / 4, 3); })
        // No tooltips - removed nodeLabel and linkLabel
        .linkColor(linkColor)
        .linkWidth(linkWidth)
        .linkCurvature(function (l) { return l.curvature; })
        .linkDirectionalArrowLength(0) // No arrows for cleaner look
        .linkDirectionalArrowRelPos(1)
        .onNodeClick(onNodeClick)
        .onNodeHover(function (node) { 
          stage.style.cursor = node && !qnaMode ? "pointer" : "default"; 
        })
        .onNodeDragEnd(function (node) {
          node.fx = node.fy = node.fz = undefined;
        })
        .onBackgroundClick(clearSelection)
        .onEngineStop(function () {
          if (fitOnNextStop && !destroyed) {
            fitOnNextStop = false;
            fitView();
          }
        })
        .warmupTicks(50);
    }

    function mount3D() {
      var instance = commonProps(ForceGraph3D()(stage));
      instance.nodeLabel(null);
      instance.linkLabel(null);
      instance.nodeOpacity(0.95);
      return instance;
    }

    function mount2D() {
      var instance = commonProps(
        ForceGraph()(stage)
      );
      instance.nodeLabel(null);
      instance.linkLabel(null);
      instance
        .autoPauseRedraw(false)
        .nodeCanvasObject(paintNode)
        .nodePointerAreaPaint(paintNodeArea)
        .linkCanvasObjectMode(function () { return "after"; })
        .linkCanvasObject(paintLinkLabel);
      return instance;
    }

    function mount(newMode) {
      stop3DLabels();
      mode = newMode;
      stage.innerHTML = "";
      stage.style.cursor = "default";
      fg = mode === "3d" ? mount3D() : mount2D();
      sizeRenderer();
      fg.graphData(visibleData());
      applyForces(fg, model, mode === "3d" ? 3 : 2);
      fitOnNextStop = true;
      ui.viewToggle.textContent = mode === "3d" ? "Switch to 2D" : "Switch to 3D";
      applyQnaMode();
      renderLegend();
      if (mode === "3d") start3DLabels();
    }

    function sizeRenderer() {
      if (!fg) return;
      var w = stage.clientWidth;
      var h = stage.clientHeight;
      if (w > 0 && h > 0) fg.width(w).height(h);
    }

    // ---- 3D label overlay - ALL labels visible -------------------------
    function projectToScreen(x, y, z) {
      if (!fg) return null;
      var camera = fg.camera && fg.camera();
      var renderer = fg.renderer && fg.renderer();
      if (!camera || !renderer) return null;
      var me = camera.matrixWorldInverse.elements;
      var pe = camera.projectionMatrix.elements;
      var vx = me[0]*x + me[4]*y + me[8]*z + me[12];
      var vy = me[1]*x + me[5]*y + me[9]*z + me[13];
      var vz = me[2]*x + me[6]*y + me[10]*z + me[14];
      var vw = me[3]*x + me[7]*y + me[11]*z + me[15];
      var cx = pe[0]*vx + pe[4]*vy + pe[8]*vz + pe[12]*vw;
      var cy = pe[1]*vx + pe[5]*vy + pe[9]*vz + pe[13]*vw;
      var cw = pe[3]*vx + pe[7]*vy + pe[11]*vz + pe[15]*vw;
      if (Math.abs(cw) < 1e-10 || cw < 0) return null;
      var sw = renderer.domElement.clientWidth;
      var sh = renderer.domElement.clientHeight;
      return {
        x: (cx / cw + 1) * sw / 2,
        y: (-cy / cw + 1) * sh / 2,
      };
    }

    function tick3DLabels() {
      if (!fg || mode !== "3d" || !labelOverlay3D) return;
      labelRAF3D = requestAnimationFrame(tick3DLabels);
      var activeIds = new Set();
      model.nodes.forEach(function (node) {
        if (hiddenClusters.has(node.cluster)) return;
        // Show ALL labels in 3D (not just top nodes)
        var show = labelsVisible && !isDimmed(node);
        if (!show) return;
        var pos = projectToScreen(node.x || 0, node.y || 0, node.z || 0);
        if (!pos) return;
        activeIds.add(node.id);
        var el = labelEls3D.get(node.id);
        if (!el) {
          el = document.createElement("span");
          el.className = "kg-3d-label";
          el.textContent = node.label;
          labelOverlay3D.appendChild(el);
          labelEls3D.set(node.id, el);
        }
        el.style.left = pos.x + "px";
        el.style.top = (pos.y + node.radius * 0.4 + 4) + "px";
        el.style.display = "";
        var fontSize = Math.max(9, 11 - (model.nodes.length > 100 ? 1 : 0));
        el.style.fontSize = fontSize + "px";
      });
      labelEls3D.forEach(function (el, id) {
        if (!activeIds.has(id)) el.style.display = "none";
      });
    }

    function start3DLabels() {
      if (!labelOverlay3D) {
        labelOverlay3D = document.createElement("div");
        labelOverlay3D.style.cssText = "position:absolute;inset:0;pointer-events:none;overflow:hidden;z-index:5;";
        stage.appendChild(labelOverlay3D);
      }
      if (labelRAF3D) cancelAnimationFrame(labelRAF3D);
      labelRAF3D = requestAnimationFrame(tick3DLabels);
    }

    function stop3DLabels() {
      if (labelRAF3D) { cancelAnimationFrame(labelRAF3D); labelRAF3D = null; }
      if (labelOverlay3D) {
        if (labelOverlay3D.parentNode) labelOverlay3D.parentNode.removeChild(labelOverlay3D);
        labelOverlay3D = null;
      }
      labelEls3D.clear();
    }

    // ---- Toolbar events ---------------------------------------------------
    ui.viewToggle.addEventListener("click", function () {
      teardownRenderer();
      mount(mode === "3d" ? "2d" : "3d");
    });

    ui.fit.addEventListener("click", fitView);

    ui.labels.addEventListener("click", function () {
      labelsVisible = !labelsVisible;
      ui.labels.classList.toggle("active", labelsVisible);
      repaint();
    });

    ui.reheat.addEventListener("click", function () {
      if (fg) fg.d3ReheatSimulation();
    });

    ui.search.addEventListener("input", function () {
      searchTerm = ui.search.value.trim();
      if (searchTerm && selectedId) clearSelection();
      repaint();
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
        clearSelection();
      }
    }
    document.addEventListener("keydown", onKeydown);

    // ---- Resize -----------------------------------------------------------
    var resizeObserver = null;
    if (typeof ResizeObserver !== "undefined") {
      resizeObserver = new ResizeObserver(function () { sizeRenderer(); });
      resizeObserver.observe(stage);
    }

    // ---- Teardown -----------------------------------------------------------
    function teardownRenderer() {
      stop3DLabels();
      if (!fg) return;
      try { fg.pauseAnimation(); } catch (e) { /* noop */ }
      try {
        var controls = fg.controls && fg.controls();
        if (controls && controls.dispose) controls.dispose();
      } catch (e) { /* noop */ }
      try {
        var renderer = fg.renderer && fg.renderer();
        if (renderer && renderer.dispose) renderer.dispose();
      } catch (e) { /* noop */ }
      fg = null;
    }

    function destroy() {
      destroyed = true;
      document.removeEventListener("keydown", onKeydown);
      if (resizeObserver) resizeObserver.disconnect();
      teardownRenderer();
      hideDetail();
      container.innerHTML = "";
      container.classList.remove("kg-explorer");
    }

    // ---- Init ---------------------------------------------------------------
    if (!model.nodes.length) {
      stage.innerHTML = '<p class="muted">No graph data available.</p>';
      ui.stats.textContent = "0 nodes";
    } else {
      mount("3d");
    }
    renderLegend();
    updateStats();

    // ---- Public API -----------------------------------------------------------
    return {
      destroy: destroy,
      clearSelection: clearSelection,
      refresh: function () {
        sizeRenderer();
      },
      getMode: function () { return mode; },
      instance: function () { return fg; },
      setQnaMode: setQnaMode,
      startSearch: startSearch,
      stopSearch: stopSearch,
      highlightAnswer: highlightAnswer,
      clearQna: clearQna,
    };
  }

  window.createKnowledgeGraph = createKnowledgeGraph;
})();