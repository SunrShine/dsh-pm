# 任务与状态（pm task）

> 读取不代表验收；`DONE` 只由人写。文件是 `projects/proj-<key>/tasks.org`，身份只看 `:ID:`。

## 状态机

```text
INBOX ─┐
TODO → NEXT → DOING → REVIEW → DONE          （DONE/CANCELLED 是终态）
         ├→ WAITING（等人/等外部）
         └→ BLOCKED（被卡住）
任意未完成 → CANCELLED
```

- 看板 5 列（任务页）：待办（INBOX/TODO/NEXT）／执行中（DOING/WAITING）／受阻（BLOCKED）／待验收（REVIEW）／已结束（DONE/CANCELLED）。
- **`DONE` 只能由 `--actor human` 写**；AI 提交最多到 `REVIEW`（工具会以 `DONE_REQUIRES_HUMAN` 拒绝）。
- 终态不可迁出（对 `DONE`/`CANCELLED` 的操作会被拒）。

```sh
pm task list  --project KEY [--status S] [--json]
pm task show  <task-id> --project KEY [--json]        # 含 goal/非目标/验收标准/证据/历史
pm task create --project KEY --title T [--goal TEXT] [--non-goal TEXT] \
        [--criterion TEXT ...] [--from-inbox INBOX_ID] [--ai] [--assignee WHO] [--id TASK_ID]
pm task transition <task-id> --project KEY --to DONE --actor human --expected-revision N
pm task check <task-id> --project KEY --criterion-id c-1a2b [--uncheck] --expected-revision N
pm task criteria init-ids <task-id> --project KEY --expected-revision N
pm task init-ids --project KEY [--dry-run] [--json]              # 给**缺 :ID: 的任务块**补 :ID:/:PM_KIND:/:PM_STATUS:（幂等、带审计）
pm task import-team <task-id> --project KEY [--parent PARENT_ID] [--write]
pm task dag set <task-id> --project KEY --edge A --edge B --expected-revision N   # *** 任务 DAG
```

## 验收标准项与稳定 ID

- 行内 ID 形如 `- [ ] 列出输入版本 [c-1a2b]`（稳定 ID 跟着**那一项**走，改文字/挪位置不断链）。
- 勾选/取消**推荐按 ID**：`--criterion-id c-1a2b`；
  `--index N`（0 开始的文件序号）与 `--criterion 序号|文本` 已 **deprecated**，且与 `--criterion-id` **互斥**（同时给会报错）。
- 老任务（没有 ID）先跑 `pm task criteria init-ids`：**只加 ID**、**保留原缩进**、幂等（再跑 `changed:false`）；
  找不到 `*** 验收标准` 节时**明确报因**（不静默跳过）。
- ID 不存在 → `CRITERION_NOT_FOUND`，错误 extra 里带该任务现有的 IDs。

## 创建任务的纪律（给 AI 规划用）

- `pm task create` 只允许**初始状态 TODO / NEXT**（想直接写 DOING/DONE 会被拒）。
- 每条 `--criterion` 要**可核对**（"能跑通 X 命令"/"列出 Y 的输入版本"），不要写"做好一点"这种。
- 拆任务前**先查重**：`pm task list --project KEY --json`（含已结束），避免重复建；
  来源是随手记时带上 `--from-inbox <inbox-id>` 留回链。

## 历史读模型（变更流水）

- `pm task show --json` 的 `history[]`：按**发生顺序（旧→新）**；前端展示时倒序（最新在上）。
  每条来自任务自己的 `:LOGBOOK:`（含 `actor`/`at`/`rev`/可选 `reason`）。
- `historyCount` = 事件**总数**（不受截断影响）；`historyShown` = 本次返回条数；
  `historyTruncated` = 是否被截断（上限 `HISTORY_LIMIT = 100`，只留**最近** 100 条）。
- 没有 LOGBOOK 或没有条目时是 `[]` / `0` / `false`，**不是 null**（缺数据就写缺，不编）。

## 写入语义（所有写命令通用）

- 都要 `--expected-revision N`（= 你刚看到的 `:PM_REVISION:`）：不匹配 → `exit 3` + `REVISION_CONFLICT`，**一个字节都不写**
  → 重新 `show` 拿新 revision 再操作。
- 一次成功写入 = 一次 CAS + 一条审计（`:LOGBOOK:`）；重复提交带 `--idempotency-key` 时第二次 `changed:false`。
- `--dry-run` 零写入；`--json` 输出 §5 五字段（`entityId/revision/source/observedAt/auditEventId`）。
- `import-team --parent`：把会话子任务挂到项目任务下；**父任务是终态（DONE/CANCELLED）时拒绝**（`TASK_TERMINAL`）。

## 任务必须带 `:ID:`（否则 CLI 寻址不到）

- 建任务只走铸造路径：CLI `pm task create` 与 MCP 工具 `task_add` **同一套属性**（`:ID: task-<ULID>` / `:PM_KIND: task` / `:PM_STATUS:` / `:PM_PROJECT_ID:`）；
  写入路径会**拒绝**缺这三样的块（`TASK_STAMP_INCOMPLETE`），不会静默写出不可寻址条目。
- 发现历史遗留的 id-less 条目（`pm task list` 里 `id=null`）→ 跑 `pm task init-ids --project KEY` 就地补 ID 与一条 `op=task-id-stamp` 审计；幂等，`--dry-run` 先看要补哪些。
- **"show 正常、写路径却 NOT_FOUND"** ⇒ 先看报错里"查了 <哪个文件>"，再查**抽屉是否闭合**（`:LOGBOOK:`/`:PROPERTIES:` 少一个 `:END:` 会把后面的块吞进抽屉，整文件读仍正常）；
  用 `python3 scripts/repair_stamp_logbook_end.py --config <cfg> --project <key>` 先 dry-run 看要不要补 `:END:`（`--apply` 才写，幂等）。
- 补完它们就能正常 `show / transition / evidence add`（含由人执行 `--to CANCELLED` 这种经审计的清理）。

## 执行配置 / 会话关联 / 交接（都只是"准备"，都不派发）

```sh
pm task execution-config get <TASK_ID> [--json]                   # 读配置 + dispatchStatus
pm task execution-config set <TASK_ID> --workspace <工作区路径> [--project KEY] \
    [--instance ID] [--memory MEM_ID] [--session SESSION_ID] [--note TEXT] \
    --reason R --expected-revision N                               # 整体替换；不改状态、不派发
pm task link-session   <TASK_ID> --session <SESSION_ID> [--instance ID] [--reason R] --expected-revision N
pm task unlink-session <TASK_ID> --reason R --expected-revision N   # --reason 必填
pm task handoff        <TASK_ID> [--json]                          # 生成交接文本（给人/AI 看的准备材料）
```

- 读出来的 `dispatchStatus` 只有 `NOT_READY` / `HANDOFF_READY` 两态：
  `HANDOFF_READY` **只表示"准备材料齐了"，不代表已派发**（本项目不派发）。
- `execution-config set` 是**整体替换**（没写的字段会被清掉）+ CAS + 一条审计；它**不改任务状态**。
- `link-session`/`unlink-session` 记"这个任务由哪个 DSH 会话在做"（解挂必须给 `--reason`，否则 `REASON_REQUIRED`）。
- `handoff` 只**打印**交接文本，零写入。
