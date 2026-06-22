<template>
  <section class="upload-panel">
    <div class="upload-toolbar">
      <div>
        <h2>上传资料</h2>
        <p>txt, md, pdf, docx, jpg, jpeg, png, wav, mp3, m4a, mp4 · {{ uploadLimitText }}</p>
      </div>
      <div class="upload-actions">
        <input
          ref="fileInput"
          class="file-input"
          type="file"
          multiple
          :accept="acceptedExtensions"
          @change="handleFileChange"
        />
        <el-button @click="fileInput?.click()">选择文件</el-button>
        <el-button type="primary" :disabled="!pendingFiles.length || uploading" @click="uploadFiles">
          上传
        </el-button>
      </div>
    </div>

    <el-table v-if="items.length" :data="items" class="upload-table">
      <el-table-column prop="name" label="文件名" min-width="220" />
      <el-table-column label="大小" width="120">
        <template #default="{ row }: { row: UploadItem }">{{ formatBytes(row.size) }}</template>
      </el-table-column>
      <el-table-column label="状态" width="120">
        <template #default="{ row }: { row: UploadItem }">
          <el-tag :type="statusTag(row.status)" effect="plain">{{ statusText(row.status) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="message" label="结果" min-width="220" />
    </el-table>

    <el-empty v-else description="尚未选择文件" />
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue";

import { apiClient } from "@/api/client";

const props = defineProps<{
  taskId: string;
}>();

const emit = defineEmits<{
  uploaded: [];
}>();

type UploadStatus = "pending" | "uploading" | "success" | "error";

interface UploadItem {
  id: string;
  file: File;
  name: string;
  size: number;
  status: UploadStatus;
  message: string;
}

const maxUploadMb = ref<number | null>(null);
const acceptedExtensions = ".txt,.md,.pdf,.docx,.jpg,.jpeg,.png,.wav,.mp3,.m4a,.mp4";
const fileInput = ref<HTMLInputElement | null>(null);
const items = ref<UploadItem[]>([]);
const uploading = ref(false);
const pendingFiles = computed(() => items.value.filter((item) => item.status === "pending"));
const uploadLimitText = computed(() =>
  maxUploadMb.value === null ? "最大上传大小以后端配置为准" : `最大 ${maxUploadMb.value} MB`
);

onMounted(loadPublicConfig);

async function loadPublicConfig() {
  try {
    const response = await apiClient.get<{ data: { max_upload_mb: number } }>("/config");
    maxUploadMb.value = response.data.data.max_upload_mb;
  } catch {
    maxUploadMb.value = null;
  }
}

function handleFileChange(event: Event) {
  const input = event.target as HTMLInputElement;
  const selected = Array.from(input.files ?? []);
  items.value.push(
    ...selected.map((file) => ({
      id: `${file.name}-${file.size}-${file.lastModified}-${crypto.randomUUID()}`,
      file,
      name: file.name,
      size: file.size,
      status: "pending" as const,
      message: "待上传"
    }))
  );
  input.value = "";
}

async function uploadFiles() {
  uploading.value = true;
  try {
    for (const item of pendingFiles.value) {
      item.status = "uploading";
      item.message = "上传中";
      const formData = new FormData();
      formData.append("files", item.file, item.file.name);
      try {
        await apiClient.post(`/tasks/${props.taskId}/files`, formData, {
          headers: { "Content-Type": "multipart/form-data" }
        });
        item.status = "success";
        item.message = "已上传";
        emit("uploaded");
      } catch (error) {
        item.status = "error";
        item.message = extractErrorMessage(error);
      }
    }
  } finally {
    uploading.value = false;
  }
}

function extractErrorMessage(error: unknown): string {
  if (typeof error === "object" && error !== null && "response" in error) {
    const response = (error as { response?: { data?: { detail?: { message?: string } } } }).response;
    return response?.data?.detail?.message ?? "上传失败";
  }
  return "上传失败";
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

function statusTag(status: UploadStatus) {
  const tags: Record<UploadStatus, "info" | "primary" | "success" | "danger"> = {
    pending: "info",
    uploading: "primary",
    success: "success",
    error: "danger"
  };
  return tags[status];
}

function statusText(status: UploadStatus): string {
  const labels: Record<UploadStatus, string> = {
    pending: "待上传",
    uploading: "上传中",
    success: "成功",
    error: "失败"
  };
  return labels[status];
}
</script>
