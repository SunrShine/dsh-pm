/* tests/frontend/pm-inbox-status.test.mjs —— task-186：状态清单以源码为唯一来源的**交叉校验**单测 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  SOURCE_FILE, INBOX_STATUS_TABLE, INBOX_FILTER_STATUSES, LEGACY_STATUS,
  TERMINAL_STATUSES, isTerminalStatus, statusRows, STATE_MACHINE_NOTE,
} from '../../frontend_impl/pm-inbox-status.js';

const src = readFileSync(new URL('../../' + SOURCE_FILE, import.meta.url), 'utf8');

function constantsFromSource() {
  const out = {};
  const re = /^STATUS_([A-Z_]+) = "([A-Z_]+)"/gm;
  let m;
  while ((m = re.exec(src)) !== null) out[m[1]] = m[2];
  return out;
}

test('清单与 src/pm/inbox_ops.py 的 STATUS_* 常量逐条一致（唯一来源）', () => {
  const consts = constantsFromSource();
  const want = ['CAPTURED', 'TRIAGE', 'TASK_PROPOSED', 'TASK_CREATED', 'NOTE', 'ARCHIVED', 'SNOOZED', 'MERGED', 'DISMISSED'];
  want.forEach((k) => assert.equal(consts[k], k, '源码里应有 STATUS_' + k));
  const got = INBOX_STATUS_TABLE.map((s) => s.key);
  assert.deepEqual(got, want, '我们的顺序与清单必须与源码 9 个常量一致（不多不少）');
  assert.equal(new Set(got).size, got.length, '不能有重复');
  assert.match(src, /KNOWN_STATUSES = \(/, '源码里应有 KNOWN_STATUSES 聚合');
});

test('终止态集合与源码 TERMINAL_STATUSES 一致', () => {
  const m = /TERMINAL_STATUSES = frozenset\(\{([^}]*)\}\)/.exec(src);
  assert.ok(m, '源码里应能解析出 TERMINAL_STATUSES');
  const fromSrc = m[1].split(',').map((x) => x.trim()).filter(Boolean).map((x) => x.replace('STATUS_', ''));
  assert.deepEqual(fromSrc.slice().sort(), TERMINAL_STATUSES.slice().sort());
  TERMINAL_STATUSES.forEach((k) => assert.equal(isTerminalStatus(k), true));
  ['CAPTURED', 'TRIAGE', 'TASK_PROPOSED', 'TASK_CREATED', 'NOTE', 'SNOOZED'].forEach((k) =>
    assert.equal(isTerminalStatus(k), false, k + ' 不是终止态'));
  assert.equal(isTerminalStatus('SNOOZED'), false, '延期不是终止态（源码注释与 CLI 都是这个口径）');
});

test('每一行都有：中文名 + 含义 + 来源（不许空、不许省来源）', () => {
  statusRows().forEach((r) => {
    assert.ok(r.zh && r.zh.length >= 2, r.key + ' 要有中文名');
    assert.ok(r.meaning && r.meaning.length >= 6, r.key + ' 要有含义');
    assert.ok(r.source && r.source.length >= 8, r.key + ' 要写明来源');
    assert.match(r.source, /inbox_ops\.py:\d+/, r.key + ' 的来源要指到源码位置');
  });
  assert.equal(statusRows().length, 9);
});

test('含义与真实行为的两个关键点不被写错', () => {
  const by = {};
  statusRows().forEach((r) => { by[r.key] = r; });
  assert.match(by.TASK_PROPOSED.meaning, /批准后才创建正式任务/, '提案只是计划，批准才建任务');
  assert.match(by.NOTE.meaning, /不进任务列表/, 'note 进 memory 候选区');
  assert.match(by.SNOOZED.meaning, /不是终止态/, '延期可再处理');
  assert.match(by.ARCHIVED.meaning, /终止态/);
  assert.match(by.MERGED.meaning, /PM_MERGED_INTO/);
  assert.match(by.DISMISSED.meaning, /理由/);
});

test('状态机口径文案与源码注释一致（四个环节都在）', () => {
  ['CAPTURED', 'TRIAGE', 'TASK_PROPOSED', 'TASK_CREATED'].forEach((k) => assert.ok(STATE_MACHINE_NOTE.indexOf(k) >= 0));
  assert.equal(SOURCE_FILE, 'src/pm/inbox_ops.py');
});

/* ===== task-191：筛选下拉的防漂移对账（源码加状态而下拉没跟 → 这里必须红） ===== */

function knownStatusesFromSource() {
  const m = /KNOWN_STATUSES = \(([\s\S]*?)\)/.exec(src);
  assert.ok(m, 'inbox_ops.py 里应能解析出 KNOWN_STATUSES');
  const consts = constantsFromSource();
  return m[1].split(',').map((x) => x.trim()).filter(Boolean).map((name) => {
    const bare = name.replace('STATUS_', '');
    assert.ok(consts[bare], 'KNOWN_STATUSES 引用了未定义常量 ' + name);
    return consts[bare];
  });
}

test('筛选下拉 = KNOWN_STATUSES（顺序一致）+ LEGACY_UNTRACKED（最后）', () => {
  const want = knownStatusesFromSource();
  assert.equal(want.length, 9, 'KNOWN_STATUSES 应有 9 个规范状态');
  assert.deepEqual(INBOX_FILTER_STATUSES, want.concat([LEGACY_STATUS]),
    '下拉必须与源码 KNOWN_STATUSES 顺序一致，且 legacy 放最后（task-191）');
  assert.equal(INBOX_FILTER_STATUSES[INBOX_FILTER_STATUSES.length - 1], 'LEGACY_UNTRACKED');
  ['NOTE', 'MERGED', 'DISMISSED'].forEach((k) =>
    assert.ok(INBOX_FILTER_STATUSES.indexOf(k) >= 0, k + ' 必须能筛（以前漏了）'));
  assert.equal(INBOX_FILTER_STATUSES.length, 10);
});

test('legacy 常量确实存在于 src/pm/inbox.py（不是我们编的）', () => {
  const legacySrc = readFileSync(new URL('../../src/pm/inbox.py', import.meta.url), 'utf8');
  const m = /LEGACY_STATUS = "([A-Z_]+)"/.exec(legacySrc);
  assert.ok(m, 'inbox.py 里应有 LEGACY_STATUS 常量');
  assert.equal(m[1], LEGACY_STATUS, '我们用的 legacy 值必须与源码一致');
  assert.match(legacySrc, /没有 :ID:|无 :ID:|旧条目/, 'inbox.py 里应说明它是旧条目（无 :ID:）的状态');
});
