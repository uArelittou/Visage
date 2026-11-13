import { nextTick } from 'vue'
import { fail, saveFields, store, toast } from '../store'
import {
  applyLore, applyRegex, buildRows, clone, loreView, newLoreEntry, newRegex, newRow, regexKey, regexView, syncRows,
} from './lore'

const KINDS = {
  wb: { view: loreView, apply: applyLore, fresh: (rows) => newLoreEntry(rows.map((r) => r.src || r.blank).filter(Boolean)) },
  rx: { view: regexView, apply: applyRegex, fresh: () => newRegex() },
}

const dirtyCopy = (v) => ({ ...v, place: v.place ? v.place.slice() : undefined })

export function field(row) {
  return row.draft || row.v
}

export function setField(row, key, value) {
  if (!row.draft) row.draft = dirtyCopy(row.v)
  row.draft[key] = value
}

export function togglePlace(row, p, on) {
  const cur = new Set(field(row).place)
  if (on) cur.add(p)
  else cur.delete(p)
  setField(row, 'place', [...cur])
}

export function rowTap(e, row) {
  if (e.target.closest('.lb,.bin')) return
  row.open = !row.open
}

export function arm(e, row, kind) {
  e.stopPropagation()
  if (!row.armed) {
    row.armed = true
    clearTimeout(row.timer)
    row.timer = setTimeout(() => { row.armed = false }, 3000)
    return
  }
  clearTimeout(row.timer)
  row.armed = false
  removeRow(kind, row)
}

function payload(kind, target, drop) {
  const rows = store.rows[kind]
  const committed = rows.filter((r) => (!r.isNew || r === target) && !(drop && r === target))
  const entries = committed.map((r) => (r === target ? KINDS[kind].apply(r.src || r.blank, r.draft || r.v) : r.src))
  const card = store.detail.card
  if (kind === 'wb') {
    const book = clone(card.character_book || {})
    book.entries = entries
    return { committed, entries, fields: { character_book: book } }
  }
  const ext = clone(card.extensions || {})
  ext[regexKey(ext)] = entries
  return { committed, entries, fields: { extensions: ext } }
}

async function commit(kind, target, drop) {
  const { committed, fields } = payload(kind, target, drop)
  const ok = await saveFields(fields, (next) => {
    const list = kind === 'wb' ? next.card.character_book?.entries : next.card.extensions?.[regexKey(next.card.extensions)]
    if (drop) store.rows[kind] = store.rows[kind].filter((r) => r !== target)
    else target.draft = null
    syncRows(store.rows[kind], committed, list || [], KINDS[kind].view)
    toast(drop ? '已删除' : '已保存到卡文件')
  })
  return ok
}

export async function saveRow(kind, row) {
  if (row.saving) return
  row.saving = true
  try {
    await commit(kind, row, false)
  } finally {
    row.saving = false
  }
}

export async function removeRow(kind, row) {
  if (row.isNew) {
    store.rows[kind] = store.rows[kind].filter((r) => r !== row)
    return
  }
  try {
    await commit(kind, row, true)
  } catch (e) {
    fail(e)
  }
}

export function cancelRow(kind, row) {
  if (row.isNew) store.rows[kind] = store.rows[kind].filter((r) => r !== row)
  else row.draft = null
}

export async function addRow(kind) {
  const spec = KINDS[kind]
  const row = newRow(spec.fresh(store.rows[kind]), spec.view)
  store.rows[kind].push(row)
  await nextTick()
  const li = document.querySelector(`#pane li[data-uid="${row.uid}"]`)
  if (li) {
    li.scrollIntoView({ block: 'center', behavior: 'smooth' })
    li.querySelector('input')?.focus({ preventScroll: true })
  }
}

export { buildRows }
