/* ===================== pm-format.js =====================
 * 零构建扁平 ESM：纯格式化叶子（task-91 阶段 1，只搬代码不改行为）。
 * 依赖：无（不 import 其它模块，也不碰 DOM）。
 *
 * i18n（B0，2026-10-15）：本文件里的表（TASK_STATUS / MEMORY_TYPES / BOARD_COLUMN_TITLES）与
 * historyTimeText 的兜底句是**运行时中文**。为了让它们能随语言切换，同时**不破坏"纯叶子、不 import"**的契约
 * （verify_flat_esm_l2.py 对本文件是**文本抽取 eval**，加 import 会直接破它 ✗），这里采用**注入式翻译器**：
 *      app.js 启动时调用 bindTranslator(t)（app.js 本来就 import pm-i18n ✓）；
 *      未 bind 时 tt(key, fallback) **逐字返回 fallback** ⇒ 行为与改造前完全一致 ✓（既有消费者/测试/harness 零变化）。
 * ⚠️ 请勿顺手改成 import { t } —— 那会破叶子契约与文本抽取 eval，并让本批"边做边长"（选 A 的理由见 内部记录/05）。
 * ⚠️ tt() 的**键名打错会静默回落成中文**（en 页会看到中文，而覆盖率/空 en 判据都抓不到）⇒ B0 判据专门静态抽取
 *      本文件所有 tt('<key>', …) 的字面量，断言每个 key 都在键表里且 zh/en 非空 ✓。
 */

/* fillTemplate：占位符替换的**本地私有**实现。（不能叫 format、也不能导出：selfcheck 的
   "顶层函数重名" 守卫会抓 pm-format.js:format ↔ pm-i18n.js:format —— 文本抽取 eval 会把两份源码拼在一个作用域里 ✗） */
function fillTemplate(template, params) {
    return String(template === null || template === undefined ? '' : template)
      .replace(/\{(\w+)\}/g, function (m, name) { return Object.prototype.hasOwnProperty.call(params || {}, name) ? String(params[name]) : ''; });
  }

export function esc(s) {
    return String(s === null || s === undefined ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

export function pad(n) { return (n < 10 ? '0' : '') + n; }

  /* pm 的 :LOGBOOK: 与「补充 / 修订」块头用的是 org 时间戳：`2026-10-12 Mon 16:12`，
     也可能是区间 `2026-10-12 Mon 16:12-16:40`。V8 的 Date.parse 认不出（NaN），
     所以 localTime 先试 org 解析；解析不出来返回空串，由调用方显示「时间未返回」。 */
export var ORG_TIME_RE = /^(\d{4})-(\d{2})-(\d{2})(?:\s+[A-Za-z]{3})?\s+(\d{1,2}:\d{2})(?:-(\d{1,2}:\d{2}))?/;

export function orgTime(value) {
    var text = String(value === null || value === undefined ? '' : value).trim();
    var m = ORG_TIME_RE.exec(text);
    if (!m) return '';
    return m[1] + '-' + m[2] + '-' + m[3] + ' ' + m[4] + (m[5] ? '-' + m[5] : '');
  }

export function localTime(iso) {
    if (!iso) return '';
    var org = orgTime(iso);
    if (org) return org;
    var t = Date.parse(iso);
    if (isNaN(t)) return '';
    var d = new Date(t);
    return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()) +
      ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes());
  }

  /* 历史条目时间：org / ISO 都能显示；解析不出来就说「时间未返回」，绝不留空白 */
/* ---- i18n 注入点（见文件头说明）：幂等、可不调用；未绑定时一切回退原中文 ---- */
var TR = null;
export function bindTranslator(fn) { if (typeof fn === 'function') TR = fn; }
function tt(key, fallback) { return TR ? TR(key) : fallback; }

export function historyTimeText(at) {
    return localTime(at) || tt('fmt.timeNotReturned', '时间未返回');
  }

/* getter 表（批次 A 的 lesson A）：模块级常量直接 t() 会在加载期冻结语言 ⇒ 用 getter 在使用点求值。
   回退值**逐字等于**改造前的中文 ⇒ 未 bind 时输出与今天完全一致 ✓（API 形状不变：仍是 TASK_STATUS[..]）。 */
export var TASK_STATUS = {
    get INBOX() { return tt('status.INBOX', '收件箱'); },
    get TODO() { return tt('status.TODO', '待办'); },
    get NEXT() { return tt('status.NEXT', '下一步'); },
    get DOING() { return tt('status.DOING', '执行中'); },
    get WAITING() { return tt('status.WAITING', '等待'); },
    get BLOCKED() { return tt('status.BLOCKED', '阻塞'); },
    get REVIEW() { return tt('status.REVIEW', '待验收'); },
    get DONE() { return tt('status.DONE', '已完成'); },
    get CANCELLED() { return tt('status.CANCELLED', '已取消'); }
  };

export var MEMORY_TYPES = {
    get fact() { return tt('memtype.fact', '事实'); },
    get decision() { return tt('memtype.decision', '决策'); },
    get gotcha() { return tt('memtype.gotcha', '坑'); }
  };

  /* 列头 title：解释每个状态到底是什么意思（用户明确问过区别） */
export var BOARD_COLUMN_TITLES = {
    get todo() { return tt('boardcol.todo', '待办：已记录 / 已排期，还没开始做（INBOX / TODO = 未排期，NEXT = 已排期）'); },
    get doing() { return tt('boardcol.doing', '执行中：正在做（DOING）'); },
    get blocked() { return tt('boardcol.blocked', '受阻：在等外部（WAITING）或现在做不了、有明确解除条件（BLOCKED）'); },
    get review() { return tt('boardcol.review', '待验收：AI/系统已提交、等人验收（REVIEW）'); },
    get closed() { return tt('boardcol.closed', '已结束：人验收通过（DONE）或明确放弃（CANCELLED）—— 终态，默认折叠'); }
  };

export function boardColumnTitle(g) {
    /* 回退串里的**全角括号**也是文案（Lead 提醒③）⇒ 走键；en 用半角括号 */
    return BOARD_COLUMN_TITLES[g.key] || fillTemplate(tt('fmt.boardColFallback', '{label}（{key}）'), { label: g.label, key: g.key });
  }
