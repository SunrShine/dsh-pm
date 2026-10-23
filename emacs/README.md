# Emacs 集成（多文件 inbox）

`pm.el`（仓库根）已更新为多文件 inbox 布局：

- 真源：`inbox-human-<period>.org`（默认 weekly）/ `inbox-ai-<period>.org`（默认 monthly）；
- `inbox.org` 是 pm 生成的**只读汇总视图**（别手改）；
- 人工文件与 AI 文件都按周期轮转，旧文件天然就是归档（不再搬文件）。

## 加载

```elisp
(setenv "PM_WORK_MEMORY" "/path/to/work-memory")
(setenv "PM_CONFIG" "/path/to/pm.toml")  ; 可选：M-x pm-capture-inbox 用
(load "/path/to/pm_tools/pm.el")
```

## 常用命令

| 命令 | 作用 |
|---|---|
| `M-x pm-inbox-open-current` | 打开当前周期的人工 inbox（不存在则建带模板的文件） |
| `M-x pm-capture-inbox` | 用 `pm capture` 记一条（自动 ID/时间/审计，并按来源路由） |
| `M-x pm-insert-inbox-entry` | 在光标处插入合法条目模板（手写用） |
| `M-x pm-inbox-render` | 重新生成 `inbox.org` 汇总视图 |
| `M-x pm-inbox-open-file` | 在历史人工 inbox 文件中选择打开 |
| `M-x pm-install-capture-template` | 加 org-capture 模板（键 `p`，写当前人工 inbox） |

## 关键变量

- `pm-root`：库根（默认读环境变量 `PM_WORK_MEMORY`）；
- `pm-inbox-human-mode`：`weekly`（默认）/ `monthly` / `single`，须与 `pm.toml` 的 `[inbox] human_mode` 一致；
- `pm-bin`：pm 可执行文件（默认自动找 `../bin/pm`）。

## yasnippet

把 `emacs/snippets/org-mode/inbox` 放进你的 yasnippet `org-mode` 目录（或加到 `yas-snippet-dirs`），
在人工 inbox 文件里输入 `inbox` + Tab 即可展开成带 `:ID:`/`:PM_STATUS:` 的合法条目。

## org-capture

`pm.el` 在加载 org 后会自动加模板（键 `p`，写当前人工 inbox 文件）；也可手动执行
`M-x pm-install-capture-template`。模板生成的条目与 pm 后端解析口径一致，不会出现“写了但 pm 看不见”。