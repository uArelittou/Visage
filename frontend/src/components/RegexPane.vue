<script setup>
import { computed, ref } from 'vue'
import { PLACEMENTS, regexPlaceText, runRegex, SCOPES } from '../lib/lore'
import { addRow, arm, cancelRow, field, rowTap, saveRow, setField, togglePlace } from '../lib/rowActions'
import { store } from '../store'

const rows = computed(() => store.rows.rx)
const sample = ref('<thinking>这段会被去掉</thinking>雨还在下。')
const result = computed(() => {
  const list = rows.value.filter((r) => !r.isNew).map((r) => r.src)
  return runRegex(list, sample.value)
})

const cls = (r) => [r.v.on ? '' : 'off', r.open ? 'open' : '', r.draft ? 'dirty' : '', r.isNew ? 'fresh' : ''].join(' ')
const scopeName = (v) => SCOPES.find((s) => s[0] === v)?.[1]
const text = (r, k, e) => setField(r, k, e.target.value)
</script>

<template>
  <ul class="lore rx">
    <li v-for="r in rows" :key="r.uid" :class="cls(r)" :data-uid="r.uid" @click="rowTap($event, r)">
      <div class="lh">
        <b v-if="r.v.n">{{ r.v.n }}</b><b v-else class="nn">未命名</b>
        <span class="tk">{{ regexPlaceText(r.v.place) }}</span><span class="uns">未保存</span><span class="sp"></span>
        <span class="tg">{{ scopeName(r.v.scope) }}</span>
        <span v-if="!r.v.on" class="tg">未启用</span>
        <button class="bin" aria-label="删除" :class="{ armed: r.armed }" @click="arm($event, r, 'rx')">
          <svg viewBox="0 0 24 24"><path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13M10 11v6M14 11v6" /></svg><span>确认删除</span>
        </button>
      </div>
      <div class="lb">
        <div class="lf">
          <label class="ef w2"><span>名字</span><input class="in" :value="field(r).n" @input="text(r, 'n', $event)"></label>
          <label class="ef w2"><span>处理方式</span>
            <select class="in" :value="field(r).scope" @change="setField(r, 'scope', $event.target.value)">
              <option v-for="[k, label] in SCOPES" :key="k" :value="k">{{ label }}</option>
            </select>
          </label>
          <div class="row full">
            <label class="ck"><span class="sw"><input type="checkbox" :checked="field(r).on" @change="setField(r, 'on', $event.target.checked)"><i></i></span>启用</label>
            <label v-for="[p, label] in PLACEMENTS" :key="p" class="ck">
              <input type="checkbox" :checked="field(r).place.includes(p)" @change="togglePlace(r, p, $event.target.checked)">{{ label }}
            </label>
          </div>
          <label class="ef full"><span>查找</span><input class="in mono" :value="field(r).find" @input="text(r, 'find', $event)"></label>
          <label class="ef full"><span>替换成，留空就是删掉</span><textarea class="in mono" rows="3" :value="field(r).repl" @input="text(r, 'repl', $event)"></textarea></label>
        </div>
        <div class="acts">
          <button class="tool sm" @click="cancelRow('rx', r)">取消</button>
          <button class="tool sm main" :disabled="r.saving" @click="saveRow('rx', r)">保存</button>
        </div>
      </div>
    </li>
  </ul>
  <button class="add" @click="addRow('rx')">
    <svg viewBox="0 0 24 24"><path d="M12 1.5 22.5 12 12 22.5 1.5 12Z" /><path d="M12 7.5v9M7.5 12h9" /></svg>添加正则
  </button>
  <div class="try">
    <label for="tx">输入一段文字，看已保存的正则处理后的样子</label>
    <textarea id="tx" v-model="sample"></textarea>
    <pre v-if="result !== null">{{ result }}</pre>
    <pre v-else>有一条正则写得不对，没法运行。</pre>
  </div>
</template>
