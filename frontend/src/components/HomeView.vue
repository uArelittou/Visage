<script setup>
import { computed, ref } from 'vue'
import { ambOff } from '../lib/ambient'
import { createCollection, deleteCollection, loadItems, renameCollection, store } from '../store'
import CategoryBar from './CategoryBar.vue'
import SearchView from './SearchView.vue'
import SettingsView from './SettingsView.vue'
import Shelf from './Shelf.vue'

const emit = defineEmits(['open'])

const phase = ref('')
let enterTimer = 0
let moreBusy = false

async function pick(i) {
  if (store.view !== 'shelf') {
    store.view = 'shelf'
    if (i === store.catIdx) return
  }
  if (i === store.catIdx) return
  store.catIdx = i
  ambOff()
  phase.value = 'out'
  await Promise.all([loadItems(), new Promise((r) => setTimeout(r, 220))])
  // 进场动画只在换分类时播；不摘掉的话，从详情页返回时会重播一遍
  phase.value = 'enter'
  clearTimeout(enterTimer)
  enterTimer = setTimeout(() => { phase.value = '' }, 1400)
}

async function more() {
  if (moreBusy || store.view !== 'shelf' || store.items.length >= store.total) return
  moreBusy = true
  try { await loadItems({ more: true }) } finally { moreBusy = false }
}

const EMPTY = {
  all: '卡库里还没有卡。点右上角的「收录」添加文件夹或卡片。',
  favorites: '还没有收藏的卡。在卡的详情页点心形图标收藏。',
  unsorted: '所有卡都已经分过类了。',
}
const emptyText = computed(() => EMPTY[store.cats[store.catIdx]?.kind] || '这个分类里还没有卡。')

const toggle = (v) => { store.view = store.view === v ? 'shelf' : v }
</script>

<template>
  <div class="home">
    <header class="masthead">
      <div class="title">
        <h1>千面录</h1>
        <div class="latin">The Codex <span>of</span> a Thousand Faces</div>
        <div class="orn"><i></i><b>MMXXVI</b><i></i></div>
      </div>
    </header>
    <CategoryBar
      :cats="store.cats" :active="store.catIdx" :total="store.total" :view="store.view"
      @pick="pick" @find="toggle('search')" @settings="toggle('settings')" @import="store.gate = true"
      @create="createCollection" @rename="renameCollection" @remove="deleteCollection"
    />
    <SearchView v-if="store.view === 'search'" @open="(...a) => emit('open', ...a)" />
    <SettingsView v-else-if="store.view === 'settings'" />
    <Shelf v-else :items="store.items" :phase="phase" :empty="emptyText" @open="(...a) => emit('open', ...a)" @more="more" />
  </div>
</template>

<style>
.masthead{position:relative;text-align:center;padding:clamp(36px,6vh,72px) var(--pad) clamp(22px,3.4vh,38px)}
.title h1{font-family:var(--serif);font-weight:900;font-size:clamp(56px,7.2vw,128px);line-height:1;
  /* letter-spacing 会在末字后多留一格，padding-left 补回来才真居中 */
  letter-spacing:.16em;padding-left:.16em;
  background:linear-gradient(180deg,#fff 0%,#e3e7ec 38%,#9aa2ad 72%,#d6dbe1 100%);
  -webkit-background-clip:text;background-clip:text;color:transparent;
  filter:drop-shadow(0 0 14px rgba(220,230,245,.28)) drop-shadow(0 4px 0 rgba(0,0,0,.55))}
.title .latin{font-family:"UnifrakturMaguntia",serif;font-size:clamp(20px,2.3vw,40px);color:#dfe3e8;
  margin-top:clamp(8px,1.2vh,16px);letter-spacing:.05em;
  text-shadow:0 0 8px color-mix(in srgb,var(--theme-deep) 95%,transparent),0 0 22px color-mix(in srgb,var(--theme-deep) 55%,transparent)}
.title .latin span{color:var(--theme)}
.orn{display:flex;align-items:center;justify-content:center;gap:14px;margin-top:clamp(14px,2vh,22px);color:#8d96a3}
.orn i{display:block;height:1px;width:clamp(60px,10vw,180px);background:linear-gradient(90deg,transparent,rgba(233,237,242,.45))}
.orn i:last-child{transform:scaleX(-1)}
.orn b{font-family:var(--latin);font-size:11px;letter-spacing:.42em;padding-left:.42em;font-weight:700;color:#9aa3af}
</style>
