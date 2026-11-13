<script setup>
import { computed, ref } from 'vue'
import { clone } from '../lib/lore'
import { applyScripts } from '../lib/scripts'
import { saveFields, store } from '../store'

const scripts = computed(() => store.detail.card.scripts)
const editing = ref(false)
const busy = ref(false)
const draft = ref([])

function edit() {
  draft.value = scripts.value.map((s, i) => ({ src: i, name: s.name || '', content: s.content || '' }))
  editing.value = true
}

const add = () => draft.value.push({ src: null, name: '', content: '' })
const remove = (j) => draft.value.splice(j, 1)

async function save() {
  const ext = applyScripts(clone(store.detail.card.extensions || {}), draft.value.map((s) => ({ ...s })))
  busy.value = true
  await saveFields({ extensions: ext }, () => { editing.value = false })
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
  <template v-if="editing">
    <div v-for="(s, j) in draft" :key="j" class="erow">
      <input v-model="s.name" class="in full" style="grid-column:1/3" placeholder="脚本名">
      <span></span>
      <button class="del" aria-label="删除" @click="remove(j)"><svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6 6 18" /></svg></button>
      <textarea v-model="s.content" class="in full mono" rows="6"></textarea>
    </div>
    <button class="add" @click="add">
      <svg viewBox="0 0 24 24"><path d="M12 1.5 22.5 12 12 22.5 1.5 12Z" /><path d="M12 7.5v9M7.5 12h9" /></svg>添加脚本
    </button>
  </template>
  <template v-else>
    <template v-for="(s, j) in scripts" :key="j">
      <p class="sname">{{ s.name }}{{ s.enabled === false ? '（未启用）' : '' }}</p>
      <pre>{{ s.content }}</pre>
      <div style="height:26px"></div>
    </template>
  </template>
</template>
