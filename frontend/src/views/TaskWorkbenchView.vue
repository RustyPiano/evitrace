<template>
  <section class="workbench-page">
    <el-alert v-if="errorMessage" :title="errorMessage" type="error" show-icon />

    <div class="workbench-topbar">
      <div>
        <div class="title-line">
          <h1>{{ task?.name ?? "任务工作台" }}</h1>
          <el-tag v-if="task" :type="taskStatusTag(task.status)" effect="plain">
            {{ taskStatusLabel(task.status) }}
          </el-tag>
        </div>
        <p>{{ task?.objective ?? "加载任务中" }}</p>
        <div class="run-selector">
          <span>分析版本</span>
          <el-select
            v-model="selectedRunId"
            placeholder="暂无运行"
            :disabled="!runs.length"
            @change="changeSelectedRun"
          >
            <el-option
              v-for="run in runs"
              :key="run.run_id"
              :label="runOptionLabel(run)"
              :value="run.run_id"
            />
          </el-select>
        </div>
      </div>
      <div class="workbench-actions">
        <el-progress v-if="isSelectedLatestRun" class="top-progress" :percentage="latestRun?.progress ?? 0" />
        <el-button
          type="primary"
          :loading="analysisStarting"
          :disabled="!canStartAnalysis"
          @click="startAnalysis"
        >
          {{ analysisButtonText }}
        </el-button>
        <el-button
          v-if="isLatestRunRunning"
          type="danger"
          plain
          :loading="analysisCancelling"
          @click="cancelAnalysis"
        >
          {{ analysisCancelling ? "正在停止..." : "停止分析" }}
        </el-button>
        <el-checkbox
          v-if="showForceComplete"
          v-model="forceComplete"
          :disabled="completing"
        >
          强制确认
        </el-checkbox>
        <el-tooltip :content="completionHint" :disabled="canMarkComplete">
          <span>
            <el-button
              :loading="completing"
              :disabled="!canMarkComplete"
              @click="markCompleted"
            >
              标记完成
            </el-button>
          </span>
        </el-tooltip>
        <el-button :disabled="!analysisResult?.report_markdown" :loading="downloading" @click="downloadReport">
          下载报告
        </el-button>
      </div>
    </div>

    <el-skeleton v-if="loading" :rows="8" animated />
    <template v-else-if="task">
      <el-alert
        v-if="task.status === 'failed'"
        type="error"
        :closable="false"
        show-icon
        class="workbench-alert"
      >
        <template #title>
          <span>{{ latestRun?.error_message || task.last_error || "分析失败" }}</span>
          <el-button link type="primary" :loading="analysisStarting" @click="startAnalysis">重试</el-button>
        </template>
      </el-alert>
      <el-alert
        v-if="completionHint && !canMarkComplete && task.status === 'awaiting_review'"
        type="warning"
        :closable="false"
        show-icon
        class="workbench-alert"
        :title="completionHint"
      />

      <div class="workbench-grid">
        <aside class="workbench-left">
          <FileList :files="task.files" :running="isRunning" @deleted="refreshAll" />
          <RunProgress :run="selectedRunProgress" />
        </aside>

        <main class="workbench-center">
          <el-tabs v-model="activeTab" class="workbench-tabs">
            <el-tab-pane label="概览" name="overview">
              <div class="overview-grid">
                <div v-for="stat in overviewStats" :key="stat.label" class="stat-card">
                  <span>{{ stat.label }}</span>
                  <strong>{{ stat.value }}</strong>
                </div>
              </div>
              <el-empty
                v-if="!analysisResult"
                description="暂无分析结果，开始分析后显示概览"
              />
            </el-tab-pane>
            <el-tab-pane label="时间线" name="timeline">
              <TimelinePanel :items="timelineItems" @select-evidence="selectEvidenceByDisplayId" />
            </el-tab-pane>
            <el-tab-pane label="冲突" name="conflicts">
              <ConflictPanel
                :task-id="task.id"
                :conflicts="analysisResult?.conflicts ?? []"
                :running="isSelectedRunRunning"
                :run-id="selectedRunId"
                @select-evidence="selectEvidenceByDisplayId"
                @updated="refreshResults"
              />
            </el-tab-pane>
            <el-tab-pane label="报告" name="report">
              <ReportPanel
                :task-id="task.id"
                :report-markdown="analysisResult?.report_markdown ?? null"
                :citation-check="analysisResult?.citation_check ?? null"
                :running="isSelectedRunRunning"
                :analysis-complete="Boolean(analysisResult)"
                :run-id="selectedRunId"
                @select-evidence="selectEvidenceByDisplayId"
                @regenerated="refreshResults"
              />
            </el-tab-pane>
          </el-tabs>
        </main>

        <EvidencePanel class="workbench-right" :evidence-id="selectedEvidenceId" :run-id="selectedRunId" />
      </div>
    </template>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { useRoute } from "vue-router";
import { ElMessage } from "element-plus";

import { apiClient } from "@/api/client";
import ConflictPanel from "@/components/ConflictPanel.vue";
import EvidencePanel from "@/components/EvidencePanel.vue";
import FileList from "@/components/FileList.vue";
import ReportPanel from "@/components/ReportPanel.vue";
import RunProgress from "@/components/RunProgress.vue";
import TimelinePanel from "@/components/TimelinePanel.vue";
import { useAuthStore } from "@/stores/auth";
import type { AnalysisResult, RunStatus, TaskDetail, TaskRunSummary, TimelineItem } from "@/types/workbench";
import { extractErrorMessage } from "@/utils/errors";
import {
  formatPercent,
  isRunningStatus,
  runStatusLabel,
  taskStatusLabel,
  taskStatusTag
} from "@/utils/status";

const route = useRoute();
const authStore = useAuthStore();
const taskId = String(route.params.id);
interface EvidenceIndexItem {
  id: string;
  display_id: string;
  modality: string;
  evidence_type: string;
}

const task = ref<TaskDetail | null>(null);
const loading = ref(false);
const errorMessage = ref("");
const activeTab = ref("overview");
const latestRun = ref<RunStatus | null>(null);
const runs = ref<TaskRunSummary[]>([]);
const selectedRunId = ref<string | null>(null);
const analysisResult = ref<AnalysisResult | null>(null);
const evidenceItems = ref<EvidenceIndexItem[]>([]);
const evidenceTotal = ref(0);
const selectedEvidenceId = ref<string | null>(null);
const analysisStarting = ref(false);
const analysisCancelling = ref(false);
const completing = ref(false);
const forceComplete = ref(false);
const downloading = ref(false);
let pollTimer: number | null = null;
let polling = false;

const isRunning = computed(() => Boolean(task.value && isRunningStatus(task.value.status)));
const isLatestRunRunning = computed(() => Boolean(latestRun.value && isRunRunning(latestRun.value.status)));
const isSelectedLatestRun = computed(
  () => Boolean(latestRun.value && selectedRunId.value === latestRun.value.run_id)
);
const isSelectedRunRunning = computed(() => isSelectedLatestRun.value && isLatestRunRunning.value);
const selectedRunProgress = computed<RunStatus | null>(() => {
  if (isSelectedLatestRun.value) {
    return latestRun.value;
  }
  const run = runs.value.find((item) => item.run_id === selectedRunId.value);
  if (!run) {
    return null;
  }
  return {
    run_id: run.run_id,
    status: run.status,
    plan_json: null,
    progress: run.progress,
    current_step: null,
    warnings: [],
    error_message: null
  };
});
const citationCoverage = computed(() => analysisResult.value?.citation_check?.citation_coverage ?? 0);
const invalidCitationCount = computed(() => analysisResult.value?.citation_check?.invalid_citations?.length ?? 0);
const activeConflictCount = computed(
  () => analysisResult.value?.conflicts.filter((conflict) => conflict.status !== "ignored").length ?? 0
);
const canStartAnalysis = computed(
  () => Boolean(task.value && task.value.files.length > 0 && !isRunning.value && !analysisStarting.value)
);
const analysisButtonText = computed(() => {
  if (task.value?.status === "failed") {
    return "重试";
  }
  return analysisResult.value ? "重新分析" : "开始分析";
});
const showForceComplete = computed(
  () => Boolean(authStore.isAdmin && task.value?.status === "awaiting_review" && citationCoverage.value < 0.9)
);
const canMarkComplete = computed(() => {
  if (!task.value || task.value.status !== "awaiting_review" || completing.value || invalidCitationCount.value > 0) {
    return false;
  }
  if (citationCoverage.value >= 0.9) {
    return true;
  }
  return authStore.isAdmin && forceComplete.value;
});
const completionHint = computed(() => {
  if (!task.value || task.value.status !== "awaiting_review") {
    return "";
  }
  if (invalidCitationCount.value > 0) {
    return "报告存在无效引用，不能标记完成";
  }
  if (citationCoverage.value < 0.9 && authStore.isAdmin) {
    return forceComplete.value ? "" : "引用覆盖率低于 90%，需勾选强制确认";
  }
  if (citationCoverage.value < 0.9) {
    return "引用覆盖率低于 90%，需管理员强制确认";
  }
  return "";
});
const overviewStats = computed(() => [
  { label: "文件数", value: String(task.value?.file_count ?? 0) },
  { label: "证据数", value: String(evidenceTotal.value) },
  { label: "实体数", value: String(analysisResult.value?.entities.length ?? 0) },
  { label: "事件数", value: String(analysisResult.value?.events.length ?? 0) },
  { label: "冲突数", value: String(activeConflictCount.value) },
  { label: "引用覆盖率", value: formatPercent(citationCoverage.value) }
]);
const timelineItems = computed<TimelineItem[]>(() => {
  if (!analysisResult.value) {
    return [];
  }
  if (analysisResult.value.timeline.length) {
    const confidenceByEvent = new Map(
      analysisResult.value.events.map((event) => [event.event_id, event.confidence ?? null])
    );
    return analysisResult.value.timeline.map((item) => ({
      ...item,
      confidence: item.confidence ?? confidenceByEvent.get(item.event_id) ?? null
    }));
  }
  return analysisResult.value.events.map((event) => ({
    event_id: event.event_id,
    event_key: event.event_key,
    title: event.title,
    time_text: event.time_text,
    time_normalized: event.time_normalized,
    location: event.location,
    evidence_ids: event.evidence_ids,
    confidence: event.confidence ?? null
  }));
});
const evidenceByDisplayId = computed(
  () => new Map(evidenceItems.value.map((item) => [item.display_id, item.id]))
);

onMounted(async () => {
  await refreshAll(true);
  if (isRunning.value) {
    startPolling();
  }
});
onBeforeUnmount(stopPolling);

async function refreshAll(showLoading = false, rethrow = false) {
  if (showLoading) {
    loading.value = true;
  }
  errorMessage.value = "";
  try {
    await Promise.all([loadTask(), loadLatestRun(), loadRuns()]);
    await Promise.all([loadEvidence(), loadResults()]);
    if (!isLatestRunRunning.value) {
      analysisCancelling.value = false;
    }
  } catch (error) {
    errorMessage.value = extractErrorMessage(error, "加载任务工作台失败");
    if (rethrow) {
      throw error;
    }
  } finally {
    loading.value = false;
  }
}

async function loadTask() {
  const response = await apiClient.get<{ data: TaskDetail }>(`/tasks/${taskId}`);
  task.value = response.data.data;
}

async function loadRuns(preferredRunId?: string) {
  const response = await apiClient.get<{ data: TaskRunSummary[] }>(`/tasks/${taskId}/runs`);
  runs.value = response.data.data;
  syncSelectedRun(preferredRunId);
}

async function loadEvidence() {
  const response = await apiClient.get<{ data: EvidenceIndexItem[] }>(`/tasks/${taskId}/evidence/index`, {
    params: currentRunParams()
  });
  evidenceItems.value = response.data.data;
  evidenceTotal.value = response.data.data.length;
}

async function loadLatestRun() {
  try {
    const response = await apiClient.get<{ data: RunStatus }>(`/tasks/${taskId}/runs/latest`);
    latestRun.value = response.data.data;
  } catch (error: unknown) {
    if (isNotFound(error)) {
      latestRun.value = null;
      return;
    }
    throw error;
  }
}

async function loadResults() {
  try {
    const response = await apiClient.get<{ data: AnalysisResult }>(`/tasks/${taskId}/results`, {
      params: currentRunParams()
    });
    analysisResult.value = response.data.data;
  } catch (error: unknown) {
    if (isNotFound(error)) {
      analysisResult.value = null;
      return;
    }
    throw error;
  }
}

async function refreshResults() {
  await Promise.all([loadEvidence(), loadResults()]);
}

async function startAnalysis() {
  if (!task.value) {
    return;
  }
  analysisStarting.value = true;
  errorMessage.value = "";
  try {
    const response = await apiClient.post<{ data: { run_id: string; status: string } }>(`/tasks/${task.value.id}/runs`);
    const newRunId = response.data.data.run_id;
    selectedRunId.value = newRunId;
    latestRun.value = {
      run_id: newRunId,
      status: response.data.data.status,
      plan_json: null,
      progress: 0,
      current_step: "queued",
      warnings: [],
      error_message: null
    };
    task.value.status = "queued";
    analysisCancelling.value = false;
    analysisResult.value = null;
    selectedEvidenceId.value = null;
    await loadRuns(newRunId);
    startPolling();
  } catch (error) {
    ElMessage.error(extractErrorMessage(error, "启动分析失败"));
  } finally {
    analysisStarting.value = false;
  }
}

async function cancelAnalysis() {
  if (!task.value || !latestRun.value) {
    return;
  }
  analysisCancelling.value = true;
  try {
    await apiClient.post(`/tasks/${task.value.id}/runs/cancel`);
    ElMessage.info("正在停止分析...");
    startPolling();
  } catch (error) {
    analysisCancelling.value = false;
    ElMessage.error(extractErrorMessage(error, "停止分析失败"));
  }
}

async function markCompleted() {
  if (!task.value) {
    return;
  }
  completing.value = true;
  try {
    const response = await apiClient.patch<{ data: TaskDetail }>(`/tasks/${task.value.id}`, {
      status: "completed",
      force: forceComplete.value
    });
    task.value = response.data.data;
    ElMessage.success("任务已标记完成");
  } catch (error) {
    ElMessage.error(extractErrorMessage(error, "标记完成失败"));
  } finally {
    completing.value = false;
  }
}

async function downloadReport() {
  if (!task.value) {
    return;
  }
  downloading.value = true;
  try {
    const response = await apiClient.get(`/tasks/${task.value.id}/report/download`, {
      params: currentRunParams(),
      responseType: "blob"
    });
    const filename = filenameFromDisposition(response.headers["content-disposition"]) ?? "分析报告.md";
    const url = URL.createObjectURL(response.data as Blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    link.click();
    URL.revokeObjectURL(url);
  } catch (error) {
    ElMessage.error(extractErrorMessage(error, "下载报告失败"));
  } finally {
    downloading.value = false;
  }
}

function startPolling() {
  stopPolling();
  polling = true;
  scheduleNextPoll();
}

function scheduleNextPoll() {
  if (!polling) {
    return;
  }
  pollTimer = window.setTimeout(runPoll, 2000);
}

async function runPoll() {
  pollTimer = null;
  if (!polling) {
    return;
  }
  try {
    await refreshAll(false, true);
    if (!isRunning.value) {
      stopPolling();
      return;
    }
    scheduleNextPoll();
  } catch (error) {
    if (isUnauthorized(error)) {
      stopPolling();
      return;
    }
    scheduleNextPoll();
  }
}

function stopPolling() {
  polling = false;
  if (pollTimer !== null) {
    window.clearTimeout(pollTimer);
    pollTimer = null;
  }
}

function selectEvidenceByDisplayId(displayId: string) {
  const id = evidenceByDisplayId.value.get(displayId);
  if (!id) {
    ElMessage.warning(`未找到证据 ${displayId}`);
    return;
  }
  selectedEvidenceId.value = id;
}

async function changeSelectedRun() {
  selectedEvidenceId.value = null;
  try {
    await Promise.all([loadEvidence(), loadResults()]);
  } catch (error) {
    ElMessage.error(extractErrorMessage(error, "切换分析版本失败"));
  }
}

function syncSelectedRun(preferredRunId?: string) {
  if (!runs.value.length) {
    selectedRunId.value = null;
    return;
  }
  const candidate = preferredRunId ?? selectedRunId.value;
  if (candidate && runs.value.some((run) => run.run_id === candidate)) {
    selectedRunId.value = candidate;
    return;
  }
  selectedRunId.value = runs.value.find((run) => run.has_result)?.run_id ?? runs.value[0].run_id;
}

function currentRunParams(): { run_id: string } | undefined {
  return selectedRunId.value ? { run_id: selectedRunId.value } : undefined;
}

function runOptionLabel(run: TaskRunSummary): string {
  const resultSuffix = run.has_result ? "" : "（无结果）";
  return `${formatRunTime(run.started_at)} ${runStatusLabel(run.status)}${resultSuffix} ${shortRunId(run.run_id)}`;
}

function formatRunTime(value: string | null): string {
  return value ? new Date(value).toLocaleString() : "未知时间";
}

function shortRunId(runId: string): string {
  return runId.slice(0, 8);
}

function isRunRunning(status: string): boolean {
  return status === "running" || isRunningStatus(status);
}

function isNotFound(error: unknown): boolean {
  return Boolean(
    typeof error === "object" &&
      error !== null &&
      "response" in error &&
      (error as { response?: { status?: number } }).response?.status === 404
  );
}

function isUnauthorized(error: unknown): boolean {
  return Boolean(
    typeof error === "object" &&
      error !== null &&
      "response" in error &&
      (error as { response?: { status?: number } }).response?.status === 401
  );
}

function filenameFromDisposition(disposition: string | undefined): string | null {
  if (!disposition) {
    return null;
  }
  const match = disposition.match(/filename\*=UTF-8''([^;]+)/);
  return match ? decodeURIComponent(match[1]) : null;
}
</script>
