<script setup>
import { computed, reactive, ref } from 'vue'
import { saveFields, store } from '../store'

const FIELDS = [
  ['description', '描述'], ['personality', '性格'], ['scenario', '场景'], ['mes_example', '示例对话'],
  ['system_prompt', '系统提示'], ['post_history_instructions', '后置指令'],
]

const card = computed(() => store.detail.card)
const editing = ref(false)
const busy = ref(false)
const draft = reactive({})

const visible = computed(() => FIELDS.filter(([k]) => editing.value || card.value[k].trim()))

function edit() {
  for (const [k] of FIELDS) draft[k] = card.value[k]
  editing.value = true
}

async function save() {
  const changed = {}
  for (const [k] of FIELDS) if (draft[k] !== card.value[k]) changed[k] = draft[k]
  if (!Object.keys(changed).length) {
    editing.value = false
    return
  }
  busy.value = true
  await saveFields(changed, () => { editing.value = false })
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
  <p v-if="!visible.length" class="empty">这张卡没有人设内容。</p>
  <dl v-else class="fields">
    <div v-for="[k, label] in visible" :key="k">
      <dt>{{ label }}</dt>
      <dd>
        <textarea v-if="editing" v-model="draft[k]" class="in" rows="4"></textarea>
        <template v-else>{{ card[k] }}</template>
      </dd>
    </div>
  </dl>
</template>
