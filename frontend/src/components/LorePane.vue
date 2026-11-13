<script setup>
import { computed } from 'vue'
import { kfmt } from '../lib/format'
import { POS, ROLES } from '../lib/lore'
import { addRow, arm, cancelRow, field, rowTap, saveRow, setField } from '../lib/rowActions'
import { store } from '../store'

const rows = computed(() => store.rows.wb)

const summary = computed(() => {
  const on = rows.value.filter((r) => r.v.on)
  const constant = on.filter((r) => r.v.c).length
  return { total: rows.value.length, constant, trigger: on.length - constant, tokens: on.reduce((s, r) => s + r.v.tk, 0) }
})

const groups = computed(() => {
  const known = new Set(POS.map((p) => p[0]))
  return POS.map(([pos, key, label]) => {
    const list = rows.value.filter((r) => (known.has(r.v.pos) ? r.v.pos === pos : pos === 1))
    list.sort(pos === 4 ? (a, b) => b.v.depth - a.v.depth || a.v.order - b.v.order : (a, b) => a.v.order - b.v.order)
    return { pos, key, label, list }
  }).filter((g) => g.list.length)
})

const keywords = (v) => v.k.split(/[,，]/).map((s) => s.trim()).filter(Boolean)
const cls = (r) => [r.v.on ? '' : 'off', r.open ? 'open' : '', r.draft ? 'dirty' : '', r.isNew ? 'fresh' : ''].join(' ')
const num = (r, k, e) => setField(r, k, e.target.value)
</script>

<template>
  <p v-if="!rows.length" class="empty">这张卡没有世界书。</p>
  <div v-else class="wbsum">
    <span><b>{{ summary.total }}</b>条</span><span><b>{{ summary.constant }}</b>常驻</span>
    <span><b>{{ summary.trigger }}</b>触发</span><span><b>{{ kfmt(summary.tokens) }}</b>TOKENS</span>
  </div>
  <template v-for="g in groups" :key="g.key">
    <h4 class="wbgrp">{{ g.label }}<small>{{ g.list.length }}</small></h4>
    <ul class="lore">
      <li v-for="r in g.list" :key="r.uid" :class="cls(r)" :data-uid="r.uid" @click="rowTap($event, r)">
        <div class="lh">
          <i class="lamp" :class="r.v.c ? 'c' : 's'" :title="r.v.c ? '蓝灯常驻' : '绿灯触发'"></i>
          <b v-if="r.v.n">{{ r.v.n }}</b><b v-else class="nn">未命名</b>
          <span class="tk">{{ kfmt(r.v.tk) }}</span><span class="uns">未保存</span><span class="sp"></span>
          <span v-if="g.pos === 4" class="tg">深度<em>{{ r.v.depth }}</em> · {{ ROLES[r.v.role] ?? '系统' }}</span>
          <span class="tg">优先级<em>{{ r.v.order }}</em></span>
          <span v-if="!r.v.on" class="tg">未启用</span>
          <button class="bin" aria-label="删除" :class="{ armed: r.armed }" @click="arm($event, r, 'wb')">
            <svg viewBox="0 0 24 24"><path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13M10 11v6M14 11v6" /></svg><span>确认删除</span>
          </button>
        </div>
        <div class="kw">
          <span v-if="r.v.c">常驻，不用关键词</span>
          <template v-else-if="keywords(r.v).length"><span v-for="s in keywords(r.v)" :key="s">{{ s }}</span></template>
          <span v-else>还没有关键词</span>
        </div>
        <div class="lb">
          <div class="lf">
            <label class="ef w2"><span>条目名</span><input class="in" :value="field(r).n" @input="num(r, 'n', $event)"></label>
            <label class="ef w2"><span>触发关键词，逗号隔开</span><input class="in" :value="field(r).k" @input="num(r, 'k', $event)"></label>
            <label class="ef w2"><span>位置</span>
              <select class="in" :value="field(r).pos" @change="setField(r, 'pos', Number($event.target.value))">
                <option v-for="[p, , label] in POS" :key="p" :value="p">{{ label }}</option>
              </select>
            </label>
            <label class="ef"><span>深度（@D）</span><input class="in" type="number" min="0" :value="field(r).depth" @input="num(r, 'depth', $event)"></label>
            <label class="ef"><span>角色（@D）</span>
              <select class="in" :value="field(r).role" @change="setField(r, 'role', Number($event.target.value))">
                <option v-for="(name, i) in ROLES" :key="i" :value="i">{{ name }}</option>
              </select>
            </label>
            <label class="ef"><span>优先级 order</span><input class="in" type="number" :value="field(r).order" @input="num(r, 'order', $event)"></label>
            <div class="row w3">
              <label class="ck"><span class="sw"><input type="checkbox" :checked="field(r).on" @change="setField(r, 'on', $event.target.checked)"><i></i></span>启用</label>
              <label class="ck"><span class="sw"><input type="checkbox" :checked="field(r).c" @change="setField(r, 'c', $event.target.checked)"><i></i></span>蓝灯常驻</label>
              <label class="ck"><input type="checkbox" :checked="field(r).noIn" @change="setField(r, 'noIn', $event.target.checked)">禁止被递归激活</label>
              <label class="ck"><input type="checkbox" :checked="field(r).noOut" @change="setField(r, 'noOut', $event.target.checked)">禁止递归激活其他</label>
            </div>
            <textarea class="in lt full" rows="5" placeholder="内容" :value="field(r).t" @input="num(r, 't', $event)"></textarea>
          </div>
          <div class="acts">
            <button class="tool sm" @click="cancelRow('wb', r)">取消</button>
            <button class="tool sm main" :disabled="r.saving" @click="saveRow('wb', r)">保存</button>
          </div>
        </div>
      </li>
    </ul>
  </template>
  <button class="add" @click="addRow('wb')">
    <svg viewBox="0 0 24 24"><path d="M12 1.5 22.5 12 12 22.5 1.5 12Z" /><path d="M12 7.5v9M7.5 12h9" /></svg>添加条目
  </button>
</template>
