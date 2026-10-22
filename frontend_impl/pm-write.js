/* ===================== pm-write.js =====================
 * 零构建扁平 ESM：统一的写命令出口（task-109 阶段 3 从 app.js 搬出）。
 * 依赖：./pm-state.js（state.idem / busy / credential / conflict / writeError）、
 *       ./pm-api.js（httpJson / api / apiError）—— 都更底层；**不 import app.js**。
 *
 * 渲染怎么来：performWrite 在「开始写 / 成功 / 409 / 失败 / 网络错」时要刷新界面，
 * 但 render() 属于 app.js → 用**注入钩子**（configureWrite({render})），保持不反向依赖。
 * 逐字保留的语义：actor 固定 human、CAS expectedRevision、客户端 idempotencyKey、
 * omitEnvelope（整文件 digest 路由不发这两个字段）、keepEmpty（空字符串是合法值）、
 * 409 → conflict 面板 + afterConflict 重拉、失败**绝不本地先变**（只有成功才写 credential 并删 idem 键）。
 */
import { state } from './pm-state.js';
import { httpJson, api, apiError } from './pm-api.js';
import { t } from './pm-i18n.js';   /* task-C5S1V：模块内文案的唯一出口（批次 A 要求本文件 CJK == 0） */

var writeHooks = { render: function () {} };

/* app.js 启动时注入 render（函数声明，IIFE 内 hoisted） */
export function configureWrite(hooks) {
  writeHooks = Object.assign({}, writeHooks, hooks || {});
}

/* 名字不叫 render：与本仓库 app.js IIFE 里的 render() 同名会踩 selfcheck 的「一名一义」守卫（跨模块同名读起来像覆盖） */
function notifyRender() { if (writeHooks.render) writeHooks.render(); }

export function mintKey() {
    try {
      if (window.crypto && window.crypto.randomUUID) return window.crypto.randomUUID();
    } catch (e) { /* 老环境退回时间戳 + 随机 */ }
    return 'pm-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 10);
  }

  /* 统一的写命令出口：CAS revision + 客户端 idempotencyKey + 409 自动重拉 + §5 凭据。 */
export function performWrite(cfg) {
    var slot = cfg.slot;
    if (!state.idem[slot]) state.idem[slot] = mintKey();
    var key = state.idem[slot];
    /* omitEnvelope：该路由用整文件 digest 做 CAS，不接受 idempotencyKey/expectedRevision（路由是字段白名单，未声明字段会 400） */
    var body = cfg.omitEnvelope ? { actor: 'human' } : { actor: 'human', idempotencyKey: key };
    if (!cfg.omitEnvelope && cfg.revision !== undefined && cfg.revision !== null) body.expectedRevision = cfg.revision;
    Object.keys(cfg.body || {}).forEach(function (k) {
      var v = cfg.body[k];
      /* keepEmpty=true 时保留空字符串（例如「清空简报某段」是合法值） */
      if (v === undefined || v === null || (v === '' && cfg.keepEmpty !== true)) return;
      if (typeof v === 'number' && !isFinite(v)) return;
      if (Array.isArray(v) && v.length === 0) return;
      body[k] = v;
    });
    state.busy = true;
    state.writeError = null;
    state.conflict = null;
    notifyRender();
    return httpJson(api(cfg.path, cfg.query), {
      method: cfg.method || 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(body)
    }).then(function (x) {
      var b = x.body;
      if (x.ok && b.ok === true) {
        delete state.idem[slot];
        state.credential = {
          action: cfg.label || cfg.path, until: cfg.until || null, text: cfg.text || '',
          entityId: b.entityId, revision: b.revision, source: b.source,
          observedAt: b.observedAt, auditEventId: b.auditEventId,
          data: b.data || {}, key: cfg.omitEnvelope ? null : key, at: new Date().toISOString()
        };
        state.busy = false;
        return Promise.resolve(cfg.afterOk ? cfg.afterOk(b) : null).then(function () { notifyRender(); });
      }
      if (x.status === 409) {
        var ce = b.error || {};
        state.credential = null;
        state.conflict = {
          code: ce.code || 'REVISION_CONFLICT', message: ce.message || t('write.revisionConflict'),
          currentRevision: b.currentRevision, expectedRevision: b.expectedRevision,
          currentDigest: b.currentDigest, hint: b.hint,
          diffHint: b.diffHint, at: new Date().toISOString()
        };
        state.busy = false;
        return Promise.resolve(cfg.afterConflict ? cfg.afterConflict() : null).then(function () { notifyRender(); });
      }
      state.writeError = Object.assign(apiError(x), {
        action: cfg.label || cfg.path, id: cfg.ident || '',
        body: b   /* 保留原始 body：STALE_PLAN 这类错误带 baseRevision/currentRevision 等额外字段 */
      });
      state.busy = false;
      notifyRender();
    }).catch(function (err) {
      state.writeError = {
        status: 0, code: 'NETWORK', message: err.message || String(err),
        action: cfg.label || cfg.path, id: cfg.ident || ''
      };
      state.busy = false;
      notifyRender();
    });
  }
