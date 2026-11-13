<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { thumbUrl, hasCover } from '../lib/api'
import { clip, errText, estTk, kfmt, stripTags } from '../lib/format'
import { store } from '../store'
import CardFace from './CardFace.vue'
import GreetPane from './GreetPane.vue'
import LorePane from './LorePane.vue'
import PersonaPane from './PersonaPane.vue'
import RegexPane from './RegexPane.vue'
import ReviewPane from './ReviewPane.vue'
import ScriptPane from './ScriptPane.vue'
import ShelfControls from './ShelfControls.vue'

const emit = defineEmits(['close'])

const REDUCED = matchMedia('(prefers-reduced-motion:reduce)').matches
const PERSONA_KEYS = ['description', 'personality', 'scenario', 'mes_example', 'system_prompt', 'post_history_instructions']
const PANES = { persona: PersonaPane, greet: GreetPane, wb: LorePane, rx: RegexPane, sp: ScriptPane, review: ReviewPane }

const tab = ref('persona')
const shown = ref('persona')
const paneEl = ref(null)
const wrapEl = ref(null)
const tind = ref(null)
let tabTimer = 0
let tspin = 45

const card = computed(() => store.detail?.card)
const name = computed(() => card.value?.name || store.cur?.name || '')
const meta = computed(() => {
  const c = card.value
  if (!c) return store.detail?.meta.error ? '这张卡无法解析' : ''
  const tags = c.tags.filter(Boolean)
  return [c.creator ? `${c.creator} 制作` : '', tags.join('，')].filter(Boolean).join('，')
})
const desc = computed(() => {
  const c = card.value
  if (!c) return errText(store.detail?.meta.error)
  return clip(stripTags(c.creator_notes) || stripTags(c.description), 120)
})
const tokens = computed(() => {
  const c = card.value
  if (!c) return 0
  const fields = [c.description, c.personality, c.scenario, c.first_mes, c.mes_example, c.system_prompt, c.post_history_instructions]
  const book = (c.character_book?.entries || []).filter((e) => e.enabled !== false && !e.disable)
  return fields.reduce((s, t) => s + estTk(t), 0) + book.reduce((s, e) => s + estTk(e.content), 0)
})
const grade = computed(() => store.rating?.display_score ?? null)
const bg = computed(() => (store.cur && hasCover(store.cur) ? `url('${thumbUrl(store.cur)}')` : 'none'))

const tabs = computed(() => {
  const c = card.value
  if (!c) return [['persona', '人设', '']]
  const wb = store.rows.wb.length
  const persona = PERSONA_KEYS.some((k) => (c[k] || '').trim())
  return [
    ...(persona ? [['persona', '人设', '']] : []),
    ['greet', '开场白', c.greetings.length],
    ['wb', '世界书', wb],
    ['rx', '正则', store.rows.rx.length],
    ['sp', '脚本', c.scripts.length],
    ['review', '点评', ''],
  ].filter(([k, , n]) => !((k === 'rx' || k === 'sp') && !n))
})

function placeTind() {
  const w = wrapEl.value
  const i = tind.value
  const b = w?.querySelector('[aria-selected="true"]')
  if (!i || !b) return
  /* 按钮带字距，右边多出半个字距的空，量宽时扣掉，线和菱形才对得上字的中间 */
  const R = w.getBoundingClientRect()
  const r = b.getBoundingClientRect()
  const ls = parseFloat(getComputedStyle(b).letterSpacing) || 0
  const tw = r.width - ls
  i.style.setProperty('--w', tw * 1.4 + 'px')
  i.style.setProperty('--x', r.left - R.left - tw * 0.2 + 'px')
  i.style.setProperty('--y', r.bottom - R.top + 'px')
  i.style.setProperty('--rot', tspin + 'deg')
  if (i.classList.contains('cold')) requestAnimationFrame(() => requestAnimationFrame(() => i.classList.remove('cold')))
}

function layout() {
  tind.value?.classList.add('cold')
  placeTind()
}

function goTab(k) {
  if (k === tab.value) return
  const keys = tabs.value.map((t) => t[0])
  const dir = Math.sign(keys.indexOf(k) - keys.indexOf(tab.value)) || 1
  tab.value = k
  tspin += 180 * dir
  nextTick(placeTind)
  const p = paneEl.value
  if (REDUCED) {
    shown.value = k
    return
  }
  clearTimeout(tabTimer)
  p.style.setProperty('--dx', dir * 18 + 'px')
  p.classList.remove('swap')
  p.classList.add('out')
  tabTimer = setTimeout(async () => {
    /* 先关掉过渡再撤 out，免得整块内容自己滑回来，跟子元素的浮上动画叠在一起 */
    p.classList.add('swap')
    p.classList.remove('out')
    shown.value = k
    await nextTick()
    ;[...p.children].forEach((c, j) => c.style.setProperty('--k', Math.min(j, 8)))
    tabTimer = setTimeout(() => p.classList.remove('swap'), 1100)
  }, 200)
}

watch(() => store.cur?.id, (id, old) => {
  if (id === undefined || old === undefined) {
    tab.value = shown.value = tabs.value[0][0]
    tspin = 45
  }
})

watch(tabs, (t) => {
  if (!t.some((x) => x[0] === tab.value)) {
    tab.value = shown.value = t[0][0]
  }
  nextTick(placeTind)
}, { deep: true })

const onResize = () => {
  if (!document.body.classList.contains('open')) return
  tind.value?.classList.add('cold')
  placeTind()
}
onMounted(() => addEventListener('resize', onResize))
onBeforeUnmount(() => removeEventListener('resize', onResize))

defineExpose({ layout })
</script>

<template>
  <article id="detail" class="detail">
    <template v-if="store.cur && store.detail">
      <section class="hero">
        <div class="hero-bg" :style="{ backgroundImage: bg }"></div>
        <div class="hero-wrap">
          <button class="back rise" style="--d:250" aria-label="返回卡库" @click="emit('close')">
            <svg viewBox="0 0 34 26" aria-hidden="true"><path d="M31 13H5" /><path d="M13.5 4.5 5 13l8.5 8.5" /></svg>
          </button>
          <div class="hero-in">
            <CardFace :item="store.cur" :index="store.curIndex" />
            <div>
              <h2 class="rise" style="--d:380">{{ name }}</h2>
              <p v-if="meta" class="meta rise" style="--d:470">{{ meta }}</p>
              <p v-if="desc" class="desc rise" style="--d:550">{{ desc }}</p>
              <div class="actions rise" style="--d:630">
                <div class="stat"><b>{{ kfmt(tokens) }}</b><span>TOKENS</span></div>
                <i class="dia"></i>
                <div class="grade"><b>{{ grade ?? '—' }}</b><span>/ 10 分</span></div>
                <i class="dia"></i>
                <ShelfControls />
              </div>
            </div>
          </div>
        </div>
      </section>
      <div ref="wrapEl" class="tabs-wrap rise" style="--d:720">
        <div id="tabs" class="tabs" role="tablist">
          <button v-for="[k, label, n] in tabs" :key="k" role="tab" :aria-selected="k === tab" @click="goTab(k)">
            {{ label }}<small v-if="n !== ''">{{ n }}</small>
          </button>
        </div>
        <i ref="tind" class="tind cold"></i>
      </div>
      <section id="pane" ref="paneEl" class="pane rise" style="--d:800">
        <p v-if="!card" class="empty">{{ errText(store.detail.meta.error) || '这张卡无法读取。' }}</p>
        <component :is="PANES[shown]" v-else :key="store.detail.id + shown" />
      </section>
    </template>
  </article>
</template>

<style>
.detail{display:none}
body.open .home{display:none}
body.open .detail{display:block}
.hero{position:relative;min-height:clamp(420px,56vh,620px);overflow:hidden}
.hero-bg{position:absolute;inset:-60px;background-size:cover;background-position:center 30%;filter:blur(38px) saturate(1.1) brightness(.5);transform:scale(1.1)}
.hero::after{content:"";position:absolute;inset:0;background:linear-gradient(180deg,rgba(11,13,19,.2) 0%,rgba(11,13,19,.65) 60%,var(--bg) 100%)}
/* 返回键改为 fixed 后不再占位，顶部补回它原来的 22+48px，封面落点不变 */
.hero-wrap{position:relative;z-index:1;width:var(--wrap);margin:0 auto;padding:70px var(--pad) 0}
.back{position:fixed;z-index:30;top:22px;left:calc(max(0px,(100% - 1640px)/2) + var(--pad));width:48px;height:48px;display:grid;place-items:center;color:var(--silver);opacity:.72;
  transition:opacity .3s,transform .3s,filter .3s}
.back svg{width:34px;height:26px;fill:none;stroke:currentColor;stroke-width:2.2;stroke-linecap:square;stroke-linejoin:miter}
.back:hover{opacity:1;transform:translateX(-4px);filter:drop-shadow(0 0 8px color-mix(in srgb,var(--theme) 70%,transparent))}
/* 文字列定宽：按内容定宽时，卡名的字体分片晚到一步，列宽一变整块重新居中，飞到的封面会被挪开 */
.hero-in{display:grid;grid-template-columns:clamp(200px,18vw,300px) min(40em,calc(100% - clamp(200px,18vw,300px) - clamp(28px,4vw,64px)));justify-content:center;gap:clamp(28px,4vw,64px);align-items:end;padding:12px 0 36px}
.hero h2{font-family:var(--show);font-weight:400;font-size:clamp(40px,4.6vw,76px);color:var(--silver);line-height:1.15;letter-spacing:.06em;
  text-shadow:0 2px 18px rgba(0,0,0,.6);overflow-wrap:anywhere}
.hero .meta{margin-top:12px;font-size:14px;color:var(--text);opacity:.85}
.hero .desc{margin-top:18px;max-width:38em;font-family:var(--serif);font-size:16px;line-height:1.95;color:var(--text);
  display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:3;overflow:hidden}
.actions{display:flex;align-items:center;gap:22px;margin-top:28px}
.grade{display:flex;align-items:baseline;gap:8px}
.grade b{font-family:var(--latin);font-size:32px;color:var(--silver)}
.grade span{font-size:12px;color:var(--dim)}
.stat{display:flex;align-items:baseline;gap:8px}
.stat b{font-family:var(--latin);font-size:32px;color:var(--silver)}
.stat span{font-family:var(--latin);font-size:11px;letter-spacing:.2em;color:var(--dim)}
.actions .dia{width:6px;height:6px;transform:rotate(45deg);background:var(--theme);opacity:.7}
.tabs-wrap{position:relative;border-bottom:1px solid var(--line)}
.tabs{width:var(--wrap);margin:0 auto;padding:0 var(--pad);display:flex;justify-content:center;flex-wrap:wrap;gap:0 clamp(22px,3vw,44px)}
.tabs button{padding:15px 0;font-family:var(--show);font-size:17px;letter-spacing:.16em;color:var(--dim);border-bottom:1px solid transparent;margin-bottom:-1px;transition:color .35s}
.tabs button:hover{color:#cdd4dd}
.tabs button[aria-selected="true"]{color:var(--silver)}
/* 标签栏的指示线：和首页分类条同一套，滑到新标签，菱形转半圈 */
.tind{position:absolute;left:0;top:0;height:1px;width:var(--w,0);transform:translate(var(--x,0),calc(var(--y,0px) - 1px));pointer-events:none;
  background:linear-gradient(90deg,transparent,var(--theme),transparent);
  transition:transform .55s cubic-bezier(.65,0,.25,1),width .55s cubic-bezier(.65,0,.25,1)}
.tind::after{content:"";position:absolute;left:50%;top:0;width:6px;height:6px;transform:translate(-50%,-50%) rotate(var(--rot,45deg));
  background:var(--silver);box-shadow:0 0 10px var(--theme);transition:transform .55s cubic-bezier(.65,0,.25,1)}
.tind.cold,.tind.cold::after{transition:none}
.tabs small{margin-left:6px;font-family:var(--latin);font-size:11px;opacity:.7;letter-spacing:0}
/* 切标签：旧内容往反方向淡出，新内容从标签移动的方向依次浮上来 */
.pane{width:var(--wrap);margin:0 auto;padding:34px var(--pad) 100px;transition:opacity .2s ease,transform .2s ease}
.pane.out{opacity:0;transform:translateX(calc(var(--dx,0px) * -1))}
.pane.swap{transition:none}
.pane.swap>*{animation:panein .6s cubic-bezier(.2,.8,.2,1) backwards;animation-delay:calc(var(--k,0)*55ms)}
@keyframes panein{from{opacity:0;transform:translate(var(--dx,0px),14px)}}
.pane>*{max-width:900px;margin-left:auto;margin-right:auto}
.pane .empty{text-align:center;color:var(--dim)}

/* ── 进出详情页的衔接 ──
   封面从卡库的位置飞到详情页的位置（.fly 是飞行中的替身），
   卡库向外淡出，详情页的模糊背景淡入，文字随后一行行浮起。返回时倒着来。 */
.fly{position:fixed;z-index:20;pointer-events:none;transform-origin:0 0}
.fly .frame,.fly .no{opacity:0}
.fly.hot .frame{opacity:.7}
.fly.hot .no{opacity:.9}
.fly.hot .art{box-shadow:0 14px 26px -10px rgba(0,0,0,.85),0 0 0 1px rgba(255,255,255,.04),0 0 42px -12px var(--theme)}
.fly.hot .art img{filter:brightness(1.07) saturate(1.06)}
body.open.opening .home,body.open.closing .home{display:block;position:fixed;top:var(--hy,0);left:0;right:0;pointer-events:none;
  transform-origin:var(--ox,50%) var(--oy,50%)}
body.opening .home{z-index:2;animation:homeout .55s cubic-bezier(.4,0,.6,1) forwards}
body.closing .home{animation:homein .6s cubic-bezier(.2,.7,.2,1) .15s backwards}
body.closing .detail{z-index:2;opacity:0;transition:opacity .3s ease;pointer-events:none}
@keyframes homeout{to{opacity:0;transform:scale(1.05)}}
@keyframes homein{from{opacity:0;transform:scale(1.05)}}
.detail.enter .hero-bg{animation:bgin 1.5s cubic-bezier(.2,.7,.2,1) backwards}
@keyframes bgin{from{opacity:0;transform:scale(1.32)}}
.detail.enter .rise{animation:lift .8s cubic-bezier(.2,.8,.2,1) backwards;animation-delay:calc(var(--d)*1ms)}
.detail.enter h2.rise{animation-name:liftb;animation-duration:1s}
@keyframes lift{from{opacity:0;transform:translateY(16px)}}
@keyframes liftb{from{opacity:0;transform:translateY(16px);filter:blur(8px);letter-spacing:.16em}}

@media (max-width:560px){
  .hero-in{grid-template-columns:1fr}
  .hero-in .tilt{width:200px}
}
</style>
