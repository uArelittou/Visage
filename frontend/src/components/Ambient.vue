<script setup>
import { onMounted, ref } from 'vue'
import { attachAmbient } from '../lib/ambient'

const root = ref(null)
onMounted(() => attachAmbient([...root.value.querySelectorAll('i')]))
</script>

<template>
  <div ref="root" class="amb" aria-hidden="true"><i></i><i></i></div>
</template>

<style>
/* 星空：随机散星 + 随机浮现的黄道星座，画在 canvas 上 */
#sky{position:fixed;inset:0;width:100%;height:100%;z-index:0;pointer-events:none}
/* 星座单独一层，压在封面背景之上；封面亮起时整层慢慢淡出 */
#zodiac{position:fixed;inset:0;width:100%;height:100%;z-index:0;pointer-events:none;transition:opacity 1.4s ease}
body.amb-on #zodiac,body.open #zodiac{opacity:0}
/* 悬浮卡片时的封面背景：两层轮换做交叉淡入，慢慢放大 */
.amb{position:fixed;inset:0;z-index:0;pointer-events:none;overflow:hidden}
.amb i{position:absolute;inset:-6%;background-size:cover;background-position:center 30%;opacity:0;
  filter:blur(5px) saturate(1.1) brightness(.5);transition:opacity 1.1s ease;will-change:opacity,transform}
.amb i.on{opacity:.9}
.amb i.kb{animation:drift 16s cubic-bezier(.2,.6,.3,1) forwards}
@keyframes drift{from{transform:scale(1.04)}to{transform:scale(1.18) translateY(-1.5%)}}
/* 压暗四周和底部，卡和文字始终压得住背景 */
.amb::after{content:"";position:absolute;inset:0;
  background:radial-gradient(ellipse 80% 70% at 50% 45%,transparent 30%,rgba(6,7,10,.75) 100%),linear-gradient(180deg,rgba(6,7,10,.2),rgba(6,7,10,.55))}
/* 进详情页时不直接关掉：悬浮的封面背景留着，和详情页的模糊封面交叉淡入 */
.amb{transition:opacity .6s ease}
body.open .amb{opacity:0;transition:opacity .9s ease .1s}
body.open.closing .amb{opacity:1;transition:opacity .6s ease}
</style>
