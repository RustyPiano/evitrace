<template>
  <el-container class="app-shell">
    <el-aside class="app-sidebar" width="220px">
      <div class="brand">EviTrace</div>
      <el-menu :default-active="route.path" router class="sidebar-menu">
        <el-menu-item index="/tasks">任务</el-menu-item>
        <el-sub-menu v-if="authStore.isAdmin" index="/admin">
          <template #title>管理</template>
          <el-menu-item index="/admin/users">用户</el-menu-item>
          <el-menu-item index="/admin/skills">Skill</el-menu-item>
          <el-menu-item index="/admin/health">健康</el-menu-item>
          <el-menu-item index="/admin/audit">审计</el-menu-item>
        </el-sub-menu>
      </el-menu>
    </el-aside>

    <el-container>
      <el-header class="app-header">
        <span class="page-title">情报工作台</span>
        <div class="header-actions">
          <el-tag
            v-if="runMode"
            size="small"
            effect="plain"
            :type="runModeTagType"
            :title="runModeTitle"
          >
            {{ runMode.mode_label }}
          </el-tag>
          <span class="user-label">{{ authStore.user?.username }}</span>
          <el-tag size="small" effect="plain">{{ authStore.user?.role }}</el-tag>
          <el-button @click="logout">退出</el-button>
        </div>
      </el-header>

      <el-main class="app-main">
        <RouterView />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";

import { getSystemMode } from "@/api/system";
import { useAuthStore } from "@/stores/auth";
import type { ComponentDeployment, RunModeMetadata } from "@/types/system";

const route = useRoute();
const router = useRouter();
const authStore = useAuthStore();
const runMode = ref<RunModeMetadata | null>(null);

const runModeTagType = computed(() => {
  if (runMode.value?.mode === "real") {
    return "success";
  }
  if (runMode.value?.mode === "hybrid") {
    return "warning";
  }
  return "info";
});

const runModeTitle = computed(() => {
  if (!runMode.value) {
    return "";
  }
  const metadata = runMode.value;
  return [
    `LLM：${componentTitle(metadata.llm, "未配置")}`,
    `视觉：${componentTitle(metadata.vision, "未启用")}`,
    `OCR：${componentTitle(metadata.ocr)}`,
    `ASR：${componentTitle(metadata.asr)}`
  ].join("｜");
});

onMounted(async () => {
  runMode.value = await getSystemMode();
});

function logout() {
  authStore.logout();
  router.push("/login");
}

function componentTitle(
  component: { real: boolean; model?: string | null; deployment?: ComponentDeployment | null },
  missingModelLabel?: string
) {
  if (!component.real) {
    return "演示";
  }
  const model = component.model || missingModelLabel;
  const deployment = deploymentLabel(component.deployment);
  return model ? `${model} · ${deployment}` : deployment;
}

function deploymentLabel(deployment?: ComponentDeployment | null) {
  if (deployment === "local") {
    return "本地";
  }
  if (deployment === "remote") {
    return "远程";
  }
  return "未知";
}
</script>
