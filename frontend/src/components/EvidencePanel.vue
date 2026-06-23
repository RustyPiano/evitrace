<template>
  <aside class="evidence-panel">
    <el-empty v-if="!evidenceId" description="选择一条证据查看来源" />
    <el-skeleton v-else-if="loading" :rows="5" animated />
    <template v-else-if="evidence">
      <div class="evidence-panel-header">
        <div>
          <span>{{ evidence.display_id }}</span>
          <h2>{{ evidence.file.original_name }}</h2>
        </div>
        <el-tag effect="plain">{{ evidenceTypeLabel(evidence.evidence_type) }}</el-tag>
      </div>

      <p class="evidence-content">{{ evidence.content }}</p>

      <dl class="locator-list">
        <div v-for="item in locatorItems" :key="item.label">
          <dt>{{ item.label }}</dt>
          <dd>{{ item.value }}</dd>
        </div>
      </dl>

      <div v-if="mediaUrl && mediaKind === 'image'" class="source-preview">
        <img :src="mediaUrl" alt="source image" />
      </div>
      <div v-else-if="frameUrl" class="source-preview">
        <img :src="frameUrl" alt="video frame" />
        <video
          v-if="mediaUrl && mediaKind === 'video'"
          ref="mediaRef"
          class="source-player"
          :src="mediaUrl"
          controls
          @loadedmetadata="seekToLocator"
        />
      </div>
      <audio
        v-else-if="mediaUrl && mediaKind === 'audio'"
        ref="mediaRef"
        class="source-player"
        :src="mediaUrl"
        controls
        @loadedmetadata="seekToLocator"
      />
      <video
        v-else-if="mediaUrl && mediaKind === 'video'"
        ref="mediaRef"
        class="source-player"
        :src="mediaUrl"
        controls
        @loadedmetadata="seekToLocator"
      />
    </template>
    <el-alert
      v-else-if="loadError"
      :title="loadError.title"
      :type="loadError.type"
      :closable="false"
    />
    <el-alert v-else title="证据不存在或无权访问" type="warning" :closable="false" />
  </aside>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from "vue";

import { apiClient } from "@/api/client";

const props = defineProps<{
  evidenceId: string | null;
  runId: string | null;
}>();

interface TaskFile {
  id: string;
  original_name: string;
  modality: string;
}

interface EvidenceDetail {
  id: string;
  display_id: string;
  file_id: string;
  file: TaskFile;
  modality: string;
  evidence_type: string;
  content: string;
  locator: Record<string, unknown>;
}

interface EvidenceSource {
  locator: Record<string, unknown>;
  file_url: string;
  frame_url: string | null;
}

const evidence = ref<EvidenceDetail | null>(null);
const source = ref<EvidenceSource | null>(null);
const loading = ref(false);
const mediaUrl = ref<string | null>(null);
const frameUrl = ref<string | null>(null);
const mediaRef = ref<HTMLMediaElement | null>(null);
const loadError = ref<{ title: string; type: "warning" | "error" } | null>(null);

const evidenceTypeLabels: Record<string, string> = {
  paragraph: "文本段落",
  ocr: "图片文字",
  asr: "音频转写",
  video_frame_ocr: "视频帧文字",
  image_caption: "画面描述",
  video_frame_caption: "视频画面描述"
};

const mediaKind = computed(() => {
  if (!evidence.value) {
    return null;
  }
  if (evidence.value.modality === "image") {
    return "image";
  }
  if (evidence.value.modality === "audio") {
    return "audio";
  }
  if (
    evidence.value.modality === "video" &&
    (source.value?.locator.kind === "video_audio" || source.value?.locator.kind === "video_frame")
  ) {
    return "video";
  }
  return null;
});

const locatorItems = computed(() => {
  const locator = evidence.value?.locator ?? {};
  const items: Array<{ label: string; value: string }> = [];
  if (locator.kind) {
    items.push({ label: "定位类型", value: String(locator.kind) });
  }
  if (typeof locator.page === "number") {
    items.push({ label: "页码", value: String(locator.page) });
  }
  if (typeof locator.paragraph === "number") {
    items.push({ label: "段落", value: String(locator.paragraph) });
  }
  if (Array.isArray(locator.bbox)) {
    items.push({ label: "BBox", value: locator.bbox.join(", ") });
  }
  if (typeof locator.start_ms === "number" || typeof locator.end_ms === "number") {
    items.push({
      label: "时间段",
      value: `${formatMs(Number(locator.start_ms ?? 0))} - ${formatMs(Number(locator.end_ms ?? 0))}`
    });
  }
  if (typeof locator.timestamp_ms === "number") {
    items.push({ label: "帧时间", value: formatMs(locator.timestamp_ms) });
  }
  if (typeof locator.frame_path === "string") {
    items.push({ label: "关键帧", value: locator.frame_path });
  }
  return items;
});

watch(
  () => [props.evidenceId, props.runId] as const,
  async ([id]) => {
    releaseObjectUrls();
    evidence.value = null;
    source.value = null;
    loadError.value = null;
    if (!id) {
      return;
    }
    loading.value = true;
    try {
      const [detailResponse, sourceResponse] = await Promise.all([
        apiClient.get<{ data: EvidenceDetail }>(`/evidence/${id}`, {
          params: currentRunParams()
        }),
        apiClient.get<{ data: EvidenceSource }>(`/evidence/${id}/source`, {
          params: currentRunParams()
        })
      ]);
      evidence.value = detailResponse.data.data;
      source.value = sourceResponse.data.data;
      await loadPreviewAssets();
      await nextTick();
      seekToLocator();
    } catch (error) {
      loadError.value = classifyLoadError(error);
    } finally {
      loading.value = false;
    }
  },
  { immediate: true }
);

onBeforeUnmount(releaseObjectUrls);

async function loadPreviewAssets() {
  if (!source.value || !evidence.value) {
    return;
  }
  if (evidence.value.modality === "image" || evidence.value.modality === "video") {
    mediaUrl.value = await fetchProtectedBlob(source.value.file_url);
  }
  if (evidence.value.modality === "audio") {
    mediaUrl.value = await fetchProtectedBlob(source.value.file_url);
  }
  if (source.value.frame_url) {
    frameUrl.value = await fetchProtectedBlob(source.value.frame_url);
  }
}

async function fetchProtectedBlob(url: string): Promise<string> {
  const apiPath = url.startsWith("/api/v1") ? url.slice("/api/v1".length) : url;
  const response = await apiClient.get(apiPath, {
    params: currentRunParams(),
    responseType: "blob"
  });
  return URL.createObjectURL(response.data as Blob);
}

function currentRunParams(): { run_id: string } | undefined {
  return props.runId ? { run_id: props.runId } : undefined;
}

function seekToLocator() {
  const locator = source.value?.locator;
  if (!locator || !mediaRef.value) {
    return;
  }
  const targetMs =
    typeof locator.start_ms === "number"
      ? locator.start_ms
      : typeof locator.timestamp_ms === "number"
        ? locator.timestamp_ms
        : null;
  if (targetMs !== null) {
    mediaRef.value.currentTime = targetMs / 1000;
  }
}

function releaseObjectUrls() {
  if (mediaUrl.value) {
    URL.revokeObjectURL(mediaUrl.value);
  }
  if (frameUrl.value) {
    URL.revokeObjectURL(frameUrl.value);
  }
  mediaUrl.value = null;
  frameUrl.value = null;
}

function classifyLoadError(error: unknown): { title: string; type: "warning" | "error" } {
  if (typeof error === "object" && error !== null && "response" in error) {
    const response = (error as { response?: { status?: number } }).response;
    if (response?.status === 403 || response?.status === 404) {
      return { title: "证据不存在或无权访问", type: "warning" };
    }
  }
  return { title: "证据加载失败，请稍后重试", type: "error" };
}

function evidenceTypeLabel(type: string): string {
  return evidenceTypeLabels[type] ?? type;
}

function formatMs(value: number): string {
  const seconds = value / 1000;
  return `${seconds.toFixed(seconds >= 10 ? 1 : 2)}s`;
}
</script>
