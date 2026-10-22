/* tests/frontend/pm-plain-copy.test.mjs —— task-202：界面文案"黑话"判据（有牙齿）。
 *
 * 口径（与 内部记录/05 的 C 系列"API payload 不得出现 正在运行/RUNNING"**不同**）：那条是**接口**口径，
 * 本条是**界面文案**口径 —— UI 可见文案里不许再出现「心跳」这种黑话，且必须给出
 * "看不出/不判断是否在跑"的如实说明（保留"只读快照"这个说法）。
 *
 * 负例（人工跑，证明有牙齿）：把两处文案改回「会话没有心跳」→ 本文件必须红。
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const read = (rel) => readFileSync(new URL('../../frontend_impl/' + rel, import.meta.url), 'utf8');
const HTML = read('index.html');
const APP = read('app.js');
const TABLE = read('pm-i18n.js');   /* task-204 起：空态/副标题等文案的唯一来源是文案表 */

test('① UI 源码里「心跳」命中 0（不再泄漏黑话）', () => {
  const inHtml = (HTML.match(/心跳/g) || []).length;
  const inApp = (APP.match(/心跳/g) || []).length;
  assert.equal(inHtml, 0, 'index.html 里不该再出现「心跳」');
  assert.equal(inApp, 0, 'app.js 里不该再出现「心跳」');
});

test('② 该处必须给出"看不出/不判断是否在跑"的如实说明', () => {
  /* task-C5S1V：这段话已从 index.html 搬进文案表（批次 A 要求 HTML 里 CJK == 0），
     因此断言随之改为「查表 + 查钩子」—— 语义不变（仍然逐字要求同一句话 + 仍然要求侧栏保留该区分）。
     修前红：本文件在搬文案后立刻红（HTML.indexOf(这句) = -1）✓；修后绿：见本次提交 ✓ */
  assert.ok(HTML.indexOf('data-i18n="aside.body"') >= 0,
    '侧栏那段说明必须挂 data-i18n="aside.body" 钩子（文案不再直接写死在 HTML）');
  assert.ok(TABLE.indexOf('会话此刻是否还在跑，快照里看不出来') >= 0,
    '文案表里要逐字保留「会话此刻是否还在跑，快照里看不出来」');
  assert.ok(TABLE.indexOf('不说「它现在正在跑」') >= 0, '文案表仍要保留"不说它在跑"的区分');
  assert.ok(TABLE.indexOf('只读快照：会话此刻是否还在跑，快照里看不出来') >= 0,
    '副标题的「只读快照：会话此刻是否还在跑，快照里看不出来」必须逐字在文案表里（task-204 起文案的唯一来源）');
  assert.ok(APP.indexOf("t('sub.board')") >= 0, 'app.js 的副标题必须从表里取（sub.board）');
});

test('③ 旧黑话文案不得残留（改回去必须红）', () => {
  assert.ok(HTML.indexOf('会话没有心跳') < 0, 'index.html 不该残留旧句');
  assert.ok(APP.indexOf('会话没有心跳') < 0, 'app.js 不该残留旧句');
  assert.ok(TABLE.indexOf('会话没有心跳') < 0, '文案表里也不该残留旧句');
  assert.ok(APP.indexOf('这里不判断它是否正在跑') < 0, 'app.js 不该残留旧句尾部');
});
