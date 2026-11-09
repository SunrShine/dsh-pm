/* ===================== pm-board-model.js =====================
 * 零构建扁平 ESM：看板的「合并列 → 子状态 chip」模型（task-96 阶段 2 整组搬出）。
 * 依赖：仅 ./pm-format.js（更低层）；不含 DOM/state。
 */
import { esc } from './pm-format.js';
import { t, format } from './pm-i18n.js';   /* task-C5S1V：模块内文案的唯一出口（本文件 CJK == 0） */

  /* 子状态 chip：合并列里必须能区分真实 status（不猜，用 task.status） */
export var SUB_STATUS_CHIPS = {
    INBOX: 'board.statusUnscheduled', TODO: 'board.statusUnscheduled', NEXT: 'board.statusScheduled',
    WAITING: 'board.statusWaiting', BLOCKED: 'board.statusBlocked',
    DONE: 'board.statusDone', CANCELLED: 'board.statusCancelled'
  };
  /* 只有「合并了多个 status」的列才加 chip；doing / review 是单状态列，加了是冗余 */
export var MERGED_GROUP_STATUSES = { todo: ['INBOX', 'TODO', 'NEXT'], blocked: ['WAITING', 'BLOCKED'], closed: ['DONE', 'CANCELLED'] };

/* task-C5S1V：**使用点求值** —— 标签用 t() 现取（表里只放键名，切语言即时生效） */
export function subStatusLabel(status) {
    var key = SUB_STATUS_CHIPS[String(status || '').toUpperCase()];
    return key ? t(key) : '';
  }

export function subStatusChip(status, groupKey) {
    if (!MERGED_GROUP_STATUSES[groupKey]) return '';
    var label = subStatusLabel(status);
    if (!label) return '';
    return '<span class="chip" title="' + esc(format(t('board.realStatusTitle'), { status: String(status) })) + '">' + esc(label) + '</span>';
  }
