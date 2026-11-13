<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { vTilt } from '../lib/tilt'
import { addSources, hasNative, pickFilesAndAdd, pickFolderAndAdd, store, toast } from '../store'

const gate = ref(null)
const dropOn = ref(false)
const native = ref(hasNative())
const typed = ref('')
const busy = ref(false)
let dragN = 0

watch(() => store.gate, (on) => {
  const d = gate.value
  if (on) {
    native.value = hasNative()
    if (!d.open) d.showModal()
  } else if (d.open) d.close()
})

async function run(job) {
  if (busy.value) return
  busy.value = true
  try {
    if (await job()) store.gate = false
  } finally {
    busy.value = false
  }
}

const pickFolder = () => run(pickFolderAndAdd)
const pickFiles = () => run(pickFilesAndAdd)
const addTyped = () => run(async () => {
  const ok = await addSources([typed.value])
  if (ok) typed.value = ''
  return ok
})

// 拖放：pywebview 里完整路径由 app.py 的 Python 端取到后经 window.__qmlDropped 交给 store；
// 浏览器里 File 对象拿不到路径，只能提示。这里只负责拖入时的遮罩。
const onEnter = (e) => {
  if (!e.dataTransfer?.types.includes('Files')) return
  e.preventDefault()
  dragN++
  dropOn.value = true
}
const onOver = (e) => { if (dragN) e.preventDefault() }
const onLeave = () => { if (dragN && --dragN === 0) dropOn.value = false }
const onDrop = (e) => {
  e.preventDefault()
  dragN = 0
  dropOn.value = false
  store.gate = false
  if (!hasNative() && e.dataTransfer.files.length) toast('浏览器里拿不到文件路径，请在收录窗口输入路径')
}

onMounted(() => {
  addEventListener('dragenter', onEnter)
  addEventListener('dragover', onOver)
  addEventListener('dragleave', onLeave)
  addEventListener('drop', onDrop)
})
onBeforeUnmount(() => {
  removeEventListener('dragenter', onEnter)
  removeEventListener('dragover', onOver)
  removeEventListener('dragleave', onLeave)
  removeEventListener('drop', onDrop)
})
</script>

<template>
  <dialog ref="gate" class="gate" @close="store.gate = false" @click="$event.target === gate && gate.close()">
    <div class="gate-in">
      <button class="x" aria-label="关闭" @click="gate.close()">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18" /></svg>
      </button>
      <div v-tilt class="tilt slot" :class="{ pick: native }" :role="native ? 'button' : null" :tabindex="native ? 0 : null"
        :aria-label="native ? '选择卡片' : null" @click="native && pickFiles()" @keydown.enter.space.prevent="native && pickFiles()">
        <div class="card">
          <div class="art"><div class="rim"></div></div>
          <div class="frame"></div>
          <div class="sigil"><svg class="seal" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path class="rim" d="M12 1.5 22.5 12 12 22.5 1.5 12Z" /><path class="cross" d="M12 7.5v9M7.5 12h9" /><circle class="dot" cx="12" cy="12" r="1.3" /></svg></div>
        </div>
      </div>
      <div>
        <h3>Inscribe a New Face</h3>
        <p class="sub">把新面孔收入千面录</p>
        <p class="fmt">PNG · WEBP · JSON</p>
        <div v-if="native" class="ways">
          <button class="way main" :disabled="busy" @click="pickFolder">选择文件夹</button>
          <button class="way" :disabled="busy" @click="pickFiles">选择卡片</button>
        </div>
        <form v-else class="ways typed" @submit.prevent="addTyped">
          <input v-model="typed" class="in" placeholder="文件夹或卡片的完整路径，例如 D:\SillyTavern\角色卡" spellcheck="false" autocomplete="off">
          <button class="way main" :disabled="busy || !typed.trim()">添加</button>
        </form>
        <p v-if="native" class="hint">或者...把文件夹或者角色卡拖进来看看吧~</p>
      </div>
    </div>
    <!-- 弹窗在浏览器顶层，页面上的 ToastBar 会被遮住，所以弹窗里再放一份同样的提示 -->
    <div class="toast" :class="{ on: store.messageOn }" role="status" aria-live="polite">{{ store.message }}</div>
  </dialog>

  <div class="drop" :class="{ on: dropOn }" aria-hidden="true">
    <div class="drop-box gate">
      <div class="tilt slot">
        <div class="card">
          <div class="art"></div>
          <div class="sigil"><svg class="seal" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path class="rim" d="M12 1.5 22.5 12 12 22.5 1.5 12Z" /><path class="cross" d="M12 7.5v9M7.5 12h9" /><circle class="dot" cx="12" cy="12" r="1.3" /></svg></div>
        </div>
      </div>
      <h3>Inscribe a New Face</h3>
      <p class="sub">松开鼠标，收入千面录</p>
    </div>
  </div>
</template>

<style>
dialog.gate{margin:auto;border:0;padding:0;background:transparent;color:var(--text);max-width:min(860px,92vw);width:100%}
dialog.gate::backdrop{background:radial-gradient(circle at 50% 40%,rgba(18,12,32,.72),rgba(5,6,9,.92));backdrop-filter:blur(6px)}
.gate-in{position:relative;display:grid;grid-template-columns:minmax(150px,240px) 1fr;gap:clamp(24px,4vw,56px);align-items:center;
  padding:clamp(26px,4vw,52px);background:linear-gradient(180deg,rgba(32,37,47,.96),rgba(18,21,28,.96));border:1px solid rgba(233,237,242,.14);
  box-shadow:0 40px 80px -20px rgba(0,0,0,.8)}
.gate-in::before{content:"";position:absolute;inset:8px;border:1px solid rgba(233,237,242,.06);pointer-events:none}
.slot .art{display:grid;place-items:center;background:
  repeating-linear-gradient(135deg,rgba(255,255,255,.025) 0 8px,transparent 8px 16px),#10141a;
  outline:1px dashed rgba(233,237,242,.32);outline-offset:-10px}
.slot.pick{cursor:pointer}
.slot .sigil{position:absolute;inset:0;display:grid;place-items:center;transform:translateZ(40px);pointer-events:none}
.slot .sigil .seal{width:46%;height:auto;color:var(--silver);overflow:visible;
  filter:drop-shadow(0 0 8px rgba(166,140,255,.75)) drop-shadow(0 0 18px rgba(166,140,255,.35))}
.slot .sigil .rim{stroke-width:.6}
.slot .sigil .cross{stroke-width:.7}
.slot .sigil .dot{opacity:1}
.gate h3{font-family:"UnifrakturMaguntia",serif;font-weight:400;font-size:clamp(28px,3vw,42px);color:#e6e9ee;
  text-shadow:0 0 10px rgba(75,51,145,.9),0 0 26px rgba(75,51,145,.5)}
.gate .sub{font-family:var(--show);font-size:clamp(17px,1.4vw,20px);letter-spacing:.2em;color:#c7ced8;margin-top:10px}
.gate .fmt{font-family:var(--latin);font-weight:700;font-size:10px;letter-spacing:.38em;color:var(--dim);margin-top:18px}
.gate .ways{display:flex;flex-wrap:wrap;gap:14px;margin-top:30px}
.way{font-family:var(--show);font-size:17px;letter-spacing:.2em;padding:12px 26px;border:1px solid rgba(233,237,242,.25);color:#e4e8ed;transition:all .3s}
.way.main{background:linear-gradient(180deg,#e9edf2,#a9b1bc);color:#151920;border-color:transparent}
.way:disabled{opacity:.5}
.ways.typed{flex-wrap:nowrap;align-items:stretch}
.ways.typed .in{flex:1;min-width:0}
.way:hover:not(:disabled){border-color:rgba(166,140,255,.8);box-shadow:0 0 20px -2px rgba(166,140,255,.5)}
.way.main:hover{filter:brightness(1.08)}
.gate .hint{margin-top:22px;font-size:13px;color:var(--dim)}
.gate .x{position:absolute;right:14px;top:12px;width:34px;height:34px;display:grid;place-items:center;color:var(--dim)}
.gate .x svg{width:18px;height:18px}
.gate .x:hover{color:var(--silver)}

.drop{position:fixed;inset:0;z-index:50;display:grid;place-items:center;pointer-events:none;opacity:0;transition:opacity .25s;
  background:radial-gradient(circle at 50% 45%,rgba(34,22,64,.7),rgba(5,6,9,.92))}
.drop.on{opacity:1}
.drop-box{width:min(320px,52vw);text-align:center}
.drop .slot{width:62%;margin:0 auto 26px;animation:float 3s ease-in-out infinite}
@keyframes float{50%{transform:translateY(-10px)}}

@media (max-width:860px){
  .gate-in{grid-template-columns:1fr;text-align:center}
  .gate-in .slot{width:150px;margin:0 auto}
  .gate .ways{justify-content:center}
}
</style>
