# 贡献指南

感谢你愿意参与 dsh-pm。这份仓库是「Python 后端 + 内嵌静态前端 + DSH 插件包」的复合仓库，
改动前请先读一遍 README.md。

## 环境

- **Python >= 3.11**：后端只用标准库，不需要装依赖。
- **Node.js >= 22**（推荐 24）：仅用于前端机械守卫 frontend_impl/selfcheck.mjs
  和 tests/test_subagents.py 里的 zstd 探针（没有 node 时该组测试会自动跳过）。
- 不需要 DSH 检出也能跑测试；只有本机验证脚本才需要 DSH。

## 跑测试（提交前必做）

~~~sh
./bin/test                              # Python 单元测试（标准库 unittest）
node frontend_impl/selfcheck.mjs        # 前端机械守卫：重名 / 语法 / CSS 配平 / 表单接线
~~~

CI（.github/workflows/ci.yml）只跑上面这两条。那些需要无头 Chrome 的本机验证脚本
**不随公开副本发布**，也不在 CI 里跑。

## 提交与 PR

- 一个 commit 只做一件事，message 用中文或英文都可以，写清「为什么」；
- PR 请填 .github/PULL_REQUEST_TEMPLATE.md，并贴出 ./bin/test 与 selfcheck 的输出；
- 不要提交任何**真实笔记库内容、真实绝对路径、凭据或 token**；示例一律用假数据（如 demo）。

## 设计约束（改代码前请先看）

- **Org 是唯一真源**：DSH 只是只读输入，不能把投影当成事实；
- **人工文件只读 / 只追加**：机器只在文件缺失时创建模板，此后不改写人工内容；
- **写入必须先 CAS 再原子写**：PM_REVISION 不匹配就拒绝，绝不半写；
- **诚实优先**：缺数据就写「未建立」，不要用推测填满界面。
## DSH 兼容性（维护者须知）

**人读的最低版本**：插件半需要 **DSH ≥ 0.2.1-alpha.1**（CLI 与三条 skill 不需要 DSH）。这句话在
`README.md` / `README.zh-CN.md` / `USAGE.md` / `USAGE.zh-CN.md` 四处同步：改一处就要四处一起改。

**机器闸门的机制**（DSH 侧 `packages/boot/app-boot/src/plugin-compatibility.ts`）：

- 只检查 peer 名字是 `@deepseek-ai/dsh` 或 `@deepseek-ai/dsh-*` 的依赖（`@deepseek-ai/cordis`、`react` 等不检查）；
- 比较对象是 **DSH 运行时版本**（`dsh --version`，当前 `0.2.1-alpha.1`）；
- 不满足就 **拒绝加载**，并提示救援命令：
  `dsh plugin allow-version <pkg@ver> --dsh-version <exact> --accept-risk`。

**本仓库刻意不声明任何 `@deepseek-ai/dsh*` peer**（照 `dsh-flow` 先例），原因有二：

1. 保持「不触发兼容闸门」，让插件在更多 DSH 版本上先能装上、再看行为；
2. semver 的预发布规则会 **反向挡人**：`includePrerelease:false` 下 `*`、`^0.2.1` 都**不满足** `0.2.1-alpha.1`；
   而 `^0.2.1-alpha.1` / `>=0.2.1-alpha.1` 又要求预发布落在**同一 `[major,minor,patch]` 元组** ⇒ 将来的
   `0.3.0-alpha.x` **也不会**满足 `>=0.2.1-alpha.1`，等于用一个「最低版本」声明把更高版本挡在门外。

**若将来确实要强制**（例如 DSH 出了稳定版后再议）：peer 写 `">=0.2.1-alpha.1 <0.3.0"`；
**不要**写 `^0.2.1`、`*`、`workspace:*`（前两者实测都不满足 `0.2.1-alpha.1`，`workspace:` 更不是合法 range），
并在文档里注明「更高版本需要 `allow-version` 救援」。

