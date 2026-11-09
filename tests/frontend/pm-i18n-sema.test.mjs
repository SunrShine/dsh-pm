import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

/* 语义守卫（Lead 2026-10-16 常设要求）：改动涉及【表达式/布尔/回退】时补小测试。
   背景：i18n 收尾 D4 批把 esc(c.op || '变更') 改写成 esc(c.op || '' + esc(t('dfp.changeWord')) + '') ✗
   —— 语法合法、模块检查、单测、总门禁全都看不见 ✗，只有【回头读原文】才发现 ✗。
   这条测试把该处语义钉住：c.op 为空时必须回退到键 dfp.changeWord，且不得再用破坏优先级的拼接写法。 */
const APP = readFileSync(new URL('../../frontend_impl/app.js', import.meta.url), 'utf8');
const TBL = readFileSync(new URL('../../frontend_impl/pm-i18n.js', import.meta.url), 'utf8');

test('变更的 op 回退：c.op 为空时回退到 dfp.changeWord（且写成 t(...) 而不是拼接）', () => {
  assert.ok(APP.includes("esc(c.op || t('dfp.changeWord'))"), '回退必须是 esc(c.op || t(...))');
  assert.ok(!APP.includes("esc(c.op || '' + esc("), '不得再出现破坏优先级的 \'\' + esc(...) 写法');
  assert.ok(/"dfp\.changeWord":\s*\{\s*zh:/.test(TBL), '键 dfp.changeWord 必须在键表里（有 zh）');
  assert.ok(/"dfp\.changeWord":\s*\{\s*zh:\s*"[^"]+",\s*en:\s*"[^"]+"/.test(TBL), '键 dfp.changeWord 的 en 必须非空');
});

test('同族守卫：REV 字段括号两处都走格式键 dfp.revFieldFmt', () => {
  assert.ok(APP.includes("format(t('dfp.revFieldFmt'), { x: ':PM_PLAN_REVISION:' })"), ':PM_PLAN_REVISION: 走格式键');
  assert.ok(APP.includes("format(t('dfp.revFieldFmt'), { x: ':PM_BASE_REVISION:' })"), ':PM_BASE_REVISION: 走格式键');
});
