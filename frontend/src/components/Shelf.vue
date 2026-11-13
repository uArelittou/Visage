<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { ambOff, ambOn } from '../lib/ambient'
import CardFace from './CardFace.vue'

defineProps({
  items: { type: Array, required: true },
  phase: { type: String, default: '' },
  empty: { type: String, default: '这个分类里还没有卡。' },
})
const emit = defineEmits(['open', 'more'])

const sentinel = ref(null)
let io = null

onMounted(() => {
  io = new IntersectionObserver((es) => { if (es.some((e) => e.isIntersecting)) emit('more') }, { rootMargin: '600px 0px' })
  io.observe(sentinel.value)
})
onBeforeUnmount(() => io?.disconnect())
</script>

<template>
  <main class="shelf" :class="phase">
    <button
      v-for="(item, k) in items" :key="item.id" class="cell" :data-id="item.id" :style="{ '--k': Math.min(k, 14) }"
      :aria-label="item.name"
      @click="emit('open', item, k, $event.currentTarget)"
      @pointerenter="ambOn(item)" @pointerleave="ambOff" @focus="ambOn(item)" @blur="ambOff"
    >
      <CardFace :item="item" :index="k" />
      <span class="nm">{{ item.name }}</span>
    </button>
    <p v-if="!items.length" class="none">{{ empty }}</p>
    <div ref="sentinel" class="sentinel"></div>
  </main>
</template>

<style>
@keyframes rise{from{opacity:0;transform:translateY(22px)}}
.shelf{width:var(--wrap);margin:0 auto;padding:clamp(30px,4.5vh,56px) var(--pad) 110px;
  display:grid;grid-template-columns:repeat(5,minmax(0,1fr));
  column-gap:clamp(20px,2.6vw,52px);row-gap:clamp(30px,4.2vw,68px);
  transition:opacity .22s ease,transform .22s ease}
.shelf.out{opacity:0;transform:translateY(10px)}
.shelf.enter .cell{animation:rise .7s cubic-bezier(.2,.8,.2,1) backwards;animation-delay:calc(var(--k)*30ms)}
.shelf .none{grid-column:1/-1;text-align:center;color:var(--dim);font-family:var(--show);letter-spacing:.2em;padding:60px 0}
.shelf .sentinel{grid-column:1/-1;height:1px}
.cell{display:block;text-align:center;width:100%}
.cell:focus-visible{outline:none}
.cell .nm{display:block;margin-top:clamp(12px,1.1vw,18px);font-family:var(--show);font-size:clamp(15px,1.12vw,20px);
  letter-spacing:.14em;padding-left:.14em;color:#a9b2be;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;transition:color .3s,text-shadow .3s}
.cell:hover .nm,.cell:focus-visible .nm{color:var(--silver);text-shadow:0 0 14px color-mix(in srgb,var(--theme) 70%,transparent)}
.cell:hover .art img{filter:brightness(1.07) saturate(1.06)}
.cell:hover .art{box-shadow:calc(var(--ry)*-1.1px) calc(var(--rx)*1.1px + 14px) 26px -10px rgba(0,0,0,.85),0 0 0 1px rgba(255,255,255,.04),
  0 0 42px -12px var(--theme)}
.cell:hover .frame,.cell:focus-visible .frame{opacity:.7}
.cell:hover .no,.cell:focus-visible .no{opacity:.9}
.cell:focus-visible .card{--s:1.03}

@media (max-width:1100px){.shelf{grid-template-columns:repeat(4,minmax(0,1fr))}}
@media (max-width:860px){.shelf{grid-template-columns:repeat(3,minmax(0,1fr))}}
@media (max-width:560px){.shelf{grid-template-columns:repeat(2,minmax(0,1fr))}}
</style>
