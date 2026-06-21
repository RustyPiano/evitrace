<template>
  <section class="content-panel">
    <div class="section-header">
      <div>
        <h1>{{ task?.name ?? "任务详情" }}</h1>
        <p>{{ task?.objective }}</p>
      </div>
      <div class="header-actions">
        <el-button
          type="primary"
          :loading="analysisStarting"
          :disabled="!canRunAnalysis"
          @click="startAnalysis"
        >
          {{ analysisButtonText }}
        </el-button>
        <el-button @click="router.push('/tasks')">返回</el-button>
      </div>
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
      <div class="section-header compact">
        <h2>分析运行</h2>
        <span>{{ latestRun ? runStatusLabel(latestRun.status) : "尚未运行" }}</span>
      </div>
      <div class="analysis-run-panel">
        <el-progress
          :percentage="latestRun?.progress ?? 0"
          :status="task.status === 'failed' ? 'exception' : latestRun?.status === 'succeeded' ? 'success' : undefined"
        />
        <div class="run-meta">
          <span>当前步骤：{{ latestRun?.current_step ?? "-" }}</span>
          <span v-if="latestRun?.error_message">错误：{{ latestRun.error_message }}</span>
          <span v-else-if="task.last_error">提示：{{ task.last_error }}</span>
        </div>
        <el-alert
          v-if="latestRun?.warnings?.length"
          type="warning"
          :closable="false"
          show-icon
          title="运行警告"
        >
          <ul class="warning-list">
            <li v-for="warning in latestRun.warnings" :key="warning">{{ warning }}</li>
          </ul>
        </el-alert>
      </div>

      <div v-if="analysisResult" class="analysis-results">
        <div class="section-header compact">
          <h2>分析结果</h2>
          <span>
            {{ analysisResult.events.length }} 事件 · {{ analysisResult.conflicts.length }} 冲突
          </span>
        </div>
        <el-tabs>
          <el-tab-pane label="事件">
            <el-table :data="analysisResult.events">
              <el-table-column prop="event_id" label="编号" width="100" />
              <el-table-column prop="title" label="标题" min-width="180" />
              <el-table-column prop="time_normalized" label="时间" min-width="180" />
              <el-table-column prop="location" label="地点" min-width="140" />
              <el-table-column label="证据" min-width="160">
                <template #default="{ row }: { row: AnalysisEvent }">
                  <el-button
                    v-for="displayId in row.evidence_ids"
                    :key="displayId"
                    link
                    type="primary"
                    @click.stop="selectEvidenceByDisplayId(displayId)"
                  >
                    {{ displayId }}
                  </el-button>
                </template>
              </el-table-column>
            </el-table>
          </el-tab-pane>
          <el-tab-pane label="冲突">
            <el-table :data="analysisResult.conflicts">
              <el-table-column prop="conflict_id" label="编号" width="100" />
              <el-table-column prop="type" label="类型" width="100" />
              <el-table-column prop="description" label="描述" min-width="260" show-overflow-tooltip />
              <el-table-column label="状态" width="120">
                <template #default="{ row }: { row: AnalysisConflict }">
                  <el-tag effect="plain">{{ conflictStatusLabel(row.status) }}</el-tag>
                </template>
              </el-table-column>
            </el-table>
          </el-tab-pane>
          <el-tab-pane label="报告">
            <div class="citation-summary">
              <el-tag
                :type="analysisResult.citation_check.invalid_citations.length ? 'danger' : 'success'"
                effect="plain"
              >
                无效引用 {{ analysisResult.citation_check.invalid_citations.length }}
              </el-tag>
              <el-tag effect="plain">
                结论引用覆盖 {{ Math.round(analysisResult.citation_check.citation_coverage * 100) }}%
              </el-tag>
            </div>
            <article class="report-markdown" v-html="renderedReport"></article>
          </el-tab-pane>
        </el-tabs>
      </div>

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
  last_error: string | null;
  file_count: number;
  updated_at: string;
  files: TaskFile[];
}

interface RunStatus {
  run_id: string;
  status: string;
  progress: number;
  current_step: string | null;
  warnings: string[];
  error_message: string | null;
}

interface AnalysisEvent {
  event_id: string;
  title: string;
  time_normalized: string | null;
  location: string | null;
  evidence_ids: string[];
}

interface AnalysisConflict {
  conflict_id: string;
  type: string;
  description: string;
  status: string;
}

interface CitationCheck {
  invalid_citations: string[];
  citation_coverage: number;
}

interface AnalysisResult {
  entities: unknown[];
  events: AnalysisEvent[];
  timeline: unknown[];
  conflicts: AnalysisConflict[];
  report_markdown: string | null;
  citation_check: CitationCheck;
}

const route = useRoute();
const router = useRouter();
const task = ref<TaskDetail | null>(null);
const loading = ref(false);
const parsing = ref(false);
const analysisStarting = ref(false);
const evidenceItems = ref<EvidenceItem[]>([]);
const evidenceTotal = ref(0);
const evidencePage = ref(1);
const evidencePageSize = 50;
const selectedEvidenceId = ref<string | null>(null);
const latestRun = ref<RunStatus | null>(null);
const analysisResult = ref<AnalysisResult | null>(null);
let pollTimer: number | null = null;

const canParse = computed(() => {
  if (!task.value || parsing.value) {
    return false;
  }
  return task.value.files.length > 0 && !isRunningStatus(task.value.status);
});

const canRunAnalysis = computed(() => {
  if (!task.value || analysisStarting.value) {
    return false;
  }
  return task.value.files.length > 0 && !isRunningStatus(task.value.status);
});

const analysisButtonText = computed(() => {
  if (!task.value || !analysisResult.value) {
    return "开始分析";
  }
  return "重新分析";
});

const renderedReport = computed(() => renderMarkdown(analysisResult.value?.report_markdown ?? ""));

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

async function loadLatestRun() {
  if (!task.value) {
    return;
  }
  try {
    const response = await apiClient.get<{ data: RunStatus }>(`/tasks/${task.value.id}/runs/latest`);
    latestRun.value = response.data.data;
  } catch (error: any) {
    if (error.response?.status === 404) {
      latestRun.value = null;
      return;
    }
    throw error;
  }
}

async function loadResults() {
  if (!task.value) {
    return;
  }
  try {
    const response = await apiClient.get<{ data: AnalysisResult }>(`/tasks/${task.value.id}/results`);
    analysisResult.value = response.data.data;
  } catch (error: any) {
    if (error.response?.status === 404) {
      analysisResult.value = null;
      return;
    }
    throw error;
  }
}

async function refreshTaskAndEvidence() {
  await loadTask();
  await loadEvidence();
  await loadLatestRun();
  await loadResults();
}

async function parseFiles() {
  if (!task.value) {
    return;
  }
  parsing.value = true;
  await apiClient.post(`/tasks/${task.value.id}/parse`);
  startPolling();
}

async function startAnalysis() {
  if (!task.value) {
    return;
  }
  analysisStarting.value = true;
  try {
    const response = await apiClient.post<{ data: { run_id: string; status: string } }>(`/tasks/${task.value.id}/runs`);
    latestRun.value = {
      run_id: response.data.data.run_id,
      status: response.data.data.status,
      progress: 0,
      current_step: "queued",
      warnings: [],
      error_message: null
    };
    task.value.status = "queued";
    startPolling();
  } finally {
    analysisStarting.value = false;
  }
}

function startPolling() {
  stopPolling();
  pollTimer = window.setInterval(async () => {
    await refreshTaskAndEvidence();
    if (!task.value || !isRunningStatus(task.value.status)) {
      parsing.value = false;
      stopPolling();
    }
  }, 2000);
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

function selectEvidenceByDisplayId(displayId: string) {
  const evidence = evidenceItems.value.find((item) => item.display_id === displayId);
  if (evidence) {
    selectedEvidenceId.value = evidence.id;
  }
}

function changeEvidencePage(page: number) {
  evidencePage.value = page;
  loadEvidence();
}

function isRunningStatus(status: string): boolean {
  return ["queued", "parsing", "extracting", "detecting_conflicts", "generating_report"].includes(status);
}

function runStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    queued: "排队中",
    running: "运行中",
    succeeded: "已完成",
    failed: "失败"
  };
  return labels[status] ?? status;
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

function conflictStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    unreviewed: "待审核",
    confirmed: "已确认",
    ignored: "已忽略"
  };
  return labels[status] ?? status;
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

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function renderInlineMarkdown(value: string): string {
  return escapeHtml(value)
    .replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>")
    .replace(/(\[E-\d{4}\])/g, '<span class="citation">$1</span>');
}

function renderMarkdown(markdown: string): string {
  const lines = markdown.split("\n");
  const output: string[] = [];
  let inList = false;

  function closeList() {
    if (inList) {
      output.push("</ul>");
      inList = false;
    }
  }

  for (const rawLine of lines) {
    const line = rawLine.trimEnd();
    if (!line.trim()) {
      closeList();
      continue;
    }
    if (line.startsWith("- ")) {
      if (!inList) {
        output.push("<ul>");
        inList = true;
      }
      output.push(`<li>${renderInlineMarkdown(line.slice(2))}</li>`);
      continue;
    }
    closeList();
    if (line.startsWith("### ")) {
      output.push(`<h3>${renderInlineMarkdown(line.slice(4))}</h3>`);
    } else if (line.startsWith("## ")) {
      output.push(`<h2>${renderInlineMarkdown(line.slice(3))}</h2>`);
    } else if (line.startsWith("# ")) {
      output.push(`<h1>${renderInlineMarkdown(line.slice(2))}</h1>`);
    } else {
      output.push(`<p>${renderInlineMarkdown(line)}</p>`);
    }
  }
  closeList();
  return output.join("");
}
</script>
