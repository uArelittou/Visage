<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { createCollection, setCollections, store, toggleFavorite } from '../store'

const open = ref(false)
const draft = ref('')
const root = ref(null)
const input = ref(null)

const mine = computed(() => new Set(store.cur?.collections || []))
const user = computed(() => store.cats.filter((c) => c.kind === 'user'))
const faved = computed(() => !!store.cur?.favorite)

function toggle(c) {
  const ids = new Set(mine.value)
  if (!ids.delete(c.id)) ids.add(c.id)
  setCollections([...ids])
}

async function add() {
  const name = draft.value.trim()
  if (!name) return
  const c = await createCollection(name)
  if (!c) return
  draft.value = ''
  await setCollections([...mine.value, c.id])
}

// Esc 先关菜单；在捕获阶段拦下，免得同时触发「返回卡库」
const onKey = (e) => {
  if (e.key !== 'Escape') return
  e.stopPropagation()
  open.value = false
}
const onDown = (e) => { if (!root.value?.contains(e.target)) open.value = false }

watch(open, async (on) => {
  if (on) {
    addEventListener('keydown', onKey, true)
    addEventListener('pointerdown', onDown, true)
    await nextTick()
    if (!user.value.length) input.value?.focus()
  } else {
    removeEventListener('keydown', onKey, true)
    removeEventListener('pointerdown', onDown, true)
  }
})
watch(() => store.cur?.id, () => { open.value = false })
onBeforeUnmount(() => {
  removeEventListener('keydown', onKey, true)
  removeEventListener('pointerdown', onDown, true)
})
</script>

<template>
  <div ref="root" class="shelf-ctl">
    <button class="sc-btn" :class="{ on: faved }" :aria-pressed="faved" :aria-label="faved ? '取消收藏' : '收藏'" @click="toggleFavorite">
      <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 20.5 4.2 12.7a4.6 4.6 0 0 1 6.5-6.5L12 7.5l1.3-1.3a4.6 4.6 0 0 1 6.5 6.5Z" /></svg>
    </button>
    <button class="sc-btn" :class="{ on: mine.size > 0 }" aria-haspopup="true" :aria-expanded="open" aria-label="分到分类" @click="open = !open">
      <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2.8 21.2 12 12 21.2 2.8 12Z" /><path d="M12 8.5v7M8.5 12h7" /></svg>
    </button>
    <div v-if="open" class="sc-menu" role="menu">
      <p v-if="!user.length" class="sc-none">还没有自己的分类</p>
      <button v-for="c in user" :key="c.id" class="sc-row" role="menuitemcheckbox" :aria-checked="mine.has(c.id)" @click="toggle(c)">
        <i class="sc-box" :class="{ on: mine.has(c.id) }"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12.5 10 17.5 19 7" /></svg></i>
        <span>{{ c.name }}</span>
      </button>
      <label class="sc-new">
        <input ref="input" v-model="draft" maxlength="24" placeholder="新建分类" spellcheck="false" @keydown.enter.prevent="add">
      </label>
    </div>
  </div>
</template>

<style>
.shelf-ctl{position:relative;display:flex;align-items:center;gap:4px}
.sc-btn{width:32px;height:32px;display:grid;place-items:center;color:var(--dim);transition:color .3s,filter .3s}
.sc-btn svg{width:19px;height:19px;fill:none;stroke:currentColor;stroke-width:1.5;stroke-linejoin:round;stroke-linecap:round;transition:fill .3s}
.sc-btn:hover{color:var(--silver)}
.sc-btn.on{color:var(--theme);filter:drop-shadow(0 0 8px color-mix(in srgb,var(--theme) 60%,transparent))}
.sc-btn.on:first-child svg{fill:currentColor}
.sc-menu{position:absolute;left:0;bottom:calc(100% + 8px);z-index:6;min-width:200px;max-width:280px;max-height:300px;overflow:auto;padding:8px;
  background:rgba(14,17,24,.96);border:1px solid var(--line);box-shadow:0 18px 40px -12px rgba(0,0,0,.8);backdrop-filter:blur(10px)}
.sc-none{padding:6px 8px;font-size:12.5px;color:var(--dim)}
.sc-row{display:flex;align-items:center;gap:10px;width:100%;padding:7px 8px;text-align:left;font-family:var(--show);font-size:15px;letter-spacing:.1em;color:var(--text);transition:background .2s,color .2s}
.sc-row:hover{background:rgba(255,255,255,.04);color:var(--silver)}
.sc-box{flex:none;width:14px;height:14px;display:grid;place-items:center;border:1px solid rgba(233,237,242,.3);transform:rotate(45deg) scale(.82);transition:all .25s}
.sc-box svg{width:11px;height:11px;fill:none;stroke:var(--bg);stroke-width:2.6;transform:rotate(-45deg);opacity:0}
.sc-box.on{background:var(--theme);border-color:var(--theme)}
.sc-box.on svg{opacity:1}
.sc-new{display:block;margin-top:6px;padding-top:6px;border-top:1px solid var(--line)}
.sc-new input{width:100%;padding:6px 8px;background:none;border:0;outline:0;color:var(--silver);font-family:var(--show);font-size:15px;letter-spacing:.1em}
.sc-new input::placeholder{color:var(--dim)}
</style>
