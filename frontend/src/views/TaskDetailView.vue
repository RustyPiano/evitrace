<template>
  <section class="content-panel">
    <div class="section-header">
      <div>
        <h1>{{ task?.name ?? "任务详情" }}</h1>
        <p>{{ task?.objective }}</p>
      </div>
      <el-button @click="router.push('/tasks')">返回</el-button>
    </div>

    <el-skeleton v-if="loading" :rows="5" animated />
    <template v-else-if="task">
      <div class="task-meta-grid">
        <div>
          <span>状态</span>
          <el-tag :type="statusTag(task.status)" effect="plain">{{ statusLabel(task.status) }}</el-tag>
        </div>
        <div>
          <span>文件数</span>
          <strong>{{ task.file_count }}</strong>
        </div>
        <div>
          <span>更新时间</span>
          <strong>{{ formatDate(task.updated_at) }}</strong>
        </div>
      </div>

      <el-divider />
      <FileUploadPanel :task-id="task.id" @uploaded="loadTask" />

      <el-divider />
      <h2>已上传文件</h2>
      <el-table :data="task.files">
        <el-table-column prop="original_name" label="文件名" min-width="220" />
        <el-table-column prop="modality" label="类型" width="120" />
        <el-table-column label="状态" width="120">
          <template #default="{ row }: { row: TaskFile }">
            <el-tag effect="plain">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="大小" width="120">
          <template #default="{ row }: { row: TaskFile }">{{ formatBytes(row.size_bytes) }}</template>
        </el-table-column>
      </el-table>
    </template>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";

import { apiClient } from "@/api/client";
import FileUploadPanel from "@/components/FileUploadPanel.vue";

interface TaskFile {
  id: string;
  original_name: string;
  modality: string;
  status: string;
  size_bytes: number;
}

interface TaskDetail {
  id: string;
  name: string;
  objective: string;
  status: string;
  file_count: number;
  updated_at: string;
  files: TaskFile[];
}

const route = useRoute();
const router = useRouter();
const task = ref<TaskDetail | null>(null);
const loading = ref(false);

onMounted(loadTask);

async function loadTask() {
  loading.value = true;
  try {
    const response = await apiClient.get<{ data: TaskDetail }>(`/tasks/${route.params.id}`);
    task.value = response.data.data;
  } finally {
    loading.value = false;
  }
}

function statusLabel(status: string): string {
  const labels: Record<string, string> = {
    draft: "草稿",
    ready: "可分析",
    queued: "排队中",
    parsing: "解析中",
    extracting: "提取中",
    detecting_conflicts: "冲突检测",
    generating_report: "生成报告",
    awaiting_review: "待审核",
    completed: "已完成",
    failed: "失败"
  };
  return labels[status] ?? status;
}

function statusTag(status: string) {
  if (status === "failed") {
    return "danger";
  }
  if (status === "completed" || status === "awaiting_review") {
    return "success";
  }
  if (status === "ready") {
    return "primary";
  }
  return "info";
}

function formatDate(value: string): string {
  return new Date(value).toLocaleString();
}

function formatBytes(value: number): string {
  if (value < 1024) {
    return `${value} B`;
  }
  if (value < 1024 * 1024) {
    return `${(value / 1024).toFixed(1)} KB`;
  }
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}
</script>
