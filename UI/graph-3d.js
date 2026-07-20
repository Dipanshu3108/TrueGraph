/**
 * 3D force-graph renderer (extracted from the original graph.js).
 */
(function () {
  "use strict";

  var Shared = window.GraphShared;
  var S = window.GRAPH_SHARED;

  function rgba(hex, alpha) { return Shared.rgba(hex, alpha); }
  function idOf(endpoint) { return Shared.idOf(endpoint); }

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

    fg.d3AlphaDecay(0.009);
    fg.d3VelocityDecay(0.5);
  }

  function create(stage, ctx) {
    var fg = null;
    var labelOverlay = null;
    var labelEls = new Map();
    var labelRAF = null;
    var resetPending = false;

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
      if (ctx.answerNodes.has(node.id)) {
        var aPulse = 0.55 + 0.45 * Math.sin(ctx.answerPulse + node.idx * 0.7);
        return rgba(S.QNA_ANSWER_COLOR, aPulse);
      }
      if (ctx.searchNodes.has(node.id)) {
        var alpha = 0.55 + 0.45 * Math.sin(ctx.searchPulse);
        return rgba(S.QNA_SEARCH_COLOR, alpha);
      }
      if (isDimmed(node)) return "#16161c";
      return node.color;
    }

    function linkColor(link) {
      if (ctx.answerNodes.size || ctx.searchNodes.size) {
        var s = idOf(link.source);
        var t = idOf(link.target);
        var active = ctx.answerNodes.size
          ? (ctx.answerNodes.has(s) && ctx.answerNodes.has(t))
          : (ctx.searchNodes.has(s) && ctx.searchNodes.has(t));
        return active
          ? "rgba(" + S.LINK_HI + ",0.9)"
          : "rgba(" + S.LINK_COLOR + ",0.06)";
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

    function linkWidth(link) {
      var w = 1.2 + 2.0 * Math.min(link.weight - 1, 4);
      if (ctx.highlightLinks.has(link)) w += 2.0;
      return Math.min(w, 8);
    }

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

    function tickLabels() {
      if (!fg || !labelOverlay) return;
      labelRAF = requestAnimationFrame(tickLabels);
      var activeIds = new Set();
      ctx.model.nodes.forEach(function (node) {
        if (ctx.hiddenClusters.has(node.cluster)) return;
        var show = ctx.labelsVisible && !isDimmed(node);
        if (!show) return;
        var pos = projectToScreen(node.x || 0, node.y || 0, node.z || 0);
        if (!pos) return;
        activeIds.add(node.id);
        var el = labelEls.get(node.id);
        if (!el) {
          el = document.createElement("span");
          el.className = "kg-3d-label";
          el.textContent = node.label;
          labelOverlay.appendChild(el);
          labelEls.set(node.id, el);
        }
        el.style.left = pos.x + "px";
        el.style.top = (pos.y + node.radius * 0.4 + 4) + "px";
        el.style.display = "";
        var fontSize = Math.max(9, 11 - (ctx.model.nodes.length > 100 ? 1 : 0));
        el.style.fontSize = fontSize + "px";
      });
      labelEls.forEach(function (el, id) {
        if (!activeIds.has(id)) el.style.display = "none";
      });
    }

    function startLabels() {
      if (!labelOverlay) {
        labelOverlay = document.createElement("div");
        labelOverlay.style.cssText = "position:absolute;inset:0;pointer-events:none;overflow:hidden;z-index:5;";
        stage.appendChild(labelOverlay);
      }
      if (labelRAF) cancelAnimationFrame(labelRAF);
      labelRAF = requestAnimationFrame(tickLabels);
    }

    function stopLabels() {
      if (labelRAF) { cancelAnimationFrame(labelRAF); labelRAF = null; }
      if (labelOverlay) {
        if (labelOverlay.parentNode) labelOverlay.parentNode.removeChild(labelOverlay);
        labelOverlay = null;
      }
      labelEls.clear();
    }

    function sizeRenderer() {
      if (!fg) return;
      var w = stage.clientWidth;
      var h = stage.clientHeight;
      if (w > 0 && h > 0) fg.width(w).height(h);
    }

    function mount() {
      stage.innerHTML = "";
      stopLabels();

      var data = visibleData();
      fg = ForceGraph3D()(stage)
        .backgroundColor(S.BG_COLOR)
        .nodeColor(nodeColor)
        .nodeVal(function (n) { return Math.pow(n.radius / 4, 3); })
        .nodeOpacity(0.95)
        .nodeLabel(null)
        .linkColor(linkColor)
        .linkWidth(linkWidth)
        .linkCurvature(function (l) { return l.curvature; })
        .linkDirectionalArrowLength(0)
        .linkDirectionalArrowRelPos(1)
        .linkLabel(null)
        .onNodeClick(ctx.onNodeClick)
        .onNodeHover(function (node) {
          stage.style.cursor = node && !ctx.qnaMode ? "pointer" : "default";
        })
        .onNodeDragEnd(function (node) {
          node.fx = node.fy = node.fz = undefined;
        })
        .onBackgroundClick(ctx.onBackgroundClick)
        .onEngineStop(function () {
          if (resetPending) {
            resetPending = false;
            fitView();
          }
        })
        .warmupTicks(50)
        .graphData(data);

      applyForces(fg, ctx.model, 3);
      sizeRenderer();
      try {
        var controls = fg.controls && fg.controls();
        if (controls) {
          controls.autoRotate = true;
          controls.autoRotateSpeed = 0.6;
          controls.enableDamping = true;
        }
      } catch (e) { /* noop */ }
      startLabels();
    }

    function visibleData() {
      var nodes = ctx.model.nodes.filter(function (n) { return !ctx.hiddenClusters.has(n.cluster); });
      var ids = new Set(nodes.map(function (n) { return n.id; }));
      var links = ctx.model.links.filter(function (l) {
        return ids.has(idOf(l.source)) && ids.has(idOf(l.target));
      });
      return { nodes: nodes, links: links };
    }

    function teardown() {
      stopLabels();
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

    function refresh() {
      sizeRenderer();
    }

    function focusNode(node) {
      if (!fg || !node) return;
      var distance = 140;
      var distRatio = 1 + distance / Math.hypot(node.x || 1, node.y || 1, node.z || 1);
      fg.cameraPosition(
        { x: (node.x || 0) * distRatio, y: (node.y || 0) * distRatio, z: (node.z || 0) * distRatio },
        { x: node.x || 0, y: node.y || 0, z: node.z || 0 },
        1200
      );
    }

    function fitView() {
      if (fg) fg.zoomToFit(700, 45);
    }

    function repaint() {
      if (!fg) return;
      fg.nodeColor(fg.nodeColor());
      fg.linkColor(fg.linkColor());
      fg.linkWidth(fg.linkWidth());
    }

    function applyFilter() {
      if (!fg) return;
      fg.graphData(visibleData());
      fg.d3ReheatSimulation();
    }

    function setQnaMode(enabled) {
      if (!fg) return;
      if (enabled) {
        fg.nodeLabel(function (n) { return n.label; });
        fg.linkLabel(function (l) { return l.type; });
        fg.onNodeClick(function () {});
        fg.onBackgroundClick(function () {});
      } else {
        fg.nodeLabel(null);
        fg.linkLabel(null);
        fg.onNodeClick(ctx.onNodeClick);
        fg.onBackgroundClick(ctx.onBackgroundClick);
      }
      stage.style.cursor = "default";
    }

    function reset() {
      if (!fg) return;
      resetPending = true;
      fg.d3ReheatSimulation();
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
      instance: function () { return fg; },
    };
  }

  window.Graph3D = { create: create };
})();
