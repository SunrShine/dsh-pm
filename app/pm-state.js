/* ===================== pm-state.js =====================
 * 零构建扁平 ESM：全局 state **单例**（task-109 阶段 3 从 app.js 搬出）。
 * 关键：这是**同一个可变对象** —— 所有模块/视图共享它，不存在第二份状态；
 * 读写语义与搬出前逐字一致（含持久化字段 detailWidth / sidebarCollapsed / taskExpanded）。
 * 依赖：无（不 import 任何模块，也不碰 DOM）。
 */
export var state = {
    data: null, error: null,
    view: 'board',
    project: null,          // 项目 key
    tab: 'tasks',           // 项目页标签：tasks | cards | timeline | memory
    card: null,             // 选中的工作卡 session_id
    note: -1,               // 选中的 inbox 条目下标（相对 state.inbox.entries）
    detailOpen: true,
    detailWidth: null,      // 用户拖过的宽度（null = 用视图默认）；只存 localStorage('pm-detail-width')
    sidebarCollapsed: false, // 左侧栏折叠成 48px 图标条；只存 localStorage('pm-sidebar-collapsed')
    taskExpanded: {},        // 卡片展开的 task id 集合；只存 localStorage('pm-task-expanded')
    taskExtras: {},          // {taskId: {revision, teamTasks, dagEdges, loading, error}} —— 列表只给 count，展开时懒加载一次 task show
    q: '',                  // 收件箱搜索（客户端）
    inbox: null,            // {source:'endpoint'|'cards', path, count, entries, status, error}
    inboxStatus: '',        // 状态过滤（真实端点参数）
    inboxOrigin: '',        // 来源过滤（客户端）：'' = 全部 / 'human' / 'ai'
    inboxDetail: null,      // {id, data:{id,revision,status,text,annotations[],revisions[]}, error}
    busy: false,            // 写命令进行中
    credential: null,       // 最近一次成功写命令的 §5 凭据
    conflict: null,         // 最近一次 409（已自动重拉）
    writeError: null,       // 最近一次 422/502/400/404/网络失败
    idem: {},               // idempotencyKey：同一动作重试沿用同一个 key
    criterionIdUnsupported: false, // task-132：宿主路由拒绝 criterionId 时（UNKNOWN_FIELDS）粘性退回 index
    pending: null,          // 二次确认中的动作
    caps: undefined,        // /ui-pm/capabilities 结果：undefined=未取，null=不可用
    board: null,            // 当前项目的任务分组 {project, path, count, groups, error}
    task: null,             // 选中的任务 {project, id}
    taskDetail: null,       // 任务详情 {project, id, task, error}
    projectMemory: null,    // 项目页「项目记忆」标签
    projectBrief: null,     // 项目简报：{key, data:{project,brief,reason,message,path}, error}（只读投影）
    overview: null,         // 工作台跨项目任务概览
    overviewLoading: false,
    review: null,           // {items, errors, fetchedAt}
    reviewLoading: false,
    reviewSel: null,        // 选中的 REVIEW 任务 {project, id}
    reviewDetail: null,
    memory: null,           // {candidates, entries, error}
    memoryLoading: false,
    memorySel: null,        // {kind:'candidate'|'verified', id}
    discardNote: null,      // task-165：最近一次「丢弃候选」的结果 {id, reason, idempotent}
    approvedProposal: null, // task-168：最近一次批准的结果 {id, project, taskIds[], at}
    focusTask: null,        // task-168：渲染后要定位/高亮的卡 {project, id, at}
    memoryScope: '',        // 记忆列表的 scope 过滤
    contextScope: '',       // 上下文影响的 scope
    memoryType: '',         // 记忆类型过滤
    memoryShowDeprecated: false,
    execTask: null,         // 向导绑定的任务 {project,id,title,revision}
    execStep: 1,            // 1..6（只显示「第 N 步」，不做百分比/进度条）
    execDraft: null,        // {project,workspace,instance,session,memoryRefs[],note}
    execDraftRestored: false,
    execData: { workspaces: null, memories: null, sessions: null, config: null, handoff: null, error: null },
    proposals: null,
    projects: undefined,     // undefined=未加载 / null=端点未接入 / {items,error}；批准对话框的项目下拉用它
    projectCreate: null,     // 两段式的第一步结果（创建项目目录）
    proposalEdit: null,      // 提案「修改」编辑器的草稿：{title, changes[], risks[], actions[], srcRev}        // {items, error}：GET /ui-pm/proposals?status=PENDING
    proposalsLoading: false,
    proposal: null,         // 选中的提案 id
    proposalDetail: null,   // {id, proposal, error}
    staleRetried: false,    // STALE_PLAN 重试过一次（HTTP 路由未必转发 allow-stale）
    navStack: [],           // 应用内历史栈：go() 时把上一页压栈（浏览器 history 不用，因为直接刷新时它会退到站外）
    context: null           // /ui-pm/memory/context 结果
  }
