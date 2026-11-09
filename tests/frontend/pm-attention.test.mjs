import { setLang } from '../../frontend_impl/pm-i18n.js';
/* task-C5S1V：本文件逐字比对中文文案 ⇒ 显式钉住语言（默认语言一变就会莫名红） */
setLang('zh');

/* tests/frontend/pm-attention.test.mjs —— task-184 纯逻辑单测（node --test，零依赖） */
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  DEFAULT_VISIBLE, suggestStale, suggestTodo, noRecordTime, COLLAPSE_KEY,
  daysSince, attentionReasons, attentionSuggestion, groupByProject, visibleCards,
  parseCollapse, serializeCollapse, expandAllText,
} from '../../frontend_impl/pm-attention.js';

const NOW = Date.parse('2026-10-13T18:00:00+08:00');
const stale = (days) => ({ observation: 'STALE_BUSY', recorded_at: new Date(NOW - days * 86400000).toISOString() });

test('daysSince：整天数；拿不到/非法时间返回 null', () => {
  assert.equal(daysSince(new Date(NOW - 2 * 86400000).toISOString(), NOW), 2);
  assert.equal(daysSince(new Date(NOW - 3600 * 1000).toISOString(), NOW), 0);
  assert.equal(daysSince(null, NOW), null);
  assert.equal(daysSince('不是时间', NOW), null);
});

test('attentionReasons：STALE_BUSY 与未完成 todo 两种逐字文案', () => {
  assert.deepEqual(attentionReasons(stale(2), NOW), ['缓存说它在忙，但已 2 天没有新记录，会话可能中断']);
  assert.deepEqual(attentionReasons({ open_todos: 3 }, NOW), ['还有 3 条未完成 todo']);
  assert.deepEqual(attentionReasons({ observation: 'STALE_BUSY', recorded_at: null }, NOW),
    ['缓存说它在忙，但' + noRecordTime() + '，会话可能中断']);
  assert.deepEqual(attentionReasons({ observation: 'STALE_BUSY', recorded_at: new Date(NOW).toISOString() }, NOW),
    ['缓存说它在忙，但不到 1 天没有新记录，会话可能中断']);
  assert.deepEqual(attentionReasons({ observation: 'RECENT' }, NOW), [], '没有判据就不编理由');
  assert.deepEqual(attentionReasons(null, NOW), []);
});

test('attentionReasons：两种判据同时成立时都给', () => {
  const c = Object.assign(stale(2), { open_todos: 4 });
  assert.deepEqual(attentionReasons(c, NOW), ['缓存说它在忙，但已 2 天没有新记录，会话可能中断', '还有 4 条未完成 todo']);
});

test('attentionSuggestion：STALE_BUSY 与 todo 各自一句；都没有就不给', () => {
  assert.equal(attentionSuggestion(stale(2)), suggestStale());
  assert.equal(attentionSuggestion({ open_todos: 1 }), suggestTodo());
  assert.equal(attentionSuggestion({ observation: 'RECENT' }), '');
});

test('groupByProject：按项目分组、保持出现顺序；没有 title 就用 key', () => {
  const cards = [
    { project: 'demo-chip', session_id: 'a' },
    { project: 'pm_tools', session_id: 'b' },
    { project: 'demo-chip', session_id: 'c' }
  ];
  const groups = groupByProject(cards, (k) => (k === 'demo-chip' ? 'demo-chip · 示例芯片项目' : ''));
  assert.equal(groups.length, 2);
  assert.equal(groups[0].key, 'demo-chip');
  assert.equal(groups[0].title, 'demo-chip · 示例芯片项目');
  assert.equal(groups[0].cards.length, 2);
  assert.equal(groups[1].key, 'pm_tools');
  assert.equal(groups[1].title, 'pm_tools', '没有 title 时退回 key');
  const noProject = groupByProject([{}], null);
  assert.equal(noProject[0].key, '（未标记项目）');
});

test('visibleCards：默认前 N 条；展开后全给；N 可配', () => {
  const cards = new Array(28).fill(0).map((_, i) => ({ i: i }));
  assert.equal(DEFAULT_VISIBLE, 7);
  assert.equal(visibleCards(cards, false).length, 7);
  assert.equal(visibleCards(cards, true).length, 28);
  assert.equal(visibleCards(cards, false, 5).length, 5);
  assert.equal(visibleCards([], false).length, 0);
});

test('折叠状态：解析/序列化稳定；坏数据当没折叠（不抛）', () => {
  assert.equal(COLLAPSE_KEY, 'pm-needsme');
  assert.deepEqual(parseCollapse(null), { propsCollapsed: false, cardsCollapsed: false, cardsExpanded: false });
  assert.deepEqual(parseCollapse('{oops'), { propsCollapsed: false, cardsCollapsed: false, cardsExpanded: false });
  assert.deepEqual(parseCollapse('"字符串"'), { propsCollapsed: false, cardsCollapsed: false, cardsExpanded: false });
  const st = { propsCollapsed: true, cardsCollapsed: false, cardsExpanded: true };
  assert.deepEqual(parseCollapse(serializeCollapse(st)), st);
});

test('expandAllText：逐字带数字', () => {
  assert.equal(expandAllText(28), '展开全部（28）');
  assert.equal(expandAllText(0), '展开全部（0）');
});