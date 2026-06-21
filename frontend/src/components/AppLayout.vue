<template>
  <el-container class="app-shell">
    <el-aside class="app-sidebar" width="220px">
      <div class="brand">EviTrace</div>
      <el-menu :default-active="route.path" router class="sidebar-menu">
        <el-menu-item index="/tasks">任务</el-menu-item>
      </el-menu>
    </el-aside>

    <el-container>
      <el-header class="app-header">
        <span class="page-title">情报工作台</span>
        <el-button type="primary" @click="router.push('/login')">登录</el-button>
      </el-header>

      <el-main class="app-main">
        <RouterView />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup lang="ts">
import { useRoute, useRouter } from "vue-router";

const route = useRoute();
const router = useRouter();
</script>
