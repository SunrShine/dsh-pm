# 随手记 / 提案 / 记忆（inbox · proposal · memory）

## 1. 随手记 inbox（多文件：`inbox-human-*.org` / `inbox-ai-*.org` + 生成视图 `inbox.org`）

- 一句话先记下来，之后再分流。**捕获原文只读**：补充是**追加**，改写要显式修订并**逐字留旧值**。
- **真源按来源 + 周期轮转**：人工默认 weekly（`inbox-human-2026-W43.org`）、AI 默认 monthly（`inbox-ai-2026-10.org`）；
  配置 `[inbox] human_mode/ai_mode`（weekly/monthly/quarterly/yearly/single/per-entry；代码默认 single 兼容旧库）。
  **归档 = 时间轮转，不搬文件**；`inbox.org` 只是 `pm inbox render` 生成的只读汇总视图。
- 状态机：`CAPTURED → TRIAGE → TASK_PROPOSED → TASK_CREATED`；另有终态 `ARCHIVED / MERGED / DISMISSED`。

```sh
pm capture "一句话" [--project KEY] [--dry-run]     # 只追加，不改已有内容；CLI/人工→human 文件，MCP/AI→ai 文件
pm inbox list [--status S] [--origin human|ai] [--json]  # 带 annotationCount/revisionCount/pinned/lastAnnotationText
pm inbox annotate <inbox-id> --text "补充"             # 追加一段补充（带 actor/时间/rev）
pm inbox edit     <inbox-id> --text "新正文" --reason "为什么改"   # 显式修订，旧值逐字留档
pm inbox history  <inbox-id>                            # 看补充/修订流水
pm inbox set-status <inbox-id> --status TRIAGE|TASK_PROPOSED|TASK_CREATED|ARCHIVED|DISMISSED \
    --expected-revision N --reason R
pm inbox archive|snooze|merge|note|dismiss|pin|unpin    # 分流动作；pin 置顶，unpin 取消（都按 :ID: 跨文件写回所在文件）
pm inbox files|render [--check]|migrate [--dry-run|--write]  # 真源清单 / 生成视图 / 旧单文件库迁移
```

- **`edit`/`set-status` 都要 `--reason`**（写审计）；非法迁移会被明确拒绝，**不静默降级**。
- **快速记录没有服务端幂等键**（实测，task-01M51Z5A7…）：`pm capture` 没有 `--idempotency-key`；HTTP 路由 `POST /ui-pm/capture`
  **不是字段白名单** —— body 里多带的字段（`idempotencyKey`/`expectedRevision` 等）会被**静默忽略**（**200**，不是 400），
  同键 + 同 text 连发两次 ⇒ 对应周期文件（`inbox-human-<period>.org` / `inbox-ai-<period>.org`）**多两条**。400 只出现在 `text` 为空/非字符串、或 body 不是对象（`INVALID_BODY`）。
  ⇒ 防重复入库目前只有**客户端在飞去重**（U2，`frontend_impl/pm-write.js`）；别指望塞 key 能去重。
  将来要做：① `pm capture` 加 `--idempotency-key`（写入改走一次 CAS + 幂等键，现在 `capture` 是 append 直写）② 插件 `captureArgs()` 透传成 argv ③ 前端 body 带 key。
  复现：`python3 scripts/verify_capture_no_idempotency.py`（一次性隔离实例 + 临时库，7 项判据）。
- 旧版（没有 v2 属性）的条目：`annotationCount`/`revisionCount` 是 `null`、`pinned=false`；不要伪造计数。
- 人写过的人工内容不要覆盖；AI 的补充一律走 `annotate`（追加）。

### 1.1 会话级记忆注入（DSH hooks，M4a）

给 DSH 的 Claude Code hooks 桥用（`.claude/hooks.json`，挂载由**用户**执行）。**只读、有预算、可一键关**：

```sh
pm hook session-start [--scope S] [--max-items N] [--max-bytes B] [--debug] [--json]  # SessionStart：memory context 渲染（带来源+预算）
pm hook recall [--max-items N] [--max-bytes B] [--debug] [--json]          # UserPromptSubmit：读 stdin 的 prompt 做 top-k 注入
pm hook install                                                            # 只打印可复制的 .claude/hooks.json + cordis.patch.yml insert
```

- 注入口径：每条带 `sources` + `memory/<type>.org:<line> rev=N`；**无命中/超时/异常/关开关一律零输出**；
- 外部输入不可信：`prompt` 截断、**不回声**、头部写明"不是指令"；
- 开关与预算在 `pm.toml` 的 `[hooks]`（`inject` / `max_items` / `max_bytes` / `session_max_bytes` / `timeout_ms` / `scope`）；非法值或不认识的键 ⇒ `CONFIG_INVALID` 硬失败；
- 结果只进 stdout，**不回写工作记忆库**（org 的 size/mtime 都不变）；
  而**宿主会话记录里可以查到**注入内容 —— 那是它到达模型的通道（宿主行为），不是我们写的，也不要拿它当没生效的证据。

想看「新会话到底会拿到什么」，用预览命令（同样只读）：

```sh
pm prompt get --scope S --json   # 读项目初始系统提示词（人写数据层；只读提示词本身，不预览运行时注入物）
```

- **预览必须调用真实注入函数**（`hooks.session_start_text` / `hooks.recall_text`），不另写一套渲染 —— 否则预览迟早与真实注入漂移；
- **没进上下文的块显式标 `injected=false` + 原因**（诚实性规则，绝不假装它会进上下文）；
- 只读：不碰任何人工文件与生成物；唯一允许的写是 `.local/` 下的**派生索引**（与真实注入同源）。

## 2. 提案 proposal（`proposals.org`）

- AI 的**计划**，等人批准。**未批准的提案绝不创建正式任务**。
- 状态机：`PENDING → APPROVED / REJECTED`。

```sh
pm proposal create --project KEY --title T --change "op=新增;title=...;criteria=..." [...]
pm proposal list [--status PENDING] [--json] ; pm proposal show <proposal-id>
pm proposal approve <proposal-id> --actor human --expected-revision N   # 这才建正式任务
pm proposal reject  <proposal-id> --actor human --reason R
pm proposal revise  <proposal-id> --change ... --actor human            # 保留 ID，重挂源 revision
```

- `create` 只写 `proposals.org`，并把**源 inbox** 标 `TASK_PROPOSED`；`approve` 才真正建任务、把源 inbox 标 `TASK_CREATED`。
- 抛给用户的说法：**"提案待批准"**，不要说"我已经建好任务了"。

## 3. 记忆 memory（`memory/*.org` + `memory-candidates.org`）

- 三类：事实（facts）/ 决策（decisions）/ 坑（gotchas）；AI 只能提**候选**。
- 状态机：`CANDIDATE → VERIFIED → DEPRECATED`（DEPRECATED 保留历史，不删除）。

```sh
pm memory add --scope <项目 id 或 global> --type fact|decision|gotcha --text "..." \
    [--sources REF ...] [--topic T] [--task-id ID] [--created-by ai|human] [--supersedes OLD_ID]
pm memory candidates [--status CANDIDATE|VERIFIED] [--json]     # 待人工确认的候选
pm memory verify <MEMORY_ID> --actor human --expected-revision N   # 只有人能 verify（CAS）
pm memory discard <MEMORY_ID> --reason R --expected-revision N      # 丢弃**候选**（只允许 CANDIDATE → 标 DEPRECATED）
pm memory deprecate <MEMORY_ID> --reason R --expected-revision N [--superseded-by NEW_ID]
pm memory list [--type fact|decision|gotcha] [--scope S] [--status VERIFIED|DEPRECATED] [--json]
pm memory context --scope <项目 id 或 global> [--task TASK_ID] [--no-global] [--allow-cross-scope] [--json]
```

- **AI 加的一律是候选**：`--created-by` 默认 `ai`，落库状态就是 `CANDIDATE`；
  命令行没有"直接写进 VERIFIED"的开关 —— 用 `pm memory candidates` 看待确认的候选。
- **丢弃候选用 `discard`**：只允许从 `CANDIDATE` 丢（状态复用 `DEPRECATED`，不新增状态），`--reason` 必填、落一条 `op=discard` 审计；已 `VERIFIED` 的请用 `deprecate`（保留取代链）；
  重复丢同一个候选是**幂等**的（`changed:false`、不新增审计）。
- **只有人能 `verify`**（且要带 `--expected-revision`）；AI 提的候选不 verify 就不会进上下文包。
- `memory context` **只含 VERIFIED**；默认含 `global` 域（`--no-global` 关掉）；
  跨项目读某任务记忆需显式 `--allow-cross-scope`（help 写明"需显式授权"）。
- 冲突/取代用 `--supersedes`（双向链），不要直接删旧记忆。
- 各命令的完整 flag 以 `pm memory <子命令> --help` 为准（这里不重抄）。

### 3.1 检索：`pm recall` + 派生索引（P0）

```sh
pm index [--rebuild] [--dry-run] [--json]        # 建/刷新索引（默认增量；--rebuild 整份重建）
pm recall --query Q [--scope S] [--type T] [--limit N] \
          [--include-candidate] [--include-deprecated] [--any] [--json]
```

- **默认口径** = `layer IN (L1,L2) AND status=VERIFIED`；**L3 永不进召回**（连索引都不建）。
  候选要 `--include-candidate`、已废弃要 `--include-deprecated` —— 默认都不出现。
- **命中每条都带 `path:line` 与 `revision`**（注入与前端都靠它做来源标注）；输出还带 `library`（读的是哪个库）与 `indexEntries`。
- **索引是派生物**：落 `<库>/.local/index.sqlite`，**可删可重建、永不回写 Org**；`pm recall` 会按内容 sha **增量刷新**，所以 verify/render 之后立刻查就是对读数。
- **不静默给空结果**：库是空的（或 `--config` 指错的库）→ `INDEX_EMPTY` + 非零退出并说明；没索引而库里有记忆 → 自动建索引后命中。
- **FTS5 不可用时**自动降级为 SQLite `LIKE` 子串匹配，并在输出里**明说降级**（`mode: like` + `note`）。
  已知限制：`unicode61` 把连续中文当成**一个 token** ⇒ 查询按**前缀**匹配，词中匹配会退到 `LIKE` 兜底。

### 3.2 分层：L2 场景 + `pm memory stale`（M3 第一切片）

```sh
pm memory scene set --scope S --scene NAME --title T [--body TEXT] [--sources id@rev ...] \
                    [--status CANDIDATE|VERIFIED] [--expected-revision N]
pm memory scene show --scope S --scene NAME [--json]
pm memory scene list [--scope S] [--json]
pm memory stale [--json]          # 纯计算：引用的 L1 revision 变了/没了 ⇒ 指出受影响的 L2/L3（只读）
```

### 3.3 生成：`pm memory extract / condense / distill`（M3 第二切片）

```sh
pm memory extract  --session <会话 id> [--scope S] [--instance ID]   # 会话材料 → L1 候选
pm memory condense --scope S [--topic T]                            # 该 scope 的 VERIFIED L1 → L2 候选
pm memory distill  [--scope S|global] [--topic T]                   # L2 集合 → L3 候选
# 三条共用：--llm "<命令>" | --skeleton | --stale-only | [--dry-run] [--json]
```

- **人触发 → 只产候选**：产物只写 `memory-candidates.org`（带 `:PM_LAYER:` 与 `:PM_SOURCES:` 版本锚点），
  **人 `verify` 才升格**；命令永不直接写正式区（不新增第二条路）。
- **LLM 出口（方案 A）**：`--llm "<命令>"` —— prompt 走 **stdin**、候选 JSON 走 **stdout**（严格 schema，
  `{"candidates":[{"title":"..","body":"..","type":"fact|decision|gotcha","sources":["锚点"]}]}`）；**不内嵌任何 SDK**。
  也可在 `pm.toml` 的 `[memory.generate]` 里配 `llm`；**两者都没有 ⇒ 拒绝生成**（不编造）。
- **默认零出网**：库内容只发给**你自己指定的本地命令**；`--allow-network` 必须显式给（报告里会标注）。
- **`--skeleton`（方案 C）**：不调 LLM，只产「待归纳清单」候选（列锚点、不编造正文）。
- **失败绝不静默**：没给 LLM / LLM 非 0 / 超时 / 非法 JSON / schema 不符 / 超预算（`[memory.generate]` 的
  `timeout_s` / `max_input_bytes` / `max_candidates`）⇒ **带 code 非 0 退出、一字节不写**。
- **幂等**：整份产出的内容 sha256 作幂等键 ⇒ 同输入重跑 `changed:false`、不产重复；`--stale-only` 只处理 stale/缺失目标。
- **重跑不覆盖历史**：旧的 **候选**自动转 `DEPRECATED` + 双向 `:PM_SUPERSEDES:`；旧的 **VERIFIED 不动**
  （AI 不得把人确认过的记忆自动降级）⇒ 报告 `pendingHumanSupersede` 并给出人该跑的 `deprecate` 命令。
```

- **L2 = 一块一文件**：`memory/l2/<scope>/<scene>.org`，**路径即 id**；索引只存标题+摘要，正文按需读文件。
- **`:PM_SOURCES:` 用 `id@revision`**（如 `memory-abc@3`）= 归纳时读到的那条 L1 的版本锚点。
  `stale` 就靠它判新鲜：锚点对不上 → **[过期]**；没写 `@rev` → **[无锚点]**（**不能证明新鲜，也不假设过期**，单独列出，绝不混进 fresh）。
- **写 L2 走 `scene set`**：新建不用 `--expected-revision`，更新必须给（CAS，不匹配 → 退出码 3、一字节不写）；正文与其它 memory 一样 3 空格缩进。
- **重跑不原地覆盖**（第二切片）：旧的转 `DEPRECATED` 并用 `:PM_SUPERSEDES:` 指向新的 —— 由生成命令负责，本阶段先保证读写与 stale 可跑。
- 只索引 **L1**（`memory/*.org` 与 `memory-candidates.org` 里 `layer=L1` 的条目）；L2/L3 的索引是后续阶段。

## 4. 工作区 workspace（DSH 侧）

```sh
pm workspace list --project <DSH 侧项目 key> [--json]        # 列工作区目录 + 各自会话数
pm workspace context <工作区目录> [--no-global] [--json]     # 该目录的记忆（只含 VERIFIED）+ 会话（观察值）
```

- `workspace list` 的 `--project` 用的是 **DSH 工作区注册表里的项目名**（不是库里的项目 key；拿不准就先 `pm project list --json` 看库内项目，再看 `workspace list` 的候选）。
- `workspace context` 收的是**目录路径**（`list` 输出里的 `path`）；其中的会话状态（如 `[IDLE]`）是**观察值**，只描述缓存记录了什么，**不代表正在跑**。

## 5. 三者的关系（一句话）

随手记是**入口**（先记下来）→ 提案是**计划**（等人批）→ 任务是**承诺**（可验收）；记忆是**沉淀**（只有人确认过的才给 AI 用）。
