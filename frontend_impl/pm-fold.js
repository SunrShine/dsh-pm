/* pm-fold.js —— 原生 <details> 展开态的**单一实现**（task-209）。
 *
 * 问题：render() 整体重建 innerHTML，而 <details open> 只活在 DOM 里 → 任何重渲染（点卡片会
 *      selectTask → render()）都会把用户展开的终态列打回关闭态。
 * 做法：状态存进 map（app 用 state.folds，动态属性，不新增第二套折叠状态），渲染时**回填 open**，
 *      并监听原生 toggle（不冒泡 → 捕获阶段）把用户操作写回 map。**不做**"渲染后强制展开"的兜底。
 */
export var FOLD_KEY_ATTR = 'data-fold-key';

/** 该折叠键是否展开（defaultOpen=true 时，除非用户显式关过） */
export function foldIsOpen(map, key, defaultOpen) {
  var m = map || {};
  var v = m[key];
  if (typeof v === 'boolean') return v;
  return defaultOpen === true;
}

/** 写回一次用户操作（返回新 map，便于单测） */
export function setFold(map, key, open) {
  var m = map || {};
  m[key] = open === true;
  return m;
}

/** 折叠键：同一视图中唯一即可（列 key + 项目；或功能前缀 + 实体 id） */
export function foldKey() {
  return Array.prototype.filter.call(arguments, function (x) { return x !== undefined && x !== null && x !== ''; }).join(':');
}

/** 受控 <details> 的属性串（data-fold-key + open）——纯模块（如 pm-dag）复用它，避免第二套实现 */
export function foldAttrs(map, key, defaultOpen) {
  var open = foldIsOpen(map, key, defaultOpen === true);
  return ' data-fold-key="' + String(key) + '"' + (open ? ' open' : '');
}

/** 渲染一个受控 <details>：open 由 map 决定；带 data-fold-key 供 toggle 委派写回 */
export function foldDetailsHtml(map, key, summaryHtml, bodyHtml, opts) {
  var o = opts || {};
  return '<details' + (o.cls ? ' class="' + o.cls + '"' : '') + foldAttrs(map, key, o.defaultOpen) +
    (o.attrs ? ' ' + o.attrs : '') + '>' +
    '<summary>' + summaryHtml + '</summary>' + bodyHtml + '</details>';
}

/** 从一次 toggle 事件目标找到 dataset 键（事件不冒泡 → 调用方要用捕获阶段） */
export function foldKeyFromTarget(target) {
  var el = target;
  while (el && el.getAttribute) {
    var k = el.getAttribute(FOLD_KEY_ATTR);
    if (k) return { key: k, open: el.open === true };
    el = el.parentElement;
  }
  return null;
}
