/* ===================== 主题（内联，原本是 theme.js） =====================
 * 三模式：跟随系统 / 浅色 / 深色 —— 零构建、无依赖、无 CDN。
 * 注意：ui-pm 宿主只托管「单段文件名」的静态文件（src/index.ts 的 resolveAppFile：名字里不能有
 * 目录分隔符，扩展名要在白名单里；子目录一律 400）。task-91 起纯叶子拆成同目录扁平模块
 * （./pm-format.js / ./pm-dag.js）；主题逻辑仍内联在本文件顶部：它要读宿主 window.parent。
 * 设计依据：frontend-design/theme-and-framework.md；环境检测契约由 DSH boot-theme 提供。
 *
 * 「跟随系统」在本页有两种环境，检测路径不同：
 *   1) 内嵌 DSH（iframe, allow-same-origin）：宿主有自己的主题开关，必须读**宿主已解析**的结果
 *      window.parent.document.body[data-ds-dark-theme]（boot-theme 已把 system 解析过），
 *      并对该属性挂 MutationObserver —— 宿主切换主题时本页不刷新即跟随。
 *   2) 独立打开：matchMedia('(prefers-color-scheme: dark)') + change 监听。
 * 只读宿主，绝不写宿主的任何属性或 class。
 * 用户手动选择（light/dark）优先于环境，存 localStorage；三模式循环保证能回到「跟随系统」。
 * 首屏防闪烁由 index.html <head> 内联脚本完成（它在渲染前用同样的规则算出 data-theme）。
 */
/* task-91 阶段 1：纯叶子拆成扁平 ESM（零构建；插件只服务单段文件名）。
   主题逻辑仍内联在本文件顶部：它要读宿主 window.parent，且历史上有 3 文件白名单的约束。 */
import { esc, pad, orgTime, localTime, historyTimeText, TASK_STATUS, MEMORY_TYPES, BOARD_COLUMN_TITLES, boardColumnTitle, bindTranslator } from './pm-format.js';
/* 搜索命中高亮（用户 2026-10-19 要求）：把查询词包成 <mark class="hl">。
   口径：先按大小写不敏感**切分原文本**、再逐段 esc ⇒ 不引入 XSS、也不会把 HTML 实体切坏 ✓（空查询原样 esc）。 */
function highlightEsc(text, q) {
  var s = String(text === null || text === undefined ? '' : text);
  var term = String(q === null || q === undefined ? '' : q).trim();
  if (!term) return esc(s);
  var low = s.toLowerCase(), tl = term.toLowerCase(), out = '', i = 0;
  while (true) {
    var at = low.indexOf(tl, i);
    if (at < 0) { out += esc(s.slice(i)); break; }
    out += esc(s.slice(i, at)) + '<mark class="hl">' + esc(s.slice(at, at + term.length)) + '</mark>';
    i = at + term.length;
  }
  return out;
}

/* B0：把 i18n 的 t 注入 pm-format.js（它是纯叶子、不 import 任何模块 ⇒ 由上层显式注入）。
   未注入时 pm-format 的表逐字回退原中文 ⇒ 行为与改造前一致。幂等，可重复调用。 */
bindTranslator(t);
import { dagModel, dagSvgHtml, dagTextHtml, dagChainLines, dagPairCount, clipText, dagStatusClass, dagSub, dagNarrow, DAG_W, DAG_H, DAG_GX, DAG_GY, DAG_PAD } from './pm-dag.js';
/* task-265：初始系统提示词页（模块自带渲染与纯函数；本文件只负责路由/状态装配与事件委派 ✓） */
import { renderPromptPage, PROMPT_TEMPLATE, isDirty as promptIsDirty, buildPreview, filledCount as filledPromptCount, includeCount as includePromptCount, blankBlocks, sampleBlocks, firstEmptyName, promptCountHtml, nameWarn, libCardsHtml } from './pm-prompt.js';
/* task-146：交互原语抽成扁平模块（app.js 只用，不再留第二份实现） */
import { EDGE_THRESHOLD, EDGE_MAX_STEP, EDGE_THROTTLE_MS, createEdgeAutoScroll } from './pm-scroll.js';
import { BOARD_DROP_TARGETS, BOARD_COL_LABELS, STATUS_GROUP, KANBAN_COL_CLASS, KANBAN_COL_SELECTOR, KANBAN_BODY_CLASS, columnAtPoint, bodyOfColumn, columnRects, dropDecision, dropTargetFor, dropReason } from './pm-kanban.js';
/* task-158（B）：记忆卡片的编号与取代链（纯逻辑在模块里，可单测） */
import { memoryShortId, memoryFullId, memoryLinks, memoryAllEntries, memoryPresentIds, memoryLinkLabel, memoryLinkNote, memoryCopyNote, memoryDiscardOutcome, memoryWriteErrorText, memoryMergeOptionText, splitCandidates, processedSummaryParts, processedStatusChip } from './pm-memory.js';
/* task-171：向导「④ 指派会话」——只列真会话 + 子 agent/队友开关 + 用名字而不是裸 id */
import { CONTINUABLE, sessionIdentityMissing, cardsById, partitionSessions, visibleSessions, peerToggleText } from './pm-session.js';
/* task-184：「需要我处理」——折叠持久化 + 长列表收敛/分组 + 逐字理由与建议 */
import { COLLAPSE_KEY, ignoreNote, DEFAULT_VISIBLE, parseCollapse, serializeCollapse, attentionReasons, attentionSuggestion, groupByProject, visibleCards, expandAllText } from './pm-attention.js';
/* task-186：收件箱状态说明（静态卡片；内容与来源在 pm-inbox-status.js，单测直接和 inbox_ops.py 对账） */
import { INBOX_STATUS_TABLE, INBOX_FILTER_STATUSES, LEGACY_STATUS, TERMINAL_STATUSES, STATE_MACHINE_NOTE, isTerminalStatus, SOURCE_FILE } from './pm-inbox-status.js';
/* task-96 阶段 2：纯叶子继续下行 */
import { subStatusChip, SUB_STATUS_CHIPS, MERGED_GROUP_STATUSES } from './pm-board-model.js';
import { entryAnnotations, annoBlockHtml, annoListHtml, NOTE_ANNO_MAX, NOTE_ANNO_LONG } from './pm-anno.js';
import { inboxPinState } from './pm-pin-state.js';
import { state } from './pm-state.js';
/* task-209：原生 <details> 展开态的单一实现（状态进 state.folds，渲染回填 open，toggle 写回） */
import { foldKey, foldAttrs, foldDetailsHtml, setFold, foldKeyFromTarget } from './pm-fold.js';
/* task-217：项目下拉的单一实现（收件箱笔记 + 提案两处共用；名字优先/key 次要/同名消歧/未就绪如实降级） */
import { PROJECT_MANUAL, PROJECT_NEW, projectFieldModel } from './pm-project-select.js';
/* task-204 一期：i18n（只有一份实现——文案表在 pm-i18n.js） */
import { initLang, applyShell, setLang, t, format } from './pm-i18n.js';
import { api, httpJson, apiError, capsReady, endpointListed, unavailableReason, loadCapabilities, notYet, missingEndpointText } from './pm-api.js';
import { performWrite, mintKey, configureWrite } from './pm-write.js';

(function () {
  'use strict';

  /* task-204 一期：语言先定下来（URL ?lang= > localStorage > 宿主 html[lang] > navigator > 中文），再套静态外壳 */
  initLang();
  applyShell(document);

  var KEY = 'pm-theme';
  /* task-204：文案懒计算 —— 切语言后由 PMTheme.refresh() 重新取（不在别的作用域里赋值） */
  function LABELS() { return { system: t('theme.system'), light: t('theme.light'), dark: t('theme.dark') }; }
  var ORDER = ['system', 'light', 'dark'];
  var root = document.documentElement;
  var button = document.getElementById('theme-toggle');

  /* ---------- 环境检测（只读） ---------- */

  function parentDoc() {
    try {
      if (window.parent && window.parent !== window && window.parent.document) return window.parent.document;
    } catch (e) { /* 跨源：拿不到就退回系统偏好 */ }
    return null;
  }

  function hostSupported(doc) {
    if (!doc || !doc.documentElement) return false;
    try {
      if (typeof doc.documentElement.dataset.dsThemeSource === 'string') return true;
      return !!(doc.body && doc.body.hasAttribute('data-ds-dark-theme'));
    } catch (e) { return false; }
  }

  function hostDark(doc) {
    try { return !!(doc.body && doc.body.hasAttribute('data-ds-dark-theme')); }
    catch (e) { return false; }
  }

  function systemDark() {
    return !!(window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches);
  }

  /* 返回 { dark: boolean, source: 'dsh'|'system' } */
  function environment() {
    var doc = parentDoc();
    if (hostSupported(doc)) return { dark: hostDark(doc), source: 'dsh' };
    return { dark: systemDark(), source: 'system' };
  }

  function readMode() {
    try {
      var saved = localStorage.getItem(KEY);
      if (saved === 'light' || saved === 'dark') return saved;
    } catch (e) { /* 隐私模式等：退回跟随环境 */ }
    return 'system';
  }

  function resolve(mode) {
    if (mode === 'light' || mode === 'dark') return { theme: mode, source: 'manual' };
    var env = environment();
    return { theme: env.dark ? 'dark' : 'light', source: env.source };
  }

  /* task-204：来源名懒计算（切语言后 PMTheme.refresh() → apply() 会重新取，天然跟语言走） */
  function SOURCE_LABELS() { return { dsh: t('theme.source.dsh'), system: t('theme.source.system'), manual: t('theme.source.manual') }; }

  function apply() {
    var mode = readMode();
    var r = resolve(mode);
    /* 只作用于本 iframe 文档的 <html>，不触碰宿主页面主题。 */
    root.setAttribute('data-theme', r.theme);
    root.setAttribute('data-theme-mode', mode);
    root.setAttribute('data-theme-source', r.source);
    if (button) {
      /* 拼接模板也进表（含标点）：英文模式不会再拼出全角冒号/括号 */
      var text = format(t('topbar.themeFormat'), { theme: t('topbar.theme'), mode: LABELS()[mode], system: LABELS()[r.theme] });
      button.textContent = text;
      button.setAttribute('aria-label', format(t('topbar.themeAriaFormat'),
        { theme: t('topbar.theme'), mode: LABELS()[mode], shown: LABELS()[r.theme], source: SOURCE_LABELS()[r.source] }));
      button.setAttribute('title', text + ' · ' + SOURCE_LABELS()[r.source]);
    }
    return r;
  }

  function save(mode) {
    try {
      if (mode === 'system') localStorage.removeItem(KEY);
      else localStorage.setItem(KEY, mode);
    } catch (e) { /* 存不下也不影响本次会话 */ }
  }

  /* ---------- 交互 ---------- */

  if (button) {
    button.addEventListener('click', function () {
      var next = ORDER[(ORDER.indexOf(readMode()) + 1) % ORDER.length];
      save(next);
      apply();
    });
  }

  /* ---------- 环境变化的实时跟随 ---------- */

  var observers = [];

  function watchHost() {
    var doc = parentDoc();
    if (!hostSupported(doc) || !doc.body) return false;
    try {
      var mo = new MutationObserver(function () { if (readMode() === 'system') apply(); });
      mo.observe(doc.body, { attributes: true, attributeFilter: ['data-ds-dark-theme'] });
      observers.push(mo);
    } catch (e) { return false; }
    return true;
  }

  var followingSystemPrefs = !watchHost();

  if (window.matchMedia) {
    var mq = window.matchMedia('(prefers-color-scheme: dark)');
    var onPref = function () {
      /* 只有在“跟随本机系统偏好”这条路径上才响应；内嵌 DSH 时以宿主为准。 */
      if (readMode() === 'system' && followingSystemPrefs) apply();
    };
    if (mq.addEventListener) mq.addEventListener('change', onPref);
    else if (mq.addListener) mq.addListener(onPref);
  }

  /* 宿主文档可能在加载后才挂上 body / 属性：重试一次，覆盖“页面加载后宿主才就绪”的情况。 */
  if (!followingSystemPrefs) {
    var tries = 0;
    var timer = setInterval(function () {
      tries += 1;
      if (watchHost() || tries > 20) clearInterval(timer);
      if (readMode() === 'system') apply();
    }, 500);
  }

  apply();

  window.PMTheme = {
    mode: readMode,
    theme: function () { return resolve(readMode()).theme; },
    source: function () { return resolve(readMode()).source; },
    label: function () { return LABELS()[readMode()]; },
    refresh: apply
  };
})();

/* PM 工作台 —— 原生 JS，零构建、无依赖、无 CDN。
 *
 * 数据面（诚实约束，见 frontend-design/README.md 与 backend-design.md §3）：
 *   只读 GET ../cards（ui-cards-v1）；写只经 POST ../capture。
 *   - 不出现“正在运行”：记录状态照抄 pm 的 observation_label。
 *   - 每条观察都带观察时间与来源（cards[].recorded_at / card_file，inbox.path + 行号）。
 *   - 颜色不是唯一信息：每个状态徽标都带文字。
 *   - 归档用方角虚线徽标，与圆胶囊的观察徽标区分。
 *   - 没有后端模型的地方（任务/验收/记忆/Inbox 分流命令）显式标注「尚未接入」并列出缺的模型，
 *     不用演示数据冒充真实数据（page-designs §6 最后一条）。
 */
(function () {
  'use strict';

  /* task-204：标题走文案表（切语言后 render 即生效，不留旧值） */
  function viewTitle(view) { return t('view.' + view) || view; }

  /* 观察值 → 圆胶囊配色。颜色只是辅助，文字始终在。 */
  var OBS_CLASS = {
    STALE_BUSY: 'amber', BUSY: 'purple', RECENT: 'blue',
    IDLE: 'gray', CLOSED: 'gray', ARCHIVED: 'gray', EMPTY: 'gray'
  };
  var OBS_MEANING = {
    BUSY: '忙碌',
    RECENT: '近有记录',
    STALE_BUSY: '陈旧·忙碌',
    IDLE: '沉寂',
    CLOSED: '已结束',
    ARCHIVED: '已归档',
    EMPTY: '空会话'
  };

  /* 写命令的统一返回形状（backend-design §5/§6）：接入后照这个渲染，不提前假装成功。 */
  var WRITE_SHAPE = '{ "ok": true, "entityId": "inbox-01J…", "revision": 2, '
    + '"source": "org", "observedAt": "2026-10-12T10:45:00+08:00", "auditEventId": "evt-…" }';

;

  var el = {
    content: document.getElementById('content'),
    pageTitle: document.getElementById('page-title'),
    pageSub: document.getElementById('page-sub'),
    sync: document.getElementById('sync'),
    detail: document.getElementById('detail'),
    detailTitle: document.getElementById('detail-title'),
    detailBody: document.getElementById('detail-body'),
    shell: document.getElementById('shell')
  };

  /* ================= 第三列宽度：纯函数（桩可直接断言） ================= */

  var DETAIL_W_DEFAULT = 380;      /* 视图默认宽度（review/memory 用 DETAIL_W_WIDE） */
  var DETAIL_W_WIDE = 480;
  var DETAIL_W_MIN = 320;          /* 再窄就没法用了 */
  var DETAIL_W_ABS_MAX = 720;
  var DETAIL_W_CHROME = 250 + 360; /* 左侧导航 250 + 给中列至少留 360 */

  /* 夹在 [320, min(720, viewportWidth - 610)]；视口极窄时下界优先（**永不 < 320**）。
     NaN / 0 / 负数 / 非法值一律回退默认 380 —— 绝不把 NaN 写进 CSS。 */
  function clampDetailWidth(px, viewportWidth) {
    var v = Number(px);
    if (!isFinite(v) || v <= 0) v = DETAIL_W_DEFAULT;
    var vw = Number(viewportWidth);
    if (!isFinite(vw) || vw <= 0) vw = 1440;
    var max = Math.min(DETAIL_W_ABS_MAX, vw - DETAIL_W_CHROME);
    if (max < DETAIL_W_MIN) max = DETAIL_W_MIN;
    return Math.round(Math.min(Math.max(v, DETAIL_W_MIN), max));
  }

  /* 解析 localStorage：'420' / '420px' → 420；缺失 / 'abc' / '0' / 负数 / NaN → **null**
     （null 的语义是「没有有效的用户覆盖」，调用方改用视图默认宽度）。 */
  function parseStoredWidth(raw) {
    if (raw === null || raw === undefined) return null;
    var text = String(raw).trim();
    if (!text) return null;
    var m = /^(-?\d+(?:\.\d+)?)\s*(?:px)?$/i.exec(text);
    if (!m) return null;
    var v = Number(m[1]);
    if (!isFinite(v) || v <= 0) return null;
    return v;
  }

  /* ================= 工具 ================= */

  function relTime(iso) {
    if (!iso) return t('rel.none');
    var ts = Date.parse(iso);
    if (isNaN(ts)) return t('rel.unknown');
    var diff = Date.now() - ts;
    if (diff < 0) diff = 0;
    var m = Math.floor(diff / 60000);
    if (m < 1) return t('rel.justNow');
    if (m < 60) return format(t('rel.minutes'), { n: m });
    var h = Math.floor(m / 60);
    if (h < 24) return format(t('rel.hours'), { n: h });
    var d = Math.floor(h / 24);
    if (d < 30) return format(t('rel.days'), { n: d });
    return localTime(iso).slice(0, 10);
  }

  function isArchived(c) { return c.observation === 'ARCHIVED'; }

  function obsBadge(c) {
    var cls = OBS_CLASS[c.observation] || 'gray';
    var label = c.observation_label || OBS_MEANING[c.observation] || '未知';
    var title = '观察值：' + label + '（来自 DSH 投影缓存；runtime_status 恒为 unknown，不代表此刻在运行）';
    return '<span class="badge ' + cls + '" title="' + esc(title) + '">' +
      '<span class="dot" aria-hidden="true"></span>' + esc(label) + '</span>';
  }

  /* 缺摘要不是错误，是真实缺口：用方角虚线标记，并把字段名写出来 */
  function summaryChip(c) {
    if (c.summary) return '';
    return '<span class="chip dashed" title="' + esc(t('sum.notGeneratedTitle')) +
      esc(c.summary_source || 'not_generated') + ')">' + esc(t('ag.notGeneratedChip')) + '</span>';
  }

  function archChip(c) {
    return isArchived(c) ? '<span class="chip dashed" title="' + esc(t('ag.archivedTitle')) + '">' + esc(t('ag.archivedChip')) + '</span>' : '';
  }

  function instChip(c) {
    if (!state.data || c.instance === state.data.instances[0]) return '';
    return '<span class="chip" title="' + esc(t('ag.instanceTitle')) + '">' + esc(c.instance) + '</span>';
  }

  function unbacked(title, lines, extra) {
    var html = '<div class="unbacked"><h3>' + esc(title) + '</h3>';
    html += '<p>' + esc(t('unbacked.note')) + '</p>';
    html += '<ul>';
    lines.forEach(function (l) { html += '<li>' + l + '</li>'; });
    html += '</ul>';
    if (extra) html += extra;
    html += '</div>';
    return html;
  }

  function banner(text) {
    return '<div class="banner"><strong>' + esc(t('banner.notWired')) + '</strong><span>' + text + '</span></div>';
  }

  function dataSourceLine() {
    var d = state.data;
    if (!d) return '';
    /* 这段会经 textContent 写入 #page-sub，返回纯文本（不转义） */
    /* task-204：这段也在外壳（#page-sub）里，同样走表 */
    return format(t('sub.dataSourceFormat'), { schema: d.schemaVersion || 'ui-cards', time: localTime(d.generated_at) || t('common.unknown') });
  }

  function writeShapeHtml() {
    return '<div class="src">' + esc(t('ws.expectShape')) + '<br>' + esc(WRITE_SHAPE) +
      '<br>' + esc(t('ws.conflictNote')) + '</div>';
  }

  /* ================= 工作卡（AI 工作卡）片段 ================= */

  function cardTitle(c) {
    if (c.summary) return c.summary;
    return '（未生成一句话摘要）';
  }

  function cardSourceLine(c) {
    return '来源：DSH 只读记录 · <code>' + esc(c.card_file || 'generated/sessions/…') + '</code>' +
      esc(t('ag.observedAtPrefix')) + esc(localTime(c.recorded_at) || t('ag.unknownTime'));
  }

  function rowHtml(c) {
    var arch = isArchived(c);
    return '<div class="item' + (arch ? ' is-dim' : '') + '">' +
      '<div class="item-main">' +
      '<button type="button" class="item-title link" data-session="' + esc(c.session_id) + '"' +
      ' data-instance="' + esc(c.instance) + '">' + esc(cardTitle(c)) + '</button>' +
      '<div class="item-meta">' +
      '<span>' + esc(c.project) + '</span>' +
      obsBadge(c) + instChip(c) + archChip(c) + summaryChip(c) +
      '<span>' + esc(format(t('row.turnsSteps'), { turns: c.turns, steps: c.steps })) + '</span>' +
      (c.open_todos ? '<span>' + esc(format(t('row.openTodos'), { n: c.open_todos })) + '</span>' : '') +
      '<span>' + esc(format(t('proj.observed'), { time: relTime(c.recorded_at) })) + '</span>' +
      '</div></div>' +
      '<div class="item-side"><button type="button" class="btn small" data-open-session="' + esc(c.session_id) +
      '" data-instance="' + esc(c.instance) + '">' + esc(t('row.openSession')) + '</button></div></div>';
  }

  function agentCardHtml(c) {
    var arch = isArchived(c);
    return '<article class="panel agent' + (arch ? ' is-dim' : '') + '">' +
      '<div class="agent-row">' + obsBadge(c) + archChip(c) +
      '<span class="subtle" style="font-size:11.5px">' + esc(t('ag.observedPrefix')) + esc(relTime(c.recorded_at)) + '</span></div>' +
      '<button type="button" class="agent-title' + (arch ? '' : ' link') + '" data-session="' + esc(c.session_id) +
      '" data-instance="' + esc(c.instance) + '">' + esc(cardTitle(c)) + '</button>' +
      (c.open_todos
        ? '<div class="agent-action">' + esc(format(t('ag.todosOpen'), { n: c.open_todos, total: c.total_todos })) + '</div>'
        : '<div class="agent-action">' + esc(format(t('ag.noOpenTodos'), { t: c.turns, s: c.steps })) + '</div>') +
      '<div class="agent-source">' +
      '<span>' + esc(c.project) + '</span>' + instChip(c) + summaryChip(c) +
      '<span>' + esc(c.card_file || '') + '</span>' +
      '<span> · ' + esc(localTime(c.recorded_at) || t('ag.unknownTime')) + '</span>' +
      '</div></article>';
  }

  /* ---------- 关掉浏览器表单历史 / 启发式自动填充（task-76） ----------
     单行 input 与 textarea 补 autocomplete="off"；checkbox/radio/hidden/file/submit/button/range/color 不动；
     作者已显式写过的值一律尊重，不覆盖。 */
  var AUTOFILL_TYPES = ['', 'text', 'search', 'url', 'email', 'tel', 'password', 'number', 'date', 'month', 'week', 'time', 'datetime-local'];

  function hardenAutofill(root) {
    if (!root || !root.querySelectorAll) return 0;
    var nodes = root.querySelectorAll('input, textarea');
    var changed = 0;
    Array.prototype.forEach.call(nodes, function (el) {
      if (!el || !el.getAttribute || !el.setAttribute) return;
      var tag = String(el.tagName || '').toUpperCase();
      if (tag !== 'TEXTAREA') {
        var type = String(el.getAttribute('type') || 'text').toLowerCase();
        if (AUTOFILL_TYPES.indexOf(type) < 0) return;
      }
      if (el.getAttribute('autocomplete')) return;
      el.setAttribute('autocomplete', 'off');
      changed++;
    });
    return changed;
  }

  function hardenAutofillNow() { return hardenAutofill(document); }

  /* 动态插入的对话框/向导表单也照顾到：只观察 childList（改属性不会触发，不会自激） */
  function watchAutofill() {
    if (typeof MutationObserver !== 'function' || !document.body) return;
    try {
      var mo = new MutationObserver(function () { hardenAutofillNow(); });
      mo.observe(document.body, { childList: true, subtree: true });
    } catch (e) { /* 老浏览器：render() 与对话框里的显式调用已经够用 */ }
  }

  function quickHtml(id) {
    return '<div class="quick-wrap">' +
      /* task-76：关掉浏览器的表单历史/自动填充建议（form 级 + 控件级 + 中性 name） */
      '<form class="quick" id="' + id + '" autocomplete="off">' +
      '<textarea id="quick" name="pm-quick-capture" rows="3" class="quick-input" autocomplete="off" autocapitalize="off" autocorrect="off" spellcheck="false" ' +
      'data-i18n-placeholder="quick.placeholder" placeholder="' + esc(t('quick.placeholder')) + '" aria-label="' + esc(t('quick.ariaLabel')) + '"></textarea>' +
      '<div class="quick-actions"><button class="btn primary" type="submit">' + esc(t('quick.submit')) + '</button></div></form>' +
      '<p class="hint" data-i18n="qn.hint">' + esc(t('qn.hint')) + '</p>' +
      '<p class="quick-status" id="quick-status" role="status" aria-live="polite"></p>' +
      '<div class="quick-emacs" id="quick-emacs" hidden><h4 data-i18n="qn.emacsHeading">' + esc(t('qn.emacsHeading')) + '</h4>' +
      '<p class="hint" data-i18n="qn.emacsHint">' + esc(t('qn.emacsHint')) + '</p>' +
      '<div class="copy-row"><code id="quick-emacs-cmd"></code>' +
      '<button type="button" class="btn small" id="quick-emacs-copy">' + esc(t('qn.emacsCopy')) + '</button></div>' +
      '<p class="hint" id="quick-emacs-note"></p></div></div>';
  }

  /* ================= 工作台 ================= */

  function boardNextPanel() {
    var head = '<section class="panel"><div class="panel-head"><div><h2>' + esc(t('board.nextStepHeading')) + '</h2>' +
      '<p class="subtle">' + esc(t('board.nextStepSubtitle')) + '</p></div>';
    if (!capsReady()) {
      return '<section class="panel"><div class="panel-head"><div><h2>' + esc(t('board.nextStepHeading')) + '</h2>' +
        '<p class="subtle">' + esc(t('board.tasksNotReady')) + '</p></div></div><div class="panel-body">' +
        unbacked(t('board.overviewNotReady'), [
          t('board.needEndpoint'),
          t('board.currentState') + unavailableReason('GET', '/ui-pm/tasks'),
          t('board.overviewLayoutOk')
        ]) + '</div></section>';
    }
    if (state.overviewLoading) {
      return head + '</div><div class="panel-body"><div class="empty">' + esc(t('board.loadingProjects')) + '</div></div></section>';
    }
    if (!state.overview) {
      return head + '<button class="btn small" type="button" data-load-overview="1">' + esc(t('board.loadOverview')) + '</button></div>' +
        '<div class="panel-body"><div class="empty">' + esc(t('board.onDemand').replace('{n}', String((state.data.projects || []).length))) +
        '<br>' +
        '<span class="subtle">' + esc(t('board.nextStepRealOnly')) + '</span></div></section>';
    }
    var withTasks = state.overview.projects.filter(function (p) { return p.count > 0; });
    var html = head + '<span class="subtle" style="font-size:12px">' + withTasks.length + ' / ' +
      esc(format(t('board.projectsWithTasks'), { n: state.overview.projects.length })) + '</span></div><div class="panel-body">';
    if (!withTasks.length) {
      html += '<div class="empty">' + esc(t('board.noTasksAnywhere')) + '<br>' +
        '<span class="subtle">' + esc(t('board.createFirstInProjects')) + '</span></div>';
    }
    withTasks.slice(0, 8).forEach(function (p) {
      var c = p.counts || {};
      var nexts = ((c.todo || {}).tasks || []).slice(0, 2);   /* task-56：NEXT 归入 todo */
      html += '<div class="item"><div class="item-main"><div class="item-title">' + esc(p.project) + '</div>' +
        '<div class="item-meta">' +
        (function () {
          /* 5 列 key 优先；其它 key 追加在后面 —— 数据驱动，不再写死列名 */
          var order = ['todo', 'doing', 'blocked', 'review', 'closed'];
          var keys = order.filter(function (k) { return c[k]; });
          Object.keys(c).forEach(function (k) { if (keys.indexOf(k) < 0) keys.push(k); });
          return keys.slice(0, 5).map(function (k) {
            var g = c[k];
            return g && g.count ? '<span class="chip">' + esc(g.label || k) + ' ' + g.count + '</span>' : '';
          }).join('');
        })() + '</div>';
      nexts.forEach(function (item) {
        html += '<button type="button" class="item-title link" style="margin-top:6px" data-task-id="' + esc(item.id) + '"' +
          ' data-task-project="' + esc(p.project) + '">' + esc(item.title) + '</button>';
      });
      html += '</div><div class="item-side"><button type="button" class="btn small" data-project="' +
        esc(p.project) + '">' + esc(t('board.openProject')) + '</button></div></div>';
    });
    if (withTasks.length > 8) html += '<div class="notice">' + esc(format(t('board.moreProjects'), { n: (withTasks.length - 8) })) + '</div>';
    html += '</div></section>';
    return html;
  }

  /* 随手记卡片：不新增任何请求，直接用 state.data.inbox.entries */
  /* 顶部卡片：**只列被置顶的随手记**（pinned === true），表格形式。
     数据来自已加载的 cards payload（inbox.entries），不新增请求、不写后端。
     pinned 字段缺失 → 写「置顶状态未接入」，**绝不拿最新的几条冒充置顶**。
     置顶/取消置顶按钮在后续任务（task-50）接入，这里只提供「处理 →」。 */
  function notesCardHtml() {
    var inbox = state.data ? state.data.inbox : null;
    var entries = (inbox && Array.isArray(inbox.entries)) ? inbox.entries : null;
    var head = '<section class="panel notes-card"><div class="panel-head"><div><h2>' + esc(t('notes.heading')) + '</h2>' +
      '<p class="subtle">' + esc(t('notes.subtitle')) + '</p></div>';
    var foot = '<div class="notes-foot"><span class="subtle" style="font-size:11.5px">' +
      esc(t('notes.pinButtonsLater')) + '</span>' +
      '<button type="button" class="btn small" data-goto="inbox">' + esc(t('notes.gotoInbox')) + '</button></div>';

    if (!entries) {
      return head + '<span class="badge gray">' + esc(t('notes.notWired')) + '</span></div>' +
        '<div class="panel-body"><div class="empty">' + esc(t('notes.inboxNotWired')) + '</div></div></section>';
    }
    var hasField = entries.some(function (e) { return Object.prototype.hasOwnProperty.call(e, 'pinned'); });
    var legacy = entries.filter(function (e) { return !e.id; });
    if (!hasField) {
      return head + '<span class="chip dashed">' + esc(t('notes.pinStateNotWired')) + '</span></div><div class="panel-body">' +
        '<div class="empty">' + esc(t('notes.pinStateExplain')) + '<code>pinned</code>' + esc(t('notes.pinStateExplain2')) +
        '<br>' +
        '<span class="subtle">' + esc(t('notes.pinLater')) + '</span></div>' +
        (legacy.length ? '<div class="notes-legacy">' + esc(format(t('notes.legacyMany'), { n: legacy.length })) + '</div>' : '') +
        foot + '</div></section>';
    }
    var pinned = entries.filter(function (e) { return e.pinned === true; });
    var pinnedTracked = pinned.filter(function (e) { return !!e.id; });
    var pinnedLegacy = pinned.filter(function (e) { return !e.id; });
    var html = head + '<span class="badge ' + (pinnedTracked.length ? 'amber' : 'gray') + '"' +
      ' title="' + esc(t('notes.pinnedTrackedTitle')) + '">' + esc(format(t('notes.pinnedTracked'), { n: pinnedTracked.length })) + '</span></div>' +
      '<div class="panel-body">';
    if (!pinnedTracked.length) {
      html += '<div class="empty">' + esc(t('notes.noPinned')) +
        (pinnedLegacy.length ? '<br><span class="subtle">' + esc(format(t('notes.legacyPinned'), { n: pinnedLegacy.length })) +
          esc(t('notes.legacyPinned2')) + '</span>' : '') + '</div>';
    } else {
      var rows = pinnedTracked.slice().sort(function (a, b) {
        return (Date.parse(b.capturedAt || '') || 0) - (Date.parse(a.capturedAt || '') || 0);
      });
      html += '<table class="notes-table"><thead><tr>' +
        '<th>' + esc(t('notes.thNote')) + '</th><th>' + esc(t('notes.thStatus')) + '</th><th>' + esc(t('notes.thCaptured')) + '</th><th>' + esc(t('notes.thExtra')) + '</th><th>' + esc(t('notes.thOp')) + '</th></tr></thead><tbody>';
      rows.forEach(function (e) {
        var text = String(e.text || '');
        var preview = text.length > 90 ? text.slice(0, 90) + '…' : text;
        var anno = (typeof e.annotationCount === 'number')
          ? (e.annotationCount > 0 ? '<span class="chip">' + esc(format(t('notes.annotations'), { n: e.annotationCount })) + '</span>' : '<span class="subtle">—</span>')
          : '<span class="subtle">' + esc(t('notes.notReturned')) + '</span>';
        html += '<tr>' +
          '<td class="note-cell"><button type="button" data-board-note="' + esc(e.id) + '"' +
          ' title="' + esc(text) + '&#10;' + esc(t('notes.clickToInbox')) + '">' + esc(preview) + '</button></td>' +
          '<td><span class="chip">' + esc(String(e.status || t('notes.notReturned'))) + '</span></td>' +
          '<td>' + esc(e.capturedAt ? (localTime(e.capturedAt) || t('fmt.timeNotReturned')) : t('notes.timeNotReturned')) + '</td>' +
          '<td>' + anno + '</td>' +
          '<td class="notes-op"><button type="button" class="btn small" data-board-note="' + esc(e.id) + '">' + esc(t('notes.handle')) + '</button>' +
          (function () {
            var pin3 = inboxPinState(e, PIN_STATE_DEPS);
            return pin3.ok
              ? '<button type="button" class="btn small" data-inbox-pin="' + esc(e.id) + '" aria-pressed="true">' + esc(t('notes.unpin')) + '</button>'
              : notYet(t('notes.unpin'), pin3.why);
          })() +
          '</td>' +
          '</tr>';
      });
      html += '</tbody></table>';
    }
    if (legacy.length) {
      html += '<div class="notes-legacy">' + esc(format(t('notes.legacyMany'), { n: legacy.length })) + '</div>';
    }
    html += foot + '</div></section>';
    return html;
  }

  /* 点卡片条目 → 跳收件箱并选中；若当前有状态过滤把这个 id 滤掉了，先清过滤再选 */
  function openInboxEntry(id) {
    if (!id) return;
    go('inbox');
    var found = (state.inbox && state.inbox.entries || []).some(function (e) { return e.id === id; });
    if (!found && state.inboxStatus) {
      state.inboxStatus = '';
      loadInbox().then(function () { selectNoteById(id); render(); });
      return;
    }
    /* 来源筛选是纯客户端过滤：条目还在内存里、只是被来源滤掉 ⇒ 先清来源再选，
       否则右栏选中了、列表里却看不见这条（与上面状态过滤的处理口径一致）。 */
    if (found && state.inboxOrigin && !filteredEntries().some(function (x) { return x.e.id === id; })) {
      state.inboxOrigin = '';
    }
    selectNoteById(id);
    render();
  }

  function viewBoard() {
    var d = state.data;
    var cards = d.cards || [];
    var attention = cards.filter(function (c) { return c.needs_attention; });
    var missing = cards.filter(function (c) { return c.summary_source === 'not_generated'; });
    var archived = cards.filter(isArchived);

    /* 顶部两列：左「快速记录」，右「随手记」卡片（≤1100px 堆叠）。数据全部来自已加载的 cards payload。 */
    var html = '<div class="top-row">' +
      '<div class="quick-col">' + quickHtml('quick-form') + '</div>' +
      notesCardHtml() +
      '</div>';

    html += '<div class="grid top-grid">';

    /* 需要我处理：两类条目分开列（待批准提案 / 需要处理的工作卡），不混成一锅 */
    html += attentionPanel(attention, missing.length);

    /* 今日下一步：跨项目任务概览（懒加载，避免每次渲染打 N 个请求） */
    html += boardNextPanel();

    html += '</div>';

    /* 项目概览：只显示真实字段，进度/阶段不编 */
    html += '<div class="section-title"><div><h2>' + esc(t('board.overviewHeading')) + '</h2>' +
      '<p class="subtle">' + esc(format(t('board.overviewSubtitle'), { n: d.projects.length })) + '</p></div>' +
      '<button class="btn small" type="button" data-goto="projects">' + esc(t('board.viewAllProjects')) + '</button></div>';
    html += '<div class="grid project-grid">';
    projectOrder(d.projects).slice(0, 6).forEach(function (p) { html += projectCardHtml(p); });
    html += '</div>';

    /* AI 工作动态 */
    var active = cards.filter(function (c) { return !isArchived(c); });
    active.sort(function (a, b) { return (Date.parse(b.recorded_at) || 0) - (Date.parse(a.recorded_at) || 0); });
    html += '<div class="section-title"><div><h2>' + esc(t('board.activityHeading')) + '</h2>' +
      '<p class="subtle">' + esc(t('board.activitySubtitle')) + '</p></div>' +
      '<span class="subtle" style="font-size:12px">' + esc(format(t('board.cardSummary'), { n: cards.length })) +
      (archived.length ? esc(format(t('proj.archivedCount'), { n: archived.length })) : '') + '</span></div>';
    html += '<div class="grid agent-grid">';
    if (!active.length) html += '<div class="panel"><div class="empty">' + esc(t('board.noActiveCards')) + '</div></div>';
    active.slice(0, 9).forEach(function (c) { html += agentCardHtml(c); });
    html += '</div>';

    return html;
  }

  function proposalRowHtml(p) {
    var sel = state.proposal === p.id;
    var changes = p.changes || [];
    var criteria = 0;
    changes.forEach(function (c) { criteria += (c.criteria || []).length; });
    return '<button type="button" class="card-row' + (sel ? ' selected' : '') + '" data-proposal-id="' + esc(p.id) + '">' +
      '<span class="card-title">' + esc(p.title || t('pr.noTitle')) + '</span>' +
      '<span class="task-row">' +
      '<span class="badge amber">' + esc(t('pr.pending')) + '</span>' +
      (p.project ? '<span class="chip">' + esc(p.project) + '</span>'
                 : '<span class="chip dashed" title="' + esc(t('pr.noProjectTitle')) + '">' + esc(t('pr.noProject')) + '</span>') +
      '<span class="chip">' + esc(format(t('pr.changesN'), { n: changes.length })) + '</span>' +
      (criteria ? '<span class="chip">' + esc(format(t('pr.criteriaN'), { n: criteria })) + '</span>' : '') +
      '<span class="chip" title="' + esc(t('pr.planRevTitle')) + '">plan rev ' + esc(String(p.plan_revision)) + '</span>' +
      '<span class="chip" title="' + esc(t('pr.createdByTitle')) + '">' + (p.created_by === 'ai' ? esc(t('pr.aiMade')) : esc(p.created_by || t('pr.unknown'))) + '</span>' +
      '</span>' +
      '<span class="task-row subtle" style="font-size:11.5px">' + esc(t('pr.sourcePrefix')) + esc(p.source_inbox_id || '—') +
      esc(t('pr.revSuffix')) + esc(String(p.revision)) + esc(format(t('pr.lineFmt'), { n: String(p.line) })) + '</span>' +
      '</button>';
  }

  /* task-209：折叠状态（动态属性，不新增第二套折叠状态；与 state.needsMe 同一做法） */
  function folds() { if (!state.folds) state.folds = {}; return state.folds; }

  /* task-186：收件箱状态说明卡 —— **静态**：不发请求、不可交互、不改既有布局行为。
     内容唯一来源 ${SOURCE_FILE} 的常量；含义取自 pm inbox 的真实行为，并在每行写明来源。 */
  function inboxStatusLegendHtml() {
    /* 表本身（pm-inbox-status.js）保持纯数据：文案在使用点按键取（模块级不调 t()，否则会冻结语言）。 */
    var rows = INBOX_STATUS_TABLE.map(function (s) {
      return '<tr><td><code>' + esc(s.key) + '</code></td>' +
        '<td>' + esc(t('leg.st.' + s.key + '.zh')) + '</td>' +
        '<td>' + esc(t('leg.st.' + s.key + '.meaning')) + (isTerminalStatus(s.key) ? ' <span class="chip dashed">' + esc(t('leg.terminal')) + '</span>' : '') + '</td>' +
        '<td class="subtle legend-src">' + esc(t('leg.st.' + s.key + '.source')) + '</td></tr>';
    }).join('');
    return '<section class="panel status-legend" id="inbox-status-legend">' +
      '<div class="panel-head"><div><h2>' + esc(t('panel.inboxLegend')) + '</h2>' +
      '<p class="subtle">' + esc(format(t('leg.summaryA'), { n: INBOX_STATUS_TABLE.length })) + '<code>' + esc(SOURCE_FILE) + '</code>' + esc(format(t('leg.summaryB'), { list: TERMINAL_STATUSES.join(' / ') })) + '<code>pm inbox</code>' + esc(t('leg.summaryC')) +
      esc(t('leg.summaryD')) + '</p></div></div>' +
      '<div class="panel-body"><table class="legend-table"><thead><tr>' +
      '<th>' + esc(t('leg.thStatus')) + '</th><th>' + esc(t('leg.thZh')) + '</th><th>' + esc(t('leg.thMeaning')) + '</th><th>' + esc(t('leg.thSource')) + '</th></tr></thead><tbody>' + rows + '</tbody></table>' +
      '<p class="hint">' + esc(t('leg.stateMachineNote')) + '</p>' +
      '<p class="hint">' + esc(t('leg.appendA')) + '<code>annotate</code>' + esc(t('leg.appendB')) + '<code>edit</code>' + esc(t('leg.appendC')) + '<code>pin</code>·<code>unpin</code>' + esc(t('leg.appendD')) +
      '<b>' + esc(t('leg.appendE')) + '</b>' + esc(t('leg.appendF')) + '<code>:ID:</code>' + esc(t('leg.appendG')) + '</p>' +
      '</div></section>';
  }

  /* task-184：折叠状态（localStorage 持久化，一个稳定 key；解析失败当没折叠） */
  function needsMeState() {
    if (!state.needsMe) {
      var raw = null;
      try { raw = localStorage.getItem(COLLAPSE_KEY); } catch (e) { raw = null; }
      state.needsMe = parseCollapse(raw);
    }
    return state.needsMe;
  }

  function needsMeToggle(kind) {
    var st = needsMeState();
    if (kind === 'props') st.propsCollapsed = !st.propsCollapsed;
    else if (kind === 'cards') st.cardsCollapsed = !st.cardsCollapsed;
    else if (kind === 'expand') st.cardsExpanded = !st.cardsExpanded;
    state.needsMe = st;
    try { localStorage.setItem(COLLAPSE_KEY, serializeCollapse(st)); } catch (e) { /* 存不了就只在本次会话生效 */ }
    render();
  }

  /* 单张需要处理的工作卡：逐字说明「为什么需要你处理」+ 一句下一步；保留「打开会话」 */
  function attentionRowHtml(c) {
    var reasons = attentionReasons(c);
    var suggest = attentionSuggestion(c);
    return '<div class="item is-attention">' +
      '<div class="item-main">' +
      '<button type="button" class="item-title link" data-session="' + esc(c.session_id) + '"' +
      ' data-instance="' + esc(c.instance) + '">' + esc(cardTitle(c)) + '</button>' +
      '<div class="item-meta">' +
      '<span>' + esc(c.project) + '</span>' + obsBadge(c) + instChip(c) + summaryChip(c) +
      '<span>' + esc(format(t('att.observedAt'), { t: relTime(c.recorded_at) })) + '</span>' +
      '</div>' +
      (reasons.length
        ? '<ul class="attention-why">' + reasons.map(function (r) { return '<li>' + esc(r) + '</li>'; }).join('') + '</ul>'
        : '<p class="attention-why subtle">' + esc(t('att.whyUnknown')) + '<code>observation</code>' + esc(t('att.whyUnknown2')) + '<code>open_todos</code>' + esc(t('att.whyUnknown3')) + '</p>') +
      (suggest ? '<p class="attention-next">' + esc(suggest) + '</p>' : '') +
      '</div>' +
      '<div class="item-side"><button type="button" class="btn small" data-open-session="' + esc(c.session_id) +
      '" data-instance="' + esc(c.instance) + '">' + esc(t('row.openSession')) + '</button></div></div>';
  }

  function attentionPanel(attention, missingCount) {
    var props = (state.proposals && state.proposals.items) || [];
    var propError = state.proposals && state.proposals.error;
    var html = '<section class="panel"><div class="panel-head"><div><h2>' + esc(t('panel.needsMe')) + '</h2>' +
      '<p class="subtle">' + esc(t('att.panelHint')) + '</p></div>' +
      '<span class="badge ' + (props.length + attention.length ? 'amber' : 'gray') + '">' +
      esc(format(t('att.itemsN'), { n: props.length + attention.length })) + '</span></div><div class="panel-body">';

    var nms = needsMeState();
    html += '<button type="button" class="group-head needsme-toggle" data-needsme-toggle="props" aria-expanded="' + (nms.propsCollapsed ? 'false' : 'true') + '">' +
      (nms.propsCollapsed ? '▸ ' : '▾ ')  + esc(t('panel.proposals')) + ' <span class="badge amber">' + props.length + '</span>' +
      '<span class="subtle" style="font-weight:400">' + esc(t('att.clickToExpand')) + (nms.propsCollapsed ? esc(t('att.expand')) : esc(t('att.collapse'))) + esc(t('att.collapseTail')) + '</span></button>';
    if (nms.propsCollapsed) {
      html += '<div class="empty subtle">' + esc(t('att.collapsedHint')) + '</div>';
    } else if (!capsReady()) {
      html += '<div class="empty">' + esc(t('att.proposalsNotReady')) + esc(unavailableReason('GET', '/ui-pm/proposals')) + '</div>';
    } else if (propError) {
      html += '<div class="empty">' + esc(t('att.proposalsLoadFailed')) + esc(propError) + '</div>';
    } else if (!state.proposals) {
      html += '<div class="empty">' + esc(t('att.proposalsLoading')) + '</div>';
    } else if (!props.length) {
      html += '<div class="empty">' + esc(t('empty.noProposals')) + '<br><span class="subtle">' +
        esc(t('att.proposalsExplainA')) + '</span></div>';
    } else {
      props.forEach(function (p) { html += proposalRowHtml(p); });
    }

    html += '<button type="button" class="group-head needsme-toggle" style="margin-top:16px" data-needsme-toggle="cards" aria-expanded="' + (nms.cardsCollapsed ? 'false' : 'true') + '">' +
      (nms.cardsCollapsed ? '▸ ' : '▾ ')  + esc(t('panel.attentionCards')) + ' <span class="badge ' +
      (attention.length ? 'amber' : 'gray') + '">' + attention.length + '</span>' +
      '<span class="subtle" style="font-weight:400">' + esc(t('att.clickToCollapse')) + (nms.cardsCollapsed ? esc(t('att.expand')) : esc(t('att.collapse'))) + esc(t('att.collapseTail')) + '</span></button>';
    if (nms.cardsCollapsed) {
      html += '<div class="empty subtle">' + esc(t('att.collapsedHint')) + '</div>';
    } else if (!attention.length) {
      html += '<div class="empty">' + esc(t('empty.noAttention')) +
        '<span class="subtle">' + esc(t('empty.noAttentionNote')) + '</span></div>';
    } else {
      /* 长列表收敛：默认前 N 条（按项目分组，组头带**全量**张数）+ 「展开全部（N）」 */
      var shown = visibleCards(attention, nms.cardsExpanded === true);
      var allGroups = groupByProject(attention, projectTitleOf);
      var shownKeys = {};
      shown.forEach(function (c) { shownKeys[String(c.project || '')] = true; });
      groupByProject(shown, projectTitleOf).forEach(function (g) {
        var full = null;
        allGroups.forEach(function (x) { if (x.key === g.key) full = x; });
        html += '<div class="needsme-group"><div class="group-head">' + esc(g.title) +
          ' · ' + esc(format(t('att.cardsCount'), { n: (full ? full.cards.length : g.cards.length) })) + '</div>';
        g.cards.forEach(function (c) { html += attentionRowHtml(c); });
        html += '</div>';
      });
      if (!nms.cardsExpanded && attention.length > shown.length) {
        html += '<button type="button" class="btn small" data-needsme-toggle="expand">' + esc(expandAllText(attention.length)) + '</button>';
      } else if (nms.cardsExpanded && attention.length > DEFAULT_VISIBLE) {
        html += '<button type="button" class="btn small" data-needsme-toggle="expand">' + esc(format(t('att.expandBtn'), { n: DEFAULT_VISIBLE })) + '</button>';
      }
      html += '<p class="subtle" style="margin-top:8px">' + esc(ignoreNote()) + '</p>';
    }
    html += '<div class="notice">' + esc(t('att.missingA')) + '<b>' + missingCount + '</b>' + esc(t('att.missingB')) +
      esc(t('att.missingC')) + '<br>' + esc(t('att.missingD')) + '</div>';
    html += '</div></section>';
    return html;
  }

  function projectTitleOf(key) {
    var hit = ((state.data && state.data.projects) || []).filter(function (p) { return p.key === key; })[0];
    return hit ? hit.title : key;
  }

  function projectOrder(projects) {
    return projects.slice().sort(function (a, b) {
      return (Date.parse(b.last_recorded) || 0) - (Date.parse(a.last_recorded) || 0);
    });
  }

  function projectCardHtml(p) {
    return '<article class="panel project" data-project-card="' + esc(p.key) + '">' +
      '<div class="project-top"><div><button type="button" class="project-title" data-project="' + esc(p.key) + '">' +
      esc(p.title) + '</button>' +
      '<div class="project-key">key: ' + esc(p.key) + '</div>' +
      '<div class="project-path">' + esc((p.paths && p.paths[0]) || t('proj.noPath')) + '</div></div>' +
      '<span class="badge ' + (p.attention ? 'amber' : 'gray') + '">' +
      (p.attention ? format(t('proj.needsAttention'), { n: p.attention }) : t('proj.noAttention')) + '</span></div>' +
      '<div class="project-foot"><span>' + esc(format(t('proj.cards'), { n: p.cards })) + esc(format(t('proj.missingSummary'), { n: p.missing_summary })) +
      (p.stale_busy ? format(t('proj.staleBusy'), { n: p.stale_busy }) : '') + '</span>' +
      '<span>' + esc(format(t('proj.observed'), { time: relTime(p.last_recorded) })) + '</span></div>' +
      '<div class="notice">' + esc(t('proj.nextStep')) + '<span class="chip dashed">' + esc(t('common.notEstablished')) + '</span>' + esc(t('proj.needsTaskModel')) +
      esc(t('proj.acceptanceProgress')) + '<span class="chip dashed">' + esc(t('proj.noAcceptanceBaseline')) + '</span></div>' +
      '</article>';
  }

  /* ================= 任务与记忆：数据层（P3 已接入真实端点） ================= */

  /* 状态机照抄 pm tasks.py 的 ALLOWED_TRANSITIONS（§5.2）：界面只提供这些去向，非法迁移不会出现在按钮里。 */
  var TASK_TRANSITIONS = {
    INBOX: ['TODO', 'NEXT', 'CANCELLED'],
    TODO: ['NEXT', 'CANCELLED'],
    NEXT: ['DOING', 'WAITING', 'BLOCKED', 'CANCELLED'],
    DOING: ['REVIEW', 'WAITING', 'BLOCKED', 'CANCELLED'],
    WAITING: ['NEXT', 'DOING', 'BLOCKED', 'CANCELLED'],
    BLOCKED: ['NEXT', 'DOING', 'WAITING', 'CANCELLED'],
    REVIEW: ['DONE', 'DOING', 'WAITING', 'BLOCKED', 'CANCELLED'],
    DONE: [],
    CANCELLED: []
  };
  function statusBadge(status) {
    var cls = status === 'BLOCKED' ? 'red'
      : (status === 'REVIEW' || status === 'DONE') ? 'green'
      : status === 'CANCELLED' ? 'gray'
      : status === 'DOING' ? 'purple'
      : status === 'WAITING' ? 'amber'
      : status === 'INBOX' ? 'gray' : 'blue';
    return '<span class="badge ' + cls + '">' + esc(TASK_STATUS[status] || status) + '</span>';
  }

  /* ---------- 任务：读取与动作 ---------- */

  function projectByKey(key) {
    return (state.data && state.data.projects || []).filter(function (p) { return p.key === key; })[0] || null;
  }

  function loadBoard(project) {
    if (!project) return Promise.resolve();
    if (!capsReady()) {
      state.board = { project: project, groups: [], error: unavailableReason('GET', '/ui-pm/tasks'), count: 0 };
      return Promise.resolve();
    }
    return httpJson(api('tasks', { project: project })).then(function (x) {
      if (x.ok && x.body.ok === true) {
        var d = x.body.data || {};
        state.board = { project: project, path: d.path, count: d.count || 0, groups: d.groups || [], error: null };
      } else {
        state.board = { project: project, groups: [], count: 0, error: apiError(x).message };
      }
    }).catch(function (err) {
      state.board = { project: project, groups: [], count: 0, error: err.message || String(err) };
    });
  }

  function loadTaskDetail(project, id) {
    if (!capsReady()) {
      state.taskDetail = { project: project, id: id, error: unavailableReason('GET', '/ui-pm/tasks/:id') };
      return Promise.resolve();
    }
    return httpJson(api('tasks/' + encodeURIComponent(id), { project: project })).then(function (x) {
      if (x.ok && x.body.ok === true && x.body.data) {
        state.taskDetail = { project: project, id: id, task: x.body.data.task, path: x.body.data.path, error: null };
      } else {
        state.taskDetail = { project: project, id: id, error: apiError(x).message };
      }
    }).catch(function (err) {
      state.taskDetail = { project: project, id: id, error: err.message || String(err) };
    });
  }

  /* ---------- 点卡片把该列在看板内部居中（task-84；只动 board.scrollLeft，不碰整页） ---------- */
  var BOARD_CENTER_PAD = 12;

  function boardReduceMotion() {
    try { return !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches); } catch (e) { return false; }
  }

  function syncBoardArrows() {
    var b = document.getElementById('project-board');
    if (b && b.__syncArrows) b.__syncArrows();
  }

  /* 返回 {scrolled, target, reason}，方便桩断言与调试 */
  var BOARD_CENTER_TTL = 2000;

  function boardCenterPending() {
    var c = state.boardCenter;
    return !!(c && c.taskId && (Date.now() - c.at) < BOARD_CENTER_TTL);
  }

  /* 纯几何：只算不改（返回 null 表示没有可居中的目标） */
  function boardCenterTarget(taskId, opts) {
    opts = opts || {};
    if (!taskId) return null;
    var boardEl = document.getElementById('project-board');
    if (!boardEl || !boardEl.querySelectorAll) return null;
    var hit = boardEl.querySelectorAll('[data-task-id="' + taskId + '"]');
    var card = (hit && hit.length) ? hit[0] : null;
    if (!card || !card.closest) return null;
    var col = card.closest(KANBAN_COL_SELECTOR);
    if (!col) return null;
    var colW = col.offsetWidth || 0;
    var boardW = boardEl.clientWidth || 0;
    var max = Math.max(0, (boardEl.scrollWidth || 0) - boardW);
    if (!colW || !boardW || max <= 0) return null;
    /* 展开按钮那条路径：列比视口还宽时以「卡可见」为先，放弃居中 */
    if (opts.requireFullColumn && colW > boardW) return null;
    var centered = (col.offsetLeft || 0) - (boardW - colW) / 2;
    /* 两端各留 BOARD_CENTER_PAD 的余量，让相邻列露一点；空间不够时退回普通 clamp */
    var lo = max > BOARD_CENTER_PAD * 2 ? BOARD_CENTER_PAD : 0;
    var hi = max > BOARD_CENTER_PAD * 2 ? max - BOARD_CENTER_PAD : max;
    return { boardEl: boardEl, col: col, colW: colW, max: max, target: Math.max(lo, Math.min(hi, Math.round(centered))) };
  }

  /* 落到目标位置；记下「待完成居中」，并安排收尾 */
  function applyBoardCenter(taskId, t, attempts) {
    var boardEl = t.boardEl;
    var behavior = (attempts >= 2) ? 'auto' : (boardReduceMotion() ? 'auto' : 'smooth');
    if (behavior === 'smooth' && boardEl.scrollTo) {
      try { boardEl.scrollTo({ left: t.target, behavior: 'smooth' }); }
      catch (e) { boardEl.scrollLeft = t.target; behavior = 'auto'; }
    } else {
      boardEl.scrollLeft = t.target;
    }
    state.boardCenter = { taskId: taskId, target: t.target, at: Date.now(), attempts: (attempts || 0) + 1 };
    setTimeout(finishBoardCenter, behavior === 'smooth' ? 460 : 0);
    return behavior;
  }

  /* 收尾：补一次箭头同步；真的到了目标（±2px）才撤掉「待完成居中」标记 */
  function finishBoardCenter() {
    syncBoardArrows();
    var c = state.boardCenter;
    if (!c) return;
    var boardEl = document.getElementById('project-board');
    if (!boardEl) { state.boardCenter = null; return; }
    if (Math.abs((boardEl.scrollLeft || 0) - c.target) <= 2) state.boardCenter = null;
  }

  /* 渲染期间若有「待完成居中」，把目标位置重新落一次（绝不在动画中途写回中途值） */
  function reapplyBoardCenterIfPending() {
    if (!boardCenterPending()) return false;
    var c = state.boardCenter;
    var t = boardCenterTarget(c.taskId);
    if (!t) return false;
    /* 内容被重建 → 平滑动画已经不可能延续：这里**即时**落到目标，
       既不会把中途值写回去，也不会让动画从 0 重新抖一遍（attempts>=2 → 'auto'） */
    applyBoardCenter(c.taskId, t, 2);
    return true;
  }

  function centerBoardOnTask(taskId, opts) {
    var t = boardCenterTarget(taskId, opts);
    if (!t) return { scrolled: false, reason: 'no-target' };
    var cur = t.boardEl.scrollLeft || 0;
    if (Math.abs(t.target - cur) < t.colW * 0.2) {
      state.boardCenter = null;   /* 已经基本居中 → 不滚，也不留待完成标记 */
      return { scrolled: false, target: t.target, reason: 'already-centered' };
    }
    var behavior = applyBoardCenter(taskId, t, 0);
    return { scrolled: true, target: t.target, behavior: behavior, reason: 'centered' };
  }

  /* P2（用户 2026-10-19 裁定）：「点卡片/行 ⇒ 右栏展开详情」抽成公共口径 ——
     右栏收起时点了卡片什么都不显示，用户以为没反应 ✗。只做 false ⇒ true 并持久化；
     **不**在 render 里反向展开（保留用户手动「收起详情」的选择 ✓）。 */
  function ensureDetailOpen() {
    if (state.detailOpen) return;
    state.detailOpen = true;
    try { localStorage.setItem('pm-detail-open', '1'); } catch (e) { /* 忽略 */ }
  }

  function selectTask(project, id) {
    state.task = { project: project, id: id };
    state.taskDetail = null;
    state.card = null;
    /* 点卡片必须看得到结果：右栏收起时自动展开并持久化（公共口径 ensureDetailOpen ✓） */
    ensureDetailOpen();
    var known = state.taskDetail;
    if (!known || known.id !== id) loadTaskDetail(project, id).then(function () { render(); centerBoardOnTask(id); });
    state.keepCardVisible = true;   /* 若这张卡在列里不完整可见 → 渲染后在该列内居中（task-174） */
    render();
    /* task-174：不再强制把右栏滚到顶（那会让列表/详情位置乱跳）；只把焦点给标题、且 preventScroll */
    var body = el.detailBody;
    var head = (body && body.querySelector) ? body.querySelector('#task-detail-head') : null;
    if (head && head.focus) {
      /* preventScroll：只滚右栏，别让浏览器把整页也滚下去（task-84 ①） */
      try { head.focus({ preventScroll: true }); } catch (e) { try { head.focus(); } catch (e2) {} }
    }
    centerBoardOnTask(id);   /* 点卡片 → 该列在看板内部居中 */
  }

  function taskTransition(project, id, to, revision, reason) {
    return performWrite({
      slot: 'task-transition|' + id + '|' + to,
      method: 'PATCH', path: 'tasks/' + encodeURIComponent(id),
      revision: revision, body: { action: 'transition', project: project, to: to, reason: reason },
      label: '任务流转 ' + (TASK_STATUS[to] || to), ident: id,
      afterOk: function () { return reloadTaskViews(project, id); },
      afterConflict: function () { return reloadTaskViews(project, id); }
    });
  }

  /* task-132：优先用稳定 ID（criteria[].id → criterionId）；旧实例没有 id 时退回 index，
     并在界面上如实标注「按位置定位」。两者**恰好给一个**（都给/都不给后端会 400）。 */
  function taskCheck(project, id, criterion, index, uncheck, revision) {
    var cid = (!state.criterionIdUnsupported && criterion && criterion.id) ? String(criterion.id) : '';
    var target = cid ? { criterionId: cid } : { index: index };
    return performWrite({
      slot: 'task-check|' + id + '|' + (cid || ('i' + index)) + '|' + (uncheck ? 'u' : 'c'),
      method: 'PATCH', path: 'tasks/' + encodeURIComponent(id),
      revision: revision,
      body: Object.assign({ action: 'check', project: project, uncheck: uncheck === true }, target),
      label: (uncheck ? '取消勾选标准 ' : '勾选标准 ') + (cid || (index + 1)), ident: id,
      afterOk: function () { return reloadTaskViews(project, id); },
      afterConflict: function () { return reloadTaskViews(project, id); }
    }).then(function () {
      /* 宿主能力降级：路由明确说「不接受 criterionId」时，粘性退回 index（如实标注，不假装新路径） */
      var we = state.writeError;
      var unknown = (we && we.body && we.body.unknownFields) || [];
      if (we && String(we.code) === 'UNKNOWN_FIELDS' && unknown.indexOf('criterionId') >= 0) {
        state.criterionIdUnsupported = true;
        render();
      }
    });
  }

  function taskCreate(project, title, goal, nonGoal, criteria) {
    return performWrite({
      slot: 'task-create|' + project + '|' + title,
      path: 'tasks', revision: null,
      body: { project: project, title: title, goal: goal, nonGoal: nonGoal, criterion: criteria },
      label: '新建任务', ident: project,
      afterOk: function () { return loadBoard(project); }
    });
  }

  function reloadTaskViews(project, id) {
    return Promise.all([
      loadBoard(project),
      loadTaskDetail(project, id),
      state.view === 'review' ? loadReview() : Promise.resolve()
    ]);
  }

  /* ---------- 待验收：按项目逐个查 REVIEW（端点要求 project 必填） ---------- */

  function loadReview() {
    if (!capsReady()) {
      state.review = { items: [], errors: [], fetchedAt: new Date().toISOString(), error: unavailableReason('GET', '/ui-pm/tasks') };
      return Promise.resolve();
    }
    var projects = (state.data && state.data.projects || []).map(function (p) { return p.key; });
    var items = [];
    var errors = [];
    var chain = Promise.resolve();
    projects.forEach(function (key) {
      chain = chain.then(function () {
        return httpJson(api('tasks', { project: key, status: 'REVIEW' })).then(function (x) {
          if (x.ok && x.body.ok === true) {
            ((x.body.data || {}).groups || []).forEach(function (g) {
              (g.tasks || []).forEach(function (t) { items.push(Object.assign({ project: key }, t)); });
            });
          } else {
            errors.push({ project: key, message: apiError(x).message });
          }
        }).catch(function (err) { errors.push({ project: key, message: err.message || String(err) }); });
      });
    });
    return chain.then(function () {
      state.review = { items: items, errors: errors, fetchedAt: new Date().toISOString(), error: null };
    });
  }

  function loadReviewDetail(project, id) {
    return loadTaskDetail(project, id);
  }

  /* ---------- 记忆：候选 / 正式 / 上下文 ---------- */

  function loadMemory() {
    if (!capsReady()) {
      state.memory = { candidates: [], entries: [], error: unavailableReason('GET', '/ui-pm/memory') };
      return Promise.resolve();
    }
    /* 用户 2026-10-21："两处记录数量不一致" —— 根因是计数口径分裂：
       entries 走服务端 scope 过滤、而 `/ui-pm/memory/candidates` 路由**不支持 scope** 只能拿全量，
       于是下拉计数（全量 candidates+entries）与 tabs/列表（scoped）对不上 ✗。
       ⇒ 改为**一次拉全量**，scope 过滤统一在 viewMemory 里客户端做（展示与计数同源 ✓）。 */
    return Promise.all([
      httpJson(api('memory/candidates')),
      httpJson(api('memory'))
    ]).then(function (res) {
      var cand = res[0], mem = res[1];
      var out = { candidates: [], entries: [], unsourcedCount: 0, error: null, errors: [] };
      if (cand.ok && cand.body.ok === true) {
        var cd = cand.body.data || {};
        out.candidates = cd.entries || [];
        out.unsourcedCount = cd.unsourcedCount || 0;
      } else { out.errors.push(t('memp.errCandidates') + apiError(cand).message); }
      if (mem.ok && mem.body.ok === true) {
        out.entries = (mem.body.data || {}).entries || [];
      } else { out.errors.push(t('memp.errEntries') + apiError(mem).message); }
      out.error = out.errors.length ? out.errors.join(' · ') : null;
      state.memory = out;
    }).catch(function (err) {
      state.memory = { candidates: [], entries: [], error: err.message || String(err) };
    });
  }

  /* 用户 2026-10-21：检索必须带**当前项目 scope + 类型**两个过滤器（此前只传 q ⇒ 搜出别的项目的记忆 ✗）；
     放在模块级，供搜索框、切 scope、切类型三处共用同一实现 ✓ */
  function memoryRunSearch(term, opts) {
    var q = String(term == null ? '' : term).trim();
    if (!q) { state.memSearch = null; state.memHit = null; if (state.view === 'memory') render(); return Promise.resolve(); }
    /* 用户 2026-10-21：**新检索**默认展示"全部"档（否则默认候选档会像"没搜到"✗）；
       由 scope/类型下拉触发的重搜保留用户当前档位（keepTier ✓）*/
    if (!(opts && opts.keepTier)) state.memoryTier = 'all';
    var scope = String(state.memoryScope || '');
    var type = String(state.memoryType || '');
    var qs = 'q=' + encodeURIComponent(q) + '&limit=20' +
      (scope ? '&scope=' + encodeURIComponent(scope) : '') +
      (type ? '&type=' + encodeURIComponent(type) : '');
    state.memHit = null;
    return fetch('/ui-pm/recall?' + qs, { headers: { accept: 'application/json' } })
      .then(function (r) { return r.json() })
      .then(function (j) {
        var d = (j && j.data) || {};
        /* 兼容 CLI 透传的**双层包装**：/ui-pm/recall 返回 {ok:true,data:{data:{hits:[…]}}} ✓ */
        if (d && d.data && (d.data.hits || d.data.results)) d = d.data;
        state.memSearch = { term: q, scope: scope, type: type, count: d.count, hits: d.hits || d.results || [], error: null };
        if (state.view === 'memory') render();
      })
      .catch(function (e) {
        state.memSearch = { term: q, scope: scope, type: type, hits: [], error: (e && e.message) || String(e) };
        if (state.view === 'memory') render();
      });
  }

  function loadMemoryContext(scope) {
    if (!scope || !capsReady()) { state.context = null; return Promise.resolve(); }
    return httpJson(api('memory/context', { scope: scope })).then(function (x) {
      state.context = (x.ok && x.body.ok === true) ? x.body.data : null;
    }).catch(function () { state.context = null; });
  }

  function loadProjectMemory(project) {
    if (!capsReady()) {
      state.projectMemory = { error: unavailableReason('GET', '/ui-pm/memory'), entries: [] };
      return Promise.resolve();
    }
    return httpJson(api('memory', { scope: project })).then(function (x) {
      if (x.ok && x.body.ok === true) {
        state.projectMemory = { entries: (x.body.data || {}).entries || [], error: null };
      } else {
        state.projectMemory = { entries: [], error: apiError(x).message };
      }
    }).catch(function (err) {
      state.projectMemory = { entries: [], error: err.message || String(err) };
    });
  }

  /* ---------- 工作台：跨项目任务概览（懒加载，避免每帧 N 次请求） ---------- */

  /* ---------- 提案（§5.3）：工作台「需要我处理」的待批准队列 ---------- */

  /* ================= AI 执行准备向导（内部记录（未随仓库发布） §0 §3） =================
   * 红线：不实现假 dispatch —— 这里只保存执行配置或复制 handoff，
   * dispatchStatus 只显示后端给的 NOT_READY / HANDOFF_READY，绝不声称「已派发 / 正在执行」。
   * 步骤：① 项目 ② 工作区 ③ 上下文记忆 ④ 会话 ⑤ 附加说明 ⑥ 预览与确认。
   * 端点全部按 capabilities 判断；缺失时按钮禁用并写明缺哪个 endpoint。 */

  var EXEC_STEPS = ['项目', '工作区', '上下文记忆', '会话', '附加说明', '预览与确认'];

  function execStorageKey(id) { return 'pm-exec-draft|' + id; }

  function loadExecDraft(id) {
    try {
      var raw = localStorage.getItem(execStorageKey(id));
      if (!raw) return null;
      var parsed = JSON.parse(raw);
      return (parsed && typeof parsed === 'object') ? parsed : null;
    } catch (e) { return null; }
  }

  function saveExecDraft() {
    if (!state.execTask) return;
    try {
      localStorage.setItem(execStorageKey(state.execTask.id), JSON.stringify({
        draft: state.execDraft, step: state.execStep, savedAt: new Date().toISOString()
      }));
    } catch (e) { /* 存不下不影响本次会话 */ }
  }

  function clearExecDraft(id) {
    try { localStorage.removeItem(execStorageKey(id)); } catch (e) {}
  }

  function execCaps() {
    return {
      workspaces: endpointListed('GET', '/ui-pm/workspaces'),
      projectContext: endpointListed('GET', '/ui-pm/projects/:id/context'),
      workspaceContext: endpointListed('GET', '/ui-pm/workspaces/context'),
      config: endpointListed('GET', '/ui-pm/tasks/:id/execution-config'),
      saveConfig: endpointListed('POST', '/ui-pm/tasks/:id/execution-config'),
      link: endpointListed('POST', '/ui-pm/tasks/:id/link-session'),
      unlink: endpointListed('POST', '/ui-pm/tasks/:id/unlink-session'),
      handoff: endpointListed('GET', '/ui-pm/tasks/:id/handoff')
    };
  }

  function execErr(node, x) {
    var e = apiError(x);
    state.execData.error = e.code + '：' + e.message;
    return e;
  }

  function loadExecWorkspaces(project) {
    if (!project) return Promise.resolve();
    if (!execCaps().workspaces) {
      state.execData.workspaces = { error: missingEndpointText('GET', '/ui-pm/workspaces'), items: [] };
      return Promise.resolve();
    }
    return httpJson(api('workspaces', { project: project })).then(function (x) {
      if (x.ok && x.body.ok === true) state.execData.workspaces = { items: (x.body.data || {}).workspaces || [], error: null };
      else state.execData.workspaces = { items: [], error: apiErrText(x) };
    }).catch(function (err) { state.execData.workspaces = { items: [], error: err.message || String(err) }; });
  }

  function apiErrText(x) { var e = apiError(x); return e.code + '：' + e.message; }

  function loadExecProjectMemories(project) {
    if (!project) return Promise.resolve();
    if (!execCaps().projectContext) {
      state.execData.projectMemories = { error: missingEndpointText('GET', '/ui-pm/projects/:id/context'), items: [] };
      return Promise.resolve();
    }
    return httpJson(api('projects/' + encodeURIComponent(project) + '/context')).then(function (x) {
      if (x.ok && x.body.ok === true) state.execData.projectMemories = { items: (x.body.data || {}).memories || [], error: null };
      else state.execData.projectMemories = { items: [], error: apiErrText(x) };
    }).catch(function (err) { state.execData.projectMemories = { items: [], error: err.message || String(err) }; });
  }

  function loadExecWorkspaceContext(path) {
    if (!path) return Promise.resolve();
    if (!execCaps().workspaceContext) {
      state.execData.workspaceContext = { error: missingEndpointText('GET', '/ui-pm/workspaces/context'), memories: [], sessions: [] };
      return Promise.resolve();
    }
    return httpJson(api('workspaces/context', { path: path })).then(function (x) {
      if (x.ok && x.body.ok === true) {
        var d = x.body.data || {};
        state.execData.workspaceContext = { memories: d.memories || [], sessions: d.sessions || [], project: d.project, error: null };
      } else state.execData.workspaceContext = { memories: [], sessions: [], error: apiErrText(x) };
    }).catch(function (err) { state.execData.workspaceContext = { memories: [], sessions: [], error: err.message || String(err) }; });
  }

  function loadExecConfig(id) {
    if (!execCaps().config) {
      state.execData.config = { error: missingEndpointText('GET', '/ui-pm/tasks/:id/execution-config'), value: null };
      return Promise.resolve();
    }
    return httpJson(api('tasks/' + encodeURIComponent(id) + '/execution-config')).then(function (x) {
      if (x.ok && x.body.ok === true) state.execData.config = { value: x.body.data || {}, error: null };
      else state.execData.config = { value: null, error: apiErrText(x) };
    }).catch(function (err) { state.execData.config = { value: null, error: err.message || String(err) }; });
  }

  function loadExecHandoff(id) {
    if (!execCaps().handoff) {
      state.execData.handoff = { error: missingEndpointText('GET', '/ui-pm/tasks/:id/handoff'), text: null, fields: null };
      return Promise.resolve();
    }
    return httpJson(api('tasks/' + encodeURIComponent(id) + '/handoff')).then(function (x) {
      if (x.ok && x.body.ok === true) {
        var d = x.body.data || {};
        state.execData.handoff = { text: d.text || d.handoff || null, fields: d.fields || d, error: null };
      } else state.execData.handoff = { text: null, fields: null, error: apiErrText(x) };
    }).catch(function (err) { state.execData.handoff = { text: null, fields: null, error: err.message || String(err) }; });
  }

  function openExecWizard(task, revision) {
    var caps = execCaps();
    var draft = null;
    var restored = false;
    var saved = loadExecDraft(task.id);
    if (saved && saved.draft) { draft = saved.draft; restored = true; }
    state.execTask = { project: task.projectId || state.project || '', id: task.id, title: task.title, revision: revision };
    state.execDraft = draft || { project: task.projectId || '', workspace: '', instance: '', session: '', memoryRefs: [], note: '' };
    state.execStep = (saved && saved.step) ? saved.step : 1;
    state.execDraftRestored = restored;
    state.execData = { workspaces: null, memories: null, sessions: null, config: null, handoff: null, error: null };
    var dlg = document.getElementById('exec-dialog');
    if (dlg && dlg.showModal) dlg.showModal();
    fetchExecDataForStep().then(renderExec);
  }

  function fetchExecDataForStep() {
    var d = state.execDraft;
    var jobs = [];
    if (state.execStep >= 2 && !state.execData.workspaces) jobs.push(loadExecWorkspaces(d.project));
    if (state.execStep >= 3 && !state.execData.projectMemories) jobs.push(loadExecProjectMemories(d.project));
    if (state.execStep >= 2 && d.workspace && !state.execData.workspaceContext) jobs.push(loadExecWorkspaceContext(d.workspace));
    if (state.execStep >= 6 && !state.execData.handoff) jobs.push(loadExecHandoff(state.execTask.id));
    if (!state.execData.config) jobs.push(loadExecConfig(state.execTask.id));
    return Promise.all(jobs);
  }

  /* 读「当前勾选」的单选值：不依赖 change 事件是否已经派发 */
  function pickChecked(sel) {
    if (!document.querySelector) return '';
    var node = document.querySelector(sel);
    return (node && node.value) ? node.value : '';
  }

  /* 每步的输入在「下一步」之前读进草稿 */
  function captureExecStep() {
    var d = state.execDraft;
    var pick = function (id) { var el2 = document.getElementById(id); return el2 ? el2.value : ''; };
    if (state.execStep === 1) {
      var pv = pick('exec-project');
      if (pv !== undefined && pv !== null && pv !== '') d.project = pv;
    } else if (state.execStep === 2) {
      /* 工作区是单选按钮：以「当前勾选的那个」为准（比依赖 change 事件更稳，键盘选择也不会漏） */
      var wsChecked = pickChecked('input[name="exec-workspace-radio"]:checked');
      if (wsChecked) d.workspace = wsChecked;
      var instEl = document.getElementById('exec-instance');
      if (instEl) d.instance = instEl.value;
    } else if (state.execStep === 3) {
      d.memoryRefs = [];
      var boxes = document.querySelectorAll ? document.querySelectorAll('[data-exec-memory]') : [];
      Array.prototype.forEach.call(boxes, function (b) { if (b.checked) d.memoryRefs.push(b.getAttribute('data-exec-memory')); });
    } else if (state.execStep === 4) {
      var sChecked = pickChecked('input[name="exec-session-radio"]:checked');
      if (sChecked) d.session = sChecked;
      var sEl = document.getElementById('exec-session');
      if (sEl && sEl.value) d.session = sEl.value;
    } else if (state.execStep === 5) {
      var nEl = document.getElementById('exec-note');
      if (nEl) d.note = nEl.value;
    }
    saveExecDraft();
  }

  function dispatchStatusText(v) {
    if (v === 'NOT_READY') return t('ex.notReady');
    if (v === 'HANDOFF_READY') return t('ex.handoffReady');
    if (!v) return t('ex.dashPending');
    return String(v) + t('ex.notInContract');
  }

  function renderExec() {
    if (!state.execTask) return;
    var d = state.execDraft;
    var caps = execCaps();
    var body = document.getElementById('exec-body');
    var sub = document.getElementById('exec-sub');
    var status = document.getElementById('exec-status');
    var prev = document.getElementById('exec-prev');
    var next = document.getElementById('exec-next');
    var save = document.getElementById('exec-save');
    var copy = document.getElementById('exec-copy');
    var discard = document.getElementById('exec-discard');
    if (!body) return;

    if (sub) {
      sub.textContent = t('ex.taskPrefix') + state.execTask.title + esc(t('ex.parenOpen')) + state.execTask.id + esc(t('ex.parenClose')) + t('ex.stepPrefix') + state.execStep +
        t('ex.stepOf') + EXEC_STEPS[state.execStep - 1] + (state.execDraftRestored ? t('ex.draftRestored') : '');
    }
    var stepsHtml = '<ol class="steps">' + EXEC_STEPS.map(function (label, i) {
      return '<li' + (state.execStep === i + 1 ? ' aria-current="step"' : '') + '>' + (i + 1) + ' ' + esc(label) + '</li>';
    }).join('') + '</ol>';
    var html = stepsHtml;

    var missingCaps = [];
    if (!caps.workspaces) missingCaps.push('GET /ui-pm/workspaces');
    if (!caps.projectContext) missingCaps.push('GET /ui-pm/projects/:id/context');
    if (!caps.workspaceContext) missingCaps.push('GET /ui-pm/workspaces/context');
    if (!caps.config) missingCaps.push('GET /ui-pm/tasks/:id/execution-config');
    if (!caps.saveConfig) missingCaps.push('POST /ui-pm/tasks/:id/execution-config');
    if (!caps.link) missingCaps.push('POST /ui-pm/tasks/:id/link-session');
    if (!caps.unlink) missingCaps.push('POST /ui-pm/tasks/:id/unlink-session');
    if (!caps.handoff) missingCaps.push('GET /ui-pm/tasks/:id/handoff');
    if (missingCaps.length) {
      html += '<div class="exec-missing"><b>' + esc(t('ex.missingEndpoints')) + '</b>' + esc(t('ex.missingEndpointsTail')) +
        missingCaps.map(function (m) { return '<code>' + esc(m) + '</code>'; }).join(t('ex.listSep')) + '</div>';
    }
    if (state.execData.error) {
      html += '<div class="exec-missing">' + esc(state.execData.error) + '</div>';
    }
    if (state.execDraftRestored) {
      html += '<div class="notice">' + esc(t('exl.draftRestoredA')) +
        esc(t('exl.draftRestoredB')) + '</div>';
    }

    var projectOptions = (state.data.projects || []).map(function (p) {
      return '<option value="' + esc(p.key) + '"' + (d.project === p.key ? ' selected' : '') + '>' +
        esc(p.title) + esc(t('ex.parenOpen')) + esc(p.key) + esc(t('ex.projectOptionTail')) + '</option>';
    }).join('');

    if (state.execStep === 1) {
      html += '<p class="hint">' + esc(t('ex.step1A')) + '<b>' + esc(t('ex.step1B')) + '</b>' + esc(t('ex.step1C')) +
        esc(t('exl.projectAdviceA')) + '<code>' + esc(state.execTask.project || t('exl.unknownProject')) + '</code>' + esc(t('exl.projectAdviceB')) + '</p>' +
        '<label class="field"><span>' + esc(t('ex.projectLabel')) + '</span><select id="exec-project">' +
        '<option value="">' + esc(t('ex.notChosen')) + '</option>' + projectOptions + '</select></label>';
    } else if (state.execStep === 2) {
      html += '<p class="hint">' + esc(t('ex.step2')) + '<b>' + esc(t('ex.step2B')) + '</b>' + esc(t('ex.step2C')) + '</p>';
      if (!caps.workspaces) {
        html += '<div class="exec-missing">' + esc(missingEndpointText('GET', '/ui-pm/workspaces')) + '</div>';
      } else if (!state.execData.workspaces) {
        html += '<div class="exec-none">' + esc(t('ex.loadingWorkspaces')) + '</div>';
      } else if (state.execData.workspaces.error) {
        html += '<div class="exec-missing">' + esc(t('ex.loadFailed')) + esc(state.execData.workspaces.error) + '</div>';
      } else if (!state.execData.workspaces.items.length) {
        html += '<div class="exec-none">' + esc(t('ex.noWorkspace')) + '</div>';
      } else {
        state.execData.workspaces.items.forEach(function (w) {
          html += '<label class="exec-choice"><input type="radio" name="exec-workspace-radio" value="' + esc(w.path) + '"' +
            (d.workspace === w.path ? ' checked' : '') + '>' +
            '<span class="exec-main"><b>' + esc(w.title || w.path) + '</b>' +
            '<span class="exec-meta">' + esc(w.path) + esc(t('ex.instanceMeta')) + esc(w.instance || '—') +
            esc(t('ex.workspaceSessionsA')) + esc(String(w.sessionCount === undefined ? '—' : w.sessionCount)) + esc(t('ex.workspaceSessionsB')) + '</span></span></label>';
        });
        html += '<label class="field"><span>' + esc(t('ex.instanceLabel')) + '</span>' +
          '<input type="text" id="exec-instance" value="' + esc(d.instance || '') + '" placeholder="default / preview / learn"></label>';
      }
    } else if (state.execStep === 3) {
      html += '<p class="hint">' + esc(t('ex.step3A')) + '<b>' + esc(t('ex.step3B')) + '</b>' + esc(t('ex.step3C')) +
        esc(t('ex.step3D')) + '</p>';
      var mems = [];
      var pm2 = state.execData.projectMemories;
      if (pm2 && pm2.items) pm2.items.forEach(function (m) { mems.push(Object.assign({ src: t('ex.srcProject') }, m)); });
      var wc = state.execData.workspaceContext;
      if (wc && wc.memories) wc.memories.forEach(function (m) {
        if (!mems.some(function (x) { return x.id === m.id; })) mems.push(Object.assign({ src: t('ex.srcWorkspace') }, m));
      });
      if (!caps.projectContext) html += '<div class="exec-missing">' + esc(missingEndpointText('GET', '/ui-pm/projects/:id/context')) + '</div>';
      if (d.workspace && !caps.workspaceContext) html += '<div class="exec-missing">' + esc(missingEndpointText('GET', '/ui-pm/workspaces/context')) + '</div>';
      if (pm2 && pm2.error) html += '<div class="exec-missing">' + esc(t('ex.ctxLoadFailed')) + esc(pm2.error) + '</div>';
      if (!mems.length && caps.projectContext) {
        html += '<div class="exec-none">' + esc(t('ex.noVerified')) +
          esc(t('ex.noVerified2')) + '</div>';
      }
      mems.forEach(function (m) {
        var checked = (d.memoryRefs || []).indexOf(m.id) >= 0;
        /* task-01M52AMT6895：表单控件必须有 id 或 name（DevTools「A form field element should have an id or name attribute」）；
           id 用 m.id 派生 ⇒ 列表内唯一（exec-mem-<id>）。 */
        html += '<label class="exec-choice"><input type="checkbox" id="exec-mem-' + esc(m.id) + '"' + (checked ? ' checked' : '') + ' data-exec-memory="' + esc(m.id) + '">' +
          '<span class="exec-main"><b>' + esc(MEMORY_TYPES[m.type] || m.type || t('ex.untyped')) + '</b> ' + esc(m.text) +
          '<span class="exec-meta">' + esc(m.id) + ' · scope ' + esc(m.scope || '—') +
          esc(t('ex.srcPrefix')) + esc(m.src) + esc(t('ex.statusPrefix')) + esc(m.status || '—') + '</span></span></label>';
      });
      html += '<p class="hint">' + esc(t('exl.candidateNotInjected')) + '<code>:ID:</code>' + esc(t('exl.candidateNotInjectedB')) + '</p>';
    } else if (state.execStep === 4) {
      html += '<p class="hint">' + esc(t('exl.step4A')) + '<b>' + esc(t('exl.step4B')) + '</b>' + esc(t('exl.step4C')) + '</p>';
      var sessions = (state.execData.workspaceContext && state.execData.workspaceContext.sessions) || [];
      if (!d.workspace) {
        html += '<div class="exec-none">' + esc(t('ex.pickWorkspaceFirst')) + '</div>';
      } else if (!caps.workspaceContext) {
        html += '<div class="exec-missing">' + esc(missingEndpointText('GET', '/ui-pm/workspaces/context')) + '</div>';
      } else if (state.execData.workspaceContext && state.execData.workspaceContext.error) {
        html += '<div class="exec-missing">' + esc(t('ex.loadFailed')) + esc(state.execData.workspaceContext.error) + '</div>';
      } else if (!sessions.length) {
        html += '<div class="exec-none">' + esc(t('ex.noSessions')) + '</div>';
      } else {
        /* task-171：默认只列**真会话**；子 agent / 团队队友用**可见开关**（不静默隐藏），打开时明确标注。
           身份字段优先用会话对象自己的；context 端点还没带时，按 session_id 从 cards 补齐（同一份会话）。
           三字段全缺（旧实例）→ 如实提示，按老样子显示。 */
        var sessionParts = partitionSessions(sessions, cardsById((state.data && state.data.cards) || []));
        var showPeers = state.showSubagentSessions === true;
        if (sessionParts.identityMissing) {
          html += '<div class="exec-missing">' + esc(t('ex.noIdentityFields')) + '<code>session_mode</code> / <code>session_label</code> / ' +
            '<code>session_title</code>' + esc(t('exl.cannotTellPeersA')) + '**' + esc(t('exl.cannotTellPeersB')) + '**' + esc(t('exl.cannotTellPeersC')) + '</div>';
        } else if (sessionParts.peers.length) {
          html += '<button type="button" class="btn small" id="exec-show-subagents" aria-pressed="' + (showPeers ? 'true' : 'false') + '">' +
            esc(showPeers ? (t('ex.hidePeersA') + sessionParts.peers.length + t('ex.hidePeersB')) : peerToggleText(sessionParts)) + '</button>';
        }
        var sessionRows = visibleSessions(sessionParts, showPeers);
        if (!sessionRows.length) html += '<div class="exec-none">' + esc(t('ex.noSessions')) + '</div>';
        sessionRows.forEach(function (s) {
          var isPeer = String(s.session_mode) === CONTINUABLE;
          var noIdentity = sessionIdentityMissing(s);
          html += '<label class="exec-choice"><input type="radio" name="exec-session-radio" value="' + esc(s.id) + '"' +
            (d.session === s.id ? ' checked' : '') + '>' +
            '<span class="exec-main"><b>' + esc(sessionParts.label(s)) + '</b>' +
            (isPeer ? '<span class="chip warn" title="' + esc(t('ex.peerTitle')) + '">' + esc(t('ex.peerLabel')) + '</span>' : '') +
            (noIdentity ? '<span class="chip dashed" title="' + esc(t('ex.noIdentityTitle')) + '">' + esc(t('ex.noIdentityChip')) + '</span>' : '') +
            '<span class="exec-meta">' + esc(s.summary || t('ex.noSummary')) +
            esc(t('ex.fullIdPrefix')) + '<code>' + esc(s.id) + '</code>' +
            esc(t('ex.instanceMeta')) + esc(s.instance || '—') +
            esc(t('ex.obsPrefix')) + esc(s.observation || '—') + esc(t('ex.obsTail')) + '</span></span></label>';
        });
      }
      html += '<div class="notice"><b>' + esc(t('exl.manualPathA')) + '</b>' + esc(t('exl.manualPathB')) +
        esc(t('exl.manualPathC')) + '</div>' +
        '<input type="hidden" id="exec-session" value="' + esc(d.session || '') + '">';
    } else if (state.execStep === 5) {
      html += '<p class="hint">' + esc(t('exl.step5A')) + '<b>' + esc(t('exl.step5B')) + '</b>' + esc(t('exl.step5C')) + '</p>' +
        '<label class="field"><span>' + esc(t('ex.noteLabel')) + '</span><textarea id="exec-note" rows="4" placeholder="' + esc(t('ex.notePlaceholder')) + '">' +
        esc(d.note || '') + '</textarea></label>';
    } else {
      var cfgValue = (state.execData.config && state.execData.config.value) || null;
      html += '<p class="hint">' + esc(t('exl.step6A')) + '<b>' + esc(t('exl.step6B')) + '</b>' + esc(t('exl.step6C')) + '</p>' +
        '<div class="exec-preview"><div class="kv">' +
        '<b>' + esc(t('ex.kvTask')) + '</b><span>' + esc(state.execTask.title) + esc(t('ex.revPrefix')) + esc(String(state.execTask.revision)) + esc(t('ex.parenClose')) + '</span>' +
        '<b>' + esc(t('ex.kvProject')) + '</b><span>' + (d.project ? esc(d.project) : '<span class="chip dashed">' + esc(t('ex.notChosenChip')) + '</span>') + esc(t('ex.parenOpen')) + ':PM_EXEC_PROJECT:' + esc(t('ex.parenClose')) + '</span>' +
        '<b>' + esc(t('ex.kvWorkspace')) + '</b><span>' + (d.workspace ? esc(d.workspace) : '<span class="chip dashed">' + esc(t('ex.notChosenChip')) + '</span>') + esc(t('ex.parenOpen')) + ':PM_EXEC_WORKSPACE:' + esc(t('ex.parenClose')) + '</span>' +
        '<b>' + esc(t('ex.kvInstance')) + '</b><span>' + (d.instance ? esc(d.instance) : '—') + esc(t('ex.parenOpen')) + ':PM_EXEC_INSTANCE:' + esc(t('ex.parenClose')) + '</span>' +
        '<b>' + esc(t('ex.kvSession')) + '</b><span>' + (d.session ? esc(d.session) : '<span class="chip dashed">' + esc(t('ex.notChosenChip')) + '</span>') + esc(t('ex.parenOpen')) + ':PM_EXEC_SESSION:' + esc(t('ex.parenClose')) + '</span>' +
        '<b>' + esc(t('ex.kvMemory')) + '</b><span>' + ((d.memoryRefs || []).length ? esc(d.memoryRefs.join(' | ')) : '—') + esc(t('ex.parenOpen')) + ':PM_EXEC_MEMORY:' + esc(t('ex.parenClose')) + '</span>' +
        '<b>' + esc(t('ex.kvNote')) + '</b><span>' + (d.note ? esc(d.note) : '—') + esc(t('ex.parenOpen')) + ':PM_EXEC_NOTE:' + esc(t('ex.parenClose')) + '</span>' +
        '<b>dispatchStatus</b><span>' + esc(cfgValue ? dispatchStatusText(cfgValue.dispatchStatus) : t('ex.dashPending')) + '</span>' +
        '<b>setAt / setBy</b><span>' + (cfgValue ? (esc(cfgValue.setAt || '—') + ' · ' + esc(cfgValue.setBy || '—')) : '—') + '</span>' +
        '</div></div>' +
        '<div class="notice"><b>' + esc(t('exl.noDispatchA')) + '</b>' + esc(t('exl.noDispatchB')) +
        esc(t('exl.noDispatchC')) + '</div>';
      if (!caps.saveConfig) html += '<div class="exec-missing">' + esc(missingEndpointText('POST', '/ui-pm/tasks/:id/execution-config')) + '</div>';
      if (!caps.handoff) html += '<div class="exec-missing">' + esc(missingEndpointText('GET', '/ui-pm/tasks/:id/handoff')) + '</div>';
      if (state.execData.handoff && state.execData.handoff.text) {
        html += '<label class="field"><span>' + esc(t('ex.handoffLabel')) + '</span>' +
          '<textarea id="exec-handoff" rows="7" readonly>' + esc(state.execData.handoff.text) + '</textarea></label>';
      } else if (caps.handoff && state.execData.handoff && state.execData.handoff.error) {
        html += '<div class="exec-missing">' + esc(t('ex.handoffLoadFailed')) + esc(state.execData.handoff.error) + '</div>';
      }
      html += '<div class="op-row">' +
        (caps.link ? '<button class="btn small" type="button" id="exec-link">' + esc(t('ex.linkSession')) + '</button>' : notYet(t('ex.linkOnly'), missingEndpointText('POST', '/ui-pm/tasks/:id/link-session'))) +
        (caps.unlink ? '<button class="btn small" type="button" id="exec-unlink">' + esc(t('ex.unlinkSession')) + '</button>' : notYet(t('ex.unlinkOnly'), missingEndpointText('POST', '/ui-pm/tasks/:id/unlink-session'))) +
        '</div>';
    }
    html += writeResultHtml();
    body.innerHTML = html;

    if (status) status.textContent = '';
    if (prev) prev.hidden = state.execStep <= 1;
    if (next) next.hidden = state.execStep >= 6;
    if (save) save.hidden = state.execStep < 6;
    if (copy) {
      copy.hidden = state.execStep < 6;
      copy.disabled = !(state.execData.handoff && state.execData.handoff.text);
      copy.title = copy.disabled ? t('ex.copyDisabledTitle') : t('ex.copyTitle');
    }
    if (discard) discard.hidden = !state.execDraftRestored;
    wireExecStep();
  }

  function wireExecStep() {
    var body = document.getElementById('exec-body');
    if (!body || !body.querySelectorAll) return;
    body.querySelectorAll('[name="exec-workspace-radio"]').forEach(function (node) {
      node.addEventListener('change', function () {
        state.execDraft.workspace = node.value;
        state.execData.workspaceContext = null;
        state.execData.handoff = null;
        saveExecDraft();
        fetchExecDataForStep().then(renderExec);
      });
    });
    var peerToggle = body.querySelector('#exec-show-subagents');
    if (peerToggle) {
      peerToggle.addEventListener('click', function () {
        state.showSubagentSessions = !(state.showSubagentSessions === true);
        renderExec();
      });
    }
    body.querySelectorAll('[name="exec-session-radio"]').forEach(function (node) {
      node.addEventListener('change', function () {
        state.execDraft.session = node.value;
        var hidden = document.getElementById('exec-session');
        if (hidden) hidden.value = node.value;
        saveExecDraft();
      });
    });
    var link = document.getElementById('exec-link');
    if (link) link.addEventListener('click', function () { openLinkSession(); });
    var unlink = document.getElementById('exec-unlink');
    if (unlink) unlink.addEventListener('click', function () { openUnlinkSession(); });
  }

  function execNext() {
    captureExecStep();
    if (state.execStep < 6) {
      state.execStep += 1;
      saveExecDraft();
      fetchExecDataForStep().then(renderExec);
      return;
    }
  }

  function execPrev() {
    captureExecStep();
    if (state.execStep > 1) {
      state.execStep -= 1;
      saveExecDraft();
      renderExec();
    }
  }

  function saveExecutionConfig() {
    captureExecStep();
    var d = state.execDraft;
    var status = document.getElementById('exec-status');
    if (!d.project) { if (status) { status.className = 'dialog-status err'; status.textContent = t('sx.pickProject'); } state.execStep = 1; renderExec(); return; }
    if (!d.workspace) { if (status) { status.className = 'dialog-status err'; status.textContent = t('sx.pickWorkspace'); } state.execStep = 2; renderExec(); return; }
    if (!execCaps().saveConfig) {
      if (status) { status.className = 'dialog-status err'; status.textContent = missingEndpointText('POST', '/ui-pm/tasks/:id/execution-config'); }
      return;
    }
    if (status) { status.className = 'dialog-status'; status.textContent = t('sa.saving'); }
    performWrite({
      slot: 'exec-config|' + state.execTask.id,
      path: 'tasks/' + encodeURIComponent(state.execTask.id) + '/execution-config',
      revision: state.execTask.revision,
      body: {
        project: d.project, workspace: d.workspace, instance: d.instance,
        memory: d.memoryRefs || [], session: d.session, note: d.note
      },
      label: '保存执行配置', ident: state.execTask.id,
      afterOk: function () {
        var st = document.getElementById('exec-status');
        if (st) { st.className = 'dialog-status ok'; st.textContent = t('sx.savedCreds'); }
        clearExecDraft(state.execTask.id);
        state.execDraftRestored = false;
        state.execData.config = null;
        state.execData.handoff = null;
        return Promise.all([loadExecConfig(state.execTask.id), loadExecHandoff(state.execTask.id),
          loadTaskDetail(state.execTask.project, state.execTask.id)]).then(renderExec);
      },
      afterConflict: function () {
        return Promise.all([loadTaskDetail(state.execTask.project, state.execTask.id), loadExecConfig(state.execTask.id)]).then(renderExec);
      }
    }).then(function () {
      var st = document.getElementById('exec-status');
      if (!st) return;
      if (state.writeError) { st.className = 'dialog-status err'; st.textContent = (errText(state.writeError.code) || state.writeError.code) + t('task.errorSep') + state.writeError.message; }
      else if (state.conflict) { st.className = 'dialog-status err'; st.textContent = t('sa.conflict'); }
    });
  }

  function openLinkSession() {
    var d = state.execDraft;
    if (!d.session) {
      var st = document.getElementById('exec-status');
      if (st) { st.className = 'dialog-status err'; st.textContent = t('sx.pickSessionStep4'); }
      return;
    }
    openConfirmDialog({
      title: '只绑定会话（link-session）？',
      note: '只把会话关联到任务，不改状态、也不派发。',
      body: '<div class="kv"><b>' + esc(t('ols.task')) + '</b><span>' + esc(state.execTask.id) + '</span>' +
        '<b>' + esc(t('ols.session')) + '</b><span>' + esc(d.session) + '</span>' +
        '<b>' + esc(t('ols.instance')) + '</b><span>' + esc(d.instance || esc(t('ols.instanceNote'))) + '</span></div>',
      okLabel: '确认绑定',
      onOk: function () {
        performWrite({
          slot: 'link-session|' + state.execTask.id + '|' + d.session,
          path: 'tasks/' + encodeURIComponent(state.execTask.id) + '/link-session',
          revision: state.execTask.revision,
          body: { session: d.session, instance: d.instance },
          label: '绑定会话', ident: state.execTask.id,
          afterOk: function () { return Promise.all([loadExecConfig(state.execTask.id), loadExecHandoff(state.execTask.id)]); }
        });
      }
    });
  }

  function openUnlinkSession() {
    openConfirmDialog({
      title: '解除会话关联（unlink-session）？',
      note: '只解除关联，不改任务状态；必须写原因。',
      body: reasonField('原因', '例如：会话选错了 / 换到另一个工作区', true),
      okLabel: '确认解除',
      onOk: function () {
        var el2 = document.getElementById('confirm-reason');
        var reason = el2 ? el2.value.trim() : '';
        if (!reason) {
          var st = document.getElementById('confirm-status');
          st.className = 'dialog-status err';
          st.textContent = t('sx.reasonRequired');
          document.getElementById('confirm-dialog').showModal();
          return;
        }
        performWrite({
          slot: 'unlink-session|' + state.execTask.id,
          path: 'tasks/' + encodeURIComponent(state.execTask.id) + '/unlink-session',
          revision: state.execTask.revision,
          body: { reason: reason },
          label: '解除会话', ident: state.execTask.id,
          afterOk: function () { return Promise.all([loadExecConfig(state.execTask.id), loadExecHandoff(state.execTask.id)]); }
        });
      }
    });
  }

  function loadProposals() {
    if (!capsReady()) {
      state.proposals = { items: [], error: unavailableReason('GET', '/ui-pm/proposals') };
      return Promise.resolve();
    }
    return httpJson(api('proposals', { status: 'PENDING' })).then(function (x) {
      if (x.ok && x.body.ok === true) {
        state.proposals = { items: (x.body.data || {}).proposals || [], error: null };
      } else {
        state.proposals = { items: [], error: apiError(x).message };
      }
    }).catch(function (err) {
      state.proposals = { items: [], error: err.message || String(err) };
    });
  }

  function loadProposalDetail(id) {
    if (!capsReady()) {
      state.proposalDetail = { id: id, error: unavailableReason('GET', '/ui-pm/proposals/:id') };
      return Promise.resolve();
    }
    return httpJson(api('proposals/' + encodeURIComponent(id))).then(function (x) {
      if (x.ok && x.body.ok === true && (x.body.data || {}).proposal) {
        state.proposalDetail = { id: id, proposal: x.body.data.proposal, error: null };
      } else {
        state.proposalDetail = { id: id, error: apiError(x).message };
      }
    }).catch(function (err) {
      state.proposalDetail = { id: id, error: err.message || String(err) };
    });
  }

  function selectProposal(id) {
    ensureDetailOpen();   /* P2：点提案卡就展开右栏（此前只"选中"，收起状态下看不到任何反应 ✗）*/
    state.proposal = id;
    state.proposalDetail = null;
    state.staleRetried = false;
    state.card = null;
    state.task = null;
    state.taskDetail = null;
    var known = (state.proposals && state.proposals.items || []).filter(function (p) { return p.id === id; })[0];
    if (known) state.proposalDetail = { id: id, proposal: known, error: null };
    loadProposalDetail(id).then(render);
    render();
  }

  function approveProposal(p, project, allowStale) {
    state.lastApproveAllowStale = allowStale === true;
    return performWrite({
      slot: 'proposal-approve|' + p.id,
      path: 'proposals/' + encodeURIComponent(p.id) + '/approve',
      revision: p.revision,
      body: { project: project, allowStale: allowStale === true ? true : undefined },
      label: '批准提案', ident: p.id,
      /* 成功后不要清掉选中：§5 凭据和「已在 <项目> 创建 N 条任务」要留在右栏，
         提案详情按 id 重拉后状态会变成 APPROVED。 */
      afterOk: function (b) {
        /* task-168①：批准后不要停在旧快照 —— 记下新任务 id、刷该项目的看板、并安排定位/高亮那张卡 */
        var data = (b && b.data) || {};
        var ids = Array.isArray(data.taskIds) ? data.taskIds : (Array.isArray(b && b.taskIds) ? b.taskIds : []);
        var project = data.project || project || p.project || '';
        state.approvedProposal = { id: p.id, project: project, taskIds: ids.map(String), at: Date.now() };
        /* 不抢右栏：批准后右栏要留给提案详情（用户要在那里看到「已创建任务 → …（TODO）」）；
           定位/高亮在切到项目页时生效（focusTask 有 TTL，过期就只当没这回事）。 */
        if (ids.length) { state.focusTask = { project: project, id: String(ids[0]), at: Date.now(), select: false }; state.boardCenter = null; }
        return Promise.all([
          loadProposals(), loadProposalDetail(p.id), load(true, true),
          project ? loadBoard(project) : Promise.resolve()
        ]);
      },
      afterConflict: function () { return Promise.all([loadProposals(), loadProposalDetail(p.id)]); }
    });
  }

  function rejectProposal(p, reason) {
    return performWrite({
      slot: 'proposal-reject|' + p.id,
      path: 'proposals/' + encodeURIComponent(p.id) + '/reject',
      revision: p.revision,
      body: { reason: reason },
      label: '拒绝提案', ident: p.id,
      afterOk: function () { return Promise.all([loadProposals(), loadProposalDetail(p.id)]); },
      afterConflict: function () { return Promise.all([loadProposals(), loadProposalDetail(p.id)]); }
    });
  }

  function loadOverview() {
    if (state.overviewLoading) return Promise.resolve();
    if (!capsReady()) {
      state.overview = { error: unavailableReason('GET', '/ui-pm/tasks'), projects: [] };
      return Promise.resolve();
    }
    state.overviewLoading = true;
    render();
    var keys = projectOrder(state.data.projects).map(function (p) { return p.key; });
    var out = [];
    var chain = Promise.resolve();
    keys.forEach(function (key) {
      chain = chain.then(function () {
        return httpJson(api('tasks', { project: key })).then(function (x) {
          if (x.ok && x.body.ok === true) {
            var d = x.body.data || {};
            var counts = {};
            (d.groups || []).forEach(function (g) { counts[g.key] = { label: g.label, count: g.count, tasks: g.tasks || [] }; });
            out.push({ project: key, counts: counts, count: d.count || 0 });
          }
        }).catch(function () { /* 单个项目失败不阻断 */ });
      });
    });
    return chain.then(function () {
      state.overview = { projects: out, error: null };
      state.overviewLoading = false;
    });
  }

  /* task-234：新建项目的结果提示（创建/已存在）。两个视图都渲染 —— 创建成功后 app 常把视图切到
     viewProjectDetail（state.project 非空），提示必须在那里也能看到（实测：只放 viewProjects 会看不到）。 */
  function newProjectNoteHtml() {
    if (!state.newProjectNote || !state.newProjectNote.text) return '';
    return '<p class="mem-note" id="new-project-note">' + esc(state.newProjectNote.text) + '</p>';
  }

  function viewProjects() {
    if (state.project) return viewProjectDetail(state.project);
    /* task-234：Projects 页的「＋ 新建项目」入口。
       · 端点未列在 capabilities ⇒ 入口**禁用 + 原因**（notYet，不隐藏、不假装可用）；
       · 点了走 openCreateProjectDialog() —— 内部**复用 createProject()**（不新写请求）。 */
    var canCreateProject = endpointListed('POST', '/ui-pm/projects');
    var newProjectEntry = canCreateProject
      ? '<button type="button" class="btn small" data-new-project="1">' + esc(t('proj.newProject')) + '</button>'
      : notYet(t('proj.newProject'), missingEndpointText('POST', '/ui-pm/projects'));
    var noteHtml = newProjectNoteHtml();
    var html = '<div class="section-title"><div><h2>' + esc(t('proj.heading')) + '</h2>' +
      '<p class="subtle">' + esc(format(t('proj.subtitle'), { n: state.data.projects.length })) + '</p>' +
      '</div><span>' + newProjectEntry + '</span></div>' + noteHtml + '<div class="grid project-grid">';
    projectOrder(state.data.projects).forEach(function (p) { html += projectCardHtml(p); });
    html += '</div>';
    html += '<div class="notice">' + esc(t('proj.notice1')) +
      esc(t('proj.notice2')) + '</div>';
    return html;
  }

  function tabButtons() {
    var tabs = [
      ['tasks', t('tab.tasks')], ['cards', t('tab.cards')], ['timeline', t('tab.timeline')], ['memory', t('tab.memory')]
    ];
    var html = '<div class="tabs" role="tablist" aria-label="' + esc(t('tab.viewAria')) + '">';
    /* 注意：回调参数不能叫 t —— 那会**遮住** i18n 的 t()，把 tab 对象当函数调用（真实回归：3081 项目页渲染崩）。 */
    tabs.forEach(function (tab) {
      var sel = state.tab === tab[0];
      var missing = tab[0] === 'timeline';
      html += '<button type="button" role="tab" data-tab="' + tab[0] + '" aria-selected="' + sel + '">' +
        esc(tab[1]) + (missing ? ' <span class="chip dashed">' + esc(t('common.notWired')) + '</span>' : '') + '</button>';
    });
    html += '</div>';
    return html;
  }

  /* task-56 起后端把看板收成 5 组：todo(INBOX/TODO/NEXT) / doing / blocked(WAITING/BLOCKED) / review / closed(DONE/CANCELLED)。
     这里按 group.key 直接归类，不再特判旧的 'done' / 'next'。 */
  function boardCounts(board) {
    var out = { total: 0, todo: 0, doing: 0, blocked: 0, review: 0, closed: 0 };
    ((board && board.groups) || []).forEach(function (g) {
      out.total += g.count || 0;
      if (typeof out[g.key] === 'number') out[g.key] = g.count || 0;
    });
    return out;
  }

  /* ---------- 任务卡展开：会话子任务（teamTasks）+ 依赖链（dagEdges） ----------
     数据只读 API 字段，**不解析 org 文件**；teamTasks 字段不存在 → 不显示展开按钮（也不显示 0）。 */

  function taskExpandedSet() {
    if (!state.taskExpanded) state.taskExpanded = {};
    return state.taskExpanded;
  }

  function loadTaskExpanded() {
    try {
      var raw = localStorage.getItem('pm-task-expanded');
      if (!raw) return {};
      var parsed = JSON.parse(raw);
      var map = {};
      if (Array.isArray(parsed)) parsed.forEach(function (id) { if (id) map[String(id)] = true; });
      else if (parsed && typeof parsed === 'object') Object.keys(parsed).forEach(function (k) { if (parsed[k]) map[k] = true; });
      return map;
    } catch (e) { return {}; }
  }

  function saveTaskExpanded() {
    try {
      var ids = Object.keys(taskExpandedSet()).filter(function (k) { return state.taskExpanded[k]; });
      localStorage.setItem('pm-task-expanded', JSON.stringify(ids));
    } catch (e) { /* 存不下不影响本次会话 */ }
  }

  function safeDomId(id) { return String(id || '').replace(/[^A-Za-z0-9_.-]/g, '_'); }

  /* 列表刻意只有 teamTaskCount/dagEdgeCount（task-69 的裁定 B）：数组在展开时懒加载一次 task show，
     按 task id + revision 缓存；失败就写「子任务读取失败」，绝不造假行。 */
  function taskExtrasOf(taskId) {
    if (!state.taskExtras) state.taskExtras = {};
    return state.taskExtras[taskId] || null;
  }

  function loadTaskExtras(taskId, project, revision, force) {
    if (!state.taskExtras) state.taskExtras = {};
    var cached = state.taskExtras[taskId];
    if (cached && !force && !cached.loading && !cached.error && cached.revision === revision) return Promise.resolve();
    if (!endpointListed('GET', '/ui-pm/tasks/:id')) {
      state.taskExtras[taskId] = { revision: revision, error: missingEndpointText('GET', '/ui-pm/tasks/:id') };
      return Promise.resolve();
    }
    state.taskExtras[taskId] = { revision: revision, loading: true };
    return httpJson(api('tasks/' + encodeURIComponent(taskId), { project: project })).then(function (x) {
      if (x.ok && x.body.ok === true) {
        var t = (x.body.data || {}).task || {};
        state.taskExtras[taskId] = { revision: revision, teamTasks: t.teamTasks || [], dagEdges: t.dagEdges || [], error: null };
      } else {
        state.taskExtras[taskId] = { revision: revision, error: apiErrText(x) };
      }
    }).catch(function (err) {
      state.taskExtras[taskId] = { revision: revision, error: err.message || String(err) };
    });
  }

  /* 会话子任务一行：id · 标题（截断 + title 全文）· 状态 chip · owner；缺字段写「未返回」，不编造 */
  function teamTaskRowHtml(s) {
    s = s || {};
    var id = s.id ? String(s.id) : '';
    var title = s.title === null || s.title === undefined ? '' : String(s.title);
    var trunc = title.length > 90 ? title.slice(0, 90) + '…' : title;
    var status = (s.status === null || s.status === undefined || s.status === '') ? '' : String(s.status);
    var owner = (s.owner === null || s.owner === undefined || s.owner === '') ? '' : String(s.owner);
    return '<div class="team-task-row" data-team-row="' + esc(id) + '"' +
      (id ? ' id="team-task-' + esc(safeDomId(id)) + '"' : '') + '>' +
      '<span class="team-task-id">' + (id ? esc(id) : esc(t('tt.idNotReturned'))) + '</span>' +
      '<span class="team-task-title"' + (title ? ' title="' + esc(title) + '"' : '') + '>' +
      (title ? esc(trunc) : '<span class="subtle">' + esc(t('tt.titleNotReturned')) + '</span>') + '</span>' +
      (status ? '<span class="chip" title="' + esc(t('tt.statusChipTitle')) + '">' + esc(status) + '</span>'
              : '<span class="chip dashed">' + esc(t('tt.statusNotReturned')) + '</span>') +
      '<span class="team-task-owner">' + (owner ? esc(owner) : esc(t('tt.ownerNotReturned'))) + '</span>' +
      ((s.line === null || s.line === undefined) ? '' : '<span class="subtle">' + esc(format(t('tt.lineN'), { n: String(s.line) })) + '</span>') +
      '</div>';
  }

  function dagNodes(svg, id) {
    if (!svg || !svg.querySelectorAll) return [];
    return Array.prototype.slice.call(svg.querySelectorAll('[data-dag-node="' + id + '"]'));
  }

  function dagHighlight(svg, id, on) {
    if (!svg || !svg.querySelectorAll) return;
    var clear = function () {
      Array.prototype.forEach.call(svg.querySelectorAll('.dag-hot'), function (n) { if (n.classList) n.classList.remove('dag-hot'); });
      if (svg.classList) svg.classList.remove('dag-focus');
    };
    clear();
    if (!on) return;
    var hot = {};
    hot[id] = 1;
    Array.prototype.forEach.call(svg.querySelectorAll('[data-dag-edge]'), function (e) {
      var pair = String(e.getAttribute('data-dag-edge') || '').split('|');
      if (pair[0] === id || pair[1] === id) {
        hot[pair[0]] = 1; hot[pair[1]] = 1;
        if (e.classList) e.classList.add('dag-hot');
      }
    });
    Object.keys(hot).forEach(function (n) {
      dagNodes(svg, n).forEach(function (g) { if (g.classList) g.classList.add('dag-hot'); });
    });
    if (svg.classList) svg.classList.add('dag-focus');
  }

  function dagScrollToTeamRow(id) {
    if (!id) return;
    var target = document.getElementById('team-task-' + safeDomId(id));
    if (!target) return;
    if (target.scrollIntoView) { try { target.scrollIntoView({ block: 'center' }); } catch (e) {} }
    if (target.classList) {
      target.classList.add('team-task-hot');
      setTimeout(function () { if (target.classList) target.classList.remove('team-task-hot'); }, 1600);
    }
  }

  function dagPulseNode(id) {
    if (!id || !document.querySelector) return;
    var node = document.querySelector('[data-dag-node="' + id + '"]');
    if (!node) return;
    var svg = node.closest ? node.closest('svg') : null;
    dagHighlight(svg, id, true);
    setTimeout(function () { dagHighlight(svg, id, false); }, 1600);
  }

  /* ---------- 拖动改状态（task-86）：pointer events 自绘，不乐观更新 ---------- */
  var DRAG_THRESHOLD = 4;
  /* 列常量（BOARD_DROP_TARGETS / BOARD_COL_LABELS / STATUS_GROUP）与落点判定
     都由 pm-kanban.js 提供（task-146 抽原语；这里不再有第二份实现）。 */

  function dragAnnounce(msg) {
    var box = document.getElementById('board-drag-status');
    if (box) box.textContent = msg;
    if (el.sync) el.sync.textContent = msg;
  }

  function dragCardTitle(cardEl) {
    var t = cardEl && cardEl.querySelector ? cardEl.querySelector('.task-title') : null;
    return t ? String(t.textContent || '') : (cardEl ? String(cardEl.getAttribute('data-drag-id') || '') : '');
  }

  function markDropColumns(fromStatus) {
    var boardEl = document.getElementById('project-board');
    if (!boardEl || !boardEl.querySelectorAll) return [];
    var cols = Array.prototype.slice.call(boardEl.querySelectorAll(KANBAN_COL_SELECTOR));
    cols.forEach(function (col) {
      var key = col.getAttribute('data-col-key');
      var decision = dropDecision(key, fromStatus, { targets: BOARD_DROP_TARGETS, allowed: allowedTargets(fromStatus), statusLabels: TASK_STATUS });
      if (col.classList) { col.classList.remove('drop-ok', 'drop-no', 'drop-hover'); }
      var reason = decision.reason;
      if (!decision.ok) { if (col.classList) col.classList.add('drop-no'); }
      else if (col.classList) { col.classList.add('drop-ok'); }
      col.setAttribute('data-drop-reason', reason);
      var hint = col.querySelector ? col.querySelector('.drop-hint') : null;
      if (hint) hint.textContent = reason ? (t('sx.notDroppablePrefix') + reason) : (t('sx.dropToPrefix') + (TASK_STATUS[decision.target] || decision.target));
    });
    return cols;
  }

  /* 命中判定在 pm-kanban.js（columnAtPoint）；这里只把它接到当前 DOM / 拖动快照上 */
  function boardColumnAt(x, y) {
    var d = state.drag;
    return columnAtPoint(x, y, {
      cachedRects: (d && d.colRects) || [],
      elementFromPoint: document.elementFromPoint ? document.elementFromPoint.bind(document) : null,
      stopAt: document.body
    });
  }

  /* ---------- 边缘自动滚动（task-86 起；task-146 起实现搬进 pm-scroll.js） ----------
     这里只做 DOM 适配：横向=看板容器（只滚它，绝不动 window），纵向=指针所在列卡片区（KANBAN_BODY_SELECTOR）。 */
  var boardScroller = createEdgeAutoScroll({
    threshold: EDGE_THRESHOLD,            /* 48：我们的实测值（SortableJS 默认 30，可换） */
    maxStep: EDGE_MAX_STEP,               /* 18 px/帧（SortableJS 约 10） */
    throttleMs: EDGE_THROTTLE_MS,         /* 默认 0（关闭）；可传 24 复现 SortableJS 的节奏 */
    hRect: function () {
      var boardEl = document.getElementById('project-board');
      return (boardEl && boardEl.getBoundingClientRect) ? boardEl.getBoundingClientRect() : null;
    },
    hEl: function () { return document.getElementById('project-board'); },
    onHScroll: function (el) { if (el && el.__syncArrows) el.__syncArrows(); },
    vTargetAt: function (x, y) { return bodyOfColumn(boardColumnAt(x, y)); },
    /* 上层兜底（bubbleScroll 思路）：指针不在任何列里时，滚页面而不是干等 */
    vFallbackRect: function () {
      var h = (typeof window !== 'undefined' && window.innerHeight) ? window.innerHeight : 0;
      var w = (typeof window !== 'undefined' && window.innerWidth) ? window.innerWidth : 0;
      return h ? { top: 0, bottom: h, height: h, left: 0, right: w, width: w } : null;
    },
    vFallbackEl: function () { return document.scrollingElement || document.documentElement || null; }
  });

  function boardEdgeScroll(ev) { boardScroller.move(ev); }

  function boardEdgeScrollStop() { boardScroller.stop(); }

  function boardDragDown(ev, cardEl) {
    if (ev.button !== undefined && ev.button !== 0) return;
    if (state.dragPending) { dragAnnounce(t('drag.pending')); return; }
    var id = cardEl.getAttribute('data-drag-id');
    if (!id) return;
    state.drag = {
      active: false, id: id, project: cardEl.getAttribute('data-drag-project') || '',
      from: cardEl.getAttribute('data-drag-status') || '',
      revision: parseInt(cardEl.getAttribute('data-drag-revision') || '', 10),
      x0: ev.clientX, y0: ev.clientY, pointerId: ev.pointerId, node: cardEl, hover: null, colRects: []
    };
    cardEl.addEventListener('pointermove', boardDragMove);
    cardEl.addEventListener('pointerup', boardDragUp);
    cardEl.addEventListener('pointercancel', boardDragCancel);
  }

  function boardDragStart(ev) {
    var d = state.drag;
    d.active = true;
    d.suppressClick = true;
    if (document.body && document.body.classList) document.body.classList.add('pm-dragging');
    if (d.node && d.node.classList) d.node.classList.add('dragging');
    if (d.node && d.node.setPointerCapture && d.pointerId !== undefined) { try { d.node.setPointerCapture(d.pointerId); } catch (e) {} }
    var boardEl = document.getElementById('project-board');
    d.colRects = (boardEl && boardEl.querySelectorAll)
      ? columnRects(Array.prototype.slice.call(boardEl.querySelectorAll(KANBAN_COL_SELECTOR)))
      : [];
    markDropColumns(d.from);
    dragAnnounce(format(t('drag.start'), { t: dragCardTitle(d.node), s: (TASK_STATUS[d.from] || d.from) }));
  }

  function boardDragMove(ev) {
    var d = state.drag;
    if (!d) return;
    if (!d.active) {
      if (Math.abs(ev.clientX - d.x0) < DRAG_THRESHOLD && Math.abs(ev.clientY - d.y0) < DRAG_THRESHOLD) return;   /* <4px 视为点击 */
      boardDragStart(ev);
    }
    if (ev.preventDefault) ev.preventDefault();
    boardEdgeScroll(ev);
    var col = boardColumnAt(ev.clientX, ev.clientY);
    var key = col ? col.getAttribute('data-col-key') : null;
    if (key !== d.hover) {
      d.hover = key;
      if (d.colRects) d.colRects.forEach(function (c) { if (c.col.classList) c.col.classList.remove('drop-hover'); });
      if (col && col.classList) col.classList.add('drop-hover');
      var hint = col && col.querySelector ? col.querySelector('.drop-hint') : null;
      if (hint) dragAnnounce(format(t('drag.hover'), { c: (col.getAttribute('data-col-label') || key), r: (col.getAttribute('data-drop-reason') || hint.textContent) }));
    }
  }

  function boardDragCleanup() {
    var d = state.drag;
    boardEdgeScrollStop();
    if (document.body && document.body.classList) document.body.classList.remove('pm-dragging');
    if (d) {
      if (d.active) state.dragSuppressClick = true;
      if (d.node) {
        if (d.node.classList) d.node.classList.remove('dragging');
        if (d.node.removeEventListener) {
          d.node.removeEventListener('pointermove', boardDragMove);
          d.node.removeEventListener('pointerup', boardDragUp);
          d.node.removeEventListener('pointercancel', boardDragCancel);
        }
        if (d.node.releasePointerCapture && d.pointerId !== undefined) { try { d.node.releasePointerCapture(d.pointerId); } catch (e) {} }
      }
      if (d.colRects) d.colRects.forEach(function (c) { if (c.col.classList) c.col.classList.remove('drop-ok', 'drop-no', 'drop-hover'); });
    }
    state.drag = null;
  }

  function boardDragCancel() { dragAnnounce(t('drag.cancelled')); boardDragCleanup(); }

  /* 结算：合法 → 写命令（不乐观更新）；需要理由/确认 → 复用既有对话框；非法 → 只提示不发请求 */
  function dragSettle(d, col) {
    var key = col.getAttribute('data-col-key');
    var label = col.getAttribute('data-col-label') || BOARD_COL_LABELS[key] || key;
    var to = dropTargetFor(key, d.from, { targets: BOARD_DROP_TARGETS, allowed: allowedTargets(d.from) });
    if (!to) {
      dragAnnounce(format(t('drag.notDroppable'), { l: label, r: dropReason(key, d.from, { targets: BOARD_DROP_TARGETS, allowed: allowedTargets(d.from), statusLabels: TASK_STATUS }) }));
      return { ok: false, reason: 'illegal' };
    }
    if (to === d.from || key === STATUS_GROUP[d.from]) {
      dragAnnounce(format(t('drag.sameColumn'), { l: label }));
      return { ok: false, reason: 'same-column' };
    }
    if (to === 'DONE') {
      dragAnnounce(t('drag.droppedClosed'));
      requestTransition(d.project, d.id, d.from, 'DONE', d.revision);
      return { ok: true, dialog: 'accept' };
    }
    if (to === 'BLOCKED' || to === 'WAITING' || to === 'CANCELLED') {
      dragAnnounce(t('drag.droppedBlocked'));
      requestTransition(d.project, d.id, d.from, to, d.revision);
      return { ok: true, dialog: 'reason' };
    }
    state.dragPending = { taskId: d.id, to: to };
    dragAnnounce(format(t('drag.submitting'), { id: d.id, s: (TASK_STATUS[to] || to) }));
    render();
    return taskTransition(d.project, d.id, to, d.revision, '').then(function () {
      state.dragPending = null;
      render();
      dragAnnounce(state.writeError || state.conflict
        ? (format(t('drag.submitFailed'), { code: ((state.writeError && state.writeError.code) || (state.conflict && state.conflict.code) || '') }))
        : (format(t('drag.dropped'), { s: (TASK_STATUS[to] || to) })));
    });
  }

  function boardDragUp(ev) {
    var d = state.drag;
    if (!d) return;
    var wasActive = d.active;
    var col = wasActive ? boardColumnAt(ev.clientX, ev.clientY) : null;
    if (!wasActive) { boardDragCleanup(); return; }   /* 没超过阈值：不拦截，点击照旧触发 selectTask */
    if (ev.preventDefault) ev.preventDefault();
    boardDragCleanup();
    if (!col) { dragAnnounce(t('drag.cancelledNoColumn')); return; }
    dragSettle(d, col);
  }

  function taskCardHtml(task, project, groupKey) {
    var total = task.criteriaTotal || 0;
    var done = task.criteriaDone || 0;
    var isSel = !!(state.task && state.task.id === task.id && state.task.project === project);
    /* 列表只给 teamTaskCount；数组来自懒加载的 task show（若未来列表直接给数组，则直接用，不再发请求） */
    var inlineSubs = Array.isArray(task.teamTasks) ? task.teamTasks : null;
    var count = (typeof task.teamTaskCount === 'number') ? task.teamTaskCount : null;
    var extras = taskExtrasOf(task.id);
    var loadedSubs = (extras && Array.isArray(extras.teamTasks)) ? extras.teamTasks : null;
    var subs = (inlineSubs && inlineSubs.length) ? inlineSubs : loadedSubs;
    var edges = (Array.isArray(task.dagEdges) && task.dagEdges.length) ? task.dagEdges : ((extras && Array.isArray(extras.dagEdges)) ? extras.dagEdges : []);
    /* 只有 teamTaskCount 字段缺失（且没有内联数组）才不显示按钮 —— 不写 0 */
    var canExpand = (inlineSubs && inlineSubs.length > 0) ||
      (count !== null && count > 0 && endpointListed('GET', '/ui-pm/tasks/:id'));
    var shownCount = (subs && subs.length) ? subs.length : (count || 0);
    var expanded = canExpand && taskExpandedSet()[task.id] === true;
    var extrasId = 'task-extras-' + safeDomId(task.id);
    var pending = !!(state.dragPending && state.dragPending.taskId === task.id);
    var html = '<div class="task-card' + (isSel ? ' selected' : '') + (pending ? ' is-pending' : '') + '"' +
      ' data-drag-id="' + esc(task.id) + '" data-drag-project="' + esc(project) + '"' +
      ' data-drag-status="' + esc(task.status) + '" data-drag-revision="' + esc(String(task.revision)) + '"' +
      ' aria-describedby="board-drag-help">' +
      /* 主按钮：选中/打开右栏详情（task-66）；展开按钮是它的**兄弟**，不是子元素，结构上就不可能冒泡触发选中 */
      '<button type="button" class="task-card-main" data-task-id="' + esc(task.id) + '"' +
      ' data-task-project="' + esc(project) + '" aria-current="' + (isSel ? 'true' : 'false') + '">' +
      '<span class="task-title">' + esc(task.title) + '</span>' +
      '<span class="task-row">' + statusBadge(task.status) + subStatusChip(task.status, groupKey) +
      (total
        ? '<span class="chip" title="' + esc(t('card.acceptanceProgressTitle')) + '">' + esc(format(t('card.acceptanceProgress'), { done: done, total: total })) + '</span>'
        : '<span class="chip dashed" title="' + esc(t('card.noAcceptanceTitle')) + '">' + esc(t('card.noAcceptance')) + '</span>') +
      (task.ai ? '<span class="chip dashed" title="' + esc(t('card.aiTaskTitle')) + '">AI</span>' : '') +
      '</span>' +
      '<span class="task-row subtle" style="font-size:11.5px">' + esc(task.assignee || 'unassigned') +
      esc(format(t('card.revLine'), { rev: task.revision, line: task.line })) + '</span>' +
      '</button>';
    if (canExpand) {
      /* 刷新后靠 localStorage 恢复的展开态：这里补一次懒加载（loadTaskExtras 会同步写 loading 缓存，不会重复触发） */
      if (expanded && !extras && count !== null && count > 0 && !inlineSubs) {
        loadTaskExtras(task.id, project, task.revision).then(function () { render(); });
      }
      html += '<button type="button" class="task-card-expand" id="task-expand-' + safeDomId(task.id) + '"' +
        ' data-task-expand="' + esc(task.id) + '" data-task-expand-project="' + esc(project) + '"' +
        ' data-task-expand-revision="' + esc(String(task.revision)) + '"' +
        ' aria-expanded="' + (expanded ? 'true' : 'false') + '"' +
        ' aria-controls="' + esc(extrasId) + '">' +
        esc(expanded ? t('card.collapseExtras') : format(t('card.expandExtras'), { n: shownCount })) + '</button>' +
        '<div class="task-extras" id="' + esc(extrasId) + '"' + (expanded ? '' : ' hidden') + '>' +
        (extras && extras.loading
          ? '<p class="hint">' + esc(t('card.loadingExtras')) + '</p>'
          : (extras && extras.error
            ? '<p class="hint">' + esc(t('card.extrasFailed')) + esc(extras.error) + '</p>'
            : (subs && subs.length
              ? '<div class="task-extras-title">' + esc(format(t('card.extrasTitle'), { n: subs.length })) + '</div>' + subs.map(teamTaskRowHtml).join('') +
                (edges.length ? dagSvgHtml(edges, subs) : '')
              : '<p class="hint">' + esc(format(t('card.noExtras'), { n: esc(String(count === null ? t('card.countNotReturned') : count)) })) + '</p>'))) +
        '</div>';
    }
    if (pending) html += '<div class="task-pending" role="status">' + esc(t('card.submitting')) + '</div>';
    html += '</div>';
    return html;
  }

  function taskBoardPanel(project, board, counts) {
    if (!capsReady()) {
      return unbacked(t('board.notWiredTitle'), [
        t('board.needEndpoint'),
        t('board.currentState') + unavailableReason('GET', '/ui-pm/tasks'),
        t('board.autoRealBoard')
      ]);
    }
    if (!board) return '<div class="panel"><div class="empty">' + esc(t('board.loading')) + '</div></div>';
    if (board.error) {
      return '<div class="panel"><div class="panel-head"><h2>' + esc(t('board.heading')) + '</h2></div>' +
        '<div class="panel-body"><div class="empty">' + esc(t('board.loadFailed')) + esc(board.error) + '</div>' +
        '<div style="text-align:center;margin-bottom:12px">' +
        '<button class="btn small" type="button" data-reload-tasks="' + esc(project) + '">' + esc(t('board.retry')) + '</button></div></div></div>';
    }
    var html = '<section class="panel"><div class="panel-head"><div><h2>' + esc(t('board.heading')) + '</h2>' +
      '<p class="subtle">' + esc(t('board.subtitle')) + '</p></div>' +
      '<div style="display:flex;gap:6px;align-items:center">' +
      '<span class="subtle" style="font-size:12px">' + esc(format(t('board.taskCount'), { n: counts.total })) + '</span>' +
      '<span class="chip" title="' + esc(t('proj.countScopeTitle')) + '">' + esc(format(t('proj.countScope'), { key: project })) + '</span>' +
      (endpointListed('POST', '/ui-pm/tasks')
        ? '<button class="btn small primary" type="button" data-new-task="' + esc(project) + '">' + esc(t('board.newTask')) + '</button>'
        : notYet(t('board.newTask'), unavailableReason('POST', '/ui-pm/tasks') || t('board.endpointNotReady'))) +
      '</div></div><div class="panel-body">';
    if (!counts.total) {
      html += '<div class="empty">' + esc(t('board.emptyProject')) +
        (endpointListed('POST', '/ui-pm/tasks') ? esc(t('board.emptyHint')) : '') + '</div>';
    } else {
      html += '<div class="board-tools">' +
        '<button type="button" class="btn small" id="board-prev" aria-label="' + esc(t('board.scrollLeftAria')) + '">←</button>' +
        '<button type="button" class="btn small" id="board-next" aria-label="' + esc(t('board.scrollRightAria')) + '">→</button>' +
        '<span class="subtle" style="font-size:11.5px">' + esc(t('board.toolsHintA')) +
        esc(t('board.toolsHintB')) + '<b>' + esc(t('board.toolsHintC')) + '</b>' + esc(t('board.toolsHintD')) +
        esc(t('board.toolsHintE')) + '</span>' +
        '<span id="board-drag-status" class="sr-only" role="status" aria-live="polite"></span>' +
        '<span id="board-drag-help" class="sr-only">' + esc(t('board.dragHelp')) + '</span>' +
        '</div>' +
        '<div class="board" id="project-board" tabindex="0" role="region" aria-label="' + esc(t('board.regionAria')) + '">';
      (board.groups || []).forEach(function (g) {
        var tasks = g.tasks || [];
        html += '<section class="' + KANBAN_COL_CLASS + '" data-col-key="' + esc(g.key) + '" data-col-label="' + esc(g.label) + '"' +
          ' aria-label="' + esc(format(t('board.colAria'), { label: g.label, n: g.count })) + '">' +
          '<h3 class="kanban-head" title="' + esc(boardColumnTitle(g)) + '">' + esc(g.label) + ' · ' + g.count + '</h3>' +
          '<span class="drop-hint" aria-hidden="true"></span>' +
          '<div class="' + KANBAN_BODY_CLASS + '">';
        if (!tasks.length) {
          html += '<div class="kanban-empty">—</div>';
        } else if (g.key === 'closed') {
          /* 终态列默认折叠成一行摘要（点开看全部） */
          /* task-209：展开态进 state.folds（键=列+项目），渲染回填 open —— 点卡片/任何重渲染都不会再收起 */
          html += foldDetailsHtml(folds(), foldKey('kanban', g.key, project),
            format(t('board.foldClosed'), { n: tasks.length }),
            tasks.map(function (task) { return taskCardHtml(task, project, g.key); }).join(''), { cls: 'kanban-fold' });
        } else {
          tasks.forEach(function (task) { html += taskCardHtml(task, project, g.key); });
        }
        html += '</div></section>';
      });
      html += '</div>';
    }
    html += '<div class="notice">' + esc(t('board.footerA')) +
      esc(t('board.footerB')) +
      esc(t('board.footerC')) +
      esc(t('board.footerD')) + '<b>' + esc(t('board.footerE')) + '</b>' + esc(t('board.footerF')) +
      esc(t('board.footerG')) + '</div>';
    html += '</div></section>';
    return html;
  }

  function projectMemoryPanel(project) {
    var pm = state.projectMemory;
    if (!capsReady()) return unbacked(t('mem.notWiredTitle'), [t('mem.needEndpoint'), unavailableReason('GET', '/ui-pm/memory')]);
    if (!pm) return '<div class="panel"><div class="empty">' + esc(t('mem.loading')) + '</div></div>';
    if (pm.error) return '<div class="panel"><div class="panel-body"><div class="empty">' + esc(t('board.loadFailed')) + esc(pm.error) + '</div></div></div>';
    var html = '<section class="panel"><div class="panel-head"><div><h2>' + esc(t('mem.heading')) + '</h2>' +
      '<p class="subtle">' + esc(format(t('mem.subtitle'), { s: project })) + '</p></div>' +
      '<button class="btn small" type="button" data-goto="memory">' + esc(t('mem.gotoMemory')) + '</button></div><div class="panel-body">';
    if (!pm.entries.length) html += '<div class="empty">' + esc(t('mem.empty')) + '</div>';
    pm.entries.forEach(function (e) { html += memoryRowHtml(e, 'verified', pm.entries.map(function (x) { return String(x.id); })); });
    html += '</div></section>';
    return html;
  }

  /* ================= 项目简报（只读投影，task-52/53） ================= */

  function loadProjectBrief(key) {
    if (!endpointListed('GET', '/ui-pm/projects/:key/brief')) {
      state.projectBrief = { key: key, data: null, error: missingEndpointText('GET', '/ui-pm/projects/:key/brief') };
      return Promise.resolve();
    }
    return httpJson(api('projects/' + encodeURIComponent(key) + '/brief')).then(function (x) {
      if (x.ok && x.body.ok === true) state.projectBrief = { key: key, data: x.body.data || {}, error: null };
      else {
        var e = apiError(x);
        state.projectBrief = { key: key, data: null, error: e.code + '：' + e.message, errorBody: x.body };
      }
    }).catch(function (err) {
      state.projectBrief = { key: key, data: null, error: err.message || String(err) };
    });
  }

  function briefText(text) {
    /* 局部变量不能叫 t（i18n 保留名）：否则下面 t('common.notEstablished') 会撞上它 ——
       实测报 "TypeError: t is not a function"，只有真机才炸 ✗（shadow-scan 工具能事前抓到 ✓）。 */
    var raw = String(text === null || text === undefined ? '' : text);
    if (!raw.trim()) return '<p class="subtle">' + esc(t('common.notEstablished')) + '</p>';
    return '<div class="brief-text">' + esc(raw).replace(/\n/g, '<br>') + '</div>';
  }

  function briefAcceptance(items, notes) {
    var list = items || [];
    var extra = notes || [];
    if (!list.length && !extra.length) return '<p class="subtle">' + esc(t('common.notEstablished')) + '</p>';
    var html = '';
    list.forEach(function (it) {
      html += '<div class="check-row ' + (it.done ? 'pass' : 'pending') + '">' +
        '<i aria-hidden="true">' + (it.done ? '✓' : '·') + '</i>' +
        '<span>' + esc(it.text) + '</span>' +
        '<span class="chip subtle">' + esc(it.done ? t('brief.checked') : t('brief.unchecked')) + '</span></div>';
    });
    extra.forEach(function (n) { html += '<p class="hint">' + esc(t('brief.noCheckbox')) + esc(n) + '</p>'; });
    return html;
  }

  /* task-C5S1X：只接受六段白名单里的 section，其余回落 goal（避免拼出非法段名）。 */
  function briefSectionKnown(section) {
    var ok = false;
    BRIEF_SECTION_OPTIONS.forEach(function (o) { if (o[0] === section) ok = true; });
    return ok;
  }

  function briefBlock(section, label, inner, editHtml) {
    return '<div class="brief-block"><div class="subtle" style="font-size:12px;display:flex;align-items:center;gap:8px;justify-content:space-between">' +
      '<span>' + esc(label) + '</span><span>' + (editHtml || '') + '</span></div>' +
      '<div class="brief-body">' + inner + '</div></div>';
  }

  function briefMissingBlock(label, why) {
    return '<div class="brief-block"><div class="subtle" style="font-size:12px">' + esc(label) + '</div>' +
      '<div class="brief-body"><span class="chip dashed" title="' + esc(why) + '">' + esc(t('common.notWired')) + '</span>' +
      '<div class="subtle" style="font-size:11.5px;margin-top:4px">' + esc(why) + '</div></div></div>';
  }

  /* getter 表（lesson A：模块级常量不能直接 t()）—— API 形状不变：仍是 [[key, label], ...] */
    var BRIEF_LABELS = [['goal', t('brief.labelGoal')], ['milestones', t('brief.labelMilestones')], ['risks', t('brief.labelRisks')], ['acceptance', t('brief.labelAcceptance')]];

  /* ---------- 编辑项目简报（POST /ui-pm/projects/:key/brief，task-54/70/71） ----------
     该路由用整文件 sha256 digest 做 CAS，字段白名单是 {section,text,expectedDigest,actor}：
     不发 idempotencyKey / expectedRevision；text 允许为空（空=清空该段）。 */
  var BRIEF_SECTION_OPTIONS = [
    ['goal', t('brief.secGoal')], ['scope', t('brief.secScope')], ['nonGoal', t('brief.secNonGoal')],
    ['acceptance', t('brief.secAcceptance')], ['milestones', t('brief.secMilestones')], ['risks', t('brief.secRisks')]
  ];

  function briefSectionLabel(section) {
    var hit = BRIEF_SECTION_OPTIONS.filter(function (o) { return o[0] === section; })[0];
    return hit ? hit[1] : section;
  }

  function briefSectionText(b, section) {
    if (!b) return '';
    if (section === 'acceptance') {
      var lines = (b.acceptance || []).map(function (it) { return (it.done ? '- [x] ' : '- [ ] ') + String(it.text || ''); });
      (b.acceptanceNotes || []).forEach(function (n) { lines.push(String(n)); });
      return lines.join('\n');
    }
    return String(b[section] || '');
  }

  function acceptanceFormatCheck(text) {
    var lines = String(text || '').split('\n').filter(function (l) { return l.trim().length > 0; });
    var bad = lines.filter(function (l) { return !/^-\s*\[[ xX]\]\s*/.test(l.trim()); });
    return { total: lines.length, bad: bad.length };
  }

  function openBriefEditor(key, section) {
    var d = (state.projectBrief && state.projectBrief.data) || null;
    var b = d && d.brief;
    if (!b) { el.sync.textContent = t('brief.editNoData'); return; }
    var digest = d.digest ? String(d.digest) : '';
    if (!digest) {
      el.sync.textContent = t('brief.editNoOrg');
      return;
    }
    state.briefEdit = {
      key: key, section: briefSectionKnown(section) ? section : 'goal', digest: digest, drafts: {},
      srcPath: (d.path ? String(d.path) : ('projects/proj-' + key)) + '/project.org',
      b: b
    };
    renderBriefEditor();
  }

  function syncBriefFormatHint() {
    var e = state.briefEdit;
    var hint = document.getElementById('brief-edit-format');
    if (!e || !hint) return;
    var ta = document.getElementById('brief-edit-text');
    var text = ta ? ta.value : '';
    if (e.section !== 'acceptance') {
      hint.textContent = t('brief.hintPlain');
      return;
    }
    var c = acceptanceFormatCheck(text);
    hint.textContent = c.total === 0
      ? t('brief.hintAcceptanceEmpty')
      : (c.bad === 0 ? format(t('brief.hintFormatOk'), { n: c.total })
        : format(t('brief.hintFormatBad'), { bad: c.bad, total: c.total }));
  }

  function renderBriefEditor() {
    var e = state.briefEdit;
    var cur = (e.drafts[e.section] !== undefined) ? e.drafts[e.section] : briefSectionText(e.b, e.section);
    var body = '<p class="hint">' + esc(t('brief.targetFile')) + '<code>' + esc(e.srcPath) + '</code>' + esc(t('brief.writeHow1')) + '<b>' + esc(t('brief.wholeFileCas')) + '</b>' +
      esc(format(t('brief.writeHow2'), { d: String(e.digest).slice(0, 12) })) + '<code>:LOGBOOK:</code>' + esc(t('brief.writeHow3')) + '</p>' +
      '<label class="field"><span>' + esc(t('brief.editFieldSection')) + '</span><select id="brief-edit-section">' +
      BRIEF_SECTION_OPTIONS.map(function (o) {
        return '<option value="' + o[0] + '"' + (o[0] === e.section ? ' selected' : '') + '>' + esc(o[1]) + '</option>';
      }).join('') + '</select></label>' +
      '<label class="field"><span>' + esc(t('brief.editFieldBody')) + '</span>' +
      '<textarea id="brief-edit-text" rows="9">' + esc(cur) + '</textarea></label>' +
      '<p class="hint" id="brief-edit-format"></p>';
    openConfirmDialog({
      title: t('brief.editorTitle'),
      note: t('brief.editorNote'),
      body: body,
      okLabel: t('brief.editorOk'),
      onOk: function () {
        var ta = document.getElementById('brief-edit-text');
        e.drafts[e.section] = ta ? ta.value : '';
        e.text = e.drafts[e.section];
        openBriefPreview();
      }
    });
    syncBriefFormatHint();
  }

  function openBriefPreview() {
    var e = state.briefEdit;
    var oldText = briefSectionText(e.b, e.section);
    var newText = e.text === undefined ? oldText : e.text;
    var oldLines = oldText.length ? oldText.split('\n') : [t('brief.emptyParen')];
    var newLines = newText.length ? newText.split('\n') : [t('brief.emptyParen')];
    var oldSet = {}, newSet = {};
    oldLines.forEach(function (l) { oldSet[l] = true; });
    newLines.forEach(function (l) { newSet[l] = true; });
    var column = function (lines, other) {
      return lines.map(function (l) {
        var same = !!other[l];
        return '<div class="diff-line' + (same ? '' : ' diff-changed') + '">' + (same ? '\u00a0\u00a0' : '\u00b1\u00a0') + esc(l) + '</div>';
      }).join('');
    };
    var body = '<div class="grid" style="grid-template-columns:1fr 1fr;gap:10px">' +
      '<div><p class="subtitle">' + esc(format(t('brief.diffOld'), { s: briefSectionLabel(e.section) })) + '</p>' + column(oldLines, newSet) + '</div>' +
      '<div><p class="subtitle">' + esc(format(t('brief.diffNew'), { s: briefSectionLabel(e.section) })) + '</p>' + column(newLines, oldSet) + '</div></div>' +
      '<p class="hint">' + esc(t('brief.diffHint')) + '<b>±</b>' + esc(t('brief.diffHint2')) + '</p>' +
      '<div class="notice">' + esc(t('brief.saveWill1')) + '<code>' + esc(e.srcPath) + '</code>' + esc(t('brief.saveWill2')) + '<b>' + esc(briefSectionLabel(e.section)) +
      '</b>' + esc(t('brief.saveWill3')) + '<code>:LOGBOOK:</code>' + esc(t('brief.saveWill4')) +
      esc(t('brief.saveWill5')) + '</div>';
    openConfirmDialog({
      title: t('brief.previewTitle'),
      note: t('brief.previewNote'),
      body: body,
      okLabel: t('brief.previewOk'),
      onOk: function () { saveBriefSection(); }
    });
  }

  function saveBriefSection() {
    var e = state.briefEdit;
    if (!e) return Promise.resolve();
    return performWrite({
      slot: 'brief-set|' + e.key + '|' + e.section,
      path: 'projects/' + encodeURIComponent(e.key) + '/brief',
      omitEnvelope: true,
      keepEmpty: true,
      body: { section: e.section, text: e.text === undefined ? '' : e.text, expectedDigest: e.digest, actor: 'human' },
      label: format(t('brief.saveLabel'), { s: briefSectionLabel(e.section) }), ident: e.key,
      afterOk: function () { return loadProjectBrief(e.key); },
      afterConflict: function () { return loadProjectBrief(e.key); }
    });
  }

  /* 四栏 + 范围/非目标（可折叠）：只读，不提供编辑入口 */
  function projectBriefPanels(key) {
    var endpoint = 'GET /ui-pm/projects/:key/brief';
    if (!endpointListed('GET', '/ui-pm/projects/:key/brief')) {
      var why = format(t('brief.endpointMissing'), { ep: endpoint });
      return '<div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(240px,1fr))">' +
        BRIEF_LABELS.map(function (l) { return briefMissingBlock(l[1], why); }).join('') +
        '</div>' +
        '<div class="notice">' + esc(t('brief.notWiredNotice')) +
        esc(t('brief.verifyHintA')) + '<code>GET /ui-pm/capabilities</code>' + esc(t('brief.verifyHintB')) + '<code>' + esc(endpoint) + '</code>' + esc(t('brief.verifyHintC')) + '</div>';
    }
    var pb = state.projectBrief;
    if (!pb || pb.key !== key) return '<div class="empty">' + esc(t('brief.loading')) + '</div>';
    if (pb.error) {
      var hint = (pb.errorBody && (pb.errorBody.hint || (pb.errorBody.error || {}).hint)) || '';
      return '<div class="empty">' + esc(t('brief.loadFailed')) + esc(pb.error) +
        (hint ? '<br><span class="subtle">' + esc(hint) + '</span>' : '') + '</div>';
    }
    var d = pb.data || {};
    if (d.brief === null || d.brief === undefined) {
      var reason = d.reason || t('brief.reasonNotReturned');
      var title = (reason === 'NO_PROJECT_ORG')
        ? t('brief.noOrg')
        : (format(t('brief.noData'), { r: String(reason) }));
      return '<div class="brief-empty"><div class="empty">' + esc(title) +
        (d.message ? '<br><span class="subtle">' + esc(d.message) + '</span>' : '') +
        '<br><span class="subtle">' + esc(t('brief.manualAreaNoteA')) + '<code>pm init</code>' + esc(t('brief.manualAreaNoteB')) + '<code>pm project create</code>' + esc(t('brief.manualAreaNoteC')) +
        esc(t('brief.manualAreaNote2')) + '</span></div></div>';
    }
    var b = d.brief;
    var miss = b.missingSections || [];
    var srcPath = (d.path ? String(d.path) : ('projects/proj-' + key)) + '/project.org';
    var canEdit = endpointListed('POST', '/ui-pm/projects/:key/brief');
    var editBtn = canEdit
      ? (d.digest
        ? '<button type="button" class="btn small" data-brief-edit="' + esc(key) + '">' + esc(t('brief.editEllipsis')) + '</button>'
        : notYet(t('brief.edit'), t('brief.noDigest')))
      : notYet(t('brief.edit'), missingEndpointText('POST', '/ui-pm/projects/:key/brief'));
    /* task-225②：把「来源 <相对路径>」换成**可复制的 Emacs 指令** —— 绝对路径来自服务端
       （GET /ui-pm/projects/:key/brief 顶层 absolutePath，由后端用库根解析，前端不拼）；
       拿不到时**如实降级**（相对路径 + 「库根未解析」），绝不编造绝对路径、也不用工作区路径冒充。 */
    var abs = (typeof d.absolutePath === 'string' && d.absolutePath) ? String(d.absolutePath) : '';
    var openCmd = abs ? ('emacs "' + abs + '"') : '';
    /* task-C5S1X：每段一个「编辑这一段」入口（复用既有编辑器 + 整文件 sha256 CAS）。
       digest 缺失或 absolutePath=null 时**禁用并在 title 里说明原因**（不隐藏、不假装可用）。
       定义在这里而不是模块级：d / abs / key 都在这层作用域里（模块级会 ReferenceError）。 */
    var sectionEdit = function (section) {
      var why = !d.digest
        ? t('brief.noDigestWhole')
        : (!abs ? t('brief.rootUnresolved') : '');
      if (why) return notYet(t('brief.editSection'), why);
      return '<button type="button" class="btn small" data-brief-edit="' + esc(key) + '" data-brief-section="' + esc(section) + '"' +
        ' title="' + esc(format(t('brief.editSectionTitle'), { section: briefSectionLabel(section) })) + '">' + esc(t('brief.editSection')) + '</button>';
    };
    var srcChip = openCmd
      ? '<span class="chip" title="' + esc(t('brief.emacsChipTitle')) + '">' + esc(t('brief.emacsOpen')) + '</span>' +
        '<button type="button" class="btn small" data-copy="' + esc(openCmd) + '" ' +
        'title="' + esc(t('brief.copyCmdTitle')) + '">⧉ ' + esc(openCmd) + '</button>'
      : '<span class="chip dashed" title="' + esc(t('brief.absMissingTitle')) + '">' +
        esc(format(t('brief.relPath'), { p: srcPath })) + '</span>';
    /* task-225③：自解释文案（两态逐字）；技术细节放 tooltip */
    var sixChip = miss.length
      ? '<span class="chip subtle" title="' + esc(t('brief.missingSectionsTitle')) + '">' +
        esc(format(t('brief.missingSections'), { n: miss.length, list: miss.join('、') })) + '</span>'
      : '<span class="chip subtle" title="' + esc(t('brief.allSectionsTitle')) + '">' +
        esc(t('brief.allSections')) + '</span>';
    var html = '<div class="brief-head">' +
      '<span class="chip dashed">' + esc(t('brief.chipManualArea')) + '</span>' +
      editBtn +
      srcChip + sixChip +
      '</div>';
    html += '<div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(240px,1fr))">' +
      briefBlock('goal', t('brief.blockGoal'), briefText(b.goal), sectionEdit('goal')) +
      briefBlock('milestones', t('brief.blockMilestones'), briefText(b.milestones), sectionEdit('milestones')) +
      briefBlock('risks', t('brief.blockRisks'), briefText(b.risks), sectionEdit('risks')) +
      briefBlock('acceptance', t('brief.blockAcceptance'), briefAcceptance(b.acceptance, b.acceptanceNotes), sectionEdit('acceptance')) +
      '</div>';
    /* task-C5S1X：范围 / 非目标也各给一个入口，且按钮放在折叠**外面**（收起时也看得见）。 */
    var scopeHead = '<div class="subtle" style="font-size:12px;display:flex;align-items:center;gap:8px;justify-content:space-between">' +
      '<span>' + esc(t('brief.scopeHead')) + '</span><span>' + sectionEdit('scope') + '</span></div>';
    var nonGoalHead = '<div class="subtle" style="font-size:12px;display:flex;align-items:center;gap:8px;justify-content:space-between">' +
      '<span>' + esc(t('brief.nonGoalHead')) + '</span><span>' + sectionEdit('nonGoal') + '</span></div>';
    html += '<div class="brief-scope">' +
      '<div class="brief-block">' + scopeHead + '<details' + foldAttrs(folds(), foldKey('brief', 'scope'), true) + '><summary>' + esc(t('brief.scopeHead')) + '</summary>' + briefText(b.scope) + '</details></div>' +
      '<div class="brief-block">' + nonGoalHead + '<details' + foldAttrs(folds(), foldKey('brief', 'nongoal'), true) + '><summary>' + esc(t('brief.nonGoalHead')) + '</summary>' + briefText(b.nonGoal) + '</details></div>' +
      '</div>';
    /* 注意：这一条里本来就有 <code> 标签 ⇒ 不能整段 esc（否则标签变成字面量 ✗，实测被 zh 逐字对比抓到） */
    html += '<div class="notice">' + esc(t('brief.orderNoticeA')) + '<code>' + esc(srcPath) + '</code>' + esc(t('brief.orderNoticeB')) +
      esc(t('brief.orderNotice2')) +
      esc(t('brief.orderNotice3')) +
      esc(t('brief.orderNotice4')) + '</div>';
    return html;
  }

  /* 右栏摘要：只说事实，不重复整页 */
  function briefRightPaneHtml(key) {
    if (!endpointListed('GET', '/ui-pm/projects/:key/brief')) {
      return '<p class="hint">' + esc(missingEndpointText('GET', '/ui-pm/projects/:key/brief')) + '</p>';
    }
    var pb = state.projectBrief;
    if (!pb || pb.key !== key) return '<p class="hint">' + esc(t('brief.loading')) + '</p>';
    if (pb.error) return '<p class="hint">' + esc(t('brief.loadFailedPrefix')) + esc(pb.error) + '</p>';
    var d = pb.data || {};
    var srcPath = (d.path ? String(d.path) : ('projects/proj-' + key)) + '/project.org';
    if (d.brief === null || d.brief === undefined) {
      return '<p class="hint">' + (d.reason === 'NO_PROJECT_ORG'
        ? t('brief.noProjectOrg')
        : t('brief.noDataPrefix') + esc(String(d.reason || t('brief.notReturned'))) + t('brief.noDataSuffix')) + '</p>' +
        '<p class="hint">' + esc(t('brief.sourcePrefix')) + '<code>' + esc(srcPath) + '</code>' + esc(t('brief.readOnlySuffix')) + '</p>';
    }
    var b = d.brief;
    var goal = String(b.goal || '').trim();
    var first = goal ? goal.split('\n')[0] : '';
    var miss = b.missingSections || [];
    return '<p class="subtitle">' + esc(t('brief.goalHeading')) + '</p>' +
      (first ? '<div class="brief-text">' + esc(first) + '</div>' : '<p class="subtle">' + esc(t('brief.notEstablished')) + '</p>') +
      '<p class="subtitle">' + esc(t('brief.missingHeading')) + '</p>' +
      (miss.length ? '<p class="hint">' + esc(miss.join(t('brief.sectionSep'))) + esc(t('brief.missingNote')) + '</p>' : '<p class="hint">' + esc(t('brief.allSections')) + '</p>') +
      '<p class="hint">' + esc(t('brief.sourcePrefix')) + '<code>' + esc(srcPath) + '</code>' + esc(t('brief.sourceTail')) + '</p>';
  }

  function viewProjectDetail(key) {
    var p = projectByKey(key);
    /* task-234 回归补充（verifier task-238 的"不依赖投影"口径）：项目不在 state.data.projects 时走这个回退分支，
       提示也必须在这里出现（否则"没投影"就等于"看不到结果"）。 */
    if (!p) return newProjectNoteHtml() + '<div class="panel"><div class="empty">' + esc(format(t('proj.notFound'), { key: key })) + '</div></div>';
    var cards = state.data.cards.filter(function (c) { return c.project === key; });
    var archived = cards.filter(isArchived);
    var board = (state.board && state.board.project === key) ? state.board : null;
    var counts = boardCounts(board);

    /* task-234 回归修复（verifier2 task-238 抓到）：这里原来写成两行 ——
       `html += newProjectNoteHtml();` 紧跟着 `var html = …`。var 提升下第一行的 html 是 undefined，
       第二行又把刚拼好的字符串**整体覆盖** ⇒ 详情视图把提示丢掉（列表视图没这个问题，因为它是拼进 markup 的）。
       现在照 1783 的写法：提示直接作为 markup 的前缀。 */
    var html = newProjectNoteHtml() + '<div class="section-title"><div><h2>' + esc(p.title) + '</h2>' +
      '<p class="subtle">' + esc(t('proj.detailPrefix')) + esc(p.key) + esc(format(t('proj.lastObserved'), { time: localTime(p.last_recorded) || t('common.unknownTime') })) +
      esc(format(t('proj.sourceLine'), { rel: relTime(p.last_recorded) })) + '</p></div>' +
      '</div>';

    /* task-225①：标题做成**页面级小节标题**（复用 .section-title，17px/700），技术副标题降级进 tooltip，不再占首屏 */
    html += '<div class="section-title"><div><h2>' + esc(t('proj.briefHeading')) + '</h2>' +
      '<p class="subtle">' + esc(t('proj.manualArea')) + '</p></div>' +
      '<span class="chip" title="' + esc(t('proj.briefChipTitle')) + '">' + esc(t('proj.techDetails')) + '</span>' +
      '</div>';
    html += '<section class="panel">' +
      '<div class="panel-body" style="padding:16px 18px">' +
      projectBriefPanels(key) +
      '<div class="notice">' + esc(t('proj.pathsCopyable')) + '<br>' +
      (p.paths || []).map(function (path) {
        return '<button type="button" class="btn small" data-copy="' + esc(path) + '" style="margin:4px 6px 0 0">' +
          '⧉ ' + esc(path) + '</button>';
      }).join('') +
      '<br><span class="subtle">' + esc(t('proj.pathsNote')) + esc(p.key) + '</span></div>' +
      '</div></section>';

    var tasksKnown = capsReady() && !!board && !board.error;
    /* task-01M52595：口径标注（用户把"当前项目"的 17/34 当成全库数 ⇒ 明说范围） */
    html += '<p class="hint">' + esc(format(t('proj.countScope'), { key: p.key })) + '</p>';
    html += '<div class="metrics">' +
      (tasksKnown
        ? metric(counts.total, t('proj.metricTasks')) +
          metric(counts.todo + ' / ' + counts.doing, t('proj.metricTodoDoing')) +
          metric(counts.review, t('proj.metricReview'))
        : metric('—', t('proj.metricTasksNotWired'), true) + metric('—', t('proj.metricReviewNotWired'), true)) +
      metric(cards.length, t('tab.cards')) +
      metric(p.missing_summary, t('common.missingSummary')) +
      metric('—', t('proj.acceptanceNotEstablished'), true) +
      '</div>';

    html += tabButtons();

    if (state.tab === 'tasks') {
      html += taskBoardPanel(key, board, counts);
    } else if (state.tab === 'cards') {
      html += '<section class="panel"><div class="panel-head"><div><h2>' + esc(t('tab.cards')) + '</h2>' +
        '<p class="subtle">' + esc(t('proj.cardsNote')) + '</p></div>' +
        '<span class="subtle" style="font-size:12px">' + esc(format(t('proj.cardCount'), { n: cards.length })) +
        (archived.length ? esc(format(t('proj.archivedCount'), { n: archived.length })) : '') + '</span></div>' +
        '<div class="panel-body">';
      if (!cards.length) html += '<div class="empty">' + esc(t('proj.noCards')) + '</div>';
      var rank = function (c) { return isArchived(c) ? 2 : (c.needs_attention ? 0 : 1); };
      cards.slice().sort(function (a, b) {
        return rank(a) - rank(b) || (Date.parse(b.recorded_at) || 0) - (Date.parse(a.recorded_at) || 0);
      }).forEach(function (c) { html += rowHtml(c); });
      html += '</div></section>';
    } else if (state.tab === 'memory') {
      html += projectMemoryPanel(key);
    } else {
      html += unbacked(t('proj.timelineNotWired'), [
        t('proj.timelineNeedEvents'),
        t('proj.timelineNeedEndpoint'),
        t('proj.timelineLogbook')
      ]);
    }
    return html;
  }

  function briefField(label, value, why) {
    return '<div><div class="subtle" style="font-size:12px">' + esc(label) + '</div>' +
      '<div style="margin-top:4px;font-weight:700">' +
      (value ? esc(value) : '<span class="chip dashed" title="' + esc(why) + '">' + esc(t('common.notEstablished')) + '</span>') +
      '</div><div class="subtle" style="font-size:11.5px;margin-top:4px">' + esc(why) + '</div></div>';
  }

  function metric(value, label, unbackedMetric) {
    return '<div class="metric' + (unbackedMetric ? ' unbacked-metric' : '') + '">' +
      '<strong>' + esc(value) + '</strong><span>' + esc(label) + '</span></div>';
  }

  /* ================= 收件箱 ================= */

  /* ---------- 收件箱：数据与动作状态（P2a 起 archive / snooze 接真实端点） ---------- */

  /* 端点支持的状态过滤值（pm inbox list --status；大小写不敏感）。task-191：值来自唯一来源——
     9 个规范状态按 src/pm/inbox_ops.py:41-45 的 KNOWN_STATUSES 顺序，末尾是旧数据状态 LEGACY_UNTRACKED
     （src/pm/inbox.py:34 的 LEGACY_STATUS = 没有 :ID: 的旧 capture / 人手写的顶层列表项）。
     以前这里手写死列表，漏了 NOTE / MERGED / DISMISSED（筛不出来）——改成从模块取，防漂移测试盯着。 */
  var INBOX_STATUSES = INBOX_FILTER_STATUSES;

  function inboxUrl(status) {
    var real = (status && status !== '*') ? status : '';
    var query = real ? '?status=' + encodeURIComponent(real) : '';
    try { return new URL('../inbox', location.href).toString() + query; }
    catch (e) { return '/ui-pm/inbox' + query; }
  }

  function endpointReady() { return !!(state.inbox && state.inbox.source === 'endpoint'); }

  /* 拉 inbox：优先真实端点 GET ../inbox；端点不可用（例如宿主还是旧构建，404）时
   * 回退到 /cards 的只读 inbox —— 但此时没有 revision，动作一律禁用，不假装能写。 */
  function loadInbox() {
    return fetch(inboxUrl(state.inboxStatus), { headers: { accept: 'application/json' }, cache: 'no-store' })
      .then(function (r) {
        /* 改名（i18n 保留名规则）：回调参数不得叫 t —— 它会静默遮住从 pm-i18n.js 导入的 t()。 */
        return r.text().then(function (body) {
          var b = null;
          try { b = body ? JSON.parse(body) : null; } catch (e) { b = null; }
          if (!r.ok || !b || b.ok !== true) {
            var why = (b && b.error && (b.error.message || b.error.code)) || ('HTTP ' + r.status);
            throw new Error(why);
          }
          return b.data || {};
        });
      })
      .then(function (data) {
        state.inbox = {
          source: 'endpoint', path: data.path || 'inbox.org', count: data.count || 0,
          entries: data.entries || [], status: state.inboxStatus, error: null
        };
      })
      .catch(function (err) {
        var cardsInbox = state.data && state.data.inbox;
        var entries = (cardsInbox && cardsInbox.entries) || [];
        if (state.inboxStatus) {
          entries = entries.filter(function (e) { return String(e.status).toUpperCase() === state.inboxStatus; });
        }
        state.inbox = {
          source: 'cards', path: (cardsInbox && cardsInbox.path) || 'inbox.org',
          count: entries.length, entries: entries, status: state.inboxStatus,
          error: err.message || String(err)
        };
      })
      .then(function () { clampNote(); });
  }

  /* ---------- 收件箱单条：补充 / 修订 / 历史（契约 内部记录/09 §4） ---------- */

  function loadInboxDetail(id) {
    if (!endpointListed('GET', '/ui-pm/inbox/:id')) {
      state.inboxDetail = { id: id, data: null, error: missingEndpointText('GET', '/ui-pm/inbox/:id') };
      return Promise.resolve();
    }
    return httpJson(api('inbox/' + encodeURIComponent(id))).then(function (x) {
      if (x.ok && x.body.ok === true) state.inboxDetail = { id: id, data: x.body.data || {}, error: null };
      else state.inboxDetail = { id: id, data: null, error: apiErrText(x) };
    }).catch(function (err) {
      state.inboxDetail = { id: id, data: null, error: err.message || String(err) };
    });
  }

  function inboxRevisionFor(entry) {
    var d = state.inboxDetail;
    if (d && d.data && d.id === entry.id && typeof d.data.revision === 'number') return d.data.revision;
    return entry.revision;
  }

  /* 历史条目形状：契约只规定「headline + 补充块 + 修订块（按时间）」，
     具体键名以后端为准，这里按常见键名取值，取不到就显示「—」，绝不编造。 */
  function normalizeHistory(row, kind) {
    row = row || {};
    var at = row.at || row.time || row.createdAt || row.observedAt || row.timestamp || row.date || '';
    var revision = (row.revision !== undefined) ? row.revision : ((row.rev !== undefined) ? row.rev : null);
    return {
      kind: kind,
      at: at,
      actor: row.actor || row.by || '',
      revision: revision,
      text: row.text || row.body || row.note || '',
      reason: row.reason || '',
      oldText: row.oldText || row.old || '',
      newText: row.newText || row.new || ''
    };
  }

  function inboxHistory() {
    var d = state.inboxDetail;
    if (!d || !d.data) return [];
    var items = [];
    (d.data.annotations || []).forEach(function (a) { items.push(normalizeHistory(a, 'annotate')); });
    (d.data.revisions || []).forEach(function (r) { items.push(normalizeHistory(r, 'edit')); });
    /* 只有所有条目都有可解析时间才重排；否则保持后端给的顺序（不做猜测） */
    /* 规则不变：**所有**条目都有可比较时间才重排，否则保持后端返回顺序（不猜）。
       只是「可比较」的判定从 Date.parse 换成归一化后的文本键 —— org 时间戳
       （2026-10-12 Mon 16:12）归一化后是 YYYY-MM-DD HH:MM，可以按字典序比较。 */
    var allDated = items.length > 0 && items.every(function (h) { return localTime(h.at) !== ''; });
    if (allDated) {
      items.sort(function (a, b) {
        var ka = localTime(a.at), kb = localTime(b.at);
        return ka < kb ? 1 : (ka > kb ? -1 : 0);   /* 倒序 */
      });
    }
    return items;
  }

  function historyRowHtml(h) {
    var html = '<div class="ev" style="margin-bottom:8px">' +
      '<strong>' + (h.kind === 'edit' ? t('h.revise') : t('h.append')) + '</strong> ' +
      '<span class="chip">' + esc(h.actor || t('h.actorNotReturned')) + '</span>' +
      '<span class="chip">' + esc(historyTimeText(h.at)) + '</span>' +
      (h.revision !== null ? '<span class="chip">rev ' + esc(String(h.revision)) + '</span>' : '<span class="chip">' + esc(t('h.revNotReturned')) + '</span>') +
      '</div>';
    if (h.kind === 'edit') {
      html += '<div class="subtitle">' + esc(t('h.reasonPrefix')) + esc(h.reason || t('h.backendNotReturned')) + '</div>' +
        '<details' + foldAttrs(folds(), foldKey('editdiff', t.id, h.revision, h.at)) + ' style="margin:4px 0 8px 12px">' +
        '<summary class="subtitle">' + esc(t('h.oldNewSummary')) + '</summary>' +
        '<div class="src" style="margin-top:6px">' + esc(t('h.oldPrefix')) + (h.oldText ? esc(h.oldText) : esc(t('h.backendNotReturned'))) + '</div>' +
        '<div class="src" style="margin-top:6px">' + esc(t('h.newPrefix')) + (h.newText ? esc(h.newText) : esc(t('h.backendNotReturned'))) + '</div>';
    } else if (h.text) {
      html += '<div class="subtitle" style="margin:0 0 8px 12px">' + esc(h.text) + '</div>';
    }
    return html;
  }

  function saveAnnotation(entry) {
    var ta = document.getElementById('annotate-text');
    var text = ta ? ta.value.trim() : '';
    var status = document.getElementById('annotate-status');
    if (!text) {
      if (status) { status.className = 'hint'; status.className = 'dialog-status err'; status.textContent = t('sa.empty'); }
      return;
    }
    var rev = inboxRevisionFor(entry);
    if (!endpointListed('POST', '/ui-pm/inbox/:id/annotate')) {
      if (status) { status.className = 'dialog-status err'; status.textContent = missingEndpointText('POST', '/ui-pm/inbox/:id/annotate'); }
      return;
    }
    if (status) { status.className = 'dialog-status'; status.textContent = t('sa.saving'); }
    performWrite({
      slot: 'inbox-annotate|' + entry.id,
      path: 'inbox/' + encodeURIComponent(entry.id) + '/annotate',
      revision: rev,
      body: { text: text },
      label: t('sa.label'), text: entry.text, ident: entry.id,
      afterOk: function () { return Promise.all([load(true, true), loadInboxDetail(entry.id)]); },
      afterConflict: function () { return Promise.all([load(true, true), loadInboxDetail(entry.id)]); }
    }).then(function () {
      var st = document.getElementById('annotate-status');
      if (!st) return;
      if (state.writeError) { st.className = 'dialog-status err'; st.textContent = state.writeError.code + t('task.errorSep') + state.writeError.message; }
      else if (state.conflict) { st.className = 'dialog-status err'; st.textContent = t('sa.conflict'); }
    });
  }

  function openEditOriginal(entry) {
    var d = (state.inboxDetail && state.inboxDetail.data) ? state.inboxDetail.data : null;
    var oldText = (d && d.text) ? d.text : entry.text;
    openConfirmDialog({
      title: '修订原文？',
      note: '改写当前文本是审计动作：旧值会逐字留在条目里，必须填写原因。',
      body: '<label class="field"><span>' + esc(t('oeo.oldLabel')) + '</span>' +
        '<textarea id="edit-old" rows="3" readonly>' + esc(oldText) + '</textarea></label>' +
        '<label class="field"><span>' + esc(t('oeo.newLabel')) + '</span>' +
        '<textarea id="edit-new" rows="3" placeholder="' + esc(t('edit.placeholderNew')) + '" required aria-required="true"></textarea></label>' +
        reasonField('修订原因', '例如：原文有错别字', true) +
        '<p class="hint">' + esc(t('oeo.firstReviseHint')) + '' +
        '旧值会写进条目正文的「旧值：」块并进入审计，不会丢。</p>' +
        '<div class="notice">' + esc(t('oeo.notice')) + '</div>',
      okLabel: '确认修订',
      onOk: function () {
        var newEl = document.getElementById('edit-new');
        var reasonEl = document.getElementById('confirm-reason');
        var newText = newEl ? newEl.value.trim() : '';
        var reason = reasonEl ? reasonEl.value.trim() : '';
        var fail = function (msg) {
          var st = document.getElementById('confirm-status');
          st.className = 'dialog-status err';
          st.textContent = msg;
          document.getElementById('confirm-dialog').showModal();
        };
        if (!newText) { fail('新值不能为空'); return; }
        if (!reason) { fail('修订必须填写原因'); return; }
        performWrite({
          slot: 'inbox-edit|' + entry.id,
          path: 'inbox/' + encodeURIComponent(entry.id) + '/edit',
          revision: inboxRevisionFor(entry),
          body: { text: newText, reason: reason },
          label: '修订原文', text: entry.text, ident: entry.id,
          afterOk: function () { return Promise.all([load(true, true), loadInboxDetail(entry.id)]); },
          afterConflict: function () { return Promise.all([load(true, true), loadInboxDetail(entry.id)]); }
        });
      }
    });
  }

  function clampNote() {
    var entries = (state.inbox && state.inbox.entries) || [];
    if (!entries.length) { state.note = -1; return; }
    if (state.note >= 0 && state.note < entries.length) return;   /* 用户已经选过，别抢 */
    /* 默认选中第一条「可操作」的条目（有稳定 ID + revision）：旧条目本来也点不了动作，
       这样右栏一进来就是能办事的那条，而不是先看到一排禁用按钮。 */
    var firstActionable = -1;
    for (var i = 0; i < entries.length; i++) {
      if (entries[i].id && typeof entries[i].revision === 'number') { firstActionable = i; break; }
    }
    state.note = firstActionable >= 0 ? firstActionable : 0;
  }

  function selectNoteById(id) {
    if (!id || !state.inbox) return;
    var idx = state.inbox.entries.map(function (e) { return e.id; }).indexOf(id);
    if (idx >= 0) state.note = idx;
  }

  /* 能不能对这条做写操作：端点就绪 + 有稳定 ID + 有真实 revision（CAS 前提）。 */
  function inboxActionState(e) {
    if (!endpointReady()) {
      return { ok: false, why: format(t('ia.notReady'), { why: ((state.inbox && state.inbox.error) || t('ia.unknownReason')) +
        '' }) };
    }
    if (!e.id) {
      return { ok: false, why: t('ia.noStableId') };
    }
    if (typeof e.revision !== 'number') {
      return { ok: false, why: t('ia.noRevision') };
    }
    return { ok: true, revision: e.revision };
  }

  /* 置顶状态判定已搬到 pm-pin-state.js（纯函数）；这里把两个能力门控辅助注入进去 */
  var PIN_STATE_DEPS = { endpointListed: endpointListed, missingEndpointText: missingEndpointText };

  /* 顶部表格行的条目来自 cards payload，可能不在当前筛选过的 inbox 列表里 */
  function findAnyInboxEntry(id) {
    var found = findInboxEntry(id);
    if (found) return found;
    var cardsInbox = state.data && state.data.inbox;
    var list = (cardsInbox && cardsInbox.entries) || [];
    for (var i = 0; i < list.length; i++) { if (list[i].id === id) return list[i]; }
    return null;
  }

  function pinNote(entry) {
    var st = inboxPinState(entry, PIN_STATE_DEPS);
    if (!st.ok) {
      el.sync.textContent = t('pin.cannotPrefix') + (entry && entry.pinned === true ? t('note.unpin') : t('note.pin')) + t('task.errorSep') + st.why;
      return Promise.resolve();
    }
    return performWrite({
      slot: (st.pinned ? 'inbox-unpin|' : 'inbox-pin|') + entry.id,
      path: 'inbox/' + encodeURIComponent(entry.id) + (st.pinned ? '/unpin' : '/pin'),
      revision: entry.revision,
      body: {},
      label: st.verb, text: entry.text, ident: entry.id,
      afterOk: function () { return Promise.all([load(true, true), loadInboxDetail(entry.id)]); },
      afterConflict: function () { return Promise.all([load(true, true), loadInboxDetail(entry.id)]); }
    });
  }

  /* 默认视图（page-designs §2.4/§2.5）：隐藏已归档 / 已合并 / 已丢弃，以及尚未到期的延期。
   * 端点不带 status 时会返回全部条目（含 ARCHIVED），所以这层过滤必须显式做，
   * 否则「归档后从默认列表消失」不成立。选「全部状态」时不做任何隐藏。 */
  function defaultViewEntries(entries) {
    var today = localDate(0);
    return entries.filter(function (e) {
      var s = String(e.status || '').toUpperCase();
      if (s === 'ARCHIVED' || s === 'MERGED' || s === 'DISMISSED') return false;
      if (s === 'SNOOZED' && e.snoozeUntil && e.snoozeUntil > today) return false;
      return true;
    });
  }

  /* 来源筛选（客户端）：多文件 inbox 后每条都带 origin（human / ai）与 file 文件名。
     旧 payload / cards 回退可能没有 origin ⇒ 按文件名兜底识别；仍未知就归空串（只在「全部来源」里出现）。 */
  function noteOrigin(e) {
    var o = String((e && e.origin) || '').toLowerCase();
    if (o === 'human' || o === 'ai') return o;
    var f = String((e && e.file) || '');
    if (f.indexOf('inbox-ai') === 0) return 'ai';
    if (f.indexOf('inbox-human') === 0) return 'human';
    return '';
  }

  function filteredEntries() {
    var all = (state.inbox && state.inbox.entries) ? state.inbox.entries : [];
    var visible = all;
    if (state.inboxStatus === '') visible = defaultViewEntries(all);
    else if (state.inboxStatus !== '*') {
      visible = all.filter(function (e) { return String(e.status || '').toUpperCase() === state.inboxStatus; });
    }
    if (state.inboxOrigin) {
      visible = visible.filter(function (e) { return noteOrigin(e) === state.inboxOrigin; });
    }
    var q = state.q.trim().toLowerCase();
    return visible
      .map(function (e) { return { e: e, i: all.indexOf(e) }; })
      .filter(function (x) { return !q || String(x.e.text).toLowerCase().indexOf(q) >= 0; });
  }

  /* 改来源筛选后，若右栏选中的那条已被滤掉，就挪到列表里第一条可见的（别让右栏显示列表外的条目） */
  function clampNoteToVisible() {
    var visible = filteredEntries();
    if (!visible.length) { state.note = -1; return; }
    var still = visible.some(function (x) { return x.i === state.note; });
    if (!still) state.note = visible[0].i;
  }

  function viewInbox() {
    if (!state.inbox) return '<div class="panel"><div class="empty">' + esc(t('inbox.loadingInbox')) + '</div></div>';
    var inbox = state.inbox;
    var entries = inbox.entries || [];
    var list = filteredEntries();
    var legacy = entries.filter(function (e) { return !e.id; });

    var html = '<div class="section-title"><div><h2>' + esc(t('inbox.heading')) + '</h2>' +
      '<p class="subtle">' + esc(t('inbox.subtitleA')) + '<code>' + esc(inbox.path) + '</code>' +
      (inbox.status ? esc(t('inbox.statusFilter')) + '<code>' + esc(inbox.status) + '</code>' : '') + '</p></div>' +
      '<button class="btn primary" type="button" id="new-capture">' + esc(t('inbox.quickCapture')) + '</button></div>';

    html += inboxStatusLegendHtml();   /* task-186：位置＝页面标题之下、下面各块（含快速记录入口区）之上 */

    if (endpointReady()) {
      var provided = [];
      if (endpointListed('POST', '/ui-pm/inbox/:id/archive')) provided.push(t('inbox.actionArchive'));
      if (endpointListed('POST', '/ui-pm/inbox/:id/snooze')) provided.push(t('inbox.actionSnooze'));
      if (endpointListed('POST', '/ui-pm/inbox/:id/merge')) provided.push(t('inbox.actionMerge'));
      if (endpointListed('POST', '/ui-pm/inbox/:id/note')) provided.push(t('inbox.actionNote'));
      if (endpointListed('POST', '/ui-pm/inbox/:id/dismiss')) provided.push(t('inbox.actionDismiss'));
      if (endpointListed('POST', '/ui-pm/proposals')) provided.push(t('inbox.actionProposal'));
      html += '<div class="notice info">' + esc(t('inbox.capsNoticeA')) + '<b>' + esc(t('inbox.capsNoticeB')) + '</b>' + esc(t('inbox.capsNoticeC')) +
        (provided.length ? esc(t('inbox.capsProvided')) + '<b>' + esc(provided.join(' / ')) + '</b>' + esc(t('inbox.capsProvidedTail')) : esc(t('inbox.capsNone'))) +
        esc(t('inbox.capsNoticeD')) + '<b>' + esc(t('inbox.capsNoticeReal')) + 'revision</b>' + esc(t('inbox.capsNoticeE')) + '<b>idempotencyKey</b>' + esc(t('inbox.capsNoticeF')) +
        esc(t('inbox.capsNoticeG')) + '</div>';
    } else {
      html += banner(esc(t('inbox.bannerA')) + '<code>/ui-pm/inbox</code>' + esc(t('inbox.bannerB')) +
        esc(inbox.error || t('det.unknownWord')) + esc(t('inbox.bannerC')) +
        esc(t('inbox.bannerD')));
    }

    html += '<div class="metrics">' +
      metric(state.data.inbox ? state.data.inbox.count : inbox.count, t('inbox.metricTotal')) +
      metric(inbox.count, inbox.status === '*' ? t('inbox.metricAll') : (inbox.status ? format(t('inbox.metricFilter'), { s: inbox.status }) : t('inbox.metricDefault'))) +
      metric(legacy.length, t('inbox.metricLegacy')) +
      metric(endpointReady() ? t('inbox.ready') : t('inbox.unavailable'), t('inbox.metricEndpoint'), !endpointReady()) +
      '</div>';

    html += '<div class="toolbar" style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:0 0 14px">' +
      '<label class="sr-only" for="inbox-q">' + esc(t('inbox.searchAria')) + '</label>' +
      '<input type="text" id="inbox-q" style="max-width:300px" placeholder="' + esc(t('inbox.searchPlaceholder')) + '" value="' + esc(state.q) + '">' +
      '<label class="sr-only" for="inbox-status">' + esc(t('inbox.statusFilterAria')) + '</label>' +
      '<select id="inbox-status" style="max-width:230px">' +
      '<option value=""' + (state.inboxStatus === '' ? ' selected' : '') + '>' + esc(t('inbox.metricDefault')) + '</option>' +
      '<option value="*"' + (state.inboxStatus === '*' ? ' selected' : '') + '>' + esc(t('inbox.metricAll')) + '</option>' +
      INBOX_FILTER_STATUSES.map(function (s) {
        return '<option value="' + s + '"' + (state.inboxStatus === s ? ' selected' : '') + '>' + s + '</option>';
      }).join('') +
      '</select>' +
      /* 来源筛选（三态：全部 / 人工 / AI）与状态筛选**叠加**：状态走端点参数，来源在客户端再过滤一层 */
      '<label class="sr-only" for="inbox-origin">' + esc(t('inbox.originFilterAria')) + '</label>' +
      '<select id="inbox-origin" style="max-width:150px" aria-label="' + esc(t('inbox.originFilterAria')) + '">' +
      '<option value=""' + (state.inboxOrigin === '' ? ' selected' : '') + '>' + esc(t('inbox.originAll')) + '</option>' +
      '<option value="human"' + (state.inboxOrigin === 'human' ? ' selected' : '') + '>' + esc(t('inbox.originHuman')) + '</option>' +
      '<option value="ai"' + (state.inboxOrigin === 'ai' ? ' selected' : '') + '>' + esc(t('inbox.originAi')) + '</option>' +
      '</select>' +
      notYet(t('inbox.filterByProject'), t('inbox.filterNotYet')) +
      '</div>';

    html += '<section class="panel"><div class="panel-head"><div><h2>' + esc(t('panel.triage')) + '</h2>' +
      '<p class="subtle">' + esc(t('inbox.notTask')) + '</p></div>' +
      '<span class="subtle" style="font-size:12px">' + esc(format(t('inbox.showing'), { n: list.length, total: entries.length })) + '</span></div>' +
      '<div class="panel-body" style="padding:6px 10px 12px">';
    if (!entries.length) {
      html += '<div class="empty">' +
        (inbox.status ? esc(format(t('inbox.noStatusEntries'), { s: inbox.status })) : esc(t('inbox.emptyInbox'))) + '</div>';
    } else if (!list.length) {
      html += '<div class="empty">' + esc(state.inboxOrigin ? t('inbox.originEmpty') : t('inbox.noMatch')) + '</div>';
    } else {
      list.forEach(function (x) { html += noteRowHtml(x.e, x.i); });
    }
    html += '</div></section>';

    html += '<div class="notice">' + esc(t('inbox.defaultHidesA')) + '<b>' + esc(t('inbox.defaultHidesB')) + '</b>' + esc(t('inbox.defaultHidesC')) + '<b>' + esc(t('inbox.defaultHidesD')) + '</b>' +
      esc(t('inbox.defaultHidesE')) +
      '<br>' + esc(t('inbox.fieldFacts')) + '</div>';

    return html;
  }

  function noteRowHtml(e, i) {
    var isLegacy = !e.id;
    var selected = state.note === i;
    var origin = noteOrigin(e);
    var can = inboxActionState(e);
    var until = e.snoozeUntil ? esc(format(t('note.snoozeUntil'), { t: e.snoozeUntil })) : '';
    /* #23：整行可点却进不了 Tab 序 ⇒ 根用 <button>（原生可聚焦、Enter/Space 可激活）；选中态补 aria-current ✓ */
    /* 用户裁定（2026-10-19）：卡片必须**包含**操作按钮 —— 原根是 <button>，里面嵌按钮被浏览器拆到外面 ✗。
       改成 <article class="note">（承载卡片观感/焦点/选中）+ 内层 <button class="note-main">（文字/meta，原生可聚焦）+ .note-actions（现在真在卡内 ✓）。*/
    return '<article class="note' + (selected ? ' selected' : '') + '" data-note="' + i + '"' +
      ' data-origin="' + origin + '"' + (e.file ? ' data-file="' + esc(e.file) + '"' : '') +
      (selected ? ' aria-current="true"' : '') + '>' +
      '<button type="button" class="note-main" data-note-main="' + i + '">' +
      '<div class="note-body">' +
      '<div class="note-text">' + highlightEsc(e.text, state.q) + '</div>' +   /* 用户 2026-10-19：搜索命中字符高亮 ✓ */
      '<div class="note-meta">' +
      (isLegacy
        ? '<span class="chip dashed" title="' + esc(t('note.legacyChipTitle')) + '">' + esc(t('note.legacyName')) + '</span>'
        : '<span class="chip solid">' + esc(e.status) + '</span>') +
      /* 来源徽章（轻量）：多文件 inbox 后区分人工 / AI；文件名放 title，不占行宽 */
      (origin
        ? '<span class="chip' + (origin === 'ai' ? ' dashed' : '') + '" data-origin-chip="' + origin + '" title="' +
          esc(format(t('inbox.originFileTitle'), { f: e.file || t('inbox.originUnknownFile') })) + '">' +
          esc(origin === 'ai' ? t('inbox.originAi') : t('inbox.originHuman')) + '</span>'
        : '') +
      /* 2026-10-19 用户：LEGACY 行只显示「老记录（无 ID）· 第 N 行」；无 rev/捕获时间就**不显示** ✗（别把"没有这个属性"当信息）*/
      (isLegacy ? '' : '<span>' + esc(t('note.idPrefix')) + esc(e.id) + '</span>') +
      (isLegacy ? '' : '<span>rev ' + (typeof e.revision === 'number' ? e.revision : '—') + '</span>') +
      '<span>' + esc(format(t('note.lineN'), { n: e.line })) + '</span>' +
      (isLegacy ? '' : '<span>' + esc(t('note.capturedPrefix')) + esc(inboxFieldText(e, 'capturedAt')) + '</span>') +
      (e.projectHint ? '<span class="chip">hint: ' + esc(e.projectHint) + '</span>' : '') +
      /* 徽章：只有真的 >0 才显示；null / 缺失一律不显示（绝不写 0） */
      (typeof e.annotationCount === 'number' && e.annotationCount > 0
        ? '<span class="chip" title="' + esc(format(t('note.annotChipTitle'), { n: e.annotationCount })) + '">' + esc(format(t('note.annotChip'), { n: e.annotationCount })) + '</span>' : '') +
      (typeof e.revisionCount === 'number' && e.revisionCount > 0
        ? '<span class="chip dashed warn" title="' + esc(format(t('note.revisedChipTitle'), { n: e.revisionCount })) + '">' + esc(format(t('note.revisedChip'), { n: e.revisionCount })) + '</span>' : '') +
      until +
      '</div>' +
      '</button>' +          /* 闭合 .note-main：操作区在它外面、但在 article.note 里面 ✓ */
      /* D7（2026-10-19 真机）：补充列表里有 <button class="anno-toggle"> ⇒ **不能**放在 button.note-main 里面
         （按钮不能嵌套 ⇒ 解析器提前闭合 .note-main ⇒ .note-actions 被挤出 article ✗，36 张里 1 张"有补充"的卡中招）
         ⇒ 移到 .note-main 外面、article.note 里面 ✓ */
      annoListHtml(e, i) +
      '<div class="note-actions">' +
      '<button type="button" class="btn small" data-note-open="' + i + '"' +
      ' aria-label="' + esc(t('note.handleAria')) + '" title="' + esc(t('note.handleAria')) + '">' + esc(t('note.handle')) + '</button>' +
      (can.ok
        ? '<button type="button" class="btn small" data-inbox-archive="' + esc(e.id) + '">' + esc(t('inbox.actionArchive')) + '</button>' +
          '<button type="button" class="btn small" data-inbox-snooze="' + esc(e.id) + '">' + esc(t('inbox.actionSnooze')) + '</button>'
        : notYet(t('inbox.actionArchive'), can.why) + notYet(t('inbox.actionSnooze'), can.why)) +
      (function () {
        var pin = inboxPinState(e, PIN_STATE_DEPS);
        return pin.ok
          ? '<button type="button" class="btn small" data-inbox-pin="' + esc(e.id) + '"' +
            ' aria-pressed="' + (pin.pinned ? 'true' : 'false') + '" title="' +
            (pin.pinned ? esc(t('note.unpinHint')) : esc(t('note.pinHint'))) + '">' + esc(pin.verb) + '</button>'
          : notYet(e.pinned === true ? t('note.unpin') : t('note.pin'), pin.why);
      })() +
      '</div></article>';
  }

  /* ================= 待验收（P3：REVIEW 任务 + transition 验收） ================= */

  function reviewCardHtml(item) {
    var sel = state.reviewSel && state.reviewSel.id === item.id;
    var total = item.criteriaTotal || 0, done = item.criteriaDone || 0;
    return '<button type="button" class="card-row' + (sel ? ' selected' : '') + '"' +
      ' data-review-id="' + esc(item.id) + '" data-review-project="' + esc(item.project) + '">' +
      '<span class="card-title">' + esc(item.title) + '</span>' +
      '<span class="task-row">' + statusBadge(item.status) +
      '<span class="chip">' + esc(format(t('rvp.cardCriteria'), { done: done, total: total })) + '</span>' +
      (item.ai ? '<span class="chip dashed" title="' + esc(t('rvp.aiTitle')) + '">AI</span>' : '') +
      '</span>' +
      '<span class="task-row subtle" style="font-size:11.5px">' + esc(item.project) +
      ' · rev ' + item.revision + ' · ' + esc(item.assignee || 'unassigned') + '</span>' +
      '</button>';
  }

  function viewReview() {
    var html = '<div class="section-title"><div><h2>' + esc(t('rvp.heading')) + '</h2>' +
      '<p class="subtle">' + esc(t('rvp.subtitle')) + '</p></div>' +
      '<button class="btn" type="button" id="refresh-inline">' + esc(t('rvp.refresh')) + '</button></div>';

    if (!capsReady()) {
      html += banner(esc(t('rvp.endpointNotReady')) + esc(unavailableReason('GET', '/ui-pm/tasks') || t('rvp.tasksUnavailable')) +
        esc(t('rvp.endpointTail2')));
      html += '<div class="metrics">' + metric('—', t('rvp.metricNotReady'), true) +
        metric('—', t('rvp.metricNoSla'), true) + metric('—', t('rvp.metricEvidence'), true) + '</div>';
      html += unbacked(t('rvp.unbackedTitle'), [
        t('rvp.unbacked1'),
        t('rvp.unbacked2'),
        t('rvp.unbacked3'),
        t('rvp.unbacked4')
      ]);
      return html;
    }

    var r = state.review;
    var items = (r && r.items) || [];
    html += banner(esc(t('rvp.bannerA')) + '<code>' + esc(t('rvp.bannerCode')) + '</code>' + esc(t('rvp.bannerB')));
    html += '<div class="notice info">' + esc(t('rvp.acceptA')) + '<b>PATCH /ui-pm/tasks/:id {action:transition, to:DONE}</b>' +
      esc(t('rvp.acceptB')) + '<code>human</code>' + esc(t('rvp.acceptC')) +
      esc(t('rvp.acceptD')) + '</div>';

    html += '<div class="metrics">' +
      metric(items.length, t('rvp.metricReview')) +
      metric(((r && r.errors) || []).length, t('rvp.metricFailed')) +
      metric('—', t('rvp.metricNoSla'), true) +
      metric('—', t('rvp.metricEvidence'), true) +
      '</div>';

    html += '<section class="panel"><div class="panel-head"><div><h2>' + esc(t('rvp.listHeading')) + '</h2>' +
      '<p class="subtle">' + esc(t('rvp.listSubtitleA')) +
      ((state.data.projects || []).length) + esc(t('rvp.listSubtitleB')) + '</p></div>' +
      '<span class="badge gray">' + items.length + esc(t('rvp.itemsCount')) + '</span></div><div class="panel-body">';
    if (!r) {
      html += '<div class="empty">' + esc(t('rvp.loading')) + '</div>';
    } else if (!items.length) {
      html += '<div class="empty">' + esc(t('rvp.emptyA')) + '<br>' +
        '<span class="subtle">' + esc(t('rvp.emptyB')) + '</span></div>';
    } else {
      items.forEach(function (item) { html += reviewCardHtml(item); });
    }
    if (r && r.errors && r.errors.length) {
      html += '<div class="notice warn">' + esc(format(t('rvp.errorsLine'), { n: r.errors.length })) +
        esc(r.errors.slice(0, 3).map(function (e) { return e.project + t('rvp.errParenOpen') + e.message + t('rvp.errParenClose'); }).join(t('rvp.errSep'))) +
        (r.errors.length > 3 ? esc(t('rvp.errorsMore')) : '') + '</div>';
    }
    html += '</div></section>';

    html += '<div class="notice">' + esc(t('rvp.detailHintA')) +
      esc(t('rvp.detailHintB')) + '</div>';
    return html;
  }

  /* ================= 记忆与决策（P4：候选 → 人工确认 → 正式） ================= */

  function typeChip(type) {
    var cls = type === 'decision' ? 'purple' : type === 'gotcha' ? 'amber' : 'blue';
    return '<span class="badge ' + cls + '">' + esc(MEMORY_TYPES[type] || type || esc(t('chip.untyped'))) + '</span>';
  }

  /* 当前 scope 下的记忆集合（取代链/呈现判定与列表同源 ✓；scope 为空=全部）*/
  function memoryScopedList() {
    var all = memoryAllEntries(state.memory) || []
    var sc = String(state.memoryScope || '')
    return sc ? all.filter(function (e) { return String((e && e.scope) || '') === sc }) : all
  }
  /* 按 scope 的记忆块列表（内部记录/23「记忆块（按 scope）」）：每块给条目计数；未标范围归到一件并如实命名 ✓ */
    /* 1a：scope 选择从「左列表按钮」改为「顶部下拉」—— 三档计数写进 option 文本（信息不丢）。*/
  function memoryScopeOptions() {
    /* 用户 2026-10-21：下拉计数必须与页面 tabs/列表同口径 —— 取「**待确认候选** + 正式/已废弃条目」，
       不再把"已处理候选档案"算进来（否则出现 下拉 3 条 · 正式 2 / tabs 正式 1 ✗）。
       数据是**全量**（loadMemory 不传 scope）⇒ 各 scope 的分项计数与选中后页面的数字一致 ✓ */
    var all = splitCandidates((state.memory && state.memory.candidates) || []).pending
      .concat((state.memory && state.memory.entries) || [])
    var by = {}, byTier = {}
    all.forEach(function (e) {
      var kk = e.scope ? String(e.scope) : ''
      by[kk] = (by[kk] || 0) + 1
      var tt = byTier[kk] || (byTier[kk] = { CANDIDATE: 0, VERIFIED: 0, DEPRECATED: 0 })
      if (tt[e.status] !== undefined) tt[e.status]++
    })
    var cur = state.memoryScope || ''
    var opt = function (v, label, n, tier) {
      var cnt = tier ? ' · ' + format(t('memp.scopeCounts'), { c: tier.CANDIDATE, v: tier.VERIFIED, d: tier.DEPRECATED }) : ''
      return '<option value="' + esc(v) + '"' + (cur === v ? ' selected' : '') + '>' + esc(label) + (n == null ? '' : ' （' + esc(String(n)) + ' 条' + cnt + '）') + '</option>'
    }
    var keys = Object.keys(by).filter(function (x) { return x !== '' }).sort()
    return opt('', t('memp.allScopes'), all.length, null) +
      keys.map(function (k2) { return opt(k2, k2, by[k2], byTier[k2]) }).join('') +
      (by[''] ? opt('__noscope__', t('memp.noScope'), by[''], byTier['']) : '')
  }
  function memModeBtn(key, label, enabled) {
    var cur = (state.memoryMode || 'browse') === key;
    return '<button type="button" class="mem-mode-btn' + (cur ? ' active' : '') + '" role="tab"' +
      ' data-mem-mode="' + esc(key) + '" aria-selected="' + (cur ? 'true' : 'false') + '"' +
      (enabled ? '' : ' disabled aria-disabled="true"') + '>' + esc(label) + '</button>';
  }
  /* §3#3 搜索面：q 必填 + 可选 scope/type/limit/any（按端点清单 ✓）；提交走 GET /ui-pm/recall（结果面 P2 第二片）*/
      /* TODO（用户 2026-10-19，优先级低）：检索请求若返回**非 JSON**（如 "Unexpected token B…"）应改为人话 ——
       用 r.text() 兜底显示"HTTP <status> + 前 80 字"，不要把 JSON 解析异常当文案 ✗；本轮先留 TODO（用户说搜索设计后边再找素材替代）。*/
/* 用户 2026-10-20：搜索面视觉重做 —— 输入行（label + 自适应输入框 + 检索按钮）**同一行**；说明文字下一行；
     结果不再挤在输入行里 ⇒ 渲染到主内容区 #entries（filters 之下、底部 notice 之上 ✓）。*/
  function memorySearchBarHtml(searchOk) {
    return '<div class="mem-search-bar" role="search">' +
      '<label class="mem-search-label" for="mem-q">' + esc(t('memp.searchLabel')) + '</label>' +
      '<input id="mem-q" name="mem-q" class="mem-search-input" type="search" autocomplete="off" data-mem-q="1"' +
      ' placeholder="' + esc(t('memp.searchPlaceholder')) + '"' + (searchOk ? '' : ' disabled') + '>' +
      '<button type="button" class="btn" data-mem-search-go="1"' + (searchOk ? '' : ' disabled aria-disabled="true"') + '>' +
      esc(t('memp.searchGo')) + '</button>' +
      '</div>' +
      '<div class="mem-search-hint hint">' + esc(t('memp.searchHint')) + '</div>';
  }
  /* 三种结果态**一眼可区分**（Lead 2026-10-18）：① 无关键词（还没搜）② 搜了没命中 ③ 端点缺失（功能关闭）。
     命中项带 path:line 与相关度（打原文 ⇒ 读数可逐字对照 ✓）。 */
  /* 检索结果按档位过滤（用户 2026-10-21：进入检索后 全部/候选/正式/已废弃 也能筛）*/
  function memorySearchHits() {
    var s = state.memSearch;
    if (!s || !s.hits) return [];
    var tier = state.memoryTier || 'candidate';
    return s.hits.filter(function (h) {
      if (tier === 'all') return true;
      if (tier === 'candidate') return String(h.status) === 'CANDIDATE';
      if (tier === 'deprecated') return String(h.status) === 'DEPRECATED';
      return String(h.status) === 'VERIFIED';
    });
  }
  function memorySearchResultHtml(searchOk) {
    if (!searchOk) {
      return '<div class="empty">' + esc(t('memp.searchDisabled')) + '<code>GET /ui-pm/recall</code>' +
        (unavailableReason('GET', '/ui-pm/recall') ? esc(format(t('memp.reasonParen'), { r: unavailableReason('GET', '/ui-pm/recall') })) : '') + '</div>';
    }
    var s = state.memSearch;
    if (!s) return '<div class="empty">' + esc(t('memp.searchIdle')) + '</div>';
    if (s.error) return '<div class="empty">' + esc(t('memp.searchFailed')) + '<code>' + esc(String(s.error)) + '</code></div>';
    /* 用户 2026-10-21：检索必须带上**两个过滤器**（当前项目 scope / 类型），并把实际生效条件写出来 ✓ */
    var scopeLabel = s.scope ? String(s.scope) : t('memp.allScopes');
    var typeLabel = s.type ? (MEMORY_TYPES[s.type] || String(s.type)) : t('memp.filterTypeAll');
    var filterLine = '<div class="subtle mem-search-filters">' + esc(format(t('memp.searchFilters'), { s: scopeLabel, t: typeLabel })) + '</div>';
    var hits = memorySearchHits();
    if (!s.hits || !s.hits.length) {
      return filterLine + '<div class="empty">' + esc(format(t('memp.searchNoHit'), { q: s.term || '' })) + '</div>';
    }
    if (!hits.length) {
      return filterLine + '<div class="subtle">' + esc(format(t('memp.searchHits'), { n: 0, q: s.term || '' })) + '</div>' +
        '<div class="empty">' + esc(t('memp.searchHitTierEmpty')) + '</div>';
    }
    return filterLine + '<div class="subtle">' + esc(format(t('memp.searchHits'), { n: hits.length, q: s.term || '' })) + '</div>' +
      '<ul class="mem-hits">' + hits.map(function (h) {
        var loc = String(h.path || '') + (h.line ? ':' + String(h.line) : '');
        var sel = state.memHit && String(state.memHit.id) === String(h.id);
        return '<li class="mem-hit' + (sel ? ' sel' : '') + '" data-mem-hit-id="' + esc(String(h.id || '')) + '" tabindex="0">' +
          '<code class="mem-hit-loc">' + esc(loc) + '</code>' +
          '<span class="chip">' + esc(String(h.status || '')) + '</span>' +
          '<span class="chip dashed">rev ' + esc(String(h.revision == null ? '—' : h.revision)) + '</span>' +
          '<span class="mem-hit-score">' + esc(format(t('memp.searchScore'), { s: String(h.score == null ? '—' : h.score) })) + '</span>' +
          '<span class="mem-hit-text">' + highlightEsc(String(h.snippet || h.text || h.title || ''), s.term) + '</span></li>';   /* 命中项自带 title（recall 结果无 text 字段）*/
      }).join('') + '</ul>';
  }

  /* §3#4 时间范围的实现：按档取"有时间语义"的字段（候选=createdAt、正式=verifiedAt）；
     'all' 或未知值 ⇒ 不过滤 ✓（默认值不放宽任何东西 ⇒ 旧读数不作废 ✓）。 */
  function memoryInRange(e, kind) {
    var r = state.memoryRange || 'all';
    if (r === 'all') return true;
    var days = r === '7d' ? 7 : (r === '30d' ? 30 : 0);
    if (!days) return true;
    var t = kind === 'verified' ? (e.verifiedAt || e.createdAt) : e.createdAt;
    if (!t) return true;                       /* 没时间的条目**不因范围被藏**（如实显示 ✓） */
    var ms = Date.parse(t);
    if (isNaN(ms)) return true;
    return (Date.now() - ms) <= days * 86400000;
  }
  function memoryRangeBar() {
    var r = state.memoryRange || 'all';
    var opt = function (v, k) { return '<option value="' + v + '"' + (r === v ? ' selected' : '') + '>' + esc(t(k)) + '</option>' };
    return '<label class="mem-range">' + esc(t('memp.rangeLabel')) +
      '<select id="mem-range" name="mem-range" data-mem-range="1">' + opt('all', 'memp.rangeAll') + opt('7d', 'memp.range7') + opt('30d', 'memp.range30') + '</select></label>';
  }

  /* §3#5 懒加载（P1）：列表**只给首行摘要**（不再整段渲染全文 ✗），点开才展开全文。
     行数用格式键（zh「共 {n} 行」/ en "{n} lines"）⇒ 不留空 en ✓。展开态存 state.memoryExpanded[id] ✓。 */
  function memoryTitleHtml(e) {
    var full = String(e.text == null ? '' : e.text);
    var lines = full.split(String.fromCharCode(10));
    var first = (lines[0] || '').trim();
    var more = lines.length > 1 || first.length > 120;
    var shown = first.length > 120 ? first.slice(0, 120) + '…' : first;
    var ex = state.memoryExpanded && state.memoryExpanded[String(e.id)];
    var key = 'memr.moreLines';
    var expandLabel = more
      ? t(ex ? 'memr.collapse' : 'memr.expand') + (ex ? '' : ' ' + format(t(key), { n: lines.length }))
      : '';
    return '<span class="card-title">' + esc(ex ? full : shown) +
      (more
        ? '</span><button type="button" class="mem-expand" data-mem-expand="' + esc(e.id) + '"' +
          ' aria-expanded="' + (ex ? 'true' : 'false') + '">' + esc(expandLabel) + '</button><span class="card-title-tail">'
        : '') +
      '</span>';
  }

  /* ---- P0 分栏（内部记录/12 §3#1/#6/#9）---- */
  /* 选中的记忆条目：在候选 + 正式 + 已废弃里按 id 找（state.memorySel 由现有卡片点击设置 ✓） */
  function memorySelEntry() {
    var sel = state.memorySel;
    if (!sel || !sel.id) return null;
    var all = memoryAllEntries(state.memory) || [];
    for (var i = 0; i < all.length; i++) if (String(all[i].id) === String(sel.id)) return all[i];
    return null;
  }
  /* 分栏宽度持久化（§3#9）：记忆页专属 key，默认 360，夹在 260..560 之间（不让用户拖到没法用 ✓） */
  function memoryDetailWidth() {
    var w = Number(state.memoryDetailW);
    if (!w || isNaN(w)) {
      try { w = Number(localStorage.getItem('pm-memory-split-w')) } catch (e) { w = 0 }
    }
    if (!w || isNaN(w)) w = 360;
    return Math.max(260, Math.min(560, Math.round(w)));
  }
  /* 右栏分层详情：编号 / 类型 / 范围 / 状态 / revision / 来源 / 时间 / 全文；未选中给空态（§3#6 四类空态之一 ✓） */
  function memoryDetailHtml(e) {
    if (!e) return '<div class="empty">' + esc(t('memp.detailEmpty')) + '</div>';
    var dep = e.status === 'DEPRECATED';
    var row = function (label, val) {
      return '<div class="mem-kv"><span class="mem-k">' + esc(label) + '</span><span class="mem-v">' + val + '</span></div>';
    };
    var srcs = (e.sources && e.sources.length)
      ? e.sources.map(function (x) { return '<code>' + esc(String(x)) + '</code>' }).join(' ')
      : '<span class="subtle">' + esc(t('memr.notWritten')) + '</span>';
    return '<div class="detail-section"><h3>' + esc(t('memp.detailHeading')) + '</h3>' +
      row(t('memr.shortIdLabel'), '<span class="mem-id" role="button" tabindex="0" data-mem-copy="' + esc(memoryFullId(e.id)) + '" title="' + esc(t('memr.copyIdTitle')) + '">' + esc(memoryShortId(e.id)) + '</span>') +
      row(t('det.typeHeading'), esc(MEMORY_TYPES[e.type] || e.type || '—')) +
      row(t('memp.scopeLabel'), esc(e.scope || '—')) +
      row(t('memr.statusLabel'), esc(dep ? t('memr.deprecated') : (e.status === 'CANDIDATE' ? t('memr.candidate') : t('memr.confirmed')))) +
      row('revision', esc(String(e.revision == null ? '—' : e.revision))) +
      /* 内部记录/23 载荷里的**新字段**：layer(L1/L2/L3) 与 file(来源文件) —— 缺失一律写「未写入」，不猜 ✓ */
      row(t('memp.layerLabel'), e.layer ? '<span class="chip">' + esc(String(e.layer)) + '</span>' : '<span class="subtle">' + esc(t('memr.notWritten')) + '</span>') +
      row(t('memp.fileLabel'), e.file ? '<code>' + esc(String(e.file)) + '</code>' : '<span class="subtle">' + esc(t('memr.notWritten')) + '</span>') +
      row(t('det.sourceHeading'), srcs) +
      row(t('memr.timeLabel'), esc(localTime(e.createdAt) || t('memr.notWritten'))) +
      '</div>' +
      '<div class="detail-section"><h3>' + esc(t('memr.textHeading')) + '</h3>' +
      '<p class="mem-text">' + esc(e.text || '') + '</p></div>';
  }

  /* 内部记录/12 §3#2（P0）：三档切换器 + 计数徽章。计数未加载（null/undefined）⇒ 显示「—」，
     不把"未知"写成 0（§0 反模式⑤）；已加载但为 0 ⇒ 老实显示 0。 */
  function memoryTierBar(nCand, nVerified, nDeprecated) {
    var tier = state.memoryTier || 'candidate';
    var fmt = function (n) { return (n === null || n === undefined) ? '—' : String(n) };
    var item = function (key, label, n) {
      return '<button type="button" class="tab' + (tier === key ? ' sel' : '') + '" data-mem-tier="' + esc(key) + '"' +
        ' role="tab" aria-selected="' + (tier === key ? 'true' : 'false') + '">' + esc(label) +
        '<span class="n">' + esc(fmt(n)) + '</span></button>';
    };
    return '<div class="tabs" id="tabs" role="group" aria-label="' + esc(t('memp.tierAria')) + '">' +
      item('all', t('memp.tierAll'), nCand + nVerified + nDeprecated) +
      item('candidate', t('memp.tierCandidate'), nCand) +
      item('verified', t('memp.tierVerified'), nVerified) +
      item('deprecated', t('memp.tierDeprecated'), nDeprecated) +
      '</div>';
  }

    /* ②（0.2.6.3）：条目行改用 内部记录/23 的词汇（entry/top/tbadge/sbadge/unsourced/src/txt/meta/chain/acts ✓）
     + 卡片态 .sel（选中）/.linked（取代链悬停高亮目标）/.flash（跳转闪一下）✓；整卡可点（不再用 <button> 包一层 ✗）。*/
  function memoryRowHtml(e, kind, shownIds) {
    var sel = state.memorySel && state.memorySel.id === e.id &&
      state.memorySel.kind === (kind || (e.status === 'CANDIDATE' ? 'candidate' : 'verified'));
    var presentIds = shownIds || memoryPresentIds(memoryScopedList());
    var links = memoryLinks(e, memoryScopedList());
    var dep = e.status === 'DEPRECATED'
    var statusLabel = kind === 'candidate' ? t('memr.candidate') : (dep ? t('memr.deprecated') : t('memr.confirmed'))
    var typeCls = String(e.type || '').toLowerCase()
    var chain = links.map(function (l) {
      var info = memoryLinkLabel(l, presentIds);
      return '<span class="tag' + (info.present ? '' : ' dep') + '"' +
        ' data-mem-link="' + esc(l.id) + '" data-mem-dir="' + esc(l.dir) + '"' +
        ' title="' + esc(info.present ? (t('memr.jumpToTarget') + memoryFullId(l.id)) : (t('memr.targetNotListed') + memoryFullId(l.id))) + '">' +
        esc(info.label) + '</span>';
    }).join('')
    return '<article class="entry' + (sel ? ' sel open' : '') + '" tabindex="0"' +
      ' data-memory-id="' + esc(e.id) + '" data-memory-kind="' + esc(kind || (e.status === 'CANDIDATE' ? 'candidate' : 'verified')) + '">' +
      '<div class="top">' +
        '<span class="tbadge ' + esc(typeCls) + '">' + esc(String(e.type || '').toUpperCase()) + '</span>' +
        '<span class="sbadge' + (dep ? ' dep' : '') + '">' + esc(statusLabel) + '</span>' +
        (e.unsourced ? '<span class="unsourced">' + esc(t('memr.noSource')) + '</span>' : '') +
        '<span class="src" title="' + esc(memoryFullId(e.id) || t('memr.notWritten')) + '">' + esc(memoryShortId(e.id)) + '</span>' +
      '</div>' +
      /* 示例 627-647：收起=首行摘要，展开(.open)=完整正文 ✓ */
      '<div class="txt">' + (sel
        ? esc(String(e.text || ''))
        : esc(String(e.text || '').split('\n')[0].slice(0, 80))) + '</div>' +
      '<div class="meta">rev ' + esc(String(e.revision)) +
        (kind === 'candidate'
          ? esc(t('memr.extractedAt')) + esc(localTime(e.createdAt) || '—') + esc(t('memr.by')) + esc(e.createdBy || '—')
          : esc(t('memr.confirmedAt')) + esc(localTime(e.verifiedAt) || '—') + esc(t('memr.by')) + esc(e.verifiedBy || '—')) +
        ' · ' + esc(e.scope || '—') + '</div>' +
      (chain ? '<div class="chain">' + chain + '</div>' : '') +
      '<div class="acts">' +
        '<span class="pill" role="button" tabindex="0" data-mem-expand="' + esc(e.id) + '"' +
          ' aria-expanded="' + (sel ? 'true' : 'false') + '">' + esc(sel ? t('memr.collapse') : t('memp.actExpand')) + '</span>' +
        (kind === 'candidate'
          ? (endpointListed('POST', '/ui-pm/memory-candidates/:id/verify')
            ? '<span class="pill primary" role="button" tabindex="0" data-memory-verify="' + esc(e.id) + '">' + esc(t('memp.actVerify')) + '</span>'
            : '') +
            (endpointListed('POST', '/ui-pm/memory/:id/discard')
              ? '<span class="pill danger" role="button" tabindex="0" data-memory-discard="' + esc(e.id) + '">' + esc(t('memp.actDiscard')) + '</span>'
              : '')
          : (e.status !== 'DEPRECATED' && endpointListed('POST', '/ui-pm/memory/:id/deprecate')
            ? '<span class="pill danger" role="button" tabindex="0" data-memory-deprecate="' + esc(e.id) + '">' + esc(t('memp.actDeprecate')) + '</span>'
            : '')) +
        '<span class="pill" role="button" tabindex="0" data-mem-copy="' + esc(memoryFullId(e.id)) + '"' +
          ' title="' + esc(t('memr.copyIdTitle') + (memoryFullId(e.id) || t('memr.notWritten'))) + '">' + esc(t('memr.copyIdTitle')) + '</span>' +
      '</div>' +
      '</article>'
  }
  function contextPanelHtml() {
    var scopes = (state.data.projects || []).map(function (p) { return p.key; });
    var html = '<section class="panel"><div class="panel-head"><div><h2>' + esc(t('dfm.contextHeading2')) + '</h2>' +
      '<p class="subtle">' + esc(t('ctx.subtitle')) + '</p></div>' +
      '<label class="sr-only" for="context-scope">' + esc(t('ctx.pickScopeAria')) + '</label>' +
      '<select id="context-scope" style="max-width:200px"><option value="">' + esc(t('ctx.pickScopeOption')) + '</option>' +
      scopes.map(function (s) {
        return '<option value="' + esc(s) + '"' + (state.contextScope === s ? ' selected' : '') + '>' + esc(s) + '</option>';
      }).join('') + '</select></div><div class="panel-body">';
    if (!state.contextScope) {
      html += '<div class="empty">' + esc(t('ctx.emptyHint')) + '</div>';
    } else if (!state.context) {
      html += '<div class="empty">' + esc(t('ctx.loadingPrefix'))  + esc(state.contextScope)  + esc(t('ctx.loadingSuffix')) + '</div>';
    } else {
      var c = state.context;
      html += '<div class="kv">' +
        '<b>scope</b><span>' + esc(c.scope) + '</span>' +
        '<b>' + esc(t('ctx.onlyVerified')) + '</b><span>' + (c.onlyVerified ? esc(t('ctx.yes'))  : esc(t('ctx.no')) + '') + '</span>' +
        '<b>' + esc(t('ctx.includeGlobal')) + '</b><span>' + (c.includeGlobal ? esc(t('ctx.yes2')) : esc(t('ctx.no2'))) + '</span>' +
        '<b>' + esc(t('ctx.crossScope')) + '</b><span>' + (c.allowCrossScope ? esc(t('ctx.authorized'))  : esc(t('ctx.notAuthorized')) + '') + '</span>' +
        '<b>' + esc(t('ctx.entersContext')) + '</b><span>' + (c.counts.total || 0)  + esc(t('ctx.itemsPrefix'))  + c.counts.fact  + esc(t('ctx.decisionSep'))  + c.counts.decision  + esc(t('ctx.gotchaSep'))  + c.counts.gotcha + '）</span>' +
        '<b>' + esc(t('ctx.excluded')) + '</b><span>' + esc(t('ctx.candPrefix'))  + c.excluded.candidate  + esc(t('ctx.deprecatedPrefix'))  + c.excluded.deprecated +
        ' · 其它 scope ' + c.excluded.otherScope + '</span>' +
        '<b>' + esc(t('dfm.sourceLabel2')) + '</b><span>' + (c.sources && c.sources.length ? esc(c.sources.join('、')) : esc(t('dfp.noneWord3')) + '') + '</span>' +
        '</div>';
      html += '<p class="hint">' + esc(t('ctx.defaultScopeHintPrefix'))  + esc(c.scope)  + esc(t('ctx.defaultScopeHintTail')) + '</p>';
    }
    html += '</div></section>';
    return html;
  }

  /* task-265：初始系统提示词页的装配（骨架期：块来自模板/会话草稿，真读写在 slice ③ 接 /ui-pm/prompt ✓） */
  function promptPageState() {
    var projects = (state.data && state.data.projects) || [];
    /* 用户 2026-10-20 改进②③：项目下拉 = ui-cards 的项目 ∪「已保存过提示词」的项目（/ui-pm/prompts），
       并标注每个项目「已保存 rev N」/「无记录（模板起）」⇒ 用户不用再猜哪个项目已经有 prompt.org ✓ */
    var savedRevByKey = {}
    ;(state.promptIndex || []).forEach(function (x) {
      var kk = String((x && x.key) || '')
      if (kk) savedRevByKey[kk] = Number((x && x.rev) || 0)
    })
    var mergedProjects = []
    var seenProj = {}
    projects.forEach(function (x) {
      var k1 = String(x.key || '')
      if (!k1 || seenProj[k1]) return
      seenProj[k1] = true
      mergedProjects.push({ key: k1, title: x.title || k1, mem: x.mem, tasks: x.tasks,
        savedRev: Object.prototype.hasOwnProperty.call(savedRevByKey, k1) ? savedRevByKey[k1] : null })
    })
    ;(state.promptIndex || []).forEach(function (x) {
      var k2 = String((x && x.key) || '')
      if (!k2 || seenProj[k2]) return
      seenProj[k2] = true
      mergedProjects.push({ key: k2, title: k2, mem: null, tasks: null, savedRev: Number((x && x.rev) || 0) })
    })
    var cur = mergedProjects.filter(function (x) { return x.key === state.project })[0] || mergedProjects[0] || null;
    var blocks = state.promptBlocks || blankBlocks();
    /* ⚠️ 脏基线必须是**进入本页时/上次保存后**的快照 ✗ 不能是"当前 blocks" ——
       我第一版写成 (state.promptSaved == null) ? JSON.stringify(blocks) : … ⇒ 基线==当前 ⇒ **永远不脏** ✗
       ⇒ 保存/撤销按钮永远 disabled ⇒ 用户根本没法保存 ✗（探针的「撤销两步确认」判据抓到的就是这个 ✓）。 */
    if (state.promptSaved === undefined) state.promptSaved = JSON.stringify(blocks);   /* 首次进入：模板即基线 ✓ */
    var savedJson = state.promptSaved;
    return {
      key: (cur && cur.key) || state.project || '',
      projects: mergedProjects,
      blocks: blocks,
      dirty: promptIsDirty(blocks, savedJson),
      exists: state.promptExists === true,
      serverRev: state.promptRev || 0,
      open: state.promptOpen == null ? -1 : state.promptOpen,
      savedAt: state.promptSavedAt || null,
      savedProjects: state.promptIndex || [],
      loading: state.promptLoading === true,
      noProject: state.promptNoProject === true,
      conflict: state.promptConflict || null,
      saving: state.promptSaving === true,
      revertArmed: state.promptRevertArmed === true,   /* 撤销要两步确认（防"敲了很多字才误点"✓）*/
      docs: state.promptDocs || {},
      savedIncludes: state.promptSavedIncludes || {},
      pvOpen: state.promptPvOpen !== false,
      lib: state.promptLib || [],
      libProj: state.promptLibProj || 'ALL',
      libQ: state.promptLibQ || '',
      renderAvailable: state.promptRenderAvailable === true,
      savedBlocks: state.promptSaved ? JSON.parse(state.promptSaved) : [],
      caps: {
        get: endpointListed('GET', '/ui-pm/prompt'),
        put: endpointListed('PUT', '/ui-pm/prompt')
      }
    };
  }

  function viewMemory() {
    var html = '<h1>' + esc(t('memp.heading')) + '</h1><p class="hint">' + esc(t('memp.subtitle')) + '</p>';

    if (!capsReady()) {
      html += banner(esc(t('memp.endpointNotReady')) + esc(unavailableReason('GET', '/ui-pm/memory') || t('memp.memUnavailable')) +
        esc(t('memp.endpointTail')));
      html += '<div class="metrics">' + metric('—', t('memp.metricCandNotReady'), true) +
        metric('—', t('memp.metricVerNotReady'), true) + metric('—', t('memp.metricNoConflict'), true) + '</div>';
      html += unbacked(t('memp.unbackedTitle'), [
        t('memp.unbacked1'),
        t('memp.unbacked2'),
        t('memp.unbacked3'),
        t('memp.unbacked4')
      ]);
      return html;
    }

    var m0 = state.memory;
    /* 验收⑤（错误态）：**加载失败必须说出来**。此前只有"caps 不就绪"才有提示 ✗ ⇒ 接口 500/网络错时页面一片空白、用户无从判断 ✓；
       这里把 state.memory.error 显式渲染（点名 + 原因 ✓，与"让空/失败可解释"同族 ✓）。 */
    if (m0 && m0.error) {
      html += banner(esc(t('memp.memLoadFailed')) + esc(String(m0.error)));
    }
    var m = state.memory;
    /* 用户 2026-10-21：**scope 过滤只在这里做一次**（候选/正式/已废弃/统计/下拉计数全部来自同一份过滤结果）
       ⇒ 不会再出现"下拉 3 条 · tabs/列表 1 条"两处计数打架 ✗ */
    var memScope = String(state.memoryScope || '');
    var memInScope = function (e) { return !memScope || String((e && e.scope) || '') === memScope; };
    /* task-218：候选区**只列待确认**（status === CANDIDATE）；已处理（VERIFIED/DEPRECATED）进下面的折叠区保留可查。
       计数/徽章/空态/列表全部共用这一份 candidates（= pending），不会出现"计数说 3、列了 2"。 */
    var candSplit = splitCandidates(((m && m.candidates) || []).filter(memInScope));
    var candidates = candSplit.pending;
    var processedCandidates = candSplit.processed;
    var entries = ((m && m.entries) || []).filter(memInScope);
    var deprecated = entries.filter(function (e) { return e.status === 'DEPRECATED'; });
    var unsourced = candidates.concat(entries).filter(function (x) { return x.unsourced }).length;

    if (state.discardNote) {
      html += '<p class="mem-note"><b>' + esc(state.discardNote.note) + '</b>' +
        esc(t('memp.shortIdPrefix')) + esc(memoryShortId(state.discardNote.id)) +
        esc(t('memp.reasonPrefix')) + esc(state.discardNote.reason) + '</p>';
    }
    if (state.writeError) {
      html += '<p class="mem-note warn">' + esc(t('memp.prevFailedPrefix')) +
        esc(memoryWriteErrorText(state.writeError.code, state.writeError.message)) + '</p>';
    }
      


    /* B1（用户 2026-10-19 裁定，与 内部记录/23 对齐）：类型/显示已废弃控件已并入下方 .filters 同一行 ✓ */

    /* task-158：先把「本屏实际会渲染的 id」算出来（候选 + 正式，含类型/废弃过滤），
       再渲染卡片 —— 取代链的目标是否在本页据此判定。 */
    /* §3#4 时间范围（P1）：只对"有时间语义"的档生效（候选=createdAt / 正式=verifiedAt；已废弃档不适用 ⇒ 不出选择器 ✓）。
       "范围过大"⇒ 给**降级文案**而不是硬渲（阈值 200，先本地判；后端有真阈值时再换 ✓）。 */
    var rangeBlocked = tier !== 'deprecated' && candidates.concat(entries).filter(function (e) { return memoryInRange(e, tier) }).length > 200;
    if (rangeBlocked) html += '<div class="notice">' + esc(t('memp.rangeTooLarge')) + '</div>';
    var shownCandidates = candidates.filter(typeFilter).filter(function (e) { return memoryInRange(e, 'candidate') });
    var shownVerified = [];
    var allTypes = state.memoryType ? [state.memoryType] : ['fact', 'decision', 'gotcha'];
    allTypes.forEach(function (type) {
      entries.filter(function (e) {
        return e.type === type && (state.memoryShowDeprecated || e.status !== 'DEPRECATED');
      }).forEach(function (e) { if (memoryInRange(e, 'verified')) shownVerified.push(e); });
    });
    /* task-218：折叠里的"已处理"**仍在页面上** → 也要算进 shownIds（否则取代链目标会被误判"不在本页"） */
    var shownProcessed = processedCandidates.filter(typeFilter);
    var shownIds = shownCandidates.concat(shownProcessed).concat(shownVerified).map(function (e) { return String(e.id); });

    /* 内部记录/12 §3#2（P0）：三档切换器 + 计数徽章。计数**未加载时显示占位「—」**，绝不把"未知"显示成 0（§0 反模式⑤）。
       task-01M52EY6VH7309KZ21BNCRABBJ：默认档=candidate（与旧页面首屏一致，避免"默认看不到东西"）。 */
    /* §3#3（P2）：浏览 / 搜索双模式。搜索走 GET /ui-pm/recall；
       端点缺失（capabilities 里没有）⇒ 页签**禁用**并**点名缺哪个端点**（沿用 unavailableReason ✓，与"让空/失败可解释"同族 ✓）。 */
    var searchOk = endpointListed('GET', '/ui-pm/recall');
    /* 内部记录/23 的 .stats：只做**真实**控件（刷新=重取当前页数据 ✓）；
       示例里的 #demo（演示数据选择）与 #theme（主题）与 pm 契约无关 ⇒ **不做**（设计输入不是照搬 ✓）。 */
    html += '<div class="stats">' +
      '<button type="button" class="btn small" data-mem-refresh="1">' + esc(t('memp.refresh')) + '</button>' +
      '<span class="subtle">' + esc(format(t('memp.statsLine'), { n: candidates.length + entries.length, c: candidates.length, v: entries.filter(function (x) { return x.status !== 'DEPRECATED' }).length, d: deprecated.length, u: (candidates.concat(entries)).filter(function (x) { return x.unsourced }).length })) + '</span>' +
      '</div>';
    /* B1（用户 2026-10-19 裁定，与 内部记录/23 对齐）：范围 / 类型 / 显示已废弃 / 浏览·搜索 **同一行**，顺序照示例 .filters ✓ */
    html += '<div class="filters" role="tablist">' +
      ('<label class="sr"><select id="fscope" class="btn bordered" aria-label="' + esc(t('memp.scopeAria')) + '" data-mem-scope-sel="1">' + memoryScopeOptions() + '</select></label>') +
      '<select id="memory-type" class="btn bordered" aria-label="' + esc(t('memp.filterTypeAria')) + '">' +
      '<option value="">' + esc(t('memp.filterTypeAll')) + '</option>' +
      /* task-01M52ADGGT15：回调参数名不得用 t —— 会遮蔽 i18n 的 t() ⇒ TypeError: t is not a function
         ⇒ render() 在写 #content 前中断 ⇒ 症状「头新体旧」。参数改名 kind；{ t: kind } 的键名 t 是文案占位符，保持不变。 */
      ['fact', 'decision', 'gotcha'].map(function (kind) {
        return '<option value="' + kind + '"' + (state.memoryType === kind ? ' selected' : '') + '>' +
          esc(MEMORY_TYPES[kind]) + esc(format(t('memp.typeSuffix'), { t: kind })) + '</option>';
      }).join('') + '</select>' +
      '<button type="button" class="btn bordered' + (state.memoryShowDeprecated ? ' active' : '') + '"' +
      ' id="memory-show-deprecated" aria-pressed="' + (state.memoryShowDeprecated ? 'true' : 'false') + '">' +
      (state.memoryShowDeprecated ? esc(t('memp.hideDeprecated')) : esc(t('memp.showDeprecated'))) + '</button>' +
      memModeBtn('browse', t('memp.modeBrowse'), true) +
      memModeBtn('search', t('memp.modeSearch'), searchOk) +
      /* 端点缺失时必须**点名缺哪个端点**（Lead 2026-10-18）⇒ 永远带上路径字面量，
         有 unavailableReason 就再接一句原因（原因可能不含路径，所以不能只靠它 ✓）。 */
      (searchOk ? '' : '<span class="hint" id="mem-search-why">' + esc(t('memp.searchDisabled')) +
        '<code>GET /ui-pm/recall</code>' +
        (unavailableReason('GET', '/ui-pm/recall') ? esc(format(t('memp.reasonParen'), { r: unavailableReason('GET', '/ui-pm/recall') })) : '') + '</span>') +
      '</div>';
    var mode = state.memoryMode || 'browse';
    if (mode === 'search') {
      html += memorySearchBarHtml(searchOk);
    }
    /* 浏览面的 hidden 直接放在 #entries 上（不再包一层 mem-browse：那层的开/闭跨了 .mem-split 边界 ⇒ 会交叉配平 ✗） */
    /* 1b：三档 tabs 属于右栏（示例 .tabs 在 section.detail 里 ✓）⇒ 移到 dhead 之后渲染（见下） */
    var tier = state.memoryTier || 'candidate';
    /* P0（内部记录/12 §3#1）：左列表 + 右分层详情分栏。宽度持久化沿用记忆页专属 key（§3#9）。
       ⚠️ 详情用 state.memorySel（点卡片已经在设它 ✓）⇒ 不新增点击处理 ✓，只在渲染时按选中项出右栏 ✓。 */
    /* §3#6 四类空态之一（"该档无条目"）：分档后**必须**按档给一句不同的话，不能留空白 ✗。
       计数口径：候选=待确认；正式=非 DEPRECATED；已废弃=只 DEPRECATED。 */
    var tierCount = tier === 'candidate'
      ? candidates.length
      : (tier === 'all'
        ? candidates.length + entries.length + deprecated.length
        : (tier === 'verified'
          ? entries.filter(function (x) { return x.status !== 'DEPRECATED' }).length
          : deprecated.length));
    var selMem = memorySelEntry();
    html += '<div class="split" style="--mem-detail-w:' + esc(String(memoryDetailWidth())) + 'px">' +
      /* 内部记录/23 示例：左「记忆块（按 scope）」+ 计数；点选即过滤（复用既有 state.memoryScope ⇒ 与 #mem-scope 下拉同一状态 ✓）*/
      /* 1b（Lead 裁定对齐 内部记录/23 示例）：右栏 = section.detail( .dhead 标题 + .tabs 三档 + #entries 条目列表 + 正文 ) ✓ */
      /* 1a（Lead 2026-10-19 裁定）：左侧块列表已移除（示例 .split 单栏 + 注释「scope 只用顶部下拉」）⇒ 单栏 ✓ */
      '<section class="detail" id="mem-detail" aria-label="' + esc(t('memp.detailHeading')) + '">' +
      '<div class="dhead"><span class="t">' + esc(format(t('memp.dheadTitle'), { scope: state.memoryScope ? state.memoryScope : t('memp.allScopes') })) + '</span>' +
        '<span class="src">' + esc(format(t('memp.dheadSrc'), { scope: state.memoryScope ? state.memoryScope : t('memp.allScopes') })) + '</span></div>' +
      /* verifier 复核（2026-10-19）：跳到取代链/缺失目标的**可见反馈**容器 —— 曾在 A-③ 被删 ⇒ setMemoryNote 静默跳过 ✗。
         位置：**dhead 之后**、tabs/entries 之前（放进 dhead 里会让头部凭空多 22px 空隙 ⇒ 与示例 header 不一致 ✗）；
         默认空、有反馈才显示（:empty 隐藏、不占高）；role=status+aria-live 让读屏能读到 ✓ */
      '<p id="mem-link-note" class="mem-note" role="status" aria-live="polite"></p>' +
      (function () {
        /* 用户 2026-10-21：检索模式下档位 tabs 也要能筛结果 ⇒ 计数改成"命中的档位分布"（与筛选同源 ✓）*/
        if (mode === 'search' && state.memSearch && state.memSearch.hits) {
          var hs = state.memSearch.hits;
          var nC = hs.filter(function (h) { return String(h.status) === 'CANDIDATE' }).length;
          var nV = hs.filter(function (h) { return String(h.status) === 'VERIFIED' }).length;
          var nD = hs.filter(function (h) { return String(h.status) === 'DEPRECATED' }).length;
          return memoryTierBar(nC, nV, nD);
        }
        return memoryTierBar(candidates.length, entries.length, deprecated.length);
      })() +
      '<div id="entries" class="entries' + (mode === 'search' ? ' mem-search-entries' : '') + '">';
    if (mode === 'search') {
      /* 用户要求：搜索结果卡片显示在**下边**（主内容区）✓ */
      html += '<div id="mem-search-result" class="mem-search-result">' + memorySearchResultHtml(searchOk) + '</div>';
    } else {
    /* B3（用户 2026-10-19 裁定，与 内部记录/23 对齐）：#entries 内**一个扁平列表**、按档位过滤；
       删掉「候选记忆」panel 外壳与按类型分组的 panel（示例 #entries 里没有分组标题/外壳 ✓）。
       计数与列表从此用**同一个集合**（同一个 flat）⇒ 不会再有"tab 8 / 列表 0"的口径分裂 ✓ */
    var flat = tier === 'candidate'
      ? candidates
      : (tier === 'verified'
        ? entries.filter(function (e) { return e.status !== 'DEPRECATED' })
        : (tier === 'deprecated' ? deprecated : candidates.concat(entries)));
    flat = flat.filter(typeFilter).filter(function (e) {
      return memoryInRange(e, tier === 'candidate' ? 'candidate' : (tier === 'deprecated' ? 'deprecated' : 'verified'));
    });
    /* 取代链"目标在不在当前页"的口径必须与**实际渲染的列表**一致（用户 2026-10-19 截图指出：
       tooltip 说"点击跳到目标卡片"、点了却提示"不在当前列表" ⇒ 因为旧 shownIds 含已被删掉的「已处理」行；
       现在 shownIds = flat 的真实成员 ⇒ tooltip / 悬停高亮 / 点击 三者同源 ✓）*/
    shownIds = flat.map(function (e) { return String(e.id); });
    flat.forEach(function (e) { html += memoryRowHtml(e, tier === 'candidate' ? 'candidate' : 'verified', shownIds); });
    /* 四档各自空态（示例 577-580 四种不同的话）；时间范围过滤生效时优先说「范围内没有」✓ */
    if (!flat.length) {
      var emptyKey = (!rangeBlocked && (state.memoryRange || 'all') !== 'all')
        ? 'memp.rangeEmpty'
        : (tier === 'candidate' ? 'memp.candidatesEmpty'
          : (tier === 'verified' ? 'memp.verifiedEmptyTier'
            : (tier === 'deprecated' ? 'memp.deprecatedEmptyTier' : 'memp.allEmptyTier')));
      html += '<div class="empty mem-tier-empty">' + esc(t(emptyKey)) + '</div>';
    }
    }
    html += '</div>' +                                   /* /mem-entries */
      /* 示例 .detail = dhead + tabs + #entries（条目信息在卡内展开 ✓；分层详情/正文块已删 ✓）*/
      '</section>' +                                      /* /mem-detail（右栏） */
      '</div>';                                          /* /mem-split（分栏拖拽条已删 ✓）*/

    /* P0-1（用户裁定 2026-10-19）：删掉「上下文影响」整块（含 scope 选择器）✗ —— 示例里没有 ✓ */
    html += '<div class="notice">' + esc(t('memp.conflictPrefix')) + '<code>supersedes</code> / <code>supersededBy</code>' + esc(t('memp.conflictTail')) +
      esc(t('memp.conflictTail2')) + '</div>';

    html += '<div class="notice">' + esc(t('memp.noticeA')) + '<b>' + esc(t('memp.noticeB')) + '</b>' + esc(t('memp.noticeC')) +
      '<b>' + esc(t('memp.discardBold')) + '</b>' + esc(t('memp.discardTail')) +
      '<b>' + esc(t('memp.mergeBold')) + '</b>' + esc(t('memp.mergeTail')) +
      (endpointListed('POST', '/ui-pm/memory/:id/discard') ? ''
        : ' <b>' + esc(t('memp.noDiscardA')) + '</b>' + esc(t('memp.noDiscardB'))) + '</div>';
    /* 用户要求（2026-10-19）：诚实标注移到最后 + 文案更详细；细节放**可折叠**区（默认收起 ✓，页面侧文案 ✓ 不动 docs）*/
    html += '<details class="boundary"><summary>' + esc(t('memp.noticeMore')) + '</summary><ul>' +
      ['memp.noticeD1','memp.noticeD2','memp.noticeD3','memp.noticeD4','memp.noticeD5'].map(function (k2) { return '<li>' + esc(t(k2)) + '</li>' }).join('') +
      '</ul></details>';
    /* 用户裁定（2026-10-19）：诚实标注必须是页面**最后一块**（真机核过：此前误落在 detailForMemory 死路径 ✗）*/
    return html;
  }

  function typeFilter(e) {
    return !state.memoryType || e.type === state.memoryType;
  }

  /* ================= 第三栏：当前项详情 / 操作 ================= */

  function detailForCard() {
    var c = state.data.cards.filter(function (x) { return x.session_id === state.card; })[0];
    if (!c) return null;
    var html = '<div class="detail-section"><h3>' + esc(t('det.obsHeading')) + '</h3>' +
      '<p>' + obsBadge(c) + ' <span class="subtle">' + esc(c.observation_label || '') + '</span></p>' +
      '<p class="hint">' + esc(t('det.obsHint')) +
      esc(t('det.obsLabelHintA')) + esc(c.observation_label || '') + esc(t('det.obsLabelHintB')) + '</p></div>';

    html += '<div class="detail-section"><h3>' + esc(t('det.summaryHeading')) + '</h3>' +
      (c.summary
        ? '<p>' + esc(c.summary) + '</p><p class="hint">' + esc(c.summary_source === 'ai' ? t('det.summarySourceAi') : format(t('det.summarySourceOther'), { s: c.summary_source })) + '</p>'
        : '<p class="subtle">' + esc(format(t('det.summaryNone'), { s: c.summary_source || 'not_generated' })) + '</p>') +
      '</div>';

    html += '<div class="detail-section"><h3>' + esc(t('det.factsHeading')) + '</h3><div class="kv">' +
      '<b>' + esc(t('det.kvProject')) + '</b><span>' + esc(c.project) + '</span>' +
      '<b>' + esc(t('det.kvInstance')) + '</b><span>' + esc(c.instance) + '</span>' +
      '<b>' + esc(t('det.kvTurns')) + '</b><span>' + esc(format(t('det.turnsSteps'), { t: c.turns, s: c.steps })) + '</span>' +
      '<b>' + esc(t('det.kvCachedTodos')) + '</b><span>' + esc(format(t('det.cachedTodos'), { n: c.open_todos, total: c.total_todos })) + '</span>' +
      '<b>' + esc(t('det.kvLastRecord')) + '</b><span>' + esc(format(t('det.lastRecordValue'), { time: localTime(c.recorded_at) || t('det.unknownWord'), rel: relTime(c.recorded_at) })) + '</span>' +
      '<b>' + esc(t('det.kvCwd')) + '</b><span style="word-break:break-all">' + esc(c.cwd || t('det.notRecorded')) + '</span>' +
      '</div></div>';

    html += '<div class="detail-section"><h3>' + esc(t('det.sourceHeading')) + '</h3><div class="src">' + esc(c.card_file || t('det.notRecorded')) + '</div></div>';

    html += '<div class="detail-section"><button type="button" class="btn primary" data-session="' +
      esc(c.session_id) + '" data-instance="' + esc(c.instance) + '">' + esc(t('det.openSession')) + '</button>' +
      (isArchived(c) ? '<p class="hint">' + esc(t('det.archivedHint')) + '</p>' : '') +
      '</div>';
    return html;
  }

  function detailForBoard() {
    var d = state.data;
    return '<div class="detail-section"><h3>' + esc(t('det.dataSourceHeading')) + '</h3>' +
      '<div class="src">' + esc('GET ../cards · ' + (d.schemaVersion || 'ui-cards')) + '<br>' +
      esc(format(t('det.generatedAt'), { v: (d.generated_at || t('det.unknownWord')) })) + '<br>' +
      esc(t('det.readonlySnapshot')) + '<br>' +
      esc(format(t('det.library'), { v: (d.library || t('det.unknownWord')) })) + '</div>' +
      '<p class="hint">' + esc(format(t('det.capabilities'), { v: (d.capabilities || []).join(', ') || t('det.notDeclared') })) + '</p></div>' +
      '<div class="detail-section"><h3>' + esc(t('det.howToRead')) + '</h3>' +
      '<ul class="hint" style="margin:0 0 0 18px;padding:0;line-height:1.8">' +
      '<li>' + esc(format(t('det.howToRead1'), { list: Object.keys(OBS_MEANING).map(function (k) { return OBS_MEANING[k]; }).join(' / ') })) + '</li>' +
      '<li>' + esc(t('det.howToRead2')) + '<code>needs_attention=true</code>' + esc(t('det.howToRead2b')) + '</li>' +
      '<li>' + esc(t('det.howToRead3')) + '<code>summary_source=not_generated</code>' + esc(t('det.howToRead4')) + '</li>' +
      '<li>' + esc(t('det.howToRead5')) + '</li>' +
      '</ul></div>' +
      '<div class="detail-section"><h3>' + esc(t('det.colorHeading')) + '</h3>' +
      '<p class="hint">' + esc(t('det.colorHintA')) +
      esc(t('det.colorHintB')) + '<span class="chip dashed">' + esc(t('det.chipDashed')) + '</span> ' +
      '<span class="badge gray"><span class="dot"></span>' + esc(t('det.badgeGray')) + '</span></p></div>';
  }

  function detailForInbox() {
    if (!state.inbox || !state.inbox.entries.length) return '<div class="empty">' + esc(t('di.noRecords')) + '</div>';
    var inbox = state.inbox;
    var i = state.note;
    if (i < 0 || i >= inbox.entries.length) i = 0;
    var e = inbox.entries[i];
    var can = inboxActionState(e);
    var busy = state.busy;

    var hist = inboxHistory();
    /* 修订之后 entries[].text 就是**新值**（显式修订的语义），所以标题说「当前文本」；
       捕获原文保留在 revisions[].oldText / 审计 / 正文「旧值：」块里。
       次数只在真的读到 revisions[] 时才显示 —— 读不到就写「修订次数未返回」，不编造 0。 */
    var detailCaps = endpointListed('GET', '/ui-pm/inbox/:id');
    var detailLoaded = !!(state.inboxDetail && state.inboxDetail.id === e.id && state.inboxDetail.data);
    var editCount = hist.filter(function (h) { return h.kind === 'edit'; }).length;
    var countKnown = detailCaps && detailLoaded;
    var titleBadge = '';
    if (countKnown && editCount > 0) {
      titleBadge = ' <span class="chip dashed warn" title="' + esc(t('di.revisedBadgeTitle')) + '">' +
        esc(format(t('di.revisedBadge'), { n: editCount })) + '</span>';
    } else if (!countKnown) {
      titleBadge = ' <span class="chip dashed" title="' + esc(missingEndpointText('GET', '/ui-pm/inbox/:id')) + '">' + esc(t('di.editsNotReturned')) + '</span>';
    }
    var html = '<div class="detail-section" id="inbox-text" tabindex="-1"><h3>' + esc(t('di.currentTextHeading')) + (countKnown && editCount === 0 ? esc(t('di.notRevisedYet')) : '') +
      ' <span class="chip">' + esc(t('di.readonly')) + '</span>' + titleBadge + '</h3>' +
      '<div class="src">' + esc(e.text) + '</div>' +
      '<p class="hint">' + esc(t('di.currentTextHintA')) + '<b>' + esc(t('di.currentTextHintB')) + '</b>' + esc(t('di.currentTextHintC')) +
      esc(t('di.currentTextHintD')) + '<b>' + esc(t('di.currentTextHintE')) + '</b>' + esc(t('di.currentTextHintF')) + '<b>' + esc(t('di.currentTextHintG')) + '</b>' +
      esc(t('di.currentTextHintH')) + '</p>' +
      '<div class="kv" style="margin-top:10px">' +
      '<b>' + esc(t('di.kvStableId')) + '</b><span>' + (e.id ? esc(e.id) : '<span class="chip dashed">' + esc(t('di.noneChip')) + '</span>' + esc(t('di.legacyParen'))) + '</span>' +
      '<b>' + esc(t('di.kvStatus')) + '</b><span>' + esc(e.status) + '</span>' +
      '<b>' + esc(t('di.kvRevision')) + '</b><span>' + (typeof e.revision === 'number' ? e.revision : esc(t('di.endpointNotReturned'))) + '</span>' +
      '<b>' + esc(t('di.kvSnoozeUntil')) + '</b><span>' + (e.snoozeUntil ? esc(e.snoozeUntil) : esc(t('di.dash'))) + '</span>' +
      '<b>' + esc(t('di.kvLocation')) + '</b><span>' + esc(inbox.path) + esc(format(t('di.lineN'), { n: e.line })) + '</span>' +
      '<b>' + esc(t('di.kvCaptured')) + '</b><span>' + inboxField(e, 'capturedAt') + '</span>' +
      '<b>' + esc(t('di.kvSource')) + '</b><span>' + inboxField(e, 'source') + '</span>' +
      '<b>' + esc(t('di.kvProjectHint')) + '</b><span>' + inboxField(e, 'projectHint') + '</span>' +
      '</div></div>';

    html += '<div class="detail-section"><h3>' + esc(t('di.archiveSnoozeHeading')) + '</h3>';
    if (can.ok) {
      html += '<p class="hint">' + esc(t('di.archiveHintA')) + '<b>' + esc(t('di.archiveHintReal')) + ' revision ' + can.revision + '</b>' + esc(t('di.archiveHintB')) +
        esc(t('di.archiveHintC')) + '</p>' +
        '<div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:10px">' +
        '<button type="button" class="btn" data-inbox-archive="' + esc(e.id) + '"' +
        (busy ? ' disabled aria-disabled="true"' : '') + '>' + esc(t('di.archiveEllipsis')) + '</button>' +
        (function () {
          var pin2 = inboxPinState(e, PIN_STATE_DEPS);
          return pin2.ok
            ? '<button type="button" class="btn" data-inbox-pin="' + esc(e.id) + '"' + (busy ? ' disabled' : '') +
              ' aria-pressed="' + (pin2.pinned ? 'true' : 'false') + '">' + esc(pin2.verb) + '…</button>'
            : notYet(pin2.pinned ? t('note.unpin') : t('note.pin'), pin2.why);
        })() + '</div>' +
        '<div class="snooze-row">' +
        '<label for="snooze-date">' + esc(t('di.snoozeLabel')) + '</label>' +
        '<input type="date" id="snooze-date" value="' + tomorrowLocal() + '"' + (busy ? ' disabled' : '') + '>' +
        '<button type="button" class="btn" data-inbox-snooze="' + esc(e.id) + '"' +
        (busy ? ' disabled aria-disabled="true"' : '') + '>' + esc(t('di.snoozeEllipsis')) + '</button>' +
        '</div>' +
        '<p class="hint">' + esc(t('di.twoActionsHint')) + '</p>';
        
    } else {
      html += '<p class="hint">' + esc(can.why) + '</p>' +
        '<div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:10px">' +
        notYet(t('di.archiveEllipsis'), can.why) + notYet(t('di.snoozeEllipsis'), can.why) + '</div>';
    }
    if (busy) html += '<p class="hint">' + esc(t('di.submitting')) + '</p>';
    html += '</div>';

    /* 分流动作的可用性只来自 capabilities：端点在本实例存在就启用并真的调用 */
    var proposalsOk = endpointListed('POST', '/ui-pm/proposals');
    var noteOk = endpointListed('POST', '/ui-pm/inbox/:id/note');
    var mergeOk = endpointListed('POST', '/ui-pm/inbox/:id/merge');
    var dismissOk = endpointListed('POST', '/ui-pm/inbox/:id/dismiss');
    var opBtn = function (label, ok, method, path, kind, danger) {
      if (!can.ok) return notYet(label, can.why);
      if (!ok) return notYet(label, missingEndpointText(method, path));
      return '<button type="button" class="btn small' + (danger ? ' danger' : '') + '" data-inbox-op="' + kind + '"' +
        ' data-inbox-op-id="' + esc(e.id) + '"' + (busy ? ' disabled aria-disabled="true"' : '') + '>' +
        esc(label) + '…</button>';
    };
    html += '<div class="detail-section" id="inbox-actions" tabindex="-1"><h3>' + esc(t('di.actionsHeading')) + '</h3>' +
      '<p class="hint">' + esc(t('di.actionsHintA')) + '<b>' + esc(t('di.actionsHintB')) + '</b>' + esc(t('di.actionsHintC')) +
      esc(t('di.actionsHintD')) + '</p>' +
      '<div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:10px">' +
      opBtn(t('di.opProposal'), proposalsOk, 'POST', '/ui-pm/proposals', 'ai-task') +
      opBtn(t('di.opNote'), noteOk, 'POST', '/ui-pm/inbox/:id/note', 'note') +
      opBtn(t('di.opMerge'), mergeOk, 'POST', '/ui-pm/inbox/:id/merge', 'merge') +
      opBtn(t('di.opDismiss'), dismissOk, 'POST', '/ui-pm/inbox/:id/dismiss', 'dismiss', true) +
      '</div>' +
      (can.ok ? '' : '<p class="hint">' + esc(can.why) + '</p>') +
      '<div class="notice" style="margin-top:10px">' + esc(t('di.noticeA')) +
      esc(t('di.noticeB')) + '<b>' + esc(t('di.noticeC')) + '</b>' + esc(t('di.noticeD')) +
      esc(t('di.noticeE')) + '</div></div>';

    /* 补充（追加式，原文不动） */
    var capsAnnotate = endpointListed('POST', '/ui-pm/inbox/:id/annotate');
    var capsEdit = endpointListed('POST', '/ui-pm/inbox/:id/edit');
    var capsDetail = endpointListed('GET', '/ui-pm/inbox/:id');
    var detailErr = (state.inboxDetail && state.inboxDetail.id === e.id) ? state.inboxDetail.error : null;

    html += '<div class="detail-section"><h3>' + esc(t('di.annotateHeading')) + '</h3>';
    if (!can.ok) {
      html += notYet(t('di.saveAnnotate'), can.why);
    } else if (!capsAnnotate) {
      html += notYet(t('di.saveAnnotate'), missingEndpointText('POST', '/ui-pm/inbox/:id/annotate'));
    } else {
      html += '<label class="field"><span>' + esc(t('di.annotateField')) + '</span>' +
        '<textarea id="annotate-text" rows="3" placeholder="' + esc(t('di.annotatePlaceholder')) + '"></textarea></label>' +
        '<div class="op-row"><button type="button" class="btn" id="annotate-save" data-annotate-save="' + esc(e.id) + '"' +
        (busy ? ' disabled aria-disabled="true"' : '') + '>' + esc(t('di.saveAnnotate')) + '</button>' +
        '<span class="hint" id="annotate-status" role="status" aria-live="polite"></span></div>' +
        '<p class="hint">' + esc(t('di.annotateHint')) + '</p>';
    }
    html += '</div>';

    /* 修订原文（显式，记旧值） */
    html += '<div class="detail-section"><h3>' + esc(t('di.editHeading')) + '</h3>';
    if (!can.ok) {
      html += notYet(t('di.editOriginal'), can.why);
    } else if (!capsEdit) {
      html += notYet(t('di.editOriginal'), missingEndpointText('POST', '/ui-pm/inbox/:id/edit'));
    } else {
      html += '<div class="op-row"><button type="button" class="btn small" id="edit-open" data-edit-open="' + esc(e.id) + '"' +
        (busy ? ' disabled aria-disabled="true"' : '') + '>' + esc(t('di.editEllipsis')) + '</button></div>' +
        '<p class="hint">' + esc(t('di.editHint')) + '</p>';
    }
    html += '</div>';

    /* 历史（倒序） */
    html += '<div class="detail-section"><h3>' + esc(t('di.historyHeading')) +
      (hist.length ? esc(format(t('di.historyCount'), { n: hist.length })) : '') + '</h3>';
    if (!capsDetail) {
      html += '<p class="hint">' + esc(missingEndpointText('GET', '/ui-pm/inbox/:id')) + '</p>';
    } else if (detailErr) {
      html += '<p class="hint">' + esc(t('di.historyFailed')) + esc(detailErr) + esc(t('di.historyFailedTail')) + '</p>';
    } else if (!state.inboxDetail || state.inboxDetail.id !== e.id) {
      html += '<p class="hint">' + esc(t('di.historyLoading')) + '</p>';
    } else if (!hist.length) {
      html += '<p class="hint">' + esc(t('di.historyEmpty')) + '</p>';
    } else {
      hist.forEach(function (h) { html += historyRowHtml(h); });
      html += '<p class="hint">' + esc(t('di.historyHint')) + '</p>';
    }
    html += '</div>';

    html += writeResultHtml();

    html += '<div class="detail-section"><h3>' + esc(t('di.impactHeading')) + '</h3>' +
      '<div class="notice" style="margin:0">' + esc(t('di.impactA')) + '<code>' + esc(inbox.path) + '</code>' +
      esc(t('di.impactB')) + '<br>' +
      esc(t('di.impactC')) + '</div></div>';

    html += '<div class="detail-section"><h3>' + esc(t('di.contractHeading')) + '</h3>' + writeShapeHtml() +
      '<p class="hint">' + esc(t('di.contractA')) + '<code>human</code>' + esc(t('di.contractB')) +
      esc(t('di.contractC')) + '</p></div>';

    return html;
  }

  /* 最近一次写命令的结果：成功 → 凭据；409 → 冲突（已自动重拉）；其它 → 失败原因。 */
  function writeResultHtml() {
    var html = '';
    if (state.credential) {
      var c = state.credential;
      var d = c.data || {};
      var extra = '';
      var isProposalWrite = c.action === '批准提案' || c.action === '拒绝提案' || c.action === '修改提案计划';
      if (d.op === 'pin' || d.op === 'unpin') {
        extra = ' · 后端返回 op=' + esc(String(d.op)) + '、pinned=' + (d.pinned === true ? t('wr.pinnedTrue') : t('wr.pinnedFalse'));
      } else if (d.idempotent) extra = t('wr.idempotent');
      else if (d.changed === false) extra = t('wr.changedFalse');
      html += '<div class="detail-section"><h3>' + esc(t('wr.credHeading')) + '</h3><div class="cred">' +
        (c.text ? '<div class="src" style="margin-bottom:9px">' + esc(c.text) + '</div>' : '') +
        '<p><b>' + esc(c.action || t('wr.actionDefault')) + esc(t('wr.succeededSuffix')) + '</b>' + (((c.data || {}).previousStatus || (c.data || {}).status) ? t('wr.colon') : '') +
        esc(d.previousStatus || '—') + ' → ' + esc(d.status || '—') +
        (c.until ? t('wr.deferUntilPrefix') + esc(c.until) + t('wr.parenClose') : '') + esc(extra) + '</p>' +
        (function () {
          /* task-73：状态名一律读响应，不硬编码；任务 id 只取响应 taskIds，不与提案 id 混用 */
          var inboxInfo = d.inbox || null;
          var inboxStatus = (inboxInfo && inboxInfo.status) ? String(inboxInfo.status)
            : (d.inboxStatus ? String(d.inboxStatus) : '');
          var inboxId = (inboxInfo && inboxInfo.id) ? String(inboxInfo.id) : '';
          var inboxRev = (inboxInfo && inboxInfo.revision !== undefined) ? inboxInfo.revision
            : (d.inboxRevision !== undefined ? d.inboxRevision : null);
          var out = '';
          if (d.taskIds && d.taskIds.length) {
            out += '<p>' + esc(t('wr.createdPrefix')) + '<b>' + esc(d.project || t('wr.targetProject')) + '</b>' + esc(format(t('wr.createdMid'), { n: d.taskIds.length })) + '</p>' +
              '<p><b>' + esc(t('wr.newTaskIdLabel')) + '</b>' + esc(t('wr.fromResponsePrefix')) + '<code>data.taskIds</code>' + esc(t('wr.colon')) + esc(d.taskIds.join(t('wr.listSep'))) + '</p>';
            var det = currentProposal();
            var detailIds = (det && Array.isArray(det.taskIds)) ? det.taskIds : null;
            if (detailIds && detailIds.length && detailIds.join(',') !== d.taskIds.join(',')) {
              out += '<p class="hint">' + esc(t('wr.mismatchA2')) + '<code>data.taskIds</code>：' + esc(d.taskIds.join('、')) +
                esc(t('wr.detailPrefix')) + '<code>:PM_TASK_IDS:</code>' + esc(t('wr.colon')) + esc(detailIds.join(t('wr.listSep'))) + esc(t('wr.bothListed'));
            }
          }
          if (d.taskIds || inboxStatus || inboxId) {
            out += t('wr.inboxStatusPrefix') + (inboxStatus ? '<b>' + esc(inboxStatus) + '</b>'
              : '<span class="subtle">' + esc(t('wr.notReturnedParen')) + '</span>') +
              ((inboxId || inboxRev !== null)
                ? '（' + (inboxId ? esc(inboxId) + ' · ' : '') + 'revision ' + esc(String(inboxRev === null ? t('wr.notReturned') : inboxRev)) + '）'
                : '') + '</p>';
          }
          if (isProposalWrite) {
            out += '<p class="hint">' + esc(t('wr.proposalA2')) +
              '两者不是同一个对象，不要互相冒充。</p>';
          }
          return out;
        })() +
        '<div class="kv" style="margin-top:9px">' +
        '<b>entityId' + (isProposalWrite ? t('wr.thisProposalParen') : '') + '</b><span>' + esc(c.entityId || '—') + '</span>' +
        '<b>revision</b><span>' + esc(c.revision === undefined ? '—' : String(c.revision)) + '</span>' +
        '<b>source</b><span>' + esc(c.source || '—') + '</span>' +
        '<b>observedAt</b><span>' + esc(c.observedAt || '—') + '</span>' +
        '<b>auditEventId</b><span>' + esc(c.auditEventId || '—') + '</span>' +
        '</div>' +
        '<p class="hint">' + esc(t('wr.credHint')) + esc(t('wr.credHintTail'))
    }
    if (state.conflict) {
      var cf = state.conflict;
      var isDigest = cf.code === 'DIGEST_CONFLICT';
      html += '<div class="detail-section"><h3>' + (isDigest ? t('wr.digestConflict') : t('wr.revisionConflict')) + '</h3><div class="conflict-box">' +
        '<p><b>' + esc(cf.code) + '</b>' + esc(t('wr.colon')) + esc(cf.message) + '</p>' +
        '<div class="kv" style="margin-top:9px">' +
        (isDigest
          ? '<b>' + esc(t('wr.currentDigestLabel')) + '</b><span>' + esc(cf.currentDigest ? String(cf.currentDigest).slice(0, 16) + '…' : esc(t('wr.responseNotReturned'))) + '</span>' +
            (state.briefEdit && state.briefEdit.digest ? '<b>' + esc(t('wr.yourDigestLabel')) + '</b><span>' + esc(String(state.briefEdit.digest).slice(0, 16)) + '…</span>' : '')
          : '<b>' + esc(t('wr.youSawLabel')) + '</b><span>' + esc(t('wr.revisionWord')) + esc(cf.expectedRevision === undefined ? '—' : String(cf.expectedRevision)) + '</span>' +
            '<b>' + esc(t('wr.fileNowLabel')) + '</b><span>' + esc(t('wr.revisionWord')) + esc(cf.currentRevision === undefined ? '—' : String(cf.currentRevision)) + '</span>') +
        '</div>' +
        ((cf.hint || cf.diffHint) ? '<p class="hint">' + esc(cf.hint || cf.diffHint) + '</p>' : '') +
        '<p class="hint"><b>' + (isDigest ? t('wr.digestChangedHint') : t('wr.refreshHint')) + '</b>' +
        (isDigest ? '新的 digest 已经重新取回；刚才一个字节都没写（CAS 不会覆盖别人的修改）。'
                  : '列表已按最新 revision 重新拉取；刚才的提交没有写入任何内容（CAS 不会覆盖别人的修改）。') +
        '</p></div></div>';
    }
    if (state.writeError) {
      var w = state.writeError;
      var hint = '';
      if (w.status === 404) hint = '宿主对 <code>/ui-pm/inbox/:id/…</code> 返回 404：运行中的 DSH 可能还是旧构建（没有 inbox 路由），需要重启宿主。';
      else if (w.status === 422) hint = '422 = 命令在语义上被拒绝（例如旧条目没有 :ID:、日期不合法）。这类条目应先在 Org 里补 :ID:（§9）。';
      else if (w.status === 502) hint = '502 = pm 命令本身失败（宿主已经收到请求）。';
      else if (w.status === 0) hint = '请求没有到达宿主（网络或同源问题）。';
      html += '<div class="detail-section"><h3>' + esc(t('wr.submitFailedHeading')) + '</h3><div class="error-box">' +
        '<p><b>' + esc(w.code) + '</b> · HTTP ' + esc(String(w.status || '—')) + esc(t('wr.colon')) + esc(w.message) + '</p>' +
        '<p class="hint">' + esc(t('wr.actionLabel2'))  + esc(w.action)  + esc(t('wr.entryLabel2'))  + esc(w.id) + '</p>' +
        (hint ? '<p class="hint">' + hint + '</p>' : '') +
        '</div></div>';
    }
    return html;
  }

  /* ---------- 收件箱写命令：归档 / 延期 ---------- */

  /* idempotencyKey 由客户端生成；同一 (条目, 动作, until) 的重试沿用同一个 key。 */
  function idempotencyKey(id, action, until) {
    var slot = id + '|' + action + '|' + (until || '');
    if (!state.idem[slot]) state.idem[slot] = mintKey();
    return state.idem[slot];
  }

  /* 本地日期 YYYY-MM-DD（offsetDays=0 即今天）。不能用 toISOString：那是 UTC。 */
  function localDate(offsetDays) {
    var d = new Date(Date.now() + (offsetDays || 0) * 86400000);
    return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate());
  }

  function tomorrowLocal() { return localDate(1); }

  /* inbox 条目字段：区分「端点没返回这个字段」与「条目本身没有这个属性」 */
  function inboxField(e, key) {
    if (!Object.prototype.hasOwnProperty.call(e, key)) return '<span class="subtle">' + esc(t('field.notReturned')) + '</span>';
    var v = e[key];
    if (v === null || v === undefined || v === '') return '<span class="subtle">' + esc(t('field.noProperty')) + '</span>';
    if (key === 'capturedAt') return esc(localTime(v) || String(v));
    return esc(String(v));
  }

  /* 纯文本版本（列表行用，避免在 meta 里塞 HTML） */
  function inboxFieldText(e, key) {
    if (!Object.prototype.hasOwnProperty.call(e, key)) return t('field.notReturned');
    var v = e[key];
    if (v === null || v === undefined || v === '') return t('field.noProperty');
    if (key === 'capturedAt') return localTime(v) || String(v);
    return String(v);
  }

  function copyText(text, statusId) {
    var status = statusId ? document.getElementById(statusId) : null;
    var ok = function () { if (status) { status.textContent = t('sx.copiedCheck'); } };
    var bad = function () { if (status) { status.textContent = t('sx.copyFailedManual'); } };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(ok, bad);
      return;
    }
    try {
      var ta = document.getElementById('ai-instruction');
      if (ta && ta.select) { ta.select(); document.execCommand && document.execCommand('copy'); ok(); return; }
    } catch (e) { /* 落到下面 */ }
    bad();
  }

  function findInboxEntry(id) {
    var entries = (state.inbox && state.inbox.entries) || [];
    for (var i = 0; i < entries.length; i++) { if (entries[i].id === id) return entries[i]; }
    return null;
  }

  /* 分流写命令：note / merge / dismiss（端点存在才启用；CAS revision 来自列表） */
  var INBOX_OP_LABEL = { note: t('op.note'), merge: t('op.merge'), dismiss: t('op.dismiss') };

  function inboxOp(action, entry, body) {
    return performWrite({
      slot: entry.id + '|' + action + '|' + JSON.stringify(body || {}),
      path: 'inbox/' + encodeURIComponent(entry.id) + '/' + action,
      revision: entry.revision,
      body: body || {},
      label: INBOX_OP_LABEL[action] || action,
      text: entry.text, ident: entry.id,
      afterOk: function () { return load(true, true); },
      afterConflict: function () { return load(true, true); }
    });
  }

  /* ---------- 提案：AI 指令 + 人工表单 ---------- */

  function buildAiProposalInstruction(e) {
    var lines = [];
    lines.push('请为下面这条随手记创建一条提案（proposal），不要创建正式任务，也不要派发执行。');
    lines.push('');
    lines.push('- 条目 ID：' + (e.id || '（这条还没有稳定 ID：请先在 Org 里补 :ID: 再处理）'));
    lines.push('- 项目提示：' + (e.projectHint || '（未提供；请先问我这条属于哪个项目）'));
    lines.push('- 原文：');
    lines.push(String(e.text || '').split('\n').map(function (l) { return '    ' + l; }).join('\n'));
    lines.push('');
    lines.push('要求：');
    lines.push('1) 用 pm 生成 proposal（例如 pm proposal create --source-inbox <ID> --change … --risk … --action … --json），只在 proposals.org 落一条；');
    lines.push('2) 不要写 tasks.org、不要创建正式任务、不要派发执行；');
    lines.push('3) 提案里写清：变更（新增/修改/删除的任务）、风险与不确定项、需要我确认的事项；');
    lines.push('4) 完成后告诉我 proposal ID，我会在提案里批准或拒绝。');
    return lines.join('\n');
  }

  function setProposalMode(mode) {
    state.proposalMode = mode;
    var ai = document.getElementById('proposal-ai');
    var manual = document.getElementById('proposal-manual');
    var submit = document.getElementById('proposal-submit');
    if (ai) ai.hidden = mode !== 'ai';
    if (manual) manual.hidden = mode !== 'manual';
    if (submit) submit.textContent = mode === 'ai' ? t('chg.copyInstruction') : t('chg.create');
  }

  function openProposalDialog(entry) {
    state.pendingProposal = { entry: entry };
    var source = document.getElementById('proposal-source');
    if (source) {
      source.innerHTML = '<b>' + esc(t('chg.fromNote')) + '</b>　' +
        (entry.id ? esc(entry.id) : '<span class="chip dashed">' + esc(t('pr.noStableId')) + '</span>') +
        (entry.projectHint ? ' <span class="chip">hint: ' + esc(entry.projectHint) + '</span>' : '') +
        '<br>' + esc(entry.text);
    }
    document.getElementById('ai-instruction').value = buildAiProposalInstruction(entry);
    state.proposalProjectPrefill = entry.projectHint || '';
    refreshProposalProjectField();
    if (state.projects === undefined) loadProjects().then(refreshProposalProjectField);
    document.getElementById('proposal-title-input').value = '';
    document.getElementById('proposal-change').value = '';
    var opSel = document.getElementById('proposal-change-op'); if (opSel) opSel.value = t('chg.opAdd');
    document.getElementById('proposal-risk').value = '';
    document.getElementById('proposal-action').value = '';
    document.getElementById('proposal-status').textContent = '';
    document.getElementById('ai-copy-status').textContent = '';
    setProposalMode('ai');
    document.getElementById('proposal-dialog').showModal();
  }

  /* 提案表单里的项目字段：端点可用 → 下拉（可留空）；不可用 → 手输 + 写明未接入 */
  function refreshProposalProjectField() {
    var wrap = document.getElementById('proposal-project-wrap');
    if (!wrap) return;
    var prefill = state.proposalProjectPrefill || '';
    if (state.projects && state.projects.items) {
      wrap.innerHTML = projectSelectHtml('proposal-project', prefill, { optional: true, aria: t('chg.projectAria') }) +
        '<p class="hint">' + esc(t('chg.projectOptional')) + '<code>:PM_PROJECT:</code>' + esc(t('chg.projectOptionalTail')) + '</p>';
    } else if (state.projects === undefined) {
      wrap.innerHTML = '<input type="text" id="proposal-project" value="' + esc(prefill) + '" placeholder="' + esc(t('ph.projectKey')) + '">' +
        '<p class="hint">' + esc(t('chg.loadingProjects')) + '</p>';
    } else {
      wrap.innerHTML = '<input type="text" id="proposal-project" value="' + esc(prefill) + '" placeholder="' + esc(t('ph.projectKey')) + '">' +
        '<p class="hint">' + esc(t('chg.projectsNotWired')) + '</p>';
    }
  }

  /* 后端错误码 → 键表映射（按 code；未知则回退原码，绝不吞掉信息） */
  function errText(code) {
    if (!code) return '';
    var known = ['REASON_REQUIRED','INVALID_MEMORY_REF','PROPOSAL_EXISTS_FOR_INBOX','CAS_CONFLICT','NOT_FOUND','VALIDATION'];
    return known.indexOf(code) >= 0 ? t('err.' + code) : '';
  }

  function linesOf(value) {
    return String(value || '').split('\n').map(function (s) { return s.trim(); })
      .filter(function (s) { return s.length > 0; });
  }

  function createProposal(entry, fields) {
    return performWrite({
      slot: 'proposal-create|' + entry.id + '|' + (fields.title || ''),
      path: 'proposals',
      revision: null,
      body: {
        sourceInbox: entry.id,
        title: fields.title,
        project: fields.project,
        change: fields.change,
        risk: fields.risk,
        action: fields.action,
        createdBy: 'human'
      },
      label: t('chg.create'),
      ident: entry.id,
      afterOk: function () {
        var dlg = document.getElementById('proposal-dialog');
        if (dlg && dlg.close) dlg.close();
        return load(true, true);
      }
    });
  }

  function submitProposalForm() {
    var status = document.getElementById('proposal-status');
    var entry = (state.pendingProposal || {}).entry;
    if (state.proposalMode !== 'manual') {
      copyText(document.getElementById('ai-instruction').value, 'ai-copy-status');
      setTimeout(function () {
        var dlg = document.getElementById('proposal-dialog');
        if (dlg && dlg.close) dlg.close();
      }, 700);
      return;
    }
    if (!entry || !entry.id) {
      status.className = 'dialog-status err';
      status.textContent = t('sx.noStableId');
      return;
    }
    var change = linesOf(document.getElementById('proposal-change').value);
    /* 操作显式化：下拉所选 op 前缀到每一条（后端 _parse_change 取每行第一个词为 op）⇒ 用户不必输入操作词 */
    var opSel2 = document.getElementById('proposal-change-op');
    var opChosen = opSel2 && opSel2.value ? opSel2.value : t('chg.opAdd');
    change = change.map(function (line) { return opChosen + '：' + line; });
    if (!change.length) {
      status.className = 'dialog-status err';
      status.textContent = t('sx.atLeastOneChange');
      return;
    }
    status.className = 'dialog-status';
    status.textContent = t('task.submitting');
    createProposal(entry, {
      project: document.getElementById('proposal-project').value.trim(),
      title: document.getElementById('proposal-title-input').value.trim(),
      change: change,
      risk: linesOf(document.getElementById('proposal-risk').value),
      action: linesOf(document.getElementById('proposal-action').value)
    }).then(function () {
      if (state.writeError) {
        status.className = 'dialog-status err';
        status.textContent = state.writeError.code + '：' + state.writeError.message;
      } else if (state.conflict) {
        status.className = 'dialog-status err';
        status.textContent = t('sx.conflict409A') + state.conflict.message + t('sx.conflict409B');
      }
    });
  }

  /* task-217：收件箱「保存为项目笔记」的项目字段 —— 与批准/提案下拉**同一套做法**（不新写一套），
     但数据源用 state.data.projects（随看板一起从 GET /ui-pm/cards 来的那份，无需额外端点）：
       · 「（不指定）」+ 已有项目（**名字优先、key 次要**；同名用 key 消歧，与 task-171 同口径）
       · 「其他…（手动输入 key）」逃生口（笔记可能提到**新**项目，能力不削）
       · 列表未就绪 → 如实写「项目列表未就绪（GET /ui-pm/cards 未返回）」+ 保留手动输入，绝不空菜单、不静默交空值 */
  /* 逃生口/占位常量来自 pm-project-select.js（单一实现） */

  /* task-227：折叠摘要按语言拼（模板在 pm-i18n.js）；数字来自同一份 processed（processedSummaryParts）。
     other > 0 时用带 {other} 的模板 —— 否则 N 与 X+Y 对不上（verifier2 实测 4 vs 3）。 */
  function processedSummaryI18n(processed) {
    var p = processedSummaryParts(processed);
    var key = p.other > 0 ? 'mem.processedSummaryOther' : 'mem.processedSummary';
    return format(t(key), { total: p.total, verified: p.verified, deprecated: p.deprecated, other: p.other });
  }

  function noteProjectFieldHtml(prefill) {
    var m = projectFieldModel(state.data && state.data.projects, prefill, { sourceLabel: 'GET /ui-pm/cards' });
    if (m.manualOnly) {
      return '<input type="text" id="op-project" value="' + esc(m.value) + '" placeholder="' + esc(m.placeholder) + '">' +
        '<p class="hint">' + esc(m.note) + '</p>';
    }
    var opts = m.rows.map(function (r) {
      return '<option value="' + esc(r.key) + '"' + (r.selected ? ' selected' : '') + '>' + esc(r.label) +
        (r.secondary !== r.label ? ' <span class="subtle">' + esc(r.secondary) + '</span>' : '') + '</option>';
    }).join('');
    return '<select id="op-project" aria-label="' + esc(t('op.projectSelectAria')) + '">' +
      '<option value=""' + (m.value ? '' : ' selected') + '>' + esc(m.emptyLabel) + '</option>' + opts +
      '<option value="' + PROJECT_MANUAL + '">' + esc(m.manualLabel) + '</option></select>' +
      '<label class="field" id="op-project-manual-wrap" hidden><span>' + esc(t('op.projectKey')) + '</span>' +
      '<input autocomplete="off" type="text" id="op-project-manual" placeholder="' + esc(t('op.projectPlaceholder')) + '"></label>';
  }

  /* 读值：下拉里选了「其他…」就读手动输入；未就绪时读的也是同一个 input（id 一致） */
  function noteProjectValue() {
    var sel = document.getElementById('op-project');
    if (!sel) return '';
    if (sel.tagName === 'SELECT' && sel.value === PROJECT_MANUAL) {
      var man = document.getElementById('op-project-manual');
      return man ? String(man.value || '').trim() : '';
    }
    return String(sel.value || '').trim();
  }

  function wireNoteProjectField() {
    var sel = document.getElementById('op-project');
    var wrap = document.getElementById('op-project-manual-wrap');
    if (!sel || !wrap || sel.tagName !== 'SELECT') return;
    var sync = function () { wrap.hidden = (sel.value !== PROJECT_MANUAL); };
    sel.addEventListener('change', sync);
    sync();
  }

  /* 其它分流动作的二次确认（note / merge / dismiss） */
  function openInboxOpDialog(kind, entry) {
    if (kind === 'note') {
      openConfirmDialog({
        title: t('opd.noteTitle'),
        note: t('opd.noteNote'),
        body: '<div class="src">' + esc(entry.text) + '</div>' +
          '<label class="field"><span>' + esc(t('opd.noteProject')) + '</span>' + noteProjectFieldHtml(entry.projectHint || '') + '</label>' +
          '<p class="hint">' + esc(format(t('opd.noteHintA'), { rev: entry.revision })) +
          esc(t('opd.noteHintB')) + '<code>:PM_PROJECT:</code>' + esc(t('opd.noteHintC')) + '</p>',
        okLabel: t('opd.noteOk'),
        onOk: function () {
          inboxOp('note', entry, { project: noteProjectValue() });   /* body 契约不变（project 字段） */
        }
      });
      wireNoteProjectField();   /* task-217：下拉选「其他…（手动输入 key）」时才显出手动输入框 */
      return;
    }
    if (kind === 'merge') {
      openConfirmDialog({
        title: t('opd.mergeTitle'),
        note: t('opd.mergeNote'),
        body: '<div class="src">' + esc(entry.text) + '</div>' +
          '<label class="field"><span>' + esc(t('opd.mergeField')) + '</span>' +
          '<input type="text" id="op-into" placeholder="' + esc(t('opd.mergePlaceholder')) + '" required aria-required="true"></label>' +
          '<p class="hint">' + esc(t('opd.mergeHint')) + '</p>',
        okLabel: t('opd.mergeOk'),
        onOk: function () {
          var el2 = document.getElementById('op-into');
          var into = el2 ? el2.value.trim() : '';
          if (!into) {
            var st = document.getElementById('confirm-status');
            st.className = 'dialog-status err';
            st.textContent = t('opd.mergeNeedId');
            document.getElementById('confirm-dialog').showModal();
            return;
          }
          inboxOp('merge', entry, { into: into });
        }
      });
      return;
    }
    openConfirmDialog({
      title: t('opd.dismissTitle'),
      note: t('opd.dismissNote'),
      body: '<div class="src">' + esc(entry.text) + '</div>' + reasonField(t('opd.reasonLabel'), t('opd.reasonPlaceholder'), true),
      okLabel: t('opd.dismissOk'),
      onOk: function () {
        var el2 = document.getElementById('confirm-reason');
        var reason = el2 ? el2.value.trim() : '';
        if (!reason) {
          var st = document.getElementById('confirm-status');
          st.className = 'dialog-status err';
          st.textContent = t('opd.dismissNeedReason');
          document.getElementById('confirm-dialog').showModal();
          return;
        }
        inboxOp('dismiss', entry, { reason: reason });
      }
    });
  }

  function writeInbox(action, id, revision, opts) {
    opts = opts || {};
    return performWrite({
      slot: id + '|' + action + '|' + (opts.until || ''),
      path: 'inbox/' + encodeURIComponent(id) + '/' + action,
      revision: revision,
      body: { until: opts.until, reason: opts.reason },
      label: action === 'archive' ? t('inbox.actionArchive') : t('inbox.actionSnooze'),
      text: opts.text, until: opts.until, ident: id,
      afterOk: function () { return load(true, true).then(function () { selectNoteById(id); }); },
      afterConflict: function () { return load(true, true).then(function () { selectNoteById(id); }); }
    });
  }

  /* 通用二次确认弹窗：body 由调用方给（可含输入），确认后执行 onOk。 */
  function openConfirmDialog(cfg) {
    state.pending = { onOk: cfg.onOk };
    document.getElementById('confirm-title').textContent = cfg.title;
    document.getElementById('confirm-note').textContent = cfg.note || '';
    document.getElementById('confirm-body').innerHTML = cfg.body || '';
    document.getElementById('confirm-status').textContent = '';
    document.getElementById('confirm-ok').textContent = cfg.okLabel || t('sx.confirm');
    document.getElementById('confirm-dialog').showModal();
    hardenAutofillNow();   /* 对话框里的表单（理由/标题/key 等）同样关掉表单历史（task-76） */
  }

  /* #8：表单错误必须与字段关联、可被屏读器播报、并把焦点带到出错字段。
     用法：setFieldError(容器, 文案, 控件) / clearFieldError(容器, 控件)。 */
  function setFieldError(container, msg, fieldEl) {
    if (container) {
      container.className = 'dialog-status err';
      container.textContent = msg;
      /* 提交失败用 assertive 播报（polite 对"失败"偏弱）；成功后由 clearFieldError 还原 polite */
      container.setAttribute('role', 'alert');
      container.setAttribute('aria-live', 'assertive');
    }
    if (fieldEl) {
      fieldEl.setAttribute('aria-invalid', 'true');
      if (container && container.id) fieldEl.setAttribute('aria-describedby', container.id);
      try { fieldEl.focus(); } catch (e) {}
    }
  }
  function clearFieldError(container, fieldEl) {
    if (container) {
      container.setAttribute('role', 'status');
      container.setAttribute('aria-live', 'polite');
      container.removeAttribute('aria-describedby');
    }
    if (fieldEl) {
      fieldEl.removeAttribute('aria-invalid');
      fieldEl.removeAttribute('aria-describedby');
    }
  }

  function reasonField(label, placeholder, required) {
    return '<label class="field"><span>' + esc(label) + (required ? esc(t('fld.required')) : esc(t('fld.optional'))) + '</span>' +
      '<input type="text" id="confirm-reason" placeholder="' + esc(placeholder || '') + '"' +
      (required ? ' required aria-required="true"' : '') + '></label>';   /* #17：必填要有语义，不只靠文案 */
  }

  /* 收件箱：归档 / 延期（二次确认） */
  function openConfirm(action, id) {
    var entries = (state.inbox && state.inbox.entries) || [];
    var entry = null;
    for (var i = 0; i < entries.length; i++) { if (entries[i].id === id) { entry = entries[i]; break; } }
    if (!entry) return;
    var can = inboxActionState(entry);
    if (!can.ok) { el.sync.textContent = t('sx.cannotOperatePrefix') + can.why; return; }

    var until = '';
    if (action === 'snooze') {
      var input = el.detailBody.querySelector('#snooze-date');
      until = (input && input.value) ? input.value : tomorrowLocal();
      if (!until) until = tomorrowLocal();
    }
    var body = '<div class="src">' + esc(entry.text) + '</div>' +
      '<div class="kv" style="margin-top:10px">' +
      '<b>' + esc(t('ocf.entry')) + '</b><span>' + esc(entry.id) + '</span>' +
      '<b>' + esc(t('ocf.current')) + '</b><span>' + esc(entry.status) + ' · revision ' + can.revision + '</span>' +
      (action === 'snooze' ? '<b>' + esc(t('ocf.deferUntil')) + '</b><span>' + esc(until) + '</span>' : '') +
      '</div>' +
      reasonField('原因', '例如：重复记录 / 下个迭代再看', false) +
      '<p class="hint">' + esc(t('ocf.revHintPrefix'))  + can.revision  + esc(t('ocf.revHintTail')) + '' +
      '如果文件已被别人改过，服务端返回 409，一个字节都不会写。</p>';

    openConfirmDialog({
      title: action === 'archive' ? '归档这条记录？' : '延期这条记录？',
      note: action === 'archive'
        ? '归档是状态变更，不删除原文；之后可以用 ARCHIVED 状态过滤找回。'
        : '到期前从默认待处理列表隐藏，到期后重新出现；既不是归档，也不是完成。',
      body: body,
      okLabel: action === 'archive' ? '确认归档' : '确认延期',
      onOk: function () {
        var reasonEl = document.getElementById('confirm-reason');
        var reason = reasonEl ? reasonEl.value.trim() : '';
        writeInbox(action, id, can.revision, { until: until, reason: reason, text: entry.text });
      }
    });
  }

  /* ---------- 任务动作（含二次确认） ---------- */

  function allowedTargets(status) { return TASK_TRANSITIONS[status] || []; }

  function openTransition(project, id, from, to, revision, opts) {
    opts = opts || {};
    var label = TASK_STATUS[to] || to;
    var needsReason = opts.reasonRequired === true;
    var body = '<div class="kv">' +
      '<b>' + esc(t('ot.task')) + '</b><span>' + esc(id) + '</span>' +
      '<b>' + esc(t('ot.transition')) + '</b><span>' + esc(TASK_STATUS[from] || from) + ' → <b>' + esc(label) + '</b></span>' +
      '<b>revision</b><span>' + revision + '</span>' +
      '</div>' + (opts.extraHtml || '') +
      reasonField(opts.reasonLabel || '说明', opts.reasonPlaceholder || '为什么要这样流转', needsReason) +
      '<p class="hint">' + esc(t('ot.submitWord')) + 'PATCH /ui-pm/tasks/:id {action:transition, to:' + esc(to) + esc(t('ot.hintMid')) +
      '带 revision ' + revision + '（CAS）与客户端 idempotencyKey。</p>';
    openConfirmDialog({
      title: opts.title || ('把任务流转到「' + label + '」？'),
      note: opts.note || '',
      body: body,
      okLabel: opts.okLabel || ('确认' + label),
      onOk: function () {
        var reasonEl = document.getElementById('confirm-reason');
        var reason = reasonEl ? reasonEl.value.trim() : '';
        if (needsReason && !reason) {
          var st = document.getElementById('confirm-status');
          st.className = 'dialog-status err';
          setFieldError(st, '这个流转必须填写说明', document.getElementById('confirm-reason'));
          document.getElementById('confirm-dialog').showModal();
          return;
        }
        taskTransition(project, id, to, revision, reason);
      }
    });
  }

  function requestTransition(project, id, from, to, revision) {
    if (to === 'DONE') {
      /* task-80：项目页也能验收 —— 弹窗必须「知情」：逐条标准 + 勾选态 + 未勾选数 + 人写/审计说明 */
      var det = (state.taskDetail && state.taskDetail.task) || null;
      var t0 = det || {};
      var list = t0.criteria || [];
      var unchecked = list.filter(function (c) { return !c.done; }).length;
      var total = list.length;
      var critBlock = '<div class="detail-section" style="margin-top:8px;padding-top:8px"><h3>' + esc(t('req.criteriaPrefix'))  +
        (t0.criteriaDone || 0) + '/' + total + '）</h3>' +
        criteriaHtml(t0, false) +
        (total && unchecked ? '<p class="hint"><b>' + esc(t('rv.someUncheckedA')) + unchecked + esc(t('rv.someUncheckedB')) + '</b>' + esc(t('rv.someUncheckedTail')) + '</p>' : '') +
        '<p class="hint">' + esc(t('req.fullViewHint')) + '</p>' +
        '<p class="hint"><b>' + esc(t('req.doneByHuman')) + '</b>' + esc(t('req.logbookPrefix')) + '<code>actor=human</code>' + esc(t('req.logbookMid')) + '<code>:LOGBOOK:</code>' + esc(t('req.logbookTail')) + '</p>' +
        '</div>';
      openTransition(project, id, from, to, revision, {
        title: '验收通过（REVIEW → DONE）？',
        note: '这是终态：确认后任务变成「已完成」。',
        okLabel: '确认验收通过',
        reasonLabel: '验收意见',
        reasonPlaceholder: '写清依据（可引用标准与证据）',
        reasonRequired: false,
        extraHtml: critBlock
      });
      return;
    }
    var reasonRequired = to === 'BLOCKED' || to === 'WAITING' || to === 'CANCELLED';
    openTransition(project, id, from, to, revision, {
      reasonRequired: reasonRequired,
      reasonLabel: reasonRequired ? '原因' : '说明',
      reasonPlaceholder: to === 'BLOCKED' ? '阻塞条件是什么' : '补充说明'
    });
  }

  function openTaskCreate(project) {
    var dlg = document.getElementById('task-dialog');
    /* 项目 key 存在 state 里（不从文本反推）；表单上也留一份便于调试/测试 */
    state.taskCreateProject = String(project || '');
    var form = document.getElementById('task-form');
    if (form && form.setAttribute) form.setAttribute('data-project', state.taskCreateProject);
    document.getElementById('task-project').textContent = project;
    document.getElementById('task-status').textContent = '';
    document.getElementById('task-title').value = '';
    document.getElementById('task-goal').value = '';
    document.getElementById('task-nongoal').value = '';
    document.getElementById('task-criteria').value = '';
    dlg.showModal();
    document.getElementById('task-title').focus();
  }

  /* 新建任务：只有后端确认成功才关对话框；失败（含 409/422）保持打开并显示 code：message。
     校验失败（空标题 / 缺项目 key）**一个请求都不发**。 */
  function createTaskFromDialog(project) {
    var status = document.getElementById('task-status');
    var key = String(project || state.taskCreateProject || '');
    var titleEl = document.getElementById('task-title');
    var title = titleEl ? String(titleEl.value || '').trim() : '';
    if (!key) {
      status.className = 'dialog-status err';
      status.textContent = t('task.missingProject');
      return { ok: false, reason: 'no-project' };
    }
    if (!title) {
      status.className = 'dialog-status err';
      status.textContent = t('task.titleRequired');
      return { ok: false, reason: 'empty-title' };
    }
    var criteria = document.getElementById('task-criteria').value.split('\n')
      .map(function (s) { return s.trim(); }).filter(function (s) { return s.length > 0; });
    status.className = 'dialog-status';
    status.textContent = t('task.submitting');
    return taskCreate(key, title,
      document.getElementById('task-goal').value.trim(),
      document.getElementById('task-nongoal').value.trim(),
      criteria
    ).then(function () {
      var st = document.getElementById('task-status');
      var err = state.writeError || state.conflict;
      if (err) {
        st.className = 'dialog-status err';
        st.textContent = (err.code || 'ERROR') + t('task.errorSep') + (err.message || t('task.writeFailed')) + t('task.keepOpenHint');
        return { ok: false, reason: 'write-error', code: err.code };
      }
      var dlg = document.getElementById('task-dialog');
      if (dlg && dlg.close) dlg.close();
      st.className = 'dialog-status';
      st.textContent = '';
      return { ok: true };
    });
  }

  /* ---------- 记忆动作（verify 只能人点；废弃必须给原因） ---------- */

  /* task-165：丢弃候选走 POST /ui-pm/memory/:id/discard（必填 reason；DEPRECATED 保留历史）。
     幂等重放（changed:false / discarded:false）必须如实说「已经丢弃过」——见 memoryDiscardOutcome。 */
  var DISCARD_DEFAULT_REASON = t('task.discardDefaultReason');

  function openMemoryDiscard(entry) {
    var body = '<div class="src">' + esc(entry.text) + '</div>' +
      '<div class="kv" style="margin-top:10px">' +
      '<b>' + esc(t('memd.kvType')) + '</b><span>' + esc(MEMORY_TYPES[entry.type] || entry.type) + '</span>' +
      '<b>' + esc(t('memd.kvScope')) + '</b><span>' + esc(entry.scope) + '</span>' +
      '<b>revision</b><span>' + esc(String(entry.revision)) + '</span>' +
      '</div>' +
      '<label class="field"><span>' + esc(t('memd.reasonField')) + '</span>' +
      '<input type="text" id="confirm-reason" value="' + esc(DISCARD_DEFAULT_REASON) + '"></label>' +
      '<p class="hint">' + esc(t('memd.hintA')) + '<b>DEPRECATED</b>' + esc(t('memd.hintB')) + '<b>' + esc(t('memd.hintC')) + '</b>' + esc(t('memd.hintD')) +
      '</p>';
    openConfirmDialog({
      title: t('memd.title'),
      note: t('memd.note'),
      body: body,
      okLabel: t('memd.okLabel'),
      onOk: function () {
        var reasonEl = document.getElementById('confirm-reason');
        var reason = reasonEl ? reasonEl.value.trim() : '';
        if (!reason) {
          var box = document.getElementById('confirm-status');
          if (box) { box.className = 'dialog-status err'; box.textContent = t('memd.needReason'); }
          var dlg = document.getElementById('confirm-dialog');
          if (dlg && dlg.showModal) { try { dlg.showModal(); } catch (e) {} }
          return;
        }
        memoryDiscard(entry.id, entry.revision, reason);
      }
    });
  }

  function memoryDiscard(id, revision, reason) {
    return performWrite({
      slot: 'memory-discard|' + id,
      path: 'memory/' + encodeURIComponent(id) + '/discard',
      revision: revision,
      body: { reason: reason },
      label: '丢弃候选', ident: id,
      afterOk: function (b) {
        var outcome = memoryDiscardOutcome(b);
        state.discardNote = { id: id, reason: reason, idempotent: outcome.idempotent, note: outcome.note };
        state.memoryShowDeprecated = true;             /* 丢弃后要看得见 DEPRECATED 状态 */
        state.memorySel = { kind: 'verified', id: id };
        return loadMemory();
      },
      afterConflict: function () { return loadMemory(); }
    });
  }

  /* task-165②：「合并到已有条目」= 人的确认动作：走既有 verify + supersedes（目标可点选） */
  function openMemoryMerge(entry) {
    var all = memoryAllEntries(state.memory).filter(function (x) {
      return x && x.id && String(x.id) !== String(entry.id);
    });
    var body = '<div class="src">' + esc(entry.text) + '</div>' +
      '<p class="hint" style="margin-top:8px">' + esc(t('omm.mergeHint')) + '' +
      '这是<b>人的确认动作</b>（verify 的 actor 固定 human）；AI 没有 verify 路径。</p>' +
      (all.length
        ? '<label class="field"><span>' + esc(t('omm.targetLabel')) + '</span><select id="merge-target">' +
          all.map(function (x) {
            return '<option value="' + esc(x.id) + '">' + esc(memoryMergeOptionText(x)) + '</option>';
          }).join('') + '</select></label>'
        : '<p class="hint">' + esc(t('omm.noTargets')) + '</p>') +
      '<p class="hint">' + esc(t('omm.afterPrefix'))  + esc(memoryShortId(entry.id))  + esc(t('omm.afterSuffix')) + '</p>';
    openConfirmDialog({
      title: '把这条候选合并到已有条目？',
      note: '写入 verified 是人的动作；取代链会同时出现在两条上。',
      body: body,
      okLabel: '确认并入 verified',
      onOk: function () {
        var sel = document.getElementById('merge-target');
        var target = sel ? sel.value : '';
        if (!target) {
          var box = document.getElementById('confirm-status');
          if (box) { box.className = 'dialog-status err'; box.textContent = t('sx.pickSupersedeTarget'); }
          var dlg = document.getElementById('confirm-dialog');
          if (dlg && dlg.showModal) { try { dlg.showModal(); } catch (e) {} }
          return;
        }
        memoryVerify(entry.id, entry.revision, {
          supersedes: target,
          reason: '合并到已有条目 ' + memoryShortId(target)
        });
      }
    });
  }

  function openMemoryVerify(entry) {
    var body = '<div class="src">' + esc(entry.text) + '</div>' +
      '<div class="kv" style="margin-top:10px">' +
      '<b>' + esc(t('omv.typeLabel')) + '</b><span>' + esc(MEMORY_TYPES[entry.type] || entry.type) + '</span>' +
      '<b>' + esc(t('omv.scopeLabel')) + '</b><span>' + esc(entry.scope) + '</span>' +
      '<b>' + esc(t('omv.sourceLabel')) + '</b><span>' + (entry.sources && entry.sources.length ? esc(entry.sources.join('、')) : esc(t('omv.unsourced'))) + '</span>' +
      '<b>revision</b><span>' + entry.revision + '</span>' +
      '</div>' +
      (entry.unsourced ? '<p class="hint">' + esc(t('omv.unsourcedHint')) + '</p>' : '') +
      '<label class="field"><span>' + esc(t('omv.conflictLabel')) + '</span>' +
      '<input type="text" id="confirm-conflict" placeholder="' + esc(t('mem.conflictPlaceholder')) + '"></label>' +
      reasonField('确认说明', '为什么可以进入正式记忆', false);
    openConfirmDialog({
      title: '确认这条候选进入正式记忆？',
      note: 'AI 只能提出候选；写入 verified 是人的动作（actor=human）。',
      body: body,
      okLabel: '确认写入 verified',
      onOk: function () {
        var conflictEl = document.getElementById('confirm-conflict');
        var reasonEl = document.getElementById('confirm-reason');
        memoryVerify(entry.id, entry.revision, {
          conflictWith: conflictEl ? conflictEl.value.trim() : '',
          reason: reasonEl ? reasonEl.value.trim() : ''
        });
      }
    });
  }

  function memoryVerify(id, revision, opts) {
    opts = opts || {};
    return performWrite({
      slot: 'memory-verify|' + id,
      path: 'memory-candidates/' + encodeURIComponent(id) + '/verify',
      revision: revision,
      body: { conflictWith: opts.conflictWith, supersedes: opts.supersedes, reason: opts.reason },
      label: '确认记忆', ident: id,
      afterOk: function () { state.memorySel = { kind: 'verified', id: id }; return loadMemory(); },
      afterConflict: function () { return loadMemory(); }
    });
  }

  function openMemoryDeprecate(entry) {
    var body = '<div class="src">' + esc(entry.text) + '</div>' +
      '<div class="kv" style="margin-top:10px">' +
      '<b>' + esc(t('omd.typeLabel')) + '</b><span>' + esc(MEMORY_TYPES[entry.type] || entry.type) + '</span>' +
      '<b>' + esc(t('omd.scopeLabel')) + '</b><span>' + esc(entry.scope) + '</span>' +
      '<b>' + esc(t('omd.confirmedLabel')) + '</b><span>' + esc(entry.verifiedAt || '—') + ' · ' + esc(entry.verifiedBy || '—') + '</span>' +
      '<b>revision</b><span>' + entry.revision + '</span>' +
      '</div>' +
      reasonField('废弃原因', '例如：已被新方案取代 / 结论有误', true) +
      '<label class="field"><span>' + esc(t('omd.supersededByLabel')) + '</span>' +
      '<input type="text" id="confirm-superseded-by" placeholder="memory-…"></label>' +
      '<p class="hint">' + esc(t('omd.deprecateHint')) + '</p>';
    openConfirmDialog({
      title: '废弃这条正式记忆？',
      note: '破坏性操作：会影响之后 AI 拿到的上下文。',
      body: body,
      okLabel: '确认废弃',
      onOk: function () {
        var reasonEl = document.getElementById('confirm-reason');
        var byEl = document.getElementById('confirm-superseded-by');
        var reason = reasonEl ? reasonEl.value.trim() : '';
        if (!reason) {
          var st = document.getElementById('confirm-status');
          st.className = 'dialog-status err';
          setFieldError(st, '废弃必须填写原因', document.getElementById('confirm-reason'));
          document.getElementById('confirm-dialog').showModal();
          return;
        }
        memoryDeprecate(entry.id, entry.revision, reason, byEl ? byEl.value.trim() : '');
      }
    });
  }

  function memoryDeprecate(id, revision, reason, supersededBy) {
    return performWrite({
      slot: 'memory-deprecate|' + id,
      path: 'memory/' + encodeURIComponent(id) + '/deprecate',
      revision: revision,
      body: { reason: reason, supersededBy: supersededBy },
      label: '废弃记忆', ident: id,
      afterOk: function () { return loadMemory(); },
      afterConflict: function () { return loadMemory(); }
    });
  }

  function taskActionBlock(task, project, allowDone) {
    var canWrite = endpointListed('PATCH', '/ui-pm/tasks/:id');
    var all = allowedTargets(task.status);
    var targets = allowDone ? all : all.filter(function (x) { return x !== 'DONE'; });
    var html = '';
    if (!canWrite) {
      html += '<p class="hint">' + esc(unavailableReason('PATCH', '/ui-pm/tasks/:id') || t('det.patchNotReady')) + '</p>';
    }
    html += '<div style="display:flex;gap:6px;flex-wrap:wrap">';
    if (!targets.length) html += '<span class="hint">' + esc(t('det.noTransitions')) + '</span>';
    /* task-80：「验收通过（已完成）」是首要动作（primary、排最前）；其余合法边保持次要 */
    var ordered = targets.slice().sort(function (a, b) {
      return (a === 'DONE' ? -1 : 0) - (b === 'DONE' ? -1 : 0);
    });
    ordered.forEach(function (to) {
      var isDone = to === 'DONE';
      var label = isDone ? t('det.acceptDone') : ('→ ' + (TASK_STATUS[to] || to));
      html += canWrite
        ? '<button type="button" class="btn small' + (isDone ? ' primary' : '') + '" data-transition-to="' + to + '">' + esc(label) + '</button>'
        : notYet(label, unavailableReason('PATCH', '/ui-pm/tasks/:id') || t('det.notReady'));
    });
    html += '</div>';
    if (targets.indexOf('DONE') >= 0) {
      html += '<p class="hint">' + esc(t('det.acceptHintA')) +
        esc(t('det.acceptHintB')) + '<b>' + esc(t('det.acceptHintC')) + '</b>' + esc(t('det.acceptHintD')) + '</p>';
    }
    html += '<p class="hint">' + esc(t('det.smHintA')) + '<code>ALLOWED_TRANSITIONS</code>' + esc(t('det.smHintB')) +
      esc(t('det.smHintC')) + '</p>';
    return html;
  }

  /* ================= task-125（E3）：验收标准 ↔ 证据 =================
     契约见 内部记录（未随仓库发布）：证据行 `- <crit-id> | kind | result | ref | at | actor | note`，
     读模型给 evidence[]（每项 {criterionId,kind,result,ref,at,actor,note,raw,line}）+ evidenceCount。
     三种情形文案必须**不同**：①这条标准没有证据 →「未挂证据」；②响应整体没有 evidence 字段
     （旧实例）→「本实例未提供证据字段（宿主可能还是旧构建）」；③有证据 → 正常列出。
     所有形态都包在稳定容器 .task-evidence 里（task-115 的教训：夹具等不到元素会产生假红）。 */
  var EVIDENCE_KIND_LABELS = { test: t('det.evKindTest'), build: t('det.evKindBuild'), manual: t('det.evKindManual'), artifact: t('det.evKindArtifact'), review: t('det.evKindReview'), other: t('det.evKindOther') };
  var EVIDENCE_RESULT_LABELS = { pass: t('det.evResultPass'), fail: t('det.evResultFail'), info: t('det.evResultInfo') };

  function evidenceKindText(kind) {
    if (!kind) return '类型：未写入';
    return EVIDENCE_KIND_LABELS[kind] || String(kind);   /* 未知枚举原样显示，不猜 */
  }

  function evidenceResultText(result) {
    if (!result) return '结果：未写入';
    return EVIDENCE_RESULT_LABELS[result] || String(result);
  }

  /* 'missing' = 响应里根本没有 evidence 字段（我们不知道）；'ready' = 有该字段（知道空/非空） */
  /* 参数名不能用 t：会遮蔽模块级 i18n 的 t() ⇒ 一旦函数体里调 t('…') 就 TypeError。
     （2026-10-18 verifier 定位：criterionEvidenceHtml 就是这样，经 window.PMEvidenceHtml 在 cdp.eval 里现形，
       还被门禁误标成「验证器自身」✗。）本函数自己不调用 t()，仍改名防后患。 */
  function taskEvidenceState(task) {
    if (!task || !Object.prototype.hasOwnProperty.call(task, 'evidence')) return 'missing';
    return Array.isArray(task.evidence) ? 'ready' : 'missing';
  }

  /* 一条证据：类型 · 结果 · 引用 · 时间 · actor · 说明（缺字段一律写「未写入」，不猜） */
  function evidenceRowHtml(e) {
    var item = e || {};
    var actor = item.actor ? String(item.actor) : '';
    var resClass = item.result === 'pass' ? 'ok' : (item.result === 'fail' ? 'bad' : 'gray');
    return '<li class="ev-row">' +
      '<span class="chip">' + esc(evidenceKindText(item.kind)) + '</span>' +
      '<span class="chip ' + resClass + '">' + esc(evidenceResultText(item.result)) + '</span>' +
      (item.ref ? '<code class="ev-ref">' + esc(String(item.ref)) + '</code>'
        : '<span class="subtle">' + esc(t('ev.noRef')) + '</span>') +
      '<span class="subtle">' + esc(item.at ? localTime(item.at) : esc(t('ev.noTime'))) + '</span>' +
      '<span class="chip ' + (actor === 'ai' ? 'ai' : 'gray') + '">' +
      esc(actor ? ('actor=' + actor + (actor === 'ai' ? '（AI 挂的，不代替验收）' : '')) : 'actor：未写入') + '</span>' +
      '<span class="ev-note">' + (item.note ? esc(t('ev.notePrefix')) + esc(String(item.note)) : esc(t('ev.noNote'))) + '</span>' +
      '</li>';
  }

  /* 某条标准的证据（缩进在标准下面）。未知 crit-id / 无 id 都不崩，如实说明。 */
  function criterionEvidenceHtml(task, criterion) {
    var evState = taskEvidenceState(task);
    var html = '<div class="task-evidence">';
    if (evState === 'missing') {
      html += '<p class="hint">' + esc(t('ev.noField')) + '</p></div>';
      return html;
    }
    var all = task.evidence || [];
    var cid = (criterion && criterion.id) ? String(criterion.id) : '';
    var mine = all.filter(function (e) { return !!e && !!cid && String(e.criterionId) === cid; });
    if (!mine.length) {
      html += '<p class="hint">' + esc(t('tes.noEvidence2'));
      if (!cid && all.length) html += '（这条标准没有稳定 ID，无法按 ID 归集证据）';
      html += '</p>';
    } else {
      html += '<ul class="ev-list">' + mine.map(evidenceRowHtml).join('') + '</ul>';
      if (mine.some(function (e) { return e && e.actor === 'ai'; })) {
        html += '<p class="hint">' + esc(t('ev.aiHint')) + '</p>';
      }
    }
    html += '</div>';
    return html;
  }

  /* 待验收页「3. 证据」：按标准分组（每条标准仍各自带 .task-evidence 容器） */
  function taskEvidenceSectionHtml(item) {
    if (taskEvidenceState(item) === 'missing') return criterionEvidenceHtml(item, null);
    var list = item.evidence || [];
    var counted = (typeof item.evidenceCount === 'number') ? item.evidenceCount : list.length;
    var html = '<p class="hint">' + esc(t('tes.fromOwnPrefix')) + '<code>' + esc(t('tes.sectionName')) + '</code>' + esc(t('tes.sectionSuffix'))  + list.length +
      ' 条 · evidenceCount ' + counted + '）。AI 自评：未建模，不展示。</p>';
    var crits = item.criteria || [];
    if (!crits.length) {
      html += list.length ? '<div class="task-evidence"><ul class="ev-list">' + list.map(evidenceRowHtml).join('') + '</ul></div>'
        : '<div class="task-evidence"><p class="hint">' + esc(t('tes.noEvidence')) + '</p></div>';
      return html;
    }
    crits.forEach(function (c, i) {
      html += '<div class="ev-crit"><div class="ev-crit-title">' + esc(t('tes.criteriaPrefix'))  + (i + 1) + ' · ' + esc(c.text || '') + '</div>' +
        criterionEvidenceHtml(t, c) + '</div>';
    });
    return html;
  }

  function criteriaHtml(item, canWrite) {
    var list = item.criteria || [];
    if (!list.length) {
      return '<p class="hint">' + esc(t('cr.noCriteria')) + '</p>';
    }
    /* 旧实例：标准没有稳定 ID → 界面如实说明按位置定位（不假装是新路径） */
    var noIds = list.some(function (c) { return !c || !c.id; });
    var idUnsupported = state.criterionIdUnsupported === true;   /* 宿主路由拒绝 criterionId（实测旧构建） */
    var html = '<div>';
    list.forEach(function (c, i) {
      html += '<div class="check-row ' + (c.done ? 'pass' : 'pending') + '">' +
        (canWrite
          ? '<button type="button" class="check-box" data-criterion-index="' + i + '"' +
            (c.id ? ' data-criterion-id="' + esc(String(c.id)) + '"' : '') +
            ' data-criterion-done="' + (c.done ? 'true' : 'false') + '"' +
            ' aria-label="' + (c.done ? t('sr.checkOff') : t('sr.checkOn')) + esc(c.text) + '">' + (c.done ? '✓' : '') + '</button>'
          : '<i aria-hidden="true">' + (c.done ? '✓' : '·') + '</i>') +
        '<span>' + esc(c.text) + '</span>' +
        '<span class="chip">' + (c.done ? t('sr.checked') : t('sr.unchecked')) + '</span></div>' +
        criterionEvidenceHtml(t, c);
    });
    html += '</div>';
    html += '<p class="hint">' + esc(t('cr.checkHint')) +
      (idUnsupported ? '，本实例这条路由<b>不接受 <code>criterionId</code></b>：已退回<b>按位置（index）定位</b>'
        : (noIds ? '，本实例没有稳定 ID：<b>按位置（index）定位</b>' : '，用稳定 <code>criterionId</code> 定位')) +
      '；勾选不等于验收通过 —— 通过要把任务流转到 DONE。</p>';
    return html;
  }

  /* ===== task-174：滚动位置保持（横向 + 各列纵向 + 右栏），单一实现 ===== */

  var CARD_ANCHOR_TTL = 8000;

  function captureScrollState() {
    var snap = { board: null, cols: null, detail: null, project: state.project || '' };
    var boardEl = document.getElementById('project-board');
    if (boardEl && boardEl.querySelectorAll) {
      snap.board = boardEl.scrollLeft || 0;
      snap.cols = {};
      Array.prototype.slice.call(boardEl.querySelectorAll(KANBAN_COL_SELECTOR)).forEach(function (col) {
        var key = col.getAttribute('data-col-key');
        var body = bodyOfColumn(col);
        if (key && body && body.scrollTop) snap.cols[key] = body.scrollTop;
      });
    }
    var ds = detailScroller();
    if (ds) snap.detail = ds.scrollTop || 0;
    return snap;
  }

  /* opts.skipBoard：本轮已经有"横向居中"要落位时，横向交给它、这里只恢复纵向（task-196）。
     默认（不传）行为不变：横向 + 纵向 + 右栏全恢复。纵向**永远**恢复。 */
  function restoreScrollState(snap, opts) {
    if (!snap) return;
    var skipBoard = !!(opts && opts.skipBoard);
    var boardEl = document.getElementById('project-board');
    if (boardEl && boardEl.querySelectorAll) {
      if (snap.board && !skipBoard) { try { boardEl.scrollLeft = snap.board; } catch (e) {} }
      var cols = snap.cols || {};
      Array.prototype.slice.call(boardEl.querySelectorAll(KANBAN_COL_SELECTOR)).forEach(function (col) {
        var key = col.getAttribute('data-col-key');
        var body = bodyOfColumn(col);
        if (key && body && cols[key]) {
          try { body.scrollTop = cols[key]; } catch (e) {}
          /* task-209：<details> 刚重建时列还矮，赋值会被夹到 0（不是我们不恢复）。
             只做"没夹住才补一次"：不等定时器、不无条件延迟；已夹住就不动。 */
          if (body.scrollTop !== cols[key] && typeof requestAnimationFrame === 'function') {
            var want = cols[key], target = body;
            requestAnimationFrame(function () { try { if (target.scrollTop !== want) target.scrollTop = want; } catch (e2) {} });
          }
        }
      });
    }
    if (snap.detail) {
      var ds = detailScroller();
      if (ds) { try { ds.scrollTop = snap.detail; } catch (e) {} }
    }
  }

  /* 右栏真正的滚动容器：CSS 里 .detailbar 是 max-height:100vh + overflow:auto，
     #detail-body 通常不滚 —— 两个都看，取真正能滚的那个（拿不到就返回 null，不猜）。 */
  function detailScroller() {
    var bar = document.querySelector('.detailbar');
    if (bar && (bar.scrollHeight || 0) > (bar.clientHeight || 0)) return bar;
    var body = document.getElementById('detail-body');
    if (body && (body.scrollHeight || 0) > (body.clientHeight || 0)) return body;
    return bar || body || null;
  }

  /* 列内几何：返回 {col, body, main, br, cr}，拿不到就 null */
  function cardBox(id) {
    var boardEl = document.getElementById('project-board');
    if (!boardEl || !boardEl.querySelectorAll) return null;
    var main = boardEl.querySelector('[data-task-id="' + id + '"]');
    if (!main || !main.closest) return null;
    var col = main.closest(KANBAN_COL_SELECTOR);
    var body = bodyOfColumn(col);
    if (!col || !body || !body.getBoundingClientRect || !main.getBoundingClientRect) return null;
    return { col: col, body: body, main: main, br: body.getBoundingClientRect(), cr: main.getBoundingClientRect() };
  }

  /* 卡片完全在列的可视区里吗 */
  function cardFullyVisible(id) {
    var b = cardBox(id);
    if (!b) return false;
    return (b.cr.top >= b.br.top - 1) && (b.cr.bottom <= b.br.bottom + 1);
  }

  /* 只在**该列内**居中（绝不动整页） */
  function ensureCardFullyVisible() {
    var sel = state.task;
    if (!sel || !sel.id) return false;
    var b = cardBox(sel.id);
    if (!b) return false;
    if (b.cr.top >= b.br.top - 1 && b.cr.bottom <= b.br.bottom + 1) return false;   /* 已完整可见 → 保持位置 */
    var h = b.cr.bottom - b.cr.top;
    var delta = (b.cr.top - b.br.top) - (b.br.height - h) / 2;
    try { b.body.scrollTop = Math.max(0, (b.body.scrollTop || 0) + delta); } catch (e) {}
    return true;
  }

  /* 展开/收起：记录卡片顶部相对列可视区顶部的偏移，渲染后把那一位移补回去 */
  function anchorTaskCard(id) {
    var b = cardBox(id);
    if (!b) { state.cardAnchor = null; return false; }
    state.cardAnchor = { id: id, key: b.col.getAttribute('data-col-key'), offset: b.cr.top - b.br.top, at: Date.now() };
    return true;
  }

  function applyCardAnchor() {
    var a = state.cardAnchor;
    if (!a || !a.id) return false;
    state.cardAnchor = null;
    if (a.at && (Date.now() - a.at) > CARD_ANCHOR_TTL) return false;
    var boardEl = document.getElementById('project-board');
    if (!boardEl || !boardEl.querySelectorAll) return false;
    var col = boardEl.querySelector(KANBAN_COL_SELECTOR + '[data-col-key="' + a.key + '"]') || null;
    var body = col ? bodyOfColumn(col) : null;
    var b = cardBox(a.id);
    if (!body || !b) return false;
    var delta = (b.cr.top - b.br.top) - a.offset;   /* 顶部相对位置漂了多少 */
    if (delta) { try { body.scrollTop = Math.max(0, (body.scrollTop || 0) + delta); } catch (e) {} }
    return true;
  }

  /* ===== task-168：批准后的定位/高亮，以及「已创建任务」行 ===== */

  var FOCUS_TASK_TTL = 120000;   /* 批准后可能先在工作台看凭据，再切到项目页才算「看到」→ 给足时间 */

  /* 渲染完成后调用：把新建的卡滚进视口 + 短暂高亮（HTML 重建不会抹掉，因为它每次渲染后重试） */
  function applyFocusTask() {
    var f = state.focusTask;
    if (!f || !f.id) return false;
    if (f.at && (Date.now() - f.at) > FOCUS_TASK_TTL) { state.focusTask = null; return false; }
    if (f.project && state.view === 'projects' && state.project && state.project !== f.project) return false;
    var boardEl = document.getElementById('project-board');
    if (!boardEl || !boardEl.querySelectorAll) return false;
    var hit = boardEl.querySelectorAll('[data-task-id="' + f.id + '"]');
    var main = (hit && hit.length) ? hit[0] : null;
    if (!main) return false;
    var card = (main.closest && main.closest('.task-card')) || main;
    if (typeof card.scrollIntoView === 'function') { try { card.scrollIntoView({ block: 'center' }); } catch (e) {} }
    if (card.classList) {
      card.classList.add('task-flash');
      setTimeout(function () { if (card.classList) card.classList.remove('task-flash'); }, 1800);
    }
    state.focusTask = null;
    if (f.select) { selectTask(f.project || state.project, f.id); }
    return true;
  }

  /* 提案「已创建任务」的候选来源：①批准响应 taskIds（精确）②看板里 sourceInboxId 与提案源随手记相同的任务（如实标注为按来源关联） */
  function proposalLinkedTasks(p) {
    var out = [];
    var approved = state.approvedProposal;
    if (approved && approved.id === (p && p.id) && approved.taskIds && approved.taskIds.length) {
      approved.taskIds.forEach(function (id) { out.push({ id: String(id), exact: true }); });
    } else if (p && p.source_inbox_id && state.board && Array.isArray(state.board.groups)) {
      state.board.groups.forEach(function (g) {
        (g.tasks || []).forEach(function (t) {
          if (t && t.sourceInboxId && String(t.sourceInboxId) === String(p.source_inbox_id)) {
            out.push({ id: String(t.id), exact: false });
          }
        });
      });
    }
    var project = (approved && approved.id === (p && p.id) && approved.project) || (p && p.project) || (state.board && state.board.project) || '';
    out.forEach(function (x) {
      var hit = null;
      if (state.board && Array.isArray(state.board.groups)) {
        state.board.groups.forEach(function (g) {
          (g.tasks || []).forEach(function (t) { if (t && String(t.id) === x.id) hit = t; });
        });
      }
      x.title = hit ? String(hit.title || '') : '';
      x.status = hit ? String(hit.status || '') : '';
      x.project = project;
    });
    return out;
  }

  function proposalCreatedTasksHtml(p) {
    var list = proposalLinkedTasks(p);
    var html = '<div class="detail-section"><h3>' + esc(t('pct.heading')) + '</h3>';
    if (!list.length) {
      html += '<p class="hint">' + esc(t('pct.noIdsA')) + '<code>taskIds</code>' + esc(t('pct.noIdsB')) +
        esc(t('pct.noIdsC')) + '<code>data.taskIds</code>' + esc(t('pct.noIdsD')) + '</p></div>';
      return html;
    }
    list.forEach(function (item) {
      html += '<p class="hint"><button type="button" class="btn small" data-task-jump="' + esc(item.id) + '"' +
        ' data-task-project="' + esc(item.project || '') + '">' + esc(t('pct.jump')) + '</button> ' +
        esc(t('pct.createdPrefix')) + '<b>' + esc(item.title || item.id) + '</b>' + esc(t('pct.statusPrefix')) + '<b>' + esc(item.status || t('pct.notWritten')) + '</b>' + esc(t('pct.statusSuffix')) +
        (item.exact ? '' : '<span class="subtle">' + esc(t('pct.bySource')) + '</span>') +
        '</p>';
    });
    html += '</div>';
    return html;
  }

  function findProposal(id) {
    var known = ((state.proposals && state.proposals.items) || []).filter(function (p) { return p.id === id; })[0];
    if (known) return known;
    var d = state.proposalDetail;
    return (d && d.id === id) ? d.proposal : null;
  }

  function proposalCriteriaHtml(criteria) {
    if (!criteria || !criteria.length) return '';
    return '<div>' + criteria.map(function (c) {
      return '<div class="check-row ' + (c.done ? 'pass' : 'pending') + '"><i aria-hidden="true">' +
        (c.done ? '✓' : '·') + '</i><span>' + esc(c.text) + '</span></div>';
    }).join('') + '</div>';
  }

  /* ================= 提案「修改」（POST /ui-pm/proposals/:id/revise） ================= */

  /* 把计划归一化成可比较的行（diff 预览用；按整行比较，不假装最小编辑距离） */
  function planLinesFor(plan) {
    var lines = [];
    lines.push('标题：' + (String((plan && plan.title) || '').trim() || '（未写标题）'));
    var changes = (plan && plan.changes) || [];
    changes.forEach(function (c) {
      lines.push((c.op || '新增') + '：' + (String(c.title || '').trim() || '（未写标题）'));
      String(c.text || '').split('\n').forEach(function (l) { if (l.trim()) lines.push('  正文：' + l.trim()); });
      (c.criteria || []).forEach(function (x) { if (String(x).trim()) lines.push('  标准：' + String(x).trim()); });
    });
    if (!changes.length) lines.push('（没有任何变更）');
    ((plan && plan.risks) || []).forEach(function (r) { if (String(r).trim()) lines.push('风险：' + String(r).trim()); });
    ((plan && plan.actions) || []).forEach(function (a) { if (String(a).trim()) lines.push('待确认：' + String(a).trim()); });
    return lines;
  }

  function openProposalEditor(p) {
    var srcEntry = findInboxEntry(p.source_inbox_id);
    var srcRev = (srcEntry && typeof srcEntry.revision === 'number') ? srcEntry.revision : null;
    state.proposalEdit = {
      title: p.title || '',
      changes: (p.changes || []).map(function (c) {
        return { op: c.op || '新增', title: c.title || '', text: c.text || '', criteria: (c.criteria || []).slice() };
      }),
      risks: (p.risks || []).slice(),
      actions: (p.actions || []).slice(),
      srcRev: srcRev
    };
    if (!state.proposalEdit.changes.length) state.proposalEdit.changes.push({ op: '新增', title: '', text: '', criteria: [] });
    renderProposalEditor(p);
  }

  function captureProposalEditor() {
    var e = state.proposalEdit;
    if (!e) return;
    var t = document.getElementById('revise-title');
    if (t) e.title = t.value;
    var risks = document.getElementById('revise-risks');
    if (risks) e.risks = linesOf(risks.value);
    var actions = document.getElementById('revise-actions');
    if (actions) e.actions = linesOf(actions.value);
    var next = [];
    e.changes.forEach(function (c, i) {
      var ti = document.getElementById('revise-change-title-' + i);
      var tx = document.getElementById('revise-change-text-' + i);
      var cr = document.getElementById('revise-change-criteria-' + i);
      next.push({
        op: c.op || '新增',
        title: ti ? ti.value : c.title,
        text: tx ? tx.value : c.text,
        criteria: cr ? linesOf(cr.value) : (c.criteria || [])
      });
    });
    e.changes = next;
  }

  function renderProposalEditor(p) {
    var e = state.proposalEdit;
    var srcRevText = e.srcRev === null ? '未返回' : String(e.srcRev);
    var body = '<p class="hint">' + esc(t('rvpe.rehangPrefix')) + '<b>' + esc(t('rpe.sourceRevLabel')) + esc(srcRevText) + '</b>' +
      '（当前计划基于 rev ' + esc(String(p.base_revision)) + '）。保存会写 <code>proposals.org</code> 且 <code>plan rev +1</code>；' +
      '<b>' + esc(t('rvpe.noSideEffect')) + '</b>。</p>' +
      '<label class="field"><span>' + esc(t('rvpe.titleLabel')) + '</span><input type="text" id="revise-title" value="' + esc(e.title) + '"></label>' +
      '<div class="detail-section" style="margin-top:10px;padding-top:8px"><h3>' + esc(t('rvpe.changesHeadingPrefix'))  + e.changes.length + '）</h3>' +
      e.changes.map(function (c, i) {
        return '<div style="border-top:1px dashed var(--pm-border);padding-top:8px;margin-top:8px">' +
          '<div class="task-row"><span class="chip">' + esc(c.op || esc(t('rvpe.opAdd')) + '') + '</span>' +
          '<span class="hint">' + esc(t('rvpe.v1OnlyAdd')) + '</span>' +
          '<button type="button" class="btn small danger" data-revise-del="' + i + '" style="margin-left:auto">' + esc(t('rvpe.removeRow')) + '</button></div>' +
          '<label class="field"><span>' + esc(t('rvpe.changeTitle')) + '</span><input type="text" id="revise-change-title-' + i + '" value="' + esc(c.title || '') + '" required aria-required="true"></label>' +
          '<label class="field"><span>' + esc(t('rvpe.changeBody')) + '</span><textarea id="revise-change-text-' + i + '" rows="2">' + esc(c.text || '') + '</textarea></label>' +
          '<label class="field"><span>' + esc(t('rvpe.changeCriteria')) + '</span><textarea id="revise-change-criteria-' + i + '" rows="2">' + esc((c.criteria || []).join('\n')) + '</textarea></label>' +
          '</div>';
      }).join('') +
      '<div class="op-row" style="margin-top:8px"><button type="button" class="btn small" data-revise-add="1">' + esc(t('rvpe.addChange')) + '</button></div></div>' +
      '<label class="field"><span>' + esc(t('rvpe.risksLabel')) + '</span><textarea id="revise-risks" rows="2">' + esc((e.risks || []).join('\n')) + '</textarea></label>' +
      '<label class="field"><span>' + esc(t('rvpe.actionsLabel')) + '</span><textarea id="revise-actions" rows="2">' + esc((e.actions || []).join('\n')) + '</textarea></label>';
    openConfirmDialog({
      title: '修改提案计划…',
      note: '改的是计划内容；保存前先给你看 diff。',
      body: body,
      okLabel: '下一步：预览 diff',   /* 提案修改流属它自己的批次（B?），此串不归 B1E ⇒ 保持原样 */
      onOk: function () {
        captureProposalEditor();
        var fail = function (msg) {
          var st = document.getElementById('confirm-status');
          st.className = 'dialog-status err';
          st.textContent = msg;
          document.getElementById('confirm-dialog').showModal();
        };
        var filled = e.changes.filter(function (c) { return String(c.title || '').trim().length > 0; });
        if (!e.changes.length || !filled.length) {
          fail('至少要有一条带标题的变更：空数组（清空计划）会被后端拒绝 —— pm 的语义是「不传则保持」，想清空也得给出至少一条。');
          return;
        }
        if (filled.length !== e.changes.length) {
          fail('有 ' + (e.changes.length - filled.length) + ' 条变更没写标题：请补齐或删掉它们。');
          return;
        }
        openRevisePreview(p);
      }
    });
  }

  function openRevisePreview(p) {
    var e = state.proposalEdit;
    var draft = {
      title: String(e.title || '').trim(),
      changes: e.changes.map(function (c) {
        return {
          op: c.op || '新增', title: String(c.title || '').trim(), text: String(c.text || '').trim(),
          criteria: (c.criteria || []).map(function (x) { return String(x).trim(); }).filter(function (x) { return x.length > 0; })
        };
      }),
      risks: (e.risks || []).slice(),
      actions: (e.actions || []).slice()
    };
    var oldLines = planLinesFor(p);
    var newLines = planLinesFor(draft);
    var oldSet = {}, newSet = {};
    oldLines.forEach(function (l) { oldSet[l] = true; });
    newLines.forEach(function (l) { newSet[l] = true; });
    var column = function (lines, other) {
      return lines.map(function (l) {
        var same = !!other[l];
        return '<div class="diff-line' + (same ? '' : ' diff-changed') + '">' + (same ? '\u00a0\u00a0' : '\u00b1\u00a0') + esc(l) + '</div>';
      }).join('');
    };
    var srcRevText = e.srcRev === null ? '未返回' : String(e.srcRev);
    var body = '<div class="grid" style="grid-template-columns:1fr 1fr;gap:10px">' +
      '<div><p class="subtitle">' + esc(t('orp.oldPrefix'))  + esc(String(p.base_revision)) + '）</p>' + column(oldLines, newSet) + '</div>' +
      '<div><p class="subtitle">' + esc(t('orp.newPrefix'))  + esc(srcRevText) + '）</p>' + column(newLines, oldSet) + '</div></div>' +
      '<p class="hint">' + esc(t('orp.diffHint')) + '</p>' +
      '<div class="notice">' + esc(t('orp.saveNoticePrefix')) + '<code>proposals.org</code>、<code>plan rev +1</code>' + esc(t('orp.saveNoticeTail')) + '' +
      (draft.title ? '' : '；标题留空 = 不修改标题') +
      ((draft.risks.length || draft.actions.length) ? '' : '；风险/待确认留空 = 保持原样') + '。</div>';
    openConfirmDialog({
      title: '确认重挂到源最新 revision？',
      note: '保存后提案基于源的最新 revision，STALE 检查随之解除。',
      body: body,
      okLabel: '确认重挂并保存',
      onOk: function () { reviseProposal(p, draft); }
    });
  }

  function reviseProposal(p, draft) {
    var body = {};
    /* changes 绝不能是空数组：空数组 = 清空计划，后端会 400；不传才是「保持」 */
    body.changes = draft.changes;
    if (draft.title) body.title = draft.title;
    if (draft.risks.length) body.risks = draft.risks;
    if (draft.actions.length) body.actions = draft.actions;
    return performWrite({
      slot: 'proposal-revise|' + p.id,
      path: 'proposals/' + encodeURIComponent(p.id) + '/revise',
      revision: p.revision,
      body: body,
      label: '修改提案计划', ident: p.id,
      afterOk: function () { return Promise.all([loadProposals(), loadProposalDetail(p.id), load(true, true)]); },
      afterConflict: function () { return Promise.all([loadProposals(), loadProposalDetail(p.id)]); }
    });
  }

  function stalePlanPanel(p) {
    var w = state.writeError;
    if (!w || w.code !== 'STALE_PLAN') return '';
    var b = w.body || {};
    var base = b.baseRevision !== undefined ? b.baseRevision : p.base_revision;
    var cur = b.currentRevision !== undefined ? b.currentRevision : '—';
    var html = '<div class="detail-section"><h3>' + esc(t('spp.heading')) + '</h3><div class="conflict-box">' +
      '<p>' + esc(w.message || esc(t('spp.note')) + '') + '</p>' +
      '<div class="kv" style="margin-top:9px">' +
      '<b>' + esc(t('spp.basedOn')) + '</b><span>' + esc(t('spp.sourceRevisionWord'))  + esc(String(base)) + '</span>' +
      '<b>' + esc(t('spp.sourceNow')) + '</b><span>' + esc(t('wr.revisionWord2'))  + esc(String(cur)) + '</span>' +
      '</div>';
    if (!state.staleRetried) {
      var canReviseStale = endpointListed('POST', '/ui-pm/proposals/:id/revise');
      html += '<p class="hint">' + esc(t('spp.twoPaths')) + '<b>' + esc(t('spp.reviseWord')) + '</b>' + esc(t('spp.reviseHint')) + '' +
        '或<b>带着风险继续批准</b>（在不知道源记录最新内容的情况下创建正式任务）。</p>' +
        '<div class="op-row">' +
        (canReviseStale
          ? '<button type="button" class="btn primary" data-proposal-revise="' + esc(p.id) + '">' + esc(t('spp.reviseBtnPrefix'))  + esc(String(cur)) + '）</button>'
          : notYet('修改（重挂）', missingEndpointText('POST', '/ui-pm/proposals/:id/revise'))) +
        '<button type="button" class="btn" data-proposal-approve-stale="' + esc(p.id) + '">' + esc(t('spp.approveAnyway')) + '</button>' +
        '</div>';
    } else {
      html += '<p class="hint">' + esc(t('spp.stillRejected')) + '<b>' + esc(t('spp.routeNoForward')) + '<code>--allow-stale</code></b>' +
        '（capabilities 里这条 approve 只声明了 <code>project</code>）。' +
        '请在 DSH 会话里执行下面这条命令，或先「拒绝」再重新生成提案。</p>' +
        '<div class="src">pm --config ' + esc(t('spp.cmdToml')) + ' proposal approve ' + esc(p.id) +
        ' --expected-revision ' + esc(String(p.revision)) + ' --allow-stale --json</div>' +
        '<div class="op-row"><button type="button" class="btn small" data-copy-stale="' + esc(p.id) + '">' + esc(t('spp.copyCommand')) + '</button>' +
        '<span class="hint" id="stale-copy-status" role="status" aria-live="polite"></span></div>';
    }
    html += '</div></div>';
    return html;
  }

  function detailForProposal() {
    var id = state.proposal;
    if (!id) return null;
    var d = state.proposalDetail;
    if (!d || d.id !== id) return '<div class="empty">' + esc(t('dfp.loading')) + '</div>';
    if (d.error) return '<div class="empty">' + esc(t('det.loadFailed')) + esc(d.error) + '</div>';
    var p = d.proposal;
    var canApprove = endpointListed('POST', '/ui-pm/proposals/:id/approve');
    var canReject = endpointListed('POST', '/ui-pm/proposals/:id/reject');
    var changes = p.changes || [];

    var html = '<div class="detail-section"><h3>' + esc(t('dfp.heading')) + '</h3>' +
      '<p style="font-weight:700;line-height:1.5">' + esc(p.title || esc(t('dfp.untitled')) + '') + '</p>' +
      '<div class="kv" style="margin-top:9px">' +
      '<b>' + esc(t('dfp.status')) + '</b><span><span class="badge amber">' + esc(p.status) + '</span></span>' +
      '<b>' + esc(t('dfp.projectLabel')) + '</b><span>' + (p.project ? esc(p.project) : '<span class="chip dashed">' + esc(t('dfp.projectUnset')) + '</span>') + '</span>' +
      '<b>' + esc(t('dfp.proposalRev')) + '</b><span>' + esc(String(p.revision)) + '</span>' +
      '<b>plan rev</b><span>' + esc(String(p.plan_revision)) + esc(format(t('dfp.revFieldFmt'), { x: ':PM_PLAN_REVISION:' })) + '</span>' +
      '<b>' + esc(t('dfp.basedOnRev')) + '</b><span>' + esc(String(p.base_revision)) + esc(format(t('dfp.revFieldFmt'), { x: ':PM_BASE_REVISION:' })) + '</span>' +
      '<b>' + esc(t('dfp.generatedBy')) + '</b><span>' + esc(p.created_by || '—') + '</span>' +
      '<b>' + esc(t('dfp.position')) + '</b><span>' + esc(format(t('dfp.lineFmt'), { n: p.line })) + '</span>' +
      '</div></div>';

    html += proposalCreatedTasksHtml(p);

    var srcEntry = findInboxEntry(p.source_inbox_id);
    html += '<div class="detail-section"><h3>' + esc(t('dfp.sourceNote')) + '</h3><div class="kv">' +
      '<b>' + esc(t('dfp.entryId')) + '</b><span>' + esc(p.source_inbox_id || '—') + '</span>' +
      '<b>' + esc(t('dfp.rawText')) + '</b><span>' + (srcEntry ? esc(srcEntry.text) : '<span class="subtle">' + esc(t('dfp.entryGone')) + '</span>') + '</span>' +
      '</div>' +
      (p.source_inbox_id ? '<button type="button" class="btn small" style="margin-top:9px" data-open-inbox="' +
        esc(p.source_inbox_id) + '">在收件箱里查看</button>' : '') + '</div>';

    html += '<div class="detail-section"><h3>' + esc(t('dfp.changesPrefix')) + changes.length + esc(t('dfp.closeParen')) + '</h3>';
    if (!changes.length) html += '<p class="subtle">' + esc(t('dfp.noChanges')) + '</p>';
    changes.forEach(function (c) {
      html += '<div class="ev" style="margin-bottom:8px">' +
        '<strong>' + esc(c.op || t('dfp.changeWord')) + esc(t('wr.colon')) + esc(c.title || c.text || '') + '</strong>' +
        '<span class="subtitle">' + esc(t('dfp.taskWord'))  + esc(c.task_id || esc(t('dfp.createdOnApprove')) + '') + '</span>' +
        proposalCriteriaHtml(c.criteria) + '</div>';
    });
    html += '<p class="hint">' + esc(t('dfp.onlyAddHint')) + '' +
      '不会静默忽略。</p></div>';

    html += '<div class="detail-section"><h3>' + esc(t('dfp.risksHeading')) + '</h3>' +
      '<p class="subtitle">' + esc(t('dfp.risks')) + '</p>' +
      ((p.risks || []).length ? '<ul class="bullets">' + p.risks.map(function (r) { return '<li>' + esc(r) + '</li>'; }).join('') + '</ul>' : '<p class="hint">' + esc(t('dfp.noneWord')) + '</p>') +
      '<p class="subtitle">' + esc(t('dfp.actionsHeading')) + '</p>' +
      ((p.actions || []).length ? '<ul class="bullets">' + p.actions.map(function (a) { return '<li>' + esc(a) + '</li>'; }).join('') + '</ul>' : '<p class="hint">' + esc(t('dfp.noneWord4')) + '</p>') +
      '</div>';

    html += '<div class="detail-section"><h3>' + esc(t('dfp.actions')) + '</h3><div style="display:flex;gap:6px;flex-wrap:wrap">';
    if (p.status !== 'PENDING') {
      html += '<span class="hint">' + esc(t('dfp.currentStatusPrefix'))  + esc(p.status)  + esc(t('dfp.cannotRepeat')) + '</span>' +
        notYet('修改', '提案已是终态（' + p.status + '），不能再改计划');
    } else {
      html += canApprove
        ? '<button type="button" class="btn primary" data-proposal-approve="' + esc(p.id) + '">' + esc(t('dfp.approveBtn')) + '</button>'
        : notYet('批准计划', missingEndpointText('POST', '/ui-pm/proposals/:id/approve'));
      html += canReject
        ? '<button type="button" class="btn" data-proposal-reject="' + esc(p.id) + '">' + esc(t('dfp.rejectBtn')) + '</button>'
        : notYet('拒绝', missingEndpointText('POST', '/ui-pm/proposals/:id/reject'));
      var canRevise = endpointListed('POST', '/ui-pm/proposals/:id/revise');
      html += canRevise
        ? '<button type="button" class="btn" data-proposal-revise="' + esc(p.id) + '">' + esc(t('dfp.reviseBtn')) + '</button>'
        : notYet('修改', missingEndpointText('POST', '/ui-pm/proposals/:id/revise'));
    }
    html += '</div><p class="hint">批准会在 <b>' + esc(p.project || '所选项目') + '</b> 创建 ' + changes.length +
      ' 条正式任务，并把源随手记标记为「任务已创建（TASK_CREATED）」；拒绝不改变正式任务。</p></div>';

    /* 422 PROJECT_NOT_FOUND：不能只显示错误文本 —— 给一键「创建后重试」（同一两段式） */
    var w = state.writeError;
    var errBody = (w && w.body) ? w.body : null;
    var errInner = (errBody && errBody.error) ? errBody.error : {};
    var errCode = (w && w.code) || errInner.code || '';
    if (w && errCode === 'PROJECT_NOT_FOUND') {
      var missingKey = (errBody && (errBody.project || errBody.key)) || errInner.project || p.project || '（未知）';
      var errHint = (errBody && errBody.hint) || errInner.hint || '';
      html += '<div class="detail-section"><h3>' + esc(t('dfp.noProjectDir')) + '</h3>' +
        '<div class="error-box"><b>' + esc(errCode) + esc(t('wr.colon')) + esc(w.message) + '</b>' +
        (errHint ? '<p class="hint">' + esc(errHint) + '</p>' : '') +
        '<p class="hint">' + esc(t('dfp.approveNeeds')) + '<code>projects/proj-' + esc(missingKey) + '/</code>' + esc(t('dfp.existsSuffix')) + '' +
        '可以先创建它再重试（幂等，两步都会给出结果）。</p></div>' +
        '<div class="op-row"><button type="button" class="btn primary" data-project-retry="' + esc(missingKey) + '">' +
        '创建 projects/proj-' + esc(missingKey) + ' 后重试</button></div></div>';
    }

    /* 两段式第一步结果（POST /ui-pm/projects）：该命令没有 revision/审计字段，如实说明 */
    if (state.projectCreate) {
      var pc = state.projectCreate;
      html += '<div class="detail-section"><h3>' + esc(t('dfp.step1Heading')) + '</h3>';
      if (pc.error) {
        html += '<div class="error-box"><b>' + esc(t('dfp.createFailed')) + '</b><p class="hint">' + esc(pc.error) + '</p></div>';
      } else {
        var pd = pc.data || {};
        html += '<div class="kv">' +
          '<b>key</b><span>' + esc(pd.key || pc.key) + '</span>' +
          '<b>id</b><span>' + esc(pd.id || '—') + '</span>' +
          '<b>' + esc(t('dfp.pathLabel')) + '</b><span>' + esc(pd.path || '—') + '</span>' +
          '<b>' + esc(t('dfp.resultLabel')) + '</b><span>' + (pd.created ? esc(t('dfp.resultCreated'))  : (pd.exists ? esc(t('dfp.resultExisted'))  : esc(t('dfp.resultUnknown')) + '')) + '</span>' +
          '<b>' + esc(t('dfp.writtenFiles')) + '</b><span>' + ((pd.files || []).length ? esc((pd.files || []).join(t('wr.listSep'))) : '—') + '</span>' +
          '<b>' + esc(t('dfp.observedAt')) + '</b><span>' + esc(pc.at ? localTime(pc.at) : '—') + '</span>' +
          '</div><p class="hint">project create 的响应没有 revision / auditEventId（命令本身就没有这两个字段），' +
          '所以这一步没有 §5 凭据；批准那一步的 §5 凭据在下面。</p>';
      }
      html += '</div>';
    }

    html += stalePlanPanel(p);
    html += writeResultHtml();
    return html;
  }

  /* 批准 / 拒绝的二次确认 */
  /* ================= 项目下拉与「先建目录再批准」两段式 ================= */

  var NEW_PROJECT = '__new__';
  var PROJECT_KEY_RE = /^[A-Za-z0-9._-]+$/;

  function loadProjects() {
    if (!endpointListed('GET', '/ui-pm/projects')) {
      state.projects = null;   /* 端点缺失：调用方回落手输，不伪造选项 */
      return Promise.resolve();
    }
    return httpJson(api('projects')).then(function (x) {
      if (x.ok && x.body.ok === true) state.projects = { items: (x.body.data || {}).projects || [], error: null };
      else state.projects = { items: [], error: apiErrText(x) };
    }).catch(function (err) {
      state.projects = { items: [], error: err.message || String(err) };
    });
  }

  function projectOptionByKey(key) {
    if (!state.projects || !state.projects.items) return null;
    var hit = null;
    state.projects.items.forEach(function (p) { if (p.key === key) hit = p; });
    return hit;
  }

  /* 排序：库内项目（inLibrary=true）按 key 优先 → 仅投影项目（标注「未建库目录」）→ 「＋ 新建项目…」 */
  function projectOptionList() {
    var items = (state.projects && state.projects.items) ? state.projects.items.slice() : [];
    var byKey = function (a, b) { return String(a.key) < String(b.key) ? -1 : (String(a.key) > String(b.key) ? 1 : 0); };
    var inLib = items.filter(function (p) { return p.inLibrary === true; }).sort(byKey);
    var outLib = items.filter(function (p) { return p.inLibrary !== true; }).sort(byKey);
    return inLib.concat(outLib);
  }

  function projectSelectHtml(id, selected, opts) {
    opts = opts || {};
    var items = projectOptionList();
    /* task-217：选项渲染走同一模块（**名字优先、key 次要**；同名用 key 消歧）；逃生口「＋ 新建项目…」保留 */
    var model = projectFieldModel(items, selected, { withNewProject: true, optional: opts.optional !== false, sourceLabel: 'GET /ui-pm/projects' });
    var html = '<select id="' + esc(id) + '"' + (opts.aria ? ' aria-label="' + esc(opts.aria) + '"' : '') + '>';
    if (model.optional) html += '<option value=""' + ((!selected) ? ' selected' : '') + '>' + esc(t('psh.noProject')) + '</option>';
    else if (!selected) html += '<option value="" selected>' + esc(t('apf.pickProject2')) + '</option>';
    model.rows.forEach(function (r) {
      html += '<option value="' + esc(r.key) + '"' + (r.selected ? ' selected' : '') + '>' +
        esc(r.label) + (r.inLibrary === true ? '' : ' · 未建库目录') + '</option>';
    });
    html += '<option value="' + PROJECT_NEW + '"' + (selected === PROJECT_NEW ? ' selected' : '') + '>' + esc(t('apf.newProject2')) + '</option>';
    html += '</select>';
    return html;
  }

  function projectManualHtml(value, note) {
    return '<input type="text" id="approve-project" value="' + esc(value || '') + '" placeholder="' + esc(t('ph.projectKey')) + '">' +
      '<p class="hint">' + note + '</p>';
  }

  /* 批准对话框里的项目字段（统一在这里重建，方便列表加载完刷新） */
  function approveProjectFieldHtml(prefill) {
    if (state.projects === undefined) {
      return projectManualHtml(prefill, t('chg.loadingProjects'));
    }
    if (state.projects === null) {
      return projectManualHtml(prefill, '项目列表未接入，请手动输入 key（本实例未提供 ' + 'GET /ui-pm/projects' + '）。');
    }
    return '<select id="approve-project-select" aria-label="' + esc(t('apv.projectAria')) + '">' +
      (function () {
        var items = projectOptionList();
        var html = (prefill ? '' : '<option value="" selected>' + esc(t('apf.pickProject')) + '</option>');
        items.forEach(function (p) {
          html += '<option value="' + esc(p.key) + '"' + (p.key === prefill ? ' selected' : '') + '>' +
            esc(p.key) + (p.title && p.title !== p.key ? '（' + esc(p.title) + '）' : '') +
            (p.inLibrary === true ? '' : ' · 未建库目录') + '</option>';
        });
        html += '<option value="' + NEW_PROJECT + '">' + esc(t('apf.newProject')) + '</option>';
        return html;
      })() + '</select>' +
      '<label class="field" id="approve-new-wrap" hidden><span>' + esc(t('apf.newKeyLabel')) + '</span>' +
      '<input type="text" id="approve-project-new" placeholder="' + esc(t('ph.projectKey')) + '"></label>' +
      '<label class="field" id="approve-new-title-wrap" hidden><span>' + esc(t('apf.newTitleLabel')) + '</span>' +
      '<input type="text" id="approve-project-title" placeholder="' + esc(t('ph.projectTitle')) + '"></label>' +
      '<p class="hint" id="approve-project-hint"></p>';
  }

  function refreshApproveProjectField() {
    var wrap = document.getElementById('approve-project-field');
    if (!wrap) return;
    var prefill = state.approvePrefill || '';
    wrap.innerHTML = wrap.innerHTML.replace(/[\s\S]*/, '');   /* 清空 */
    wrap.innerHTML = approveProjectFieldHtml(prefill);
    syncApproveProjectUI();
  }

  /* 选择变化：显示/隐藏新 key 输入、改主按钮文案、给提示 */
  function syncApproveProjectUI() {
    var sel = document.getElementById('approve-project-select');
    var wrapNew = document.getElementById('approve-new-wrap');
    var wrapTitle = document.getElementById('approve-new-title-wrap');
    var hint = document.getElementById('approve-project-hint');
    var ok = document.getElementById('confirm-ok');
    if (sel) {
      var v = sel.value;
      var isNew = v === NEW_PROJECT;
      var hit = projectOptionByKey(v);
      var notInLib = !!(hit && hit.inLibrary !== true);
      if (wrapNew) wrapNew.hidden = !isNew;
      if (wrapTitle) wrapTitle.hidden = !isNew;
      if (hint) {
        hint.textContent = isNew
          ? '会先创建 projects/proj-<key>/ 目录（幂等），再批准；第一步失败绝不会批准。'
          : (notInLib ? '该项目还没有库目录（inLibrary=false），将先创建再批准。' : '');
      }
      if (ok) ok.textContent = (isNew || notInLib) ? t('sx.createAndApprove') : (state.approveOkLabel || t('sx.confirmApprove'));
    } else if (ok) {
      ok.textContent = state.approveOkLabel || t('sx.confirmApprove');
    }
  }

  /* 新建项目目录：POST /ui-pm/projects（幂等）。该命令没有 revision / 审计字段，所以不套 §5。 */
  function createProject(key, title) {
    if (!endpointListed('POST', '/ui-pm/projects')) {
      return Promise.resolve({ ok: false, error: missingEndpointText('POST', '/ui-pm/projects') });
    }
    return httpJson(api('projects'), {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ key: key, title: title || key })
    }).then(function (x) {
      if (x.ok && x.body.ok === true) return { ok: true, data: x.body.data || {} };
      var e = apiError(x);
      return { ok: false, error: e.code + '：' + e.message };
    }).catch(function (err) { return { ok: false, error: err.message || String(err) }; });
  }

  /* task-234：新建项目对话框。诚实三态：
       · key 非法（PROJECT_KEY_RE）⇒ 行内错误 + **不发任何请求**（onOk 里先校验再发；输入时也即时提示）；
       · created === false ⇒「已存在，未改动」（**绝不写"创建成功"**）；
       · 其它失败 ⇒ 原样显示 error（含端点缺失的 missingEndpointText）。 */
  function createProjectDialogBody(key, title, errText) {
    return '<label class="field"><span>' + esc(t('proj.keyField')) + '</span>' +
      '<input type="text" id="new-project-key" autocomplete="off" placeholder="' + esc(t('proj.keyPlaceholder')) + '" value="' + esc(key || '') + '"></label>' +
      '<label class="field"><span>' + esc(t('proj.titleField')) + '</span>' +
      '<input type="text" id="new-project-title" autocomplete="off" placeholder="' + esc(t('proj.titlePlaceholder')) + '" value="' + esc(title || '') + '"></label>' +
      '<p class="hint" id="new-project-err"' + (errText ? '' : ' hidden') + '>' + esc(errText || '') + '</p>' +
      '<p class="hint">' + esc(format(t('proj.keyRuleHint'), { re: '^[A-Za-z0-9._-]+$' })) +
      esc(t('proj.createHint')) + '</p>';
  }

  function openCreateProjectDialog(opts) {
    var o = opts || {};
    openConfirmDialog({
      title: t('proj.createDialogTitle'),
      note: t('proj.createDialogNote'),
      body: createProjectDialogBody(o.key, o.title, o.err),
      okLabel: t('proj.createOkLabel'),
      onOk: function () {
        var kEl = document.getElementById('new-project-key');
        var tEl = document.getElementById('new-project-title');
        var key = kEl ? String(kEl.value || '').trim() : '';
        var title = tEl ? String(tEl.value || '').trim() : '';
        if (!PROJECT_KEY_RE.test(key)) {
          /* 行内错误 + 重新打开（confirm 提交时会先关闭）⇒ **全程不发请求** ✓ */
          openCreateProjectDialog({ key: key, title: title, err: format(t('proj.keyInvalid'), { rule: t('proj.keyRule'), v: (key || t('proj.keyEmpty')) }) });
          return;
        }
        createProject(key, title).then(function (res) {
          if (!res.ok) { openCreateProjectDialog({ key: key, title: title, err: t('proj.createFailed') + res.error }); return; }
          var d = res.data || {};
          /* 结果写进**页面上的常驻提示**（state.newProjectNote）：
             不能只写 el.sync —— refreshAll(true) 会立刻把 el.sync 覆盖成「强制重扫中…」⇒ 用户看不到结果（实测踩到）。 */
          if (d.created === true) {
            state.newProjectNote = { kind: 'ok', text: format(t('proj.createdOk'), { path: (d.path || ('projects/proj-' + key)) }) };
            loadProjects();
            refreshAll(true);   /* 列表刷新：新项目马上出现在 Projects 页 */
            return;
          }
          /* created === false：已存在 —— 如实说，绝不写"创建成功" */
          state.newProjectNote = { kind: 'exists', text: format(t('proj.existsUnchanged'), { path: (d.path || ('projects/proj-' + key)) }) };
          loadProjects();
          refreshAll(true);
        });
      }
    });
    var kIn = document.getElementById('new-project-key');
    if (kIn) kIn.addEventListener('input', function () {
      var e = document.getElementById('new-project-err');
      if (!e) return;
      var v = String(kIn.value || '').trim();
      if (v && !PROJECT_KEY_RE.test(v)) { e.hidden = false; e.textContent = t('proj.keyRule'); }
      else { e.hidden = true; e.textContent = ''; }
    });
  }

  /* 两段式：先创建目录，成功才批准；第一步失败直接中止。
     task-96 明确**不拆**：本函数碰 document（confirm-status/confirm-dialog）与 state，不是纯叶子；
     它对 harness 的验证走 CDP/真机断言，而不是 import —— 硬拆只会污染纯模块或要塞 DOM 桩。 */
  function createProjectThenApprove(p, key, allowStale, title) {
    var status = document.getElementById('confirm-status');
    var dlg = document.getElementById('confirm-dialog');
    if (status) { status.className = 'dialog-status'; status.textContent = t('sx.step1Creating') + key + ' …'; }
    if (dlg && dlg.showModal) dlg.showModal();
    state.projectCreate = null;
    return createProject(key, title).then(function (res) {
      if (!res.ok) {
        state.projectCreate = { key: key, error: res.error, at: new Date().toISOString() };
        if (status) { status.className = 'dialog-status err'; status.textContent = t('sx.step1Failed') + res.error; }
        render();
        return;
      }
      state.projectCreate = { key: key, data: res.data, at: new Date().toISOString() };
      if (status) { status.className = 'dialog-status'; status.textContent = t('sx.step1DoneApproving'); }
      if (res.data && res.data.created) loadProjects();   /* 新目录进下拉，下次不用再建 */
      approveProposal(p, key, allowStale);
    });
  }

  function openApproveProposal(p, allowStale) {
    var needsProject = !p.project;
    var srcEntry = findInboxEntry(p.source_inbox_id);
    var prefill = (srcEntry && srcEntry.projectHint) ? srcEntry.projectHint : '';
    state.approvePrefill = prefill;
    state.approveOkLabel = allowStale ? '确认批准（知风险）' : '确认批准';
    if (needsProject && state.projects === undefined) loadProjects().then(function () { refreshApproveProjectField(); });
    var body = '<div class="src">' + esc(p.title || p.id) + '</div>' +
      '<div class="kv" style="margin-top:10px">' +
      '<b>' + esc(t('oap.willCreate')) + '</b><span>' + (p.changes || []).length  + esc(t('oap.itemsSuffix')) + '</span>' +
      '<b>' + esc(t('oap.proposalRevLabel')) + '</b><span>' + esc(String(p.revision)) + '</span>' +
      '</div>' +
      (needsProject
        ? '<div id="approve-project-field">' + approveProjectFieldHtml(prefill) + '</div>'
        : '<p class="hint">' + esc(t('oap.projectPrefix')) + '<b>' + esc(p.project) + '</b>' + esc(t('oap.projectSource')) + '</p>') +
      '<div class="notice">' + esc(t('oap.destructive')) + '' +
      (allowStale ? '<br><b>' + esc(t('oap.skipStale')) + '</b>' + esc(t('oap.skipStaleTail'))  : '') +
      '</div>';
    openConfirmDialog({
      title: allowStale ? '仍要批准这条提案？（跳过源变更检查）' : '批准这条提案？',
      note: '批准后才会创建正式任务；拒绝不改变正式任务。',
      body: body,
      okLabel: allowStale ? '确认批准（知风险）' : '确认批准',
      onOk: function () {
        var fail = function (msg) {
          var st = document.getElementById('confirm-status');
          st.className = 'dialog-status err';
          st.textContent = msg;
          document.getElementById('confirm-dialog').showModal();
        };
        var project = p.project || '';
        if (needsProject) {
          /* 只有项目列表可用时字段才是下拉（与渲染时的判断一致），否则读手输框 */
          var sel = (state.projects && state.projects.items) ? document.getElementById('approve-project-select') : null;
          var title = '';
          var needsCreate = false;
          if (sel) {
            project = sel.value;
            if (project === NEW_PROJECT) {
              var ni = document.getElementById('approve-project-new');
              var ti = document.getElementById('approve-project-title');
              project = ni ? ni.value.trim() : '';
              title = ti ? ti.value.trim() : '';
              if (!PROJECT_KEY_RE.test(project)) { fail('新项目 key 只能包含字母、数字、点、下划线、连字符'); return; }
              needsCreate = true;
            } else {
              var hit = projectOptionByKey(project);
              if (hit && hit.inLibrary !== true) needsCreate = true;
            }
          } else {
            var input = document.getElementById('approve-project');
            project = input ? input.value.trim() : '';
          }
          if (!project) { fail('必须指定项目'); return; }
          if (needsCreate) { createProjectThenApprove(p, project, allowStale, title); return; }
        }
        approveProposal(p, project, allowStale);
      },
      afterOpen: function () { syncApproveProjectUI(); }
    });
    syncApproveProjectUI();
  }

  function openRejectProposal(p) {
    openConfirmDialog({
      title: '拒绝这条提案？',
      note: '拒绝只改 proposals.org，正式任务零变化；之后可以重新生成提案。',
      body: '<div class="src">' + esc(p.title || p.id) + '</div>' +
        reasonField('拒绝原因', '例如：范围不对 / 需要先确认输入版本', true),
      okLabel: '确认拒绝',
      onOk: function () {
        var el2 = document.getElementById('confirm-reason');
        var reason = el2 ? el2.value.trim() : '';
        if (!reason) {
          var st = document.getElementById('confirm-status');
          st.className = 'dialog-status err';
          setFieldError(st, '拒绝必须填写原因', document.getElementById('confirm-reason'));
          document.getElementById('confirm-dialog').showModal();
          return;
        }
        rejectProposal(p, reason);
      }
    });
  }

  function detailForTask() {
    var sel = state.task;
    if (!sel) return null;
    var d = state.taskDetail;
    if (!d || d.id !== sel.id) return '<div class="empty">' + esc(t('det.taskLoading')) + '</div>';
    if (d.error) return '<div class="empty">' + esc(t('det.loadFailed')) + esc(d.error) + '</div>';
    var task = d.task || {};
    var canWrite = endpointListed('PATCH', '/ui-pm/tasks/:id');

    var html = '<div class="detail-section" id="task-detail-head" tabindex="-1"><h3>' + esc(t('det.taskHead')) + '</h3>' +
      '<p style="font-weight:700;line-height:1.5">' + esc(task.title) + '</p>' +
      '<div class="kv" style="margin-top:9px">' +
      '<b>' + esc(t('det.kvStatus')) + '</b><span>' + statusBadge(task.status) +
      (task.statusMismatch ? ' <span class="chip dashed warn">' + esc(t('det.statusMismatch')) + '</span>' : '') + '</span>' +
      '<b>' + esc(t('det.kvProject')) + '</b><span>' + esc(task.projectId || sel.project) + '</span>' +
      '<b>' + esc(t('det.kvAssignee')) + '</b><span>' + esc(task.assignee || 'unassigned') + (task.ai ? esc(t('det.aiProposed')) : esc(t('det.humanMade'))) + '</span>' +
      '<b>revision</b><span>' + esc(String(task.revision)) + '</span>' +
      '<b>' + esc(t('det.kvSource')) + '</b><span>' + (task.sourceInboxId
        ? '<button type="button" class="btn small" data-open-inbox="' + esc(task.sourceInboxId) + '">' +
          esc(t('det.viewInInbox')) + esc(task.sourceInboxId) + '</button>'
        : esc(t('det.noSource'))) + '</span>' +
      '<b>' + esc(t('det.kvLocation')) + '</b><span>' + esc(d.path || '') + esc(format(t('det.lineN'), { n: String(task.line) })) + '</span>' +
      '</div></div>';

    html += '<div class="detail-section"><h3>' + esc(t('det.goalHeading')) + '</h3>' +
      '<p>' + (task.goal ? esc(task.goal) : '<span class="subtle">' + esc(t('det.noGoal')) + '</span>') + '</p>' +
      '<p class="hint">' + esc(t('det.nonGoalPrefix')) + (task.nonGoal ? esc(task.nonGoal) : esc(t('det.nonGoalNone'))) + '</p></div>';

    html += '<div class="detail-section"><h3>' + esc(format(t('det.criteriaHeading'), { done: (task.criteriaDone || 0), total: (task.criteriaTotal || 0) })) + '</h3>' +
      criteriaHtml(task, canWrite) + '</div>';

    /* §5.2：DONE 只能从 REVIEW 且由人确认 —— 任务面板里只在这一个条件下给出「→ 已完成」 */
    /* 严格按 §5.2：DONE 只在 REVIEW 且人确认时出现（不看当前是哪个视图；AI 提出的任务不出现） */
    /* task-80：任何 REVIEW 任务都能在这里验收（写操作照旧 actor=human；DONE 仍然只能由人写） */
    var humanCanDone = String(task.status) === 'REVIEW';
    html += '<div class="detail-section"><h3>' + esc(t('det.smHeading')) + '</h3>' +
      taskActionBlock(task, sel.project, humanCanDone) + '</div>';

    var execCapsNow = execCaps();
    var execReady = execCapsNow.saveConfig || execCapsNow.handoff || execCapsNow.workspaces;
    html += '<div class="detail-section"><h3>' + esc(t('det.execHeading')) + '</h3>' +
      (execReady
        ? '<button type="button" class="btn" data-exec-open="' + esc(task.id) + '" data-exec-project="' + esc(sel.project) +
          '" data-exec-revision="' + esc(String(task.revision)) + '">' + esc(t('det.setExec')) + '</button>'
        : notYet(t('det.setExecShort'), missingEndpointText('GET', '/ui-pm/workspaces'))) +
      '<p class="hint">' + esc(t('det.execHintA')) + '<code>:PM_EXEC_*:</code>' + esc(t('det.execHintB')) +
      esc(t('det.execHintC')) + '<b>' + esc(t('det.execHintD')) + '</b>' + esc(t('det.execHintE')) + '</p></div>';

    html += '<div class="detail-section"><h3>' + esc(t('det.historyHeading')) + '</h3>' + taskHistoryHtml(task) + '</div>';

    html += writeResultHtml();
    return html;
  }

  /* ---------- 任务变更历史（task-94）：数据来自 task show 的 history[]（旧→新，缺失一律 null） ----------
     诚实口径：整体缺 history 字段 ≠ 空数组；任何字段缺失写「未写入」，绝不猜；
     与 §5 凭据块分工：凭据块只讲最近一次审计，这里是完整流水。默认只显示最近 5 条 + <details> 展开（不新增 localStorage 键）。 */
  function taskHistoryRowHtml(h, i) {
    var when = localTime(h.at) || localTime(h.orgAt) || t('th.notWritten');
    var actor = h.actor ? String(h.actor) : t('th.notWritten');
    var from = h.from ? String(h.from) : t('th.notWritten');
    var to = h.to ? String(h.to) : t('th.notWritten');
    var rev = (typeof h.revision === 'number') ? ('rev ' + h.revision) : t('th.revNotWritten');
    var reason = h.reason ? String(h.reason) : '';
    var reasonShort = reason.length > 80 ? reason.slice(0, 80) + '…' : reason;
    var audit = h.auditEventId ? String(h.auditEventId) : '';
    return '<div class="th-row">' +
      '<div class="th-meta"><b>' + esc(from) + ' → ' + esc(to) + '</b>' +
      '<span class="chip">' + esc(when) + '</span>' +
      '<span class="chip">' + esc(actor) + '</span>' +
      '<span class="chip">' + esc(rev) + '</span></div>' +
      (reason
        ? '<div class="th-reason"' + (reasonShort !== reason ? ' title="' + esc(reason) + '"' : '') + '>' + esc(reasonShort) + '</div>'
        : '<div class="th-reason muted">' + esc(t('th.reasonLabel')) + '</div>') +
      (audit ? '<div class="th-audit" title="' + esc(audit) + '">' + esc(t('th.auditLabel')) + '<code>' + esc(audit.length > 26 ? audit.slice(0, 26) + '…' : audit) + '</code></div>' : '') +
      '</div>';
  }

  function taskHistoryHtml(item) {
    if (!item || !Object.prototype.hasOwnProperty.call(item, 'history')) {
      return '<div class="task-history"><p class="hint">' + esc(t('thh.logbookPrefix')) + '<code>:LOGBOOK:</code>' + esc(t('thh.logbookTail')) + '' +
        '本实例未提供 history 字段（宿主可能还是旧构建），所以这里不显示事件列表；最近一次审计见下面的凭据。</p></div>';
    }
    var list = Array.isArray(item.history) ? item.history.slice() : [];
    if (!list.length) return '<div class="task-history"><p class="hint">' + esc(t('thh.noEvents')) + '</p></div>';
    list.reverse();   /* 契约是旧→新；展示最新在上（不改动数据） */
    /* task-114：Count 是**事件总数**（不受截断影响），Shown 是**本次返回条数** ——
       截断说明必须用 shown（旧实例没有 historyShown → 退回数组长度），不能用 history.length/Count 互相顶替。 */
    var total = (typeof item.historyCount === 'number') ? String(item.historyCount) : '未写入';
    var shown = (typeof item.historyShown === 'number') ? item.historyShown : list.length;
    var html = '<div class="task-history"><div class="hint">' + esc(t('thh.totalPrefix'))  + esc(total) + esc(t('thh.itemsSuffix')) +
      (item.historyTruncated === true ? ' · 仅显示最近 ' + shown + ' 条（完整见 tasks.org）' : '') + '</div>';
    html += list.slice(0, 5).map(taskHistoryRowHtml).join('');
    var rest = list.slice(5);
    if (rest.length) {
      html += foldDetailsHtml(folds(), foldKey('history', item.id), '展开其余 ' + rest.length + ' 条',
        rest.map(taskHistoryRowHtml).join(''), { cls: 'th-rest' });
    }
    return html + '</div>';
  }

  function detailForProject() {
    if (state.task) {
      var taskHtml = detailForTask();
      if (taskHtml) return taskHtml;
    }
    if (state.card) {
      var c = detailForCard();
      if (c) return c;
    }
    var p = state.project ? projectByKey(state.project) : null;
    if (!p) {
      return '<div class="empty">' + esc(t('det.noProjectSelected')) + '<br><br>' +
        '<span class="subtle">' + esc(t('det.pickProjectCard')) + '</span></div>' +
        '<div class="detail-section"><h3>' + esc(t('det.thirdColumnHeading')) + '</h3>' +
        '<p class="hint">' + esc(t('det.thirdColumnHintA')) +
        esc(t('det.thirdColumnHintB')) + '</p></div>';
    }
    var board = (state.board && state.board.project === p.key) ? state.board : null;
    var counts = boardCounts(board);
    var html = '<div class="detail-section"><h3>' + esc(t('det.projectFactsHeading')) + '</h3><div class="kv">' +
      '<b>key</b><span>' + esc(p.key) + '</span>' +
      '<b>' + esc(t('det.kvTitle')) + '</b><span>' + esc(p.title) + '</span>' +
      '<b>' + esc(t('det.kvTasks')) + '</b><span>' + ((capsReady() && board && !board.error)
        ? esc(format(t('det.taskCountBreakdown'), { total: counts.total, todo: counts.todo, doing: counts.doing, blocked: counts.blocked, review: counts.review, closed: counts.closed }))
        : esc(t('det.tasksNotReadyNoZero'))) + '</span>' +
      '<b>' + esc(t('det.kvCards')) + '</b><span>' + esc(format(t('det.cardsAgg'), { n: p.cards })) + '</span>' +
      '<b>' + esc(t('det.kvMissingSummary')) + '</b><span>' + esc(format(t('det.cardsN'), { n: p.missing_summary })) + '</span>' +
      '<b>' + esc(t('det.kvLastObserved')) + '</b><span>' + esc(localTime(p.last_recorded) || t('det.unknownWord')) + '</span>' +
      '</div><p class="hint">' + esc(t('det.factsSource')) + '</p></div>' +
      '<div class="detail-section"><h3>' + esc(t('det.tasksVsCardsHeading')) + '</h3>' +
      '<p class="hint">' + esc(t('det.tasksVsCardsHint')) + '</p></div>' +
      '<div class="detail-section"><h3>' + esc(t('det.briefHeading2')) + '</h3>' + briefRightPaneHtml(p.key) + '</div>' +
      '<div class="detail-section"><h3>' + esc(t('det.nextStepHeading2')) + '</h3>' +
      '<p class="hint">' + esc(t('det.nextStepHint')) + '</p></div>' +
      writeResultHtml();   /* 项目简报写入的 §5 凭据 / 409(digest) 面板显示在这里 */
    return html;
  }

  function reviewActionBlock(item, project) {
    var canWrite = endpointListed('PATCH', '/ui-pm/tasks/:id');
    var html = '<div style="display:flex;gap:6px;flex-wrap:wrap">';
    if (item.status !== 'REVIEW') {
      html += '<span class="hint">' + esc(t('rab.currentStatusPrefix'))  + esc(TASK_STATUS[item.status] || item.status)  + esc(t('rab.notInReview')) + '</span>';
    } else if (!canWrite) {
      html += notYet('验收通过', unavailableReason('PATCH', '/ui-pm/tasks/:id') || 'PATCH 未就绪') +
        notYet('退回修改', unavailableReason('PATCH', '/ui-pm/tasks/:id') || 'PATCH 未就绪') +
        notYet('标记阻塞', unavailableReason('PATCH', '/ui-pm/tasks/:id') || 'PATCH 未就绪');
    } else {
      html += '<button type="button" class="btn small" data-review-return="1">' + esc(t('rab.returnBtn')) + '</button>' +
        '<button type="button" class="btn small" data-review-block="1">' + esc(t('rab.blockBtn')) + '</button>' +
        '<button type="button" class="btn primary" data-review-accept="1">' + esc(t('rab.acceptBtn')) + '</button>';
    }
    html += '</div>' +
      '<p class="hint">' + esc(t('rab.acceptHintPrefix')) + '<code>PATCH /ui-pm/tasks/:id {action:transition, to:DONE}</code>' + esc(t('rab.acceptHintTail'))  +
      '专用 accept/return 命令仍未实现，所以参考提交用 transition。' +
      '退回/阻塞必须写原因；无法判断时不要强行通过。</p>';
    return html;
  }

  function detailForReview() {
    var html = '';
    if (!state.reviewSel) {
      html += '<div class="empty">' + esc(t('dfr.pickHint')) + '</div>';
      html += '<div class="detail-section"><h3>' + esc(t('dfr.orderHeading')) + '</h3>' +
        '<p class="hint">' + esc(t('dfr.orderHint')) + '' +
        '证据来自任务自己的 <code>*** 证据（验收）</code> 节；AI 自评：未建模，不展示；' + esc(t('rv.riskUncheckedTail')) + '</p></div>';
      html += writeResultHtml();
      return html;
    }
    var sel = state.reviewSel;
    var d = state.reviewDetail;
    if (!d || d.id !== sel.id) return '<div class="empty">' + esc(t('dfr.loading')) + '</div>';
    if (d.error) return '<div class="empty">' + esc(t('brief.loadFailedPrefix2'))  + esc(d.error) + '</div>';
    var task = d.task || {};
    var canWrite = endpointListed('PATCH', '/ui-pm/tasks/:id');
    var unchecked = (task.criteria || []).filter(function (c) { return !c.done; }).length;

    html += '<div class="detail-section"><h3>' + esc(task.title) + '</h3>' +
      '<div class="kv">' +
      '<b>' + esc(t('dfr.taskLabel')) + '</b><span>' + esc(task.id) + '</span>' +
      '<b>' + esc(t('dfr.projectLabel')) + '</b><span>' + esc(sel.project) + '</span>' +
      '<b>' + esc(t('dfm.statusLabel2')) + '</b><span>' + statusBadge(task.status) + '</span>' +
      '<b>revision</b><span>' + esc(String(task.revision)) + '</span>' +
      '<b>' + esc(t('dfr.assignLabel')) + '</b><span>' + esc(task.assignee || 'unassigned') + (task.ai ? esc(t('dfr.byAi'))  : esc(t('dfr.byHuman')) + '') + '</span>' +
      '</div></div>';

    html += '<div class="detail-section"><h3>' + esc(t('dfr.h1')) + '</h3>' +
      '<p>' + (task.goal ? esc(task.goal) : '<span class="subtle">' + esc(t('dfr.noGoal')) + '</span>') + '</p>' +
      '<p class="hint">' + esc(t('dfr.nonGoalPrefix'))  + (task.nonGoal ? esc(task.nonGoal) : esc(t('dfr.notWritten')) + '') + '</p></div>';

    html += '<div class="detail-section"><h3>' + esc(t('dfr.h2')) + '</h3>' +
      '<p class="subtle">' + esc(t('dfr.noDiffModel')) + '</p></div>';

    html += '<div class="detail-section"><h3>' + esc(t('dfr.h3')) + '</h3>' + taskEvidenceSectionHtml(task) + '</div>';

    html += '<div class="detail-section"><h3>' + esc(t('dfr.h4Prefix'))  + (task.criteriaDone || 0) + '/' + (task.criteriaTotal || 0) + '）</h3>' +
      criteriaHtml(task, canWrite) + '</div>';

    html += '<div class="detail-section"><h3>' + esc(t('dfr.h5')) + '</h3>' +
      '<p class="subtle">' + esc(t('dfr.selfAssessment')) + '</p></div>';

    html += '<div class="detail-section"><h3>' + esc(t('dfr.h6')) + '</h3>' +
      '<p>' + esc(t('rv.uncheckedCriteria')) + '<b>' + unchecked + '</b>' + t('sx.itemsCountSuffix') +
      (unchecked ? esc(t('rv.decideAfterReading')) : esc(t('rv.allChecked'))) + '</p>' +
      '<p class="hint">' + esc(t('dfr.noRiskModel')) + '</p></div>';

    html += '<div class="detail-section"><h3>' + esc(t('dfr.h7')) + '</h3>' + reviewActionBlock(task, sel.project) + '</div>';
    html += writeResultHtml();
    return html;
  }

  /* ---------- task-158（B）：编号复制 + 取代链跳转（原生 DOM，零依赖） ---------- */

  function memoryCardById(id) {
    var all = document.querySelectorAll('[data-memory-id]');
    for (var i = 0; i < all.length; i++) {
      if (all[i].getAttribute && all[i].getAttribute('data-memory-id') === id) return all[i];
    }
    return null;
  }

  function setMemoryNote(text) {
    var box = document.getElementById('mem-link-note');
    if (box) box.textContent = text || '';
  }

  function copyMemoryId(id) {
    var text = memoryFullId(id);
    var done = (typeof navigator !== 'undefined' && navigator.clipboard && navigator.clipboard.writeText)
      ? navigator.clipboard.writeText(text).then(function () { return true; })['catch'](function () { return false; })
      : Promise.resolve(false);
    return done.then(function (ok) { setMemoryNote(memoryCopyNote(ok, id)); return ok; });
  }

  /* hover 目标：加高亮 + 轻微抖动/放大（reduced-motion 下 CSS 会关掉动画，只留高亮） */
  function memoryLinked(id, on) {
    var card = memoryCardById(id);
    if (!card || !card.classList) return false;
    if (on) {
      card.classList.add('mem-linked');     /* task-172：持续放大 + 提亮蒙版，直到 mouseleave */
    } else {
      card.classList.remove('mem-linked');
    }
    return true;
  }

  /* click：滚入视口 + 短暂高亮 */
  function memoryJump(id) {
    var card = memoryCardById(id);
    if (!card) return false;
    if (typeof card.scrollIntoView === 'function') card.scrollIntoView({ block: 'center' });
    if (card.classList) {
      card.classList.add('mem-flash');
      setTimeout(function () { if (card.classList) card.classList.remove('mem-flash'); }, 1700);
    }
    return true;
  }

  function findMemoryEntry(id) {
    if (!state.memory) return null;
    var hit = (state.memory.candidates || []).filter(function (e) { return e.id === id; })[0];
    if (hit) return { entry: hit, kind: 'candidate' };
    hit = (state.memory.entries || []).filter(function (e) { return e.id === id; })[0];
    return hit ? { entry: hit, kind: 'verified' } : null;
  }

  /* 用户 2026-10-21：**双击**检索命中 ⇒ 切到浏览模式、定位到那条记忆（选中 + 滚动 + 闪烁）✓ */
  function memoryOpenHitInBrowse(hit) {
    var found = findMemoryEntry(String((hit && hit.id) || ''));
    if (!found) { setMemoryNote(t('memp.hitNotInBrowse')); return; }
    var e = found.entry;
    var status = String(e.status || 'VERIFIED');
    state.memoryMode = 'browse';
    state.memoryTier = status === 'CANDIDATE' ? 'candidate' : (status === 'DEPRECATED' ? 'deprecated' : 'verified');
    state.memoryScope = String(e.scope || '');
    state.memoryType = '';       /* 清掉可能把它藏起来的筛选（跳转要能看见 ✓）*/
    state.memoryRange = 'all';
    state.memorySel = { kind: status === 'CANDIDATE' ? 'candidate' : 'verified', id: String(e.id) };
    state.memHit = null;
    state.detailOpen = true;
    render();
    memoryJump(String(e.id));
  }

  function detailForMemory() {
    var html = '';
    /* 用户 2026-10-21：检索命中的详情（recall 结果自带 path:line/score/status；与浏览选中互斥 ✓）*/
    if (state.memHit) {
      var h = state.memHit;
      var loc = String(h.path || '') + (h.line ? ':' + String(h.line) : '');
      /* 用户 2026-10-21：命中详情的正文应与**浏览模式一致**（能按 id 解析到条目时直接用同一份详情渲染 ✓）*/
      var foundHit = findMemoryEntry(String(h.id || ''));
      if (foundHit) {
        html += memoryDetailHtml(foundHit.entry);        /* 浏览模式同款：类型/scope/状态/rev/层/文件/来源/时间/正文 */
        html += '<div class="detail-section"><h3>' + esc(t('memp.hitDetailHeading')) + '</h3><div class="kv">' +
          '<b>' + esc(t('memp.hitPathLabel')) + '</b><span><code>' + esc(loc) + '</code></span>' +
          '<b>' + esc(t('memp.hitScoreLabel')) + '</b><span>' + esc(String(h.score == null ? '—' : h.score)) + '</span>' +
          '</div><p class="hint">' + esc(t('memp.hitJumpHint')) + '</p></div>';
        return html;
      }
      html += '<div class="detail-section"><h3>' + esc(t('memp.hitDetailHeading')) + '</h3>' +
        '<div class="src">' + esc(String(h.snippet || h.text || h.title || '')) + '</div></div>';
      html += '<div class="detail-section"><h3>' + esc(t('dfm.typeLabel')) + '</h3><div class="kv">' +
        '<b>' + esc(t('memp.hitPathLabel')) + '</b><span><code>' + esc(loc) + '</code></span>' +
        '<b>' + esc(t('memp.scopeLabel')) + '</b><span>' + esc(String(h.scope || '—')) + '</span>' +
        '<b>' + esc(t('dfm.typeLabel')) + '</b><span>' + esc(MEMORY_TYPES[h.type] || String(h.type || '—')) + '</span>' +
        '<b>' + esc(t('memr.statusLabel')) + '</b><span>' + esc(String(h.status || '—')) + '</span>' +
        '<b>revision</b><span>' + esc(String(h.revision == null ? '—' : h.revision)) + '</span>' +
        '<b>' + esc(t('memp.hitScoreLabel')) + '</b><span>' + esc(String(h.score == null ? '—' : h.score)) + '</span>' +
        '</div><p class="hint">' + esc(t('memp.hitNotInBrowse')) + '</p></div>';
      return html;
    }
    if (!state.memorySel) {
      html += '<div class="empty">' + esc(t('dfm.pickHint')) + '</div>';
      html += '<div class="detail-section"><h3>' + esc(t('dfm.howToUse')) + '</h3>' +
        '<p class="hint">' + esc(t('dfm.candidateHintPrefix')) + '<b>' + esc(t('dfm.suggestionBold')) + '</b>' + esc(t('dfm.candidateHintTail')) + '' +
        '确认后写入正式记忆，并开始影响对应 scope 的 AI 上下文；废弃必须写原因，历史保留（DEPRECATED）。</p></div>';
      html += writeResultHtml();
      return html;
    }
    var found = findMemoryEntry(state.memorySel.id);
    if (!found) return '<div class="empty">' + esc(t('dfm.notFound')) + '</div>';
    var e = found.entry;
    var kind = state.memorySel.kind;

    html += '<div class="detail-section"><h3>' + (kind === 'candidate' ? esc(t('dfm.candidateKind'))  : esc(t('dfm.confirmedKind')) + '') + '</h3>' +
      '<div class="src">' + esc(e.text) + '</div>' +
      '<div class="kv" style="margin-top:10px">' +
      '<b>' + esc(t('dfm.typeLabel')) + '</b><span>' + esc(MEMORY_TYPES[e.type] || e.type) + '</span>' +
      '<b>scope</b><span>' + esc(e.scope) + '</span>' +
      '<b>' + esc(t('dfm.statusLabel')) + '</b><span>' + esc(e.status) + '</span>' +
      '<b>revision</b><span>' + esc(String(e.revision)) + '</span>' +
      '<b>' + esc(t('dfm.sourceLabel')) + '</b><span>' + (e.sources && e.sources.length ? esc(e.sources.join('、')) : esc(t('dfm.unsourced')) + '') + '</span>' +
      '<b>' + esc(t('dfm.extractedLabel')) + '</b><span>' + esc(localTime(e.createdAt) || '—') + ' · ' + esc(e.createdBy || '—') + '</span>' +
      (kind === 'verified' ? '<b>' + esc(t('dfm.confirmedLabel')) + '</b><span>' + esc(localTime(e.verifiedAt) || '—') + ' · ' + esc(e.verifiedBy || '—') + '</span>' : '') +
      '</div></div>';

    if (kind === 'candidate') {
      html += '<div class="detail-section"><h3>' + esc(t('dfm.suggestionHeading')) + '</h3>' +
        '<p class="hint">' + (e.unsourced
          ? '这条候选<b>没有来源</b>：确认前请先补依据，或改写得更保守。'
          : '来源见上；来源只说明它从哪里来，不代表已经在别处验证过。') + '</p></div>';
    }

    html += '<div class="detail-section"><h3>' + esc(t('dfm.supersedeHeading')) + '</h3>' +
      '<p class="hint">supersedes：' + (e.supersedes ? esc(e.supersedes) : esc(t('dfp.noneWord2')) + '') +
      ' · supersededBy：' + (e.supersededBy ? esc(e.supersededBy) : '无') + '</p>' +
      '<p class="hint">' + esc(t('dfm.supersedeHint')) + '</p></div>';

    html += '<div class="detail-section"><h3>' + esc(t('dfp.actions2')) + '</h3>';
    var canVerify = endpointListed('POST', '/ui-pm/memory-candidates/:id/verify');
    var canDeprecate = endpointListed('POST', '/ui-pm/memory/:id/deprecate');
    var canDiscard = endpointListed('POST', '/ui-pm/memory/:id/discard');
    if (kind === 'candidate') {
      html += '<div style="display:flex;gap:6px;flex-wrap:wrap">' +
        (canVerify
          ? '<button type="button" class="btn primary" data-memory-verify="' + esc(e.id) + '">' + esc(t('dfm.verifyBtn')) + '</button>'
          : notYet('确认写入 verified', unavailableReason('POST', '/ui-pm/memory-candidates/:id/verify') || '端点未就绪')) +
        '<span class="hint" style="align-self:center">' + esc(t('dfm.keepHint')) + '</span></div>' +
        '<div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:8px">' +
        (canDiscard
          ? '<button type="button" class="btn danger" data-memory-discard="' + esc(e.id) + '">' + esc(t('dfm.discardBtn')) + '</button>' +
            /* §3#8（安全相关，Lead 2026-10-18 优先）：破坏性按钮**旁边**必须写清"不会发生什么" ✓ */
            '<span class="hint" style="align-self:center">' + esc(t('dfm.discardScope')) + '</span>'
          : notYet('丢弃候选', '本实例未提供丢弃接口（宿主可能还是旧构建）：POST /ui-pm/memory/:id/discard')) +
        (canVerify
          ? '<button type="button" class="btn" data-memory-merge="' + esc(e.id) + '">' + esc(t('dfm.mergeBtn')) + '</button>' +
            '<span class="hint" style="align-self:center">' + esc(t('dfm.mergeScope')) + '</span>'
          : notYet('合并到已有条目', '本实例未提供确认接口（宿主可能还是旧构建）：POST /ui-pm/memory-candidates/:id/verify')) +
        '</div>';
    } else if (e.status === 'DEPRECATED') {
      html += '<p class="hint">' + esc(t('dfm.deprecatedHint')) + '</p>';
    } else {
      html += '<div style="display:flex;gap:6px;flex-wrap:wrap">' +
        (canDeprecate
          ? '<button type="button" class="btn danger" data-memory-deprecate="' + esc(e.id) + '">' + esc(t('dfm.deprecateBtn')) + '</button>' +
            '<span class="hint" style="align-self:center">' + esc(t('dfm.deprecateScope')) + '</span>'
          : notYet('废弃', unavailableReason('POST', '/ui-pm/memory/:id/deprecate') || '端点未就绪')) +
        notYet('修改内容', 'pm 没有 update 命令：要改就废弃后重新确认一条') +
        '</div>';
    }
    html += '</div>';

    if (state.memoryScope && state.context) {
      html += '<div class="detail-section"><h3>' + esc(t('dfm.contextHeading')) + '</h3>' +
        '<p class="hint">scope=' + esc(state.memoryScope)  + esc(t('dfm.entersContext'))  + (state.context.counts.total || 0) +
        ' 条；被排除 候选 ' + state.context.excluded.candidate + ' / 已废弃 ' + state.context.excluded.deprecated +
        ' / 其它 scope ' + state.context.excluded.otherScope + '。</p></div>';
    }

    html += writeResultHtml();
        /* 用户要求（2026-10-19）：诚实标注**移到最后**（页面最下边 ✓），并写得更详细（页面侧文案 ✓，不动 docs）*/
return html;
  }

  /* ---------- 左侧栏折叠（VS Code 风格；与右栏「收起详情」互不干扰） ---------- */

  function applySidebarCollapsed() {
    var shell = el.shell;
    if (shell && shell.classList) shell.classList.toggle('sidebar-collapsed', state.sidebarCollapsed === true);
    var btn = document.getElementById('sidebar-toggle');
    if (btn) {
      var expanded = state.sidebarCollapsed !== true;
      btn.setAttribute('aria-expanded', expanded ? 'true' : 'false');
      btn.textContent = expanded ? '\u21e4' : '\u21e5';   /* ⇤ / ⇥ */
      btn.title = expanded ? '折叠侧栏（只留图标）' : '展开侧栏';
      btn.setAttribute('aria-label', expanded ? t('sx.collapseSidebar') : t('sx.expandSidebar'));
    }
  }

  function toggleSidebar() {
    state.sidebarCollapsed = state.sidebarCollapsed !== true;
    try { localStorage.setItem('pm-sidebar-collapsed', state.sidebarCollapsed ? '1' : '0'); } catch (e) { /* 忽略 */ }
    applySidebarCollapsed();
    /* 侧栏宽度变了 → 中列变宽，看板箭头禁用态要重算 */
    var b = document.getElementById('project-board');
    if (b && b.__syncArrows) b.__syncArrows();
  }

  /* ---------- 第三列宽度：应用 / 拖拽 / 键盘 / 持久化 ---------- */

  function viewDefaultDetailWidth() {
    return (state.view === 'review' || state.view === 'memory') ? DETAIL_W_WIDE : DETAIL_W_DEFAULT;
  }

  function currentDetailWidth() {
    var vw = (window.innerWidth || 1440);
    if (state.detailWidth !== null && state.detailWidth !== undefined) return clampDetailWidth(state.detailWidth, vw);
    return clampDetailWidth(viewDefaultDetailWidth(), vw);
  }

  /* 写到 .shell 的 CSS 变量；没有用户覆盖时移除内联变量，回落 CSS 里的视图默认值。 */
  function applyDetailWidth() {
    var shell = el.shell;
    var rz = document.getElementById('detail-resizer');
    var vw = (window.innerWidth || 1440);
    var user = (state.detailWidth === null || state.detailWidth === undefined) ? null : clampDetailWidth(state.detailWidth, vw);
    if (shell && shell.style && shell.style.setProperty) {
      if (user === null) {
        shell.style.removeProperty('--pm-detail-w');
        shell.style.removeProperty('--pm-detail-w-wide');
      } else {
        shell.style.setProperty('--pm-detail-w', user + 'px');
        shell.style.setProperty('--pm-detail-w-wide', user + 'px');
      }
    }
    if (rz) {
      rz.setAttribute('aria-valuenow', String(user === null ? clampDetailWidth(viewDefaultDetailWidth(), vw) : user));
      rz.setAttribute('aria-valuemin', String(DETAIL_W_MIN));
      rz.setAttribute('aria-valuemax', String(Math.min(DETAIL_W_ABS_MAX, Math.max(DETAIL_W_MIN, vw - DETAIL_W_CHROME))));
    }
  }

  function saveDetailWidth(px) {
    try { localStorage.setItem('pm-detail-width', String(Math.round(px))); } catch (e) { /* 存不下不影响本次会话 */ }
  }

  function setDetailWidth(px) {
    var clamped = clampDetailWidth(px, (window.innerWidth || 1440));
    state.detailWidth = clamped;
    applyDetailWidth();
    saveDetailWidth(clamped);
  }

  /* 双击复位：删掉 key（不写假值），回到视图默认 */
  function resetDetailWidth() {
    try { localStorage.removeItem('pm-detail-width'); } catch (e) {}
    state.detailWidth = null;
    applyDetailWidth();
  }

  function wireDetailResizer() {
    var rz = document.getElementById('detail-resizer');
    if (!rz) return;
    var drag = null;
    rz.addEventListener('pointerdown', function (ev) {
      if (ev.button !== undefined && ev.button !== 0) return;
      drag = { x: ev.clientX, w: currentDetailWidth() };
      if (rz.setPointerCapture && ev.pointerId !== undefined) {
        try { rz.setPointerCapture(ev.pointerId); } catch (e) { /* 不支持就算了 */ }
      }
      if (document.body && document.body.classList) document.body.classList.add('pm-resizing');
      if (ev.preventDefault) ev.preventDefault();
    });
    rz.addEventListener('pointermove', function (ev) {
      if (!drag) return;
      state.detailWidth = clampDetailWidth(drag.w - (ev.clientX - drag.x), (window.innerWidth || 1440));
      applyDetailWidth();
    });
    var finish = function () {
      if (!drag) return;
      drag = null;
      if (document.body && document.body.classList) document.body.classList.remove('pm-resizing');
      if (state.detailWidth !== null && state.detailWidth !== undefined) saveDetailWidth(state.detailWidth);
    };
    rz.addEventListener('pointerup', finish);
    rz.addEventListener('pointercancel', finish);
    rz.addEventListener('dblclick', function () { resetDetailWidth(); });
    rz.addEventListener('keydown', function (ev) {
      var vw = (window.innerWidth || 1440);
      var cur = currentDetailWidth();
      if (ev.key === 'ArrowLeft') setDetailWidth(cur + 16);
      else if (ev.key === 'ArrowRight') setDetailWidth(cur - 16);
      else if (ev.key === 'Home') setDetailWidth(DETAIL_W_MIN);
      else if (ev.key === 'End') setDetailWidth(vw);
      else return;
      if (ev.preventDefault) ev.preventDefault();
    });
  }

  function renderDetail() {
    var open = state.detailOpen;
    el.shell.classList.toggle('detail-collapsed', !open);
    document.getElementById('detail-toggle').setAttribute('aria-expanded', String(open));
    document.getElementById('detail-toggle').textContent = open ? t('topbar.detailToggleHide') : t('topbar.detailToggleShow');
    if (!open) return;

    var title = t('detail.title'), html = '';
    if (state.error && !state.data) {
      title = t('detail.title'); html = '<div class="empty">' + esc(t('detail.notLoaded')) + '</div>';
    } else if (!state.data) {
      html = '<div class="empty">' + esc(t('sync.syncing')) + '</div>';
    } else if (state.proposal && (state.view === 'board' || state.view === 'projects')) {
      title = t('detail.proposal'); html = detailForProposal() || '';
    } else if (state.task && state.view === 'projects') {
      title = t('detail.task'); html = detailForTask() || '';
    } else if (state.card && (state.view === 'board' || state.view === 'projects')) {
      title = t('detail.card'); html = detailForCard() || '';
    } else if (state.view === 'board') {
      title = t('detail.boardHelp'); html = detailForBoard();
    } else if (state.view === 'projects') {
      title = state.project ? t('detail.project') : t('detail.projectOverview'); html = detailForProject();
    } else if (state.view === 'inbox') {
      title = t('detail.triageOp'); html = detailForInbox();
    } else if (state.view === 'review') {
      title = t('detail.review'); html = detailForReview();
    } else {
      title = t('detail.memory'); html = detailForMemory();
    }
    el.detailTitle.textContent = title;
    el.detailBody.innerHTML = html;
  }

  /* ================= 渲染与路由 ================= */

  /* 视图所需的领域数据按需拉取（caps 未就绪时视图自己显示「未接入」）。 */
  /* task-01M52ADGGT15：异步取数完成后【必须校验路由再渲染】——否则旧视图的回调晚到会把
     新视图的 #content 覆盖回旧视图（症状：头部/副标题跟着新路由 ✓，主体停在旧视图 ✗，且刷新也能复现）。
     用法：在发起取数那一刻取 routeToken()，完成回调里用 guarded(token)(fn) 包一层。 */
  function routeToken() { return routeKey(currentRoute()); }
  function guarded(token, fn) {
    return function () {
      if (routeToken() !== token) return;   /* 路由已变 ⇒ 这次结果属于旧视图，丢弃（不写 #content） */
      (fn || render)();
    };
  }

  function kickoffViewData() {
    if (!state.data || !capsReady()) return;
    var tk = routeToken();
    if (state.view === 'projects' && state.project) {
      var want = state.project;
      if (!state.board || state.board.project !== want) {
        loadBoard(want).then(guarded(tk));
      }
      if (!state.projectBrief || state.projectBrief.key !== want) {
        loadProjectBrief(want).then(guarded(tk));
      }
      if (state.tab === 'memory' && (!state.projectMemory || state.projectMemory.project !== want)) {
        loadProjectMemory(want).then(guarded(tk, function (v) { state.projectMemory.project = want; render(); }));
      }
    } else if (state.view === 'board') {
      if (!state.proposals && !state.proposalsLoading && capsReady()) {
        state.proposalsLoading = true;
        loadProposals().then(guarded(tk, function () { state.proposalsLoading = false; render(); }));
      }
    } else if (state.view === 'inbox') {
      var cur = (state.inbox && state.note >= 0) ? state.inbox.entries[state.note] : null;
      if (cur && cur.id && (!state.inboxDetail || state.inboxDetail.id !== cur.id)) {
        loadInboxDetail(cur.id).then(guarded(tk));
      }
    } else if (state.view === 'review') {
      if (!state.review && !state.reviewLoading) {
        state.reviewLoading = true;
        loadReview().then(guarded(tk, function () { state.reviewLoading = false; render(); }));
      }
    } else if (state.view === 'memory') {
      if (!state.memory && !state.memoryLoading) {
        state.memoryLoading = true;
        /* 失败也必须 re-render：loadMemory 在失败路径同样写 state.memory.error ✓，
           但原来只有 .then(成功) 才 render ⇒ 接口 500/网络错时页面**永远停在 loading 壳**、错误无人可见 ✗
           （task-263 验收⑤"错误态"就是抓这个 ✓）。第二个处理器负责失败路径，且**不**依赖 guarded 的早退语义 ✓。 */
        var afterMemoryLoad = function () { state.memoryLoading = false; guarded(tk, function () { render(); })(); };
        loadMemory().then(afterMemoryLoad, afterMemoryLoad);
      }
    }
  }

  /* U4：把原本用原生 alert 的阻断式提示改成页内提示（#sync 已是 role=status/aria-live；
     顺带解决 alert 阻塞主线程、不可主题化的问题）。 */
  function surfaceNotice(msg) {
    if (el.sync) { el.sync.textContent = msg; if (el.sync.classList) el.sync.classList.add('sync-error'); }
    else if (window.console) console.warn(msg);
  }

  function render() {
    state.renderCount = (state.renderCount || 0) + 1;   /* 渲染计数：给「搜索重建次数」这类验收贴证据 */
    /* #22：右栏收起时，写失败也必须可见 —— 把最新写错误送到顶栏 #sync（role=status + aria-live）✓。
       右栏展开时静默（错误在对话框/右栏里已有位置），不重复打扰。 */
    if (el.sync && el.shell && el.shell.classList) {
      var detailCollapsed = el.shell.classList.contains('detail-collapsed');
      var we = state.writeError;
      if (detailCollapsed && we) {
        var code = errText(we.code) || we.code || '';
        el.sync.textContent = t('ui.writeFailedBanner') + (code ? code + t('task.errorSep') : '') + (we.message || '');
        el.sync.classList.add('sync-error');
      } else {
        el.sync.classList.remove('sync-error');
      }
    }

    if (state.error && !state.data) {
      el.content.innerHTML = '<div class="panel"><div class="empty">' + esc(t('brief.loadFailedPrefix3'))  + esc(state.error) + '<br><br>' +
        '<span class="subtle">' + esc(t('rnd.hostNotReady')) + '</span>' +
        '<br><br><button class="btn" type="button" id="retry">' + esc(t('rnd.retry')) + '</button></div></div>';
      renderDetail();
      return;
    }
    if (!state.data) return;

    var d = state.data;
    (function () {
      /* #29：导航按钮的 aria-label 原本不含计数（计数在旁边的 span 里，而 aria-label 会盖住它）⇒ 把计数写进可访问名 */
      var np = document.getElementById('nav-projects');
      if (np) {
        np.textContent = d.projects.length;
        var bp = np.closest ? np.closest('button') : null;
        if (bp) bp.setAttribute('aria-label', t('nav.projects') + ' (' + d.projects.length + ')');
      }
    })();
    document.getElementById('nav-inbox').textContent = (state.inboxStatus && state.inbox)
      ? state.inbox.count : (d.inbox ? d.inbox.count : 0);

    el.pageTitle.textContent = viewTitle(state.view);
    /* 用户裁定（2026-10-19）：记忆页/提示词页**界面元素按示例** ⇒ 页面自带 h1+hint，外层 app 页头标题**隐藏**（否则两套标题并存 ✗）；导航走左侧入口 ✓ */
    document.body.classList[(state.view === 'memory' || state.view === 'prompt') ? 'add' : 'remove']('embed-page-h1');
    var sub = '';
    /* task-204：页面副标题（外壳）也全部走文案表 */
    if (state.view === 'board') {
      sub = format(t('sub.board'), { cards: d.cards.length, projects: d.projects.length });
    } else if (state.view === 'projects') {
      sub = state.project ? format(t('sub.projectsOne'), { key: state.project }) : format(t('sub.projectsAll'), { projects: d.projects.length });
    } else if (state.view === 'inbox') {
      sub = format(t('sub.inbox'), {
        count: (d.inbox ? d.inbox.count : 0),
        mode: endpointReady() ? t('sub.inboxModeOk') : t('sub.inboxModeReadonly')
      });
    } else if (state.view === 'review') {
      sub = t('sub.review');
    } else {
      sub = t('sub.memory');
    }
    el.pageSub.textContent = sub + ' · ' + dataSourceLine();
    renderCrumb();

    /* task-174：重建 innerHTML 会把看板横向位置、**每列卡片区**的纵向位置、右栏详情位置一起归零。
       渲染前记下来、渲染后原样恢复 —— **只此一份实现**（不要再写第二套滚动状态）。 */
    var prevScroll = captureScrollState();
    if (state.view === 'board') el.content.innerHTML = viewBoard();
    else if (state.view === 'projects') el.content.innerHTML = viewProjects();
    else if (state.view === 'inbox') el.content.innerHTML = viewInbox();
    else if (state.view === 'review') el.content.innerHTML = viewReview();
    else if (state.view === 'prompt') {
      /* ⚠️ 顺序要紧：**先置 loading 标志、再渲染**，最后才发 GET ✗
         （我第一版是先渲染再置标志 ⇒ 首帧 loading=false ⇒ 加载态观察不到 ✗ —— delay 夹具实测抓到的 ✓）。 */
      var wantScope = promptScopeKey();
      if (state.promptLoadedFor !== wantScope) {
        state.promptLoadedFor = wantScope;
        /* 端点缺失 ⇒ **短路**（零请求）：不发 GET、直接渲染「端点缺失」人话提示 */
        if (!endpointListed('GET', '/ui-pm/prompt')) {
          state.promptLoading = false; state.promptExists = false; state.promptBlocks = []; state.promptSaved = JSON.stringify([])
          el.content.innerHTML = renderPromptPage(promptPageState()); return
        }
        state.promptLoading = true;                 /* 首次读取要有加载态（否则显示模板、像服务端内容 ✗）*/
        el.content.innerHTML = renderPromptPage(promptPageState());
        loadPromptPage(wantScope);
        /* 已保存的提示词（库）在进页时加载一次（此前只在导出/删除后刷新 ⇒ 首次进页永远空 ✗）*/
        if (endpointListed('GET', '/ui-pm/prompt-exports')) promptExportsLoad();
        /* 已保存过 prompt.org 的项目清单：进页就拉（项目下拉要标注"已保存 rev N"/"无记录" + 填充下拉要用）✓ */
        if (!state.promptIndexLoaded && endpointListed('GET', '/ui-pm/prompts')) { state.promptIndexLoaded = true; loadPromptIndex(); }
      } else {
        el.content.innerHTML = renderPromptPage(promptPageState());
      }
    }
    else el.content.innerHTML = '<div id="pmMemoryPage"><main class="main">' + viewMemory() + '</main></div>';

    /* task-196：横向居中与纵向恢复**互不相干**，不能写成互斥。
       旧写法是 if (!reapplyBoardCenterIfPending()) restoreScrollState(prevScroll) ——
       有待完成的横向居中时那个函数返回 true，于是**整段纵向恢复被跳过**，每列 scrollTop 与右栏都归零。
       现在：纵向（每列 scrollTop + 右栏）**永远**恢复；横向只在没有待居中时才恢复（跳过，交给居中落位）。 */
    var boardCentered = reapplyBoardCenterIfPending();
    restoreScrollState(prevScroll, { skipBoard: boardCentered });
    /* 展开/收起：把那张卡的**顶部**锚住（内容变高就向下长，不跳回顶部）；
       点卡片选中：优先保持位置，只有卡片不完整可见时才在**该列内**居中。 */
    if (!applyCardAnchor() && state.keepCardVisible) ensureCardFullyVisible();
    state.keepCardVisible = false;
    applyFocusTask();   /* task-168①：批准后定位/高亮新建的卡（渲染后重试，直到卡片出现） */

    kickoffViewData();

    el.shell.classList.toggle('detail-wide', state.view === 'review' || state.view === 'memory');
    applyDetailWidth();
    applySidebarCollapsed();
    renderDetail();
    wire();
    hardenAutofillNow();   /* 每次渲染后机械扫一遍：新加的输入也不会漏（task-76） */
  }

  /* ---------- 路由与「返回」 ---------- */

  function currentRoute() { return { view: state.view, project: state.project, tab: state.tab }; }

  function routeKey(r) {
    if (!r) return '';
    return r.view + (r.project ? '/' + r.project : '') + (r.tab ? ':' + r.tab : '');
  }

  /* 自然父级：没有来路时「返回」回落到这里（项目详情 → 项目列表 → 工作台）。 */
  function naturalParent(r) {
    if (!r) return null;
    if (r.view === 'projects' && r.project) return { view: 'projects', project: null, tab: r.tab };
    if (r.view === 'projects') return { view: 'board', project: null, tab: null };
    if (r.view === 'board') return null;
    return { view: 'board', project: null, tab: null };
  }

  function parentLabel(r) {
    if (!r) return '';
    if (r.view === 'projects' && r.project) return t('sr.parentProjects');
    if (r.view === 'board') return '工作台';
    if (r.view === 'projects') return '工作台';
    return '工作台';
  }

  /* 返回按钮上的短去向名：用户知道点下去去哪儿才敢点 */
  function backLabel(r) {
    if (!r) return '';
    if (r.view === 'projects' && !r.project) return '项目列表';
    if (r.view === 'projects' && r.project) return '项目 ' + r.project;
    return viewTitle(r.view);
  }

  function routeLabel(r) {
    if (!r) return '';
    if (r.view === 'projects' && !r.project) return '项目列表';
    return (viewTitle(r.view)) + (r.project ? ' / ' + r.project : '');
  }

  /* 只看不弹：用于渲染判断。栈里与当前路由相同的项跳过（浏览器前进/后退留下的重复项）。 */
  function peekBack() {
    var curKey = routeKey(currentRoute());
    for (var i = state.navStack.length - 1; i >= 0; i--) {
      if (routeKey(state.navStack[i]) !== curKey) return state.navStack[i];
    }
    return naturalParent(currentRoute());
  }

  /* 真正取来路：弹出栈顶（并清掉与当前路由重复的项）。 */
  function backTarget() {
    var curKey = routeKey(currentRoute());
    while (state.navStack.length) {
      var top = state.navStack.pop();
      if (routeKey(top) !== curKey) return top;
    }
    return naturalParent(currentRoute());
  }

  function navigate(entry, push) {
    var target = {
      view: entry.view,
      project: (entry.view === 'projects' && entry.project) ? entry.project : null,
      tab: entry.tab || state.tab
    };
    if (push !== false && routeKey(currentRoute()) !== routeKey(target)) {
      state.navStack.push(currentRoute());
      if (state.navStack.length > 30) state.navStack.shift();
    }
    state.view = target.view;
    state.project = target.project;
    if (target.tab) state.tab = target.tab;
    state.card = null;
    state.task = null;
    state.taskDetail = null;
    var hash = '#/' + target.view + (target.project ? '/' + encodeURIComponent(target.project) : '');
    if (location.hash !== hash) location.hash = hash; else render();
    syncNav();
  }

  function go(view, project, tab) {
    navigate({ view: view, project: project || null, tab: tab || null }, true);
  }

  /* 返回 = 来路；没有来路时回落自然父级。刻意不用 history.back()：
     用户直接打开/刷新 #/projects/x 时，浏览器上一页可能是别的站点。 */
  function goBack() {
    var target = backTarget();
    if (!target) return;
    navigate(target, false);
  }

  /* 标题区左上角：返回（来路）+ 显式上级链接（确定性出口） */
  function renderCrumb() {
    var cur = currentRoute();
    var back = peekBack();
    var parent = naturalParent(cur);
    var backBtn = document.getElementById('back-btn');
    var parentBtn = document.getElementById('parent-link');
    var sep = document.getElementById('crumb-sep');
    if (backBtn) {
      if (back) {
        backBtn.hidden = false;
        backBtn.textContent = t('sr.back') + backLabel(back);
        backBtn.setAttribute('title', t('sr.backTo') + routeLabel(back));
        backBtn.setAttribute('aria-label', t('sr.backTo') + routeLabel(back));
      } else {
        backBtn.hidden = true;
      }
    }
    /* 返回目标与自然父级相同时（例如直接刷新进详情页）只留一个确定性的控件，
       避免「← 返回 项目列表 / 项目列表」这种同指两个按钮；有来路时两者并存、语义不同。 */
    var sameTarget = !!(back && parent && routeKey(back) === routeKey(parent));
    if (parentBtn) {
      if (parent && !sameTarget) {
        parentBtn.hidden = false;
        parentBtn.textContent = parentLabel(cur);
        parentBtn.setAttribute('title', t('sr.goTo') + parentLabel(cur) + '（确定性出口）');
        parentBtn.setAttribute('aria-label', t('sr.goTo') + parentLabel(cur));
      } else {
        parentBtn.hidden = true;
      }
    }
    if (sep) sep.hidden = !(back && parent && !sameTarget);
  }

  function syncNav() {
    Array.prototype.forEach.call(document.querySelectorAll('#nav button'), function (b) {
      var active = b.getAttribute('data-view') === state.view;
      b.classList.toggle('active', active);
      if (active) b.setAttribute('aria-current', 'page'); else b.removeAttribute('aria-current');
    });
  }

  function fromHash() {
    var m = (location.hash || '').replace(/^#\/?/, '').split('/');
    var v = m[0] || 'board';
    if (!t('view.' + v) || t('view.' + v) === 'view.' + v) v = 'board';
    state.view = v;
    state.project = (v === 'projects' && m[1]) ? decodeURIComponent(m[1]) : null;
    state.card = null;
    state.task = null;
    state.taskDetail = null;
    /* 浏览器前进/后退不走 go()：去掉与当前路由相同的栈项，避免「返回」原地打转 */
    state.navStack = state.navStack.filter(function (e) { return routeKey(e) !== routeKey(currentRoute()); });
    syncNav();
    if (state.data) render();
  }

  /* ================= 事件 ================= */

  function openSession(sessionId, instance) {
    var card = state.data.cards.filter(function (c) { return c.session_id === sessionId; })[0];
    if (card && isArchived(card)) {
      surfaceNotice(t('sr.sessionArchived'));
      return;
    }
    if (window.parent !== window) {
      /* 内嵌在 DSH 里：交给宿主上下文调用 uiWorkspace.openSession */
      window.parent.postMessage({ type: 'pm-open-session', sessionId: sessionId, instance: instance }, '*');
    } else {
      surfaceNotice(t('sr.noHostJump'));
    }
  }

  function copyPath(path) {
    var ok = function () { el.sync.textContent = t('sx.copiedPath') + path; };
    var fail = function () { el.sync.textContent = t('sx.copyPathFailed'); };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(path).then(ok, fail);
    } else { fail(); }
  }

  /* 「处理这条」：选中 → 右栏收起则展开（并持久化）→ 滚到分流操作 / 只读说明 → 聚焦第一个可用动作 */
  function openNoteActions(i) {
    state.note = i;
    ensureDetailOpen();
    render();
    var entry = (state.inbox && state.inbox.entries) ? state.inbox.entries[i] : null;
    var actionable = !!(entry && entry.id && typeof entry.revision === 'number');
    var body = el.detailBody;
    var query = (body && body.querySelector) ? body.querySelector.bind(body) : null;
    var anchor = query ? query(actionable ? '#inbox-actions' : '#inbox-text') : null;
    if (anchor && anchor.scrollIntoView) { try { anchor.scrollIntoView({ block: 'nearest' }); } catch (e) {} }
    var target = null;
    if (query) {
      target = query('[data-inbox-op], [data-inbox-archive], [data-annotate-save], [data-edit-open]');
      if (!target && !actionable) target = query('#inbox-text');
    }
    if (target && target.focus) { try { target.focus(); } catch (e) {} }
    return { actionable: actionable, focused: !!target };
  }

  function wire() {
    /* 选中工作卡 → 第三栏详情 */
    el.content.querySelectorAll('[data-session]').forEach(function (node) {
      node.addEventListener('click', function () {
        var id = node.getAttribute('data-session');
        if (node.classList.contains('agent-title') || node.classList.contains('item-title')) {
          state.card = id;
          ensureDetailOpen();   /* P2：点会话卡 ⇒ 展开右栏（否则收起状态下点了没反应 ✗）*/
          renderDetail();
        } else {
          openSession(id, node.getAttribute('data-instance'));
        }
      });
    });

    el.content.querySelectorAll('[data-open-session]').forEach(function (node) {
      node.addEventListener('click', function () {
        openSession(node.getAttribute('data-open-session'), node.getAttribute('data-instance'));
      });
    });

    /* 详情栏里的「打开 DSH 会话」 */
    el.detailBody.querySelectorAll('[data-session]').forEach(function (node) {
      node.addEventListener('click', function () {
        openSession(node.getAttribute('data-session'), node.getAttribute('data-instance'));
      });
    });

    /* 键盘可达：项目标题是按钮；点卡片空白处也能进（鼠标便利） */
    el.content.querySelectorAll('[data-project]').forEach(function (node) {
      node.addEventListener('click', function () { ensureDetailOpen(); go('projects', node.getAttribute('data-project')); });   /* P2：进项目页时右栏项目详情自动展开 ✓ */
    });
    el.content.querySelectorAll('[data-project-card]').forEach(function (node) {
      node.addEventListener('click', function (e) {
        if (e.target.closest('button, a, input, select, textarea')) return;
        go('projects', node.getAttribute('data-project-card'));
      });
    });

    el.content.querySelectorAll('[data-goto]').forEach(function (node) {
      node.addEventListener('click', function () { go(node.getAttribute('data-goto')); });
    });

    el.content.querySelectorAll('[data-tab]').forEach(function (node) {
      node.addEventListener('click', function () {
        state.tab = node.getAttribute('data-tab');
        render();
      });
    });

    el.content.querySelectorAll('[data-copy]').forEach(function (node) {
      node.addEventListener('click', function () { copyPath(node.getAttribute('data-copy')); });
    });

    /* 收件箱：「处理这条」按钮（自带 data-note-open；行级监听对 button 直接 return，所以这里单独绑定） */
    el.content.querySelectorAll('[data-note-open]').forEach(function (node) {
      node.addEventListener('click', function (ev) {
        if (ev && ev.stopPropagation) ev.stopPropagation();
        openNoteActions(parseInt(node.getAttribute('data-note-open'), 10));
      });
    });

    /* 行内补充：展开 / 收起（默认最多 3 行） */
    el.content.querySelectorAll('[data-anno-toggle]').forEach(function (node) {
      node.addEventListener('click', function (ev) {
        /* 展开/收起只改本卡 DOM（clamped 类）—— 绝不能让点击冒泡到行选中 ⇒ 整页重建 ⇒ 展开立刻被打回 ✗ */
        if (ev && ev.stopPropagation) ev.stopPropagation();
        if (ev && ev.preventDefault) ev.preventDefault();
        var id = node.getAttribute('data-anno-toggle');
        var bodyEl = document.getElementById ? document.getElementById(id) : null;
        if (!bodyEl || !bodyEl.classList) return;
        var clamped = bodyEl.classList.contains('clamped');
        if (clamped) { bodyEl.classList.remove('clamped'); node.textContent = t('sr.collapseShort'); }
        else { bodyEl.classList.add('clamped'); node.textContent = t('sx.expand'); }
      });
    });

    /* 收件箱：选中一条记录 */
    el.content.querySelectorAll('[data-note]').forEach(function (node) {
      node.addEventListener('click', function (e) {
        /* 2026-10-19 Bug-1：根已是 article.note、正文在 button.note-main 里 ⇒ 旧的 closest('button')!==node 恒真 ⇒ 点卡片永远 return ✗。
           守卫挡**操作区**与**补充区**：
             · .note-actions 里的按钮自己处理 ✓；
             · .anno-list（补充/展开区）里的「展开/收起」与正文选择要能独立工作 —— 不挡会冒泡到行选中 ⇒ 整页重建 ⇒ 刚展开的补充又被收起（用户 2026-10-19「无法点击」✗）
           点 .note-main / 卡片空白 ⇒ 选中 + 展开右栏 ✓。*/
        if (e.target && e.target.closest && e.target.closest('.note-actions, .anno-list')) return;
        state.note = parseInt(node.getAttribute('data-note'), 10);
        ensureDetailOpen();   /* P2：点收件箱行 ⇒ 展开右栏（这一行本身就是详情入口 ✓）*/
        render();
      });
    });

    var q = el.content.querySelector('#inbox-q');
    if (q) {
      /* #28：连续输入只在停下来后重建一次视图（220ms debounce）；Escape 清空并把焦点送回输入框 */
      var searchTimer = null;
      var refocusSearch = function (toEnd) {
        var again = document.querySelector('#inbox-q');
        if (again) { again.focus(); try { again.setSelectionRange(toEnd ? again.value.length : 0, toEnd ? again.value.length : 0); } catch (e) {} }
      };
      /* IME（中文/日文等）组字期间**禁止重建视图** ✗：render() 会替换 #content 的 DOM ⇒ 输入框被换掉、
         组字被打断 ⇒ 打不出中文（2026-10-19 用户实测：按空格选字后变成 "a'a'aa'" 乱码）。
         口径：compositionstart ⇒ 挂起；compositionend ⇒ 才更新 state.q 并触发一次 debounce render。
         input 事件带 isComposing=true 时同样跳过（覆盖"组字中不触发 compositionend 的输入法" ✓）。 */
      var composing = false;
      q.addEventListener('compositionstart', function () { composing = true; });
      q.addEventListener('compositionend', function () {
        composing = false;
        state.q = q.value;
        if (searchTimer) clearTimeout(searchTimer);
        searchTimer = setTimeout(function () { render(); refocusSearch(true); }, 220);
      });
      q.addEventListener('input', function (ev) {
        if (composing || (ev && ev.isComposing)) return;   /* 组字中：只让输入法处理，不重建视图 ✓ */
        state.q = q.value;
        if (searchTimer) clearTimeout(searchTimer);
        searchTimer = setTimeout(function () { render(); refocusSearch(true); }, 220);
      });
      q.addEventListener('keydown', function (e) {
        if (e.key === 'Escape') {
          if (searchTimer) clearTimeout(searchTimer);
          state.q = '';
          render();
          refocusSearch(false);
        }
      });
    }

    /* 收件箱：状态过滤走真实端点参数 */
    var statusSelect = el.content.querySelector('#inbox-status');
    if (statusSelect) {
      statusSelect.addEventListener('change', function () {
        state.inboxStatus = statusSelect.value;
        state.note = 0;
        loadInbox().then(render);
      });
    }

    /* 收件箱：来源过滤（客户端，与状态过滤叠加；不需要重新拉取端点） */
    var originSelect = el.content.querySelector('#inbox-origin');
    if (originSelect) {
      originSelect.addEventListener('change', function () {
        state.inboxOrigin = (originSelect.value === 'human' || originSelect.value === 'ai') ? originSelect.value : '';
        clampNoteToVisible();
        render();
      });
    }

    /* 收件箱：归档 / 延期（列表与详情栏都要可点） */
    var wireInboxActions = function (root) {
      root.querySelectorAll('[data-inbox-pin]').forEach(function (node) {
        node.addEventListener('click', function () {
          var entry = findAnyInboxEntry(node.getAttribute('data-inbox-pin'));
          if (entry) pinNote(entry);
        });
      });
      root.querySelectorAll('[data-inbox-archive]').forEach(function (node) {
        node.addEventListener('click', function () {
          openConfirm('archive', node.getAttribute('data-inbox-archive'));
        });
      });
      root.querySelectorAll('[data-inbox-snooze]').forEach(function (node) {
        node.addEventListener('click', function () {
          openConfirm('snooze', node.getAttribute('data-inbox-snooze'));
        });
      });
    };
    wireInboxActions(el.content);
    wireInboxActions(el.detailBody);

    /* 快速记录按钮（收件箱页）／页内刷新／重试：这几个绑定在早前的手术里丢过一次，现在有测试守着 */
    var newBtn = el.content.querySelector('#new-capture');
    if (newBtn) newBtn.addEventListener('click', function () { openCapture(); });
    var refreshInline = el.content.querySelector('#refresh-inline');
    if (refreshInline) refreshInline.addEventListener('click', function () { refreshAll(true); });
    var retryBtn = el.content.querySelector('#retry');
    if (retryBtn) retryBtn.addEventListener('click', function () { refreshAll(true); });

    /* 快速记录：独立的即时反馈行，避免和同步状态互相覆盖 */
    var quick = el.content.querySelector('#quick-form');
    if (quick) {
      var input = quick.querySelector('#quick');
      var status = quick.parentNode.querySelector('#quick-status');
      var DRAFT_KEY = 'pm.quickDraft';
      /* 草稿保护：只存在这台浏览器里（localStorage），绝不上传、不写 Org ✓ */
      var saveDraft = function () {
        try { window.localStorage.setItem(DRAFT_KEY, input.value); } catch (e) {}
      };
      var clearDraft = function () {
        try { window.localStorage.removeItem(DRAFT_KEY); } catch (e) {}
      };
      try {
        var saved = window.localStorage.getItem(DRAFT_KEY);
        if (saved) {
          input.value = saved;
          status.className = 'quick-status';
          status.textContent = t('qn.draftRestored');
        }
      } catch (e) {}
      /* 回车换行 = textarea 默认；这里只加【org 列表延续】："- " / "- [ ] " 后回车续前缀；空项回车取消延续 */
      input.addEventListener('keydown', function (ev) {
        if (ev.key !== 'Enter') return;
        if (ev.ctrlKey || ev.metaKey) {           /* Ctrl/Cmd+Enter = 提交 */
          ev.preventDefault();
          quick.dispatchEvent(new Event('submit', { cancelable: true }));
          return;
        }
        if (ev.shiftKey) return;                  /* Shift+Enter 也是换行，交给默认行为 */
        var pos = input.selectionStart;
        if (pos !== input.selectionEnd) return;   /* 有选区时不改写 */
        var before = input.value.slice(0, pos);
        var lineStart = before.lastIndexOf('\n') + 1;
        var line = before.slice(lineStart);
        var m = /^(\s*)(- \[ \] |- )(.*)$/.exec(line);
        if (!m) return;                           /* 不在列表项里 ⇒ 默认换行 */
        ev.preventDefault();
        if (m[3].trim() === '') {                 /* 空项回车 ⇒ 取消延续（删掉前缀） */
          input.value = input.value.slice(0, lineStart) + '\n' + input.value.slice(pos);
          input.selectionStart = input.selectionEnd = lineStart + 1;
          saveDraft();
          return;
        }
        var insert = '\n' + m[1] + m[2];
        input.value = input.value.slice(0, pos) + insert + input.value.slice(pos);
        input.selectionStart = input.selectionEnd = pos + insert.length;
        saveDraft();
      });
      input.addEventListener('input', saveDraft);
      var emacsBox = quick.parentNode.querySelector('#quick-emacs');
      var emacsCmd = quick.parentNode.querySelector('#quick-emacs-cmd');
      var emacsNote = quick.parentNode.querySelector('#quick-emacs-note');
      var emacsCopy = quick.parentNode.querySelector('#quick-emacs-copy');
      if (emacsCopy) {
        emacsCopy.addEventListener('click', function () {
          var txt = emacsCmd ? emacsCmd.textContent : '';
          if (!txt) return;
          if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(txt).then(function () { emacsCopy.textContent = t('qn.emacsCopied'); }, function () {});
          }
        });
      }
      quick.addEventListener('submit', function (e) {
        e.preventDefault();
        var raw = input.value;                    /* org 语法原样：不转义、不过滤、不 trim 后再写 */
        if (!raw.trim()) return;
        var submitBtn = quick.querySelector('button[type="submit"]');
        /* 防重（客户端）：① 按钮在飞禁用 ② 同一段内容的 key 在飞时直接忽略 —— 连点只写一条 ✓ */
        if (quick.dataset.inflight === '1' || (submitBtn && submitBtn.disabled)) return;
        quick.dataset.inflight = '1';
        input.disabled = true;
        if (submitBtn) submitBtn.disabled = true;
        status.className = 'quick-status';
        status.textContent = t('quick.writing');
        capture(raw).then(function (res) {
          delete quick.dataset.inflight;
          input.disabled = false;
          if (submitBtn) submitBtn.disabled = false;
          if (res.ok) {
            input.value = '';
            clearDraft();
            input.placeholder = t('qn.cleared');
            status.className = 'quick-status ok';
            status.textContent = res.note || t('qn.recorded');
            load(true, true);
            /* 写入成功后给出【可复制】的 emacs 命令；后端不返回行号时只给路径（不猜行号）✓ */
            var abs = (res && typeof res.absolutePath === 'string') ? res.absolutePath : '';
            var lineNo = (res && res.line !== null && res.line !== undefined) ? String(res.line) : '';
            if (abs && emacsBox && emacsCmd) {
              emacsBox.hidden = false;
              emacsCmd.textContent = 'emacs +' + (lineNo || '') + ' "' + abs + '"';
              if (emacsNote) emacsNote.textContent = lineNo ? '' : t('qn.emacsNoLine');
            } else if (emacsBox && emacsCmd) {
              emacsBox.hidden = false;
              emacsCmd.textContent = t('qn.pathOnly');
              if (emacsNote) emacsNote.textContent = t('qn.emacsNoLine');
            }
          } else {
            status.className = 'quick-status err';
            status.textContent = t('quick.writeFailed') + res.error;
          }
        });
      });
    }

    wireDomain();
  }

  /* 领域交互：任务 / 待验收 / 记忆（与收件箱分开，避免一个函数过长） */
  function wireDomain() {
    var roots = [el.content, el.detailBody];

    roots.forEach(function (root) {
      root.querySelectorAll('[data-task-id]').forEach(function (node) {
        node.addEventListener('click', function () {
          if (state.dragSuppressClick) { state.dragSuppressClick = false; return; }   /* 拖动结束不触发选中 */
          selectTask(node.getAttribute('data-task-project'), node.getAttribute('data-task-id'));
        });
      });
      root.querySelectorAll('[data-review-id]').forEach(function (node) {
        node.addEventListener('click', function () {
          var id = node.getAttribute('data-review-id');
          state.reviewSel = { project: node.getAttribute('data-review-project'), id: id };
          state.reviewDetail = null;
          ensureDetailOpen();   /* P2：点待验收条目 ⇒ 展开右栏（验收详情在那里 ✓）*/
          loadReviewDetail(state.reviewSel.project, id).then(function () {
            state.reviewDetail = state.taskDetail ? Object.assign({ id: id }, state.taskDetail) : null;
            render();
          });
          render();
        });
      });
      /* 分栏拖拽条已删（用户 2026-10-19：内部记录/23 示例为单栏，无此控件）⇒ 对应 handler 一并移除。
         注意：'data-mem-split-drag' 在渲染模板与 handler 两处都出现过 —— 删模板必须同时删 handler，
         否则会 ReferenceError: drag is not defined（2026-10-19 踩过 ✗）。 */
      /* 搜索：回车或点按钮 ⇒ 真发 GET /ui-pm/recall?q=…（只读 ✓）；结果存 state.memSearch ✓
         用户 2026-10-21：必须带**两个过滤器** —— 当前项目 scope（未选=全部）+ 全部/具体类型；并记录实际条件 ✓ */
      var q = root.querySelector('[data-mem-q]');
      var runSearch = function (termArg) {
        var term = String(termArg != null ? termArg : (q ? q.value : '')).trim();
        if (q && term && q.value !== term) q.value = term;
        memoryRunSearch(term);   /* 过滤条件由模块级实现统一处理（scope/type/limit）✓ */
      };
      /* 切 scope / 类型时：若已有检索结果 ⇒ 用新过滤器重搜（不静默沿用旧结果 ✗）*/
      var rerunSearchIfAny = function () {
        if (state.memoryMode === 'search' && state.memSearch && state.memSearch.term) runSearch(state.memSearch.term);
      };
      if (q) {
        q.addEventListener('keydown', function (ev) { if (ev && ev.key === 'Enter') { ev.preventDefault(); runSearch(); } });
      }
      var sbtn = root.querySelector('[data-mem-search-go]');
      if (sbtn) sbtn.addEventListener('click', function (ev) { if (ev && ev.preventDefault) ev.preventDefault(); runSearch(); });
      var rf = root.querySelector('[data-mem-refresh]');
      if (rf) rf.addEventListener('click', function (ev) {
        if (ev && ev.preventDefault) ev.preventDefault();
        loadMemory();
      });
      root.querySelectorAll('[data-mem-scope-sel]').forEach(function (node) {
        node.addEventListener('change', function (ev) {
          if (ev && ev.preventDefault) ev.preventDefault();
          var k = node.value || '';
          state.memoryScope = (k === '__noscope__') ? '' : k;   /* 未标范围归一件（当前状态里没有独立键 ⇒ 与"全部"同义 ✓）*/
          /* 用户 2026-10-21：数据已一次拉全量，scope 过滤在 viewMemory 内客户端做
             ⇒ 这里只需清选中 + 重渲染（列表与计数同一口径，不会再"下拉 3 条 / tabs 1 条"✗）*/
          state.memorySel = null;      /* 换范围后旧选中可能已不在列表里 ⇒ 收起，避免右栏残留 */
          state.memHit = null;
          render();
          /* 检索模式：换 scope 必须用新范围重搜（用户 2026-10-21：检索要按当前项目过滤 ✓）*/
          if (state.memoryMode === 'search' && state.memSearch && state.memSearch.term) memoryRunSearch(state.memSearch.term, { keepTier: true });
        });
      });
      root.querySelectorAll('[data-mem-mode]').forEach(function (node) {
        if (node.disabled) return;
        node.addEventListener('click', function (ev) {
          if (ev && ev.preventDefault) ev.preventDefault();
          state.memoryMode = node.getAttribute('data-mem-mode') || 'browse';
          state.memHit = null;       /* 进/出检索都清掉命中选中（右栏不残留旧详情 ✓）*/
          render();
        });
      });
      root.querySelectorAll('[data-mem-range]').forEach(function (node) {
        node.addEventListener('change', function () {
          state.memoryRange = node.value || 'all';
          render();
        });
      });
      root.querySelectorAll('[data-mem-expand]').forEach(function (node) {
        node.addEventListener('click', function (ev) {
          if (ev && ev.stopPropagation) ev.stopPropagation();
          if (ev && ev.preventDefault) ev.preventDefault();
          /* 用户 2026-10-21：展开/收起必须是**同一个开关** —— 此前 pill 写 memoryExpanded，而卡片渲染读的是
             memorySel ⇒ pill 点了没有任何视觉变化 ✗。现在 pill 与卡片点击统一切换 memorySel：
             未选中 ⇒ 选中（展开）；已选中同一张 ⇒ 取消（收起）✓ */
          var id = String(node.getAttribute('data-mem-expand'));
          var card = node.closest ? node.closest('[data-memory-id]') : null;
          var kind = card ? String(card.getAttribute('data-memory-kind') || 'verified') : 'verified';
          var cur = state.memorySel;
          if (cur && String(cur.id) === id && String(cur.kind) === kind) state.memorySel = null;
          else state.memorySel = { kind: kind, id: id };
          /* 用户 2026-10-21：展开 ⇒ 右栏详情**自动出现**；收起 ⇒ 详情**自动消失**（detailOpen 随选中态联动）*/
          state.detailOpen = !!state.memorySel;
          render();
        });
      });
      root.querySelectorAll('[data-mem-tier]').forEach(function (node) {
        node.addEventListener('click', function (ev) {
          if (ev && ev.stopPropagation) ev.stopPropagation();
          state.memoryTier = node.getAttribute('data-mem-tier') || 'candidate';
          render();
        });
      });
      /* 用户 2026-10-21：单击检索命中的记忆 ⇒ 右栏自动打开详情（与浏览卡片的交互一致 ✓）*/
      root.querySelectorAll('[data-mem-hit-id]').forEach(function (node) {
        var openHit = function (ev) {
          if (ev && ev.preventDefault) ev.preventDefault();
          var id = String(node.getAttribute('data-mem-hit-id') || '');
          var hit = ((state.memSearch && state.memSearch.hits) || []).filter(function (h) { return String(h.id) === id; })[0];
          if (!hit) return;
          state.memHit = hit;
          state.memorySel = null;         /* 命中详情与浏览选中互斥，避免两套详情打架 ✓ */
          state.detailOpen = true;        /* 自动打开右栏 ✓ */
          render();
        };
        node.addEventListener('click', openHit);
        node.addEventListener('keydown', function (ev) {
          if (ev && (ev.key === 'Enter' || ev.key === ' ' || ev.key === 'Spacebar')) openHit(ev);
        });
        /* 用户 2026-10-21：双击命中 ⇒ 跳到浏览模式下的那条记忆（选中+滚动+闪烁）✓ */
        node.addEventListener('dblclick', function (ev) {
          if (ev && ev.preventDefault) ev.preventDefault();
          var id = String(node.getAttribute('data-mem-hit-id') || '');
          var hit = ((state.memSearch && state.memSearch.hits) || []).filter(function (h) { return String(h.id) === id; })[0];
          if (hit) memoryOpenHitInBrowse(hit);
        });
      });
      root.querySelectorAll('[data-mem-copy]').forEach(function (node) {
        var act = function (ev) {
          if (ev && ev.stopPropagation) ev.stopPropagation();
          if (ev && ev.preventDefault) ev.preventDefault();
          copyMemoryId(node.getAttribute('data-mem-copy'));
        };
        node.addEventListener('click', act);
        /* #7：它是 span[role=button]（不是真 button，因为外层已是 button）⇒ 必须自己处理键盘激活 */
        node.addEventListener('keydown', function (ev) {
          if (ev && (ev.key === 'Enter' || ev.key === ' ' || ev.key === 'Spacebar')) act(ev);
        });
      });
      root.querySelectorAll('[data-mem-link]').forEach(function (node) {
        var link = { id: node.getAttribute('data-mem-link'), dir: node.getAttribute('data-mem-dir') };
        var targetCard = function () { return root.querySelector('[data-memory-id="' + String(link.id).replace(/"/g, '\\"') + '"]') }
        var mark = function (on) { var t0 = targetCard(); if (t0) { if (on) t0.classList.add('linked'); else t0.classList.remove('linked') } }
        node.addEventListener('mouseenter', function () { mark(true) })
        node.addEventListener('mouseleave', function () { mark(false) })
        node.addEventListener('focus', function () { mark(true) })
        node.addEventListener('blur', function () { mark(false) })
        node.addEventListener('click', function () {   /* 跳转后闪一下目标卡（.flash；reduced-motion 由示例 CSS 处理 ✓）*/
          var t0 = targetCard(); if (!t0) return
          t0.classList.remove('flash'); void t0.offsetWidth; t0.classList.add('flash')
          setTimeout(function () { t0.classList.remove('flash') }, 1600)
        })
        node.addEventListener('click', function (ev) {
          if (ev && ev.stopPropagation) ev.stopPropagation();
          if (ev && ev.preventDefault) ev.preventDefault();
          /* 与 tooltip 同源：目标卡是否**真的渲染在当前列表**（旧写法 memoryCardById 是另一个集合 ⇒ 与 tooltip 口径分裂 ✗）*/
          var present = !!targetCard();
          if (present) memoryJump(link.id);
          setMemoryNote(memoryLinkNote(link, present));   /* 不在本页也照样给一句实话 */
        });
        node.addEventListener('mouseenter', function () { memoryLinked(link.id, true); });
        node.addEventListener('mouseleave', function () { memoryLinked(link.id, false); });
      });
      root.querySelectorAll('[data-memory-id]').forEach(function (node) {
        node.addEventListener('click', function () {
          var wantKind = node.getAttribute('data-memory-kind');
          var wantId = node.getAttribute('data-memory-id');
          /* 用户 2026-10-21：展开态再次点击同一张卡 ⇒ **收起**（此前永远只赋值、点不掉 ✗）*/
          if (state.memorySel && String(state.memorySel.id) === String(wantId) &&
              String(state.memorySel.kind) === String(wantKind)) {
            state.memorySel = null;
            state.detailOpen = false;      /* 收起 ⇒ 右栏详情自动消失 ✓ */
            render();
            return;
          }
          state.memorySel = { kind: wantKind, id: wantId };
          state.detailOpen = true;         /* 展开 ⇒ 右栏详情自动出现 ✓ */
          var found = findMemoryEntry(state.memorySel.id);
          if (found && found.entry.scope && !state.memoryScope) {
            state.memoryScope = found.entry.scope;
            state.contextScope = found.entry.scope;
            loadMemoryContext(state.contextScope).then(render);
          }
          render();
        });
      });
      root.querySelectorAll('[data-transition-to]').forEach(function (node) {
        node.addEventListener('click', function () {
          var d = state.taskDetail;
          if (!state.task || !d || !d.task) return;
          requestTransition(state.task.project, state.task.id, d.task.status,
            node.getAttribute('data-transition-to'), d.task.revision);
        });
      });
      root.querySelectorAll('[data-criterion-index]').forEach(function (node) {
        node.addEventListener('click', function () {
          var d = state.taskDetail;
          if (!state.task || !d || !d.task) return;
          var idx = parseInt(node.getAttribute('data-criterion-index'), 10);
          var clist = (d.task && d.task.criteria) || [];
          var criterion = clist[idx] || null;
          if (!isFinite(idx)) return;
          var done = node.getAttribute('data-criterion-done') === 'true';
          taskCheck(state.task.project, state.task.id, criterion, idx, done, d.task.revision);
        });
      });
      root.querySelectorAll('[data-review-accept]').forEach(function (node) {
        node.addEventListener('click', function () {
          var d = state.reviewDetail;
          if (!d || !d.task) return;
          requestTransition(state.reviewSel.project, state.reviewSel.id, d.task.status, 'DONE', d.task.revision);
        });
      });
      root.querySelectorAll('[data-review-return]').forEach(function (node) {
        node.addEventListener('click', function () {
          var d = state.reviewDetail;
          if (!d || !d.task) return;
          openTransition(state.reviewSel.project, state.reviewSel.id, d.task.status, 'DOING', d.task.revision, {
            title: '退回修改（REVIEW → 执行中）？',
            note: '退回必须写原因：AI 需要知道要改什么。',
            okLabel: '确认退回',
            reasonLabel: '退回意见',
            reasonPlaceholder: '哪里不满足验收标准',
            reasonRequired: true
          });
        });
      });
      root.querySelectorAll('[data-review-block]').forEach(function (node) {
        node.addEventListener('click', function () {
          var d = state.reviewDetail;
          if (!d || !d.task) return;
          openTransition(state.reviewSel.project, state.reviewSel.id, d.task.status, 'BLOCKED', d.task.revision, {
            title: '标记阻塞（REVIEW → 阻塞）？',
            note: '阻塞要有具体解除条件，不要用它代替「通过」。',
            okLabel: '确认阻塞',
            reasonLabel: '阻塞原因',
            reasonPlaceholder: '缺什么、等谁',
            reasonRequired: true
          });
        });
      });
      root.querySelectorAll('[data-memory-discard]').forEach(function (node) {
        node.addEventListener('click', function () {
          var found = findMemoryEntry(node.getAttribute('data-memory-discard'));
          if (found) openMemoryDiscard(found.entry);
        });
      });
      root.querySelectorAll('[data-memory-merge]').forEach(function (node) {
        node.addEventListener('click', function () {
          var found = findMemoryEntry(node.getAttribute('data-memory-merge'));
          if (found) openMemoryMerge(found.entry);
        });
      });
      root.querySelectorAll('[data-memory-verify]').forEach(function (node) {
        node.addEventListener('click', function () {
          var found = findMemoryEntry(node.getAttribute('data-memory-verify'));
          if (found) openMemoryVerify(found.entry);
        });
      });
      root.querySelectorAll('[data-memory-deprecate]').forEach(function (node) {
        node.addEventListener('click', function () {
          var found = findMemoryEntry(node.getAttribute('data-memory-deprecate'));
          if (found) openMemoryDeprecate(found.entry);
        });
      });
      wireProjectRetry(root);
      /* 项目页看板：左右箭头 + ←/→ 滚动，两端如实禁用 */
      var boardEl = (root.querySelector ? root.querySelector('#project-board') : null);
      if (boardEl) {
        var colStep = function () { return Math.max(240, Math.round((boardEl.clientWidth || 800) * 0.8)); };
        var maxScroll = function () { return Math.max(0, (boardEl.scrollWidth || 0) - (boardEl.clientWidth || 0)); };
        var setScroll = function (v) {
          var max = maxScroll();
          var next = Math.max(0, Math.min(max, Math.round(v)));
          boardEl.scrollLeft = next;
          return next;
        };
        var syncArrows = function () {
          var max = maxScroll();
          var left = boardEl.scrollLeft || 0;
          var atStart = left <= 2;
          var noOverflow = max <= 2;
          var atEnd = left >= max - 2;
          var prev = root.querySelector ? root.querySelector('#board-prev') : null;
          var next = root.querySelector ? root.querySelector('#board-next') : null;
          if (prev) {
            prev.disabled = noOverflow || atStart;
            prev.setAttribute('aria-disabled', prev.disabled ? 'true' : 'false');
            prev.title = noOverflow ? '所有列都在屏幕里，不需要滚动' : (atStart ? '已经在最左边' : '向左滚动一列');
          }
          if (next) {
            next.disabled = noOverflow || atEnd;
            next.setAttribute('aria-disabled', next.disabled ? 'true' : 'false');
            next.title = noOverflow ? '所有列都在屏幕里，不需要滚动' : (atEnd ? '已经在最右边' : '向右滚动一列');
          }
        };
        var prevBtn = root.querySelector ? root.querySelector('#board-prev') : null;
        var nextBtn = root.querySelector ? root.querySelector('#board-next') : null;
        if (prevBtn) prevBtn.addEventListener('click', function () { setScroll((boardEl.scrollLeft || 0) - colStep()); syncArrows(); });
        if (nextBtn) nextBtn.addEventListener('click', function () { setScroll((boardEl.scrollLeft || 0) + colStep()); syncArrows(); });
        if (boardEl.addEventListener) {
          boardEl.addEventListener('scroll', syncArrows);
          boardEl.addEventListener('keydown', function (ev) {
            if (ev.key === 'ArrowLeft') { setScroll((boardEl.scrollLeft || 0) - colStep()); syncArrows(); if (ev.preventDefault) ev.preventDefault(); }
            else if (ev.key === 'ArrowRight') { setScroll((boardEl.scrollLeft || 0) + colStep()); syncArrows(); if (ev.preventDefault) ev.preventDefault(); }
          });
        }
        boardEl.__syncArrows = syncArrows;
        syncArrows();
      }
      /* task-68：DAG 图交互 —— hover/聚焦高亮前驱后继、点节点滚到子任务行；点行也脉冲高亮节点 */
      /* task-86：卡片拖动（pointer events，触摸也能用） */
      root.querySelectorAll('[data-drag-id]').forEach(function (cardEl) {
        cardEl.addEventListener('pointerdown', function (ev) { boardDragDown(ev, cardEl); });
      });
      root.querySelectorAll('[data-dag-node]').forEach(function (node) {
        var nodeId = node.getAttribute('data-dag-node');
        var svg = node.closest ? node.closest('svg') : null;
        node.addEventListener('mouseenter', function () { dagHighlight(svg, nodeId, true); });
        node.addEventListener('mouseleave', function () { dagHighlight(svg, nodeId, false); });
        node.addEventListener('focus', function () { dagHighlight(svg, nodeId, true); });
        node.addEventListener('blur', function () { dagHighlight(svg, nodeId, false); });
        node.addEventListener('click', function () { dagScrollToTeamRow(nodeId); });
        node.addEventListener('keydown', function (ev) {
          if (ev.key === 'Enter' || ev.key === ' ' || ev.key === 'Spacebar') { ev.preventDefault(); dagScrollToTeamRow(nodeId); }
        });
      });
      root.querySelectorAll('[data-team-row]').forEach(function (row) {
        row.addEventListener('click', function () { dagPulseNode(row.getAttribute('data-team-row')); });
      });
      root.querySelectorAll('[data-team-row-jump]').forEach(function (btn) {
        btn.addEventListener('click', function () { dagScrollToTeamRow(btn.getAttribute('data-team-row-jump')); });
      });
      root.querySelectorAll('[data-task-expand]').forEach(function (node) {
        node.addEventListener('click', function (ev) {
          /* 展开按钮与主按钮是兄弟；这里再显式阻止冒泡，双保险不触发选中 */
          if (ev && ev.stopPropagation) ev.stopPropagation();
          if (ev && ev.preventDefault) ev.preventDefault();
          var id = node.getAttribute('data-task-expand');
          if (!id) return;
          anchorTaskCard(id);          /* task-174：先锚住这张卡的顶部位置，再重渲染 */
          var set = taskExpandedSet();
          var willExpand = !set[id];
          if (willExpand) set[id] = true;
          else delete set[id];
          saveTaskExpanded();
          var project = node.getAttribute('data-task-expand-project') || '';
          var revision = parseInt(node.getAttribute('data-task-expand-revision') || '', 10);
          render();
          var refocus = function () {
            var again = document.getElementById('task-expand-' + safeDomId(id));
            if (again && again.focus) { try { again.focus({ preventScroll: true }); } catch (e) { try { again.focus(); } catch (e2) {} } }
            /* 用户交互落在这张卡上 → 顺便保证它所在列可见/居中；列比看板宽时以卡可见为先（不居中） */
            centerBoardOnTask(id, { requireFullColumn: true });
          };
          if (willExpand && !isNaN(revision)) {
            /* 懒加载一次 task show（按 id+revision 缓存）：loadTaskExtras 会**同步**写入 loading 态，
               所以先启动它、再渲染一次，用户看到的是「正在读取…」而不是「还没有读到」。 */
            var pending = loadTaskExtras(id, project, revision);
            render();
            var keepFocus = function () { refocus(); };
            pending.then(function () { render(); keepFocus(); });
            keepFocus();
          } else {
            refocus();
          }
        });
      });
      root.querySelectorAll('[data-board-note]').forEach(function (node) {
        node.addEventListener('click', function () { openInboxEntry(node.getAttribute('data-board-note')); });
      });
      root.querySelectorAll('[data-exec-open]').forEach(function (node) {
        node.addEventListener('click', function () {
          var t = state.taskDetail && state.taskDetail.task;
          if (!t) return;
          openExecWizard({
            id: node.getAttribute('data-exec-open'),
            projectId: node.getAttribute('data-exec-project') || t.projectId,
            title: t.title
          }, parseInt(node.getAttribute('data-exec-revision'), 10));
        });
      });
      root.querySelectorAll('[data-task-jump]').forEach(function (node) {
        node.addEventListener('click', function () {
          var id = node.getAttribute('data-task-jump');
          var project = node.getAttribute('data-task-project') || '';
          if (!id) return;
          state.focusTask = { project: project, id: id, at: Date.now(), select: true };
          state.proposal = null;   /* 详情分派器优先显示提案；点「跳到这张卡」是要看任务，所以清掉提案选中 */
          if (project && state.project !== project) {
            state.project = project;
            location.hash = '#/projects/' + encodeURIComponent(project);
            loadBoard(project).then(render);
            render();
            return;
          }
          render();
        });
      });
      root.querySelectorAll('[data-needsme-toggle]').forEach(function (node) {
        node.addEventListener('click', function () { needsMeToggle(node.getAttribute('data-needsme-toggle')); });
      });
      root.querySelectorAll('[data-proposal-id]').forEach(function (node) {
        node.addEventListener('click', function () { selectProposal(node.getAttribute('data-proposal-id')); });
      });
      root.querySelectorAll('[data-proposal-approve]').forEach(function (node) {
        node.addEventListener('click', function () {
          var p = findProposal(node.getAttribute('data-proposal-approve'));
          if (p) openApproveProposal(p, false);
        });
      });
      root.querySelectorAll('[data-new-project]').forEach(function (node) {
        node.addEventListener('click', function () { openCreateProjectDialog({}); });
      });
      root.querySelectorAll('[data-brief-edit]').forEach(function (node) {
        node.addEventListener('click', function () {
          openBriefEditor(node.getAttribute('data-brief-edit'), node.getAttribute('data-brief-section'));
        });
      });
      root.querySelectorAll('[data-proposal-revise]').forEach(function (node) {
        node.addEventListener('click', function () {
          var p = findProposal(node.getAttribute('data-proposal-revise'));
          if (p) openProposalEditor(p);
        });
      });
      root.querySelectorAll('[data-proposal-reject]').forEach(function (node) {
        node.addEventListener('click', function () {
          var p = findProposal(node.getAttribute('data-proposal-reject'));
          if (p) openRejectProposal(p);
        });
      });
      root.querySelectorAll('[data-proposal-approve-stale]').forEach(function (node) {
        node.addEventListener('click', function () {
          var p = findProposal(node.getAttribute('data-proposal-approve-stale'));
          if (!p) return;
          state.staleRetried = true;   /* 重试过还失败 → 说明路由没转发 --allow-stale */
          openApproveProposal(p, true);
        });
      });
      root.querySelectorAll('[data-open-inbox]').forEach(function (node) {
        node.addEventListener('click', function () {
          var id = node.getAttribute('data-open-inbox');
          go('inbox');
          selectNoteById(id);
          render();
        });
      });
      root.querySelectorAll('[data-copy-stale]').forEach(function (node) {
        node.addEventListener('click', function () {
          var p = findProposal(node.getAttribute('data-copy-stale'));
          if (!p) return;
          copyText('pm --config <你的 pm.toml> proposal approve ' + p.id +
            ' --expected-revision ' + p.revision + ' --allow-stale --json', 'stale-copy-status');
        });
      });
      root.querySelectorAll('[data-annotate-save]').forEach(function (node) {
        node.addEventListener('click', function () {
          var entry = findInboxEntry(node.getAttribute('data-annotate-save'));
          if (entry) saveAnnotation(entry);
        });
      });
      root.querySelectorAll('[data-edit-open]').forEach(function (node) {
        node.addEventListener('click', function () {
          var entry = findInboxEntry(node.getAttribute('data-edit-open'));
          if (entry) openEditOriginal(entry);
        });
      });
      root.querySelectorAll('[data-inbox-op]').forEach(function (node) {
        node.addEventListener('click', function () {
          var kind = node.getAttribute('data-inbox-op');
          var entry = findInboxEntry(node.getAttribute('data-inbox-op-id'));
          if (!entry) return;
          if (kind === 'ai-task') openProposalDialog(entry);
          else openInboxOpDialog(kind, entry);
        });
      });
      root.querySelectorAll('[data-new-task]').forEach(function (node) {
        node.addEventListener('click', function () { openTaskCreate(node.getAttribute('data-new-task')); });
      });
      root.querySelectorAll('[data-reload-tasks]').forEach(function (node) {
        node.addEventListener('click', function () {
          loadBoard(node.getAttribute('data-reload-tasks')).then(render);
        });
      });
    });

    var typeSel = el.content.querySelector('#memory-type');
    if (typeSel) typeSel.addEventListener('change', function () {
      state.memoryType = typeSel.value;
      state.memHit = null;
      render();
      /* 用户 2026-10-21：检索要按「全部类型 / 具体类型」过滤 ⇒ 已有检索结果时用新类型重搜 ✓ */
      if (state.memoryMode === 'search' && state.memSearch && state.memSearch.term) memoryRunSearch(state.memSearch.term, { keepTier: true });
    });
    var scopeSel = el.content.querySelector('#memory-scope');
    if (scopeSel) {
      scopeSel.addEventListener('change', function () {
        state.memoryScope = scopeSel.value;
        loadMemory().then(render);
      });
    }
    var ctxSel = el.content.querySelector('#context-scope');
    if (ctxSel) {
      ctxSel.addEventListener('change', function () {
        state.contextScope = ctxSel.value;
        state.context = null;
        render();
        loadMemoryContext(state.contextScope).then(render);
      });
    }
    var ovBtn = el.content.querySelector('[data-load-overview]');
    if (ovBtn) {
      ovBtn.addEventListener('click', function () { loadOverview().then(render); });
    }
    var depBtn = el.content.querySelector('#memory-show-deprecated');
    if (depBtn) {
      depBtn.addEventListener('click', function () {
        state.memoryShowDeprecated = !state.memoryShowDeprecated;
        render();
      });
    }
  }
  /* ================= 取数 ================= */

  /* 宿主对 GET /ui-pm/cards 有 45s TTL 缓存；只有 ?refresh=1 会强制重扫。
     首屏/宿主 mount 允许走缓存，用户点「刷新」必须绕过它 —— 一个叫刷新的按钮不刷新会摧毁信任。 */
  function cardsUrl(force) {
    var base;
    try { base = new URL('../cards', location.href).toString(); }
    catch (e) { base = '/ui-pm/cards'; }
    if (!force) return base;
    return base + (base.indexOf('?') >= 0 ? '&' : '?') + 'refresh=1';
  }

  /* 显式刷新：先把视图级缓存清掉，否则「刷新」只换了 /cards，页面数据还是旧的。 */
  function refreshAll(force) {
    state.review = null;
    state.reviewDetail = null;
    state.reviewSel = null;
    state.memory = null;
    state.context = null;
    state.board = null;
    state.taskDetail = null;
    state.projectMemory = null;
    state.overview = null;
    state.proposals = null;
    state.proposalDetail = null;
    state.inboxDetail = null;
    state.taskExtras = {};   /* 列表/详情都变了，懒加载的子任务缓存一起清掉 */
    return load(false, force !== false);
  }

  function load(silent, force) {
    if (!silent && el.content) {
      el.content.innerHTML = '<div class="panel"><div class="empty">' + esc(t('memp.loadingShell')) + '</div></div>';
      el.sync.textContent = force ? t('sync.forceSyncing') : t('sync.syncing');
    }
    return fetch(cardsUrl(force), { headers: { accept: 'application/json' }, cache: 'no-store' })
      .then(function (r) {
        if (!r.ok) throw new Error('HTTP ' + r.status + '（' + r.statusText + '）');
        return r.json();
      })
      .then(function (body) {
        if (!body || body.ok !== true) throw new Error((body && body.error) || '响应格式不对');
        state.data = body.data;
        state.error = null;
        /* inbox 单独走真实端点（带 revision）；端点不可用时 loadInbox 内部回退到 /cards（只读）。 */
        return loadCapabilities().then(loadInbox).then(function () {
          el.sync.textContent = (force ? t('sync.forceSyncing') + ' ' : t('sync.read') + ' ') + localTime(body.data.generated_at) + t('sync.snapshot') +
            (endpointReady() ? '' : ' · inbox 端点不可用（回退 /cards 只读）') +
            (capsReady() ? '' : ' · 领域端点不可用（capabilities 404）');
          render();
        });
      })
      .catch(function (err) {
        state.error = err.message || String(err);
        el.sync.textContent = t('sync.failed');
        render();
      });
  }

  /* ================= 快速记录（写 inbox.org，只追加） ================= */

  function capture(text) {
    var url;
    try { url = new URL('../capture', location.href).toString(); }
    catch (e) { url = '/ui-pm/capture'; }
    return fetch(url, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      /* 注意：/capture 未证实接受 idempotencyKey（pm-write.js 明写这类路由是字段白名单，未声明字段 400）
         ⇒ 这里【不发】该字段；防重由调用点的在飞禁用 + 同一段内容的 captureKey 客户端去重承担。 */
      body: JSON.stringify({ text: text })
    }).then(function (r) {
      if (r.status === 409) {
        /* 冲突：按 backend-design §5 要求重新加载，不静默覆盖 */
        load(true, true);
        return { ok: false, error: '409 冲突：数据可能已被其他编辑器修改，已重新加载，请重试。' };
      }
      return r.json().then(function (b) {
        if (!r.ok || !b.ok) throw new Error((b && b.error) || ('HTTP ' + r.status));
        var res = b.result || b;
        if (res && res.result) res = res.result;
        var where = (res.path || 'inbox') + (res.line ? ' 第 ' + res.line + ' 行' : '');
        return {
          ok: true,
          result: b,
          note: '已追加到 ' + where +
            (res.inboxId ? ' · ID ' + res.inboxId : ' · 未返回稳定 ID（P1 已知缺口）') +
            (res.revision !== undefined ? ' · revision ' + res.revision : '')
        };
      });
    }).catch(function (err) {
      return { ok: false, error: err.message || String(err) };
    });
  }

  function openCapture() {
    var dlg = document.getElementById('capture-dialog');
    document.getElementById('capture-status').textContent = '';
    document.getElementById('capture-text').value = '';
    dlg.showModal();
    document.getElementById('capture-text').focus();
  }

  /* ---------- 项目下拉：change 委托 + 422 一键创建后重试 ---------- */

  function currentProposal() {
    var d = state.proposalDetail;
    if (d && d.proposal && d.id === state.proposal) return d.proposal;
    return null;
  }

  function wireProposalEditorControls() {
    var dlg = document.getElementById('confirm-dialog');
    if (!dlg || !dlg.addEventListener) return;
    dlg.addEventListener('change', function (ev) {
      var t = ev && ev.target ? ev.target : null;
      if (!t || t.id !== 'brief-edit-section' || !state.briefEdit) return;
      var ta = document.getElementById('brief-edit-text');
      state.briefEdit.drafts[state.briefEdit.section] = ta ? ta.value : '';
      state.briefEdit.section = t.value;
      renderBriefEditor();
    });
    dlg.addEventListener('click', function (ev) {
      var t = ev && ev.target ? ev.target : null;
      if (!t || !t.getAttribute) return;
      var p = currentProposal();
      if (!p || !state.proposalEdit) return;
      var add = t.getAttribute('data-revise-add');
      var del = t.getAttribute('data-revise-del');
      if (add) {
        captureProposalEditor();
        state.proposalEdit.changes.push({ op: '新增', title: '', text: '', criteria: [] });
        renderProposalEditor(p);
      } else if (del !== null && del !== undefined) {
        captureProposalEditor();
        var idx = parseInt(del, 10);
        if (!isNaN(idx)) state.proposalEdit.changes.splice(idx, 1);
        if (!state.proposalEdit.changes.length) state.proposalEdit.changes.push({ op: '新增', title: '', text: '', criteria: [] });
        renderProposalEditor(p);
      }
    });
  }

  function wireProjectControls() {
    var dlg = document.getElementById('confirm-dialog');
    if (dlg && dlg.addEventListener) {
      dlg.addEventListener('change', function (ev) {
        var t = ev && ev.target ? ev.target : null;
        if (t && t.id === 'approve-project-select') syncApproveProjectUI();
      });
    }
  }

  /* 详情里的「创建 projects/proj-<key> 后重试」：同一两段式，仍然二次确认 */
  function wireProjectRetry(root) {
    root.querySelectorAll('[data-project-retry]').forEach(function (node) {
      node.addEventListener('click', function () {
        var key = node.getAttribute('data-project-retry');
        var p = currentProposal();
        if (!p) { el.sync.textContent = t('sx.proposalStale'); return; }
        openConfirmDialog({
          title: '创建项目目录后重试批准？',
          note: '两步：先创建 projects/proj-' + key + '/（幂等），再批准提案；第一步失败不会批准。',
          body: '<div class="src">' + esc(key) + '</div>' +
            '<div class="notice">' + esc(t('apv.destructive2')) + '</div>',
          okLabel: '创建并重试批准',
          onOk: function () { createProjectThenApprove(p, key, state.lastApproveAllowStale === true, ''); }
        });
      });
    });
  }

  /* ================= 启动 ================= */

  /* 「刷新」是用户明确的意图：必须绕过宿主 45s TTL（?refresh=1），并清掉视图级缓存 */
  document.getElementById('refresh').addEventListener('click', function () { refreshAll(true); });

  /* 「返回」在标题区左侧：绑定一次即可（元素不在每次重渲染的 content 里） */
  document.getElementById('back-btn').addEventListener('click', function () { goBack(); });
  document.getElementById('parent-link').addEventListener('click', function () {
    var parent = naturalParent(currentRoute());
    if (parent) go(parent.view, parent.project, parent.tab);
  });

  document.getElementById('detail-toggle').addEventListener('click', function () {
    state.detailOpen = !state.detailOpen;
    try { localStorage.setItem('pm-detail-open', state.detailOpen ? '1' : '0'); } catch (e) {}
    renderDetail();
  });
  document.getElementById('detail-close').addEventListener('click', function () {
    state.detailOpen = false;
    try { localStorage.setItem('pm-detail-open', '0'); } catch (e) {}
    renderDetail();
  });

  document.getElementById('nav').addEventListener('click', function (e) {
    var b = e.target.closest('button[data-view]');
    if (b) go(b.getAttribute('data-view'));
  });

  window.addEventListener('hashchange', fromHash);
  window.addEventListener('message', function (e) {
    var m = e.data;
    if (m && m.type === 'pm-refresh') load(true);
  });

  /* 主题按钮由 theme.js 负责（三模式；内嵌读 DSH 已解析主题，独立读系统偏好）。 */

  /* 二次确认弹窗：确认后提交真实写命令（归档 / 延期） */
  var confirmDialog = document.getElementById('confirm-dialog');
  document.getElementById('confirm-form').addEventListener('submit', function (e) {
    var submitter = e.submitter;
    if (!submitter || submitter.value !== 'ok') return;
    e.preventDefault();
    var pending = state.pending;
    if (!pending) { confirmDialog.close(); return; }
    var run = pending.onOk;
    /* 不要在这里清 pending：onOk 可能因为校验失败而重新打开弹窗（例如「退回必须写原因」），
       清掉的话用户补完原因再点确认就什么都不会发生。下一次 openConfirmDialog 会覆盖它。 */
    confirmDialog.close();
    if (typeof run === 'function') run();
  });

  /* ================= task-265：初始系统提示词页（markup 照设计示例 ✓；委派到 document，视图无关 ✓） ================= */
  /* task-265 降级：**绝不**把 res.json() 的原始解析错弹给用户 ✗（旧实例上 404 返回 HTML ⇒ Unexpected end of JSON input ✗）。
     先看 res.ok 与 content-type ⇒ 失败返回**有类型的错误**（ENDPOINT_MISSING / HTTP_xxx + 人话 ✓）。 */
  function promptFetch(url, opts) {
    return fetch(url, opts || {}).then(function (res) {
      var ct = String((res.headers && res.headers.get && res.headers.get('content-type')) || '')
      if (!res.ok) return { ok: false, status: res.status, error: { code: res.status === 404 ? 'ENDPOINT_MISSING' : ('HTTP_' + String(res.status)), message: res.status === 404 ? t('prompt.epMissingVerbose') : (t('prompt.httpFailed') + ' ' + String(res.status)) } }
      if (ct.indexOf('json') < 0) return { ok: false, status: res.status, error: { code: 'NOT_JSON', message: t('prompt.epMissingVerbose') } }
      return res.json().then(function (j) { return { ok: true, status: res.status, body: j } },
        function () { return { ok: false, status: res.status, error: { code: 'BAD_JSON', message: t('prompt.epMissingVerbose') } } })
    }, function (e) { return { ok: false, status: 0, error: { code: 'NETWORK', message: t('prompt.networkFailed') } } })
  }

  function promptBlocksDraft() { return state.promptBlocks || blankBlocks() }
  function promptToast(msg) {
    var el = document.getElementById('toast')
    if (!el) return
    el.textContent = msg
    el.classList.add('on')
    setTimeout(function () { el.classList.remove('on') }, 2600)
  }
  /* ④「填充 ← 从已保存的提示词复制」：惰性拉一份"哪些项目已保存过"的索引（每次 GET 很小 ✓），
     打开下拉时刷新一次 ✓；保存成功后就地更新 ✓（避免"列表里没有我刚存的那个项目"✗）。 */
  function loadPromptIndex() {
    /* **capability 优先**：端点缺失 ⇒ 短路（零请求 ✓、不逐个 scope 扇出 ✗），顶部已有"端点缺失"人话提示 ✓；
       端点存在 ⇒ 只用**一次** GET /ui-pm/prompts ✓（清单接口为"已保存项目"专用 ✓）。 */
    var caps = { get: endpointListed('GET', '/ui-pm/prompt'), list: endpointListed('GET', '/ui-pm/prompts') }
    if (!caps.get && !caps.list) { state.promptIndexError = 'ENDPOINT_MISSING'; state.promptIndex = []; if (state.view === 'prompt') render(); return Promise.resolve() }
    if (!caps.list) { state.promptIndexError = 'LIST_MISSING'; state.promptIndex = []; if (state.view === 'prompt') render(); return Promise.resolve() }
    return promptFetch('/ui-pm/prompts', { headers: { accept: 'application/json' } }).then(function (r) {
      if (!r.ok) { state.promptIndexError = r.error.code; state.promptIndex = []; if (state.view === 'prompt') render(); return }
      var items = (r.body && r.body.data && r.body.data.items) || []
      state.promptIndexError = null
      state.promptIndex = items.map(function (x) { return { key: x.scope, exists: true, rev: x.revision || 0, at: x.updatedAt || null } })
      if (state.view === 'prompt') render()
    })
  }
  function promptIndexHas(key, rev) {
    var list = state.promptIndex || []
    for (var i = 0; i < list.length; i++) if (list[i].key === key) { list[i].rev = rev; list[i].exists = true; return }
    list.push({ key: key, exists: true, rev: rev })
    state.promptIndex = list
  }
  /* 载入该项目的提示词（GET，读拆平后的 data.{exists,revision,blocks,updatedAt} ✓）；失败显式（不静默 ✓）*/
  /* 用户 2026-10-20 真 bug：预览里的引用文档永远"没有返回展开结果" ——
     ① 请求没带 &render=1（后端按设计不展开 ✗）② render 结果拿到了没人存（state.promptDocs 从未赋值 ✗）
     ⇒ 这里请求带 render=1，并解析 data.render.blocks（name 为主键、expression 兜底）+ render.text 按 "# 块名" 分块正文 ✓ */
  function promptDocsFromRender(d) {
    var docs = {}
    var rb = (d && d.render && d.render.blocks) || []
    var renderText = String((d && d.render && d.render.text) || '')
    var chunks = {}
    if (renderText) {
      var lines = renderText.split('\n')
      var cur = null, buf = []
      var flush = function () { if (cur !== null) { chunks[cur] = buf.join('\n').trim(); cur = null; buf = [] } }
      lines.forEach(function (l) {
        if (l.indexOf('# ') === 0) { flush(); cur = l.slice(2).trim() }
        else buf.push(l)
      })
      flush()
    }
    rb.forEach(function (x) {
      if (!x) return
      var name = String(x.name || '').trim()
      var rec = { ok: x.ok !== false, reason: String(x.reason || ''), path: String(x.path || ''),
        lines: x.lines == null ? null : x.lines, bytes: x.bytes == null ? null : x.bytes,
        kb: x.bytes == null ? null : Math.round(x.bytes / 102.4) / 10,
        truncated: x.truncated === true, real: String(x.path || x.expression || ''),
        text: chunks[name] || '' }
      if (name) docs[name] = rec
      var ex = String(x.expression || '').trim()
      if (ex) docs[ex] = rec
    })
    return { docs: docs, hasRender: rb.length > 0 || renderText !== '' }
  }
  /* 载入一条导出记录（供页面内确认框与直接载入共用）：
     跨项目 ⇒ 先切 state.project、清草稿，等该项目 prompt 读回（建立保存基线/rev），再把记录块放上去
     （⇒ 计数行「有未保存的改动」，保存写回**该项目**）✓ */
  function promptLoadLibraryRecord(rec) {
    if (!rec) return
    var applyRec = function () {
      var bs = (rec.blocksData && rec.blocksData.length) ? rec.blocksData.map(function (b) {
        return { id: undefined, name: b.name, kind: b.kind || 'text', include: b.include || '', tip: '', ph: '', text: b.text || '' }
      }) : null
      if (!bs) { promptToast(t('prompt.libLoadEmpty')); return }
      state.promptBlocks = bs
      state.promptOpen = 0
      promptToast(format(t('prompt.libLoadedToast'), { p: String(rec.project || '') }))
      render()
    }
    var cross = !!(rec.project && String(rec.project) !== String(promptPageState().key || ''))
    if (cross) {
      state.project = String(rec.project)
      state.promptBlocks = null
      state.promptSaved = undefined
      state.promptRev = 0
      state.promptExists = false
      state.promptSavedAt = null
      state.promptOpen = -1
      state.promptLoading = true
      state.promptConflict = null
      state.promptLoadedFor = null
      state.promptDocs = {}
      state.promptSavedIncludes = null
      render()
      loadPromptPage(state.project).then(applyRec)['catch'](function () { applyRec() })
    } else applyRec()
  }
  /* 切项目（唯一入口）：重置草稿/基线 → render → 读回该项目 prompt ✓
     有未保存改动时**先弹确认框**（用户 2026-10-20 改进①：不许静默丢草稿 ✗）*/
  function promptSwitchProject(key) {
    if (!key) return
    state.project = String(key)
    state.promptBlocks = null
    state.promptSaved = undefined
    state.promptRev = 0
    state.promptExists = false
    state.promptSavedAt = null
    state.promptOpen = -1
    state.promptLoading = true
    state.promptConflict = null
    state.promptLoadedFor = null
    state.promptSavedIncludes = null
    state.promptDocs = {}
    render()
    loadPromptPage(String(key))
  }
  /* 库筛选/搜索的**局部刷新**：只换 #libCards + #libCount ——
     用户 2026-10-20 真 bug：输入时整页 render() ⇒ 搜索框重建、焦点丢失、光标跳到页面开头 ✗ */
  function promptLibPatch() {
    var st = promptPageState()
    var cardsEl = document.getElementById('libCards')
    if (cardsEl) cardsEl.innerHTML = libCardsHtml(st)
    var cntEl = document.getElementById('libCount')
    if (cntEl) cntEl.textContent = format(t('prompt.libCount'), { n: (st.lib || []).length })
  }
  /* 已保存的提示词（库）：GET /ui-pm/prompt-exports ⇒ state.promptLib（派生物，不写 projects/ ✓）
     ⚠️ 用户 2026-10-20 真 bug：此前把「筛选/搜索」也发给服务端（scope=<libProj>&q=<libQ>），
        而导出/删除后的刷新是**带当前筛选**拉的 ⇒ 缓存被服务端过滤过；之后切回「全部项目」只做客户端
        render（不再重取）⇒ 别的项目的记录就"消失"了（1851 那张 demo01 卡在 demo02 筛选后导出时丢了 ✗）。
     ⇒ 这里**永远拉全量**（scope=ALL、不带 q），筛选/搜索全部在前端 libCardsHtml 里做 ✓
        （数据是派生物、量小；若将来很大再给服务端分页，但不是现在的正确性隐患）*/
  function promptExportsLoad() {
    if (!endpointListed('GET', '/ui-pm/prompt-exports')) { state.promptLib = []; return Promise.resolve() }
    return promptFetch('/ui-pm/prompt-exports?scope=ALL&q=', { headers: { accept: 'application/json' } })
      .then(function (r0) {
        if (!r0.ok) { state.promptLib = []; return }
        var j = r0.body, dd = (j && j.data) || {}
        state.promptLib = dd.items || dd.records || []
        if (state.view === 'prompt') render()
      })['catch'](function () { state.promptLib = [] })
  }
  /* 内部记录/25 14:04 版：导出项目标签 / 建议路径 / 摘要 / org 序列化（照示例口径 ✓）*/
  function promptFmtStamp() {
    var d = new Date(), z = function (n) { return (n < 10 ? '0' : '') + n }
    return '' + d.getFullYear() + z(d.getMonth() + 1) + z(d.getDate()) + '-' + z(d.getHours()) + z(d.getMinutes())
  }
  function promptExportProject() {
    var el = document.getElementById('expProj')
    return (el && el.value) ? String(el.value) : promptScopeKey()
  }
  function promptSuggestPath(project) {
    return '~/prompts/' + String(project || '') + '/prompt-' + promptFmtStamp() + '.md'
  }
  function promptFilledCount() {
    var bs = promptBlocksDraft()
    return bs.filter(function (b) {
      if (b.kind === 'include') return !!String(b.include || '').trim()
      return !!String(b.text || '').trim() || !!String(b.name || '').trim()
    }).length
  }
  function promptExportText(fmt) {
    if (fmt === 'org') {
      return promptBlocksDraft().map(function (b) {
        var head = '* ' + (b.name || '') + (b.id ? ' :' + b.id + ':' : '')
        return head + (b.kind === 'include' ? String.fromCharCode(10) + '#+PM_INCLUDE: ' + String(b.include || '') : String.fromCharCode(10) + String(b.text || ''))
      }).join(String.fromCharCode(10, 10))
    }
    return promptPreviewText()
  }
  function promptRefreshProjHint() {
    var el = document.getElementById('expProjHint')
    if (!el) return
    var chosen = promptExportProject(), cur = promptScopeKey()
    el.textContent = (chosen !== cur)
      ? format(t('prompt.expProjDiff'), { c: chosen, k: cur })
      : format(t('prompt.expProjSame'), { p: chosen })
  }
  function promptUpdateExpSummary() {
    var el = document.getElementById('expSummary')
    if (!el) return
    var fmtEl = document.getElementById('expFmt')
    var fmt = fmtEl ? String(fmtEl.value || 'md') : 'md'
    var text = promptExportText(fmt)
    var bytes = new Blob([text]).size
    var bs = promptBlocksDraft()
    el.textContent = format(t('prompt.expSummary'), { b: String(bytes), p: promptExportProject(), f: String(promptFilledCount()), t: String(bs.length) }) +
      (fmt === 'org' ? t('prompt.expSumOrg') : t('prompt.expSumMd'))
  }
  function promptFillExpProj() {
    var el = document.getElementById('expProj')
    if (!el) return
    var ps = (state.data && state.data.projects) || []
    var cur = promptScopeKey()
    var keys = ps.map(function (x) { return String(x.key) })
    if (cur && keys.indexOf(cur) < 0) keys.unshift(cur)
    el.innerHTML = keys.map(function (k) {
      return '<option value="' + esc(k) + '"' + (k === cur ? ' selected' : '') + '>' + esc(k) + '</option>'
    }).join('')
  }
  /* B3 真 bug（Lead 2026-10-20）：首屏 state.project 未解析 ⇒ GET /ui-pm/prompt?scope=&render=1 ⇒ 后端 400 ✗
     ⇒ scope 解析收敛到一处：state.project → 首个项目 key；都没有 ⇒ 返回 ''（调用方**不发请求**、页面给显式态 ✓）*/
  function promptScopeKey() {
    if (state.project) return String(state.project)
    var ps = (state.data && state.data.projects) || []
    if (!ps.length) ps = (state.projects || [])
    return ps.length ? String(ps[0].key || '') : ''
  }
  function loadPromptPage(key) {
    var scope = key || promptScopeKey()
    if (!scope) {
      /* 没有可用项目 ⇒ 不请求（避免 400 ✗），页面给「先选一个项目」显式态 ✓ */
      state.promptLoading = false
      state.promptNoProject = true
      if (state.view === 'prompt') render()
      return Promise.resolve()
    }
    state.promptNoProject = false
    return promptFetch('/ui-pm/prompt?scope=' + encodeURIComponent(scope) + '&render=1', { headers: { accept: 'application/json' } })
      .then(function (r0) {
        if (!r0.ok) {
          state.promptLoading = false
          var erMsg = String(r0.error.message || '')
          var erCode = String(r0.error.code || '')
          /* 人话：含 code 与 HTTP 状态（不只显示数字 400）；NOT_JSON/ENDPOINT_MISSING 原 message 已点名端点 ✓ */
          state.promptConflict = { currentRevision: null, draft: '',
            error: (erCode ? '[' + erCode + '] ' : '') + erMsg + (r0.status ? '（HTTP ' + String(r0.status) + '）' : ''),
            code: erCode, cas: false }
          if (state.view === 'prompt') render()
          return
        }
        var j = r0.body
        var d = (j && j.data) || {}
        state.promptExists = d.exists === true
        state.promptRev = d.revision || 0
        state.promptSavedAt = d.updatedAt || null
        /* 展开结果原样带过来（err/real/lines/kb/truncated）—— 丢字段会让四态原因渲染不出来（探针抓过 ✓）*/
        var savedBlocks = (d.blocks || []).map(function (b) {
          return { id: b.id, name: b.name, kind: b.kind || 'text', include: b.include || '', tip: '', ph: '', text: b.text || '',
            err: b.err, real: b.real, lines: b.lines, kb: b.kb, truncated: b.truncated === true }
        })
        /* 真 bug（Lead 2026-10-20 3082 实测）：没保存过提示词（exists:false）应回落**模板 5 块**（内部记录/25「没保存过才从模板起」），
           否则 blocks=[] ⇒ 计数「共 0 块」+ 预览空白 ✗。已保存但 0 块属异常数据 ⇒ 同样回模板（可解释、可编辑）。*/
        state.promptBlocks = savedBlocks.length ? savedBlocks : blankBlocks()
        state.promptSavedIncludes = {}
        state.promptBlocks.forEach(function (b) { if (b.kind === 'include') state.promptSavedIncludes[String(b.name || '')] = String(b.include || '') })
        var rr = promptDocsFromRender(d)
        state.promptDocs = rr.docs
        state.promptRenderAvailable = rr.hasRender
        state.promptRenderText = (d && d.render && d.render.text) || ''
        state.promptLoading = false
        state.promptSaved = JSON.stringify(state.promptBlocks)
        state.promptConflict = null
        if (state.promptExists) promptIndexHas(scope, state.promptRev)
        promptExportsLoad()
        if (state.view === 'prompt') render()
      })
      .catch(function (e) {
        state.promptLoading = false
        state.promptConflict = { currentRevision: null, draft: '', error: (e && e.message) || t('prompt.loadFailed') }
        if (state.view === 'prompt') render()
      })
  }
  /* ④「填充」（三选一）与「撤销改动」：都是"把编辑器换成某一份内容" —— 都是**副本**（不是引用 ✓）；
     当前有未保存改动 ⇒ 先确认（两步：先提示、再执行 ✓）。 */
  function applyFill(value, again) {
    if (!value) return
    var st = promptPageState()
    if (st.dirty && !again) {
      state.promptFillArmed = value
      promptToast(t('prompt.fillConfirm'))
      return
    }
    state.promptFillArmed = null
    if (value === 'blank') { state.promptBlocks = blankBlocks(); state.promptOpen = 0; render(); promptToast(t('prompt.fillToastBlank')); return }
    if (value === 'sample') { state.promptBlocks = sampleBlocks(); state.promptOpen = 0; render(); promptToast(t('prompt.fillToastSample')); return }
    if (value.indexOf('copy:') === 0) {
      var src = value.slice(5)
      fetch('/ui-pm/prompt?scope=' + encodeURIComponent(src), { headers: { accept: 'application/json' } })
        .then(function (r) { return r.json() })
        .then(function (j) {
          var d = (j && j.data) || {}
          var bs = (d.blocks || []).map(function (b) { return { id: undefined, name: b.name, kind: b.kind || 'text', include: b.include || '', tip: '', ph: '', text: b.text || '' } })
          if (!bs.length) { promptToast(t('prompt.fillEmpty')); return }
          state.promptBlocks = bs                      /* **副本**：id 清空（不是引用来源 ✓）*/
          state.promptOpen = 0
          if (src === st.key) { state.promptSaved = JSON.stringify(bs); state.promptRev = d.revision || state.promptRev; state.promptSavedAt = d.updatedAt || null }
          render()
          promptToast(src === st.key
            ? format(t('prompt.fillToastSelf'), { n: String(bs.length) })
            : format(t('prompt.fillToastCopy'), { p: src, n: String(bs.length), k: String(st.key || '') }))
        })
        .catch(function () { promptToast(t('prompt.fillEmpty')) })
    }
  }
  /* 内部记录/25 14:04：导出对话框（项目标签/格式/摘要）+ 库筛选搜索的事件 ✓ */
  document.addEventListener('change', function (ev) {
    var id = ev.target && ev.target.id
    if (id === 'expProj') {
      var pe = document.getElementById('expPath'); if (pe) pe.value = promptSuggestPath(promptExportProject())
      promptRefreshProjHint(); promptUpdateExpSummary()
    } else if (id === 'expFmt') { promptUpdateExpSummary() }
    else if (id === 'libProj') { state.promptLibProj = String(ev.target.value || 'ALL'); promptLibPatch() }
  })
  document.addEventListener('input', function (ev) {
    var id = ev.target && ev.target.id
    if (id === 'libQ') { state.promptLibQ = String(ev.target.value || ''); promptLibPatch() }
    else if (ev.target && ev.target.closest && ev.target.closest('#pmPromptPage') && document.getElementById('expSummary')) promptUpdateExpSummary()
  })
  document.addEventListener('click', function (ev) {
    var el = ev.target && ev.target.closest ? ev.target.closest('#addBlock,#save,#revert,#copy,#reload,#pvToggle,#export,#expCancel,#expGo,#delCancel,#delGo,#switchCancel,#switchGo,#libLoadCancel,#libLoadGo,[data-toggle],[data-kind],[data-lib-act],[data-del-block]') : null
    if (!el) return
    var st = promptPageState()
    var i = Number(el.getAttribute('data-i') || el.getAttribute('data-toggle'))
    /* 删除块（用户 2026-10-20）：先弹确认对话框 —— 只删**草稿里的这一块**，保存后才写回 prompt.org ✓ */
    if (el.hasAttribute && el.hasAttribute('data-del-block')) {
      var di = Number(el.getAttribute('data-del-block'))
      var bsD = promptBlocksDraft()
      state.promptDelBlock = di
      var whoEl = document.getElementById('dlgDelWho')
      if (whoEl) whoEl.textContent = format(t('prompt.delWho'), { i: String(di + 1), n: String((bsD[di] || {}).name || t('prompt.newBlockName')) })
      var dlgD = document.getElementById('dlgDelBlock')
      if (dlgD && dlgD.showModal) dlgD.showModal()
      return
    }
    if (el.id === 'delCancel') {
      state.promptDelBlock = null
      var dc = document.getElementById('dlgDelBlock'); if (dc && dc.close) dc.close()
      return
    }
    if (el.id === 'switchCancel') {
      state.promptPendingProj = null
      var sc2 = document.getElementById('dlgSwitchProj'); if (sc2 && sc2.close) sc2.close()
      render(); return
    }
    if (el.id === 'libLoadCancel') {
      state.promptPendingLoad = null
      var lc = document.getElementById('dlgLibLoad'); if (lc && lc.close) lc.close()
      return
    }
    if (el.id === 'libLoadGo') {
      var pl = state.promptPendingLoad
      state.promptPendingLoad = null
      var lg = document.getElementById('dlgLibLoad'); if (lg && lg.close) lg.close()
      if (pl) {
        var lrec = (state.promptLib || []).filter(function (x) { return String(x.id) === String(pl.id) })[0]
        if (lrec) promptLoadLibraryRecord(lrec)
      }
      return
    }
    if (el.id === 'switchGo') {
      var np = state.promptPendingProj
      state.promptPendingProj = null
      var sg2 = document.getElementById('dlgSwitchProj'); if (sg2 && sg2.close) sg2.close()
      if (np) promptSwitchProject(np)
      return
    }
    if (el.id === 'delGo') {
      var di2 = state.promptDelBlock
      var bsD2 = promptBlocksDraft()
      state.promptDelBlock = null
      var dg = document.getElementById('dlgDelBlock'); if (dg && dg.close) dg.close()
      if (di2 != null && bsD2[di2]) {
        bsD2.splice(di2, 1)
        state.promptBlocks = bsD2
        render()
        promptToast(format(t('prompt.delDone'), { n: String(di2 + 1) }))
      }
      return
    }
    if (el.id === 'addBlock') {
      var bs = promptBlocksDraft().concat([{ name: t('prompt.newBlockName'), kind: 'text', include: '', tip: '', ph: '', text: '' }])
      state.promptBlocks = bs
      state.promptOpen = bs.length - 1
      render(); return
    }
    if (el.id === 'save') { promptSave(); return }
    if (el.id === 'reload') { state.promptConflict = null; state.promptBlocks = null; state.promptSaved = undefined; state.promptLoading = true; render(); loadPromptPage(state.project); return }
    if (el.id === 'revert') {
      if (!state.promptRevertArmed) { state.promptRevertArmed = true; promptToast(t('prompt.revertConfirm')); return }
      state.promptRevertArmed = false
      state.promptBlocks = null
      state.promptSaved = undefined
      state.promptLoading = true
      render(); loadPromptPage(state.project); return
    }
    if (el.id === 'copy') {
      /* 用户 2026-10-20：点复制"没反应"（iframe/嵌入环境无 clipboard-write 权限 ✗）。
         三级降级 + **必有可见反馈**：① clipboard API ② execCommand('copy') ③ 自动选中预览文本并提示快捷键 */
      var txt = promptPreviewText()
      var okToast = function () { promptToast(t('prompt.copied')) }
      var selectAllPreview = function () {
        try {
          var pvEl = document.getElementById('preview')
          if (pvEl && window.getSelection) {
            var sel = window.getSelection(); sel.removeAllRanges()
            var r = document.createRange(); r.selectNodeContents(pvEl); sel.addRange(r)
          }
        } catch (e) {}
        promptToast(t('prompt.copySelected'))
      }
      var legacyCopy = function () {
        var ok = false
        try {
          var ta = document.createElement('textarea')
          ta.value = txt; ta.setAttribute('readonly', ''); ta.style.position = 'fixed'; ta.style.left = '-9999px'; ta.style.top = '0'
          document.body.appendChild(ta); ta.select()
          ok = document.execCommand('copy')
          document.body.removeChild(ta)
        } catch (e) { ok = false }
        if (ok) okToast(); else selectAllPreview()
      }
      if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(txt).then(okToast, legacyCopy)
      else legacyCopy()
      return
    }
    /* ---- 新 内部记录/25：预览折叠 / 保存到文件（导出）/ 文件库 ---- */
    if (el.id === 'pvToggle') {
      state.promptPvOpen = !(state.promptPvOpen !== false)
      el.setAttribute('aria-expanded', state.promptPvOpen ? 'true' : 'false')
      var pvEl2 = document.getElementById('preview')
      if (pvEl2) { if (state.promptPvOpen) pvEl2.removeAttribute('hidden'); else pvEl2.setAttribute('hidden', '') }
      el.textContent = state.promptPvOpen ? t('prompt.pvCollapse') : t('prompt.pvExpand')
      return
    }
    if (el.id === 'export') {
      var dlg = document.getElementById('dlgExport')
      if (dlg) {
        promptFillExpProj()
        var pip = document.getElementById('expPath')
        if (pip) pip.value = promptSuggestPath(promptExportProject())
        promptRefreshProjHint()
        promptUpdateExpSummary()
        if (dlg.showModal) dlg.showModal(); else dlg.setAttribute('open', '')
      }
      return
    }
    if (el.id === 'expCancel') { var d0 = document.getElementById('dlgExport'); if (d0 && d0.close) d0.close(); return }
    if (el.id === 'expGo') {
      var fmtEl = document.getElementById('expFmt')
      var fmt = fmtEl ? String(fmtEl.value || 'md') : 'md'
      var pathEl = document.getElementById('expPath')
      var pathVal = pathEl ? String(pathEl.value || '').trim() : ''
      if (!pathVal) { promptToast(t('prompt.expEmptyPath')); return }
      var text = promptExportText(fmt)
      var segs = pathVal.split('/')
      var name = segs[segs.length - 1] || 'prompt'
      if (!/\.[A-Za-z0-9]+$/.test(name)) name = name + '.' + fmt
      var bytes = new Blob([text]).size
      try {
        var mime = fmt === 'md' ? 'text/markdown' : 'text/plain'
        var blob = new Blob([text], { type: mime + ';charset=utf-8' })
        var a = document.createElement('a')
        a.href = URL.createObjectURL(blob); a.download = name
        document.body.appendChild(a); a.click(); document.body.removeChild(a)
        setTimeout(function () { try { URL.revokeObjectURL(a.href) } catch (e) {} }, 1000)
      } catch (e) {}
      var proj = promptExportProject()
      /* 路由 POST 契约（2026-10-20 真机 400 实测）：只接受
         scope/path/name/fmt/text/snapshot/blocksData/idempotencyKey 八个字段 ——
         · 带 project/bytes/blocks ⇒ 400 UNKNOWN_FIELDS（record.project 由 scope 映射 ✓）
         · blocksData 必须是 **JSON 字符串**（数组 ⇒ 400 "blocksData must be a string"）*/
      var recBody = { scope: proj, path: pathVal, name: name, fmt: fmt, text: text,
        snapshot: text.slice(0, 2000),
        blocksData: JSON.stringify(promptBlocksDraft().map(function (b) { return { name: b.name, kind: b.kind, include: b.include || '', text: b.text || '' } })),
        idempotencyKey: 'exp-' + String(Date.now()) + '-' + Math.random().toString(36).slice(2, 8) }
      if (endpointListed('POST', '/ui-pm/prompt-exports')) {
        promptFetch('/ui-pm/prompt-exports', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(recBody) })
          .then(function (r) { promptToast(r && r.ok ? format(t('prompt.exportedOk'), { path: pathVal }) : t('prompt.exportDegraded')); promptExportsLoad() })
          .catch(function () { promptToast(t('prompt.exportDegraded')) })
      } else {
        promptToast(t('prompt.exportDegraded') + ' GET/POST /ui-pm/prompt-exports')
      }
      var dd = document.getElementById('dlgExport'); if (dd && dd.close) dd.close()
      return
    }
    if (el.hasAttribute('data-lib-act') && el.getAttribute('data-lib-act') === 'del') {
      var lid = el.getAttribute('data-id') || ''
      if (lid && endpointListed('DELETE', '/ui-pm/prompt-exports/:id')) {
        promptFetch('/ui-pm/prompt-exports/' + encodeURIComponent(lid), { method: 'DELETE' })
          .then(function () { promptToast(t('prompt.libDeletedToast')); promptExportsLoad() })
          .catch(function () { promptToast(t('prompt.libDeletedToast')) })
      } else promptToast(t('prompt.libDeleteNoEndpoint'))
      return
    }
    if (el.hasAttribute('data-lib-act') && el.getAttribute('data-lib-act') === 'load') {
      var lid2 = el.getAttribute('data-id') || ''
      var rec = (state.promptLib || []).filter(function (x) { return String(x.id) === String(lid2) })[0]
      if (!rec) return
      var crossProject = !!(rec.project && String(rec.project) !== String(st.key || ''))
      if (!st.dirty && !crossProject) { promptLoadLibraryRecord(rec); return }
      /* 用户 2026-10-20：确认框换成**页面内对话框**（与删除框同构），不再用浏览器原生 confirm() ✗ */
      state.promptPendingLoad = { id: String(rec.id || '') }
      var lw = document.getElementById('dlgLoadWho')
      if (lw) lw.textContent = format(t('prompt.libLoadWho'), {
        n: String(rec.name || rec.path || rec.id || ''),
        p: String(rec.project || '-'),
        k: String(st.key || '-')
      })
      var lb = document.getElementById('dlgLoadBody')
      if (lb) lb.textContent = (st.dirty && crossProject) ? t('prompt.libLoadBodyBoth')
        : (crossProject ? t('prompt.libLoadBodyCross') : t('prompt.libLoadBodyDirty'))
      var ld = document.getElementById('dlgLibLoad')
      if (ld && ld.showModal) ld.showModal()
      return
    }
    if (el.hasAttribute('data-toggle')) {
      state.promptRevertArmed = false
      state.promptOpen = (Number(state.promptOpen) === i) ? -1 : i
      render(); return
    }
    if (el.hasAttribute('data-kind')) {
      var bs2 = promptBlocksDraft()
      if (bs2[i]) bs2[i].kind = el.getAttribute('data-kind')
      state.promptBlocks = bs2
      state.promptOpen = i
      render(); return
    }
  })
  document.addEventListener('change', function (ev) {
    var el = ev.target
    if (!el || !el.id) return
    if (el.id === 'proj') {
      var nextProj = String(el.value || '')
      if (!nextProj || nextProj === String(state.project || '')) return
      var stP = promptPageState()
      if (stP.dirty) {
        /* 有未保存改动 ⇒ 弹页面内确认框（不是原生 confirm，样式与删除框一致 ✓），先不切 */
        state.promptPendingProj = nextProj
        var swWho = document.getElementById('dlgSwitchWho')
        var curKey = String(stP.key || state.project || '')
        if (swWho) swWho.textContent = format(t('prompt.switchWho'), { k: curKey, n: nextProj })
        var swDlg = document.getElementById('dlgSwitchProj')
        if (swDlg && swDlg.showModal) swDlg.showModal()
        el.value = curKey   /* 下拉回退到当前项目；确认后再切 */
        return
      }
      promptSwitchProject(nextProj)
      return
    }
    if (el.id === 'fillFrom') {
      var v = el.value
      el.value = ''
      if (state.promptFillArmed === v) applyFill(v, true)
      else applyFill(v, false)
    }
  })
  document.addEventListener('input', function (ev) {
    var el = ev.target
    if (!el || !el.getAttribute) return
    if (el.hasAttribute('data-name')) {
      var i1 = Number(el.getAttribute('data-name'))
      var a = promptBlocksDraft()
      if (a[i1]) a[i1].name = el.value
      state.promptBlocks = a
      refreshPromptChrome()
      /* 就地更新**该行**的块名警告（空名/重名）—— 只在渲染时算的话，用户敲字时看不到警告 ✗（探针抓过 ✓）*/
      var row = el.closest ? el.closest('.row') : null
      if (row) {
        var w = nameWarn(a, i1)
        var box = row.querySelector('.namewarn')
        var seg = row.querySelector('.seg')
        if (w && !box) { box = document.createElement('div'); box.className = 'namewarn'; (seg && seg.parentNode ? seg.parentNode : row).insertBefore(box, seg || null) }
        if (w) box.textContent = w
        else if (box) box.parentNode.removeChild(box)
      }
      return
    }
    if (el.hasAttribute('data-inc')) {
      var i2 = Number(el.getAttribute('data-inc'))
      var b2 = promptBlocksDraft()
      if (b2[i2]) b2[i2].include = el.value
      state.promptBlocks = b2
      try {
        if (state.promptDocs) { var nm2 = String((b2[i2] || {}).name || ''); if (state.promptDocs[nm2]) delete state.promptDocs[nm2] }
        var pv = document.getElementById('preview')
        if (pv) {
          var stt = promptPageState()
          pv.textContent = buildPreview(stt.blocks, stt.docs, { savedIncludes: stt.savedIncludes })
        }
      } catch (e) {}
      refreshPromptChrome(); return
    }
    if (el.hasAttribute('data-i')) {
      var i3 = Number(el.getAttribute('data-i'))
      var c2 = promptBlocksDraft()
      if (c2[i3]) c2[i3].text = el.value
      state.promptBlocks = c2
      refreshPromptChrome()
    }
  })
  document.addEventListener('focusin', function (ev) {
    var el = ev.target
    if (el && el.id === 'fillFrom' && !state.promptIndexLoaded) { state.promptIndexLoaded = true; loadPromptIndex() }
  })
  /* 只刷新"外壳"（计数行 + 按钮可用性），不动编辑器 ⇒ 光标不丢 ✓ */
  function refreshPromptChrome() {
    var el = document.getElementById('count');
    if (!el) return;
    var st = promptPageState();
    el.innerHTML = promptCountHtml(st, st.blocks);
    var saveBtn = document.getElementById('save');
    if (saveBtn) saveBtn.disabled = !(st.dirty && st.caps.put);
    var revBtn = document.getElementById('revert');
    if (revBtn) revBtn.disabled = !st.dirty;
  }

  function promptPreviewText() {
    return buildPreview(promptBlocksDraft(), state.promptDocs || {});
  }

  /* task-265 slice③：保存（CAS + 审计）。契约 §6：PUT /ui-pm/prompt body {scope, blocks, expectedRevision, reason?, idempotencyKey}；
       失败 409 + currentRevision ✓；路由层 actor **必填**（human ✓）；**每个块原样回传 :ID:**（省略 = 服务端读成删块 ⇒ 422 ✓）。
       每次"保存"生成**新 key**（同一次重试沿用同一个 ✓，不跨次复用 ✗）。 */
  function promptSave() {
    var st = promptPageState();
    if (!st.dirty || !st.caps.put) return;
    var key = 'prompt-save-' + String(Date.now()) + '-' + Math.random().toString(36).slice(2, 8);
    var body = {
      scope: st.key,
      actor: 'human',
      expectedRevision: st.serverRev || 0,
      idempotencyKey: key,
      blocks: st.blocks.map(function (b) {
        return { id: b.id, name: b.name, kind: b.kind, include: b.include || '', text: b.text || '' };
      })
    };
    state.promptSaving = true;
    /* ⚠️ 必须用**绝对路径** '/ui-pm/prompt' ✗：相对路径会按页面地址 /ui-pm/app/index.html 解析成
       /ui-pm/app/ui-pm/prompt ⇒ 服务端 400「path escapes the workbench directory」✗
       （夹具测试之所以"过"，是因为夹具在 fetch 的**原始 URL** 层短路 ✓ ⇒ 掩盖了这个真 bug ✓ —— 真路由探针一次就照出来了 ✓）。 */
    fetch('/ui-pm/prompt', { method: 'PUT', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) })
      .then(function (resp) {
        return resp.json().then(function (j) { return { status: resp.status, body: j }; });
      })
      .then(function (r) {
        state.promptSaving = false;
        var d = (r.body && r.body.data) || {};        /* **拆平后的一层** ✓（不是 data.data ✓）*/
        if (r.status === 409) {
          /* 冲突三条：① 明说"别人先改了（当前 revision N）"② 给重新载入入口 ③ **绝不自动覆盖、草稿不静默丢** ✓ */
          state.promptConflict = {
            currentRevision: d.currentRevision == null ? null : d.currentRevision,
            draft: JSON.stringify(st.blocks, null, 1)      /* 把用户刚打的草稿**留一份可复制的** ✓ */
          };
          render(); return;
        }
        if (!r.body || r.body.ok !== true) {
          state.promptConflict = { currentRevision: null, draft: JSON.stringify(st.blocks, null, 1), error: (d && d.message) || ('HTTP ' + String(r.status)) };
          render(); return;
        }
        /* 成功：文件级 revision 为准刷新 ✓；保存后基线=当前（"无改动"随之出现 ✓）*/
        state.promptConflict = null;
        state.promptRev = (d.revision == null) ? state.promptRev : d.revision;
        state.promptExists = true;
        state.promptSaved = JSON.stringify(st.blocks);
        render();
      })
      .catch(function (e) {
        state.promptSaving = false;
        state.promptConflict = { currentRevision: null, draft: JSON.stringify(st.blocks, null, 1), error: (e && e.message) || String(e) };
        render();
      });
  }

  /* 提案弹窗：两选一 + 复制指令 + 人工提交 */
  document.getElementById('proposal-form').addEventListener('change', function (ev) {
    var t = ev.target;
    if (t && t.name === 'proposal-mode') setProposalMode(t.value);
  });
  document.getElementById('proposal-form').addEventListener('submit', function (ev) {
    var submitter = ev.submitter;
    if (!submitter || submitter.value !== 'ok') return;
    ev.preventDefault();
    submitProposalForm();
  });
  document.getElementById('ai-copy').addEventListener('click', function () {
    copyText(document.getElementById('ai-instruction').value, 'ai-copy-status');
  });

  /* ---------- 执行准备向导：弹窗按钮与草稿 ---------- */

  /* 只读当前可见输入刷新草稿（不切步骤） */
  function captureExecStepSoft() {
    if (!state.execTask) return;
    var pick = function (id) { var el2 = document.getElementById(id); return el2 ? el2.value : null; };
    var v;
    v = pick('exec-project'); if (v !== null) { if (v !== state.execDraft.project) { state.execDraft.workspace = ''; state.execDraft.session = ''; state.execData.workspaceContext = null; } state.execDraft.project = v; }
    v = pick('exec-note'); if (v !== null) state.execDraft.note = v;
    v = pick('exec-instance'); if (v !== null) state.execDraft.instance = v;
    v = pick('exec-session'); if (v !== null && v) state.execDraft.session = v;
    var boxes = document.querySelectorAll ? document.querySelectorAll('[data-exec-memory]') : [];
    if (boxes && boxes.length) {
      state.execDraft.memoryRefs = [];
      Array.prototype.forEach.call(boxes, function (b) { if (b.checked) state.execDraft.memoryRefs.push(b.getAttribute('data-exec-memory')); });
    }
    saveExecDraft();
  }

  var execDialog = document.getElementById('exec-dialog');
  document.getElementById('exec-next').addEventListener('click', execNext);
  document.getElementById('exec-prev').addEventListener('click', execPrev);
  document.getElementById('exec-save').addEventListener('click', saveExecutionConfig);
  document.getElementById('exec-copy').addEventListener('click', function () {
    var ta = document.getElementById('exec-handoff');
    var fromBox = ta && ta.value ? ta.value : '';
    var text = fromBox || (((state.execData || {}).handoff || {}).text || '');
    if (!text) return;
    copyText(text, 'exec-status');
  });
  document.getElementById('exec-close').addEventListener('click', function () {
    captureExecStepSoft();
    execDialog.close();
  });
  document.getElementById('exec-discard').addEventListener('click', function () {
    if (!state.execTask) return;
    clearExecDraft(state.execTask.id);
    state.execDraftRestored = false;
    state.execDraft = { project: state.execTask.project, workspace: '', instance: '', session: '', memoryRefs: [], note: '' };
    state.execStep = 1;
    renderExec();
  });
  document.getElementById('exec-body').addEventListener('input', captureExecStepSoft);
  document.getElementById('exec-body').addEventListener('change', captureExecStepSoft);

  /* 新建任务对话框（task-90）：原先没人接 submit，method="dialog" 只是把窗口关掉 —— 一个请求都不发 */
  document.getElementById('task-form').addEventListener('submit', function (e) {
    var submitter = e.submitter;
    if (!submitter || submitter.value !== 'ok') return;   /* 取消 / × → 交给 method="dialog" 默认行为关闭，零请求 */
    e.preventDefault();
    createTaskFromDialog(state.taskCreateProject);
  });

  var capDialog = document.getElementById('capture-dialog');
  document.getElementById('capture-form').addEventListener('submit', function (e) {
    var submitter = e.submitter;
    if (!submitter || submitter.value !== 'ok') return;
    e.preventDefault();
    var text = document.getElementById('capture-text').value.trim();
    var status = document.getElementById('capture-status');
    if (!text) { status.textContent = t('sr.emptyContent'); status.className = 'dialog-status err'; return; }
    status.className = 'dialog-status';
    status.textContent = t('sx.writing');
    capture(text).then(function (res) {
      if (res.ok) {
        status.className = 'dialog-status ok';
        status.textContent = res.note;
        document.getElementById('capture-text').value = '';
        load(true, true);
        setTimeout(function () { if (capDialog.open) capDialog.close(); status.textContent = ''; }, 1400);
      } else {
        status.className = 'dialog-status err';
        status.textContent = t('sx.writeFailedPrefix') + res.error;
      }
    });
  });

  try { state.detailOpen = localStorage.getItem('pm-detail-open') !== '0'; } catch (e) {}

  /* 第三列宽度：用户拖过的值优先；收起/展开不改动它（收起只是 CSS 隐藏第三列） */
  try { state.detailWidth = parseStoredWidth(localStorage.getItem('pm-detail-width')); } catch (e) { state.detailWidth = null; }
  wireDetailResizer();
  wireProjectControls();
  /* 对话框的「×」与「取消」：type=button + data-dialog-close，统一在这里关（不产生任何写请求） */
  Array.prototype.forEach.call(document.querySelectorAll('[data-dialog-close]'), function (btn) {
    btn.addEventListener('click', function () {
      var dlgEl = document.getElementById(btn.getAttribute('data-dialog-close'));
      if (dlgEl && dlgEl.close) dlgEl.close();
    });
  });

  wireProposalEditorControls();
  watchAutofill();   /* 动态插入的任何表单也会被扫到 */
  configureWrite({ render: render });   /* pm-write 用注入的 render 刷新界面（不反向 import app.js） */

  /* 左侧栏折叠：读持久化并绑定按钮（键盘可达，button 原生 Enter/Space） */
  try { state.sidebarCollapsed = localStorage.getItem('pm-sidebar-collapsed') === '1'; } catch (e) { state.sidebarCollapsed = false; }
  state.taskExpanded = loadTaskExpanded();   /* 任务卡展开状态：按 task id 存集合 */
  (function () {
    var btn = document.getElementById('sidebar-toggle');
    if (btn && btn.addEventListener) btn.addEventListener('click', toggleSidebar);
  })();
  applySidebarCollapsed();
  /* task-209：原生 <details> 的展开态只活在 DOM 里 → 捕获阶段监听 toggle 写回 state.folds
     （toggle 事件**不冒泡**，必须用捕获 true；只挂这一次，不在 render 里重复挂）。 */
  document.addEventListener('toggle', function (ev) {
    var hit = foldKeyFromTarget(ev.target);
    if (!hit) return;
    setFold(folds(), hit.key, hit.open);
  }, true);
  /* task-204：语言开关（在"主题"旁边）——只改文案与 documentElement.lang，不重载页面、不复制 app */
  var langBtn = document.getElementById('lang-toggle');
  if (langBtn && langBtn.addEventListener) {
    langBtn.addEventListener('click', function () {
      var next = (document.documentElement.getAttribute('data-lang') === 'en') ? 'zh' : 'en';
      setLang(next);
      document.documentElement.setAttribute('data-lang', next);
      applyShell(document);
      /* 主题按钮/来源名由主题模块自己懒计算 → 调它自己的 refresh（不在别人的作用域里赋值） */
      if (window.PMTheme && window.PMTheme.refresh) window.PMTheme.refresh();
      render();   /* 视图标题/副标题等由 render 重建 */
    });
  }
  window.addEventListener('resize', function () {
    var b = document.getElementById('project-board');
    if (b && b.__syncArrows) b.__syncArrows();
  });
  applyDetailWidth();
  window.addEventListener('resize', function () { applyDetailWidth(); });

  /* 测试/调试钩子：宽度纯函数可被直接断言（不参与业务逻辑） */
  /* 测试/调试钩子：**仅供 harness / CDP 读**，不是公开 API。
     只暴露这一个纯渲染函数（taskHistoryHtml）；刻意**不暴露 state**，避免测试依赖内部可变单例。 */
  window.PMHistoryHtml = taskHistoryHtml;
  /* 同上：证据渲染（三形态都带 .task-evidence 容器），仅供 harness / CDP 读。 */
  window.PMEvidenceHtml = criterionEvidenceHtml;

  window.PMDetailWidth = {
    clamp: clampDetailWidth, parse: parseStoredWidth,
    defaults: { min: DETAIL_W_MIN, default: DETAIL_W_DEFAULT, wide: DETAIL_W_WIDE, absMax: DETAIL_W_ABS_MAX }
  };

  fromHash();
  load(false);
})();
