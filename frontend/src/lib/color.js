import { api, hasCover } from './api'

function rgbToHsl(r, g, b) {
  r /= 255; g /= 255; b /= 255
  const max = Math.max(r, g, b), min = Math.min(r, g, b), l = (max + min) / 2
  if (max === min) return [0, 0, l]
  const d = max - min
  const s = l > 0.5 ? d / (2 - max - min) : d / (max + min)
  const h = max === r ? (g - b) / d + (g < b ? 6 : 0) : max === g ? (b - r) / d + 2 : (r - g) / d + 4
  return [h * 60, s, l]
}

const hsl = (h, s, l) => `hsl(${h.toFixed(0)} ${(s * 100).toFixed(0)}% ${(l * 100).toFixed(0)}%)`

// 后端只给一个主色，界面要一亮一暗两个：亮的用在光和下划线，暗的用在顶栏底色和背景晕
export function themePair(hex) {
  const [h, s] = rgbToHsl(parseInt(hex.slice(1, 3), 16), parseInt(hex.slice(3, 5), 16), parseInt(hex.slice(5, 7), 16))
  return [hsl(h, Math.min(Math.max(s, 0.3), 0.65), 0.66), hsl(h, Math.min(Math.max(s * 0.8, 0.28), 0.55), 0.21)]
}

const cache = new Map()

export function coverTheme(item) {
  if (!hasCover(item)) return Promise.resolve(null)
  const key = `${item.path}|${item.hash}`
  if (!cache.has(key)) {
    cache.set(
      key,
      api.color(item.path).then((r) => (r.color ? themePair(r.color) : null), () => {
        cache.delete(key)
        return null
      }),
    )
  }
  return cache.get(key)
}

export function setTheme(pair) {
  const root = document.documentElement
  if (pair) {
    root.style.setProperty('--theme', pair[0])
    root.style.setProperty('--theme-deep', pair[1])
  } else {
    root.style.removeProperty('--theme')
    root.style.removeProperty('--theme-deep')
  }
}
