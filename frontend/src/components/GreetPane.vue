<script setup>
import { computed, ref } from 'vue'
import { saveFields, store } from '../store'

const card = computed(() => store.detail.card)
const list = computed(() => card.value.greetings.map((g) => g.text))
const editing = ref(false)
const busy = ref(false)
const draft = ref([])
const gi = ref(0)

const src = computed(() => (editing.value ? draft.value : list.value))
const n = computed(() => src.value.length)

function edit() {
  draft.value = list.value.slice()
  gi.value = Math.min(gi.value, Math.max(0, draft.value.length - 1))
  editing.value = true
}

function step(d) {
  gi.value = (gi.value + d + n.value) % n.value
}

function add() {
  draft.value.push('')
  gi.value = draft.value.length - 1
}

function remove() {
  draft.value.splice(gi.value, 1)
  gi.value = Math.max(0, gi.value - 1)
}

async function save() {
  const texts = draft.value.filter((t) => t.trim())
  const c = card.value
  const hadFirst = c.first_mes.trim() !== ''
  const next = hadFirst
    ? { first_mes: texts[0] ?? '', alternate_greetings: texts.slice(1) }
    : { first_mes: c.first_mes, alternate_greetings: texts }
  const changed = {}
  if (next.first_mes !== c.first_mes) changed.first_mes = next.first_mes
  if (JSON.stringify(next.alternate_greetings) !== JSON.stringify(c.alternate_greetings)) changed.alternate_greetings = next.alternate_greetings
  if (!Object.keys(changed).length) {
    editing.value = false
    return
  }
  busy.value = true
  await saveFields(changed, () => {
    editing.value = false
    gi.value = Math.max(0, Math.min(gi.value, store.detail.card.greetings.length - 1))
  })
  busy.value = false
}
</script>

<template>
  <div class="pbar">
    <template v-if="editing">
      <button class="tool main" :disabled="busy" @click="save">保存</button>
      <button class="tool" :disabled="busy" @click="editing = false">取消</button>
    </template>
    <button v-else class="tool" @click="edit">
      <svg viewBox="0 0 24 24"><path d="M4 20h4L19 9l-4-4L4 16z" /><path d="M13.5 6.5l4 4" /></svg>编辑
    </button>
  </div>
  <template v-if="!n">
    <button v-if="editing" class="add" @click="add">
      <svg viewBox="0 0 24 24"><path d="M12 1.5 22.5 12 12 22.5 1.5 12Z" /><path d="M12 7.5v9M7.5 12h9" /></svg>添加开场白
    </button>
    <p v-else class="empty">这张卡没有开场白。</p>
  </template>
  <template v-else>
    <textarea v-if="editing" v-model="draft[gi]" class="in big-in"></textarea>
    <p v-else class="passage">{{ list[gi] }}</p>
    <div class="turn">
      <span>第 {{ gi + 1 }} 段，共 {{ n }} 段</span>
      <template v-if="n > 1"><button @click="step(-1)">上一段</button><button @click="step(1)">下一段</button></template>
      <button v-if="editing" @click="remove">删除这段</button>
    </div>
    <button v-if="editing" class="add" @click="add">
      <svg viewBox="0 0 24 24"><path d="M12 1.5 22.5 12 12 22.5 1.5 12Z" /><path d="M12 7.5v9M7.5 12h9" /></svg>添加开场白
    </button>
  </template>
</template>
