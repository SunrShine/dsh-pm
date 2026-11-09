/* ===================== pm-anno.js =====================
 * 零构建扁平 ESM：inbox 行内「补充」列表的纯模型 + 渲染（task-96 阶段 2）。
 * 依赖：仅 ./pm-format.js（esc / localTime）；不含 DOM/state。
 * 常量随函数一起搬（NOTE_ANNO_MAX / NOTE_ANNO_LONG 各自独立声明，不搞隐式全局）。
 */
import { esc, localTime } from './pm-format.js';
import { t, format } from './pm-i18n.js';   /* task-C5S1V：模块内文案的唯一出口（本文件 CJK == 0） */

  /* 行内补充列表：数据全部来自 pm inbox list 的 entries[]（不为每行单独打 detail 请求）。
     顺序：所有条目都有可解析时间 → 最新在上；否则按返回顺序取最后 5 条（并在界面写明方向）。 */
export var NOTE_ANNO_MAX = 5;
export var NOTE_ANNO_LONG = 120;

export function entryAnnotations(e) {
    var items = (e && Array.isArray(e.annotations)) ? e.annotations.slice() : [];
    var total = (typeof e.annotationCount === 'number') ? e.annotationCount : items.length;
    var allDated = items.length > 0 && items.every(function (a) { return a && localTime(a.at) !== ''; });
    var direction = 'returned';
    var shown = items;
    var more = 0;
    if (allDated) {
      direction = 'desc';
      shown = items.slice().sort(function (a, b) {
        var ka = localTime(a.at), kb = localTime(b.at);
        return ka < kb ? 1 : (ka > kb ? -1 : 0);
      });
    }
    if (shown.length > NOTE_ANNO_MAX) {
      shown = direction === 'desc' ? shown.slice(0, NOTE_ANNO_MAX) : shown.slice(shown.length - NOTE_ANNO_MAX);
      more = items.length - NOTE_ANNO_MAX;
    }
    var known = (typeof e.annotationCount === 'number') || items.length > 0;
    return { items: shown, total: total, more: more, direction: direction, countKnown: known };
  }

export function annoBlockHtml(a, i, j) {
    var text = String((a && a.text) || '');
    var long = text.length > NOTE_ANNO_LONG || text.indexOf('\n') >= 0;
    var bodyId = 'anno-' + i + '-' + j;
    return '<div class="anno">' +
      '<div class="anno-head">' + esc(format(t('anno.head'), {
        time: (a && a.at ? (localTime(a.at) || t('anno.timeUnknown')) : t('anno.timeUnknown')),
        actor: ((a && a.actor) || t('anno.actorUnknown'))
      })) +
      ((a && a.revision !== undefined && a.revision !== null) ? ' · rev ' + esc(String(a.revision)) : '') + '</div>' +
      '<div class="anno-body' + (long ? ' clamped' : '') + '" id="' + bodyId + '">' + esc(text || t('anno.bodyUnknown')) + '</div>' +
      (long ? '<button type="button" class="anno-toggle" data-anno-toggle="' + bodyId + '"' +
        ' aria-label="' + esc(t('anno.expandAria')) + '">' + esc(t('anno.expand')) + '</button>' : '') +
      '</div>';
  }

export function annoListHtml(e, i) {
    var info = entryAnnotations(e);
    if (!info.items.length) {
      /* 兜底：只有 lastAnnotationText 的旧 payload → 一行预览（截断 + title 全文） */
      var last = (e && e.lastAnnotationText) ? String(e.lastAnnotationText) : '';
      if (!last) return '';
      var preview = last.length > 60 ? last.slice(0, 60) + '…' : last;
      return '<div class="anno-preview" title="' + esc(last) + '"><b>' + esc(t('anno.previewLabel')) + '</b>' + esc(preview) + '</div>';
    }
    var html = '<div class="anno-list"><div class="anno-dir">' + esc(t('anno.dirPrefix')) + ' ' +
      (info.countKnown ? esc(format(t('anno.count'), { n: info.total })) : esc(t('anno.countUnknown'))) +
      (info.direction === 'desc' ? esc(t('anno.dirNewestFirst')) : esc(t('anno.dirReturnOrder'))) + '</div>';
    info.items.forEach(function (a, j) { html += annoBlockHtml(a, i, j); });
    if (info.more > 0) {
      html += '<div class="anno-more">' + esc(format(t('anno.more'), { n: info.more })) + '</div>';
    }
    html += '</div>';
    return html;
  }
