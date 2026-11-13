// 鼠标相对卡中心的位置 → 倾斜角 + 边缘光位置。只在有鼠标且没开“减少动态”时启用
const CAN_TILT = matchMedia('(hover:hover) and (pointer:fine)').matches && !matchMedia('(prefers-reduced-motion:reduce)').matches
const MAX = 12

export const vTilt = {
  mounted(el) {
    if (!CAN_TILT) return
    const card = el.querySelector('.card')
    if (!card) return
    let raf = 0
    const set = (k, v) => card.style.setProperty(k, v)
    const enter = () => {
      card.classList.add('live')
      set('--s', 1.045)
      set('--ga', 1)
    }
    const move = (e) => {
      cancelAnimationFrame(raf)
      raf = requestAnimationFrame(() => {
        const r = el.getBoundingClientRect()
        const x = (e.clientX - r.left) / r.width
        const y = (e.clientY - r.top) / r.height
        set('--rx', ((0.5 - y) * 2 * MAX).toFixed(2))
        set('--ry', ((x - 0.5) * 2 * MAX).toFixed(2))
        set('--gx', (x * 100).toFixed(1) + '%')
        set('--gy', (y * 100).toFixed(1) + '%')
      })
    }
    const leave = () => {
      cancelAnimationFrame(raf)
      card.classList.remove('live')
      for (const [k, v] of [['--rx', 0], ['--ry', 0], ['--s', 1], ['--ga', 0], ['--gx', '50%'], ['--gy', '50%']]) set(k, v)
    }
    el.addEventListener('pointerenter', enter)
    el.addEventListener('pointermove', move)
    el.addEventListener('pointerleave', leave)
    el._untilt = () => {
      cancelAnimationFrame(raf)
      el.removeEventListener('pointerenter', enter)
      el.removeEventListener('pointermove', move)
      el.removeEventListener('pointerleave', leave)
    }
  },
  unmounted(el) {
    el._untilt?.()
  },
}
