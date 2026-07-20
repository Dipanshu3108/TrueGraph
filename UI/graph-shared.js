/**
 * Shared graph utilities and data model used by both 3D and 2D renderers.
 */
(function () {
  "use strict";

  // -----------------------------------------------------------------
  // Constants
  // -----------------------------------------------------------------

  // Expanded vibrant color palette for individual nodes.
  var PALETTE = [
    "#FF6B6B", "#4ECDC4", "#45B7D1", "#96CEB4", "#FFEAA7",
    "#DDA0DD", "#FF8A5C", "#A29BFE", "#FD79A8", "#00CEC9",
    "#FDCB6E", "#E17055", "#6C5CE7", "#00B894", "#E84393",
    "#0984E3", "#F9A825", "#26A69A", "#AB47BC", "#EF5350",
    "#26C6DA", "#FFA726", "#66BB6A", "#EC407A", "#42A5F5",
    "#FFCA28", "#8D6E63", "#78909C", "#D4E157", "#FF7043",
  ];

  window.GRAPH_SHARED = {
    PALETTE: PALETTE,
    TOP_LABELED: 30,
    BG_COLOR: "#09090b",
    LINK_COLOR: "180, 200, 230",
    LINK_HI: "255, 255, 255",
    LINK_ALPHA: 0.5,
    LINK_ALPHA_DIM: 0.1,
    QNA_ANSWER_COLOR: "#10b981",
    QNA_SEARCH_COLOR: "#22d3ee",
  };

  // -----------------------------------------------------------------
  // Small utilities
  // -----------------------------------------------------------------

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

  /** Normalize a link endpoint to its id string. */
  function idOf(endpoint) {
    return typeof endpoint === "object" && endpoint !== null ? endpoint.id : endpoint;
  }

  /** Deterministic palette color based on node degree and index. */
  function getNodeColor(node, idx) {
    var degree = node.degree || 0;
    var paletteIdx = (degree * 7 + idx * 3) % PALETTE.length;
    return PALETTE[paletteIdx];
  }

  // -----------------------------------------------------------------
  // Data model
  // -----------------------------------------------------------------

  /**
   * Enrich raw node/link lists into the shared graph model.
   */
  function buildModel(rawNodes, rawLinks, opts) {
    opts = opts || {};

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

    var maxDegree = Math.max(1, Math.max.apply(null, nodes.map(function (n) { return n.degree; })));
    nodes.forEach(function (n, idx) {
      var sizeScale = 6 + (n.degree / (maxDegree || 1)) * 26;
      n.radius = Math.min(32, Math.max(6, sizeScale));
      n.color = getNodeColor(n, idx);
    });

    // Parallel edges between the same pair get increasing curvature.
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

    // Simple connected-component detection for visual grouping / legend.
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
    ranked.slice(0, window.GRAPH_SHARED.TOP_LABELED).forEach(function (n) { n.top = true; });
    nodes.forEach(function (n) {
      if (n.degree >= 4) n.top = true;
    });

    return {
      nodes: nodes,
      links: links,
      clusters: clusters,
      neighbors: neighbors,
      linksOf: linksOf,
    };
  }

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

  // -----------------------------------------------------------------
  // Public shared helpers
  // -----------------------------------------------------------------

  window.GraphShared = {
    escapeHtml: escapeHtml,
    hexToRgb: hexToRgb,
    rgba: rgba,
    idOf: idOf,
    getNodeColor: getNodeColor,
    buildModel: buildModel,
    detectCommunities: detectCommunities,
    collectClusters: collectClusters,
  };
})();
