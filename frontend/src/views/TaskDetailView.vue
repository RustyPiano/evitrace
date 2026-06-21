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
      <FileUploadPanel :task-id="task.id" @uploaded="refreshTaskAndEvidence" />

      <el-divider />
      <div class="evidence-workspace">
        <div class="evidence-main">
          <div class="section-header compact">
            <h2>已上传文件</h2>
            <el-button type="primary" :loading="parsing" :disabled="!canParse" @click="parseFiles">
              解析文件
            </el-button>
          </div>
          <el-table :data="task.files">
            <el-table-column prop="original_name" label="文件名" min-width="220" />
            <el-table-column prop="modality" label="类型" width="120" />
            <el-table-column label="状态" width="140">
              <template #default="{ row }: { row: TaskFile }">
                <el-tag :type="fileStatusTag(row.status)" effect="plain">{{ fileStatusLabel(row.status) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="大小" width="120">
              <template #default="{ row }: { row: TaskFile }">{{ formatBytes(row.size_bytes) }}</template>
            </el-table-column>
            <el-table-column prop="error_message" label="解析信息" min-width="180" show-overflow-tooltip />
          </el-table>

          <div class="section-header compact evidence-list-header">
            <h2>证据列表</h2>
            <span>{{ evidenceTotal }} 条</span>
          </div>
          <el-table
            :data="evidenceItems"
            class="evidence-table"
            highlight-current-row
            @row-click="selectEvidence"
          >
            <el-table-column prop="display_id" label="编号" width="100" />
            <el-table-column label="来源文件" min-width="180">
              <template #default="{ row }: { row: EvidenceItem }">{{ row.file.original_name }}</template>
            </el-table-column>
            <el-table-column prop="modality" label="模态" width="90" />
            <el-table-column prop="evidence_type" label="类型" width="150" />
            <el-table-column prop="content_summary" label="内容" min-width="260" show-overflow-tooltip />
            <el-table-column label="定位" min-width="180">
              <template #default="{ row }: { row: EvidenceItem }">{{ locatorSummary(row.locator) }}</template>
            </el-table-column>
          </el-table>
          <el-pagination
            v-if="evidenceTotal > evidencePageSize"
            class="evidence-pagination"
            layout="prev, pager, next"
            :page-size="evidencePageSize"
            :total="evidenceTotal"
            :current-page="evidencePage"
            @current-change="changeEvidencePage"
          />
        </div>

        <EvidencePanel :evidence-id="selectedEvidenceId" />
      </div>
    </template>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";

import { apiClient } from "@/api/client";
import EvidencePanel from "@/components/EvidencePanel.vue";
import FileUploadPanel from "@/components/FileUploadPanel.vue";

interface TaskFile {
  id: string;
  original_name: string;
  modality: string;
  status: string;
  error_message: string | null;
  size_bytes: number;
}

interface EvidenceItem {
  id: string;
  display_id: string;
  file: TaskFile;
  modality: string;
  evidence_type: string;
  content_summary: string;
  locator: Record<string, unknown>;
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
const parsing = ref(false);
const evidenceItems = ref<EvidenceItem[]>([]);
const evidenceTotal = ref(0);
const evidencePage = ref(1);
const evidencePageSize = 50;
const selectedEvidenceId = ref<string | null>(null);
let pollTimer: number | null = null;

const canParse = computed(() => {
  if (!task.value || parsing.value) {
    return false;
  }
  return task.value.files.length > 0 && !isRunningStatus(task.value.status);
});

onMounted(refreshTaskAndEvidence);
onBeforeUnmount(stopPolling);

async function loadTask() {
  loading.value = true;
  try {
    const response = await apiClient.get<{ data: TaskDetail }>(`/tasks/${route.params.id}`);
    task.value = response.data.data;
  } finally {
    loading.value = false;
  }
}

async function loadEvidence() {
  if (!task.value) {
    return;
  }
  const response = await apiClient.get<{
    data: { items: EvidenceItem[]; total: number; page: number; page_size: number };
  }>(`/tasks/${task.value.id}/evidence`, {
    params: { page: evidencePage.value, page_size: evidencePageSize }
  });
  evidenceItems.value = response.data.data.items;
  evidenceTotal.value = response.data.data.total;
  if (selectedEvidenceId.value && !evidenceItems.value.some((item) => item.id === selectedEvidenceId.value)) {
    selectedEvidenceId.value = null;
  }
}

async function refreshTaskAndEvidence() {
  await loadTask();
  await loadEvidence();
}

async function parseFiles() {
  if (!task.value) {
    return;
  }
  parsing.value = true;
  await apiClient.post(`/tasks/${task.value.id}/parse`);
  startPolling();
}

function startPolling() {
  stopPolling();
  pollTimer = window.setInterval(async () => {
    await refreshTaskAndEvidence();
    if (!task.value || !isRunningStatus(task.value.status)) {
      parsing.value = false;
      stopPolling();
    }
  }, 1500);
}

function stopPolling() {
  if (pollTimer !== null) {
    window.clearInterval(pollTimer);
    pollTimer = null;
  }
}

function selectEvidence(row: EvidenceItem) {
  selectedEvidenceId.value = row.id;
}

function changeEvidencePage(page: number) {
  evidencePage.value = page;
  loadEvidence();
}

function isRunningStatus(status: string): boolean {
  return ["queued", "parsing", "extracting", "detecting_conflicts", "generating_report"].includes(status);
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

function fileStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    uploaded: "待解析",
    parsing: "解析中",
    parsed: "已解析",
    warning: "有警告",
    failed: "失败"
  };
  return labels[status] ?? status;
}

function fileStatusTag(status: string) {
  if (status === "failed") {
    return "danger";
  }
  if (status === "warning") {
    return "warning";
  }
  if (status === "parsed") {
    return "success";
  }
  if (status === "parsing") {
    return "primary";
  }
  return "info";
}

function locatorSummary(locator: Record<string, unknown>): string {
  if (locator.kind === "text") {
    const page = typeof locator.page === "number" ? `P${locator.page}` : "文本";
    const paragraph = typeof locator.paragraph === "number" ? `段 ${locator.paragraph}` : "";
    return [page, paragraph].filter(Boolean).join(" · ");
  }
  if (Array.isArray(locator.bbox)) {
    return `bbox ${locator.bbox.join(", ")}`;
  }
  if (typeof locator.start_ms === "number") {
    return `${(locator.start_ms / 1000).toFixed(1)}s`;
  }
  if (typeof locator.timestamp_ms === "number") {
    return `${(locator.timestamp_ms / 1000).toFixed(1)}s`;
  }
  return String(locator.kind ?? "-");
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
