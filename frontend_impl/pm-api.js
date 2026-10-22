/* ===================== pm-api.js =====================
 * 零构建扁平 ESM：HTTP 取数与能力门控（task-109 阶段 3 从 app.js 搬出）。
 * 依赖：./pm-format.js（esc）、./pm-state.js（caps 缓存）、./pm-i18n.js（文案表，task-C5S1V 起）—— 都更底层；**不 import app.js**。
 * 行为逐字未改：api() 的 query 组装、httpJson 的 {status, ok, body} 形状、apiError 的 code 兜底、
 * capabilities 只认 /ui-pm/capabilities（undefined=未取 / null=取不到），以及 missingEndpointText 的措辞。
 */
import { esc } from './pm-format.js';
import { state } from './pm-state.js';
import { t, format } from './pm-i18n.js';   /* task-C5S1V：模块内文案的唯一出口（本文件 CJK == 0） */

export function api(path, query) {
    var url = '../' + path;
    if (query) {
      var parts = [];
      Object.keys(query).forEach(function (k) {
        var v = query[k];
        if (v === undefined || v === null || v === '') return;
        parts.push(encodeURIComponent(k) + '=' + encodeURIComponent(String(v)));
      });
      if (parts.length) url += '?' + parts.join('&');
    }
    try { return new URL(url, location.href).toString(); } catch (e) { return '/ui-pm/' + path; }
  }

  /* 一次 HTTP 往返 → {status, ok, body}；空 body 也安全（旧宿主 404 就是空的）。 */
export function httpJson(url, opts) {
    /* #30：请求必须能超时/取消 —— 原来裸 fetch 在宿主假死或网络黑洞时永不 settle，
       调用方按 busy 禁用的按钮就永久不可用。这里给 15s 超时（AbortSignal.timeout），
       超时统一映射成 {status:0, ok:false, error:{code:'HTTP_TIMEOUT'}} 形状，上层据此恢复按钮并给重试入口。 */
    var base = opts || { headers: { accept: 'application/json' }, cache: 'no-store' };
    var o = {};
    Object.keys(base).forEach(function (k) { o[k] = base[k]; });
    try {
      if (!o.signal && typeof AbortSignal !== 'undefined' && AbortSignal.timeout) o.signal = AbortSignal.timeout(15000);
    } catch (e) { /* 老环境退化：不带 signal（行为与改造前一致），但不假装有超时 */ }
    return fetch(url, o).then(function (r) {
      return r.text().then(function (t) {
        var parsed = null;
        try { parsed = t ? JSON.parse(t) : null; } catch (e) { parsed = null; }
        return { status: r.status, ok: r.ok, body: parsed || {} };
      });
    }).catch(function (err) {
      /* #30：超时/中断也有形状，绝不把 pending 留给调用方 */
      var timedOut = err && (err.name === 'TimeoutError' || err.name === 'AbortError');
      return {
        status: 0, ok: false,
        /* 网络错的 code 对齐【既有契约】：pm-write.js 的写路径一直用 'NETWORK'（:90），
           我 U6 曾写成 'NETWORK_ERROR' ⇒ 破坏了 verify_frontend_write_path.py 的期望（0/NETWORK）✗
           ⇒ 按 Lead 口径"改命名而非改判据"。HTTP_TIMEOUT 是本批新增（原代码没有超时处理），保留。 */
        body: { error: { code: timedOut ? 'HTTP_TIMEOUT' : 'NETWORK', message: timedOut ? t('api.timeout') : ((err && err.message) || t('api.networkError')) } }
      };
    });
  }

export function apiError(x, fallback) {
    var e = (x.body && x.body.error) || {};
    return {
      status: x.status,
      code: e.code || (x.status === 404 ? 'NOT_FOUND' : 'ERROR'),
      message: e.message || fallback || ('HTTP ' + x.status)
    };
  }

  /* 领域端点是否可用：以 /ui-pm/capabilities 为准（undefined=还没取到，null=取不到→旧宿主）。 */
export function capsReady() { return !!(state.caps && state.caps.ok); }

export function endpointListed(method, path) {
    if (!capsReady()) return false;
    return state.caps.endpoints.some(function (e) { return e.method === method && e.path === path; });
  }

export function unavailableReason(method, path) {
    if (!capsReady()) return t('api.regionNotReady');
    var hit = state.caps.unavailable.filter(function (u) { return u.method === method && u.path === path; })[0];
    return hit ? hit.reason : '';
  }

export function loadCapabilities() {
    return httpJson(api('capabilities')).then(function (x) {
      if (x.ok && x.body.ok === true && x.body.data) {
        var d = x.body.data;
        state.caps = {
          ok: true, pmVersion: d.pmVersion, config: d.config,
          endpoints: d.endpoints || [], unavailable: d.unavailable || []
        };
      } else {
        state.caps = null;
      }
    }).catch(function () { state.caps = null; });
  }

export function notYet(label, reason) {
    return '<button class="btn small" type="button" disabled aria-disabled="true" title="' +
      esc(reason) + '">' + esc(label) + '</button>';
  }

  /* 端点缺失时的统一说法：只讲「本实例有没有」，不写会过时的版本号 */
export function missingEndpointText(method, path) {
    if (!capsReady()) return format(t('api.noCapsList'), { method: method, path: path });
    var reason = unavailableReason(method, path);
    return format(t('api.notProvided'), { method: method, path: path }) + (reason ? t('api.reasonSep') + reason : '');
  }
