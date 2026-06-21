<template>
  <section class="content-panel">
    <div class="section-header">
      <div>
        <h1>{{ title }}</h1>
        <p>M4 开放完整管理功能</p>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed } from "vue";
import { useRoute } from "vue-router";

const route = useRoute();
const title = computed(() => String(route.meta.title ?? "管理"));
</script>
