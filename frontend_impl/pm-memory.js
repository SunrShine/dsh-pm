/* pm-memory.js —— 记忆卡片「编号 + 取代链」的纯逻辑（task-158；零依赖、不碰 DOM）。
 * 抽出来是为了能单测：短 ID 规则、取代关系（双向）、以及「目标不在本页」的文案。
 * 契约（读模型）：memory 条目 {id, text, type, scope, status, supersedes, supersededBy, revision, …}
 *   supersedes     = 本条**取代**的那条（旧）记忆 id
 *   supersededBy   = 本条**被**哪条（新）记忆取代
 * 缺字段一律按「没有该关系」处理，绝不猜。
 */
export var MEM_SHORT_LEN = 8;

/** 短 ID：去掉 memory- 前缀后取前 8 个字符；空值返回「未写入」 */
export function memoryShortId(id) {
  var text = (id === null || id === undefined) ? '' : String(id);
  if (!text) return '未写入';
  var bare = text.indexOf('memory-') === 0 ? text.slice('memory-'.length) : text;
  return bare.slice(0, MEM_SHORT_LEN) || '未写入';
}

/** 完整 ID：没有就如实返回空串（调用方据此显示「未写入」） */
export function memoryFullId(id) {
  return (id === null || id === undefined) ? '' : String(id);
}

/** 取代关系（**双向**）：[{dir:'supersedes'|'supersededBy', id, short, label}]
 *  - supersedes 用条目自己的字段；
 *  - supersededBy：字段有就用；字段没有时，用同一份列表里「谁的 supersedes 指向我」**推导**出来
 *    （同一事实的另一半，不是猜；后端读模型可能不给反向字段）。
 *  allEntries 省略时不推导（保持单条渲染的纯函数语义）。 */
export function memoryLinks(entry, allEntries) {
  var e = entry || {};
  var out = [];
  if (e.supersedes) {
    out.push({ dir: 'supersedes', id: String(e.supersedes), short: memoryShortId(e.supersedes),
      label: '取代 → ' + memoryShortId(e.supersedes), derived: false });
  }
  if (e.supersededBy) {
    out.push({ dir: 'supersededBy', id: String(e.supersededBy), short: memoryShortId(e.supersededBy),
      label: '被 ' + memoryShortId(e.supersededBy) + ' 取代', derived: false });
  } else if (e.id && allEntries && allEntries.length) {
    for (var i = 0; i < allEntries.length; i++) {
      var other = allEntries[i];
      if (other && other.supersedes && String(other.supersedes) === String(e.id)) {
        out.push({ dir: 'supersededBy', id: String(other.id), short: memoryShortId(other.id),
          label: '被 ' + memoryShortId(other.id) + ' 取代', derived: true });
        break;                                    /* 只取第一条（多条取代同一目标时说明有分叉，界面只显示最直接的一条） */
      }
    }
  }
  return out;
}

/** 列表里的全部条目（候选 + 正式），用于推导反向取代链 */
export function memoryAllEntries(memory) {
  var m = memory || {};
  return [].concat(m.candidates || [], m.entries || []);
}

/** 当前列表里有哪些 id（用于判断「目标不在本页」） */
export function memoryPresentIds(memory) {
  var m = memory || {};
  var ids = [];
  (m.candidates || []).forEach(function (e) { if (e && e.id) ids.push(String(e.id)); });
  (m.entries || []).forEach(function (e) { if (e && e.id) ids.push(String(e.id)); });
  return ids;
}

/** 芯片文案：目标不在本页时写明，不静默 */
export function memoryLinkLabel(link, presentIds) {
  var ids = presentIds || [];
  var here = ids.indexOf(link.id) >= 0;
  return { label: here ? link.label : (link.label + '（目标不在本页）'), present: here };
}

/** 点击后的提示（found=false 时给出可执行的一句话，不静默） */
export function memoryLinkNote(link, present) {
  var dir = link && link.dir === 'supersededBy' ? '被取代' : '取代';
  if (!link) return '';
  if (present) return '已跳到 ' + dir + '目标 ' + memoryShortId(link.id);
  return '这条关系指向 ' + memoryShortId(link.id) + '，但它不在当前列表（可能已废弃、或属于别的 scope）—— 没有可跳转的卡片。';
}

/** 复制结果提示 */
export function memoryCopyNote(ok, id) {
  return ok ? ('已复制完整 ID：' + memoryFullId(id)) : ('复制失败（浏览器不允许剪贴板）—— 完整 ID：' + memoryFullId(id));
}

/** 丢弃结果判定（task-165）：**幂等重放必须如实说「已经丢弃过」**，不能显示成刚丢弃成功。
 *  响应形状：{status:"DEPRECATED", changed, discarded, wasStatus, previousRevision, auditEventId, …}
 *  （字段可能在顶层，也可能在 data 里，两处都认。） */
export function memoryDiscardOutcome(body) {
  var b = body || {};
  var d = b.data || {};
  var changed = (b.changed !== undefined) ? b.changed : d.changed;
  var discarded = (b.discarded !== undefined) ? b.discarded : d.discarded;
  if (changed === false || discarded === false) {
    return { idempotent: true, status: 'DEPRECATED',
      note: '这条候选已经丢弃过（幂等：后端返回 changed:false / discarded:false，没有新的变更）' };
  }
  return { idempotent: false, status: 'DEPRECATED',
    note: '已丢弃：状态变为 DEPRECATED（不物理删除，保留历史、不再进入 AI 上下文）' };
}

/** 失败文案：code：message（不静默、不吞错） */
export function memoryWriteErrorText(code, message) {
  return (code || 'ERROR') + '：' + (message || '后端没有给出 message');
}

/** 合并目标的选择项文案 */
export function memoryMergeOptionText(entry) {
  var e = entry || {};
  /* 不叫 state：它是 pm-state.js 的导出名，扁平模块导出面撞名会被 selfcheck 判死 */
  var statusText = e.status === 'DEPRECATED' ? '（已废弃）' : (e.status === 'CANDIDATE' ? '（候选）' : '（已确认）');
  return memoryShortId(e.id) + ' · ' + String(e.text || '').slice(0, 40) + statusText;
}

/**
 * task-218：把候选区记录按 status 拆成「待确认」与「已处理」（**唯一来源**，计数/徽章/空态/列表共用）。
 *   · pending：status === 'CANDIDATE'（AI/系统提出、还没人确认）
 *   · processed：其余（VERIFIED 已确认 / DEPRECATED 已丢弃 / status 缺失或异常值）
 * 取值口径：**非 CANDIDATE 一律算已处理**（不猜、不把异常值塞进待确认，免得候选区混进"已处理"）。
 */
export function splitCandidates(list) {
  var all = list || [];
  var pending = [], processed = [];
  all.forEach(function (e) {
    if (e && e.status === 'CANDIDATE') pending.push(e);
    else processed.push(e);
  });
  return { all: all, pending: pending, processed: processed };
}

/** 已处理里再分：已确认 / 已丢弃（用于折叠摘要与逐条标记） */
export function processedBreakdown(processed) {
  var verified = 0, deprecated = 0, other = 0;
  (processed || []).forEach(function (e) {
    if (e && e.status === 'VERIFIED') verified++;
    else if (e && e.status === 'DEPRECATED') deprecated++;
    else other++;
  });
  return { verified: verified, deprecated: deprecated, other: other, total: (processed || []).length };
}

/** 折叠摘要的数据部分（total/verified/deprecated/other；**不变量 X+Y+Z === N** 由 splitCandidates 的口径保证） */
export function processedSummaryParts(processed) {
  return processedBreakdown(processed);
}

/** 折叠摘要（zh 逐字，便于判据断言）。
 *  task-227：`other > 0` 时必须补「其他 Z」——否则 N 与 X+Y 对不上（实测过 4 = 2+1 这种）。
 *  en 文案在 pm-i18n.js 的表里（mem.processedSummary / mem.processedSummaryOther），app.js 用 format(t(...)) 拼。 */
export function processedSummaryText(processed) {
  var b = processedBreakdown(processed);
  var base = '已处理 ' + b.total + ' 条（已确认 ' + b.verified + ' / 已丢弃 ' + b.deprecated;
  if (b.other > 0) base += ' / 其他 ' + b.other;
  return base + '）';
}

/** 单条已处理的标记文案（已确认 / 已丢弃 / 原样显示异常状态） */
export function processedStatusChip(e) {
  var s = e && e.status;
  if (s === 'VERIFIED') return '已确认';
  if (s === 'DEPRECATED') return '已丢弃';
  return s ? String(s) : '状态未返回';
}
