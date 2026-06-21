<template>
  <main class="login-page">
    <section class="login-panel">
      <div class="login-brand">
        <span>EviTrace</span>
        <h1>情报工作台</h1>
      </div>

      <el-form :model="form" label-position="top" @submit.prevent>
        <el-form-item label="用户名">
          <el-input v-model="form.username" autocomplete="username" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input v-model="form.password" type="password" autocomplete="current-password" show-password />
        </el-form-item>
        <el-alert v-if="errorMessage" :title="errorMessage" type="error" show-icon />
        <el-button class="login-button" type="primary" :loading="loading" @click="login">登录</el-button>
      </el-form>
    </section>
  </main>
</template>

<script setup lang="ts">
import { reactive, ref } from "vue";
import { useRoute, useRouter } from "vue-router";

import { useAuthStore } from "@/stores/auth";

const authStore = useAuthStore();
const route = useRoute();
const router = useRouter();
const loading = ref(false);
const errorMessage = ref("");
const form = reactive({
  username: "",
  password: ""
});

async function login() {
  loading.value = true;
  errorMessage.value = "";
  try {
    await authStore.login(form);
    const redirect = typeof route.query.redirect === "string" ? route.query.redirect : "/tasks";
    router.push(redirect);
  } catch (error) {
    errorMessage.value = extractErrorMessage(error);
  } finally {
    loading.value = false;
  }
}

function extractErrorMessage(error: unknown): string {
  if (typeof error === "object" && error !== null && "response" in error) {
    const response = (error as { response?: { data?: { detail?: { message?: string } } } }).response;
    return response?.data?.detail?.message ?? "登录失败";
  }
  return "登录失败";
}
</script>
