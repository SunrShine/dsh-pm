/* pm-attention.js —— 工作台「需要我处理」的纯逻辑（task-184；零依赖、不碰 DOM）。
 *
 * 目标：把「为什么需要你处理」**逐字**说清楚（不能只给徽标），并给一句如实的下一步建议。
 * 判据来源（读模型字段，缺就如实写，不猜）：
 *   observation === 'STALE_BUSY'  → 缓存说它在忙，但记录已陈旧
 *   open_todos > 0               → 还有 N 条未完成 todo
 *   recorded_at                  → 用来算「已 N 天没有新记录」
 */
import { t, format } from './pm-i18n.js';   /* task-C5S1V：模块内文案的唯一出口（本文件 CJK == 0） */

export var DEFAULT_VISIBLE = 7;          /* 长列表默认显示前 N 条（5–8） */
export var STALE_BUSY = 'STALE_BUSY';
/* task-C5S1V：**使用点求值** —— 常量改成函数（模块级常量直接 t() 会在加载期冻结语言） */
export function suggestStale() { return t('attn.suggestStale'); }
export function suggestTodo() { return t('attn.suggestTodo'); }
export function ignoreNote() { return t('attn.ignoreNote'); }
export function noRecordTime() { return t('attn.noRecordTime'); }

/** 已过去多少整天（拿不到时间返回 null） */
export function daysSince(recordedAt, nowMs) {
  if (!recordedAt) return null;
  var t = Date.parse(recordedAt);
  if (isNaN(t)) return null;
  var ms = (typeof nowMs === 'number' ? nowMs : Date.now()) - t;
  if (ms < 0) return 0;
  return Math.floor(ms / 86400000);
}

/** 「为什么需要你处理」的逐字理由（可能多条；都没有就返回空数组，不编） */
export function attentionReasons(card, nowMs) {
  var c = card || {};
  var out = [];
  if (String(c.observation) === STALE_BUSY) {
    var d = daysSince(c.recorded_at, nowMs);
    if (d === null) {
      out.push(format(t('attn.staleUnknownTime'), { time: noRecordTime() }));
    } else if (d >= 1) {
      out.push(format(t('attn.staleDays'), { days: d }));
    } else {
      out.push(t('attn.staleUnderDay'));
    }
  }
  var todos = Number(c.open_todos);
  if (isFinite(todos) && todos > 0) out.push(format(t('attn.todos'), { n: todos }));
  return out;
}

/** 下一步建议（没有判据就不给建议，不写空话） */
export function attentionSuggestion(card) {
  var c = card || {};
  if (String(c.observation) === STALE_BUSY) return suggestStale();
  var todos = Number(c.open_todos);
  if (isFinite(todos) && todos > 0) return suggestTodo();
  return '';
}

/** 按项目分组（保持出现顺序）；titleOf(key) 拿不到就显示 key 本身 */
export function groupByProject(cards, titleOf) {
  var order = [], byKey = {};
  (cards || []).forEach(function (c) {
    var key = String((c && c.project) || t('attn.noProject'));
    if (!byKey[key]) { byKey[key] = { key: key, title: (typeof titleOf === 'function' ? titleOf(key) : '') || key, cards: [] }; order.push(key); }
    byKey[key].cards.push(c);
  });
  return order.map(function (k) { return byKey[k]; });
}

/** 长列表收敛：默认只给前 N 条（分组前后都行 —— 先切再分组，组内也遵守总数） */
export function visibleCards(cards, expanded, limit) {
  var list = cards || [];
  var n = typeof limit === 'number' ? limit : DEFAULT_VISIBLE;
  if (expanded) return list.slice();
  return list.slice(0, Math.max(0, n));
}

/** 折叠状态持久化（一次一个 key；解析失败一律当没折叠，不抛） */
export var COLLAPSE_KEY = 'pm-needsme';

export function parseCollapse(raw) {
  var def = { propsCollapsed: false, cardsCollapsed: false, cardsExpanded: false };
  if (!raw) return def;
  try {
    var o = JSON.parse(raw);
    if (!o || typeof o !== 'object') return def;
    return {
      propsCollapsed: o.propsCollapsed === true,
      cardsCollapsed: o.cardsCollapsed === true,
      cardsExpanded: o.cardsExpanded === true
    };
  } catch (e) { return def; }
}

export function serializeCollapse(st) {
  var s = st || {};
  return JSON.stringify({
    propsCollapsed: s.propsCollapsed === true,
    cardsCollapsed: s.cardsCollapsed === true,
    cardsExpanded: s.cardsExpanded === true
  });
}

/** 展开全部按钮文案（逐字带数字） */
export function expandAllText(total) {
  return format(t('attn.expandAll'), { n: (Number(total) || 0) });
}