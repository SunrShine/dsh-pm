/* tests/frontend/pm-memory-split.test.mjs —— task-218 判据
 * ①候选区只列 pending（status==='CANDIDATE'）②已处理进折叠（拆解/摘要逐字）③**计数/徽章/空态/列表同一来源**（结构断言）
 * 负例：夹具里放一条 VERIFIED 候选 → pending 里不得出现；把 app.js 的过滤拿掉 → 结构断言必须红。
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { splitCandidates, processedBreakdown, processedSummaryText, processedSummaryParts, processedStatusChip } from '../../frontend_impl/pm-memory.js';

const APP = readFileSync(new URL('../../frontend_impl/app.js', import.meta.url), 'utf8');
const cand = (id, status) => ({ id, status, type: 'fact', text: 't', revision: 1 });

test('① splitCandidates：只有 CANDIDATE 进待确认；VERIFIED/DEPRECATED/异常值一律算已处理', () => {
  const s = splitCandidates([cand('a', 'CANDIDATE'), cand('b', 'VERIFIED'), cand('c', 'DEPRECATED'), cand('d', undefined), cand('e', 'WEIRD')]);
  assert.deepEqual(s.pending.map((e) => e.id), ['a']);
  assert.deepEqual(s.processed.map((e) => e.id), ['b', 'c', 'd', 'e'], '异常/缺失状态不得混进待确认（不猜）');
  assert.equal(s.all.length, 5);
  assert.deepEqual(splitCandidates(null).pending, []);
});

test('② 已处理拆解与逐字摘要/标记', () => {
  const processed = [cand('b', 'VERIFIED'), cand('c', 'DEPRECATED'), cand('d', 'VERIFIED')];
  assert.deepEqual(processedBreakdown(processed), { verified: 2, deprecated: 1, other: 0, total: 3 });
  assert.equal(processedSummaryText(processed), '已处理 3 条（已确认 2 / 已丢弃 1）');
  assert.equal(processedStatusChip(cand('b', 'VERIFIED')), '已确认');
  assert.equal(processedStatusChip(cand('c', 'DEPRECATED')), '已丢弃');
  assert.equal(processedStatusChip(cand('e', 'WEIRD')), 'WEIRD', '异常状态原样显示，不编');
  assert.equal(processedStatusChip({}), '状态未返回');
});

test('③ 结构断言：计数/徽章/空态/列表必须来自同一份 pending（不能"计数说 3、列了 2"）', () => {
  const has = (s) => APP.indexOf(s) >= 0;
  /* 2026-10-21（用户「两处记录数量不一致」）：候选集合现在**先按当前 scope 过滤**再拆分
     （scope 过滤从服务端移到客户端，与 entries 同一口径）⇒ 断言按意图放宽为"经 splitCandidates 且带 scope 过滤" ✓ */
  assert.ok(/var candSplit = splitCandidates\(\(?\(m && m\.candidates\) \|\| \[\]\)?\.filter\(memInScope\)\)/.test(APP),
    '候选集合必须经 splitCandidates 拆分（且先按当前 scope 过滤，计数与列表同口径）');
  assert.ok(has("var candidates = candSplit.pending;"), 'candidates 必须是 pending（候选区只列待确认）');
  /* 2026-10-19 用户裁定：指标卡（metrics）删除 ⇒ 统计只留**一行**；把断言挪到统计行上（意图不变：计数用同一份 candidates ✓）*/
  assert.ok(has("format(t('memp.statsLine'), { n: candidates.length + entries.length, c: candidates.length"), '统计行必须用同一份 candidates');
  /* 2026-10-19 用户裁定（B3 与 内部记录/23 对齐）：#entries 拍平为单一列表、删候选 panel 与类型分组、删已处理折叠 =>
     以下断言按**意图**改写：计数与列表必须同源，且不再有已处理折叠这类外壳。*/
  assert.ok(has("memoryTierBar(candidates.length, entries.length, deprecated.length)"), '档位计数必须用同一份 candidates（与列表同源）');
  assert.ok(has("var flat = tier === 'candidate'") && has("? candidates"), '候选档列表直接从同一份 candidates 取（计数说几就列几）');
  assert.ok(has("tier === 'candidate' ? 'memp.candidatesEmpty'"), '候选档空态在统一空态链里（不再单独 panel）');
  assert.equal(has("foldKey('memory', 'processed'"), false, '用户 2026-10-19 裁定：已处理折叠已去掉（示例 #entries 无此块）');
  assert.ok(has("var shownIds = shownCandidates.concat(shownProcessed).concat(shownVerified)"), 'shownIds 仍含 shownProcessed（取代链判定口径不变）');
});

test('负例口径：夹具里一条 VERIFIED → pending 不得含它（去掉过滤必红）', () => {
  const s = splitCandidates([cand('x', 'CANDIDATE'), cand('y', 'VERIFIED')]);
  assert.equal(s.pending.some((e) => e.id === 'y'), false, '已确认的候选绝不能留在候选区');
  assert.equal(s.pending.length, 1, '计数（=pending.length）必须与列表一致');
});

/* ===== task-227：other 必须出现在摘要里，且 X+Y+Z === N ===== */

test('[227] other=0 → 摘要不含「其他」；other>0 → 追加「其他 Z」', () => {
  const noOther = [cand('a', 'VERIFIED'), cand('b', 'DEPRECATED')];
  const s1 = processedSummaryText(noOther);
  assert.equal(s1, '已处理 2 条（已确认 1 / 已丢弃 1）');
  assert.equal(s1.indexOf('其他'), -1, 'other=0 时不得出现「其他」');
  const withOther = noOther.concat([cand('c', 'FOO')]);
  const s2 = processedSummaryText(withOther);
  assert.equal(s2, '已处理 3 条（已确认 1 / 已丢弃 1 / 其他 1）');
  const two = noOther.concat([cand('c', 'FOO'), cand('d')]);
  assert.equal(processedSummaryText(two), '已处理 4 条（已确认 1 / 已丢弃 1 / 其他 2）');
});

test('[227] 不变量：X + Y + Z === N（对每种组合都成立）', () => {
  const cases = [
    [], [cand('a', 'VERIFIED')], [cand('a', 'DEPRECATED')], [cand('a', 'FOO')],
    [cand('a', 'VERIFIED'), cand('b', 'FOO')],
    [cand('a', 'VERIFIED'), cand('b', 'DEPRECATED'), cand('c', 'FOO'), cand('d', 'WEIRD'), cand('e')],
  ];
  cases.forEach((list) => {
    const p = processedSummaryParts(list);
    assert.equal(p.verified + p.deprecated + p.other, p.total, 'X+Y+Z 必须等于 N（' + JSON.stringify(p) + '）');
    assert.equal(p.total, list.length);
  });
});

test('[227] 负例口径：把 other 从摘要里去掉（或硬写 0）→ 断言必须红', () => {
  const withOther = [cand('a', 'VERIFIED'), cand('b', 'FOO')];
  const s = processedSummaryText(withOther);
  assert.ok(s.indexOf('其他 1') >= 0, '必须含「其他 Z」');
  /* 负例：模拟"漏掉 other"的实现（等于旧版）→ 下面这条断言必然失败 */
  const buggy = '已处理 ' + withOther.length + ' 条（已确认 1 / 已丢弃 0）';
  assert.notEqual(buggy, s, '旧版文案与新版不同（去掉 other 就与 N 对不上）');
  assert.ok(buggy.indexOf('其他') < 0 && buggy.indexOf(String(withOther.length)) >= 0, '旧版确实少算 other ✓');
});
