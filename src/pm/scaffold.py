"""work-memory 骨架模板。

人工文件只在**缺失时**创建；已存在的一律不动。
"""

from __future__ import annotations

from pathlib import Path

from pm.layout import Layout
from pm.render.org import org_table
from pm.scan import Project

TODO_KEYWORDS = (
    "#+TODO: INBOX(i) TODO(t) NEXT(n) DOING(s) WAITING(w@) BLOCKED(b@) REVIEW(r)"
    " | DONE(d!) CANCELLED(c@)"
)

GITIGNORE = ".local/\n__pycache__/\n*.pm-tmp\n"

README_TABLE_HEADERS = ["路径", "谁写", "说明"]

README_TABLE_ROWS = [
    ["inbox.org", "人", "随手记，不要求完整字段"],
    ["overrides.org", "人", "人工摘要 / pin 覆盖；机器只读"],
    ["projects/<id>/project.org", "人", "目标、范围、验收、里程碑"],
    ["projects/<id>/tasks.org", "人", "任务与状态"],
    ["projects/<id>/memory.org", "人", "该项目的事实与决策"],
    ["journal/YYYY-MM-DD.org", "人", "日记"],
    ["generated/**", "机器", "由 pm render 整体重写，禁止手改"],
    ["generated/projects/<key>.org", "机器", "每个项目一个页面"],
    ["proposals/**", "机器", "AI 提案，等人确认"],
    [".local/**", "机器", "索引 / outbox，可重建，已 gitignore"],
]


def readme_text() -> str:
    """README 用 org_table 生成 —— 手排的表格在中文列上一定错位。"""
    table = "\n".join(org_table(README_TABLE_HEADERS, README_TABLE_ROWS))
    return f"""#+TITLE: work-memory
#+STARTUP: overview

* 这个仓库是什么
  由 pm 工具管理的个人工作记忆库。
  **Org 是项目/任务/记忆的唯一真源**；DSH 的投影缓存只是输入，不是真相。

* 目录约定
{table}

* 三条硬规则
  1. **人工文件机器永不覆盖**（只会在缺失时创建）。要改内容，改人工文件或 overrides.org。
  2. **generated/ 每次 render 整体重写**，内容不含墙钟时间，因此同一份数据渲染两次零 diff。
  3. **运行状态恒为 unknown**。读到的只是快照，快照里没有「此刻是否还在跑」的信号，所以不猜；
     generated/ 里的「缓存观察」只描述缓存记录了什么。

* 人每天只需要做三件事
  1. 随手记：写 inbox.org，或在会话里说「记录一下……」。
  2. 看面板：让 agent 汇报今日下一步 / 等你确认 / 阻塞 / 信息陈旧。
  3. 确认少量变化：批计划、调优先级、验收产出。
    """

INBOX = f"""#+TITLE: Inbox
{TODO_KEYWORDS}

* Inbox
  随手记在这里，不要求完整字段。整理时再变成项目任务。

# 示例（可删）：
# ** INBOX [2026-10-10 Sat] 把 demo01 的验证结果写进管理库
#    先只读接入，不派发任何实现任务。
"""

OVERRIDES = f"""#+TITLE: 人工覆盖
{TODO_KEYWORDS}

* 说明
  这个文件由**人**维护，pm 工具只读取、从不写入。
  在这里写的人工摘要不会被自动摘要覆盖（对齐方案：AI 摘要不得覆盖人工摘要）。

* 卡片摘要覆盖
  格式：二级标题 + 属性抽屉 + 一行摘要正文。机器只取首个非空正文行。

# ** session-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
#    :PROPERTIES:
#    :PM_SOURCE_INSTANCE: dsh-default
#    :PM_SESSION: session-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
#    :PM_SUMMARY_SOURCE: human
#    :END:
#    这里写人工摘要，机器只读不改。

* 固定显示（pin）
  在这里列出的工作卡永远出现在默认视图中，不受活跃窗口与行数上限影响。
# ** session-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
"""


#: 「人工管理区」的契约表述（2026-10-12 用户批准变更后的新版）。
#: 旧版那句（HUMAN_AREA_LEGACY_MARKER）会被 pm project brief set 在写入时**当场替换**成这一版，
#: 让文件自己说真话；新建项目直接写新版。
HUMAN_AREA_NOTE = (
    "这是**人工管理区**。pm 只在项目创建时生成骨架，此后**只在你显式提交编辑时写入你指定的那一段**",
    "（actor=human + CAS + LOGBOOK 审计），不会自动改写、不会在后台批量改。",
    "（唯一入口：pm project brief set；每次写入都会在文件里留下一条审计记录。）",
)

#: 旧版契约里那句已经不再成立的话（用于就地迁移）。
HUMAN_AREA_LEGACY_MARKER = "此后永不写入"


def indent_lines(text: str, prefix: str = "   ") -> str:
    """把多行文本按 project.org 的 3 空格约定缩进（空行保持空行）。"""
    return "\n".join((prefix + line) if line else "" for line in text.split("\n"))


def project_readme(project: Project) -> str:
    paths = "\n".join(f"#+PM_PATH: {p}" for p in project.paths)
    # 注意：f-string 的表达式里**不能有反斜杠**（Python ≤3.11 会 SyntaxError，PEP 701 之后才放开），
    # 所以带 \n 拼装的这行必须先算好、模板里只留一个名字。
    human_note = indent_lines("\n".join(HUMAN_AREA_NOTE))
    return f"""#+TITLE: {project.title}
#+CATEGORY: {project.key}
#+FILETAGS: :pm:project:
{TODO_KEYWORDS}
{paths}

* {project.title}                                                       :project:
:PROPERTIES:
:ID: {project.id}
:PM_KIND: project
:PM_KEY: {project.key}
:PM_RUNTIME_STATUS: unknown
:END:

{human_note}
  运行状态恒为 unknown —— 参考 generated/ 里的缓存观察，不要在这里写「正在跑」。

** 目标
   这个项目要达成什么（可验收的表述）。

** 范围（做什么）

** 非目标（明确不做什么）

** 验收标准
   - [ ]

** 里程碑

** 风险与依赖
"""


def project_tasks(project: Project) -> str:
    return f"""#+TITLE: {project.title} — 任务
{TODO_KEYWORDS}
#+FILETAGS: :pm:tasks:

* 任务说明
  - NEXT = 已澄清、依赖满足、可以开始（不是「高优先级」的同义词）。
  - DOING = 执行中；REVIEW = 已提交结果、尚未验收。
  - **DONE 只由验收者写**。AI 说完成默认只到 REVIEW。
  - 要给 AI 做的任务加 =:PM_AI: t=，派发时用 =pm push=（待实现）。

* 任务
"""


def project_memory(project: Project) -> str:
    return f"""#+TITLE: {project.title} — 记忆
#+FILETAGS: :pm:memory:

* 事实
  环境约束、接口约定、验证方式。变更后需要复核。

* 决策
  选了什么、为何选、替代项、代价。长期保留，可被新决策取代。

* 坑
  踩过的坑与规避方式。
"""


def plan_for(layout: Layout, projects: list[Project]) -> list[tuple[Path, str]]:
    """返回 (路径, 内容)。已存在的人工文件由调用方跳过。"""
    items: list[tuple[Path, str]] = [
        (layout.readme, readme_text()),
        (layout.inbox, INBOX),
        (layout.overrides, OVERRIDES),
        (layout.root / ".gitignore", GITIGNORE),
    ]
    for project in projects:
        items.append((layout.project_file(project.id), project_readme(project)))
        items.append((layout.tasks_file(project.id), project_tasks(project)))
        items.append((layout.memory_file(project.id), project_memory(project)))
    return items
