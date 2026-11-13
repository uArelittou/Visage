<script setup>
import { store } from '../store'
</script>

<template>
  <div class="toast" :class="{ on: store.messageOn }" role="status" aria-live="polite">{{ store.message }}</div>
</template>

<style>
.toast{position:fixed;left:50%;bottom:34px;z-index:60;transform:translate(-50%,20px);opacity:0;pointer-events:none;max-width:min(720px,90vw);
  padding:12px 26px;font-family:var(--show);letter-spacing:.14em;color:var(--silver);background:rgba(20,24,31,.92);
  border:1px solid rgba(233,237,242,.2);transition:all .35s}
.toast.on{opacity:1;transform:translate(-50%,0)}
</style>
