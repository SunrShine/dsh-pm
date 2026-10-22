/* pm-kanban.js —— 看板列布局 / 滚动 / 落点判定原语（task-146 从 app.js 抽出，不新增行为）。
 *
 * 纯函数为主、依赖注入：模块作用域不碰 DOM，tests/frontend/ 可直接 import 用 node --test 测（零依赖）。
 * 这里放三件事：
 *   1) 列几何：columnAtPoint（指针命中哪一列，先查拖动开始时缓存的行列矩形）、columnRects（快照）
 *   2) 列滚动：bodyOfColumn / isScrollable（scrollHeight > clientHeight；空列/短列不滚）
 *   3) 落点判定：dropTargetFor / dropReason / dropDecision（§5.2 合法流转 + 「已经在这一列」）
 */
import { t, format } from './pm-i18n.js';   /* task-C5S1V：模块内文案的唯一出口（本文件 CJK == 0） */
export var KANBAN_COL_CLASS = 'kanban-col';
export var KANBAN_BODY_CLASS = 'kanban-body';
export var KANBAN_COL_SELECTOR = '.kanban-col';
export var KANBAN_BODY_SELECTOR = '.kanban-body';

/** 列 key → 该列可接受的状态（按优先级） */
export var BOARD_DROP_TARGETS = {
  todo: ['TODO'],
  doing: ['DOING'],
  blocked: ['BLOCKED', 'WAITING'],
  review: ['REVIEW'],
  closed: ['DONE']
};

/** 列 key → 表头文案 */
export var BOARD_COL_LABELS = {
  /* task-C5S1V：**getter 在使用点求值** —— 表里不放固定文案（放了就会冻结语言）；API 形状与测试不变 */
  get todo() { return t('column.todo'); },
  get doing() { return t('column.doing'); },
  get blocked() { return t('column.blocked'); },
  get review() { return t('column.review'); },
  get closed() { return t('column.closed'); }
};

/** 状态 → 它所在的列 key（用于「已经在这一列」判定） */
export var STATUS_GROUP = {
  INBOX: 'todo', TODO: 'todo', NEXT: 'todo', DOING: 'doing', WAITING: 'blocked',
  BLOCKED: 'blocked', REVIEW: 'review', DONE: 'closed', CANCELLED: 'closed'
};

export function nodeIsColumn(node) {
  return !!(node && node.classList && typeof node.classList.contains === 'function' && node.classList.contains(KANBAN_COL_CLASS));
}

/**
 * 指针命中哪一列：先查缓存矩形（拖动开始时的快照，避免拖动中布局变化引起误判），
 * 再退回 elementFromPoint 向上找 .kanban-col。
 * deps: { cachedRects: [{col, rect}], elementFromPoint(x, y), isColumnNode(node), stopAt(node) }
 */
export function columnAtPoint(x, y, deps) {
  var d = deps || {};
  var cached = d.cachedRects || [];
  for (var i = 0; i < cached.length; i++) {
    var entry = cached[i];
    var r = entry && entry.rect;
    if (r && x >= r.left && x <= r.right && y >= r.top && y <= r.bottom) return entry.col;
  }
  var node = typeof d.elementFromPoint === 'function' ? d.elementFromPoint(x, y) : null;
  var stopAt = d.stopAt || null;
  var isCol = typeof d.isColumnNode === 'function' ? d.isColumnNode : nodeIsColumn;
  while (node && node !== stopAt) {
    if (isCol(node)) return node;
    node = node.parentNode;
  }
  return null;
}

/** 列里的卡片滚动区（没有该节点就返回 null —— 调用方据此不滚） */
export function bodyOfColumn(col) {
  return (col && typeof col.querySelector === 'function') ? col.querySelector(KANBAN_BODY_SELECTOR) : null;
}

/** 有内容可滚吗（空列 / 短列 → false，界面上不出现无意义滚动条） */
export function isScrollable(el) {
  if (!el) return false;
  return (el.scrollHeight || 0) > (el.clientHeight || 0);
}

/** 拖动开始时给每列拍矩形快照（拿不到 rect 时退化为全 0，命中不了但不会崩） */
export function columnRects(cols, getRect) {
  return (cols || []).map(function (col) {
    var rect = typeof getRect === 'function' ? getRect(col)
      : (col && typeof col.getBoundingClientRect === 'function' ? col.getBoundingClientRect() : null);
    return { col: col, rect: rect || { left: 0, right: 0, top: 0, bottom: 0 } };
  });
}

/**
 * 这一列能不能接住 fromStatus：在列的可接受状态里取第一个「§5.2 合法」的。
 * deps: { targets, allowed }
 */
export function dropTargetFor(colKey, fromStatus, deps) {
  var d = deps || {};
  var cands = (d.targets || BOARD_DROP_TARGETS)[colKey] || [];
  var allowed = d.allowed || [];
  for (var i = 0; i < cands.length; i++) { if (allowed.indexOf(cands[i]) >= 0) return cands[i]; }
  return null;
}

/** 不能落时的原因文案（与改造前逐字一致） */
export function dropReason(colKey, fromStatus, deps) {
  var d = deps || {};
  var labels = d.labels || BOARD_COL_LABELS;
  var statusLabels = d.statusLabels || {};
  var label = labels[colKey] || colKey;
  var allowed = d.allowed || [];
  return format(t('kanban.dropReason'), {
    status: (statusLabels[fromStatus] || fromStatus || t('kanban.statusUnknown')), col: label
  }) + (allowed.length
    ? format(t('kanban.dropAllowed'), { list: allowed.map(function (s) { return statusLabels[s] || s; }).join(' / ') })
    : t('kanban.dropTerminal'));
}

/** 落点判定：{ target, ok, reason }（ok=true 时 reason 为空） */
export function dropDecision(colKey, fromStatus, deps) {
  var d = deps || {};
  var target = dropTargetFor(colKey, fromStatus, d);
  var group = (d.statusGroup || STATUS_GROUP)[fromStatus];
  if (!target) return { target: null, ok: false, reason: dropReason(colKey, fromStatus, d) };
  if (target === fromStatus || colKey === group) return { target: target, ok: false, reason: t('kanban.sameColumn') };
  return { target: target, ok: true, reason: '' };
}
