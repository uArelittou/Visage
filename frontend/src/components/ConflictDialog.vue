<script setup>
import { ref, watch } from 'vue'
import { fail, reloadDetail, store, toast } from '../store'

const dlg = ref(null)
const busy = ref(false)

watch(() => store.conflict, (c) => {
  const d = dlg.value
  if (c && !d.open) d.showModal()
  else if (!c && d.open) d.close()
})

const dismiss = () => { store.conflict = null }

async function reload() {
  busy.value = true
  try {
    await reloadDetail()
    store.conflict = null
    toast('已读取磁盘上的最新内容，你没存的修改还在')
  } catch (e) {
    store.conflict = null
    fail(e)
  } finally {
    busy.value = false
  }
}

async function overwrite() {
  const retry = store.conflict?.retry
  if (!retry) return
  busy.value = true
  store.conflict = null
  try { await retry() } finally { busy.value = false }
}
</script>

<template>
  <dialog ref="dlg" class="gate conflict" @close="dismiss">
    <div class="gate-in one">
      <div>
        <h3>The File Has Changed</h3>
        <p class="sub">{{ store.conflict?.reason === 'missing' ? '这张卡的文件已经不在了' : '这张卡在你打开之后被别的程序改过了' }}</p>
        <p class="hint">
          {{ store.conflict?.retry ? '可以先读取最新内容再改，或者用你这一份覆盖磁盘上的版本。覆盖前，原文件会自动备份。' : '文件不存在，无法保存。' }}
        </p>
        <div class="ways">
          <button v-if="store.conflict?.retry" class="way main" :disabled="busy" @click="reload">读取最新内容</button>
          <button v-if="store.conflict?.retry" class="way" :disabled="busy" @click="overwrite">用我的版本覆盖</button>
          <button class="way" :disabled="busy" @click="dlg.close()">取消</button>
        </div>
      </div>
    </div>
  </dialog>
</template>

<style>
dialog.conflict{max-width:min(620px,92vw)}
.gate-in.one{grid-template-columns:1fr;text-align:center}
.conflict .ways{justify-content:center}
.conflict h3{font-size:clamp(24px,2.4vw,34px)}
.conflict .way:disabled{opacity:.5}
</style>
