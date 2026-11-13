<script setup>
import { computed, ref } from 'vue'
import { setUserTotal, startAiRating, store, toast } from '../store'

const r = computed(() => store.rating)
const result = computed(() => r.value?.result)
const dims = computed(() => Object.values(result.value?.dimensions || {}))
const running = computed(() => store.ratingJob?.state === 'running')
const notConfigured = computed(() => /未配置/.test(store.ratingError))

const editing = ref(false)
const busy = ref(false)
const val = ref('')

function edit() {
  val.value = r.value?.display_score != null ? String(r.value.display_score) : ''
  editing.value = true
}

async function save() {
  const text = val.value.trim()
  let total = null
  if (text) {
    total = Number(text)
    if (!Number.isFinite(total) || total < 0 || total > 10) {
      toast('总分要写 0～10 之间的数字')
      return
    }
  }
  if (total === null && r.value?.user_total == null) {
    editing.value = false
    return
  }
  busy.value = true
  if (await setUserTotal(total)) editing.value = false
  busy.value = false
}

const goSettings = () => dispatchEvent(new CustomEvent('qml:settings'))
</script>

<template>
  <div class="pbar">
    <template v-if="editing">
      <button class="tool main" :disabled="busy" @click="save">保存</button>
      <button class="tool" :disabled="busy" @click="editing = false">取消</button>
    </template>
    <template v-else>
      <button class="tool" @click="edit">
        <svg viewBox="0 0 24 24"><path d="M4 20h4L19 9l-4-4L4 16z" /><path d="M13.5 6.5l4 4" /></svg>编辑
      </button>
      <button class="tool" :disabled="running" @click="startAiRating">{{ running ? '评分中…' : r?.has_ai ? '重新评分' : '开始评分' }}</button>
    </template>
  </div>
  <div class="verdict">
    <template v-if="editing">
      <input v-model="val" class="in" inputmode="decimal" @keydown.enter="save">
      <p class="by">改总分，0～10　<button v-if="r?.has_ai" @click="val = ''">恢复 AI 分</button></p>
    </template>
    <template v-else-if="r?.display_score != null">
      <div class="big">{{ r.display_score }}</div>
      <p v-if="r.user_total == null" class="by">AI 评分</p>
    </template>
    <p v-else class="noscore">还没有评分</p>
  </div>
  <p v-if="store.ratingError" class="rerr">
    {{ store.ratingError }}<button v-if="notConfigured" @click="goSettings">去设置</button>
  </p>
  <blockquote v-if="result?.review" class="review">{{ result.review }}</blockquote>
  <ul v-if="dims.length" class="items">
    <li v-for="d in dims" :key="d.name" :class="{ na: !d.applicable }">
      <span>{{ d.name }}</span>
      <i :style="{ '--v': d.applicable ? d.score * 10 + '%' : '0%' }"></i>
      <b>{{ d.applicable ? d.score : '—' }}</b>
    </li>
  </ul>
</template>
