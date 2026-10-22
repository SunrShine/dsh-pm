/* tests/frontend/pm-i18n.test.mjs —— task-204 一期 i18n 判据（有牙齿；负例见文末说明）。
 *
 * ① 每个 key 必须 zh/en 成对且非空；② **en 里不得出现中文**（外壳英文模式的核心口径，表级）；
 * ③ index.html 里每个 data-i18n* 的 key 都必须在表里（否则静态外壳会漏翻）；
 * ④ 缺 key 绝不渲染 undefined/空白（明确降级：en 缺→zh→key 本身）；⑤ 语言解析优先级；
 * ⑥ 语言切换持久化（localStorage 覆盖）。
 * 负例（人工跑，证明有牙齿）：副本里删掉某个 key 的 en / 把 en 改成空 → 本文件必须红。
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  LOCALES, DEFAULT_LANG, LANG_KEY, MESSAGES, resolveLang, lookup, t, setLang, detectLang, applyShell,
  format, placeholdersOf,
} from '../../frontend_impl/pm-i18n.js';

const HTML = readFileSync(new URL('../../frontend_impl/index.html', import.meta.url), 'utf8');
const CJK = /[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]/;

test('① 每个 key 都有非空 zh 与 en（缺一即红）', () => {
  const keys = Object.keys(MESSAGES);
  assert.ok(keys.length >= 60, '外壳键数量不该缩水（当前 ' + keys.length + '）');
  keys.forEach((k) => {
    const m = MESSAGES[k];
    assert.ok(m && typeof m.zh === 'string' && m.zh.trim().length > 0, k + ' 缺 zh');
    assert.ok(typeof m.en === 'string' && m.en.trim().length > 0, k + ' 缺 en');
  });
  assert.deepEqual(LOCALES, ['zh', 'en']);
  assert.equal(DEFAULT_LANG, 'zh');
});

/* 唯一白名单：语言开关按钮本身。英文界面下它必须显示「中文」（那是"切回中文"的按钮名），
   这不是漏翻。CDP 的"英文外壳不得出现中文"扫描同样排除这一个 [data-i18n="topbar.langSwitch"] 元素。 */
const LANG_NAME_KEYS = ['topbar.langSwitch'];

test('② 英文表里不得出现中文（语言开关按钮除外；英文模式外壳中文检测的表级保障）', () => {
  const bad = Object.keys(MESSAGES).filter((k) => CJK.test(MESSAGES[k].en));   /* 汉字 + 　-〿 + ＀-￯（含全角冒号/括号） */
  const unexpected = bad.filter((k) => LANG_NAME_KEYS.indexOf(k) < 0);
  assert.deepEqual(unexpected, [], '这些 key 的 en 里还有中文：' + unexpected.join(', '));
  assert.equal(MESSAGES['topbar.langSwitch'].en, '中文', '英文界面下这个按钮就叫「中文」（切回去）');
  assert.equal(MESSAGES['topbar.langSwitch'].zh, 'English', '中文界面下它叫「English」');
});

test('③ index.html 里每个 data-i18n* key 都在表里（静态外壳不许漏翻）', () => {
  const used = new Set();
  const re = /data-i18n(?:-title|-aria|-placeholder)?="([^"]+)"/g;
  let m;
  while ((m = re.exec(HTML)) !== null) used.add(m[1]);
  assert.ok(used.size >= 20, '静态外壳的 i18n 挂点不该太少（当前 ' + used.size + '）');
  const missing = [...used].filter((k) => !MESSAGES[k]);
  assert.deepEqual(missing, [], '这些 key 在 index.html 里用了但表里没有：' + missing.join(', '));
});

test('④ 缺 key 明确降级，绝不 undefined/空白', () => {
  assert.equal(t('no.such.key'), 'no.such.key');
  assert.equal(t('no.such.key', 'en'), 'no.such.key');
  assert.equal(lookup('no.such.key', 'en'), 'no.such.key');
  ['zh', 'en', 'fr', null, undefined, ''].forEach((l) => {
    const v = lookup('nav.board', l);
    assert.ok(typeof v === 'string' && v.trim().length > 0, '语言 ' + String(l) + ' 下 nav.board 不能为空');
  });
  assert.equal(t('nav.board', 'en'), 'Workbench');
  assert.equal(lookup('nav.board', 'fr'), MESSAGES['nav.board'].zh, '不支持的语言 → 中文兜底');
});

test('⑤ 语言解析优先级：URL > localStorage > 宿主 html[lang] > navigator > zh', () => {
  assert.equal(resolveLang({ url: 'en', stored: 'zh', host: 'zh', navigator: 'zh-CN' }), 'en');
  assert.equal(resolveLang({ stored: 'en', host: 'zh', navigator: 'zh-CN' }), 'en');
  assert.equal(resolveLang({ host: 'en', navigator: 'zh-CN' }), 'en');
  assert.equal(resolveLang({ navigator: 'en-US' }), 'en');
  assert.equal(resolveLang({}), 'zh');
  assert.equal(resolveLang({ url: 'fr', stored: 'fr', host: 'fr', navigator: 'fr' }), 'zh', '都不支持 → 中文兜底');
  assert.equal(detectLang({ search: '?lang=en&x=1', storage: 'zh', host: 'zh', navigator: 'zh-CN' }), 'en');
  assert.equal(detectLang({ search: '', storage: 'en', host: 'zh', navigator: 'zh-CN' }), 'en');
  assert.equal(detectLang({ search: '', storage: '', host: 'en', navigator: 'zh-CN' }), 'en');
  assert.equal(detectLang({ search: '', storage: '', host: '', navigator: 'en-GB' }), 'en');
});

test('⑥ 语言切换持久化（localStorage 覆盖）', () => {
  const store = new Map();
  globalThis.localStorage = {
    getItem: (k) => (store.has(k) ? store.get(k) : null),
    setItem: (k, v) => { store.set(k, String(v)); },
  };
  assert.equal(setLang('en'), 'en');
  assert.equal(store.get(LANG_KEY), 'en', '切换必须写进 localStorage（刷新后仍英文）');
  assert.equal(detectLang({ search: '', host: 'zh', navigator: 'zh-CN' }), 'en', '刷新后仍按存储的英文');
  assert.equal(setLang('zh'), 'zh');
  assert.equal(store.get(LANG_KEY), 'zh');
  assert.equal(setLang('nonsense'), 'zh', '不支持的语言 → 中文兜底');
  delete globalThis.localStorage;
});

test('⑦ applyShell 在没有 DOM 时安全返回 0（不炸）', () => {
  assert.equal(applyShell(null), 0);
  assert.equal(applyShell({}), 0);
});

/* task-204 追加（lead 2026-10-14）：拼接模板也必须进表 —— 被判据钉住两件事 */
test('⑧ 含占位符的模板：zh/en 占位符集合必须一致（防止只在一种语言里拼标点/漏参）', () => {
  const keys = Object.keys(MESSAGES).filter((k) => /\{(\w+)\}/.test(MESSAGES[k].zh) || /\{(\w+)\}/.test(MESSAGES[k].en));
  assert.ok(keys.length >= 3, '至少应有 theme/aria/dataSource 三个模板（当前 ' + keys.length + '）');
  keys.forEach((k) => {
    assert.deepEqual(placeholdersOf(MESSAGES[k].en), placeholdersOf(MESSAGES[k].zh), k + ' 的 zh/en 占位符不一致');
  });
});

test('⑨ format()：替换占位符、缺参不渲染 undefined、未知占位符留空', () => {
  assert.equal(format('{a}: {b} ({c})', { a: 'Theme', b: 'System', c: 'Light' }), 'Theme: System (Light)');
  assert.equal(format('{a}：{b}', { a: '主题', b: '跟随系统' }), '主题：跟随系统');
  assert.equal(format('{a}-{b}', { a: 'x' }), 'x-', '缺参 → 空串，不出现 undefined');
  assert.ok(format('{a}', {}).indexOf('undefined') < 0);
  assert.equal(format('no placeholder', { a: 1 }), 'no placeholder');
});

test('⑩ 用户可见的拼接都经 format()（app.js 里不得再按语言手拼全角标点）', () => {
  const app = readFileSync(new URL('../../frontend_impl/app.js', import.meta.url), 'utf8');
  /* 主题按钮那处历史写法：'…' + '：' + … 这类"字符串 + 全角标点字面量 + 字符串"必须已消失 */
  assert.ok(app.indexOf("t('topbar.theme') + '：'") < 0, 'app.js 里不该再手拼全角冒号');
  assert.ok(app.indexOf("'（' + LABEL[r.theme] + '）'") < 0, 'app.js 里不该再手拼全角括号');
  assert.ok(app.indexOf("format(t('topbar.themeFormat')") >= 0, '主题按钮必须走表里的模板');
  assert.ok(app.indexOf("format(t('topbar.themeAriaFormat')") >= 0, '主题 aria 也必须走表里的模板');
  assert.ok(app.indexOf("format(t('sub.dataSourceFormat')") >= 0, '副标题数据来源必须走表里的模板');
});
