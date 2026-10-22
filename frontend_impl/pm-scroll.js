/* pm-scroll.js —— 两轴边缘自动滚动原语（task-146 从 app.js 抽出，**行为不变**）。
 *
 * 设计：纯函数 + 依赖注入，模块作用域**不碰 DOM**（这样 tests/frontend/ 能用 node --test 直接 import，零依赖）。
 * 参数化：threshold（边缘阈值像素，默认 48 —— task-147 借 SortableJS 的 30px 思路，但按我们列宽选 48）、
 *         maxStep（每帧最大速度，默认 18 —— SortableJS 约 10）、throttleMs（速度重算间隔，默认 24ms，借 SortableJS 的节流）、
 *         hRect/hEl/onHScroll（横向容器）、vTargetAt（纵向目标：返回可滚元素）、
 *         vFallbackRect/vFallbackEl（**上层兜底滚动**：指针不在任何列卡片区时滚外层，借 SortableJS 的 bubbleScroll 思路）、
 *         raf/cancelRaf/now（可注入，便于确定性单测）。
 * 到尽头就停：任一轴到 max 立刻把该轴速度清零，不继续累积、不抖动。
 *
 * 用法（app.js）：
 *   var sc = createEdgeAutoScroll({ threshold, maxStep, hRect, hEl, onHScroll, vTargetAt });
 *   sc.move(ev);   // 每次 pointermove
 *   sc.stop();     // 拖动结束 / 取消
 */
export var EDGE_THRESHOLD = 48;      /* 我们实测合适的边缘阈值；SortableJS 默认 30，可用参数覆盖 */
export var EDGE_MAX_STEP = 18;       /* 每帧最大速度（px）；SortableJS 约 10 */
/* 速度重算节流（ms）。SortableJS 约 24ms；我们实测**默认关闭（0）**：
   measure() 只读两次 getBoundingClientRect + 纯算术，很便宜；而 24ms 节流会把「指针反向/离开边缘带」
   的反应最多延后 24ms —— 真机 CDP 实测到列内反向自动滚动因此被吞掉一帧（0→0 而不是 0→16）。
   需要时可用 { throttleMs: 24 } 打开（单测里有专门的用例）。 */
export var EDGE_THROTTLE_MS = 0;

/**
 * 单轴边缘速度：coord 落在 [lo+threshold] 左/上带 → 负；落在 [hi-threshold] 右/下带 → 正。
 * 带内按线性比例（0..maxStep）—— 越靠边越快。区间退化（hi<=lo）返回 0。
 */
export function edgeSpeedFor(coord, lo, hi, threshold, maxStep) {
  if (!(hi > lo)) return 0;
  if (coord < lo + threshold) {
    var ratio = Math.max(0, Math.min(1, (lo + threshold - coord) / threshold));
    return -Math.round(maxStep * ratio);
  }
  if (coord > hi - threshold) {
    var ratio2 = Math.max(0, Math.min(1, (coord - (hi - threshold)) / threshold));
    return Math.round(maxStep * ratio2);
  }
  return 0;
}

/**
 * 造一个两轴边缘自动滚动器。
 * deps: { threshold, maxStep, throttleMs, now(), hRect(), hEl(), onHScroll(el),
 *         vTargetAt(x, y), vFallbackRect(), vFallbackEl(), raf(cb), cancelRaf(handle) }
 */
export function createEdgeAutoScroll(deps) {
  var d = deps || {};
  var threshold = d.threshold === undefined ? EDGE_THRESHOLD : d.threshold;
  var maxStep = d.maxStep === undefined ? EDGE_MAX_STEP : d.maxStep;
  var throttleMs = d.throttleMs === undefined ? EDGE_THROTTLE_MS : d.throttleMs;
  var now = typeof d.now === 'function' ? d.now : function () { return Date.now(); };
  var st = { speed: 0, vspeed: 0, handle: 0, body: null, usesRaf: false, fallback: false, speedsAt: 0, x: 0, y: 0 };

  function raf(cb) {
    if (typeof d.raf === 'function') { st.usesRaf = false; return d.raf(cb); }
    if (typeof window !== 'undefined' && window && typeof window.requestAnimationFrame === 'function') {
      st.usesRaf = true;
      return window.requestAnimationFrame(cb);
    }
    st.usesRaf = false;
    return setTimeout(function () { cb(Date.now()); }, 16);
  }

  function cancel(handle) {
    if (typeof d.cancelRaf === 'function') { d.cancelRaf(handle); return; }
    if (st.usesRaf && typeof window !== 'undefined' && window && typeof window.cancelAnimationFrame === 'function') {
      window.cancelAnimationFrame(handle);
      return;
    }
    if (typeof clearTimeout === 'function') clearTimeout(handle);
  }

  function tick() {
    st.handle = 0;
    var speed = st.speed;
    if (speed) {
      var el = typeof d.hEl === 'function' ? d.hEl() : null;
      if (!el) {
        st.speed = 0;
      } else {
        var max = Math.max(0, (el.scrollWidth || 0) - (el.clientWidth || 0));
        var cur = el.scrollLeft || 0;
        var next = Math.max(0, Math.min(max, cur + speed));
        if (next === cur) st.speed = 0;                        /* 到尽头：不再尝试 */
        else {
          el.scrollLeft = next;                                /* 只改横向容器 */
          if (typeof d.onHScroll === 'function') d.onHScroll(el);
        }
      }
    }
    if (st.vspeed) {
      var vbody = st.body || (st.fallback && typeof d.vFallbackEl === 'function' ? d.vFallbackEl() : null);
      if (!vbody) {
        st.vspeed = 0;                                         /* 兜底也拿不到元素 → 停 */
      } else {
        var vmax = Math.max(0, (vbody.scrollHeight || 0) - (vbody.clientHeight || 0));
        var vcur = vbody.scrollTop || 0;
        var vnext = Math.max(0, Math.min(vmax, vcur + st.vspeed));
        if (vnext === vcur) st.vspeed = 0;                     /* 到尽头就停，不继续累积 */
        else vbody.scrollTop = vnext;                          /* 只改该纵向容器（列卡片区或上层兜底） */
      }
    }
    if (!st.speed && !st.vspeed) return;
    st.handle = raf(tick);
  }

  function loop() {
    if (st.handle) return;
    st.handle = raf(tick);
  }

  /* 重算两轴速度：横向=看板容器；纵向=指针所在列的卡片区；都不在 → 上层兜底（bubbleScroll 思路） */
  function measure(x, y, target) {
    var hr = typeof d.hRect === 'function' ? d.hRect() : null;
    st.speed = (hr && hr.width) ? edgeSpeedFor(x, hr.left, hr.right, threshold, maxStep) : 0;
    st.body = target || null;
    st.fallback = false;
    var br = (target && target.getBoundingClientRect) ? target.getBoundingClientRect() : null;
    st.vspeed = (br && br.height) ? edgeSpeedFor(y, br.top, br.bottom, threshold, maxStep) : 0;
    if (!st.body && st.vspeed === 0 && typeof d.vFallbackRect === 'function') {
      var fr = d.vFallbackRect();
      if (fr && fr.height) {
        st.vspeed = edgeSpeedFor(y, fr.top, fr.bottom, threshold, maxStep);
        st.fallback = st.vspeed !== 0;                         /* 上层兜底：指针不在任何列里 */
      }
    }
  }

  function move(ev) {
    st.x = ev.clientX;
    st.y = ev.clientY;
    var target = typeof d.vTargetAt === 'function' ? d.vTargetAt(st.x, st.y) : null;
    var at = now();
    /* 节流：已经在滚、目标列没变、距上次重算不足 throttleMs → 沿用上次速度（避免每 pointermove 都算） */
    if ((st.speed !== 0 || st.vspeed !== 0) && target === st.body && st.speedsAt &&
        (at - st.speedsAt) < throttleMs) {
      return;
    }
    measure(st.x, st.y, target);
    st.speedsAt = at;
    if (st.speed !== 0 || st.vspeed !== 0) loop();
  }

  function stop() {
    st.speed = 0;
    st.vspeed = 0;
    st.body = null;
    st.fallback = false;
    st.speedsAt = 0;
    if (st.handle) { cancel(st.handle); st.handle = 0; }
  }

  return { move: move, stop: stop, state: st };
}
