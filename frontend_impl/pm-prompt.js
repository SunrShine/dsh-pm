/* frontend_impl/pm-prompt.js —— 初始系统提示词页（task-265，内部记录/25）。
 *
 * 风格来源（Lead 2026-10-19 机械对齐）：markup 类名**一律取自设计示例** 内部记录/25-初始系统提示词.示例.html；
 *   样式表由 scripts/build_prompt_page_css.py 从示例的 <style> 机械生成（frontend_impl/pm-prompt.page.css，
 *   逐字节一致性由 scripts/verify_prompt_page_css_sync.py 守着，禁止手改数值）。
 *
 * 定位（内部记录/25 §0/§1）：主体是**人写的提示词**（可编辑资产），粒度=每个项目一份，存 projects/proj-<key>/prompt.org（人工文件）；
 *   预览 = **已填块按顺序渲染**（「# 块名」+ 正文 + 空行；引用文档按 §3.5 展开并标注来源）⇒ **纯函数结果，不是运行时上下文** ✓。
 * 边界（§4 照抄）：运行时上下文由 DSH 管理 —— 本页不管、不猜、不显示；页面上**不得有任何**"模型会看到什么"的断言 ✓。
 * 三条红线（§3.5）：① 解析后的绝对路径必须落在项目声明路径（或库根）内；② 拒凭据类文件名；③ 缺失/非普通文件 ⇒ 明确报错，不静默当空 ✓。
 * 块身份（§3）：身份是 **:ID:**，不是块名 ⇒ 改名只改 ** 标题（本页可改块名 ✓，空名保存前拦下 ✓，重名只提醒 ✓）。
 */
import { t, format } from './pm-i18n.js'
import { esc } from './pm-format.js'

/* 模板：**逐字取自 内部记录/25-初始系统提示词.示例.html 的 const TEMPLATE**（判据 verify_prompt_template_sync.py 守着 ✓）。 */
export const PROMPT_TEMPLATE = [
  { name: '项目概览', kind: 'include', include: '${path}/README.md', tip: '引用一份现成文档（如项目 README），省得把内容抄进提示词', ph: '' },
  { name: '项目背景', kind: 'text', tip: '一句话说清这是什么项目、现在在做什么', ph: '例：pm_tools 是 DSH 的工作记忆库工具，Org 是唯一真源。' },
  { name: '角色与工作定位', kind: 'text', tip: '希望它以什么身份，做哪些事情。', ph: '例：你是xx架构师，现在规划xx的架构开发，给出详细的文档和示例' },
  { name: '硬约束', kind: 'text', tip: '明确不要做的事（比"要做什么"更省事）', ph: '例：不要动人工文件；不要声称任务已完成；不要在没有来源时编造记忆。' },
  { name: '输出格式', kind: 'text', tip: '回复的结构偏好', ph: '例：改动先列文件清单，再给 diff 摘要。' },
]

/* 模板示例的样本文字（**逐字取自示例的 const SAMPLE** ⇒ ④「填充 ← 模板示例」用它 ✓） */
export const PROMPT_SAMPLE = {
  '项目背景': 'pm_tools 是 DSH 的工作记忆库工具：把工作区/会话状态投影成 Org 真源的项目、任务、随手记、提案与记忆。',
  '角色与工作定位': '你是xx架构师，现在规划xx的架构开发，给出详细的文档和示例',
  '硬约束': '不要改写人工文件（inbox.org / projects/** / memory/**）；不要声称任务已完成（DONE 只能人写）；没有来源的内容不当作事实。',
  '输出格式': '改动先列文件清单（路径 + 意图），再给关键 diff 摘要；长输出先给结论段。',
}

/* §3.6 可用变量：v1 就这 5 个；其中 ${dsh_home} 是 §8 未决项 ⇒ 明确标"待定"、不装作已支持 ✓ */
export const PROMPT_VARS = [
  { v: '${path}', note: '' },
  { v: '${path:N}', note: '多路径项目的第 N 条' },
  { v: '${root}', note: '' },
  { v: '${project}', note: '' },
  { v: '${dsh_home}', note: '待定（§8 未决）', pending: true },
]

export const isFilled = (b) => b.kind === 'include' ? !!String(b.include || '').trim() : !!String(b.text || '').trim()
export const filledCount = (blocks) => (blocks || []).filter(isFilled).length
export const includeCount = (blocks) => (blocks || []).filter((b) => b.kind === 'include').length
export const isDirty = (blocks, savedJson) => JSON.stringify(blocks || []) !== String(savedJson || '')

/* 空块模板（「填充 ← 空白模板」：只有块名与提示 ✓）*/
export function blankBlocks() {
  return PROMPT_TEMPLATE.map(function (b) { return { name: b.name, kind: b.kind, include: b.include || '', tip: b.tip, ph: b.ph || '', text: '' } })
}
/* 模板示例（带示例文字 ⇒ 标注"示例" ✓）*/
export function sampleBlocks() {
  return PROMPT_TEMPLATE.map(function (b) {
    return { name: b.name, kind: b.kind, include: b.include || '', tip: b.tip, ph: b.ph || '', text: PROMPT_SAMPLE[b.name] || '', sample: !!PROMPT_SAMPLE[b.name] }
  })
}
/* 「填充」下拉：空白模板 / 模板示例 / 从**已保存过**的项目复制（每项是**副本**，不是引用 ✓；本项目那条 = 回滚到上次保存 ✓）*/
export function fillOptions(savedProjects, key) {
  var out = [
    { value: 'blank', label: t('prompt.fillBlank') },
    { value: 'sample', label: t('prompt.fillSample') },
  ]
  ;(savedProjects || []).forEach(function (p) {
    out.push({ value: 'copy:' + p.key, label: (p.key === key ? t('prompt.fillCopyMine') : t('prompt.fillCopy')) + ' ' + p.key + (p.rev ? ' · rev ' + p.rev : '') })
  })
  return out
}
/* 块名警告（示例口径）：空名 ⇒ 保存前拦下并指出第几块 ✓；重名 ⇒ 只提醒不拦 ✓ */
export function nameWarn(blocks, i) {
  var b = (blocks || [])[i] || {}
  var nm = String(b.name || '').trim()
  if (!nm) return t('prompt.nameEmpty')
  var dup = (blocks || []).some(function (x, j) { return j !== i && String(x.name || '').trim() === nm })
  return dup ? t('prompt.nameDup') : ''
}
export function firstEmptyName(blocks) {
  for (var i = 0; i < (blocks || []).length; i++) if (!String(blocks[i].name || '').trim()) return i + 1
  return 0
}

/* 预览（§4）：已填块按顺序拼接；引用文档按后端给的展开结果渲染：成功 ⇒ 来源标注 + 内容；失败 ⇒ 「⚠ 展开失败：<原因>」，绝不给半截内容 ✓ */
export function buildPreview(blocks, docs, opts) {
  var savedInc = (opts && opts.savedIncludes) || null
  /* exists=false = 该项目还没保存过 prompt.org（当前显示的是模板）⇒ include 块不可能有展开结果：
     应说「该引用尚未保存」，而不是笼统的"后端没有返回这一块的展开结果" ✓（用户 2026-10-20 反馈）*/
  var neverSaved = !!(opts && opts.exists === false)
  var parts = []
  ;(blocks || []).forEach(function (b) {
    if (!isFilled(b)) return
    var body = ''
    if (b.kind === 'include') {
      /* 用户 2026-10-20：三态分开 —— ①已保存展开成功 ②已保存但后端明确失败（显示 reason 原文）③尚未保存（专门文案）*/
      var anyDocs = !!(docs && Object.keys(docs).length)
      /* verifier 2026-10-20 真缺陷：块名先命中旧展开 ⇒ include 改了仍显示旧结果 ✗
         ⇒ 与「已保存 include 快照」比对：不一致 ⇒ 该块 docs 无效 ⇒「该引用尚未保存」✓ */
      var nm = String(b.name || '').trim()
      var hasSnap = !!(savedInc && Object.prototype.hasOwnProperty.call(savedInc, nm))
      var unsaved = hasSnap && String(b.include || '') !== String(savedInc[nm] == null ? '' : savedInc[nm])
      var d = unsaved ? null : (anyDocs ? ((docs[nm] || docs[b.include]) || null) : ((b.err || b.real || b.truncated) ? b : null))
      if (unsaved) body = '⚠ ' + t('prompt.unsavedInclude')
      else if (!d && anyDocs) body = '⚠ ' + t('prompt.unsavedInclude')
      else if (!d && neverSaved) body = '⚠ ' + t('prompt.unsavedInclude')
      else if (!d) body = '⚠ ' + t('prompt.expandFailed') + '：' + t('prompt.notExpanded')
      else if (d.ok === false || d.err) body = '⚠ ' + t('prompt.expandFailed') + '：' + String(d.reason || d.err || t('prompt.notExpanded'))
      else {
        var src = '↳ ' + (d.real || b.include) + ' · ' + format(t('prompt.srcLine'), { real: d.real || '-', lines: d.lines == null ? '-' : d.lines, kb: d.kb == null ? '-' : d.kb }) + (d.truncated ? ' · ' + t('prompt.truncated') : '')
        /* 后端 render.text 已自带「↳ 表达式 · 已展开 N 行」来源行 ⇒ 不再重复拼一条（否则出现两次来源行 ✗）*/
        var txt = d.text ? String(d.text) : ''
        body = (txt && txt.indexOf('↳ ') >= 0) ? txt : (src + (txt ? String.fromCharCode(10) + txt : ''))
      }
    } else body = String(b.text || '')
    parts.push('# ' + b.name + String.fromCharCode(10) + body)
  })
  return parts.join(String.fromCharCode(10) + String.fromCharCode(10))
}

/* 已保存的提示词（库）卡片：文件名 / 项目徽章 / 路径·字节·块数·时间 / 快照片段 / 载入·删除 ✓ */
/* 库项目筛选选项：全部项目(ALL) + 记录里出现的项目 + 当前项目（默认 ALL ✓）*/
export function libProjOptionsHtml(s) {
  var cur = String((s && s.libProj) || 'ALL')
  var keys = []
  ;((s && s.lib) || []).forEach(function (r) { var k = String(r.project || ''); if (k && keys.indexOf(k) < 0) keys.push(k) })
  if (s && s.key && keys.indexOf(String(s.key)) < 0) keys.push(String(s.key))
  keys.sort()
  return '<option value="ALL"' + (cur === 'ALL' ? ' selected' : '') + '>' + esc(t('prompt.libAll')) + '</option>' +
    keys.map(function (k) { return '<option value="' + esc(k) + '"' + (cur === k ? ' selected' : '') + '>' + esc(k) + '</option>' }).join('')
}
export function libCardsHtml(s) {
  var items = (s && s.lib) || []
  var q = String((s && s.libQ) || '').toLowerCase()
  var proj = String((s && s.libProj) || '')
  /* 「全部项目」= ALL ⇒ **不过滤**（此前把 ALL 当项目名去比 ⇒ 永远"没有匹配的记录" ✗）*/
  var projFilter = (proj && proj !== 'ALL') ? proj : ''
  if (projFilter) items = items.filter(function (x) { return String(x.project || '') === projFilter })
  if (q) items = items.filter(function (x) {
    return (String(x.name || '') + ' ' + String(x.path || '') + ' ' + String(x.snapshot || '')).toLowerCase().indexOf(q) >= 0
  })
  /* 两种空态分开：有筛选/搜索但没命中 ⇒ "没有匹配"；本来就一条记录都没有 ⇒ "还没有保存过" ✓ */
  if (!items.length) {
    return '<div class="empty">' + esc((q || projFilter) ? t('prompt.libNoMatch') : t('prompt.libEmpty')) + '</div>'
  }
  return items.map(function (x) {
    var name = String(x.name || x.path || '')
    var at = String(x.savedAt || x.at || '').slice(0, 16).replace('T', ' ')
    var meta = String(x.path || '') + ' · ' + String(x.bytes == null ? '-' : x.bytes) + ' B · ' + String(x.blocks == null ? '-' : x.blocks) + ' ' + t('prompt.libBlocks') + ' · ' + at
    var id = esc(String(x.id || ''))
    return '<div class="lib-card" data-lib-id="' + id + '" data-lib-proj="' + esc(String(x.project || '')) + '">' +
      '<div class="ltop"><span class="fname">' + esc(name) + '</span>' +
      '<span class="proj-badge">' + esc(String(x.project || '')) + '</span></div>' +
      '<div class="lmeta">' + esc(meta) + '</div>' +
      '<pre class="snip">' + esc(String(x.snapshot || '').slice(0, 160)) + '</pre>' +
      '<div class="acts"><button class="btn bordered" type="button" data-lib-act="load" data-id="' + id + '">' + esc(t('prompt.libLoad')) + '</button>' +
      '<button class="btn bordered" type="button" data-lib-act="del" data-id="' + id + '">' + esc(t('prompt.libDelete')) + '</button></div></div>'
  }).join('')
}

export function previewBytes(text) { return new TextEncoder().encode(String(text || '')).length }

/* ---------------- 渲染（markup 照示例 ✓） ---------------- */
function badgeOf(b) {
  if (!isFilled(b)) return t('prompt.badgeEmpty')
  if (b.kind === 'include') return 'INCLUDE · ' + String(b.include || '')
  var txt = String(b.text || '').trim().slice(0, 18)
  return 'TEXT · ' + t('prompt.humanMaint') + (txt ? ' · ' + txt + '…' : '')
}
export function promptCountHtml(s, blocks) {
  if (s.loading) return '<em>' + esc(t('prompt.loading')) + '</em>'
  var inc = includeCount(blocks)
  var out = esc(format(t('prompt.countLine'), { total: blocks.length, filled: filledCount(blocks), inc: inc }))
  out += ' · ' + (s.exists === false
    ? '<em>' + esc(format(t('prompt.notRecorded'), { key: String(s.key || '') })) + '</em>'
    : '<b>' + esc(format(t('prompt.recorded'), { rev: String(s.serverRev == null ? 0 : s.serverRev) })) + '</b>' +
      (s.savedAt ? ' <em>' + esc(format(t('prompt.savedAt'), { at: String(s.savedAt).slice(0, 16).replace('T', ' ') })) + '</em>' : ''))
  out += ' · ' + (s.dirty ? '<b style="color:var(--warn)">' + esc(t('prompt.dirty')) + '</b>' : '<em>' + esc(t('prompt.clean')) + '</em>')
  return out
}
function editorOf(b, i) {
  if (b.kind === 'include') {
    return '<div class="incrow"><input data-inc="' + String(i) + '" value="' + esc(b.include || '') + '" placeholder="' + esc('${path}/README.md') + '" aria-label="' + esc(t('prompt.incAria')) + '"></div>' +
      '<div class="vars">' + esc(t('prompt.varsHint')) + PROMPT_VARS.map(function (v) {
        return '<code title="' + esc(v.note || '') + '">' + esc(v.v) + (v.pending ? '（' + esc(t('prompt.pending')) + '）' : '') + '</code>'
      }).join(' ') + esc(t('prompt.varsNote')) + '</div>'
  }
  return '<textarea data-i="' + String(i) + '" placeholder="' + esc(b.ph || '') + '" aria-label="' + esc(t('prompt.textAria')) + '">' + esc(b.text || '') + '</textarea>'
}
function orgOf(b, i) {
  return b.kind === 'include'
    ? format(t('prompt.orgInclude'), { name: b.name })
    : format(t('prompt.orgText'), { name: b.name })
}
function promptRowHtml(b, i, s) {
  var empty = !isFilled(b)
  var cls = empty ? 'empty' : (b.kind === 'include' ? 'include' : 'text')
  var open = Number(s.open) === i
  var warn = nameWarn(s.blocks, i)
  var body = '<div class="namerow">' +
      '<label class="namelab" for="nm' + String(i) + '">' + esc(t('prompt.blockName')) + '</label>' +
      '<input class="nameinp" id="nm' + String(i) + '" data-name="' + String(i) + '" value="' + esc(b.name || '') + '" placeholder="' + esc(t('prompt.namePlaceholder')) + '" aria-label="' + esc(t('prompt.nameAria')) + '">' +
      '<span class="namehint">' + esc(t('prompt.nameHint')) + '</span>' +
    '</div>' +
    (warn ? '<div class="namewarn">' + esc(warn) + '</div>' : '') +
    '<span class="seg" role="group" aria-label="' + esc(t('prompt.segAria')) + '">' +
      '<button type="button" data-kind="text" data-i="' + String(i) + '" aria-pressed="' + (b.kind === 'include' ? 'false' : 'true') + '">' + esc(t('prompt.kindText')) + '</button>' +
      '<button type="button" data-kind="include" data-i="' + String(i) + '" aria-pressed="' + (b.kind === 'include' ? 'true' : 'false') + '">' + esc(t('prompt.kindInclude')) + '</button>' +
    '</span>' +
    editorOf(b, i) +
    '<div class="org">' + esc(orgOf(b, i)) + '</div>'
  return '<div class="row ' + cls + (open ? ' open' : '') + '">' +
    '<div class="chip" data-toggle="' + String(i) + '"><b>' + esc(b.name || '') + '</b><s>' + esc(badgeOf(b)) + '</s></div>' +
    '<div class="conn"></div>' +
    '<div class="desc"><span class="txt">// ' + esc(b.tip || '') + '</span>' +
      /* 用户 2026-10-20：展开按钮左移给删除腾位；删除=红框「−」，点击先弹确认对话框（不直接删）✓
         注意：只用示例已有类（.plus），红色样式走 app.css 的 [data-del-block] 页面侧覆盖（不新增类名 ✗）*/
      '<button type="button" class="plus" data-toggle="' + String(i) + '" aria-expanded="' + (open ? 'true' : 'false') + '" aria-label="' + esc(t('prompt.toggleAria')) + '">' + (open ? '−' : '+') + '</button>' +
      '<button type="button" class="plus" data-del-block="' + String(i) + '" aria-label="' + esc(t('prompt.delBlockAria')) + '" title="' + esc(t('prompt.delBlockAria')) + '">−</button>' +
    '</div>' +
    '<div class="body">' + body + '</div>' +
  '</div>'
}
export function renderPromptPage(st) {
  var s = st || {}
  var projects = s.projects || []
  var blocks = s.blocks || []
  var caps = s.caps || { get: false, put: false }
  var preview = buildPreview(blocks, s.docs, { savedIncludes: s.savedIncludes, exists: s.exists === true })
  var opt = function (o) { return '<option value="' + esc(o.value) + '">' + esc(o.label) + '</option>' }
  var html = '<div id="pmPromptPage"><main class="main">'
  html += '<h1>' + esc(t('prompt.heading')) + '</h1>'
  html += '<p class="hint">' + esc(t('prompt.intro')) + '</p>'
  if (!caps.get && !caps.put) html += '<p class="hint">' + esc(t('prompt.epMissing')) + ' <code>GET /ui-pm/prompt</code> / <code>PUT /ui-pm/prompt</code></p>'
  if (s.noProject) html += '<p class="hint" id="noProject">' + esc(t('prompt.pickProjectFirst')) + '</p>'
  html += '<div class="bar">' +
    '<label for="proj" class="count"><em>' + esc(t('prompt.project')) + '</em></label>' +
    '<select id="proj" class="btn">' + projects.map(function (p) {
      /* 用户 2026-10-20 改进③：标注「已保存 rev N」/「无记录（模板起）」，项目来源已合并（ui-cards ∪ 已保存清单）✓ */
      var savedTag = (p.savedRev == null) ? t('prompt.projMetaNone') : format(t('prompt.projMetaSaved'), { r: String(p.savedRev) })
      return '<option value="' + esc(p.key) + '"' + (p.key === s.key ? ' selected' : '') + '>' + esc(p.key) + '　·　' +
        esc(format(t('prompt.projMeta'), { mem: p.mem == null ? '-' : p.mem, tasks: p.tasks == null ? '-' : p.tasks })) +
        '　·　' + esc(savedTag) + '</option>'
    }).join('') + '</select>' +
    '<span class="grow"></span>' +
    '<button class="btn bordered" id="addBlock" type="button">' + esc(t('prompt.addBlock')) + '</button>' +
    '<select id="fillFrom" class="btn" aria-label="' + esc(t('prompt.fillAria')) + '" title="' + esc(t('prompt.fillAria')) + '">' +
      '<option value="">' + esc(t('prompt.fillPick')) + '</option>' + fillOptions(s.savedProjects, s.key).map(opt).join('') + '</select>' +
    '<button class="btn bordered" id="revert" type="button"' + (s.dirty ? '' : ' disabled') + '>' + esc(t('prompt.revert')) + '</button>' +
    '<button class="btn primary" id="save" type="button"' + ((s.dirty && caps.put) ? '' : ' disabled') + '>' + esc(t('prompt.save')) + '</button>' +
  '</div>'
  html += '<p class="count" id="count" style="margin:0 0 12px">' + promptCountHtml(s, blocks) + '</p>'
  html += '<div class="legend">' +
    '<span><i class="l-blue"></i>' + esc(t('prompt.legendText')) + '</span>' +
    '<span><i class="l-green"></i>' + esc(t('prompt.legendInclude')) + '</span>' +
    '<span><i class="l-gray"></i>' + esc(t('prompt.legendEmpty')) + '</span>' +
    '<span>' + esc(t('prompt.legendTip')) + '</span></div>'
  html += '<div class="blocks" id="blocks"' + (s.loading ? ' aria-busy="true"' : '') + '>' +
    (s.loading
      ? '<p class="hint">' + esc(t('prompt.loading')) + '</p>'   /* 加载中**不渲染模板行**（否则用户先看到模板、再看到真数据 ⇒ "大小不一" ✗）*/
      : blocks.map(function (b, i) { return promptRowHtml(b, i, s) }).join('')) + '</div>'
  var pvOpen = s.pvOpen !== false
  html += '<section class="preview"><h2><span class="grow">' + esc(t('prompt.previewHeading')) + '</span>' +
    '<span class="count" id="pvSize">' + esc(format(t('prompt.pvSize'), { b: previewBytes(preview) })) + '</span>' +
    '<button class="btn primary" id="export" type="button">' + esc(t('prompt.export')) + '</button>' +
    '<button class="btn bordered" id="pvToggle" type="button" aria-expanded="' + (pvOpen ? 'true' : 'false') + '"' +
    ' aria-controls="preview">' + esc(pvOpen ? t('prompt.pvCollapse') : t('prompt.pvExpand')) + '</button>' +
    '<button class="btn bordered" id="copy" type="button">' + esc(t('prompt.copy')) + '</button></h2>' +
    '<p class="phint">' + esc(t('prompt.previewHint')) + '</p>' +
    '<pre id="preview"' + (pvOpen ? '' : ' hidden') + '>' + esc(preview) + '</pre></section>' +
    /* 已保存的提示词（库）：记录是派生物（.local/prompt-exports.json），卡内提供载入/删除 ✓ */
    '<section class="lib"><h2><span class="grow">' + esc(t('prompt.libHeading')) + '</span>' +
    '<span class="count" id="libCount">' + esc(format(t('prompt.libCount'), { n: (s.lib || []).length })) + '</span></h2>' +
    '<div class="lib-filters">' +
    '<select id="libProj" aria-label="' + esc(t('prompt.libProjAria')) + '">' + libProjOptionsHtml(s) + '</select>' +
    '<input type="search" id="libQ" placeholder="' + esc(t('prompt.libSearchPh')) + '" aria-label="' + esc(t('prompt.libSearchAria')) + '"' +
    ' value="' + esc(s.libQ || '') + '"></div>' +
    '<div class="lib-cards" id="libCards">' + libCardsHtml(s) + '</div></section>' +
    /* 导出对话框：诚实口径 —— 浏览器只能触发下载/另存为，面板拿不到最终绝对路径 ✓ */
    /* 结构**照 内部记录/25 示例**：.dlg-head(h3+诚实说明) / .dlg-body(rows+摘要) / .dlg-foot(按钮) ——
       之前 h3/hints/rows 直接挂在 form 下 ⇒ 示例 CSS 的 padding/border/gap 全不生效 ⇒ 观感"扁平又挤" ✗（用户 2026-10-20 反馈）*/
    '<dialog id="dlgExport" aria-labelledby="dlgTitle"><form class="dlg" id="exportForm">' +
    '<div class="dlg-head"><h3 id="dlgTitle">' + esc(t('prompt.exportTitle')) + '</h3>' +
    '<p class="dlg-hint" id="expHonest">' + esc(t('prompt.exportHonest')) + '</p></div>' +
    '<div class="dlg-body">' +
    '<div class="dlg-row"><label for="expProj">' + esc(t('prompt.expProjLabel')) + '</label>' +
    '<select id="expProj"></select>' +
    '<div class="dlg-hint" id="expProjHint"></div></div>' +
    '<div class="dlg-row"><label for="expPath">' + esc(t('prompt.expPath')) + '</label>' +
    '<input id="expPath" spellcheck="false" placeholder="' + esc(t('prompt.expPathPh')) + '"></div>' +
    '<div class="dlg-row"><label for="expFmt">' + esc(t('prompt.expFmt')) + '</label>' +
    '<select id="expFmt"><option value="md">Markdown (.md)</option><option value="txt">纯文本 (.txt)</option><option value="org">Org (.org)</option></select></div>' +
    '<div class="dlg-hint" id="expSummary"></div></div>' +
    '<div class="dlg-foot"><button type="button" class="btn bordered" id="expCancel">' + esc(t('prompt.expCancel')) + '</button>' +
    '<button type="button" class="btn primary" id="expGo">' + esc(t('prompt.expGo')) + '</button></div></form></dialog>' +
    /* 删除块确认对话框（用户 2026-10-20）：只删**草稿里的这一块**，保存后才写回 prompt.org；取消不改任何东西 ✓ */
    '<dialog id="dlgDelBlock" aria-labelledby="dlgDelTitle"><form class="dlg">' +
    '<div class="dlg-head"><h3 id="dlgDelTitle">' + esc(t('prompt.delTitle')) + '</h3>' +
    '<p class="dlg-hint" id="dlgDelWho"></p></div>' +
    '<div class="dlg-body"><p class="dlg-hint">' + esc(t('prompt.delBody')) + '</p></div>' +
    '<div class="dlg-foot"><button type="button" class="btn bordered" id="delCancel">' + esc(t('prompt.delCancel')) + '</button>' +
    '<button type="button" class="btn" id="delGo">' + esc(t('prompt.delGo')) + '</button></div></form></dialog>' +
    /* 切换项目确认对话框（用户 2026-10-20 改进①）：有未保存改动时**不许静默丢弃**草稿 ✓ */
    '<dialog id="dlgSwitchProj" aria-labelledby="dlgSwitchTitle"><form class="dlg">' +
    '<div class="dlg-head"><h3 id="dlgSwitchTitle">' + esc(t('prompt.switchTitle')) + '</h3>' +
    '<p class="dlg-hint" id="dlgSwitchWho"></p></div>' +
    '<div class="dlg-body"><p class="dlg-hint">' + esc(t('prompt.switchBody')) + '</p></div>' +
    '<div class="dlg-foot"><button type="button" class="btn bordered" id="switchCancel">' + esc(t('prompt.switchCancel')) + '</button>' +
    '<button type="button" class="btn" id="switchGo">' + esc(t('prompt.switchGo')) + '</button></div></form></dialog>' +
    /* 载入记录确认对话框（用户 2026-10-20：替换浏览器原生 confirm，样式与删除框一致 ✓） */
    '<dialog id="dlgLibLoad" aria-labelledby="dlgLoadTitle"><form class="dlg">' +
    '<div class="dlg-head"><h3 id="dlgLoadTitle">' + esc(t('prompt.libLoadTitle')) + '</h3>' +
    '<p class="dlg-hint" id="dlgLoadWho"></p></div>' +
    '<div class="dlg-body"><p class="dlg-hint" id="dlgLoadBody"></p></div>' +
    '<div class="dlg-foot"><button type="button" class="btn bordered" id="libLoadCancel">' + esc(t('prompt.libLoadCancel')) + '</button>' +
    '<button type="button" class="btn primary" id="libLoadGo">' + esc(t('prompt.libLoadGo')) + '</button></div></form></dialog>'
  if (s.conflict && s.conflict.cas !== true) {
    /* 默认=**简单展示后端报文**（校验类失败等，含 fixture 的 422 ✓）；只有 app.js 显式标 cas:true（真 409 REVISION_CONFLICT）才走下面的冲突 UI ✓ */
    html += '<p class="namewarn" id="conflict">' + esc(String(s.conflict.error || '')) + '</p>'
  } else if (s.conflict) {
    var cr = s.conflict.currentRevision
    html += '<p class="namewarn" id="conflict">' + esc(cr == null ? t('prompt.casConflictNoRev') : format(t('prompt.casConflict'), { rev: String(cr) })) +
      (s.conflict.error ? esc(' ' + String(s.conflict.error)) : '') +
      ' <button class="btn bordered" id="reload" type="button">' + esc(t('prompt.reload')) + '</button></p>' +
      '<details><summary>' + esc(t('prompt.draftKept')) + '</summary><pre>' + esc(String(s.conflict.draft || '')) + '</pre></details>'
  }
  html += '<p class="boundary">' + esc(t('prompt.boundary')) + '</p>'
  html += '<div class="toast" id="toast" role="status" aria-live="polite"></div>'
  html += '</main></div>'
  return html
}
