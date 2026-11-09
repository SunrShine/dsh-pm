/* tests/frontend/pm-scroll.test.mjs —— task-146 原语单测（Node 内置 node --test，零依赖）。
 * 只测纯逻辑：pm-scroll.js 不碰 DOM，这里注入假的 rect / 可滚元素 / raf。 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { EDGE_THRESHOLD, EDGE_MAX_STEP, edgeSpeedFor, createEdgeAutoScroll } from '../../frontend_impl/pm-scroll.js';

/* 一个假的可滚容器：scrollWidth/clientWidth 固定，记录写入 */
function fakeAxis(size, view) {
  return {
    scrollWidth: size, clientWidth: view, scrollHeight: size, clientHeight: view,
    scrollLeft: 0, scrollTop: 0,
    /* 纵向速度按被拖列的 getBoundingClientRect 算（与原实现一致） */
    getBoundingClientRect: () => ({ left: 0, right: view, top: 0, bottom: view, width: view, height: view }),
  };
}

/* 手动 raf：把回调按 id 存起来，测试自己决定跑几帧；cancelRaf 真的把回调移除（否则测不出「取消了」） */
function manualRaf() {
  const queue = new Map();
  let nextId = 1;
  const take = () => {
    const first = queue.entries().next();
    if (first.done) return null;
    const [id, cb] = first.value;
    queue.delete(id);
    return cb;
  };
  return {
    raf: (cb) => { const id = nextId; nextId += 1; queue.set(id, cb); return id; },
    cancelRaf: (id) => { queue.delete(id); },
    pending: () => queue.size,
    runFrame: () => { const cb = take(); if (cb) cb(Date.now()); },
    runAll: (n) => { for (let i = 0; i < n; i += 1) { const cb = take(); if (!cb) return i; cb(Date.now()); } return n; },
  };
}

test('edgeSpeedFor：阈值带外为 0，带内按比例，方向左右/上下对称', () => {
  const lo = 100, hi = 400, th = 48, step = 18;
  assert.equal(edgeSpeedFor(250, lo, hi, th, step), 0, '中间 → 0');
  assert.equal(edgeSpeedFor(101, lo, hi, th, step), -18, '最左 → -maxStep');
  assert.equal(edgeSpeedFor(399, lo, hi, th, step), 18, '最右 → +maxStep');
  assert.equal(edgeSpeedFor(lo + th, lo, hi, th, step), 0, '刚进左带边界 → 0');
  assert.equal(edgeSpeedFor(lo + th - 12, lo, hi, th, step), -5, '左带内 1/4 处 → -5（线性比例后取整）');
  assert.equal(edgeSpeedFor(hi - th, lo, hi, th, step), 0, '刚进右带边界 → 0');
  assert.ok(edgeSpeedFor(lo - 999, lo, hi, th, step) === -18, '带外更远也按满速（与改造前一致）');
});

test('edgeSpeedFor：参数化（阈值变大 → 更早开始滚；maxStep 变大 → 每帧更快）', () => {
  const lo = 0, hi = 300;
  assert.equal(edgeSpeedFor(20, lo, hi, 10, 18), 0, '阈值 10 时 20px 处不算边缘');
  assert.ok(edgeSpeedFor(20, lo, hi, 48, 18) < 0, '阈值 48 时 20px 处算边缘');
  assert.equal(edgeSpeedFor(1, lo, hi, 48, 5), -5, 'maxStep=5 → 满速 5');
  assert.equal(edgeSpeedFor(0, lo, hi, 48, 40), -40, 'maxStep=40 → 满速 40');
  assert.equal(edgeSpeedFor(5, 10, 10, 48, 18), 0, '退化区间（hi<=lo）→ 0');
  assert.equal(edgeSpeedFor(0, lo, hi, 48, 40), -40, '正中边缘（ratio=1）→ 满速');
  assert.equal(edgeSpeedFor(1, lo, hi, 48, 40), -39, '差 1px → 39（按比例四舍五入，与原实现同式）');
});

test('createEdgeAutoScroll：中间位置不启动，靠边启动并按帧滚动', () => {
  const board = fakeAxis(1200, 400);
  const body = fakeAxis(800, 300);
  const frames = manualRaf();
  let syncs = 0;
  const sc = createEdgeAutoScroll({
    hRect: () => ({ left: 0, right: 400, top: 0, bottom: 300, width: 400, height: 300 }),
    hEl: () => board,
    onHScroll: () => { syncs += 1; },
    vTargetAt: () => body,
    raf: frames.raf, cancelRaf: frames.cancelRaf,
  });
  sc.move({ clientX: 200, clientY: 150 });                    /* 中间：两轴都 0 */
  assert.equal(sc.state.speed, 0);
  assert.equal(sc.state.vspeed, 0);
  assert.equal(frames.pending(), 0, '不该排帧');

  sc.move({ clientX: 399, clientY: 299 });                    /* 右边缘 + 底边缘 */
  assert.ok(sc.state.speed > 0, '横向速度为右');
  assert.ok(sc.state.vspeed > 0, '纵向速度向下');
  assert.equal(frames.pending(), 1, '排了一帧');
  frames.runFrame();
  assert.ok(board.scrollLeft > 0, '横向容器被滚了');
  assert.equal(syncs, 1, 'onHScroll 被调用（原实现里的 __syncArrows）');
  assert.ok(body.scrollTop > 0, '纵向容器被滚了');
  assert.equal(frames.pending(), 1, '还有速度 → 继续排帧');
});

test('createEdgeAutoScroll：到尽头停住，不会越界', () => {
  const board = fakeAxis(420, 400);                           /* 只能滚 20px */
  const body = fakeAxis(310, 300);                            /* 只能滚 10px */
  const frames = manualRaf();
  const sc = createEdgeAutoScroll({
    hRect: () => ({ left: 0, right: 400, top: 0, bottom: 300, width: 400, height: 300 }),
    hEl: () => board,
    vTargetAt: () => body,
    raf: frames.raf, cancelRaf: frames.cancelRaf,
  });
  sc.move({ clientX: 400, clientY: 300 });
  frames.runAll(12);
  assert.equal(board.scrollLeft, 20, '横向顶到 max 就不动了');
  assert.equal(body.scrollTop, 10, '纵向顶到 max 就不动了');
  assert.equal(sc.state.speed, 0);
  assert.equal(sc.state.vspeed, 0);
  assert.equal(frames.pending(), 0, '两轴都到尽头 → 不再排帧');
});

test('createEdgeAutoScroll：上/左边缘往回滚（方向相反）', () => {
  const board = fakeAxis(1200, 400);
  const body = fakeAxis(800, 300);
  const frames = manualRaf();
  const sc = createEdgeAutoScroll({
    hRect: () => ({ left: 0, right: 400, top: 0, bottom: 300, width: 400, height: 300 }),
    hEl: () => board,
    vTargetAt: () => body,
    raf: frames.raf, cancelRaf: frames.cancelRaf,
  });
  board.scrollLeft = 300; body.scrollTop = 200;
  sc.move({ clientX: 0, clientY: 0 });                        /* 左上角 */
  assert.ok(sc.state.speed < 0);
  assert.ok(sc.state.vspeed < 0);
  frames.runAll(3);
  assert.ok(board.scrollLeft < 300);
  assert.ok(body.scrollTop < 200);
});

test('createEdgeAutoScroll：空列 / 短列 / 缺容器都安全（不滚、不崩、不排帧）', () => {
  const frames = manualRaf();
  const emptyBody = { scrollHeight: 100, clientHeight: 100, scrollTop: 0, getBoundingClientRect: () => ({ top: 0, bottom: 100, height: 100 }) };
  const sc = createEdgeAutoScroll({
    hRect: () => null,                                        /* 拿不到看板 rect */
    hEl: () => null,
    vTargetAt: () => emptyBody,                               /* 空列：没有可滚高度 */
    raf: frames.raf, cancelRaf: frames.cancelRaf,
  });
  sc.move({ clientX: 10, clientY: 99 });
  assert.equal(sc.state.speed, 0, '没有横向容器 → 0');
  assert.ok(sc.state.vspeed > 0, '底边缘：按 rect 算出速度（与原实现一致）');
  frames.runAll(2);
  assert.equal(emptyBody.scrollTop, 0, '但空列无可滚高度 → 实际一个像素都不动');
  assert.equal(sc.state.vspeed, 0, '到尽头（max=0）后速度清零');
  assert.equal(frames.pending(), 0, '不再排帧');

  sc.move({ clientX: 10, clientY: 50 });
  assert.equal(frames.pending(), 0, '中间位置也不排帧');
  sc.stop();
  assert.equal(sc.state.handle, 0);
});

test('createEdgeAutoScroll：stop() 清零并取消（拖动结束/取消路径）', () => {
  const board = fakeAxis(1200, 400);
  const frames = manualRaf();
  let cancelled = 0;
  const sc = createEdgeAutoScroll({
    hRect: () => ({ left: 0, right: 400, top: 0, bottom: 300, width: 400, height: 300 }),
    hEl: () => board,
    vTargetAt: () => null,
    raf: frames.raf,
    cancelRaf: (id) => { cancelled += 1; frames.cancelRaf(id); },
  });
  sc.move({ clientX: 10, clientY: 150 });
  assert.ok(sc.state.handle > 0);
  sc.stop();
  assert.equal(sc.state.speed, 0);
  assert.equal(sc.state.vspeed, 0);
  assert.equal(sc.state.handle, 0);
  assert.equal(cancelled, 1, '取消了一次排帧');
  assert.equal(frames.pending(), 0);
});

test('默认常量与 app.js 原实现一致（48 / 18）', () => {
  assert.equal(EDGE_THRESHOLD, 48);
  assert.equal(EDGE_MAX_STEP, 18);
});

test('上层兜底（bubbleScroll 思路）：指针不在任何列里时滚外层容器', () => {
  const page = fakeAxis(2000, 800);
  const frames = manualRaf();
  let clock = 1000;
  const sc = createEdgeAutoScroll({
    hRect: () => null,                                        /* 只看纵向兜底 */
    hEl: () => null,
    vTargetAt: () => null,                                    /* 不在任何列的卡片区里 */
    vFallbackRect: () => ({ top: 0, bottom: 800, height: 800 }),
    vFallbackEl: () => page,
    now: () => clock,
    raf: frames.raf, cancelRaf: frames.cancelRaf,
  });
  sc.move({ clientX: 700, clientY: 795 });                    /* 视口底部、列外 */
  assert.ok(sc.state.vspeed > 0, '兜底也要给出向下速度');
  assert.equal(sc.state.fallback, true, '标记为兜底中');
  frames.runFrame();
  assert.ok(page.scrollTop > 0, '外层被滚了');
  clock += 30;                                                /* 越过节流窗口 */
  sc.move({ clientX: 700, clientY: 400 });                    /* 视口中间、列外 */
  assert.equal(sc.state.vspeed, 0, '中间位置兜底速度也应为 0');
  assert.equal(sc.state.fallback, false, '不再标记兜底');
});

test('负例：没有兜底元素 / 不在列的上下边缘 → 不滚、不崩', () => {
  const frames = manualRaf();
  const sc = createEdgeAutoScroll({
    hRect: () => null,
    hEl: () => null,
    vTargetAt: () => null,
    vFallbackRect: () => ({ top: 0, bottom: 800, height: 800 }),
    vFallbackEl: () => null,                                  /* 兜底元素拿不到 */
    raf: frames.raf, cancelRaf: frames.cancelRaf,
  });
  sc.move({ clientX: 10, clientY: 799 });
  assert.ok(sc.state.vspeed > 0, '先算出速度');
  frames.runFrame();
  assert.equal(sc.state.vspeed, 0, '拿不到元素 → 速度清零，不排帧');
  assert.equal(frames.pending(), 0);
  sc.move({ clientX: 10, clientY: 400 });
  assert.equal(sc.state.vspeed, 0, '中间位置 → 0');
  assert.equal(sc.state.fallback, false);
});

test('节流（throttleMs）：滚动中不每帧重算；目标列变了立刻重算；throttleMs=0 关闭节流', () => {
  let clock = 1000;
  let rectCalls = 0;
  const body = fakeAxis(800, 300);
  const frames = manualRaf();
  const sc = createEdgeAutoScroll({
    hRect: () => { rectCalls += 1; return { left: 0, right: 400, top: 0, bottom: 300, width: 400, height: 300 }; },
    hEl: () => null,
    vTargetAt: () => body,
    throttleMs: 24,
    now: () => clock,
    raf: frames.raf, cancelRaf: frames.cancelRaf,
  });
  sc.move({ clientX: 399, clientY: 299 });
  assert.equal(rectCalls, 1, '首次必算');
  clock += 5;
  sc.move({ clientX: 399, clientY: 299 });                    /* 距上次 5ms < 24ms */
  assert.equal(rectCalls, 1, '节流窗口内不重算');
  clock += 30;
  sc.move({ clientX: 399, clientY: 299 });
  assert.equal(rectCalls, 2, '过了窗口就重算');

  /* 目标列变化 → 立刻重算（不等窗口） */
  const other = fakeAxis(800, 300);
  let current = body;
  const sc2 = createEdgeAutoScroll({
    hRect: () => ({ left: 0, right: 400, top: 0, bottom: 300, width: 400, height: 300 }),
    hEl: () => null,
    vTargetAt: () => current,
    throttleMs: 999,
    now: () => clock,
    raf: frames.raf, cancelRaf: frames.cancelRaf,
  });
  sc2.move({ clientX: 399, clientY: 299 });
  current = other;
  clock += 1;
  sc2.move({ clientX: 399, clientY: 299 });
  assert.equal(sc2.state.body, other, '换了目标列 → 立刻重算');

  /* throttleMs:0 → 每次都算 */
  let calls0 = 0;
  const sc3 = createEdgeAutoScroll({
    hRect: () => { calls0 += 1; return null; },
    vTargetAt: () => body,
    throttleMs: 0,
    now: () => clock,
    raf: frames.raf, cancelRaf: frames.cancelRaf,
  });
  sc3.move({ clientX: 1, clientY: 1 });
  sc3.move({ clientX: 1, clientY: 1 });
  assert.equal(calls0, 2, 'throttleMs=0 → 不节流');
});

test('参数化：阈值 30（SortableJS 默认）与 48 的差异，速度上限可调', () => {
  const lo = 0, hi = 600;
  assert.equal(edgeSpeedFor(40, lo, hi, 30, 10), 0, '30px 阈值：40px 处不算边缘');
  assert.ok(edgeSpeedFor(40, lo, hi, 48, 10) < 0, '48px 阈值：40px 处算边缘');
  assert.equal(edgeSpeedFor(0, lo, hi, 48, 10), -10, '上限 10 px/帧（SortableJS 量级）');
  assert.equal(edgeSpeedFor(0, lo, hi, 48, 18), -18, '上限 18 px/帧（我们的现值）');
});
