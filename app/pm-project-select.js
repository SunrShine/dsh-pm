/* pm-project-select.js —— 项目下拉的**单一实现**（task-217；纯函数、不碰 DOM）。
 *
 * 收件箱「保存为项目笔记」与提案对话框的项目字段都用这一份：
 *   · 「（不指定）」+ 已有项目：**名字优先、key 次要**；同名用 key 消歧（与 task-171 同口径）
 *   · escape hatch：手动输入 key（笔记/提案都可能提到**新**项目，能力不削）
 *   · **未就绪就如实说**（来源由调用方给出，如 GET /ui-pm/cards 或 GET /ui-pm/projects）：
 *     绝不渲染空菜单、也绝不静默交空值
 */
import { t, format } from './pm-i18n.js';   /* task-C5S1V：模块内文案的唯一出口（本文件 CJK == 0） */

export var PROJECT_MANUAL = '__manual__';
export var PROJECT_NEW = '__new__';   /* 「＋ 新建项目…」（批准/提案路径保留） */

/** 显示名：名字优先（title 与 key 不同才叫名字），key 次要 */
export function projectLabel(p) {
  var key = String((p && p.key) || '');
  var title = String((p && p.title) || '');
  return (title && title !== key) ? title : key;
}

/** 未就绪 / 空 的判定：null（还没读到）≠ []（读到了但没有项目） */
export function projectFieldKind(items) {
  if (items === null || items === undefined) return 'not-ready';
  if (!items.length) return 'empty';
  return 'select';
}

/** 选项行：名字优先 + 同名用 key 消歧；prefill 命中的行标 selected */
export function projectOptionRows(items, prefill) {
  var list = items || [];
  var counts = {};
  list.forEach(function (p) { var n = projectLabel(p); counts[n] = (counts[n] || 0) + 1; });
  return list.map(function (p) {
    var name = projectLabel(p);
    if (counts[name] > 1) name = name + ' · ' + String(p.key);   /* 同名消歧 */
    return {
      key: String(p.key),
      label: name,
      secondary: String(p.key),
      selected: String(p.key) === String(prefill || ''),
      inLibrary: p.inLibrary === true
    };
  });
}

export function notReadyText(sourceLabel) {
  return format(t('pselect.notReady'), { source: (sourceLabel || 'GET /ui-pm/cards') });
}

export function emptyText(sourceLabel) {
  return format(t('pselect.empty'), { source: (sourceLabel || 'GET /ui-pm/cards') });
}

/** 字段形态（纯数据，便于单测）：kind + 选项行 + 如实提示 */
export function projectFieldModel(items, prefill, opts) {
  var o = opts || {};
  var kind = projectFieldKind(items);
  if (kind !== 'select') {
    return {
      kind: kind,
      rows: [],
      manualOnly: true,
      placeholder: o.placeholder || t('pselect.placeholder'),
      value: String(prefill || ''),
      note: kind === 'not-ready' ? notReadyText(o.sourceLabel) : emptyText(o.sourceLabel)
    };
  }
  return {
    kind: 'select',
    rows: projectOptionRows(items, prefill),
    manualOnly: false,
    optional: o.optional !== false,
    manualLabel: o.manualLabel || t('pselect.manualLabel'),
    emptyLabel: o.emptyLabel || t('pselect.emptyLabel'),
    newProject: o.withNewProject === true,
    value: String(prefill || '')
  };
}
