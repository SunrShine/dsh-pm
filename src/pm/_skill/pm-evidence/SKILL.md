---
name: pm-evidence
description: 把**可核对的证据**挂到 work-memory（pm）任务的具体验收标准项上：pm task evidence add/list、kind 与 result 枚举、"不知道写 info"、actor=ai 的诚实边界。当任务涉及"交付/验收前登记证据、跑完测试或构建要把结果落到任务上、证明某条验收标准已满足"时加载。
whenToUse: 用户说"把这条证据挂上去""验收一下""测试通过了记一下""这条标准谁来证明"时；或 AI 刚跑完 test/build 需要把结果登记到任务上时。
---

# 挂验收证据（pm task evidence）

> 一句话：证据是**事实登记**，不是验收结论。**挂证据 ≠ 验收通过**，`DONE` 只由人写。

## 何时该用

- 刚跑完测试 / 构建 / 手工核对，要把**可回查**的结果挂到**某一条**验收标准上；
- 用户要看"这条标准凭什么算完成"；
- 交付前补证据链。

**不该用**：任务还没有验收标准（先 `pm task criteria init-ids` 或让人补标准）；只为"让任务看起来完成"而补 `pass`。

## 一条命令

```sh
pm task evidence add <TASK_ID> --project KEY --criterion-id c-xxxx \
    --kind test|build|manual|artifact|review|other \
    --result pass|fail|info \
    --ref <commit|路径|URL|命令> [--note "自由文本"] \
    --actor ai --expected-revision N [--idempotency-key K]
```

- `--criterion-id`：**必须**指向该任务真实存在的验收标准项（形如 `c-8c3d`；不存在 → `CRITERION_NOT_FOUND`，错误里会带现有 IDs）。
- `--kind`：六值 `test / build / manual / artifact / review / other`。
- `--result`：三值 `pass / fail / info`。
- `--ref`：commit / 文件路径 / URL / **真跑过的命令**；**不得含 `|`**（那是结构分隔符）。
- `--expected-revision`：先 `pm task show <TASK_ID> --project KEY --json` 读 `task.revision`；对不上 → `exit 3`，一个字节不写。
- 全部取值以 `pm task evidence add --help` 为准（这里不重抄帮助文本）。

## 三条写死的口径

1. **不知道就写 `info`，绝不猜 `pass`。** 没真跑过、结果不明、只能在别人的输出里看到 —— 都是 `info`，并在 `--ref`/`--note` 里写清你看到了什么。
2. **`--ref` 不含 `|`**：塞不下的自由文本进 `--note`（工具会明确拒绝并提示）。
3. **`actor=ai` 不等于验收**：AI 挂的证据只是登记；把任务推到 `REVIEW` 就够，`DONE` 等人（`--actor human`）。

## 实测示例（2026-10-13，临时库上真跑过）

```text
$ pm task evidence add task-01M4T3DCK6TQ5BG397ZRPE66NZ --project demo \
    --criterion-id c-8c3d --kind test --result pass \
    --ref "tests/test_export.py::test_manifest" --actor ai --expected-revision 1 --idempotency-key k1
已加证据 test · pass · tests/test_export.py::test_manifest  → 标准 [c-8c3d]  task-…NZ  rev 1 → 2  audit audit-01M4T3EG722FTS4V2CBB3XRNGM

# 同一个 --idempotency-key 再提交一次（重放）
{"ok": true, …, "changed": false, "evidenceCount": 1, "idempotent": true}

# 不知道结果时
$ pm task evidence add task-…NZ --project demo --criterion-id c-ce93 --kind manual --result info \
    --ref "尚未在真实导出产物上跑过" --note "只确认了校验命令存在" --actor ai --expected-revision 2
已加证据 manual · info · 尚未在真实导出产物上跑过  → 标准 [c-ce93]  task-…NZ  rev 2 → 3  audit audit-…
```

落到文件里就是任务正文的一节（自由文本永远在最后）：

```text
*** 证据（验收）
- c-8c3d | test | pass | tests/test_export.py::test_manifest | 2026-10-13T15:43:18+08:00 | ai
- c-ce93 | manual | info | 尚未在真实导出产物上跑过 | 2026-10-13T15:43:19+08:00 | ai | 只确认了校验命令存在
```

## 只读核对（别自己解析文件）

```sh
pm task evidence list <TASK_ID> --project KEY --json   # {ok,taskId,path,count,evidence[]}
pm task show <TASK_ID> --project KEY --json            # task.evidence[]（逐条结构化）+ evidenceCount
```

## 反例（不要做）

- ❌ **为了让任务好看补一条 `pass`** —— 那是造假；没跑过就 `info`。
- ❌ **把日志/测试输出"整理"成结论**：只登记你真跑过的命令与它的结果，不要转述成更漂亮的说法。
- ❌ **一条证据糊整张任务**：`--criterion-id` 必须指向**具体那一条**标准；多条标准要挂多条。
- ❌ **`--ref` 里塞 `|`** 或塞一大段输出（用 `--note`，或把输出落到文件里再引用路径）。
- ❌ **用 `evidence add` 代替 `transition`**：想让任务进 REVIEW 就 `pm task transition --to REVIEW`；想让任务 DONE —— 找**人**。
- ❌ **忽略 CAS**：`exit 3`/`409` 说明你手上的 revision 过期 → 重新 `show` 再提交，别硬重试同一个 revision。
