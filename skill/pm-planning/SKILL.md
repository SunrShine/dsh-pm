---
name: pm-planning
description: 把需求拆成 work-memory（pm）里**可核对**的任务：先查项目与已有任务再建、pm task create 只允许 TODO/NEXT、验收标准要能被一条命令验证、写清非目标、子任务/兄弟任务的边界（dag / import-team --parent）。当任务涉及"帮我规划这个需求、拆几条任务、把需求变成待办、补验收标准"时加载。
whenToUse: 用户说"帮我规划/拆一下""建几条任务""把这段需求落成待办""这几条标准怎么定"时；或 AI 提案获批后要落任务时。
---

# 任务规划（pm task create / dag / import-team）

> 一句话：规划 = **可核对的验收标准** + **明确的非目标** + **不重复建**。建之前先读。

## 先读后写（顺序别反）

```sh
pm project list --json            # {projects:[{key,id,title,inLibrary,path,taskCount,workspaceCount}],count}
pm task list --project KEY --json # 含已结束的任务：先查重，再决定新建
pm task show <TASK_ID> --project KEY --json
```

- `inLibrary=false` 的项目是"只在 DSH 里出现过、还没建目录" → 先 `pm project create <key>`（或让人确认 key）。
- **库位置不要写死**：配置查找顺序见 `pm`（主 skill）「先定位库」一节。

## 建任务：只允许 TODO / NEXT

```sh
pm task create --project KEY --title "给导出加 sha256 校验" \
    --goal "导出后能自证完整性" --non-goal "不做签名" \
    --criterion "导出完成后打印 manifest.sha256 的首行" \
    --criterion "篡改任一文件后校验命令返回非 0" \
    --ai --assignee <可选> --expected-revision 不适用（新建）
```

实测输出：

```text
$ pm task create --project demo --title "给导出加 sha256 校验" --goal "导出后能自证完整性" \
      --non-goal "不做签名" --criterion "导出完成后打印 manifest.sha256 的首行" \
      --criterion "篡改任一文件后校验命令返回非 0" --ai
已创建任务 task-01M4T3DCK6TQ5BG397ZRPE66NZ  TODO  给导出加 sha256 校验
  projects/proj-demo/tasks.org:13  audit audit-01M4T3DCK6TQ5BG397ZRPE66P0
```

- **`--criterion` 必须可核对**：能写成"跑哪条命令 / 看到什么就算过"。
  ✅「篡改任一文件后校验命令返回非 0」 ❌「尽快完成」「体验好一点」「优化一下」。
- **写清单含非目标**（`--non-goal`）：不做的事写下来，后续才不会跑偏。
- AI 建的都带 `--ai`；来源是随手记就带 `--from-inbox <INBOX_ID>` 留回链。
- 状态机口径：`TODO`（已记下）→ `NEXT`（**已澄清、可以开工**）→ `DOING`（执行中）→ `REVIEW`（待验收）→ `DONE`（**只能由人写**）。
  注意 **`TODO` 不能直接跳 `DOING`**（实测：`[INVALID_TRANSITION] TODO 允许的去向：CANCELLED, NEXT`）—— 要开工先 `--to NEXT`。

```sh
pm task transition <TASK_ID> --project KEY --to NEXT|DOING|REVIEW|BLOCKED|CANCELLED \
    --expected-revision N [--reason "为什么"]
pm task check <TASK_ID> --project KEY --criterion-id c-xxxx [--uncheck] --expected-revision N
pm task criteria init-ids <TASK_ID> --project KEY --expected-revision N   # 老任务补稳定 ID（幂等）
pm task handoff <TASK_ID> [--json]                             # 生成"交接材料"给执行者（只打印，不派发）
pm task execution-config set <TASK_ID> --project KEY --workspace <工作区路径> --reason R --expected-revision N
                                                                 # 记录去哪儿执行（整体替换；不改状态、不派发）
```

## 拆：子任务还是兄弟任务

- **兄弟任务**（同一目标下并列的独立交付物）→ 直接再 `pm task create`，然后用 `pm task dag set` 记依赖：
  ```sh
  pm task dag set <TASK_ID> --project KEY --edge 'a -> b' --expected-revision N   # 合并去重
  ```
- **一次会话的执行子任务**（团队任务记录，不建顶层任务）→ `pm task import-team`：
  ```sh
  pm task import-team <TASK_ID> --project KEY --from-json snapshot.json    # 默认 dry-run，先预演
  pm task import-team <TASK_ID> --project KEY --from-json snapshot.json --write
  pm task import-team <TASK_ID> --project KEY --parent <父任务> --from-json - --write   # 挂到父任务下
  ```
  父任务已是 `DONE`/`CANCELLED` 时会**拒绝**（`TASK_TERMINAL`）——别往已完成的任务上挂新活。
- 其它 flag（`--status` 过滤等）看 `pm task import-team --help`，别背。

## 反例（不要做）

- ❌ **一口气建 20 条**：先把需求拆成 3–7 条能独立验收的；剩下的等前面做完再拆。
- ❌ **不查重就重建**：先 `pm task list --project KEY --json`（含已结束），重复的合并/引用而不是新建。
- ❌ **验收标准写成空话**（"做好""优化"）：必须能被一条命令或一次核对判定。
- ❌ **给 AI 建的任务写 `DONE`**：`create` 只接受 `TODO`/`NEXT`；`DONE` 由人写。
- ❌ **自己给自己批提案**：`pm proposal approve` 是人的动作；AI 只 `create`/`revise`。
- ❌ **把库路径写进任务描述**：用项目 key / 相对路径，换机才不会误导。
