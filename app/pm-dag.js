/* ===================== pm-dag.js =====================
 * 零构建扁平 ESM：任务 DAG 的分层布局与 SVG 渲染（task-68），只吃 dagEdges / teamTasks 字段。
 * task-91 阶段 1：从 app.js 原样搬出，只加 export / import，不改逻辑。
 * 注意：这里是**纯渲染**，不自带事件；hover/点击联动仍在 app.js（用 data-dag-node 属性接线）。
 */
import { esc } from './pm-format.js';

  /* dagEdges: [[from,to]] → 文本链；分叉/成环时退回逐条边（不猜拓扑） */
export function dagChainLines(edges) {
    var pairs = [];
    (edges || []).forEach(function (e) {
      if (!Array.isArray(e) || e.length < 2) return;
      var from = String(e[0] || ''), to = String(e[1] || '');
      if (from && to) pairs.push([from, to]);
    });
    if (!pairs.length) return null;
    var out = {}, inc = {}, nodes = {};
    pairs.forEach(function (p) {
      (out[p[0]] = out[p[0]] || []).push(p[1]);
      (inc[p[1]] = inc[p[1]] || []).push(p[0]);
      nodes[p[0]] = 1; nodes[p[1]] = 1;
    });
    var edgeLines = pairs.map(function (p) { return p[0] + ' → ' + p[1]; });
    var branched = Object.keys(out).some(function (k) { return out[k].length > 1; }) ||
                   Object.keys(inc).some(function (k) { return inc[k].length > 1; });
    if (branched) return { lines: edgeLines, fallback: true };
    var starts = Object.keys(nodes).filter(function (n) { return !inc[n]; });
    var seen = {}, chains = [];
    starts.forEach(function (s) {
      var chain = [s], cur = s, guard = 0;
      while (out[cur] && out[cur].length === 1 && !seen[cur + '>' + out[cur][0]] && guard++ <= pairs.length + 1) {
        var nx = out[cur][0];
        seen[cur + '>' + nx] = 1;
        chain.push(nx);
        cur = nx;
      }
      chains.push(chain);
    });
    if (Object.keys(seen).length !== pairs.length) return { lines: edgeLines, fallback: true };
    return { lines: chains.map(function (c) { return c.join(' → '); }), fallback: false };
  }

export function dagPairCount(edges) {
    var seen = {}, n = 0;
    (edges || []).forEach(function (e) {
      if (!Array.isArray(e) || e.length < 2) return;
      var k = String(e[0] || '') + '|' + String(e[1] || '');
      if (!e[0] || !e[1] || seen[k]) return;
      seen[k] = 1; n++;
    });
    return n;
  }

export function dagTextHtml(edges, detailsAttrs) {   /* task-209：可选受控属性（由调用方从 state.folds 回填） */
    var info = dagChainLines(edges);
    if (!info) return '';
    return '<details class="dag-text"' + (detailsAttrs || '') + '><summary>以文本查看（' + dagPairCount(edges) + ' 条依赖）</summary>' +
      info.lines.map(function (line) { return '<div class="task-dag-line">' + esc(line) + '</div>'; }).join('') +
      (info.fallback ? '<p class="hint">依赖有分叉或成环：按每条边列出，不猜拓扑顺序。</p>' : '') +
      '</details>';
  }

  /* ---------- 任务 DAG：Kahn 分层布局（纯函数，只吃 dagEdges/teamTasks 字段） ---------- */
export var DAG_W = 158, DAG_H = 46, DAG_GX = 18, DAG_GY = 46, DAG_PAD = 10;

export function clipText(s, n) {
    var t = String(s === null || s === undefined ? '' : s);
    return t.length > n ? t.slice(0, n - 1) + '…' : t;
  }

export function dagStatusClass(status) {
    var s = String(status || '').toUpperCase();
    if (s === 'BLOCKED' || s === 'FAILED' || s === 'ERROR') return 'red';
    if (s === 'DONE' || s === 'COMPLETED' || s === 'REVIEW') return 'green';
    if (s === 'CANCELLED' || s === 'SKIPPED') return 'gray';
    if (s === 'DOING' || s === 'IN_PROGRESS' || s === 'RUNNING') return 'purple';
    if (s === 'WAITING' || s === 'TODO' || s === 'PENDING') return 'amber';
    return 'blue';
  }

export function dagSub(subs, id) {
    var hit = (subs || []).filter(function (s) { return s && String(s.id) === String(id); })[0];
    return hit || null;
  }

export function dagModel(edges, subs) {
    var pairs = [], seenEdge = {};
    (edges || []).forEach(function (e) {
      if (!Array.isArray(e) || e.length < 2) return;
      var from = String(e[0] || ''), to = String(e[1] || '');
      if (!from || !to) return;
      var k = from + '|' + to;
      if (seenEdge[k]) return;
      seenEdge[k] = 1;
      pairs.push([from, to]);
    });
    var nodes = [], known = {};
    /* 节点宇宙 = 边上的节点 ∪ 子任务 id：没有边的子任务是「无依赖」，必须能识别出来 */
    pairs.forEach(function (p) {
      [p[0], p[1]].forEach(function (n) { if (!known[n]) { known[n] = 1; nodes.push(n); } });
    });
    (subs || []).forEach(function (s) {
      var id = s && s.id ? String(s.id) : '';
      if (id && !known[id]) { known[id] = 1; nodes.push(id); }
    });
    nodes.sort();
    var succ = {}, pred = {};
    nodes.forEach(function (n) { succ[n] = []; pred[n] = []; });
    pairs.forEach(function (p) { succ[p[0]].push(p[1]); pred[p[1]].push(p[0]); });
    var indeg = {}, layer = {}, queue = [];
    nodes.forEach(function (n) { indeg[n] = pred[n].length; if (!indeg[n]) { layer[n] = 0; queue.push(n); } });
    var processed = 0;
    while (queue.length) {
      var cur = queue.shift();
      processed++;
      succ[cur].forEach(function (nx) {
        var cand = (layer[cur] || 0) + 1;
        if (!(layer[nx] >= cand)) layer[nx] = cand;
        indeg[nx]--;
        if (indeg[nx] === 0) queue.push(nx);
      });
    }
    var cyclic = processed !== nodes.length;
    var inCycle = {}, cycles = [];
    if (cyclic) {
      nodes.forEach(function (n) { if (indeg[n] > 0) inCycle[n] = 1; });
      var start = nodes.filter(function (n) { return inCycle[n]; })[0];
      var path = [], onPath = {}, cur2 = start;
      while (cur2 && !onPath[cur2]) {
        onPath[cur2] = 1;
        path.push(cur2);
        cur2 = succ[cur2].filter(function (x) { return inCycle[x]; })[0];
      }
      if (cur2) {
        var at = path.indexOf(cur2);
        cycles = path.slice(at < 0 ? 0 : at).concat([cur2]);
      }
    }
    var layers = [], isolated = [];
    if (!cyclic) {
      nodes.forEach(function (n) {
        if (!succ[n].length && !pred[n].length) { isolated.push(n); return; }
        var L = layer[n] === undefined ? 0 : layer[n];
        (layers[L] = layers[L] || []).push(n);
      });
      layers = layers.filter(function (l) { return !!l && l.length > 0; });
      layers.forEach(function (l) { l.sort(); });
    }
    return { pairs: pairs, nodes: nodes, succ: succ, pred: pred, layers: layers, isolated: isolated, cyclic: cyclic, cycles: cycles, inCycle: inCycle };
  }

export function dagNarrow() {
    try { return !!(window.matchMedia && window.matchMedia('(max-width:900px)').matches); } catch (e) { return false; }
  }

export function dagSvgHtml(edges, subs) {
    var m = dagModel(edges, subs);
    if (!m.pairs.length && !m.isolated.length) return '';
    var head = '<div class="task-extras-title">依赖图（DAG）</div>';
    if (m.cyclic) {
      var cycText = m.cycles.length ? m.cycles.join(' → ') : '（环上节点见下）';
      var inCycleNodes = m.nodes.filter(function (n) { return m.inCycle[n]; });
      return '<div class="task-dag">' + head +
        '<div class="notice warn">⚠ 任务 DAG 有环：<code>' + esc(cycText) + '</code> —— ' +
        '有环时不画分层图（画出来会误导），下面列出环上的节点与完整的边列表。</div>' +
        '<p class="hint">环上节点：' + (inCycleNodes.length ? inCycleNodes.map(function (n) { return '<code>' + esc(n) + '</code>'; }).join('、') : '未返回') + '</p>' +
        dagTextHtml(edges) + '</div>';
    }
    if (dagNarrow()) {
      return '<div class="task-dag">' + head +
        '<p class="hint">窄屏（≤900px）不画图：下面是文本链。</p>' + dagTextHtml(edges) + '</div>';
    }
    var pos = {};
    m.layers.forEach(function (layerNodes, li) {
      layerNodes.forEach(function (id, ci) {
        pos[id] = { x: DAG_PAD + ci * (DAG_W + DAG_GX), y: DAG_PAD + li * (DAG_H + DAG_GY) };
      });
    });
    var cols = 1;
    m.layers.forEach(function (l) { if (l.length > cols) cols = l.length; });
    var width = DAG_PAD * 2 + cols * DAG_W + (cols - 1) * DAG_GX;
    var height = DAG_PAD * 2 + m.layers.length * DAG_H + (m.layers.length - 1) * DAG_GY;
    var drawn = m.nodes.filter(function (n) { return m.isolated.indexOf(n) < 0; });
    var svg = '<svg class="dag-svg" role="img" aria-label="依赖图：' + drawn.length + ' 个节点、' + m.pairs.length + ' 条依赖' +
      (m.isolated.length ? '，另有 ' + m.isolated.length + ' 个无依赖节点' : '') + '" viewBox="0 0 ' + width + ' ' + height +
      '" width="100%" style="max-width:' + width + 'px;height:auto">' +
      '<defs><marker id="dag-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">' +
      '<path class="dag-arrowhead" d="M 0 0 L 10 5 L 0 10 z"/></marker></defs>';
    m.pairs.forEach(function (p) {
      var a = pos[p[0]], b = pos[p[1]];
      if (!a || !b) return;
      var x1 = a.x + DAG_W / 2, y1 = a.y + DAG_H, x2 = b.x + DAG_W / 2, y2 = b.y;
      var midY = y1 + (y2 - y1) / 2;
      svg += '<path class="dag-edge" data-dag-edge="' + esc(p[0] + '|' + p[1]) + '" d="M ' + x1 + ' ' + y1 +
        ' L ' + x1 + ' ' + midY + ' L ' + x2 + ' ' + midY + ' L ' + x2 + ' ' + y2 + '" marker-end="url(#dag-arrow)"/>';
    });
    drawn.forEach(function (id) {
      var p = pos[id];
      if (!p) return;
      var sub = dagSub(subs, id);
      var title = sub ? String(sub.title || '') : '';
      var status = sub ? String(sub.status || '') : '';
      var cls = dagStatusClass(status);
      var label = title ? clipText(title, 20) : '（标题未返回）';
      svg += '<g class="dag-node" data-dag-node="' + esc(id) + '" tabindex="0" role="button" aria-label="' +
        esc(id + (title ? ' ' + title : '') + (status ? '，状态 ' + status : '，状态未返回')) + '">' +
        '<rect class="dag-box" x="' + p.x + '" y="' + p.y + '" width="' + DAG_W + '" height="' + DAG_H + '" rx="8"/>' +
        '<rect class="dag-mark dag-mark-' + esc(cls) + '" x="' + p.x + '" y="' + p.y + '" width="4" height="' + DAG_H + '" rx="2"/>' +
        '<text class="dag-id" x="' + (p.x + 10) + '" y="' + (p.y + 16) + '">' + esc(clipText(id, 20)) + '</text>' +
        '<text class="dag-label" x="' + (p.x + 10) + '" y="' + (p.y + 30) + '">' + esc(label) + '</text>' +
        '<text class="dag-stat" x="' + (p.x + 10) + '" y="' + (p.y + 42) + '">' + esc(status || '状态未返回') + '</text>' +
        '<title>' + esc(id + ' · ' + (title || '标题未返回') + ' · ' + (status || '状态未返回')) + '</title></g>';
    });
    svg += '</svg>';
    var iso = m.isolated.length
      ? '<div class="dag-isolated"><b>无依赖（' + m.isolated.length + '）</b>：' +
        m.isolated.map(function (id) {
          var sub = dagSub(subs, id);
          return '<button type="button" class="chip" data-team-row-jump="' + esc(id) + '">' + esc(id) +
            (sub && sub.title ? ' · ' + esc(clipText(sub.title, 16)) : '') + '</button>';
        }).join(' ') + '</div>'
      : '';
    return '<div class="task-dag">' + head + svg + iso + dagTextHtml(edges) + '</div>';
  }
