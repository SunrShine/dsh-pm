/* ===================== pm-pin-state.js =====================
 * 零构建扁平 ESM：收件箱「置顶 / 取消置顶」的状态判定（task-96 阶段 2）。
 * 纯函数：**不 import app.js**，能力门控由调用方注入（endpointListed / missingEndpointText），
 * 所以这里既能被 harness 直接跑，也不会把 DOM/state 带进纯模块。
 */

  /* 置顶 / 取消置顶（task-50）：状态**只以真实 pinned 字段为准**，不做乐观翻转；
     动作完成后统一重新拉取（cards + inbox），按钮文案随回读结果变化。 */
import { t } from './pm-i18n.js';   /* task-C5S1V：模块内文案的唯一出口（本文件 CJK == 0） */

export function inboxPinState(e, deps) {
    if (!e || !e.id) {
      return { ok: false, why: t('pin.noStableId') };
    }
    if (!Object.prototype.hasOwnProperty.call(e, 'pinned')) {
      return { ok: false, why: t('pin.notWired') };
    }
    var target = (e.pinned === true) ? '/ui-pm/inbox/:id/unpin' : '/ui-pm/inbox/:id/pin';
    var gate = deps || {};
    if (!gate.endpointListed || !gate.endpointListed('POST', target)) {
      return { ok: false, why: (gate.missingEndpointText ? gate.missingEndpointText('POST', target) : t('pin.endpointNotListed')) };
    }
    if (typeof e.revision !== 'number') return { ok: false, why: t('pin.noRevision') };
    return { ok: true, pinned: e.pinned === true, verb: (e.pinned === true ? t('pin.unpin') : t('pin.pin')), endpoint: target };
  }
