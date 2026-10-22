/* tests/frontend/pm-project-select.test.mjs —— task-217 判据（负例：把来源换成 null → 必须走"未就绪"分支） */
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  PROJECT_MANUAL, PROJECT_NEW, projectLabel, projectFieldKind, projectOptionRows, projectFieldModel,
  notReadyText, emptyText,
} from '../../frontend_impl/pm-project-select.js';

const P = (key, title, extra) => Object.assign({ key, title }, extra || {});

test('① 名字优先、key 次要：label 用 title（与 key 不同时），secondary 始终是 key', () => {
  const rows = projectOptionRows([P('demo', 'PeTree 张量处理器'), P('pm_tools', 'pm_tools')], '');
  assert.equal(rows[0].label, 'PeTree 张量处理器');
  assert.equal(rows[0].secondary, 'demo', 'key 仍作为次要信息保留');
  assert.equal(rows[1].label, 'pm_tools', 'title 与 key 相同 → 只用 key 一次，不重复');
  assert.equal(projectLabel({ key: 'x', title: '' }), 'x');
  assert.equal(projectLabel({ key: 'x' }), 'x');
});

test('② 同名用 key 消歧（task-171 同口径）', () => {
  const rows = projectOptionRows([P('a1', '同名项目'), P('a2', '同名项目'), P('b', '别的')], '');
  assert.equal(rows[0].label, '同名项目 · a1');
  assert.equal(rows[1].label, '同名项目 · a2');
  assert.notEqual(rows[0].label, rows[1].label, '同名两条必须可区分');
  assert.equal(rows[2].label, '别的', '不同名的不加后缀');
});

test('③ 预选：prefill 命中的行 selected（按 key）', () => {
  const rows = projectOptionRows([P('a', 'A'), P('b', 'B')], 'b');
  assert.deepEqual(rows.map((r) => r.selected), [false, true]);
});

test('④ 未就绪 vs 空：null 是"未就绪"、[] 是"读到但没有"，两者都不得渲染空菜单', () => {
  assert.equal(projectFieldKind(null), 'not-ready');
  assert.equal(projectFieldKind(undefined), 'not-ready');
  assert.equal(projectFieldKind([]), 'empty');
  assert.equal(projectFieldKind([P('a', 'A')]), 'select');
  const nr = projectFieldModel(null, 'demo');
  assert.equal(nr.manualOnly, true);
  assert.equal(nr.rows.length, 0);
  assert.equal(nr.value, 'demo', '未就绪时保留手动输入的原值');
  assert.match(nr.note, /未就绪/);
  assert.match(nr.note, /GET \/ui-pm\/cards/, '如实写出数据来源');
  const em = projectFieldModel([], '');
  assert.equal(em.manualOnly, true);
  assert.match(em.note, /0 个项目/);
  assert.ok(notReadyText('GET /ui-pm/cards').indexOf('未返回') > 0);
  assert.ok(emptyText('GET /ui-pm/cards').indexOf('0 个项目') > 0);
});

test('⑤ 有项目时给出可选菜单模型：含（不指定）语义 + 可开关的"其他…手动输入"', () => {
  const m = projectFieldModel([P('a', 'A')], '', { sourceLabel: 'GET /ui-pm/cards' });
  assert.equal(m.kind, 'select');
  assert.equal(m.optional, true);
  assert.equal(m.emptyLabel, '（不指定）');
  assert.match(m.manualLabel, /手动输入 key/, '逃生口必须在');
  assert.equal(m.newProject, false, '默认不出现"＋ 新建项目…"（那是批准/提案路径的选项）');
  const m2 = projectFieldModel([P('a', 'A')], '', { withNewProject: true });
  assert.equal(m2.newProject, true);
  assert.equal(PROJECT_MANUAL, '__manual__');
  assert.equal(PROJECT_NEW, '__new__');
});

test('负例口径：把来源拿掉（null）→ 模型必须 manualOnly 且 note 写明未就绪（不是空菜单）', () => {
  const m = projectFieldModel(null, '', { sourceLabel: 'GET /ui-pm/cards' });
  assert.equal(m.kind, 'not-ready');
  assert.equal(m.manualOnly, true, '负例：绝不能变成 kind=select 的空菜单');
  assert.ok(m.note.indexOf('未就绪') >= 0);
});
