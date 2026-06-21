<template>
  <section class="content-panel">
    <div class="section-header">
      <div>
        <h1>任务</h1>
        <p>按任务组织资料、证据和分析结果</p>
      </div>
      <el-button type="primary" @click="router.push('/tasks/new')">新建任务</el-button>
    </div>

    <div class="table-toolbar">
      <el-input v-model="keyword" clearable placeholder="搜索名称或目标" />
      <el-select v-model="statusFilter" placeholder="状态" clearable>
        <el-option v-for="item in statusOptions" :key="item.value" :label="item.label" :value="item.value" />
      </el-select>
    </div>

    <el-table v-loading="loading" :data="filteredTasks" class="task-table">
      <el-table-column prop="name" label="任务名" min-width="180" />
      <el-table-column prop="objective" label="分析目标" min-width="240" show-overflow-tooltip />
      <el-table-column v-if="authStore.isAdmin" prop="owner_username" label="创建人" width="140" />
      <el-table-column prop="file_count" label="文件数" width="90" />
      <el-table-column label="状态" width="140">
        <template #default="{ row }: { row: TaskSummary }">
          <el-tag :type="statusTag(row.status)" effect="plain">{{ statusLabel(row.status) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="更新时间" width="190">
        <template #default="{ row }: { row: TaskSummary }">{{ formatDate(row.updated_at) }}</template>
      </el-table-column>
      <el-table-column prop="latest_run_error" label="最近错误" min-width="180" show-overflow-tooltip />
      <el-table-column label="操作" width="170" fixed="right">
        <template #default="{ row }: { row: TaskSummary }">
          <el-button link type="primary" @click="router.push(`/tasks/${row.id}`)">查看</el-button>
          <el-button link type="danger" @click="confirmDelete(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { ElMessage, ElMessageBox } from "element-plus";

import { apiClient } from "@/api/client";
import { useAuthStore } from "@/stores/auth";
import { formatDate, taskStatusLabel, taskStatusOptions, taskStatusTag } from "@/utils/status";

interface TaskSummary {
  id: string;
  name: string;
  objective: string;
  owner_username: string | null;
  file_count: number;
  status: string;
  updated_at: string;
  latest_run_error: string | null;
}

const router = useRouter();
const authStore = useAuthStore();
const tasks = ref<TaskSummary[]>([]);
const loading = ref(false);
const keyword = ref("");
const statusFilter = ref("");

const statusOptions = taskStatusOptions;

const filteredTasks = computed(() => {
  const term = keyword.value.trim().toLowerCase();
  return tasks.value.filter((task) => {
    const matchesKeyword =
      !term ||
      task.name.toLowerCase().includes(term) ||
      task.objective.toLowerCase().includes(term);
    const matchesStatus = !statusFilter.value || task.status === statusFilter.value;
    return matchesKeyword && matchesStatus;
  });
});

onMounted(loadTasks);

async function loadTasks() {
  loading.value = true;
  try {
    const response = await apiClient.get<{ data: TaskSummary[] }>("/tasks");
    tasks.value = response.data.data;
  } finally {
    loading.value = false;
  }
}

async function confirmDelete(task: TaskSummary) {
  await ElMessageBox.confirm(`确认删除任务「${task.name}」？`, "删除任务", {
    type: "warning",
    confirmButtonText: "删除",
    cancelButtonText: "取消"
  });
  await apiClient.delete(`/tasks/${task.id}`);
  ElMessage.success("已删除");
  await loadTasks();
}

const statusLabel = taskStatusLabel;
const statusTag = taskStatusTag;
</script>
