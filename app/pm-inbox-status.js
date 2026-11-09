/* pm-inbox-status.js —— 收件箱状态说明卡的**静态**内容（task-186；零依赖、不碰 DOM、不发请求）。
 *
 * 唯一来源：src/pm/inbox_ops.py 的常量
 *   STATUS_CAPTURED/TRIAGE/TASK_PROPOSED/TASK_CREATED/NOTE/ARCHIVED/SNOOZED/MERGED/DISMISSED（第 17-25 行）
 *   TERMINAL_STATUSES = {ARCHIVED, MERGED, DISMISSED}（第 47 行）
 * 含义取自 pm inbox 的真实行为（pm inbox --help + inbox_ops 的状态机注释第 50-51 行），每条都写明来源。
 * tests/frontend/pm-inbox-status.test.mjs 会**直接解析 src/pm/inbox_ops.py** 与本表逐条比对，防止凭印象漂移。
 */
export var SOURCE_FILE = 'src/pm/inbox_ops.py';

export var INBOX_STATUS_TABLE = [
  { key: 'CAPTURED', zh: '已捕获',
    meaning: '刚记下来、还没分流（新条目的默认状态）',
    source: 'pm capture / inbox.org 新条目；src/pm/inbox_ops.py:17' },
  { key: 'TRIAGE', zh: '分流中',
    meaning: '人开始处理它了（还在决定去向）',
    source: 'pm inbox set-status --to TRIAGE；src/pm/inbox_ops.py:18' },
  { key: 'TASK_PROPOSED', zh: '已提出任务计划',
    meaning: '已生成提案等批准；**批准后才创建正式任务**',
    source: 'pm proposal create（§5.3）；src/pm/inbox_ops.py:19' },
  { key: 'TASK_CREATED', zh: '已创建任务',
    meaning: '提案被批准、正式任务已建立',
    source: 'pm proposal approve；src/pm/inbox_ops.py:20' },
  { key: 'NOTE', zh: '已存为笔记',
    meaning: '存进 memory 候选区，**不进任务列表**',
    source: 'pm inbox note；src/pm/inbox_ops.py:21' },
  { key: 'ARCHIVED', zh: '已归档',
    meaning: '收起来不再跟进（**终止态**）',
    source: 'pm inbox archive；src/pm/inbox_ops.py:22' },
  { key: 'SNOOZED', zh: '已延期',
    meaning: '暂缓到 :PM_SNOOZE_UNTIL: 之后再处理（**不是终止态**）',
    source: 'pm inbox snooze --until；src/pm/inbox_ops.py:23' },
  { key: 'MERGED', zh: '已合并',
    meaning: '并入另一条记录（留 :PM_MERGED_INTO:；**终止态**）',
    source: 'pm inbox merge --into；src/pm/inbox_ops.py:24' },
  { key: 'DISMISSED', zh: '已丢弃',
    meaning: '明确不要了（必须给理由；**终止态**）',
    source: 'pm inbox dismiss --reason；src/pm/inbox_ops.py:25' }
];

export var TERMINAL_STATUSES = ['ARCHIVED', 'MERGED', 'DISMISSED'];

/** 状态机口径（inbox_ops.py:50-51 的注释，原样表达）：正常链 + 可跳去终止/延期的分支 */
export var STATE_MACHINE_NOTE = '正常链：CAPTURED → TRIAGE → TASK_PROPOSED → TASK_CREATED；' +
  'CAPTURED / TRIAGE / SNOOZED 也可以直接去 NOTE / ARCHIVED / SNOOZED / MERGED / DISMISSED。';

/*: 状态过滤下拉的值（task-191）：**9 个规范状态**（顺序与 src/pm/inbox_ops.py:41-45 的 KNOWN_STATUSES 一致）
 *  + 旧数据状态 LEGACY_UNTRACKED（放最后）。来源：src/pm/inbox.py:34 的 LEGACY_STATUS =
 *  「没有 :ID: 的旧 capture / 人手写的顶层列表项」——它是真实可出现的状态，所以下拉要留它。
 *  源码加状态而下拉没跟，tests/frontend/pm-inbox-status.test.mjs 会直接红。 */
export var LEGACY_STATUS = 'LEGACY_UNTRACKED';
export var INBOX_FILTER_STATUSES = INBOX_STATUS_TABLE.map(function (s) { return s.key; }).concat([LEGACY_STATUS]);

export function isTerminalStatus(key) {
  return TERMINAL_STATUSES.indexOf(String(key)) >= 0;
}

/** 说明卡的数据（纯数据；渲染在 app.js 里做，保持这个模块零 DOM） */
export function statusRows() {
  return INBOX_STATUS_TABLE.map(function (s) {
    return { key: s.key, zh: s.zh, meaning: s.meaning, source: s.source, terminal: isTerminalStatus(s.key) };
  });
}
