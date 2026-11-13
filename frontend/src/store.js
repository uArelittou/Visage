import { reactive } from 'vue'
import { api, ApiError } from './lib/api'
import { roman } from './lib/format'
import { hasNative, pickFiles, pickFolder } from './lib/native'
import { buildRows, loreView, regexView, syncRows, regexKey } from './lib/lore'

export const PAGE = 60

export const store = reactive({
  sourcesVersion: 0, // 来源列表变了就加一，设置页据此刷新
  boot: 'loading', // loading | picker | ready
  lib: null,
  pickerError: '',
  cats: [],
  catIdx: 0,
  items: [],
  total: 0,
  page: 1,
  view: 'shelf', // shelf | search | settings
  cur: null,
  curIndex: 0,
  detail: null,
  rating: null,
  ratingJob: null,
  ratingError: '',
  rows: { wb: [], rx: [] },
  message: '',
  messageOn: false,
  gate: false,
  conflict: null,
})

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

let toastTimer = 0
export function toast(msg) {
  store.message = msg
  store.messageOn = true
  clearTimeout(toastTimer)
  toastTimer = setTimeout(() => { store.messageOn = false }, 3200)
}

export function fail(e) {
  if (e instanceof ApiError && e.code === 'no_library') {
    store.boot = 'picker'
    return
  }
  toast(e.message || '出错了')
}

// ---------------------------------------------------------------- 卡库与分类
export async function bootstrap() {
  try {
    let lib = await api.library()
    while (lib.opening) {
      await sleep(600)
      lib = await api.library()
    }
    store.lib = lib
    // 没有来源也直接进首页，空卡库自己会提示去「收录」，不拦着先选文件夹
    if (lib.open) await enterLibrary()
    else {
      store.pickerError = lib.error || ''
      store.boot = 'picker'
    }
  } catch (e) {
    store.pickerError = e.message
    store.boot = 'picker'
  }
}

async function enterLibrary() {
  store.catIdx = 0
  store.view = 'shelf'
  await loadCats()
  await loadItems()
  store.boot = 'ready'
  watchChanges()
}

// ---------------------------------------------------------------- 来源（只在设置页管理，不是首页分类）
const REASONS = {
  already_in_library: '已在卡库里',
  path_not_found: '路径不存在',
  bad_ext: '只能收录文件夹，或 PNG、WebP、JSON 卡',
}

// 把文件夹/单卡的原路径加入来源，原地索引，不复制文件。逐个添加并汇总成一条提示。
export async function addSources(paths) {
  const list = [...new Set(paths.map((p) => p.trim()).filter(Boolean))]
  if (!list.length) return false
  let ok = 0
  let cards = 0
  const dup = []
  const bad = []
  let merged = 0
  for (const path of list) {
    try {
      const r = await api.addSource(path)
      ok++
      cards = r.card_count
      merged += r.merged.length
    } catch (e) {
      if (e instanceof ApiError && e.code === 'already_in_library') dup.push(path)
      else bad.push(`${REASONS[e.code] || e.message}`)
    }
  }
  if (ok) {
    store.sourcesVersion++
    store.lib = await api.library().catch(() => store.lib)
    if (store.boot === 'ready') {
      await loadCats()
      await loadItems()
    } else {
      store.pickerError = ''
      closeDetailData()
      await enterLibrary()
    }
  }
  const parts = []
  if (ok) parts.push(`已加入 ${ok} 个来源，共 ${cards} 张${merged ? `（并入 ${merged} 个子来源）` : ''}`)
  if (dup.length) parts.push(dup.length === 1 ? '已在卡库里' : `${dup.length} 项已在卡库里`)
  if (bad.length) parts.push(bad[0])
  toast(parts.join('；'))
  return ok > 0
}

export async function pickFolderAndAdd() {
  const p = await pickFolder()
  return p ? addSources([p]) : false
}

export async function pickFilesAndAdd() {
  const ps = await pickFiles()
  return ps.length ? addSources(ps) : false
}

// app.py 在 pywebview 里拿到拖入文件的完整路径后调用。拿不到路径时不去复制文件，提示改用按钮。
window.__qmlDropped = (paths, count) => {
  if (paths.length) addSources(paths)
  else if (count) toast('拿不到拖入文件的路径，请改用「选择文件夹」或「选择卡片」按钮')
}
export { hasNative }

export async function loadCats() {
  const r = await api.categories()
  let user = 0
  const EN = { all: 'ALL', favorites: 'FAVORITES', unsorted: 'UNSORTED' }
  store.cats = r.items.map((c) => ({
    path: c.key, id: c.id, kind: c.kind, name: c.name, total: c.count,
    en: c.kind === 'user' ? roman(user++) : EN[c.kind],
  }))
  if (store.catIdx >= store.cats.length) store.catIdx = 0
}

const catKey = () => {
  const c = store.cats[store.catIdx]
  return c && c.path !== 'all' ? c.path : undefined
}

let loadSeq = 0
export async function loadItems({ more = false } = {}) {
  const seq = ++loadSeq
  const page = more ? store.page + 1 : 1
  const r = await api.cards({ category: catKey(), page, page_size: PAGE })
  if (seq !== loadSeq) return false
  store.items = more ? [...store.items, ...r.items] : r.items
  store.total = r.total
  store.page = page
  return true
}

async function reloadItemsInPlace() {
  const seq = ++loadSeq
  const pages = Math.max(1, store.page)
  let items = []
  let total = 0
  for (let p = 1; p <= pages; p++) {
    const r = await api.cards({ category: catKey(), page: p, page_size: PAGE })
    items = items.concat(r.items)
    total = r.total
    if (items.length >= total) break
  }
  if (seq !== loadSeq) return
  store.items = items
  store.total = total
}

let refreshTimer = 0
export function scheduleRefresh() {
  clearTimeout(refreshTimer)
  refreshTimer = setTimeout(async () => {
    try {
      await loadCats()
      await reloadItemsInPlace()
    } catch (e) {
      if (e instanceof ApiError && e.code === 'no_library') store.boot = 'picker'
    }
  }, 400)
}

let watching = false
async function watchChanges() {
  if (watching) return
  watching = true
  let since = 0
  try { since = (await api.changes(0, 0)).version } catch { /* 下面的循环会重试 */ }
  for (;;) {
    try {
      const r = await api.changes(since, 20)
      since = r.version
      if (r.reset || r.changes.length) scheduleRefresh()
      for (const c of r.changes) {
        if (c.kind === 'rating' && store.cur && c.card_id === store.cur.id) reloadRating().catch(() => {})
      }
    } catch {
      await sleep(3000)
    }
  }
}

// ---------------------------------------------------------------- 详情
const entriesOf = (kind) => {
  const card = store.detail?.card
  if (!card) return []
  if (kind === 'wb') return card.character_book?.entries || []
  return card.extensions?.[regexKey(card.extensions)] || []
}
const VIEW = { wb: loreView, rx: regexView }

function rebuildRows() {
  store.rows = { wb: buildRows(entriesOf('wb'), loreView), rx: buildRows(entriesOf('rx'), regexView) }
}

function resyncRows() {
  for (const kind of ['wb', 'rx']) {
    const entries = entriesOf(kind)
    const committed = store.rows[kind].filter((r) => !r.isNew)
    if (committed.length === entries.length) syncRows(store.rows[kind], committed, entries, VIEW[kind])
    else store.rows[kind] = buildRows(entries, VIEW[kind])
  }
}

export async function loadDetail(item, index) {
  const [detail, rating] = await Promise.all([api.card(item.id), api.rating(item.id).catch(() => null)])
  store.cur = item
  store.curIndex = index
  store.detail = detail
  store.rating = rating
  store.ratingJob = null
  store.ratingError = ''
  rebuildRows()
}

export function closeDetailData() {
  store.cur = null
  store.detail = null
  store.rating = null
  store.rows = { wb: [], rx: [] }
  store.conflict = null
}

export function applyDetail(d) {
  store.detail = d
  if (store.cur) {
    store.cur.id = d.id
    store.cur.path = d.path
    store.cur.ext = d.ext
    store.cur.hash = d.meta.hash
    if (d.card) store.cur.name = d.card.name || store.cur.name
  }
  scheduleRefresh()
}

export async function reloadDetail() {
  applyDetail(await api.card(store.cur.id))
  resyncRows()
}

// onDone 在保存成功后执行（含冲突后选择覆盖的那次），用来把各行草稿对回新数据
export async function saveFields(fields, onDone, expected) {
  const d = store.detail
  const exp = expected || { mtime: d.meta.mtime_ns, hash: d.meta.hash }
  try {
    const next = await api.saveCard(d.id, fields, exp)
    applyDetail(next)
    onDone?.(next)
    return true
  } catch (e) {
    if (e instanceof ApiError && e.code === 'conflict') {
      store.conflict = {
        reason: e.detail.reason,
        current: e.detail.current,
        retry: e.detail.current
          ? () => saveFields(fields, onDone, { mtime: e.detail.current.mtime_ns, hash: e.detail.current.hash })
          : null,
      }
      return false
    }
    fail(e)
    return false
  }
}

// ---------------------------------------------------------------- 评分
export async function reloadRating() {
  store.rating = await api.rating(store.cur.id)
}

export async function setUserTotal(total) {
  try {
    store.rating = total === null ? await api.clearUserTotal(store.cur.id) : await api.setUserTotal(store.cur.id, total)
    scheduleRefresh()
    return true
  } catch (e) {
    fail(e)
    return false
  }
}

export async function startAiRating() {
  const id = store.cur.id
  store.ratingError = ''
  try {
    await api.startRating(id)
  } catch (e) {
    if (e instanceof ApiError && e.code === 'rating_busy') {
      store.ratingJob = { state: 'running' }
    } else {
      store.ratingError = e.message
      store.ratingJob = null
      return
    }
  }
  store.ratingJob = { state: 'running' }
  for (;;) {
    await sleep(1500)
    if (!store.cur || store.cur.id !== id) return
    let job
    try { job = await api.ratingJob(id) } catch { continue }
    if (job.state === 'running') continue
    store.ratingJob = null
    if (job.state === 'failed') store.ratingError = job.error || '评分失败'
    else await reloadRating()
    scheduleRefresh()
    return
  }
}

// ---------------------------------------------------------------- 收藏与用户分类
export async function createCollection(name) {
  try {
    const c = await api.createCollection(name)
    await loadCats()
    return c
  } catch (e) {
    fail(e)
    return null
  }
}

export async function renameCollection(id, name) {
  try {
    await api.renameCollection(id, name)
    await loadCats()
    return true
  } catch (e) {
    fail(e)
    return false
  }
}

export async function deleteCollection(id) {
  const wasHere = store.cats[store.catIdx]?.id === id
  try {
    await api.deleteCollection(id)
    if (wasHere) store.catIdx = 0
    await loadCats()
    if (wasHere) await loadItems()
    else scheduleRefresh()
    return true
  } catch (e) {
    fail(e)
    return false
  }
}

export async function toggleFavorite() {
  const item = store.cur
  try {
    const r = await api.setFavorite(item.id, !item.favorite)
    item.favorite = r.favorite
    scheduleRefresh()
  } catch (e) {
    fail(e)
  }
}

export async function setCollections(ids) {
  const item = store.cur
  try {
    const r = await api.setCardCollections(item.id, ids)
    item.collections = r.collections
    scheduleRefresh()
  } catch (e) {
    fail(e)
  }
}
