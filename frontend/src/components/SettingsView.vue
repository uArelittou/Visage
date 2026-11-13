<script setup>
import { onBeforeUnmount, onMounted, reactive, watch } from 'vue'
import { api } from '../lib/api'
import { fail, loadCats, loadItems, scheduleRefresh, store, toast } from '../store'

const lib = reactive({ busy: false, count: store.lib?.card_count ?? 0, sources: [] })
const armed = reactive({ clear: false, source: '' })
let armTimer = 0
const rating = reactive({ base_url: '', model: '', api_key: '', api_key_set: false, masked: '', configured: false, missing: [], busy: false })

async function refreshLib() {
  const [info, src] = await Promise.all([api.library(), api.sources()])
  store.lib = info
  lib.count = info.card_count
  lib.sources = src.sources
}

async function rescan() {
  if (lib.busy) return
  lib.busy = true
  try {
    const r = await api.scan()
    scheduleRefresh()
    await refreshLib()
    toast(`扫描完成：新增 ${r.scan.added}，更新 ${r.scan.updated}，移除 ${r.scan.removed}`)
  } catch (e) {
    fail(e)
  } finally {
    lib.busy = false
  }
}

// 「点一下变确认，3 秒复原」：清空卡库和移除来源共用一个计时器，同时只会有一个处于待确认
function arm(which, source = '') {
  armed.clear = which === 'clear'
  armed.source = which === 'source' ? source : ''
  clearTimeout(armTimer)
  armTimer = setTimeout(() => { armed.clear = false; armed.source = '' }, 3000)
}
function disarm() {
  clearTimeout(armTimer)
  armed.clear = false
  armed.source = ''
}
onBeforeUnmount(() => clearTimeout(armTimer))

async function clearAll() {
  if (lib.busy) return
  if (!armed.clear) return arm('clear')
  disarm()
  lib.busy = true
  try {
    await api.clearLibrary()
    await Promise.all([loadCats(), loadItems(), refreshLib()])
    toast('卡库已清空。点「重新扫描」按来源重建')
  } catch (e) {
    fail(e)
  } finally {
    lib.busy = false
  }
}

async function removeSource(s) {
  if (lib.busy) return
  if (armed.source !== s.path) return arm('source', s.path)
  disarm()
  lib.busy = true
  try {
    await api.removeSource(s.path)
    await Promise.all([loadCats(), loadItems(), refreshLib()])
    toast('已移出来源，文件没有动')
  } catch (e) {
    fail(e)
  } finally {
    lib.busy = false
  }
}

function fillRating(s) {
  rating.base_url = s.base_url
  rating.model = s.model
  rating.api_key = ''
  rating.api_key_set = s.api_key_set
  rating.masked = s.api_key
  rating.configured = s.configured
  rating.missing = s.missing
}

async function saveRating(clearKey = false) {
  if (rating.busy) return
  rating.busy = true
  const body = { base_url: rating.base_url.trim(), model: rating.model.trim() }
  if (clearKey) body.api_key = ''
  else if (rating.api_key) body.api_key = rating.api_key
  try {
    fillRating(await api.saveRatingSettings(body))
    toast('评分模型设置已保存')
  } catch (e) {
    fail(e)
  } finally {
    rating.busy = false
  }
}

watch(() => store.sourcesVersion, () => refreshLib().catch(fail))

onMounted(async () => {
  try {
    await refreshLib()
    fillRating(await api.ratingSettings())
  } catch (e) {
    fail(e)
  }
})

defineExpose({ refreshLib })
</script>

<template>
  <section class="settings">
    <h3 class="sg">卡库</h3>
    <div class="sbox">
      <p class="sline">当前共 <b>{{ lib.count }}</b> 张{{ store.lib?.last_scan ? `，上次扫描用时 ${store.lib.last_scan.duration} 秒` : '' }}。</p>
      <ul class="srcs">
        <li v-for="s in lib.sources" :key="s.path" :class="{ gone: s.missing }">
          <svg v-if="s.kind === 'folder'" viewBox="0 0 24 24" aria-hidden="true"><path d="M3 6.5h6.2l2 2.3H21V19H3z" /></svg>
          <svg v-else viewBox="0 0 24 24" aria-hidden="true"><path d="M6 3h8l4 4v14H6zM14 3v4h4" /></svg>
          <div class="sp"><b>{{ s.name }}</b><span :title="s.path">{{ s.path }}</span></div>
          <em>{{ s.missing ? '找不到' : `${s.count} 张` }}</em>
          <button class="bin" :class="{ armed: armed.source === s.path }" :aria-label="`移除来源 ${s.name}`" :disabled="lib.busy" @click="removeSource(s)">
            <svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6 6 18" /></svg><span>确认移除</span>
          </button>
        </li>
        <li v-if="!lib.sources.length" class="none">还没有来源。</li>
      </ul>
      <div class="sacts">
        <button class="tool sm" :disabled="lib.busy || !lib.sources.length" @click="rescan">重新扫描</button>
        <button class="tool sm danger" :class="{ armed: armed.clear }" :disabled="lib.busy" @click="clearAll">{{ armed.clear ? '确认清空' : '清空卡库' }}</button>
      </div>
    </div>

    <h3 class="sg">评分模型</h3>
    <div class="sbox">
      <p class="sline">兼容 OpenAI 接口的服务都可以。{{ rating.configured ? '已配置完整。' : rating.missing.length ? `还缺：${rating.missing.join('、')}。` : '' }}</p>
      <label class="ef"><span>接口地址 base_url</span><input v-model="rating.base_url" class="in" placeholder="https://api.openai.com/v1" spellcheck="false"></label>
      <label class="ef"><span>模型名</span><input v-model="rating.model" class="in" spellcheck="false"></label>
      <label class="ef"><span>密钥{{ rating.api_key_set ? `（已设置 ${rating.masked}，留空则不改）` : '' }}</span>
        <input v-model="rating.api_key" class="in" type="password" autocomplete="off" spellcheck="false">
      </label>
      <div class="sacts">
        <button v-if="rating.api_key_set" class="tool sm" :disabled="rating.busy" @click="saveRating(true)">清除密钥</button>
        <button class="tool sm main" :disabled="rating.busy" @click="saveRating()">保存</button>
      </div>
    </div>
  </section>
</template>

<style>
.settings{width:min(680px,calc(100% - var(--pad)*2));margin:0 auto;padding:clamp(30px,4.5vh,56px) 0 110px}
.sg{text-align:center;font-family:var(--show);font-weight:400;font-size:17px;letter-spacing:.3em;color:var(--dim);margin:40px 0 18px}
.sg:first-child{margin-top:0}
.sbox{display:grid;gap:16px;padding:24px;background:var(--panel);border:1px solid var(--line)}
.sbox .ef{display:grid;gap:5px;font-size:12px;color:var(--dim);letter-spacing:.08em}
.sline{font-size:13px;color:var(--dim);line-height:1.8}
.sline b{font-family:var(--latin);font-weight:400;font-size:16px;color:var(--silver);margin:0 3px}
.sacts{display:flex;justify-content:flex-end;gap:10px}
.srcs{list-style:none;display:grid;gap:2px}
.srcs li{display:flex;align-items:center;gap:12px;padding:9px 4px;border-bottom:1px solid var(--line)}
.srcs li.none{justify-content:center;color:var(--dim);font-size:13px;border:0}
.srcs li>svg{flex:none;width:18px;height:18px;fill:none;stroke:var(--dim);stroke-width:1.4;stroke-linejoin:round}
.srcs .sp{flex:1;min-width:0;display:grid}
.srcs .sp b{font-weight:400;font-family:var(--show);font-size:16px;letter-spacing:.08em;color:var(--silver)}
.srcs .sp span{font-size:12px;color:var(--dim);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;direction:rtl;text-align:left}
.srcs em{font-style:normal;font-family:var(--latin);font-size:12px;letter-spacing:.1em;color:var(--dim)}
.srcs li.gone em{color:var(--danger);font-family:inherit}
.srcs .bin{display:inline-flex}
.tool.danger.armed{color:var(--danger);border-color:var(--danger)}
</style>
