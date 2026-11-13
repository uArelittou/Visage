const LEGACY_KEYS = ['TavernHelper_scripts', 'tavern_helper_scripts', 'tavernHelper_scripts', 'tavernHelper']
const isObj = (v) => v !== null && typeof v === 'object' && !Array.isArray(v)

const looksLikeScripts = (arr) =>
  arr.length > 0 && arr.every((it) => isObj(it) && ['value', 'content', 'type', 'name'].some((k) => k in it))

// 与后端 backend/card/models.py 的 _find_script_list 保持同一套查找顺序：
// 前端按相同顺序展开，下标才能和详情接口里的 scripts 一一对上
export function findScriptList(ext) {
  const helper = ext.tavern_helper
  if (Array.isArray(helper)) {
    for (const pair of helper) {
      if (Array.isArray(pair) && pair.length === 2 && pair[0] === 'scripts') return Array.isArray(pair[1]) ? pair[1] : null
    }
    if (looksLikeScripts(helper)) return helper
  } else if (isObj(helper)) {
    for (const key of ['scripts', 'script']) if (Array.isArray(helper[key])) return helper[key]
  }
  for (const key of LEGACY_KEYS) if (Array.isArray(ext[key])) return ext[key]
  return null
}

export function scriptHandles(ext) {
  const out = []
  const walk = (list) => {
    for (const item of list.slice()) {
      if (!isObj(item)) continue
      if (item.type === 'folder' && Array.isArray(item.scripts)) {
        walk(item.scripts)
        continue
      }
      out.push({ host: isObj(item.value) ? item.value : item, item, list })
    }
  }
  const top = findScriptList(ext)
  if (top) walk(top)
  return out
}

export function newScript(name, content) {
  return {
    type: 'script', enabled: true, name, id: crypto.randomUUID(), content, info: '',
    button: { enabled: false, buttons: [] }, data: {},
  }
}

// edited: [{name, content, src}]，src 是该脚本在原列表里的下标，新增的为 null；按顺序写回
export function applyScripts(ext, edited) {
  const handles = scriptHandles(ext)
  const keep = new Set()
  for (const s of edited) {
    if (s.src === null) continue
    const h = handles[s.src]
    h.host.name = s.name
    h.host.content = s.content
    keep.add(s.src)
  }
  handles.forEach((h, i) => {
    if (keep.has(i)) return
    h.list.splice(h.list.indexOf(h.item), 1)
  })
  const fresh = edited.filter((s) => s.src === null)
  if (fresh.length) {
    let top = findScriptList(ext)
    if (!top) {
      top = []
      if (isObj(ext.tavern_helper)) ext.tavern_helper.scripts = top
      else ext.tavern_helper = [['scripts', top], ['variables', {}]]
    }
    for (const s of fresh) top.push(newScript(s.name, s.content))
  }
  return ext
}
