/* tests/frontend/pm-fold.test.mjs —— task-209 折叠状态单测（负例：把回填 open 去掉 → foldDetailsHtml 输出无 open → 本文件红） */
import test from 'node:test';
import assert from 'node:assert/strict';
import { foldIsOpen, setFold, foldKey, foldDetailsHtml, foldKeyFromTarget, FOLD_KEY_ATTR } from '../../frontend_impl/pm-fold.js';

test('默认关闭；用户展开后保持；用户关回后保持关闭（不因重渲染回默认）', () => {
  const m = {};
  assert.equal(foldIsOpen(m, 'closed:demo01', false), false, '默认关闭');
  setFold(m, 'closed:demo01', true);
  assert.equal(foldIsOpen(m, 'closed:demo01', false), true, '展开态进 map 后保持 ✓（这就是修复点）');
  setFold(m, 'closed:demo01', false);
  assert.equal(foldIsOpen(m, 'closed:demo01', false), false, '关回去也保持');
  assert.equal(foldIsOpen(m, 'brief:scope', true), true, 'defaultOpen=true 时默认展开');
  setFold(m, 'brief:scope', false);
  assert.equal(foldIsOpen(m, 'brief:scope', true), false, '用户显式关过 → 尊重用户');
});

test('foldKey：拼出稳定键、丢掉空段', () => {
  assert.equal(foldKey('closed', 'demo01'), 'closed:demo01');
  assert.equal(foldKey('kanban', 'closed', null, ''), 'kanban:closed');
  assert.equal(foldKey('history', undefined, 'task-1'), 'history:task-1');
});

test('foldDetailsHtml：open 由 map 决定（回填），并带 data-fold-key', () => {
  const m = {};
  const closed = foldDetailsHtml(m, 'closed:demo01', '展开 5 条已结束任务', '<div>cards</div>', { cls: 'kanban-fold' });
  assert.match(closed, /^<details class="kanban-fold" data-fold-key="closed:demo01">/, '未展开 → 不带 open：' + closed.slice(0, 60));
  assert.ok(closed.indexOf(' open') < 0, '未展开时不能带 open 属性');
  assert.ok(closed.indexOf("<summary>展开 5 条已结束任务</summary><div>cards</div></details>") >= 0, "summary 与正文顺序正确");
  setFold(m, 'closed:demo01', true);
  const open = foldDetailsHtml(m, 'closed:demo01', 's', 'b', { cls: 'kanban-fold' });
  assert.match(open, /data-fold-key="closed:demo01" open>/, '展开态必须回填 open（修复的核心）：' + open.slice(0, 70));
});

test('FOLD_KEY_ATTR 稳定（委派监听依赖它）', () => {
  assert.equal(FOLD_KEY_ATTR, 'data-fold-key');
});

test('foldKeyFromTarget：从子节点也能找到最近的可折叠祖先（含 open 值）', () => {
  const summary = { getAttribute: () => null, parentElement: null };
  const details = { getAttribute: (k) => (k === FOLD_KEY_ATTR ? 'closed:demo01' : null), open: true, parentElement: null };
  summary.parentElement = details;
  assert.deepEqual(foldKeyFromTarget(summary), { key: 'closed:demo01', open: true });
  assert.equal(foldKeyFromTarget({ getAttribute: () => null, parentElement: null }), null);
  assert.equal(foldKeyFromTarget(null), null);
});
