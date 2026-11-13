<script setup>
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { coverTheme } from './lib/color'
import { closeFlight, isBusy, openFlight } from './lib/flight'
import { bootstrap, closeDetailData, fail, loadDetail, store } from './store'
import Ambient from './components/Ambient.vue'
import ConflictDialog from './components/ConflictDialog.vue'
import DetailView from './components/DetailView.vue'
import HomeView from './components/HomeView.vue'
import ImportGate from './components/ImportGate.vue'
import LibraryPicker from './components/LibraryPicker.vue'
import Starfield from './components/Starfield.vue'
import ToastBar from './components/ToastBar.vue'

const detail = ref(null)
let opening = false

async function openCard(item, index, cell) {
  if (opening || isBusy()) return
  opening = true
  try {
    await loadDetail(item, index)
    await nextTick()
    const theme = await Promise.race([coverTheme(item), new Promise((r) => setTimeout(() => r(null), 250))])
    await openFlight(cell, theme, () => detail.value.layout())
    detail.value.$el.querySelector('.back')?.focus({ preventScroll: true })
  } catch (e) {
    closeDetailData()
    fail(e)
  } finally {
    opening = false
  }
}

async function closeCard() {
  if (!store.cur || isBusy()) return
  const cell = document.querySelector(`.cell[data-id="${store.cur.id}"]`)
  await closeFlight(cell)
  closeDetailData()
}

const onKey = (e) => {
  if (e.key !== 'Escape' || store.gate || store.conflict) return
  if (document.body.classList.contains('open')) closeCard()
  else if (store.view !== 'shelf') store.view = 'shelf'
}

async function toSettings() {
  await closeCard()
  store.view = 'settings'
}

onMounted(() => {
  addEventListener('keydown', onKey)
  addEventListener('qml:settings', toSettings)
  bootstrap()
})
onBeforeUnmount(() => {
  removeEventListener('keydown', onKey)
  removeEventListener('qml:settings', toSettings)
})
</script>

<template>
  <canvas id="sky" aria-hidden="true"></canvas>
  <Ambient />
  <canvas id="zodiac" aria-hidden="true"></canvas>
  <Starfield />

  <template v-if="store.boot === 'ready'">
    <HomeView @open="openCard" />
    <DetailView ref="detail" @close="closeCard" />
  </template>
  <LibraryPicker v-else-if="store.boot === 'picker'" />
  <ImportGate />
  <ConflictDialog />
  <ToastBar />
</template>
