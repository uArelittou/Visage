export class ApiError extends Error {
  constructor(status, code, message, detail = {}) {
    super(message)
    this.status = status
    this.code = code
    this.detail = detail
  }
}

async function request(method, url, { body, raw, signal } = {}) {
  const init = { method, signal, headers: {} }
  if (raw !== undefined) {
    init.body = raw
  } else if (body !== undefined) {
    init.body = JSON.stringify(body)
    init.headers['Content-Type'] = 'application/json'
  }
  let res
  try {
    res = await fetch(url, init)
  } catch (e) {
    if (e.name === 'AbortError') throw e
    throw new ApiError(0, 'network', '连不上后端，请确认千面录还在运行')
  }
  const text = await res.text()
  let data = null
  if (text) {
    try { data = JSON.parse(text) } catch { data = null }
  }
  if (!res.ok) {
    const d = data && typeof data.detail === 'object' && data.detail ? data.detail : {}
    throw new ApiError(res.status, d.code || 'error', d.message || `请求失败（${res.status}）`, d)
  }
  return data
}

const qs = (params) => {
  const u = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== '') u.set(k, String(v))
  const s = u.toString()
  return s ? `?${s}` : ''
}

export const api = {
  library: () => request('GET', '/api/library'),
  scan: () => request('POST', '/api/library/scan'),
  clearLibrary: () => request('POST', '/api/library/clear'),
  sources: () => request('GET', '/api/sources'),
  addSource: (path) => request('POST', '/api/sources', { body: { path } }),
  removeSource: (path) => request('DELETE', `/api/sources${qs({ path })}`),
  categories: () => request('GET', '/api/categories'),
  createCollection: (name) => request('POST', '/api/collections', { body: { name } }),
  renameCollection: (id, name) => request('PATCH', `/api/collections/${id}`, { body: { name } }),
  deleteCollection: (id) => request('DELETE', `/api/collections/${id}`),
  setFavorite: (id, value) => request('PUT', `/api/cards/${id}/favorite`, { body: { value } }),
  setCardCollections: (id, ids) => request('PUT', `/api/cards/${id}/collections`, { body: { ids } }),
  cards: (params) => request('GET', `/api/cards${qs(params)}`),
  card: (id) => request('GET', `/api/cards/${id}`),
  saveCard: (id, fields, expected) => request('PUT', `/api/cards/${id}`, {
    body: { fields, expected_mtime_ns: expected.mtime, expected_hash: expected.hash },
  }),
  color: (path) => request('GET', `/api/color${qs({ path })}`),
  rating: (id) => request('GET', `/api/cards/${id}/rating`),
  startRating: (id) => request('POST', `/api/cards/${id}/rating/ai`),
  ratingJob: (id) => request('GET', `/api/cards/${id}/rating/ai`),
  setUserTotal: (id, total) => request('PUT', `/api/cards/${id}/rating/user`, { body: { total } }),
  clearUserTotal: (id) => request('DELETE', `/api/cards/${id}/rating/user`),
  ratingSettings: () => request('GET', '/api/settings/rating'),
  saveRatingSettings: (body) => request('PUT', '/api/settings/rating', { body }),
  changes: (since, wait, signal) => request('GET', `/api/changes${qs({ since, wait })}`, { signal }),
}

export const hasCover = (item) => !!item && item.ext !== '.json' && !item.is_broken

export const thumbUrl = (item) => `/api/thumb${qs({ path: item.path })}`
