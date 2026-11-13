<script setup>
import { onBeforeUnmount, onMounted } from 'vue'

/* 星图按 0~1 的方框画，形状是示意，不追求天文精度。点：[x, y, 亮度]；线：[点, 点] */
const Z = [
  ['ARIES', [[0, 0, .5], [.45, .35, 1], [.85, .6, .8], [.93, .8, .5]], [[0, 1], [1, 2], [2, 3]]],
  ['TAURUS', [[0, .05, .8], [.1, .55, .6], [.5, .38, .6], [.47, .6, 1], [.6, .46, .5], [.7, .56, .6], [.9, .72, .5], [1, .22, .4]], [[0, 2], [2, 4], [4, 5], [1, 3], [3, 5], [5, 6], [4, 7]]],
  ['GEMINI', [[.08, .04, 1], [.3, .1, 1], [.18, .4, .5], [.45, .42, .6], [.32, .74, .5], [.62, .7, .6], [.4, .96, .7], [.76, .92, .6]], [[0, 1], [0, 2], [2, 4], [4, 6], [1, 3], [3, 5], [5, 7], [2, 3]]],
  ['CANCER', [[.48, .05, .5], [.5, .48, .6], [.16, .92, .7], [.86, .86, .6], [.62, .42, .4]], [[0, 1], [1, 2], [1, 3], [1, 4]]],
  ['LEO', [[.75, .78, 1], [.72, .52, .6], [.66, .32, .9], [.71, .14, .6], [.85, .08, .5], [.96, .2, .6], [.32, .38, .8], [.05, .6, .9], [.34, .62, .6]], [[0, 1], [1, 2], [2, 3], [3, 4], [4, 5], [2, 6], [6, 7], [7, 8], [8, 0], [6, 8]]],
  ['VIRGO', [[.96, .14, .6], [.8, .3, .5], [.62, .42, .8], [.5, .24, .6], [.42, .06, .7], [.4, .56, .6], [.58, .94, 1], [.16, .76, .5], [0, .86, .4]], [[0, 1], [1, 2], [2, 3], [3, 4], [2, 5], [5, 6], [5, 7], [7, 8]]],
  ['LIBRA', [[.2, .42, .8], [.6, .05, .9], [.9, .42, .6], [.1, .92, .5], [.86, .88, .5]], [[0, 1], [1, 2], [2, 0], [0, 3], [2, 4]]],
  ['SCORPIUS', [[.05, .02, .7], [0, .16, .8], [.04, .3, .6], [.2, .2, .6], [.3, .27, 1], [.38, .34, .6], [.45, .48, .7], [.48, .62, .5], [.5, .78, .6], [.58, .92, .6], [.72, .97, .7], [.84, .88, .6], [.87, .74, .7], [.96, .7, .8]], [[0, 1], [1, 2], [1, 3], [3, 4], [4, 5], [5, 6], [6, 7], [7, 8], [8, 9], [9, 10], [10, 11], [11, 12], [12, 13]]],
  ['SAGITTARIUS', [[0, .5, .7], [.22, .42, .8], [.18, .7, 1], [.4, .18, .7], [.56, .4, .6], [.56, .72, .8], [.82, .34, .9], [.84, .64, .6]], [[0, 1], [0, 2], [1, 2], [1, 3], [3, 4], [1, 4], [4, 5], [5, 2], [4, 6], [6, 7], [7, 5]]],
  ['CAPRICORNUS', [[.96, .1, .8], [.92, .26, .9], [.72, .7, .6], [.6, .86, .6], [.44, .76, .5], [0, .34, .9], [.13, .38, .7], [.46, .36, .5]], [[0, 1], [1, 2], [2, 3], [3, 4], [4, 5], [5, 6], [6, 7], [7, 1]]],
  ['AQUARIUS', [[.04, 0, .8], [.24, .16, .9], [.4, .1, .6], [.5, .3, .7], [.42, .52, .6], [.6, .64, .6], [.76, .56, .5], [.92, .82, .6], [.66, .96, .7]], [[0, 1], [1, 2], [2, 3], [3, 4], [4, 5], [5, 6], [6, 7], [5, 8]]],
  ['PISCES', [[.86, .58, .6], [.95, .5, .5], [1, .64, .5], [.93, .75, .5], [.82, .72, .6], [.6, .8, .4], [.35, .88, .5], [.04, .96, .8], [.12, .6, .5], [.22, .3, .5], [.2, .1, .6], [.3, .02, .5]], [[0, 1], [1, 2], [2, 3], [3, 4], [4, 0], [4, 5], [5, 6], [6, 7], [7, 8], [8, 9], [9, 10], [10, 11]]],
]

/* 一个星座的一生（毫秒）：星星亮起 → 连线一笔笔画完 → 名字浮出 → 停留 → 淡出 */
const IN = 3200, DRAW_AT = 2400, DRAW_LEN = 8000, LABEL_AT = 10000, OUT = 5000, MAXLIVE = 2
const rnd = (a, b) => a + Math.random() * (b - a)
const gauss = () => Math.sqrt(-2 * Math.log(Math.random() || 1e-9)) * Math.cos(6.2832 * Math.random())
const clamp = (v) => (v < 0 ? 0 : v > 1 ? 1 : v)

let stop = () => {}

onMounted(() => {
  const cv = document.getElementById('sky')
  const zc = document.getElementById('zodiac')
  const ctx = cv.getContext('2d')
  const zx = zc.getContext('2d')
  const STILL = matchMedia('(prefers-reduced-motion:reduce)').matches
  let W, H, stars = [], live = [], bag = [], nextAt = 0, last = 0, raf = 0, dead = false

  function build() {
    const dpr = Math.min(devicePixelRatio || 1, 2)
    W = innerWidth
    H = innerHeight
    for (const [c, g] of [[cv, ctx], [zc, zx]]) {
      c.width = W * dpr
      c.height = H * dpr
      g.setTransform(dpr, 0, 0, dpr, 0, 0)
    }
    live = []
    /* 均匀撒点会显得规整：三成的星聚成几团，亮度按幂次分布，绝大多数很暗 */
    const clumps = Array.from({ length: 5 }, () => [rnd(0, W), rnd(0, H), rnd(60, 200)])
    stars = []
    for (let i = 0, n = Math.round(W * H / 5200); i < n; i++) {
      let x = rnd(0, W), y = rnd(0, H)
      if (Math.random() < .3) {
        const c = clumps[i % 5]
        x = c[0] + gauss() * c[2]
        y = c[1] + gauss() * c[2]
      }
      const m = Math.pow(Math.random(), 3.2), tint = Math.random()
      stars.push({
        x, y, r: .3 + m * 1.3, a: .14 + m * .7, p: rnd(0, 6.28), s: rnd(.4, 1.8),
        c: tint < .15 ? '255,224,196' : tint < .4 ? '198,212,255' : '236,240,248',
      })
    }
  }

  /* 只有卡面算遮挡：标题和分类条是半透明的，星座从后面透出来反而有层次 */
  function blockers() {
    const R = []
    document.querySelectorAll('.shelf .art').forEach((el) => {
      const q = el.getBoundingClientRect()
      if (q.width > 1 && q.bottom > 0 && q.top < H) R.push(q)
    })
    return R
  }
  const hidden = (x, y, R) => R.some((q) => x > q.left - 4 && x < q.right + 4 && y > q.top - 4 && y < q.bottom + 4)

  /* 星座画大、靠近画面中间；允许被卡挡住一小部分。候选位置按“露出多少 − 离中心多远”打分，取最好的那个 */
  function spawn(t) {
    const B = document.body.classList
    if (B.contains('open') || B.contains('amb-on') || live.length >= MAXLIVE) return
    if (!bag.length) bag = Z.slice().sort(() => Math.random() - .5)
    const z = bag.pop()
    if (live.some((l) => l.z === z)) return
    const R = blockers(), sy = scrollY
    let best = null, bs = -1
    for (let k = 0; k < 80; k++) {
      const sz = Math.min(Math.max(Math.min(W, H) * rnd(.5, .66), 280), 620), rot = rnd(-.25, .25)
      const x = W / 2 + gauss() * W * .16, y = H * .42 + gauss() * H * .14
      if (x < sz * .45 || x > W - sz * .45 || y < sz * .45 || y > H - sz * .45 - 24) continue
      if (!live.every((l) => Math.hypot(l.x - x, l.y - (y + sy)) > (l.sz + sz) * .5)) continue
      const cs = Math.cos(rot), sn = Math.sin(rot)
      const pts = z[1].map(([px, py, b]) => {
        const dx = (px - .5) * sz, dy = (py - .5) * sz
        return [x + dx * cs - dy * sn, y + dx * sn + dy * cs, b]
      })
      const seen = pts.filter((p) => !hidden(p[0], p[1], R)).length / pts.length
      const off = Math.hypot((x - W / 2) / W, (y - H * .42) / H)
      const score = seen - off * .8
      if (seen >= .7 && score > bs) {
        bs = score
        best = { x, y, sz, pts }
      }
    }
    if (!best) {
      bag.unshift(z)
      return
    }
    /* 存成页面坐标，星座跟着页面一起滚动，和卡的相对位置不变 */
    live.push({ z, x: best.x, y: best.y + sy, sz: best.sz, pts: best.pts.map(([x, y, b]) => [x, y + sy, b]), t0: t, hold: rnd(14000, 22000) })
  }

  function drawCon(l, t) {
    const e = t - l.t0, end = DRAW_AT + DRAW_LEN + l.hold, f = e > end ? 1 - (e - end) / OUT : 1
    if (f <= 0) return false
    const sIn = clamp(e / IN), edges = l.z[2], prog = clamp((e - DRAW_AT) / DRAW_LEN) * edges.length
    zx.lineWidth = .8
    zx.strokeStyle = `rgba(196,210,232,${(.32 * f).toFixed(3)})`
    zx.beginPath()
    edges.forEach(([a, b], j) => {
      const s = clamp(prog - j)
      if (!s) return
      const A = l.pts[a], B = l.pts[b]
      zx.moveTo(A[0], A[1])
      zx.lineTo(A[0] + (B[0] - A[0]) * s, A[1] + (B[1] - A[1]) * s)
    })
    zx.stroke()
    for (const [x, y, b] of l.pts) {
      const a = (.4 + .55 * b) * sIn * f, r = .8 + b * 1.5
      const g = zx.createRadialGradient(x, y, 0, x, y, r * 5)
      g.addColorStop(0, `rgba(220,230,250,${(a * .35).toFixed(3)})`)
      g.addColorStop(1, 'rgba(220,230,250,0)')
      zx.fillStyle = g
      zx.beginPath()
      zx.arc(x, y, r * 5, 0, 6.2832)
      zx.fill()
      zx.fillStyle = `rgba(244,247,252,${a.toFixed(3)})`
      zx.beginPath()
      zx.arc(x, y, r, 0, 6.2832)
      zx.fill()
    }
    const la = .4 * clamp((e - LABEL_AT) / 2500) * f
    if (la > 0) {
      let bx = 0, by = -1e9
      for (const p of l.pts) {
        bx += p[0]
        if (p[1] > by) by = p[1]
      }
      zx.font = '700 10px "Cinzel Decorative",serif'
      zx.textAlign = 'center'
      zx.letterSpacing = '4px'
      zx.fillStyle = `rgba(200,212,230,${la.toFixed(3)})`
      zx.fillText(l.z[0], bx / l.pts.length, by + 22)
    }
    return true
  }

  function frame(t) {
    if (dead) return
    if (!STILL) raf = requestAnimationFrame(frame)
    if (t - last < 33) return
    const dt = t - last
    last = t // 约 30 帧就够星星闪，省一半开销
    ctx.clearRect(0, 0, W, H)
    for (const s of stars) {
      const a = s.a * (STILL ? 1 : .7 + .3 * Math.sin(t * .001 * s.s + s.p))
      if (s.r > 1.1) {
        ctx.fillStyle = `rgba(${s.c},${(a * .12).toFixed(3)})`
        ctx.beginPath()
        ctx.arc(s.x, s.y, s.r * 3.5, 0, 6.2832)
        ctx.fill()
      }
      ctx.fillStyle = `rgba(${s.c},${a.toFixed(3)})`
      ctx.beginPath()
      ctx.arc(s.x, s.y, s.r, 0, 6.2832)
      ctx.fill()
    }
    /* 封面背景亮着时，星座整层淡出（CSS），各自的时钟也停住，回来时接着放 */
    if (document.body.classList.contains('amb-on') && dt < 1000) for (const l of live) l.t0 += dt
    if (!STILL && t >= nextAt) {
      spawn(t)
      nextAt = t + rnd(6000, 11000)
    }
    zx.clearRect(0, 0, W, H)
    zx.save()
    zx.translate(0, -scrollY)
    live = live.filter((l) => drawCon(l, t))
    zx.restore()
  }

  function start() {
    build()
    if (STILL) {
      for (let i = 0; i < MAXLIVE; i++) spawn(0)
      live.forEach((l) => { l.t0 = -3e4; l.hold = 1e12 })
      last = -1e9
      frame(0)
      return
    }
    nextAt = performance.now() + 800
  }

  let rz = 0
  const onResize = () => {
    clearTimeout(rz)
    rz = setTimeout(start, 200)
  }
  addEventListener('resize', onResize)
  /* 字体加载后标题和卡名会变宽，挡住的区域跟着变，重新开始 */
  document.fonts.ready.then(() => { if (!dead) start() })
  start()
  if (!STILL) raf = requestAnimationFrame(frame)

  stop = () => {
    dead = true
    cancelAnimationFrame(raf)
    clearTimeout(rz)
    removeEventListener('resize', onResize)
  }
})

onBeforeUnmount(() => stop())
</script>

<template><span hidden></span></template>
