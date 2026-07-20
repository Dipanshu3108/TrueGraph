/**
 * 2D vis-network renderer adapted from TEST_UI/test_graph.js.
 */
(function () {
  "use strict";

  var Shared = window.GraphShared;
  var S = window.GRAPH_SHARED;

  // Concept-type colors taken from TEST_UI/test_graph.js.
  var TYPE_COLORS = {
    concept: "#5b8cff",
    glossary: "#33c2a1",
    procedure: "#f4b740",
    api: "#e26bd6",
    entity: "#ff6b6b",
  };

  function rgba(hex, alpha) { return Shared.rgba(hex, alpha); }
  function idOf(endpoint) { return Shared.idOf(endpoint); }

  function getNodeBaseColor(node, ctx) {
    var concept = ctx.conceptById.get(node.id);
    if (concept && concept.concept_type && TYPE_COLORS[concept.concept_type]) {
      return TYPE_COLORS[concept.concept_type];
    }
    return node.color || "#888";
  }

  function create(stage, ctx) {
    var network = null;
    var nodesDS = null;
    var edgesDS = null;
    var pulseRAF = null;
    var lastPulseType = null; // 'search' | 'answer' | null
    var ambientTimer = null;
    var resetPending = false;

    function visibleNodes() {
      return ctx.model.nodes.filter(function (n) { return !ctx.hiddenClusters.has(n.cluster); });
    }

    function visibleLinks() {
      var ids = new Set(visibleNodes().map(function (n) { return n.id; }));
      return ctx.model.links.filter(function (l) {
        return ids.has(idOf(l.source)) && ids.has(idOf(l.target));
      });
    }

    function isDimmed(node) {
      if (ctx.selectedId) return !ctx.highlightNodes.has(node.id);
      if (ctx.answerNodes.size) return !ctx.answerNodes.has(node.id);
      if (ctx.searchNodes.size) return !ctx.searchNodes.has(node.id);
      if (ctx.searchTerm) {
        var term = ctx.searchTerm.toLowerCase();
        return node.label.toLowerCase().indexOf(term) === -1;
      }
      return false;
    }

    function nodeColor(node) {
      var base = getNodeBaseColor(node, ctx);
      if (ctx.answerNodes.has(node.id)) {
        var aPulse = 0.55 + 0.45 * Math.sin(ctx.answerPulse + node.idx * 0.7);
        return rgba(S.QNA_ANSWER_COLOR, aPulse);
      }
      if (ctx.searchNodes.has(node.id)) {
        var alpha = 0.55 + 0.45 * Math.sin(ctx.searchPulse);
        return rgba(S.QNA_SEARCH_COLOR, alpha);
      }
      if (isDimmed(node)) {
        return rgba(base, 0.18);
      }
      return base;
    }

    function nodeBorderColor(node) {
      if (ctx.selectedId === node.id) return "#f8fafc";
      if (ctx.answerNodes.has(node.id)) return rgba(S.QNA_ANSWER_COLOR, 0.8);
      if (ctx.searchNodes.has(node.id)) return rgba(S.QNA_SEARCH_COLOR, 0.8);
      return "rgba(255,255,255,0.25)";
    }

    function nodeLabel(node) {
      if (!ctx.labelsVisible || isDimmed(node)) return "";
      return node.label;
    }

    function edgeColor(link) {
      if (ctx.answerNodes.size || ctx.searchNodes.size) {
        var s = idOf(link.source);
        var t = idOf(link.target);
        var active = ctx.answerNodes.size
          ? (ctx.answerNodes.has(s) && ctx.answerNodes.has(t))
          : (ctx.searchNodes.has(s) && ctx.searchNodes.has(t));
        return active ? "rgba(" + S.LINK_HI + ",0.9)" : "rgba(" + S.LINK_COLOR + ",0.08)";
      }
      if (ctx.highlightLinks.size) {
        return ctx.highlightLinks.has(link)
          ? "rgba(" + S.LINK_HI + ",0.95)"
          : "rgba(" + S.LINK_COLOR + ",0.08)";
      }
      if (ctx.searchTerm) return "rgba(" + S.LINK_COLOR + ",0.15)";
      var alpha = 0.3 + 0.4 * Math.min(link.weight / 3, 1);
      return "rgba(" + S.LINK_COLOR + "," + alpha + ")";
    }

    function buildVisNodes() {
      return visibleNodes().map(function (n) {
        return {
          id: n.id,
          label: nodeLabel(n),
          title: ctx.qnaMode ? n.label : null,
          value: n.radius,
          color: {
            background: nodeColor(n),
            border: nodeBorderColor(n),
            highlight: { background: n.color, border: "#f8fafc" },
            hover: { background: n.color, border: "#f8fafc" },
          },
          borderWidth: ctx.selectedId === n.id ? 2.5 : 1.5,
          font: { color: "#e2e8f0", size: 12, face: "Inter, sans-serif" },
        };
      });
    }

    function buildVisEdges() {
      return visibleLinks().map(function (l, idx) {
        return {
          id: l.source + "|" + l.target + "|" + (l.type || "") + "|" + idx,
          from: idOf(l.source),
          to: idOf(l.target),
          title: l.type,
          color: { color: edgeColor(l), highlight: "rgba(" + S.LINK_HI + ",0.95)", hover: "rgba(" + S.LINK_HI + ",0.95)" },
          width: 1.5,
          arrows: "to",
          smooth: { type: "continuous" },
        };
      });
    }

    function stopPulse() {
      if (pulseRAF) { cancelAnimationFrame(pulseRAF); pulseRAF = null; }
      lastPulseType = null;
    }

    function startAmbientMotion() {
      stopAmbientMotion();
      ambientTimer = setInterval(function () {
        if (!network || !nodesDS) return;
        var nodes = visibleNodes();
        if (!nodes.length) return;
        var node = nodes[Math.floor(Math.random() * nodes.length)];
        var positions = network.getPositions([node.id]);
        var pos = positions[node.id];
        if (!pos) return;
        var delta = 2.5;
        nodesDS.update([{
          id: node.id,
          x: pos.x + (Math.random() - 0.5) * delta,
          y: pos.y + (Math.random() - 0.5) * delta,
        }]);
      }, 2200);
    }

    function stopAmbientMotion() {
      if (ambientTimer) { clearInterval(ambientTimer); ambientTimer = null; }
    }

    function mount() {
      stage.innerHTML = "";
      stopPulse();
      stopAmbientMotion();

      if (typeof vis === "undefined" || !vis.Network) {
        stage.innerHTML = '<p class="muted">2D graph library failed to load.</p>';
        return;
      }

      var nodes = buildVisNodes();
      var edges = buildVisEdges();
      if (!nodes.length) {
        stage.innerHTML = '<p class="muted">No graph data available.</p>';
        return;
      }

      nodesDS = new vis.DataSet(nodes);
      edgesDS = new vis.DataSet(edges);

      var options = {
        physics: {
          enabled: true,
          solver: "forceAtlas2Based",
          forceAtlas2Based: {
            gravitationalConstant: -100,
            centralGravity: 0.009,
            springLength: 140,
            springConstant: 0.04,
            damping: 0.35,
            avoidOverlap: 1.0,
          },
          stabilization: { iterations: 300, fit: false },
          adaptiveTimestep: true,
          minVelocity: 0,
          maxVelocity: 20,
        },
        nodes: {
          shape: "dot",
          scaling: { min: 6, max: 32 },
          font: { color: "#c9cfe0" },
        },
        edges: {
          color: { color: "#3a4468", highlight: "#5b8cff" },
          smooth: { type: "continuous" },
        },
        interaction: { hover: true, dragNodes: true },
      };

      network = new vis.Network(stage, { nodes: nodesDS, edges: edgesDS }, options);

      network.on("click", function (params) {
        if (params.nodes.length) {
          var node = ctx.nodeById.get(params.nodes[0]);
          if (node) ctx.onNodeClick(node);
        } else {
          ctx.onBackgroundClick();
        }
      });

      network.on("stabilizationIterationsDone", function () {
        startAmbientMotion();
        if (resetPending) {
          resetPending = false;
          network.fit({ animation: { duration: 700, easingFunction: "easeInOutQuad" } });
        }
      });
      network.on("dragStart", stopAmbientMotion);
      network.on("dragEnd", startAmbientMotion);

      network.on("hoverNode", function () {
        stage.style.cursor = ctx.qnaMode ? "default" : "pointer";
      });
      network.on("blurNode", function () {
        stage.style.cursor = "default";
      });
    }

    function teardown() {
      stopAmbientMotion();
      if (network) {
        network.destroy();
        network = null;
      }
      nodesDS = null;
      edgesDS = null;
    }

    function refresh() {
      if (network) network.redraw();
    }

    function focusNode(node) {
      if (!network || !node) return;
      network.focus(node.id, {
        scale: 1.6,
        animation: { duration: 800, easingFunction: "easeInOutQuad" },
      });
    }

    function fitView() {
      if (network) network.fit({ animation: { duration: 700, easingFunction: "easeInOutQuad" } });
    }

    function updateNodes(ids) {
      if (!nodesDS) return;
      var toUpdate = (ids ? ids.map(function (id) { return ctx.nodeById.get(id); }).filter(Boolean) : visibleNodes())
        .map(function (n) {
          return {
            id: n.id,
            label: nodeLabel(n),
            title: ctx.qnaMode ? n.label : null,
            color: {
              background: nodeColor(n),
              border: nodeBorderColor(n),
              highlight: { background: n.color, border: "#f8fafc" },
              hover: { background: n.color, border: "#f8fafc" },
            },
            borderWidth: ctx.selectedId === n.id ? 2.5 : 1.5,
          };
        });
      nodesDS.update(toUpdate);
    }

    function updateEdges() {
      if (!edgesDS) return;
      var updates = visibleLinks().map(function (l, idx) {
        return {
          id: l.source + "|" + l.target + "|" + (l.type || "") + "|" + idx,
          color: { color: edgeColor(l), highlight: "rgba(" + S.LINK_HI + ",0.95)", hover: "rgba(" + S.LINK_HI + ",0.95)" },
        };
      });
      edgesDS.update(updates);
    }

    function repaint() {
      updateNodes();
      updateEdges();
    }

    function applyFilter() {
      teardown();
      mount();
    }

    function setQnaMode(enabled) {
      updateNodes();
    }

    function reset() {
      if (!network) return;
      resetPending = true;
      network.setOptions({ physics: { enabled: true } });
      network.stabilize();
    }

    return {
      mount: mount,
      teardown: teardown,
      refresh: refresh,
      focusNode: focusNode,
      fitView: fitView,
      repaint: repaint,
      applyFilter: applyFilter,
      setQnaMode: setQnaMode,
      reset: reset,
      instance: function () { return network; },
    };
  }

  window.Graph2D = { create: create };
})();
