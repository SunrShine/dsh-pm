/* tests/frontend/pm-memory.test.mjs —— task-158（B1）记忆卡片纯逻辑单测（node --test，零依赖）。
 * 覆盖：短 ID 规则、完整 ID、双向取代关系、目标是否在本页、点击/复制文案。 */
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  MEM_SHORT_LEN, memoryShortId, memoryFullId, memoryLinks, memoryAllEntries, memoryPresentIds,
  memoryLinkLabel, memoryLinkNote, memoryCopyNote, memoryDiscardOutcome, memoryWriteErrorText,
  memoryMergeOptionText,
} from '../../frontend_impl/pm-memory.js';

const ID1 = 'memory-01M4T2S0ABCDEFGHIJKLMN';
const ID2 = 'memory-01M4T2S0ZZZZZZZZZZZZZZ';

test('memoryShortId：去前缀取前 8 位；无前缀也取前 8；空值写「未写入」', () => {
  assert.equal(MEM_SHORT_LEN, 8);
  assert.equal(memoryShortId(ID1), '01M4T2S0');
  assert.equal(memoryShortId('01M4T2S0XXXX'), '01M4T2S0', '没有 memory- 前缀时直接取前 8');
  assert.equal(memoryShortId('abc'), 'abc', '短于 8 位就原样');
  assert.equal(memoryShortId(''), '未写入');
  assert.equal(memoryShortId(null), '未写入');
  assert.equal(memoryShortId(undefined), '未写入');
  assert.equal(memoryShortId('memory-'), '未写入', '只有前缀 → 没内容可显示');
});

test('memoryFullId：原样返回；空值返回空串（调用方显示「未写入」）', () => {
  assert.equal(memoryFullId(ID1), ID1);
  assert.equal(memoryFullId(null), '');
  assert.equal(memoryFullId(undefined), '');
});

test('memoryLinks：双向关系都出；没有就空数组（不猜）', () => {
  const both = memoryLinks({ id: ID1, supersedes: ID2, supersededBy: 'memory-AAAABBBBCCCCDDDD' });
  assert.equal(both.length, 2);
  assert.equal(both[0].dir, 'supersedes');
  assert.equal(both[0].id, ID2);
  assert.equal(both[0].label, '取代 → 01M4T2S0');
  assert.equal(both[1].dir, 'supersededBy');
  assert.equal(both[1].label, '被 AAAABBBB 取代');
  assert.deepEqual(memoryLinks({ id: ID1 }), []);
  assert.deepEqual(memoryLinks(null), []);
  assert.deepEqual(memoryLinks({ supersedes: '' }), [], '空字符串不算关系');
});

test('memoryPresentIds：候选 + 正式都算「在本页」，跳过没有 id 的', () => {
  const ids = memoryPresentIds({ candidates: [{ id: ID1 }, { id: null }, {}], entries: [{ id: ID2 }] });
  assert.deepEqual(ids, [ID1, ID2]);
  assert.deepEqual(memoryPresentIds(null), []);
});

test('memoryLinkLabel：目标在本页就给原文案；不在就写明「目标不在本页」', () => {
  const link = memoryLinks({ supersedes: ID2 })[0];
  const here = memoryLinkLabel(link, [ID2]);
  assert.equal(here.present, true);
  assert.equal(here.label, '取代 → 01M4T2S0');
  const gone = memoryLinkLabel(link, [ID1]);
  assert.equal(gone.present, false);
  assert.equal(gone.label, '取代 → 01M4T2S0（目标不在本页）');
});

test('memoryLinkNote：找得到给「已跳到」；找不到给可执行的一句实话（不静默）', () => {
  const sup = memoryLinks({ supersedes: ID2 })[0];
  assert.equal(memoryLinkNote(sup, true), '已跳到 取代目标 01M4T2S0');
  const miss = memoryLinkNote(sup, false);
  assert.match(miss, /不在当前列表/);
  assert.match(miss, /没有可跳转的卡片/);
  assert.match(miss, /01M4T2S0/);
  const by = memoryLinks({ supersededBy: ID2 })[0];
  assert.equal(memoryLinkNote(by, true), '已跳到 被取代目标 01M4T2S0');
  assert.equal(memoryLinkNote(null, true), '');
});

test('memoryCopyNote：成功/失败两种文案都带完整 ID（失败也要给出可手工复制的信息）', () => {
  assert.equal(memoryCopyNote(true, ID1), '已复制完整 ID：' + ID1);
  const bad = memoryCopyNote(false, ID1);
  assert.match(bad, /复制失败/);
  assert.match(bad, new RegExp(ID1));
});

test('memoryLinks：supersededBy 字段缺失时，从同一份列表推导反向链（同一事实的另一半）', () => {
  const a = { id: ID1 };                                  /* 后端没给 supersededBy */
  const b = { id: ID2, supersedes: ID1 };
  const links = memoryLinks(a, [a, b]);
  assert.equal(links.length, 1);
  assert.equal(links[0].dir, 'supersededBy');
  assert.equal(links[0].id, ID2);
  assert.equal(links[0].label, '被 01M4T2S0 取代');
  assert.equal(links[0].derived, true, '推导出来的关系有标记');
  assert.deepEqual(memoryLinks(a), [], '不传列表就不推导（保持纯函数语义）');
  assert.deepEqual(memoryLinks(a, []), []);
});

test('memoryLinks：字段有 supersededBy 就用字段（不被推导覆盖）、不重复', () => {
  const a = { id: ID1, supersededBy: 'memory-EXPLICITID99' };
  const b = { id: ID2, supersedes: ID1 };
  const links = memoryLinks(a, [a, b]);
  assert.equal(links.length, 1);
  assert.equal(links[0].id, 'memory-EXPLICITID99');
  assert.equal(links[0].derived, false);
});

test('memoryAllEntries：候选 + 正式合并（推导用）', () => {
  const all = memoryAllEntries({ candidates: [{ id: ID1 }], entries: [{ id: ID2 }] });
  assert.deepEqual(all.map((e) => e.id), [ID1, ID2]);
  assert.deepEqual(memoryAllEntries(null), []);
});

test('memoryDiscardOutcome：真丢弃 vs 幂等重放（绝不能把幂等说成刚丢弃成功）', () => {
  const fresh = memoryDiscardOutcome({ status: 'DEPRECATED', changed: true, discarded: true, wasStatus: 'CANDIDATE' });
  assert.equal(fresh.idempotent, false);
  assert.match(fresh.note, /已丢弃/);
  assert.match(fresh.note, /DEPRECATED/);
  const replay = memoryDiscardOutcome({ status: 'DEPRECATED', changed: false, discarded: false });
  assert.equal(replay.idempotent, true);
  assert.match(replay.note, /已经丢弃过/);
  assert.match(replay.note, /幂等/);
  /* 字段落在 data 里也认（后端两种形状都出现过） */
  const nested = memoryDiscardOutcome({ data: { changed: false, discarded: false } });
  assert.equal(nested.idempotent, true);
  const nestedFresh = memoryDiscardOutcome({ data: { changed: true, discarded: true } });
  assert.equal(nestedFresh.idempotent, false);
  assert.equal(memoryDiscardOutcome(null).idempotent, false, '空响应不冒充幂等');
});

test('memoryWriteErrorText：code：message（缺 message 也照实说）', () => {
  assert.equal(memoryWriteErrorText('NOT_A_CANDIDATE', '请用 pm memory deprecate（保留取代链）'),
    'NOT_A_CANDIDATE：请用 pm memory deprecate（保留取代链）');
  assert.equal(memoryWriteErrorText('', ''), 'ERROR：后端没有给出 message');
  assert.equal(memoryWriteErrorText('REASON_REQUIRED', null), 'REASON_REQUIRED：后端没有给出 message');
});

test('memoryMergeOptionText：短 ID · 摘要 + 状态标记（候选/已确认/已废弃）', () => {
  assert.equal(memoryMergeOptionText({ id: ID1, text: '示例正文', status: 'CANDIDATE' }), '01M4T2S0 · 示例正文（候选）');
  assert.equal(memoryMergeOptionText({ id: ID1, text: '示例正文', status: 'VERIFIED' }), '01M4T2S0 · 示例正文（已确认）');
  assert.match(memoryMergeOptionText({ id: ID2, text: 'x'.repeat(80), status: 'DEPRECATED' }), /（已废弃）$/);
  assert.ok(memoryMergeOptionText({ id: ID2, text: 'x'.repeat(80) }).length < 70, '长文本截断到 40 字');
});
