import { setLang } from '../../frontend_impl/pm-i18n.js';
/* task-C5S1V：本文件逐字比对中文文案 ⇒ 显式钉住语言（默认语言一变就会莫名红） */
setLang('zh');

/* tests/frontend/pm-kanban.test.mjs —— task-146 看板原语单测（node --test，零依赖）。 */
import test from 'node:test';
import assert from 'node:assert/strict';
import {

  BOARD_COL_LABELS, BOARD_DROP_TARGETS, STATUS_GROUP, nodeIsColumn, columnAtPoint,
  bodyOfColumn, isScrollable, columnRects, dropTargetFor, dropReason, dropDecision,
} from '../../frontend_impl/pm-kanban.js';

const col = (key) => ({ key });

test('nodeIsColumn：只看 classList.contains', () => {
  assert.equal(nodeIsColumn({ classList: { contains: (c) => c === 'kanban-col' } }), true);
  assert.equal(nodeIsColumn({ classList: { contains: () => false } }), false);
  assert.equal(nodeIsColumn(null), false);
  assert.equal(nodeIsColumn({}), false);
});

test('columnAtPoint：优先用拖动缓存的矩形，其次 elementFromPoint 向上找列', () => {
  const c1 = col('todo'), c2 = col('review');
  const cached = [{ col: c1, rect: { left: 0, right: 100, top: 0, bottom: 300 } }, { col: c2, rect: { left: 100, right: 200, top: 0, bottom: 300 } }];
  assert.equal(columnAtPoint(50, 150, { cachedRects: cached }), c1);
  assert.equal(columnAtPoint(150, 150, { cachedRects: cached }), c2);
  assert.equal(columnAtPoint(150, 400, { cachedRects: cached }), null, 'y 超出 → 不命中');

  /* 缓存不命中 → 退回 DOM：卡片里的 span → card → column */
  const columnNode = { classList: { contains: (c) => c === 'kanban-col' }, parentNode: null };
  const card = { classList: { contains: () => false }, parentNode: columnNode };
  const span = { classList: { contains: () => false }, parentNode: card };
  const body = { tag: 'body' };
  assert.equal(columnAtPoint(5, 5, { cachedRects: [], elementFromPoint: () => span, stopAt: body }), columnNode);
  assert.equal(columnAtPoint(5, 5, { cachedRects: [], elementFromPoint: () => null, stopAt: body }), null);
});

test('columnAtPoint：走到 stopAt 就停下，不会无限往上', () => {
  const body = { classList: { contains: () => false }, parentNode: null };
  assert.equal(columnAtPoint(1, 1, { cachedRects: [], elementFromPoint: () => body, stopAt: body }), null);
});

test('bodyOfColumn / isScrollable：空列与短列不滚', () => {
  const body = { scrollHeight: 400, clientHeight: 382 };
  assert.equal(bodyOfColumn({ querySelector: (s) => (s === '.kanban-body' ? body : null) }), body);
  assert.equal(bodyOfColumn(null), null);
  assert.equal(bodyOfColumn({}), null);
  assert.equal(isScrollable(body), true, '内容高于可视区 → 可滚');
  assert.equal(isScrollable({ scrollHeight: 382, clientHeight: 382 }), false, '正好相等 → 不滚');
  assert.equal(isScrollable({ scrollHeight: 100, clientHeight: 382 }), false, '空列 → 不滚');
  assert.equal(isScrollable(null), false);
});

test('columnRects：拍矩形快照；拿不到 rect 退化为全 0（命中不了但不崩）', () => {
  const a = { getBoundingClientRect: () => ({ left: 1, right: 2, top: 3, bottom: 4 }) };
  const b = {};
  const rects = columnRects([a, b]);
  assert.equal(rects.length, 2);
  assert.deepEqual(rects[0].rect, { left: 1, right: 2, top: 3, bottom: 4 });
  assert.deepEqual(rects[1].rect, { left: 0, right: 0, top: 0, bottom: 0 });
  assert.equal(columnRects(null).length, 0);
});

test('dropTargetFor：按列的可接受状态优先级取第一个合法状态；没有 → null', () => {
  assert.equal(dropTargetFor('doing', 'TODO', { allowed: ['DOING'] }), 'DOING');
  assert.equal(dropTargetFor('blocked', 'DOING', { allowed: ['WAITING', 'BLOCKED'] }), 'BLOCKED', 'blocked 列优先 BLOCKED');
  assert.equal(dropTargetFor('blocked', 'DOING', { allowed: ['WAITING'] }), 'WAITING');
  assert.equal(dropTargetFor('closed', 'REVIEW', { allowed: ['DONE'] }), 'DONE');
  assert.equal(dropTargetFor('review', 'TODO', { allowed: ['DOING'] }), null);
  assert.equal(dropTargetFor('nope', 'TODO', { allowed: ['TODO'] }), null);
});

test('dropReason：合法去向 / 终态两种文案', () => {
  const deps = { allowed: ['DOING', 'BLOCKED'], statusLabels: { TODO: '待办', DOING: '执行中', BLOCKED: '受阻' }, labels: BOARD_COL_LABELS };
  assert.equal(dropReason('review', 'TODO', deps),
    '状态 待办 没有到「待验收」列的合法流转（§5.2）；合法去向：执行中 / 受阻');
  assert.equal(dropReason('doing', 'DONE', { allowed: [], statusLabels: { DONE: '已完成' } }),
    '状态 已完成 没有到「执行中」列的合法流转（§5.2）；这是终态，不能流转');
});

test('dropDecision：可以落 / 非法 / 已经在这一列', () => {
  const base = { allowed: ['DOING'], statusLabels: { TODO: '待办', DOING: '执行中' } };
  assert.deepEqual(dropDecision('doing', 'TODO', base), { target: 'DOING', ok: true, reason: '' });
  const illegal = dropDecision('review', 'TODO', base);
  assert.equal(illegal.ok, false);
  assert.equal(illegal.target, null);
  assert.match(illegal.reason, /没有到「待验收」列的合法流转/);
  const same = dropDecision('doing', 'DOING', { allowed: ['DOING'] });
  assert.equal(same.ok, false);
  assert.equal(same.reason, '已经在这一列');
  const sameCol = dropDecision('todo', 'NEXT', { allowed: ['TODO'] });      /* NEXT 本来就在 todo 列 */
  assert.equal(sameCol.target, 'TODO');
  assert.equal(sameCol.ok, false);
  assert.equal(sameCol.reason, '已经在这一列');
});

test('表常量：五列标签、状态归组、可接受状态（与改造前逐字一致）', () => {
  assert.deepEqual(BOARD_COL_LABELS, { todo: '待办', doing: '执行中', blocked: '受阻', review: '待验收', closed: '已结束' });
  assert.deepEqual(BOARD_DROP_TARGETS, { todo: ['TODO'], doing: ['DOING'], blocked: ['BLOCKED', 'WAITING'], review: ['REVIEW'], closed: ['DONE'] });
  assert.equal(STATUS_GROUP.NEXT, 'todo');
  assert.equal(STATUS_GROUP.WAITING, 'blocked');
  assert.equal(STATUS_GROUP.CANCELLED, 'closed');
});
