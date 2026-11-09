import test from 'node:test'
import assert from 'node:assert/strict'
import { TASK_STATUS, MEMORY_TYPES, BOARD_COLUMN_TITLES, boardColumnTitle, historyTimeText, bindTranslator } from '../../frontend_impl/pm-format.js'
import { t, setLang } from '../../frontend_impl/pm-i18n.js'

/* B0 注入式翻译器（Lead 选 A）的三态测试 + 负例要**有牙**：
   ① 未 bind ⇒ 逐字回退原中文（行为与改造前一致）
   ② bind stub ⇒ 走键（不碰真键表也能证明"注入生效"）
   ③ bind 真 t + setLang('en') ⇒ 出英文
   负例：把回退值改掉 / 把 getter 拆掉 / 不 bind 却断言英文 —— 都必须红。 */

const ORIG = {
  INBOX: '收件箱', TODO: '待办', NEXT: '下一步', DOING: '执行中', WAITING: '等待',
  BLOCKED: '阻塞', REVIEW: '待验收', DONE: '已完成', CANCELLED: '已取消',
}
const ORIG_MEM = { fact: '事实', decision: '决策', gotcha: '坑' }

test('① 未 bind：四张表逐字回退原中文（行为与改造前一致）', () => {
  for (const [k, v] of Object.entries(ORIG)) assert.equal(TASK_STATUS[k], v, 'TASK_STATUS.' + k)
  for (const [k, v] of Object.entries(ORIG_MEM)) assert.equal(MEMORY_TYPES[k], v, 'MEMORY_TYPES.' + k)
  assert.equal(BOARD_COLUMN_TITLES.todo, '待办：已记录 / 已排期，还没开始做（INBOX / TODO = 未排期，NEXT = 已排期）')
  assert.equal(BOARD_COLUMN_TITLES.closed, '已结束：人验收通过（DONE）或明确放弃（CANCELLED）—— 终态，默认折叠')
  assert.equal(historyTimeText('not-a-time'), '时间未返回')
  /* 回退串里的**全角括号**也在（Lead 提醒③） */
  assert.equal(boardColumnTitle({ key: 'zzz', label: '标签' }), '标签（zzz）')
})

test('② bind stub：确实走键（证明注入生效，且不依赖真键表）', () => {
  const seen = []
  bindTranslator((k) => { seen.push(k); return '[' + k + ']' })
  assert.equal(TASK_STATUS.TODO, '[status.TODO]')
  assert.equal(MEMORY_TYPES.gotcha, '[memtype.gotcha]')
  assert.equal(BOARD_COLUMN_TITLES.doing, '[boardcol.doing]')
  assert.ok(seen.includes('status.TODO') && seen.includes('memtype.gotcha') && seen.includes('boardcol.doing'), 'stub 应被调用到这三个键')
})

test('③ bind 真 t + setLang(en)：出英文（且 zh 不变）', () => {
  bindTranslator(t)
  setLang('zh')
  assert.equal(TASK_STATUS.TODO, '待办')
  assert.equal(BOARD_COLUMN_TITLES.doing, '执行中：正在做（DOING）')
  setLang('en')
  assert.equal(TASK_STATUS.TODO, 'To do')
  assert.equal(TASK_STATUS.CANCELLED, 'Cancelled')
  assert.equal(MEMORY_TYPES.fact, 'Fact')
  assert.equal(BOARD_COLUMN_TITLES.doing, 'Doing: work in progress (DOING)')
  assert.equal(boardColumnTitle({ key: 'zzz', label: 'Label' }), 'Label (zzz)', 'en 下回退串用**半角括号**')
  setLang('zh')   /* 语言是全局态：测试末尾复位，避免影响同进程的其它测试 */
})

test('负例（有牙）：若某个 getter 被拆掉或回退值被改，上面的断言必须红', () => {
  /* 用"故意错的期望"证明断言有牙 —— 期望值来自键表 zh，而 getter 走 tt ⇒ 只要 getter 掉了就会不一致 */
  bindTranslator(t)
  setLang('zh')
  const keyTableTodo = t('status.TODO')
  assert.equal(TASK_STATUS.TODO, keyTableTodo, '若把 TASK_STATUS.TODO 的 getter 拆成常量，语言切换后此断言必红')
  setLang('en')
  assert.notEqual(TASK_STATUS.TODO, keyTableTodo, 'en 下必须与 zh 值不同（否则说明注入没生效）')
  setLang('zh')
})
