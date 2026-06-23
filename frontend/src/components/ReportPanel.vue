<template>
  <section class="panel-surface">
    <div v-if="reportMarkdown || hasCitationCheck" class="report-toolbar">
      <div v-if="hasCitationCheck" class="citation-summary">
        <el-tag
          :type="invalidCitations.length ? 'danger' : 'success'"
          effect="plain"
        >
          无效引用 {{ invalidCitations.length }}
        </el-tag>
        <el-tag :type="coverage < 0.9 ? 'warning' : 'success'" effect="plain">
          引用覆盖 {{ formatPercent(coverage) }}
        </el-tag>
        <el-tag v-if="fieldExplicitRatio !== null" type="info" effect="plain">
          字段显式引用 {{ formatPercent(fieldExplicitRatio) }}
        </el-tag>
      </div>
      <div class="report-actions">
        <el-button
          v-if="hasCitationCheck"
          :loading="regenerating"
          :disabled="running"
          @click="regenerateReport"
        >
          重新生成报告
        </el-button>
        <el-button v-if="reportMarkdown" type="primary" :loading="downloading" @click="downloadReport">
          下载 Markdown
        </el-button>
      </div>
    </div>

    <el-alert
      v-if="hasCitationCheck && coverage < 0.9"
      type="warning"
      :closable="false"
      show-icon
      title="引用覆盖率低于 90%，普通用户不能标记完成；管理员需强制确认。"
    />
    <el-alert
      v-if="invalidCitations.length"
      type="error"
      :closable="false"
      show-icon
      title="报告存在无效证据编号，需重新生成或复核。"
    />

    <el-empty v-if="!reportMarkdown" :description="emptyReason" />
    <article
      v-else
      class="report-markdown"
      v-html="renderedReport"
      @click="handleCitationClick"
    ></article>
  </section>
</template>

<script setup lang="ts">
import { computed, ref } from "vue";
import { ElMessage } from "element-plus";

import { apiClient } from "@/api/client";
import type { CitationCheck } from "@/types/workbench";
import { extractErrorMessage } from "@/utils/errors";
import { formatPercent } from "@/utils/status";

const props = defineProps<{
  taskId: string;
  reportMarkdown: string | null;
  citationCheck: CitationCheck | null;
  running: boolean;
  analysisComplete: boolean;
  runId: string | null;
}>();

const emit = defineEmits<{
  selectEvidence: [displayId: string];
  regenerated: [];
}>();

const regenerating = ref(false);
const downloading = ref(false);

const hasCitationCheck = computed(() => props.analysisComplete && props.citationCheck !== null);
const invalidCitations = computed(() => props.citationCheck?.invalid_citations ?? []);
const invalidCitationSet = computed(() => new Set(invalidCitations.value));
const coverage = computed(() => props.citationCheck?.citation_coverage ?? 0);
const fieldExplicitRatio = computed(() => props.citationCheck?.field_explicit_ratio ?? null);
const renderedReport = computed(() => renderMarkdown(props.reportMarkdown ?? "", invalidCitationSet.value));
const emptyReason = computed(() => {
  if (props.running) {
    return "分析运行中，报告尚未生成";
  }
  if (!props.analysisComplete) {
    return "分析未完成，暂无报告内容";
  }
  return "报告生成失败或内容为空，请重新生成报告";
});

async function regenerateReport() {
  regenerating.value = true;
  try {
    await apiClient.post(`/tasks/${props.taskId}/report/regenerate`, undefined, {
      params: currentRunParams()
    });
    ElMessage.success("报告已重新生成");
    emit("regenerated");
  } catch (error) {
    ElMessage.error(extractErrorMessage(error, "重新生成报告失败"));
  } finally {
    regenerating.value = false;
  }
}

async function downloadReport() {
  downloading.value = true;
  try {
    const response = await apiClient.get(`/tasks/${props.taskId}/report/download`, {
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

function currentRunParams(): { run_id: string } | undefined {
  return props.runId ? { run_id: props.runId } : undefined;
}

function handleCitationClick(event: MouseEvent) {
  const target = event.target instanceof HTMLElement ? event.target : null;
  const button = target?.closest<HTMLButtonElement>("[data-citation]");
  const displayId = button?.dataset.citation;
  if (displayId) {
    emit("selectEvidence", displayId);
  }
}

function filenameFromDisposition(disposition: string | undefined): string | null {
  if (!disposition) {
    return null;
  }
  const match = disposition.match(/filename\*=UTF-8''([^;]+)/);
  return match ? decodeURIComponent(match[1]) : null;
}

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function renderInlineMarkdown(value: string, invalidSet: Set<string>): string {
  return escapeHtml(value)
    .replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>")
    .replace(/\[(E-\d{4,})\]/g, (_match, displayId: string) => {
      const invalidClass = invalidSet.has(displayId) ? " invalid" : "";
      return `<button type="button" class="citation-button${invalidClass}" data-citation="${displayId}">[${displayId}]</button>`;
    });
}

function renderMarkdown(markdown: string, invalidSet: Set<string>): string {
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
      output.push(`<li>${renderInlineMarkdown(line.slice(2), invalidSet)}</li>`);
      continue;
    }
    closeList();
    if (line.startsWith("### ")) {
      output.push(`<h3>${renderInlineMarkdown(line.slice(4), invalidSet)}</h3>`);
    } else if (line.startsWith("## ")) {
      output.push(`<h2>${renderInlineMarkdown(line.slice(3), invalidSet)}</h2>`);
    } else if (line.startsWith("# ")) {
      output.push(`<h1>${renderInlineMarkdown(line.slice(2), invalidSet)}</h1>`);
    } else {
      output.push(`<p>${renderInlineMarkdown(line, invalidSet)}</p>`);
    }
  }
  closeList();
  return output.join("");
}
</script>
