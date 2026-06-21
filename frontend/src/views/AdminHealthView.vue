<template>
  <section class="content-panel">
    <div class="section-header">
      <div>
        <h1>健康状态</h1>
        <p>组件可用性检查</p>
      </div>
      <el-button :loading="loading" @click="loadHealth">刷新</el-button>
    </div>

    <el-alert v-if="errorMessage" :title="errorMessage" type="error" show-icon />
    <el-skeleton v-if="loading" :rows="5" animated />
    <div v-else class="health-grid">
      <article v-for="item in components" :key="item.component" class="health-card">
        <div>
          <span>{{ componentLabel(item.component) }}</span>
          <el-tag :type="healthStatusTag(item.status)" effect="plain">
            {{ statusLabel(item.status) }}
          </el-tag>
        </div>
        <p>{{ item.detail }}</p>
      </article>
    </div>
    <el-empty v-if="!loading && !components.length" description="暂无健康状态" />
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from "vue";

import { apiClient } from "@/api/client";
import { extractErrorMessage } from "@/utils/errors";
import { healthStatusTag } from "@/utils/status";

interface HealthComponent {
  component: string;
  status: "healthy" | "unavailable" | "skipped" | string;
  detail: string;
}

const components = ref<HealthComponent[]>([]);
const loading = ref(false);
const errorMessage = ref("");

onMounted(loadHealth);

async function loadHealth() {
  loading.value = true;
  errorMessage.value = "";
  try {
    const response = await apiClient.get<{ data: { components: HealthComponent[] } }>("/admin/health");
    components.value = response.data.data.components;
  } catch (error) {
    errorMessage.value = extractErrorMessage(error, "加载健康状态失败");
  } finally {
    loading.value = false;
  }
}

function componentLabel(component: string): string {
  const labels: Record<string, string> = {
    database: "数据库",
    disk: "磁盘可写",
    llm: "本地模型",
    ffmpeg: "FFmpeg",
    ocr: "OCR",
    asr: "ASR"
  };
  return labels[component] ?? component;
}

function statusLabel(status: string): string {
  const labels: Record<string, string> = {
    healthy: "可用",
    unavailable: "不可用",
    skipped: "跳过"
  };
  return labels[status] ?? status;
}
</script>
