import { hasCover, thumbUrl } from './api'
import { coverTheme, setTheme } from './color'

const BODY = document.body
let layers = []
let flip = 0
let current = null
let timer = 0

export const attachAmbient = (els) => { layers = els }

const keyOf = (item) => `${item.path}|${item.hash}`

// 两层轮换：新封面在一层淡入并重新开始放大，旧的一层留在原地淡出
export function ambOn(item) {
  clearTimeout(timer)
  if (!hasCover(item)) {
    ambOff()
    return
  }
  const key = keyOf(item)
  if (current === key) return
  current = key
  const old = layers[flip]
  flip ^= 1
  const next = layers[flip]
  next.style.backgroundImage = `url('${thumbUrl(item)}')`
  next.classList.remove('kb')
  void next.offsetWidth
  next.classList.add('kb', 'on')
  old.classList.remove('on')
  BODY.classList.add('amb-on')
  coverTheme(item).then((pair) => { if (current === key) setTheme(pair) })
}

export const ambHold = () => clearTimeout(timer)

export function ambClear() {
  layers.forEach((e) => e.classList.remove('on'))
  current = null
  BODY.classList.remove('amb-on')
}

// 稍等再收：鼠标从一张卡移到相邻卡时，背景不会先暗一下再亮
export function ambOff() {
  if (BODY.classList.contains('open')) return
  clearTimeout(timer)
  timer = setTimeout(() => {
    ambClear()
    setTheme(null)
  }, 280)
}
