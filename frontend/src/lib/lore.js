import { estTk } from './format'

export const clone = (o) => JSON.parse(JSON.stringify(o))

// [酒馆的 position 数值, 分组键, 显示名]；顺序就是页面上分组的顺序
export const POS = [
  [0, 'before', '角色定义之前'],
  [1, 'after', '角色定义之后'],
  [5, 'exTop', '示例对话之前'],
  [6, 'exBot', '示例对话之后'],
  [2, 'anTop', '作者注释之前'],
  [3, 'anBot', '作者注释之后'],
  [4, 'd', '@D 按深度插入'],
  [7, 'outlet', 'Outlet'],
]
export const ROLES = ['系统', '用户', 'AI']
export const SCOPES = [['all', '改写原文'], ['display', '仅显示'], ['prompt', '仅发送']]
export const PLACEMENTS = [[1, '用户输入'], [2, 'AI 输出'], [5, '世界书'], [6, '推理']]
const PLACE_NAME = { 1: '用户输入', 2: 'AI 输出', 3: '快捷命令', 5: '世界书', 6: '推理' }

let seq = 0
const nextUid = () => ++seq

const numOr = (v, d) => {
  const n = Number(v)
  return Number.isFinite(n) ? n : d
}

// ---------------------------------------------------------------- 世界书
function posOf(e) {
  const p = e.extensions?.position
  if (Number.isInteger(p)) return p
  return e.position === 'before_char' ? 0 : 1
}

export function loreView(e) {
  const x = e.extensions || {}
  const content = typeof e.content === 'string' ? e.content : ''
  return {
    n: e.comment || e.name || '',
    k: (Array.isArray(e.keys) ? e.keys : []).join(', '),
    c: !!e.constant,
    on: e.enabled !== false && !e.disable,
    pos: posOf(e),
    depth: numOr(x.depth, 4),
    role: Number.isInteger(x.role) ? x.role : 0,
    order: numOr(e.insertion_order, 100),
    noIn: !!x.exclude_recursion,
    noOut: !!x.prevent_recursion,
    t: content,
    tk: estTk(content),
  }
}

export function applyLore(entry, v) {
  const e = clone(entry)
  e.comment = v.n
  e.keys = String(v.k).split(/[,，]/).map((s) => s.trim()).filter(Boolean)
  e.constant = !!v.c
  e.enabled = !!v.on
  if ('disable' in e) e.disable = !v.on
  e.content = v.t
  e.insertion_order = numOr(v.order, 0)
  e.position = Number(v.pos) === 0 ? 'before_char' : 'after_char'
  e.extensions = {
    ...(e.extensions || {}),
    position: Number(v.pos),
    depth: Math.max(0, Math.trunc(numOr(v.depth, 0))),
    role: Number(v.role),
    exclude_recursion: !!v.noIn,
    prevent_recursion: !!v.noOut,
  }
  return e
}

export function newLoreEntry(existing) {
  const ids = existing.map((e) => Number(e.id)).filter(Number.isFinite)
  return {
    id: ids.length ? Math.max(...ids) + 1 : 0,
    keys: [], secondary_keys: [], comment: '', content: '', constant: false, selective: true,
    insertion_order: 100, enabled: true, position: 'after_char',
    extensions: { position: 1, depth: 4, role: 0, exclude_recursion: false, prevent_recursion: false },
  }
}

// ---------------------------------------------------------------- 正则
export const scopeOf = (r) => (r.markdownOnly ? 'display' : r.promptOnly ? 'prompt' : 'all')

export function regexView(r) {
  return {
    n: r.scriptName || '',
    find: r.findRegex || '',
    repl: r.replaceString || '',
    on: !r.disabled,
    scope: scopeOf(r),
    place: Array.isArray(r.placement) ? r.placement.slice() : [],
  }
}

export function regexPlaceText(place) {
  return place.map((p) => PLACE_NAME[p] || String(p)).join(' · ') || '未指定位置'
}

export function applyRegex(entry, v) {
  const r = clone(entry)
  r.scriptName = v.n
  r.findRegex = v.find
  r.replaceString = v.repl
  r.disabled = !v.on
  r.markdownOnly = v.scope === 'display'
  r.promptOnly = v.scope === 'prompt'
  r.placement = v.place.slice().sort((a, b) => a - b)
  return r
}

export function newRegex() {
  return {
    id: crypto.randomUUID(), scriptName: '', findRegex: '', replaceString: '', trimStrings: [],
    placement: [2], disabled: false, markdownOnly: false, promptOnly: false, runOnEdit: true,
    substituteRegex: 0, minDepth: null, maxDepth: null,
  }
}

export const regexKey = (ext) => (Array.isArray(ext?.regex_scripts) ? 'regex_scripts' : Array.isArray(ext?.regexScripts) ? 'regexScripts' : 'regex_scripts')

export function runRegex(list, text) {
  let out = text
  for (const r of list) {
    if (r.disabled || !r.findRegex) continue
    const m = /^\/([\s\S]*)\/([a-z]*)$/.exec(r.findRegex)
    try {
      const re = m ? new RegExp(m[1], m[2]) : new RegExp(r.findRegex, 'g')
      out = out.replace(re, String(r.replaceString || '').replace(/\{\{match\}\}/gi, '$&'))
    } catch {
      return null
    }
  }
  return out
}

// ---------------------------------------------------------------- 条目行
// 行 = 一条已存盘的原始条目（src）+ 视图（v）+ 未存盘的草稿（draft）。草稿跟着行对象走，
// 排序、增删后下标会变，所以不能用下标当键。
export function buildRows(entries, toView) {
  return entries.map((src) => ({ uid: nextUid(), src, v: toView(src), draft: null, open: false, isNew: false, armed: false }))
}

export function newRow(src, toView) {
  return { uid: nextUid(), src: null, v: toView(src), draft: toView(src), open: true, isNew: true, armed: false, blank: src }
}

// 保存成功后，把后端返回的条目按提交时的顺序对回各行；仍未保存的新行保持原样
export function syncRows(rows, committed, entries, toView) {
  committed.forEach((row, j) => {
    if (!entries[j]) return
    row.src = entries[j]
    row.v = toView(entries[j])
    if (row.isNew) {
      row.isNew = false
      row.draft = null
    }
  })
}
