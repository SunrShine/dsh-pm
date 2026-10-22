/* pm-session.js —— 向导「④ 指派会话」列表的纯逻辑（task-171；只依赖文案表（task-C5S1V 起 import t/format）、不碰 DOM）。
 *
 * 读模型事实（task-170）：每个会话可能带
 *   session_mode   'continuable'（被 spawn 的 subagent / 团队队友）/ 'one-shot'（普通会话）/ null（投影里没有）
 *   session_label  队友名字（原样）
 *   session_title  title 原样（**可能是注入文本**，例如 '<system-reminder> You are teammate "pm-f…'）
 *   session_name   清洗后的展示名：label → 非注入 title → null
 * 这里只做「分类 + 取名字 + 同名消歧」，拿不到就如实返回 null / 提示缺字段，不猜。
 */
import { t, format } from './pm-i18n.js';   /* task-C5S1V：模块内文案的唯一出口（本文件 CJK == 0） */
export var SESSION_SHORT_LEN = 8;
/* task-C5S1V：**使用点求值** —— 模块级常量不能直接 t()（加载期求值会冻结语言） */
export function noNameText() { return t('session.noName'); }
export var CONTINUABLE = 'continuable';
export var ONE_SHOT = 'one-shot';

/** session-<uuid> → 8 位短 id（去前缀；拿不到就返回空串） */
export function sessionShortId(id) {
  var text = (id === null || id === undefined) ? '' : String(id);
  if (!text) return '';
  var bare = text.indexOf('session-') === 0 ? text.slice('session-'.length) : text;
  return bare.slice(0, SESSION_SHORT_LEN);
}

/** 这条会话在界面上该叫什么：session_name → label → 非注入 title → 「无标题会话 · 短id」 */
export function sessionDisplayName(session) {
  var s = session || {};
  var name = (s.session_name || '').trim ? String(s.session_name || '').trim() : '';
  if (name) return name;
  var label = String(s.session_label || '').trim();
  if (label) return label;
  var title = String(s.session_title || '').trim();
  if (title && title.charAt(0) !== '<') return title;      /* '<' 开头视为注入文本，不当名字 */
  var short = sessionShortId(s.id || s.session_id);
  return short ? (noNameText() + ' · ' + short) : noNameText();
}

/** 身份字段齐不齐：三个身份字段全缺 → 视为「本实例未返回会话身份字段」 */
export function sessionIdentityMissing(session) {
  var s = session || {};
  return !s.session_mode && !s.session_label && !s.session_title && !s.session_name;
}

/** 把 cards 里的身份字段按 session_id 补到会话对象上（同一份会话，后端 context 端点还没带这些字段） */
export function mergeIdentity(session, cardsById) {
  var s = Object.assign({}, session || {});
  if (sessionIdentityMissing(s) && cardsById) {
    var key = String(s.id || s.session_id || '');
    var card = cardsById[key];
    if (card) {
      ['session_mode', 'session_label', 'session_title', 'session_name'].forEach(function (k) {
        if (s[k] === undefined || s[k] === null || s[k] === '') s[k] = card[k] === undefined ? null : card[k];
      });
    }
  }
  return s;
}

/** [{id, ...}] → {key: card}（按 session_id 索引） */
export function cardsById(cards) {
  var out = {};
  (cards || []).forEach(function (c) { if (c && c.session_id) out[String(c.session_id)] = c; });
  return out;
}

/**
 * 分类：真会话 / 子 agent 或团队队友 / 身份未知（字段缺失）。
 * - real：session_mode !== 'continuable' 且字段齐全（含 one-shot）
 * - peers：session_mode === 'continuable'
 * - unknown：身份字段全缺（**不能**据此隐藏，要显示 + 如实提示）
 * 同名时给短 id 消歧（在 name 后附 ' · 短id'）。
 */
export function partitionSessions(sessions, index) {
  var list = (sessions || []).map(function (s) { return mergeIdentity(s, index); });
  var real = [], peers = [], unknown = [];
  list.forEach(function (s) {
    if (sessionIdentityMissing(s)) unknown.push(s);
    else if (String(s.session_mode) === CONTINUABLE) peers.push(s);
    else real.push(s);
  });
  var counts = {};
  real.concat(peers, unknown).forEach(function (s) {
    var n = sessionDisplayName(s);
    counts[n] = (counts[n] || 0) + 1;
  });
  var label = function (s) {
    var n = sessionDisplayName(s);
    if (counts[n] > 1) {
      var short = sessionShortId(s.id || s.session_id);
      if (short && n.indexOf(short) < 0) return n + ' · ' + short;
    }
    return n;
  };
  return {
    real: real, peers: peers, unknown: unknown, counts: counts,
    identityMissing: unknown.length > 0,
    label: label
  };
}

/** 默认显示哪些（真会话 + 身份未知的；continuable 要开关才出现） */
export function visibleSessions(parts, showPeers) {
  var p = parts || { real: [], peers: [], unknown: [] };
  return showPeers ? p.real.concat(p.peers, p.unknown) : p.real.concat(p.unknown);
}

/** 开关文案：不静默隐藏，数字写在开关上 */
export function peerToggleText(parts) {
  var n = ((parts || {}).peers || []).length;
  return format(t('session.peerToggle'), { n: n });
}
