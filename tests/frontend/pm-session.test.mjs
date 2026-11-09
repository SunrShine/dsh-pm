import { setLang } from '../../frontend_impl/pm-i18n.js';
/* task-C5S1V：本文件逐字比对中文文案 ⇒ 显式钉住语言（默认语言一变就会莫名红） */
setLang('zh');

/* tests/frontend/pm-session.test.mjs —— task-171 向导会话列表纯逻辑单测（node --test，零依赖） */
import test from 'node:test';
import assert from 'node:assert/strict';
import {

  SESSION_SHORT_LEN, noNameText, sessionShortId, sessionDisplayName, sessionIdentityMissing,
  mergeIdentity, cardsById, partitionSessions, visibleSessions, peerToggleText,
} from '../../frontend_impl/pm-session.js';

const REAL = { id: 'session-11111111-2222-3333-4444-555555555555', session_mode: 'one-shot', session_name: '真会话 A' };
const PEER1 = { id: 'session-aaaaaaaa-2222-3333-4444-555555555555', session_mode: 'continuable', session_label: 'pm-api', session_name: 'pm-api' };
const PEER2 = { id: 'session-bbbbbbbb-2222-3333-4444-555555555555', session_mode: 'continuable', session_label: 'pm-api', session_name: 'pm-api' };
const OLD = { id: 'session-cccccccc-2222-3333-4444-555555555555' };

test('sessionShortId：去 session- 前缀取 8 位；异常输入安全', () => {
  assert.equal(SESSION_SHORT_LEN, 8);
  assert.equal(sessionShortId('session-11111111-2222'), '11111111');
  assert.equal(sessionShortId('11111111-2222'), '11111111');
  assert.equal(sessionShortId('abc'), 'abc');
  assert.equal(sessionShortId(''), '');
  assert.equal(sessionShortId(null), '');
});

test('sessionDisplayName：name → label → 非注入 title → 无标题会话+短 id；注入 title 不当名字', () => {
  assert.equal(sessionDisplayName({ id: 'session-x', session_name: '名字' }), '名字');
  assert.equal(sessionDisplayName({ id: 'session-x', session_label: '队友甲' }), '队友甲');
  assert.equal(sessionDisplayName({ id: 'session-11111111-2', session_title: '普通标题' }), '普通标题');
  assert.equal(sessionDisplayName({ id: 'session-11111111-2', session_title: '<system-reminder> You are teammate "pm-f…' }),
    noNameText() + ' · 11111111', '注入文本（< 开头）不能当名字');
  assert.equal(sessionDisplayName({ id: 'session-11111111-2' }), noNameText() + ' · 11111111');
  assert.equal(sessionDisplayName({}), noNameText());
});

test('sessionIdentityMissing：三个身份字段全缺才算缺', () => {
  assert.equal(sessionIdentityMissing(OLD), true);
  assert.equal(sessionIdentityMissing(REAL), false);
  assert.equal(sessionIdentityMissing({ session_title: null, session_label: '', session_mode: null, session_name: null }), true);
  assert.equal(sessionIdentityMissing({ session_mode: 'one-shot' }), false);
});

test('mergeIdentity + cardsById：context 端点没带的字段，按 session_id 从 cards 补齐', () => {
  const cards = [{ session_id: OLD.id, session_mode: 'one-shot', session_name: '卡片里的名字', session_label: null, session_title: null }];
  const idx = cardsById(cards);
  const merged = mergeIdentity(OLD, idx);
  assert.equal(merged.session_name, '卡片里的名字');
  assert.equal(merged.session_mode, 'one-shot');
  assert.equal(sessionIdentityMissing(merged), false);
  const missing = mergeIdentity(OLD, cardsById([]));
  assert.equal(sessionIdentityMissing(missing), true, '补不到就仍然如实算缺字段');
  assert.equal(mergeIdentity(REAL, idx).session_name, '真会话 A', '已有字段不被覆盖');
});

test('partitionSessions：真会话 / 队友 / 身份未知三堆；未知的**不能**被藏掉', () => {
  const parts = partitionSessions([REAL, PEER1, PEER2, OLD], cardsById([]));
  const idsOf = (arr) => arr.map((s) => String(s.id));
  assert.equal(parts.real.length, 1);
  assert.equal(parts.peers.length, 2);
  assert.equal(parts.unknown.length, 1);
  assert.equal(parts.identityMissing, true);
  assert.equal(visibleSessions(parts, false).length, 2, '默认 = 真会话 + 身份未知（队友要开关）');
  assert.equal(visibleSessions(parts, true).length, 4, '打开开关 = 全部');
  assert.equal(idsOf(visibleSessions(parts, false)).indexOf(PEER1.id), -1);
  assert.equal(idsOf(visibleSessions(parts, false)).indexOf(OLD.id) >= 0, true, '身份未知的默认也要显示（partitionSessions 会拷贝对象，按 id 比）');
});

test('同名消歧：同名队友/会话在 label 后附短 id；不同名不加', () => {
  const parts = partitionSessions([REAL, PEER1, PEER2], cardsById([]));
  const l1 = parts.label(PEER1);
  const l2 = parts.label(PEER2);
  assert.notEqual(l1, l2, '同名两条必须能区分');
  assert.match(l1, /^pm-api · [ab]{8}$/);
  assert.match(l2, /^pm-api · [ab]{8}$/);
  assert.equal(parts.label(REAL), '真会话 A', '不同名不加后缀');
});

test('peerToggleText：数字写在开关上（不静默隐藏）', () => {
  const parts = partitionSessions([REAL, PEER1, PEER2], cardsById([]));
  assert.equal(peerToggleText(parts), '显示子 agent / 团队队友（2）');
  assert.equal(peerToggleText({ peers: [] }), '显示子 agent / 团队队友（0）');
});
