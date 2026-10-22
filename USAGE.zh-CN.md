# 使用教程（USAGE）

[English](USAGE.md) · 简体中文

> 这份教程按「你想干什么」组织。安装与总览见 [README](README.zh-CN.md)；**每条命令的权威定义永远是 `pm <命令> --help`**（本文的命令都按真实 `--help` 核对过）。

## 0. 哪半能独立用

| 部分 | 需要 DSH 宿主吗 | 说明 |
| --- | --- | --- |
| `bin/pm`（CLI + MCP） | **不需要** | 直接读写你指定的 org 工作记忆库 |
| 三条 skill（`skill/`） | **不需要** | 给 agent 看的操作规程，用 `pm skill install` 装 |
| 插件半（Web 工作台 / `/ui-pm/*` 路由 / `lib/`） | **需要** DSH `0.2.1-alpha.x` | `package.json` 的 `devDependencies` 里那些 `@deepseek-ai/dsh-*` 只在开发插件半时才需要 |

只想用 CLI / MCP：克隆仓库后直接用 `./bin/pm`（或 `pip install .`）。

## 1. 30 秒跑起来（不需要 DSH）

```bash
# ① 建库骨架（不想要 git 就加 --no-git）
pm init --root ~/my-work-memory --no-git

# ② 写配置文件：告诉 pm 库在哪（pm init 只建骨架，不会替你写 pm.toml）
printf 'library = "~/my-work-memory"\n' > ~/my-work-memory/pm.toml

# ③ 记一条随手记（--config 显式指定目标库）
pm capture --config ~/my-work-memory/pm.toml "今天先把 CLI 那半跑起来" --project demo-app

# ④ 看看落在哪
pm inbox list --config ~/my-work-memory/pm.toml
```

- `library = "~/..."` 支持 `~` 展开；`pm init` 建的是 `inbox.org` / `overrides.org` / `README.org` / `.gitignore`。
- **写入门禁**：没有显式给 `--config`（也没用两个环境变量）时，写命令必须加 `--yes`，否则会被 `NEEDS_YES` 拒绝 —— 这是防止误写默认库。只想预演加 `--dry-run`（不需要 `--yes`）。

## 2. 让 agent 会用

### 2.1 装 skill

```bash
pm skill path --all                                 # 看随工具分发的三条 skill 在哪
pm skill install --skill pm-evidence --dsh-home ~/.dsh
pm skill install --all --dsh-home ~/.dsh            # 三条都装
```

- 安装是**软链**到 `<dsh-home>/skills/<name>`，改源即生效，不用重装。
- 三条 skill：`pm`（读写工作记忆的主规程）、`pm-evidence`（把可核对证据挂到验收标准项）、`pm-planning`（把需求拆成可核对任务）。

### 2.2 接 MCP（`pm mcp`，stdio）

`pm mcp` 用 stdio 说 JSON-RPC，任何支持 MCP 的客户端都能接。DSH 侧照 `config/dsh-mcp.patch.yml` 写进 profile 的 `cordis.patch.yml` —— **必须包在 `insert:` 里**（裸条目是「覆盖」语义，id 不存在时会静默不生效）：

```yaml
- insert:
    - id: mcp-pm
      name: '@deepseek-ai/dsh-mcp-client'
      config:
        serverName: pm
        transport: stdio
        command: <pm-root>/bin/pm
        args: ['mcp']
        cwd: <pm-root>
        env:
          PATH: <node-bin-dir>:/usr/local/bin:/usr/bin:/bin
```

- 建议在 `args` 里带上 `--config` 指向目标库，避免 MCP 侧与实例侧读不同的库。
- 工具清单与诚实契约（`task_add` 只能建 TODO/NEXT、`proposal_draft` 只建提案不建任务）见 README「MCP 工具」一节。

## 3. 一天的工作流

一句话：**AI 生成候选，人做决定；AI 最多提交到 REVIEW，DONE 只能人写。**

### 3.1 随手记 → 提案 → 人批准

```bash
# ① 随手记（原文只读，永不就地改写）
pm capture --config ~/my-work-memory/pm.toml "客户要一个能导出周报的入口" --project demo-app

# ② 从收件箱取 :ID:，让 AI 出一份提案
pm inbox list --config ~/my-work-memory/pm.toml
pm proposal create --config ~/my-work-memory/pm.toml \
  --source-inbox <inbox-id> \
  --change "新增：导出周报入口" \
  --criterion "导出命令能跑出一份周报" \
  --project demo-app

# ③ 人批准（批准才创建正式任务；拒绝则正式任务零变化）
pm proposal approve <proposal-id> --config ~/my-work-memory/pm.toml \
  --project demo-app --expected-revision 1
```

### 3.2 做任务：状态机是严格线性的

```text
TODO → NEXT → DOING → REVIEW → DONE        NEXT/DOING ⇄ WAITING/BLOCKED
任意未完成 → CANCELLED                     DONE / CANCELLED 是终态
```

```bash
# 开始做（跳级会被拒：TODO → DOING 非法，必须先经 NEXT）
pm task transition <task-id> --config ~/my-work-memory/pm.toml \
  --project demo-app --to NEXT --expected-revision 1
```

### 3.3 挂证据（每条验收标准都有稳定 ID）

```bash
# 看标准与它们的稳定 ID（c-xxxx）；revision 也在这里拿
pm task show <task-id> --config ~/my-work-memory/pm.toml --project demo-app --json

# 勾选一条标准
pm task check <task-id> --config ~/my-work-memory/pm.toml --project demo-app \
  --criterion-id c-65e1 --expected-revision 2

# 挂一条可核对的证据
pm task evidence add <task-id> --config ~/my-work-memory/pm.toml --project demo-app \
  --criterion-id c-65e1 --kind test --result pass \
  --ref "node --test tests/frontend" --expected-revision 3
```

- `--kind`：test / build / manual / artifact / review / other；`--result`：pass / fail / `info`。
- **不知道结论就写 `info`，绝不猜 pass**；`--ref` 不能含 `|`（塞不下就写 `--note`）。

### 3.4 AI 提交验收，人写 DONE

```bash
# AI/系统最多提交到 REVIEW
pm task transition <task-id> --config ~/my-work-memory/pm.toml --project demo-app \
  --to REVIEW --expected-revision 4 --reason "证据已挂，等人验收"

# 人验收（DONE 只认 actor=human；AI 写会被 DONE_REQUIRES_HUMAN 拒绝）
pm task transition <task-id> --config ~/my-work-memory/pm.toml --project demo-app \
  --to DONE --expected-revision 5 --actor human --reason "人已验收"
```

**所有写命令都是 CAS**：先 `task show` 拿到 `revision`，再带 `--expected-revision`；不一致 → `exit 3`（409），一字节不写。

## 4. 和 DSH 一起用

```bash
dsh plugin add github:SunrShine/dsh-pm
```

- **插件半需要 DSH ≥ `0.2.1-alpha.1`**（本仓库随该版本开发与验证；更低版本未验证，可能无法加载）；CLI/MCP 与 skill 不需要 DSH。
- 装好后从 **DSH 侧栏的「PM 工作台」**进入，界面导览与截图见 README 的「界面」章节。
- 让界面 HTTP 通路与 `pm mcp` 子进程读**同一个库**：给实例设 `DSH_UI_PM_CONFIG=<你的 pm.toml>`（见下一节）。

## 5. 多库 / 多实例

**配置查找顺序**（与 `pm --help` 一致）：

```text
--config  >  DSH_UI_PM_CONFIG  >  PM_CONFIG  >  ./pm.toml  >  ~/.dsh-pm/pm.toml  >  内置默认
```

- **显式来源必须存在且可解析**：打错一个字符就直接失败（`CONFIG_NOT_FOUND` / `CONFIG_INVALID`），**绝不静默回落到默认库**。
- `DSH_UI_PM_CONFIG` 是**实例作用域**：插件侧与 `pm mcp` 侧都认它，两个都设时读的是同一个库，不会分叉。
- 隔离一个一次性实例：用 `--dsh-home`（或 `PM_DSH_HOME`）做单实例覆盖；要操作全部数据根用 `pm skill install --all-instances`。
- `pm.toml` 里两类东西：`library`（库根）与多个 `[[instance]]`（`id` / `path` / `role`），外加视图参数 `active_days` / `active_hours` / `row_limit` / `exclude_paths`。
- 写闸门与 env 无关：两个环境变量都设，写命令**仍然**要 `--yes`（除非你用 `--config` 显式指了库）。

## 6. 常见问题

| 现象 | 原因与处理 |
| --- | --- |
| `pm: [NO_LIBRARY]` | `pm.toml` 里没有 `library`；补上库根即可 |
| `pm: [CONFIG_NOT_FOUND]` / `[CONFIG_INVALID]` | 显式配置路径不存在或 TOML 坏了。**不会**回落默认库（这是有意的） |
| `pm: [NEEDS_YES]` | 写命令没显式 `--config` 也没 `--yes`；加 `--yes` 或显式指库 |
| `[LEGACY_UNTRACKED]` | 收件箱里没有 `:ID:` 的旧条目（身份只认 `:ID:`，旧条目会被标出来而不是猜） |
| `[DONE_REQUIRES_HUMAN]` | AI/系统在写 `DONE`；改成 `--to REVIEW`，由人验收 |
| `[INVALID_TRANSITION]` | 跳级了（如 TODO → REVIEW）；按 3.2 的箭头逐级走 |
| `exit 3`（409） | `revision` 不是最新的；重新 `task show` 拿新值再写 |
| 界面里「需要我处理」为空 | 那是**明确信号**才出现的卡片（受控会话/明显异常）；空库、空载荷是合法输出，不是 bug |
| 为什么会话状态老是 `unknown` | 因为面板读的是**只读快照**：快照里没有「它现在还在跑吗」的信号，所以没人能知道；运行状态一律写 `unknown`，只显示观察到的历史 |
| 为什么 AI 不能写 DONE | DONE 是「人验收过」的唯一凭证（见 README「诚实契约」） |
| 输出里看不到对话正文 | 默认不打印 prompt 正文；要看加 `--show-prompt` |

## 7. 一页命令速查

| 目的 | 命令 |
| --- | --- |
| 记一条 | `pm capture --config ~/my-work-memory/pm.toml "…"` |
| 看收件箱 | `pm inbox list --config ~/my-work-memory/pm.toml` |
| 置顶一条 | `pm inbox pin <inbox-id> --config ~/my-work-memory/pm.toml --expected-revision 1` |
| 建项目 | `pm project create demo-app --config ~/my-work-memory/pm.toml --title "演示项目"` |
| 列项目 | `pm project list --config ~/my-work-memory/pm.toml --json` |
| 任务列表 | `pm task list --config ~/my-work-memory/pm.toml --project demo-app --json` |
| 建任务 | `pm task create --config ~/my-work-memory/pm.toml --project demo-app --title "…" --criterion "…"` |
| 看一条任务 | `pm task show <task-id> --config ~/my-work-memory/pm.toml --project demo-app --json` |
| 给旧标准补 ID | `pm task criteria init-ids <task-id> --config ~/my-work-memory/pm.toml --project demo-app --expected-revision 1` |
| 勾一条标准 | `pm task check <task-id> --config ~/my-work-memory/pm.toml --project demo-app --criterion-id c-65e1 --expected-revision 2` |
| 挂证据 | `pm task evidence add <task-id> --config ~/my-work-memory/pm.toml --project demo-app --criterion-id c-65e1 --kind test --result pass --ref "…" --expected-revision 3` |
| 看证据 | `pm task evidence list <task-id> --config ~/my-work-memory/pm.toml --project demo-app` |
| 改状态 | `pm task transition <task-id> --config ~/my-work-memory/pm.toml --project demo-app --to NEXT --expected-revision 2` |
| 出提案 | `pm proposal create --config ~/my-work-memory/pm.toml --source-inbox <inbox-id> --change "新增：…" --project demo-app` |
| 批准提案 | `pm proposal approve <proposal-id> --config ~/my-work-memory/pm.toml --project demo-app --expected-revision 1` |
| 记忆候选 | `pm memory candidates --config ~/my-work-memory/pm.toml --status CANDIDATE` |
| 加一条记忆 | `pm memory add --config ~/my-work-memory/pm.toml --text "…" --scope demo-app --type decision --topic "配置优先级" --sources "commit abc1234"` |
| 确认 / 取代 / 丢弃 | `pm memory verify <memory-id> --config ~/my-work-memory/pm.toml --expected-revision 1` ・ `pm memory deprecate <memory-id> --config ~/my-work-memory/pm.toml --reason "已被新决策取代" --superseded-by <memory-id>` ・ `pm memory discard <memory-id> --config ~/my-work-memory/pm.toml --reason "误报"` |
| 看工作区 | `pm workspace list --config ~/my-work-memory/pm.toml --json` |
| 扫 DSH 数据根 | `pm scan --config ~/my-work-memory/pm.toml --days 14` |
| 卡片视图 | `pm ui-cards --config ~/my-work-memory/pm.toml --limit 20` |
| 渲染 generated/ | `pm render --config ~/my-work-memory/pm.toml --write` |
| 摘要队列 | `pm summary queue --config ~/my-work-memory/pm.toml` |
| 起 MCP | `pm mcp --config ~/my-work-memory/pm.toml` |
| skill 路径 / 安装 | `pm skill path --all` ・ `pm skill install --all --dsh-home ~/.dsh` |

> 兜底：任何命令加 `--help`（如 `pm task evidence add --help`）看当时真实可用的选项。
