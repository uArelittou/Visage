import { ambClear, ambHold } from './ambient'
import { setTheme } from './color'

const BODY = document.body
const REDUCED = matchMedia('(prefers-reduced-motion:reduce)').matches
const VARS = ['--hy', '--ox', '--oy']

let busy = false
let lastY = 0
let enterTimer = 0

export const isBusy = () => busy

// 飞行中的替身：复制一份卡面放在原位，再用 transform 移到目的地
function makeFly(srcTilt, r, keepTilt) {
  const f = document.createElement('div')
  f.className = 'fly'
  f.style.cssText = `left:${r.left}px;top:${r.top}px;width:${r.width}px`
  const copy = srcTilt.cloneNode(true)
  copy.style.visibility = ''
  const card = copy.querySelector('.card')
  card.classList.remove('live')
  // 带上悬浮时的倾斜角，起飞的同时转正，不会“啪”地一下变平
  if (!keepTilt) card.style.cssText = ''
  else requestAnimationFrame(() => requestAnimationFrame(() => { card.style.cssText = '' }))
  f.appendChild(copy)
  document.body.appendChild(f)
  return f
}

function flyTo(f, a, b, ms) {
  const k = b.width / a.width
  return f.animate(
    [{ transform: 'none' }, { transform: `translate(${b.left - a.left}px,${b.top - a.top}px) scale(${k})` }],
    { duration: ms, easing: 'cubic-bezier(.22,.8,.2,1)', fill: 'forwards' },
  ).finished
}

const detailEl = () => document.getElementById('detail')

// cell：卡库里被点的那个 .cell；onShown：详情页显示出来后（量位置之前）要做的布局，如标签线对齐
export async function openFlight(cell, theme, onShown) {
  const DETAIL = detailEl()
  const src = cell && cell.querySelector('.tilt')
  const r0 = src && src.getBoundingClientRect()
  const fly = !REDUCED && r0 && r0.width > 0
  lastY = scrollY
  ambHold()
  setTheme(theme)
  if (!fly) {
    ambClear()
    BODY.classList.add('open')
    scrollTo(0, 0)
    onShown?.()
    return
  }
  busy = true
  // 卡库留在原地（改成固定定位），详情页在它下面铺开，两层叠着做交叉淡化
  BODY.style.setProperty('--hy', -lastY + 'px')
  BODY.style.setProperty('--ox', r0.left + r0.width / 2 + 'px')
  BODY.style.setProperty('--oy', r0.top + r0.height / 2 + lastY + 'px')
  BODY.classList.add('open', 'opening')
  DETAIL.classList.add('enter')
  scrollTo(0, 0)
  onShown?.()
  const dst = DETAIL.querySelector('.hero-in .tilt')
  const r1 = dst.getBoundingClientRect()
  const f = makeFly(src, r0, true)
  dst.style.visibility = 'hidden'
  src.style.visibility = 'hidden'
  f.classList.add('hot')
  setTimeout(() => f.classList.remove('hot'), 160)
  await flyTo(f, r0, r1, 720)
  // 飞行途中布局还可能变（字体晚到、滚动条出现），落地前再量一次，偏了就顺着滑过去，不让真封面突然跳开
  const r2 = dst.getBoundingClientRect()
  if (Math.abs(r2.left - r1.left) > 0.5 || Math.abs(r2.top - r1.top) > 0.5 || Math.abs(r2.width - r1.width) > 0.5) {
    const k1 = r1.width / r0.width
    const k2 = r2.width / r0.width
    await f.animate(
      [{ transform: `translate(${r1.left - r0.left}px,${r1.top - r0.top}px) scale(${k1})` },
        { transform: `translate(${r2.left - r0.left}px,${r2.top - r0.top}px) scale(${k2})` }],
      { duration: 220, easing: 'cubic-bezier(.3,.7,.3,1)', fill: 'forwards' },
    ).finished
  }
  dst.style.visibility = ''
  f.remove()
  src.style.visibility = ''
  BODY.classList.remove('opening')
  VARS.forEach((k) => BODY.style.removeProperty(k))
  ambClear()
  clearTimeout(enterTimer)
  enterTimer = setTimeout(() => DETAIL.classList.remove('enter'), 1600)
  busy = false
}

export async function closeFlight(cell) {
  const DETAIL = detailEl()
  const dst = DETAIL.querySelector('.hero-in .tilt')
  const tgt = cell && cell.querySelector('.tilt')
  setTheme(null)
  if (REDUCED || !dst || !tgt) {
    BODY.classList.remove('open')
    scrollTo(0, lastY)
    return
  }
  busy = true
  scrollTo(0, 0)
  const r1 = dst.getBoundingClientRect()
  BODY.style.setProperty('--hy', -lastY + 'px')
  BODY.classList.add('closing')
  // 卡库淡入动画第一帧是放大 1.05 倍，直接量会量到放大后的位置，封面会落偏。先停掉动画再量
  const home = document.querySelector('.home')
  home.style.animation = 'none'
  const r0 = tgt.getBoundingClientRect()
  BODY.style.setProperty('--ox', r0.left + r0.width / 2 + 'px')
  BODY.style.setProperty('--oy', r0.top + r0.height / 2 + lastY + 'px')
  void home.offsetWidth
  home.style.animation = ''
  const f = makeFly(dst, r1, false)
  dst.style.visibility = 'hidden'
  tgt.style.visibility = 'hidden'
  setTimeout(() => f.classList.add('hot'), 300)
  await flyTo(f, r1, r0, 680)
  BODY.classList.remove('open', 'closing')
  DETAIL.classList.remove('enter')
  VARS.forEach((k) => BODY.style.removeProperty(k))
  scrollTo(0, lastY)
  tgt.style.visibility = ''
  f.remove()
  busy = false
}
