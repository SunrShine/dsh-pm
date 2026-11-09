#!/usr/bin/env node
/*
 * frontend_impl 机械守卫（零依赖、零构建）：node frontend_impl/selfcheck.mjs
 *
 * 1) 顶层 function 声明不得重名 —— JS 里后声明静默覆盖先声明。
 *    task-100：扫描**全部 frontend_impl/*.js**，且声明正则允许 export / export default 前缀
 *    （扁平 ESM 的 export function/const 必须同样被计数与查重）。
 *    2026-10-12 事故：task-45 新加的 projectByKey 覆盖了项目页用的同名函数，
 *    项目页因此显示「找不到项目 <key>」，静态检查完全看不出来。
 * 2) 顶层「已 export」的 var/let/const 重名 → 硬失败（模块导出面撞名）；非 export 的只告警（有时是刻意复用）。
 *    「顶层」= IIFE 体内的声明（缩进 ≤ 2 空格）；函数内部的局部变量不算，避免误报。
 * 3) app.js 必须能被解析（等价一次语法检查）。
 * 4) app.css 花括号配平（**只扫 app.css**：花括号只在 CSS 里有语义，js 模块不参与，故无需覆盖新模块）。
 *    <form id> 守卫只扫 index.html（表单标签只写在 HTML 里）；getElementById / 表单接线已扫全量 js。
 * 5) getElementById 引用的 id 是否出现在 index.html（多数是运行时生成，仅提示）。
 *
 * 退出码：0 = 通过；1 = 有硬失败（重名 / 语法 / 配平）。
 */
import { readFileSync, readdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
/* task-91：app.js 拆成扁平 ESM 后，守卫必须扫**全部** .js（否则新模块是假绿） */
const jsFiles = readdirSync(here).filter((f) => f.endsWith('.js')).sort();
const sources = new Map(jsFiles.map((f) => [f, readFileSync(join(here, f), 'utf8')]));
const app = sources.get('app.js') || '';
const allJs = jsFiles.map((f) => sources.get(f)).join('\n');
const css = readFileSync(join(here, 'app.css'), 'utf8');
const html = readFileSync(join(here, 'index.html'), 'utf8');

let failed = 0;
const fail = (m) => { console.error('✗ ' + m); failed++; };
const ok = (m) => console.log('✓ ' + m);

/* ---- 1) 顶层声明重名 ---- */
const funcs = new Map();
const vars = new Map();
const perFile = new Map(jsFiles.map((f) => [f, { fns: 0, vars: 0 }]));
const exportedVarNames = new Set();   /* 出现在 export 行的顶层变量名 */
jsFiles.forEach((file) => {
  sources.get(file).split('\n').forEach((line, idx) => {
    /* task-100：必须允许 export / export default 前缀 —— 否则扁平 ESM 里 export function 全都不被计数、
       也不参与查重（缺陷实测：计数 305 → 290，往 pm-dag.js 注入 function esc(){} 仍 exit 0）。 */
    /* 函数声明：一条正则同时认「普通」与「export / export default」两形态。
       普通分支刻意写在前面，这样 scripts/verify_flat_esm_l2.py 的结构检查能发现它、并要求正则里含 export。
       代价：普通分支不认 async（本仓库顶层没有 async 声明；export 分支认）。 */
    let m = /^\s{0,2}function\s+([A-Za-z_$][\w$]*)\s*\(|^\s{0,2}export\s+(?:default\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(/.exec(line);
    if (m) {
      const fname = m[1] || m[2];
      const l = funcs.get(fname) || []; l.push(file + ':' + (idx + 1)); funcs.set(fname, l);
      perFile.get(file).fns++;
    }
    /* 变量：一行可能有多个声明符（export var A = 1, B = 2; 旧正则只看得到 A）——按逗号切开逐个取；
       初始值里带逗号的（f(a, b)）切出来的碎片不以 "名字 =" 开头，会被自然忽略。 */
    const varDecl = /^\s{0,2}((?:export\s+(?:default\s+)?)?)(?:var|let|const)\s+(.+)$/.exec(line);
    if (varDecl) {
      const isExportLine = varDecl[1].indexOf('export') >= 0;
      varDecl[2].split(',').forEach((part) => {
        const nm = /^\s*([A-Za-z_$][\w$]*)\s*=/.exec(part);
        if (!nm) return;
        const l = vars.get(nm[1]) || []; l.push(file + ':' + (idx + 1)); vars.set(nm[1], l);
        perFile.get(file).vars++;
        if (isExportLine) exportedVarNames.add(nm[1]);
      });
    }
  });
});
ok('扫描 ' + jsFiles.length + ' 个 js：' + jsFiles.join(', '));
const dupFuncs = [...funcs].filter(([, l]) => l.length > 1);
if (dupFuncs.length) {
  dupFuncs.forEach(([n, l]) => fail('顶层函数重名：' + n + '（' + l.join(', ') + '）—— 后声明会静默覆盖先声明'));
} else {
  ok('顶层 function 声明无重名（' + funcs.size + ' 个）');
ok('每文件顶层声明：' + jsFiles.map((f) => f + ' 函数=' + perFile.get(f).fns + ' 变量=' + perFile.get(f).vars).join('；'));
}
const dupVars = [...vars].filter(([, l]) => l.length > 1);
/* task-100：**已经 export 的**常量重名是硬失败（模块导出面撞名/同模块重复声明都会踩），
   历史策略「非 export 顶层 var 重名只告警」保持不变（IIFE 里刻意复用是允许的）。 */
const hardDupVars = dupVars.filter(([n]) => exportedVarNames.has(n));
const softDupVars = dupVars.filter(([n]) => !exportedVarNames.has(n));
if (hardDupVars.length) {
  hardDupVars.forEach(([n, l]) => fail('顶层 export 变量重名：' + n + '（' + l.join(', ') + '）—— 模块导出面撞名，必须改名'));
}
if (softDupVars.length) {
  softDupVars.forEach(([n, l]) => console.warn('⚠ 顶层 var 重名（非 export，仅告警）：' + n + '（' + l.join(', ') + '）'));
}
if (!dupVars.length) {
  ok('顶层 var 声明无重名（' + vars.size + ' 个，其中 export ' + exportedVarNames.size + ' 个）');
} else if (!hardDupVars.length) {
  ok('顶层 var 无 export 撞名（' + vars.size + ' 个；' + softDupVars.length + ' 个非 export 同名仅告警）');
}

/* ---- 2) 语法（每个 js 单独 node --check；ESM 里 import 不能塞进 new Function） ---- */
try {
  const { spawnSync } = await import('node:child_process');
  let bad = 0;
  jsFiles.forEach((f) => {
    const r = spawnSync(process.execPath, ['--check', join(here, f)], { encoding: 'utf8' });
    if (r.status !== 0) { bad++; fail(f + ' 语法错误：' + String(r.stderr || '').split('\n')[0]); }
  });
  if (!bad) ok(jsFiles.length + ' 个 js 全部通过 node --check');
} catch (e) {
  fail('语法检查自身出错：' + e.message);
}

/* ---- 3) CSS 花括号 ---- */
const open = (css.match(/{/g) || []).length;
const close = (css.match(/}/g) || []).length;
if (open === close) ok('app.css 花括号配平（' + open + ' 对）');
else fail('app.css 花括号不配平：' + open + ' vs ' + close);

/* ---- 4) 每个 <form id> 必须有 submit 接线（硬失败） ----
 * 2026-10-12 事故：#task-form（「＋ 新建任务」）从未接线，method="dialog" 只关窗口、一个请求都不发，
 * 而 selfcheck 与若干 DOM-only harness 当时全绿 —— 所以这里做机械守卫。 */
const formIds = [...html.matchAll(/<form\b[^>]*\bid="([^"]+)"/g)].map((m) => m[1]);
const allSources = [...sources.values()].join('\n');
const wiredForms = formIds.filter((id) => {
  const getById = new RegExp("getElementById\\('" + id + "'\\)[\\s\\S]{0,300}?addEventListener\\(\\s*'submit'");
  const qs = new RegExp("querySelector(?:All)?\\(\\s*'#" + id + "'\\)[\\s\\S]{0,300}?addEventListener\\(\\s*'submit'");
  return getById.test(allSources) || qs.test(allSources);
});
const deadForms = formIds.filter((id) => wiredForms.indexOf(id) < 0);
if (deadForms.length) {
  deadForms.forEach((id) => fail('#<form id="' + id + '"> 没有 submit 监听 —— 对话框点了不会有任何请求'));
} else {
  ok('index.html 的 ' + formIds.length + ' 个 <form id> 都有 submit 接线（' + formIds.join(', ') + '）');
}

/* ---- 5) getElementById 引用（仅提示） ---- */
const ids = new Set([...html.matchAll(/id="([^"]+)"/g)].map((m) => m[1]));
const used = new Set([...allJs.matchAll(/getElementById\('([^']+)'\)/g)].map((m) => m[1]));
const missing = [...used].filter((id) => !ids.has(id));
console.log('· getElementById 引用 ' + used.size + ' 个 id；index.html 里没有的 ' + missing.length +
  ' 个（多为运行时生成，仅供参考）：' + missing.slice(0, 12).join(', '));

process.exit(failed ? 1 : 0);
