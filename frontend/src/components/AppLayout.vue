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
import { useRoute, useRouter } from "vue-router";

import { useAuthStore } from "@/stores/auth";

const route = useRoute();
const router = useRouter();
const authStore = useAuthStore();

function logout() {
  authStore.logout();
  router.push("/login");
}
</script>
