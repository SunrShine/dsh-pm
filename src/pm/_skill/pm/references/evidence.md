# 验收证据（pm task evidence）

> 证据是**事实登记**，不是验收动作：挂满 `pass` 也不代表任务可以 `DONE`（`DONE` 只由人写）。

## 落在哪：任务正文的 `*** 证据（验收）` 节

位置固定在 `*** 验收标准` **之后**（不存在则首次追加）。每行一条，**自由文本放最后**：

```text
- <criterion-id> | <kind> | <result> | <ref> | <at> | <actor> | <note 自由文本…>
```

- `kind` ∈ `test | build | manual | artifact | review | other`
- `result` ∈ `pass | fail | info` —— **不知道就写 `info`，绝不许猜 `pass`**
- `ref`：commit / 路径 / URL / 命令文本；**不得含 `|`**（塞不下就放 `--note`，工具会拒绝并提示）

## 命令

```sh
pm task evidence add <task-id> --project KEY --criterion-id c-1a2b \
    --kind test --result pass --ref <commit|path|url|command> [--note TEXT] \
    --expected-revision N [--actor human|ai|system] [--reason R] [--idempotency-key K] [--dry-run]
pm task evidence list <task-id> --project KEY [--json]      # 每条给出可核对 id（如 e-1a2b）
pm task evidence rm <task-id> <EVIDENCE_ID> --project KEY --reason R \
    --expected-revision N [--actor …] [--dry-run]              # 按 id 移除那一条（CAS + 一条审计）
```

## 校验与写入语义

- `--criterion-id` 必须存在于该任务的验收标准里，否则 `CRITERION_NOT_FOUND`（extra 里带现有 IDs）。
- `kind`/`result`/`actor` 按枚举校验；`ref` 含 `|` → 拒绝。
- 一次 `entities.apply_change`：**CAS + 一条审计** `op=evidence-add criterion=<id> kind=<k> result=<r>`；
  `--idempotency-key` 重复提交 → `changed:false`、不再写第二次；`--dry-run` 零写入。
- 任务处于终态（DONE/CANCELLED）→ 拒绝（`TASK_TERMINAL`）。
- **批量写库必须先读后写，不要缓存 revision**：每次写入都会让 `:PM_REVISION:` **+1** ——
  例如给一个任务连挂 6 条证据，若把首条的 rev 写死复用，**后 5 条会全部 `REVISION_CONFLICT`（exit 3）** ✗；
  正确做法是**每条写之前重新读当前 rev**（`pm task show <task-id> --json` 的 `task.revision`）再写 ⇒ 6 条全成功 ✓。

## 证据 id 与移除（`rm`）

- 每条证据都有 **可核对 id**（`e-1a2b` 形态），`evidence list` / `task show --json` 都给出；它是**内容寻址**的
  （由 criterionId/kind/result/ref/at/actor/note 算出来，行内容不变则 id 稳定），所以**磁盘行格式没变**、老证据也有 id。
- **移除用 id**：`pm task evidence rm <task-id> <evidence-id>` —— 找不到 id → `EVIDENCE_NOT_FOUND`（exit 2，错误里带现有 ids），
  revision 不匹配 → `REVISION_CONFLICT`（exit 3，零写入）；终态任务拒绝（`TASK_TERMINAL`）；干跑加 `--dry-run`。
- `pm task list --json` 每行给 `evidenceCount` + `lastEvidence`（最近一条的 id/kind/result/ref/at），一眼看出"有几条、最近一条是什么"。

## 读模型

- `pm task show --json` → `evidence[]`（每项 `{criterionId, kind, result, ref, at, actor, note, raw, line}`）+ `evidenceCount`。
- `pm task list --json` 每行给 `evidenceCount` + `lastEvidence`（不塞数组，避免列表膨胀）。

## 给 AI 的纪律（重要）

1. **挂证据 ≠ 代替验收**：`--actor ai` 只能登记事实；把任务推到 `REVIEW` 就够了，`DONE` 等人。
2. **不确定就 `info`**：没真跑过测试/构建，就别写 `pass`；写 `info` + 说明你看到了什么。
3. **一证据一项**：`--criterion-id` 要指向那条**具体**的验收标准，不要拿一条证据糊整张任务。
4. **ref 要可回查**：commit / 文件路径 / URL / 真跑过的命令；不要写"已验证"这种没有指向的话。
5. **先转状态再挂证据**：`pm task evidence add` **不拦**在 `TODO` 上的写入（有意的：证据可以先于开工存在），
   所以"先 `DOING` 再挂证据、完成后 `REVIEW`"只能靠流程。今天同一实现者一天内**两次**忘了转状态就挂证据，
   其中一次随后 transition 直接吃 `INVALID_TRANSITION`（跳到"完成"时状态还没走过合法路径）✗。
   ⇒ 写证据前先 `pm task show <task-id> --json` 看 `status`；不是 `DOING` 就补 `TODO → NEXT → DOING` 再写 ✓。
