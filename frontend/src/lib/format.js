export const kfmt = (n) => (n >= 1000 ? (n / 1000).toFixed(1).replace(/\.0$/, '') + 'K' : String(n))

// 估算：中文一字约一个 token，其余约 3.5 个字符一个。不引入分词器，数字只作大小参考。
export function estTk(s) {
  if (!s) return 0
  const z = (s.match(/[\u3400-\u9fff]/g) || []).length
  return Math.ceil(z + (s.length - z) / 3.5)
}

const ROMAN = ['I', 'II', 'III', 'IV', 'V', 'VI', 'VII', 'VIII', 'IX', 'X', 'XI', 'XII', 'XIII', 'XIV', 'XV', 'XVI', 'XVII', 'XVIII', 'XIX', 'XX']

export function latinLabel(name, index) {
  if (/^[\x20-\x7e]+$/.test(name)) return name.toUpperCase()
  return ROMAN[index] || String(index + 1)
}

// 用户分类的英文副标：按创建顺序用罗马数字
export const roman = (index) => ROMAN[index] || String(index + 1)

// <style>/<script> 和 HTML 注释连同内容一起去掉：creator_notes 常以整段 CSS 开头，只去标签会把 CSS 当简介显示
export const stripTags = (s) => String(s || '')
  .replace(/<(style|script)\b[\s\S]*?(<\/\1\s*>|$)/gi, ' ')
  .replace(/<!--[\s\S]*?(-->|$)/g, ' ')
  .replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim()

// 后端错误形如 "CardParseError: 未找到角色卡数据"，给人看时去掉英文异常名
export const errText = (s) => String(s || '').replace(/^[A-Za-z_][\w.]*(Error|Exception):\s*/, '')

export function clip(s, n) {
  const chars = [...s]
  return chars.length > n ? chars.slice(0, n).join('') + '…' : s
}
