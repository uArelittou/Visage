<script setup>
import { onMounted, ref, watch } from 'vue'
import { api } from '../lib/api'
import { fail } from '../store'
import Shelf from './Shelf.vue'

const emit = defineEmits(['open'])

const q = ref('')
const items = ref([])
const total = ref(0)
const page = ref(1)
const searched = ref(false)
const input = ref(null)
let timer = 0
let seq = 0
let busy = false

async function run(more = false) {
  const text = q.value.trim()
  const mine = ++seq
  if (!text) {
    items.value = []
    total.value = 0
    searched.value = false
    return
  }
  const p = more ? page.value + 1 : 1
  try {
    const r = await api.cards({ q: text, page: p, page_size: 60 })
    if (mine !== seq) return
    items.value = more ? items.value.concat(r.items) : r.items
    total.value = r.total
    page.value = p
    searched.value = true
  } catch (e) {
    fail(e)
  }
}

async function more() {
  if (busy || items.value.length >= total.value) return
  busy = true
  try { await run(true) } finally { busy = false }
}

watch(q, () => {
  clearTimeout(timer)
  timer = setTimeout(() => run(), 250)
})
onMounted(() => input.value?.focus())
</script>

<template>
  <section class="search">
    <label class="searchbox">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><circle cx="11" cy="11" r="7" /><path d="M20 20l-4-4" /></svg>
      <input ref="input" v-model="q" type="search" placeholder="名字、作者、标签、简介、开场白" autocomplete="off" spellcheck="false">
    </label>
    <p v-if="searched" class="found">共找到 <b>{{ total }}</b> 张</p>
    <Shelf v-if="searched" :items="items" empty="没有找到匹配的卡。" @open="(...a) => emit('open', ...a)" @more="more" />
  </section>
</template>

<style>
.search{padding-top:clamp(30px,4.5vh,56px)}
.searchbox{display:flex;align-items:center;gap:14px;width:min(620px,calc(100% - var(--pad)*2));margin:0 auto;padding:10px 4px;
  border-bottom:1px solid rgba(233,237,242,.25);color:var(--dim);transition:border-color .3s,color .3s}
.searchbox:focus-within{border-color:color-mix(in srgb,var(--theme) 70%,transparent);color:var(--silver)}
.searchbox input{flex:1;min-width:0;background:none;border:0;outline:0;color:var(--silver);font-family:var(--show);font-size:22px;letter-spacing:.12em}
.searchbox input::placeholder{color:var(--dim);font-size:16px;letter-spacing:.1em}
.searchbox input::-webkit-search-cancel-button{display:none}
.found{text-align:center;margin-top:18px;font-size:13px;color:var(--dim);letter-spacing:.1em}
.found b{font-family:var(--latin);font-weight:400;font-size:18px;color:var(--silver);margin:0 4px}
</style>
