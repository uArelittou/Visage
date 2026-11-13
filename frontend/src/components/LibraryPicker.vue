<script setup>
import { ref } from 'vue'
import { addSources, hasNative, pickFolderAndAdd, store } from '../store'

const root = ref('')
const busy = ref(false)
const error = ref(store.pickerError)
const native = hasNative()

async function run(job) {
  if (busy.value) return
  busy.value = true
  error.value = ''
  try {
    await job()
  } catch (e) {
    error.value = e.message
  } finally {
    busy.value = false
  }
}

const pick = () => run(pickFolderAndAdd)
const openTyped = () => run(() => addSources([root.value]))
</script>

<template>
  <div class="home picker">
    <header class="masthead">
      <div class="title">
        <h1>千面录</h1>
        <div class="latin">The Codex <span>of</span> a Thousand Faces</div>
        <div class="orn"><i></i><b>MMXXVI</b><i></i></div>
      </div>
    </header>
    <section class="pick-box">
      <p class="pick-sub">选择存放角色卡的文件夹</p>
      <p class="pick-hint">里面的 PNG、WebP、JSON 卡会在原位置建立索引，不移动也不复制。之后还可以随时加入更多文件夹或单张卡。</p>
      <template v-if="native">
        <p v-if="error" class="pick-err">{{ error }}</p>
        <p v-if="busy" class="pick-hint">正在建立索引，卡多的话要等一会儿…</p>
        <button class="tool main" :disabled="busy" @click="pick">{{ busy ? '处理中…' : '选择文件夹' }}</button>
      </template>
      <template v-else>
        <input v-model="root" class="in" placeholder="例如 D:\SillyTavern\角色卡" spellcheck="false" autofocus @keydown.enter="openTyped">
        <p v-if="error" class="pick-err">{{ error }}</p>
        <p v-if="busy" class="pick-hint">正在建立索引，卡多的话要等一会儿…</p>
        <button class="tool main" :disabled="busy || !root.trim()" @click="openTyped">{{ busy ? '处理中…' : '打开卡库' }}</button>
      </template>
    </section>
  </div>
</template>

<style>
.pick-box{width:min(560px,calc(100% - var(--pad)*2));margin:0 auto;padding:12px 0 100px;display:grid;gap:16px;justify-items:center;text-align:center}
.pick-sub{font-family:var(--show);font-size:20px;letter-spacing:.2em;color:#c7ced8}
.pick-hint{font-size:13px;color:var(--dim);line-height:1.8}
.pick-err{font-size:13px;color:var(--danger)}
.pick-box .in{text-align:center}
</style>
