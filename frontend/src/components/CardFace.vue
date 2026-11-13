<script setup>
import { computed, ref, watch } from 'vue'
import { hasCover, thumbUrl } from '../lib/api'
import { vTilt } from '../lib/tilt'

const props = defineProps({ item: { type: Object, required: true }, index: { type: Number, default: 0 } })

const broken = ref(false)
const showImg = computed(() => hasCover(props.item) && !broken.value)
const no = computed(() => String(props.index + 1).padStart(3, '0'))
const vertical = computed(() => /[\u3400-\u9fff]/.test(props.item.name))

watch(() => props.item.path, () => { broken.value = false })
</script>

<template>
  <div v-tilt class="tilt">
    <div class="card">
      <div class="art">
        <img v-if="showImg" :src="thumbUrl(item)" alt="" loading="lazy" @error="broken = true">
        <div v-else class="ph" :class="{ v: vertical }"><span>{{ item.name }}</span></div>
        <div class="rim"></div>
      </div>
      <div class="frame"></div>
      <div class="no">N° {{ no }}</div>
    </div>
  </div>
</template>

<style>
/* 3D 卡：.tilt 提供透视，.card 跟鼠标转。overflow:hidden 会压平 3D，所以只放在 .art 上 */
.tilt{perspective:1000px;container-type:inline-size}
.card{--rx:0;--ry:0;--s:1;--gx:50%;--gy:50%;--ga:0;position:relative;aspect-ratio:2/3;transform-style:preserve-3d;
  transform:rotateX(calc(var(--rx)*1deg)) rotateY(calc(var(--ry)*1deg)) scale(var(--s));
  transition:transform .75s cubic-bezier(.18,.9,.22,1);will-change:transform}
.card.live{transition:transform .12s ease-out}
.art{position:absolute;inset:0;overflow:hidden;border-radius:3px;background:#0c0f14;
  box-shadow:calc(var(--ry)*-1.1px) calc(var(--rx)*1.1px + 14px) 26px -10px rgba(0,0,0,.85),0 0 0 1px rgba(255,255,255,.04);
  transition:box-shadow .75s cubic-bezier(.18,.9,.22,1)}
.card.live .art{transition:box-shadow .12s ease-out}
.art img{width:100%;height:100%;object-fit:cover;display:block;
  /* 封面在框里反向平移，像隔着一层玻璃看到后面的画，比反光更有纵深 */
  transform:scale(calc(1 + var(--ga)*.07)) translate(calc(var(--ry)*-.25%),calc(var(--rx)*.25%));
  transition:transform .75s cubic-bezier(.18,.9,.22,1),filter .4s}
.card.live .art img{transition:transform .12s ease-out,filter .4s}
/* 没有封面的卡（JSON 或图片损坏）：深色底，名字竖排在中间 */
.art .ph{position:absolute;inset:0;display:grid;place-items:center;padding:12%;text-align:center;
  background:
    radial-gradient(120% 80% at 50% 0%,color-mix(in srgb,var(--theme-deep) 55%,transparent),transparent 70%),
    repeating-linear-gradient(135deg,rgba(255,255,255,.025) 0 8px,transparent 8px 16px),#10141a;
  transform:scale(calc(1 + var(--ga)*.07)) translate(calc(var(--ry)*-.25%),calc(var(--rx)*.25%));
  transition:transform .75s cubic-bezier(.18,.9,.22,1)}
.card.live .art .ph{transition:transform .12s ease-out}
.art .ph span{font-family:var(--show);font-size:9cqw;line-height:1.3;letter-spacing:.2em;color:#d9dee6;
  display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:5;overflow:hidden;word-break:break-all;
  text-shadow:0 0 12px color-mix(in srgb,var(--theme) 55%,transparent)}
.art .ph.v span{writing-mode:vertical-rl;-webkit-line-clamp:3;max-height:80%}
/* 边缘光：只亮离鼠标最近的那段边，颜色取自这张封面 */
.rim{position:absolute;inset:0;border-radius:3px;padding:1.5px;pointer-events:none;opacity:var(--ga);transition:opacity .5s;
  background:radial-gradient(circle at var(--gx) var(--gy),var(--theme) 0%,color-mix(in srgb,var(--theme) 45%,transparent) 22%,transparent 52%);
  -webkit-mask:linear-gradient(#000 0 0) content-box,linear-gradient(#000 0 0);-webkit-mask-composite:xor;mask-composite:exclude}
.card .frame{position:absolute;inset:5.5%;border:1px solid rgba(240,243,247,.55);pointer-events:none;
  opacity:0;transform:translateZ(18px);transition:opacity .45s}
.card .no{position:absolute;left:8%;top:5%;font-family:var(--latin);font-weight:700;font-size:6.4cqw;letter-spacing:.12em;color:#f2f4f7;
  text-shadow:0 1px 3px rgba(0,0,0,.8);opacity:0;transform:translateZ(34px);transition:opacity .45s;pointer-events:none}
</style>
