<script setup>
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

const props = defineProps({
  cats: { type: Array, required: true },
  active: { type: Number, required: true },
  total: { type: Number, default: 0 },
  view: { type: String, default: 'shelf' },
})
const emit = defineEmits(['pick', 'find', 'settings', 'import', 'create', 'rename', 'remove'])

const catsEl = ref(null)
const ind = ref(null)
const shown = ref(0)
let spin = 45
let raf = 0

function place() {
  const el = catsEl.value
  const b = el?.querySelectorAll('.cat')[props.active]
  if (!b || !ind.value) return
  // 分类名可能被悬停按钮、输入框撑出不同的父级，位置一律按屏幕坐标相对 .cats 量
  const R = el.getBoundingClientRect()
  const r = b.getBoundingClientRect()
  ind.value.style.setProperty('--w', r.width * 1.4 + 'px')
  ind.value.style.setProperty('--x', r.left - R.left - r.width * 0.2 + 'px')
  ind.value.style.setProperty('--rot', spin + 'deg')
}

// 字体加载完卡名会变宽，指示线要重新对齐；这样的对齐不要动画
function settle() {
  const i = ind.value
  if (!i) return
  i.classList.add('cold')
  place()
  void i.offsetWidth
  i.classList.remove('cold')
}

watch(() => props.active, (_, old) => {
  if (old !== undefined) spin += 180
  place()
})
watch(() => props.cats, () => nextTick(settle), { deep: false })

watch(() => props.total, (to) => {
  const from = shown.value
  const t0 = performance.now()
  cancelAnimationFrame(raf)
  const step = (t) => {
    const k = Math.min(1, (t - t0) / 600)
    const e = 1 - Math.pow(1 - k, 3)
    shown.value = Math.round(from + (to - from) * e)
    if (k < 1) raf = requestAnimationFrame(step)
  }
  raf = requestAnimationFrame(step)
}, { immediate: true })

// ---- 用户分类：新建、重命名、删除。平时看不到，悬停或右键才出现 ----
const adding = ref(false)
const draft = ref('')
const addInput = ref(null)
const renamingId = ref(null)
const renameDraft = ref('')
const renameInput = ref(null)
const armedId = ref(null)
let armTimer = 0

async function startAdd() {
  adding.value = true
  draft.value = ''
  await nextTick()
  addInput.value?.focus()
  settle()
}

function endAdd(commit) {
  const name = draft.value.trim()
  adding.value = false
  if (commit && name) emit('create', name)
  nextTick(settle)
}

async function startRename(c) {
  renamingId.value = c.id
  renameDraft.value = c.name
  await nextTick()
  const el = [].concat(renameInput.value || [])[0]
  el?.focus()
  el?.select()
  settle()
}

function endRename(c, commit) {
  if (renamingId.value !== c.id) return
  renamingId.value = null
  const name = renameDraft.value.trim()
  if (commit && name && name !== c.name) emit('rename', c.id, name)
  nextTick(settle)
}

// 只删分类，不删卡。点一下变「确认删除」，3 秒不点自动复原
function arm(c) {
  if (armedId.value !== c.id) {
    armedId.value = c.id
    clearTimeout(armTimer)
    armTimer = setTimeout(() => { armedId.value = null }, 3000)
    return
  }
  clearTimeout(armTimer)
  armedId.value = null
  emit('remove', c.id)
}

onMounted(() => {
  settle()
  document.fonts.ready.then(settle)
  addEventListener('resize', settle)
})
onBeforeUnmount(() => {
  removeEventListener('resize', settle)
  cancelAnimationFrame(raf)
  clearTimeout(armTimer)
})
</script>

<template>
  <nav class="bar">
    <div class="bar-in">
      <div class="tally"><span class="ab">CT.</span><b>{{ String(shown).padStart(2, '0') }}</b></div>
      <div ref="catsEl" class="cats">
        <span v-for="(c, i) in cats" :key="c.path" class="cat-slot">
          <input
            v-if="c.kind === 'user' && renamingId === c.id" ref="renameInput" v-model="renameDraft"
            class="cat cat-input" maxlength="24" aria-label="分类名" spellcheck="false"
            @keydown.enter.prevent="endRename(c, true)" @keydown.esc.stop.prevent="endRename(c, false)"
            @blur="endRename(c, true)"
          >
          <button
            v-else class="cat" :aria-pressed="i === active && view === 'shelf'"
            @click="emit('pick', i)" @contextmenu.prevent="c.kind === 'user' && startRename(c)"
          >
            <span class="zh">{{ c.name }}</span><span class="en">{{ c.en }}</span>
          </button>
          <span v-if="c.kind === 'user' && renamingId !== c.id" class="cat-ops" :class="{ on: armedId === c.id }">
            <button class="op" aria-label="重命名分类" @click="startRename(c)">
              <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 20l1-4L16.5 4.5a2 2 0 0 1 3 3L8 19z" /></svg>
            </button>
            <button class="op del" :class="{ armed: armedId === c.id }" aria-label="删除分类" @click="arm(c)">
              <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18" /></svg><span>确认删除</span>
            </button>
          </span>
        </span>
        <i ref="ind" class="ind cold"></i>
      </div>
      <div class="tools">
        <button class="find" :class="{ on: view === 'search' }" aria-label="搜索" @click="emit('find')">
          <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><circle cx="11" cy="11" r="7" /><path d="M20 20l-4-4" /></svg>
        </button>
        <input
          v-if="adding" ref="addInput" v-model="draft" class="cat-input" maxlength="24" placeholder="收藏夹名"
          aria-label="新收藏夹名" spellcheck="false"
          @keydown.enter.prevent="endAdd(true)" @keydown.esc.stop.prevent="endAdd(false)" @blur="endAdd(!!draft.trim())"
        >
        <button v-else class="find cat-add" aria-label="新建收藏夹" title="新建收藏夹" @click="startAdd">
          <!-- 星形描边和搜索、设置同一笔宽；右下角的小菱形挖出十字，和「收录」的菱形加号是一套 -->
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <path d="M10 2.8l2.2 4.6 5 .7-3.6 3.5.85 5-4.45-2.35-4.45 2.35.85-5L1.8 8.1l5-.7z" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round" />
            <path class="badge" d="M18 12.6 23.4 18 18 23.4 12.6 18Z" fill="currentColor" />
            <path d="M18 15.6v4.8M15.6 18h4.8" stroke="var(--bg)" stroke-width="1.5" stroke-linecap="round" />
          </svg>
        </button>
        <button class="find" :class="{ on: view === 'settings' }" aria-label="设置" @click="emit('settings')">
          <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><circle cx="12" cy="12" r="3.2" /><circle cx="12" cy="12" r="7.2" /><path d="M12 2.5v2.3M12 19.2v2.3M2.5 12h2.3M19.2 12h2.3M5.3 5.3l1.6 1.6M17.1 17.1l1.6 1.6M18.7 5.3l-1.6 1.6M6.9 17.1l-1.6 1.6" /></svg>
        </button>
        <button class="import" @click="emit('import')">
          <svg class="seal" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path class="rim" d="M12 1.5 22.5 12 12 22.5 1.5 12Z" /><path class="cross" d="M12 7.5v9M7.5 12h9" /><circle class="dot" cx="12" cy="12" r="1.3" /></svg>
          <span class="zh">收录</span>
        </button>
      </div>
    </div>
  </nav>
</template>

<style>
.bar{position:sticky;top:0;z-index:20;border-top:1px solid var(--line);border-bottom:1px solid var(--line);
  background:color-mix(in srgb,var(--theme-deep) 14%,rgba(10,12,17,.6));backdrop-filter:blur(10px) saturate(1.2)}
.bar-in{width:var(--wrap);margin:0 auto;padding:0 var(--pad);display:grid;grid-template-columns:1fr auto 1fr;align-items:center;min-height:64px}
.tally{display:flex;align-items:baseline;gap:8px;color:var(--dim)}
.tally .ab{font-family:var(--latin);font-weight:700;font-size:10px;letter-spacing:.32em;color:#8d96a3;align-self:flex-start;margin-top:4px}
.tally b{font-family:var(--latin);font-weight:700;font-size:24px;letter-spacing:.06em;font-variant-numeric:tabular-nums;
  background:linear-gradient(180deg,#fff,#9aa2ad);-webkit-background-clip:text;background-clip:text;color:transparent;
  filter:drop-shadow(0 0 8px color-mix(in srgb,var(--theme) 45%,transparent))}

.cats{position:relative;display:flex;gap:clamp(22px,3.6vw,64px);max-width:100%}
.cat{position:relative;display:flex;flex-direction:column;align-items:center;gap:3px;padding:10px 2px 12px;color:#8f99a7;transition:color .35s}
.cat .zh{font-family:var(--show);font-size:clamp(17px,1.25vw,21px);letter-spacing:.24em;padding-left:.24em;line-height:1;white-space:nowrap}
.cat .en{font-family:var(--latin);font-weight:700;font-size:9px;letter-spacing:.3em;padding-left:.3em;opacity:.55;transition:opacity .35s;white-space:nowrap}
.cat:hover{color:#cdd4dd}
.cat[aria-pressed="true"]{color:var(--silver)}
.cat[aria-pressed="true"] .zh{background:linear-gradient(180deg,#fff,#aeb6c1);-webkit-background-clip:text;background-clip:text;color:transparent;
  filter:drop-shadow(0 0 8px rgba(233,237,242,.35))}
.cat[aria-pressed="true"] .en{opacity:.85}
/* 一根共用的指示线：切换分类时滑过去，菱形顺手转半圈 */
.ind{position:absolute;left:0;bottom:-1px;height:1px;width:var(--w,0);transform:translateX(var(--x,0));pointer-events:none;
  background:linear-gradient(90deg,transparent,rgba(233,237,242,.7),transparent);
  transition:transform .6s cubic-bezier(.65,0,.25,1),width .6s cubic-bezier(.65,0,.25,1)}
.ind::after{content:"";position:absolute;left:50%;top:0;width:7px;height:7px;transform:translate(-50%,-50%) rotate(var(--rot,45deg));
  background:var(--silver);box-shadow:0 0 10px var(--theme);transition:transform .6s cubic-bezier(.65,0,.25,1)}
.ind.cold{transition:none}.ind.cold::after{transition:none}
.tools{justify-self:end;display:flex;align-items:center;gap:10px}
.find{width:38px;height:38px;display:grid;place-items:center;color:var(--dim);transition:color .2s}
.find:hover,.find.on{color:var(--silver)}

/* 收录按钮：细银框 + 四角折线，像展柜的标牌 */
.import{position:relative;display:flex;align-items:center;gap:10px;height:40px;padding:0 18px 0 14px;color:#e4e8ed;
  background:linear-gradient(180deg,rgba(255,255,255,.07),rgba(255,255,255,.01));border:1px solid rgba(233,237,242,.22);
  transition:border-color .3s,box-shadow .3s,background .3s}
.import::before,.import::after{content:"";position:absolute;width:7px;height:7px;border:1px solid var(--silver);opacity:.7;transition:all .3s}
.import::before{left:-4px;top:-4px;border-right:0;border-bottom:0}
.import::after{right:-4px;bottom:-4px;border-left:0;border-top:0}
.import:hover{border-color:color-mix(in srgb,var(--theme) 75%,transparent);box-shadow:0 0 22px -2px color-mix(in srgb,var(--theme) 45%,transparent),inset 0 0 18px color-mix(in srgb,var(--theme) 15%,transparent);
  background:linear-gradient(180deg,color-mix(in srgb,var(--theme) 14%,transparent),color-mix(in srgb,var(--theme) 2%,transparent))}
.import:hover::before{left:-7px;top:-7px}.import:hover::after{right:-7px;bottom:-7px}
/* 菱形和十字画在同一个 SVG 里，用字符 "+" 会因字体基线偏上偏粗 */
.import .seal{width:24px;height:24px;display:block;overflow:visible;transition:transform .4s cubic-bezier(.2,.8,.2,1)}
.import:hover .seal{transform:rotate(90deg)}
.seal .rim{stroke:currentColor;stroke-width:1;opacity:.85}
.seal .cross{stroke:currentColor;stroke-width:1.1;stroke-linecap:round}
.seal .dot{fill:var(--theme);opacity:0;transition:opacity .3s}
.import:hover .seal .dot{opacity:1}
.import .zh{font-family:var(--show);font-size:17px;letter-spacing:.3em;padding-left:.1em}

/* 用户分类：分类名后面的小图标平时不显示，悬停或键盘聚焦才出现；末尾的菱形加号和「收录」是同一套图形 */
.cat-slot{position:relative;display:flex;align-items:stretch}
.cat-ops{position:absolute;left:100%;top:50%;transform:translateY(-50%);margin-left:2px;display:flex;flex-direction:column;gap:2px;
  opacity:0;pointer-events:none;transition:opacity .25s}
.cat-slot:hover .cat-ops,.cat-slot:focus-within .cat-ops,.cat-ops.on{opacity:1;pointer-events:auto}
.op{display:flex;align-items:center;gap:4px;height:14px;padding:0 2px;color:var(--dim);font-size:11px;letter-spacing:.08em;white-space:nowrap;transition:color .2s}
.op svg{width:11px;height:11px;fill:none;stroke:currentColor;stroke-width:1.7;stroke-linecap:round;stroke-linejoin:round}
.op span{display:none}
.op:hover{color:var(--silver)}
.op.del:hover,.op.del.armed{color:var(--danger)}
.op.del.armed span{display:inline;padding-right:4px;background:var(--bg)}
.cat-input{align-self:center;width:7.5em;padding:6px 4px;text-align:center;font-family:var(--show);font-size:clamp(16px,1.15vw,19px);letter-spacing:.16em;
  color:var(--silver);background:none;border:0;border-bottom:1px solid color-mix(in srgb,var(--theme) 70%,transparent);outline:0}
.cat-input::placeholder{color:var(--dim);letter-spacing:.1em}
.cat-add svg{overflow:visible}
.cat-add .badge{transition:fill .3s}
.cat-add:hover .badge{fill:var(--theme)}

@media (max-width:860px){
  .bar-in{grid-template-columns:1fr auto;grid-template-areas:"cats cats" "tally tools";row-gap:4px;padding-top:4px;padding-bottom:8px}
  .cats{grid-area:cats;justify-self:center}.tally{grid-area:tally}.tools{grid-area:tools}
}
@media (max-width:560px){.cat .en{display:none}}
</style>
