---
name: pm
description: 读写 work-memory 工作记忆库（Org 为唯一真源）：项目 / 任务（含验收标准与验收证据）/ 随手记 / 提案 / 记忆 / 摘要。当任务涉及"记录或更新工作进展、看各项目现在在做什么、给某个会话生成一句话摘要、整理 inbox、给 AI 规划任务、挂验收证据、写下项目决策/坑/约束"时加载本 skill。
whenToUse: 用户说"记录一下""更新进展""××项目做到哪了""帮我看看哪些会话在做啥""给这些卡写摘要""把这条证据挂上去""把这个记到 memory 里"时。
---

# work-memory（pm）

> **先定位库，再动手**——不要假设库在哪、更不要写死路径。见下面「先定位库」。
> 本 skill 只写"怎么用"；细节按需读 `references/`（三个文件：任务与状态、证据、随手记与记忆）。

## 这个系统是什么

- **Org 文件是唯一真源**。DSH 的投影缓存只是输入，不是真相。
- **运行状态恒为 unknown**。读到的只是只读快照，没有实时存活信号，无法证明某个会话此刻在不在跑；任何"正在运行"的断言都是编造。
  缓存里的"观察值"只描述**缓存记录了什么、有多新**。
- **DONE 只由人写**。AI 说完成，最多到 REVIEW；`goal.phase=complete` 只表示"已结束"，不是验收通过。

## 先定位库（不要写死路径）

1. **看有哪些项目**：`pm project list --json` → 每行 `{key,id,title,inLibrary,path,...}`
   （`inLibrary=true` 是库里**已建目录**的项目；`false` 是只在 DSH 里出现过、还没建目录的）。
2. **库位置按配置查找顺序解析**（先找到先用）：`--config` > 环境变量 `PM_CONFIG` > 当前目录 `./pm.toml`
   > `~/.dsh-pm/pm.toml` > 仓库自带的 `config/pm.toml`（只在源码检出里存在）。
   一个都没有也**不会失败**：用内置默认值，`pm scan` 会如实显示「无数据根」。
3. **写命令的闸门**：没有显式 `--config`（也不是 `--dry-run`）时必须加 `--yes`，否则拒绝写入。
   → 想写某个库，就用 `--config <那个库的 pm.toml>`；别用 `--yes` 去赌。
4. **多实例 / 多库**：一台机器可能有多个 DSH 数据根（各自独立的会话编号），
   `pm scan --instance <id>` 只看一个根；不同库是**不同的工作记忆**，不要跨库合并结论。

## 三条硬规则（违反会破坏数据）

1. **不要手写 `generated/**` 下的任何文件**：每次 render 整体重写，你的修改会被覆盖。
2. **人工文件只读**（`inbox-human-*.org` / `inbox-ai-*.org` / `overrides.org` / `projects/*/*.org` / `journal/*.org`；`inbox.org` 是生成视图，勿手改）：
   要改内容就用 `pm` 的写命令（它们带 CAS + 审计），或直接问用户。
   唯一例外是人在编辑它们；AI 不要"顺手改一下"。
3. **不要输出对话正文**：卡片与摘要只放结构化事实或你生成的一句话摘要。
   `pm log` 可以读日志提炼结论，但正文（用户请求原文、交付物清单）**不入库**，也不要整段贴给用户（可能含凭据）。

## 人工记录写在哪儿

| 想记什么 | 写哪里（库内相对路径） | 用什么命令 |
|---|---|---|
| 随手记、还不成形 | `inbox-human-<period>.org`（人工；AI 用 `inbox-ai-<period>.org`；`inbox.org` 是生成视图） | `pm capture "..."`（按来源路由） |
| 项目目标 / 范围 / 验收标准 / 里程碑 / 风险 | `projects/proj-<key>/project.org` | `pm project brief set`（人显式提交） |
| 任务、状态流转、验收标准勾选、证据 | `projects/proj-<key>/tasks.org` | `pm task ...`（见下） |
| 该项目的记忆（事实 / 决策 / 坑） | `projects/proj-<key>/memory.org` + 全局 `memory/*.org` | `pm memory ...` |
| AI 计划（等人批准） | `proposals.org` | `pm proposal ...` |
| 会话摘要（人工版优先） | `overrides.org` | 人写；AI 用 `pm summary set` |
| 日记 | `journal/YYYY-MM-DD.org` | 人写 |

## 常用命令（v0.3.2）

```sh
pm scan [--all] [--limit N] [--project KEY] [--instance ID] [--json]   # 只读：工作卡现状
pm project list|create|context|brief get|brief set                      # 项目与简报
pm capture "..." [--project KEY]                                        # 往 inbox 追加一条随手记（CLI→人工文件；MCP→AI 文件）
pm inbox list [--status S] [--origin human|ai]|archive|snooze|merge|note|dismiss|set-status|annotate|edit|history|pin|unpin
pm inbox files|render [--check]|migrate [--dry-run|--write]              # 多文件 inbox：真源清单 / 生成视图 / 旧库迁移
pm task list|show|create|transition|check|criteria|evidence|import-team|dag|execution-config
pm proposal list|show|create|approve|reject|revise
pm memory candidates|list|context|add|verify|deprecate|stale
pm memory scene set|show|list                    # L2 场景（memory/l2/<scope>/<scene>.org，一块一文件）
pm memory extract|condense|distill               # 生成候选（人触发 → 只产候选；见 references §3.3）
pm index [--rebuild] [--dry-run] [--json]     # 建/刷新记忆内容索引（派生物：<库>/.local/index.sqlite）
pm recall --query Q [--scope S] [--type T] [--limit N] [--include-candidate] [--include-deprecated] [--any] [--json]
pm prompt get --scope S --json   # 读项目初始系统提示词（人写数据层；只读提示词本身，不预览运行时注入物）
pm prompt set --scope S --block-json JSON --expected-revision N --actor human|ai   # 写提示词（CAS+审计+幂等；已存在仅人可改）
pm prompt list --json   # 只读清单：哪些项目已保存过提示词（页面复制源用）
pm prompt exports list --scope ALL [--q W] --json   # 导出记录列表（派生物 .local/prompt-exports.json）
pm prompt exports add --payload-b64 B64 [--idempotency-key K] --json   # 新增导出记录（同 key 重放不新增）
pm prompt exports delete --id exp-... --json   # 删除记录（只删记录，不动导出文件与 prompt.org）
pm summary queue|set ; pm log ; pm render [--write]
pm mcp                                                                  # MCP server（stdio）
```

- **读写分离**：`scan`/`show`/`list`/`recall` 是只读；写命令都要 `--expected-revision`（CAS）并落一条审计。
- **检索记忆用 `pm recall`**（默认口径 `layer IN (L1,L2) AND status=VERIFIED`，**L3 永不进召回**；
  候选 / 废弃要 `--include-candidate` / `--include-deprecated`）；命中**每条都带 `path:line` 与 `revision`**。
  索引是**派生物**（`pm index` 可删可重建，永不回写 Org）；FTS5 不可用时自动降级 LIKE 并在输出里说明。细节见 `references/inbox-and-memory.md`。
- **409/exit 3** = 你手上的 revision 过期 → **重新读一遍再操作**，不要重试同一个 revision。

## 任务与验收标准（细节 → `references/tasks-and-states.md`）

- 状态机：`TODO → NEXT → DOING → REVIEW → DONE`（+ `WAITING`/`BLOCKED`；任意未完成 → `CANCELLED`）；看板按 5 列归组。
- **新建任务**：`pm task create --project KEY --title T [--goal ...] [--non-goal ...] [--criterion ...] [--ai] [--assignee WHO]`
  —— 只允许初始状态 `TODO`/`NEXT`；`--criterion` 可重复，写清**可核对**的验收标准。
- **验收标准项有稳定 ID**（行内 `[c-1a2b]`）：勾选用 `pm task check <id> --project KEY --criterion-id c-1a2b`
  （推荐）；`--index`/`--criterion` 已 deprecated 且与 `--criterion-id` **互斥**。
  老任务没有 ID 时先跑 `pm task criteria init-ids`（只加 ID、保留缩进、幂等；认不到节会明确报因）。
- **`DONE` 只能由人写**：`--actor human` 才允许；AI 最多把任务推到 `REVIEW`。

## 验收证据（细节 → `references/evidence.md`）

```sh
pm task evidence add <task-id> --project KEY --criterion-id c-1a2b \
    --kind test|build|manual|artifact|review|other --result pass|fail|info \
    --ref <commit|路径|URL|命令> [--note TEXT] --expected-revision N [--actor ai]
pm task evidence list <task-id> --project KEY [--json]
```

- **`result` 只有 `pass`/`fail`/`info`：不知道就写 `info`，绝不猜 `pass`。**
- `--ref` 里**不能含 `|`**（塞不下就写 `--note`）；一次 CAS + 一条审计；重复提交 `changed:false`；终态任务拒绝（`TASK_TERMINAL`）。
- **挂证据 ≠ 验收通过**：`actor=ai` 只能留证据，`DONE` 仍只由人写（`pm task transition --actor human`）。

## 随手记 / 提案 / 记忆（细节 → `references/inbox-and-memory.md`）

- **随手记**：`pm capture` 只追加；**原文只读**，补充用 `pm inbox annotate`（追加段落），改原文用
  `pm inbox edit --reason`（旧值逐字留档）；状态流转走 `pm inbox set-status`，不会静默降级。
- **提案**：`pm proposal create` 只写 `proposals.org`（**绝不建任务**）；`approve` 才创建正式任务；
  `revise` 保留 ID 并重挂源 revision。
- **记忆**：AI 只能提 `CANDIDATE`（`pm memory add`）；**只有人能 `verify`**；给 AI 用的上下文包
  （`pm memory context`）**只含 VERIFIED**。

## 生成摘要的标准流程

1. `pm summary queue --all --limit 0` 拿缺摘要的工作卡清单。
2. 每张卡读 `generated/sessions/<数据根 id>/<session-id>.org`：缓存观察、goal、todos、轮/步、工作目录。
3. **只根据这些结构化事实**写一句话摘要（≤ 40 字）。信息不足就写"信息不足，仅知在 <目录> 做过 <N> 轮"。
4. `pm summary set --session <id> --text "..." --model <你的模型名>`；人工摘要优先，遇到会拒绝覆盖。
5. 重新 render。卡里连 goal/todos 都没有时：`pm log --project <key> --missing --limit 8` 读日志提炼
   （自翻页：写完摘要的卡不再属于 missing，重复调用会自动前进）。

**隐私边界**：日志正文可以读来提炼，**只有一句话结论能入库**；摘要 ≤ 40 字，写清「做了什么 + 结果」。

## 汇报格式（给用户看）

- 先说哪个项目最近有记录、哪些卡是「陈旧·忙碌」（可能中断，需要处理）。
- 运行状态一律说 `unknown`，不要说"正在跑"；缺摘要的卡单独列一段（那是需要人确认的部分）。
- 不要输出 `pm scan` 里的对话正文（默认已隐去；不要用 `--show-prompt` 去取）。

## 不要做的事

- 不修改任何 DSH 数据根（`~/.dsh`、`~/.dsh-preview` 等）下的文件（只读接入）。
- 不因为目录名相似就合并项目；要合并必须改 `pm.toml` 的 `[[merge]]` 并让用户确认。
- 不把缓存里的 `goal.phase=complete` 当成"已验收通过"；不给任务写 `DONE`。
- 不猜证据结论（不知道就 `info`）；不在 `--ref` 里塞 `|`。
