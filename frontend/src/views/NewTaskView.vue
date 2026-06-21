<template>
  <section class="content-panel">
    <div class="section-header">
      <div>
        <h1>新建任务</h1>
        <p>创建任务后上传原始资料</p>
      </div>
      <el-button @click="router.push('/tasks')">取消</el-button>
    </div>

    <el-steps :active="activeStep" finish-status="success" class="task-steps">
      <el-step title="任务信息" />
      <el-step title="上传资料" />
    </el-steps>

    <el-form
      v-if="!createdTask"
      ref="formRef"
      :model="form"
      :rules="rules"
      label-position="top"
      class="task-form"
      @submit.prevent
    >
      <el-form-item label="名称" prop="name">
        <el-input v-model="form.name" maxlength="100" show-word-limit />
      </el-form-item>
      <el-form-item label="目标" prop="objective">
        <el-input v-model="form.objective" type="textarea" maxlength="1000" :rows="5" show-word-limit />
      </el-form-item>
      <el-form-item label="描述" prop="description">
        <el-input v-model="form.description" type="textarea" maxlength="2000" :rows="4" show-word-limit />
      </el-form-item>
      <el-alert v-if="errorMessage" :title="errorMessage" type="error" show-icon />
      <div class="form-actions">
        <el-button type="primary" :loading="submitting" @click="createTask">创建任务</el-button>
      </div>
    </el-form>

    <div v-else class="upload-step">
      <FileUploadPanel :task-id="createdTask.id" @uploaded="uploaded = true" />
      <div class="form-actions">
        <el-button @click="router.push(`/tasks/${createdTask.id}`)">任务详情</el-button>
        <el-button type="primary" :disabled="!uploaded" @click="router.push(`/tasks/${createdTask.id}`)">
          进入工作台
        </el-button>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import type { FormInstance, FormRules } from "element-plus";
import { computed, reactive, ref } from "vue";
import { useRouter } from "vue-router";

import { apiClient } from "@/api/client";
import FileUploadPanel from "@/components/FileUploadPanel.vue";

interface CreatedTask {
  id: string;
  name: string;
}

const router = useRouter();
const formRef = ref<FormInstance>();
const form = reactive({
  name: "",
  objective: "",
  description: ""
});
const createdTask = ref<CreatedTask | null>(null);
const submitting = ref(false);
const uploaded = ref(false);
const errorMessage = ref("");
const activeStep = computed(() => (createdTask.value ? 1 : 0));

const rules: FormRules = {
  name: [{ required: true, message: "请输入名称", trigger: "blur" }],
  objective: [{ required: true, message: "请输入目标", trigger: "blur" }]
};

async function createTask() {
  const valid = await formRef.value?.validate().catch(() => false);
  if (!valid) {
    return;
  }
  submitting.value = true;
  errorMessage.value = "";
  try {
    const response = await apiClient.post<{ data: CreatedTask }>("/tasks", {
      name: form.name,
      objective: form.objective,
      description: form.description || null
    });
    createdTask.value = response.data.data;
  } catch (error) {
    errorMessage.value = extractErrorMessage(error);
  } finally {
    submitting.value = false;
  }
}

function extractErrorMessage(error: unknown): string {
  if (typeof error === "object" && error !== null && "response" in error) {
    const response = (error as { response?: { data?: { detail?: { message?: string } } } }).response;
    return response?.data?.detail?.message ?? "创建失败";
  }
  return "创建失败";
}
</script>
