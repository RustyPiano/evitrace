<template>
  <section class="workbench-section">
    <div class="workbench-section-header">
      <h2>文件</h2>
      <span>{{ files.length }} 个</span>
    </div>

    <el-empty v-if="!files.length" description="尚未上传文件" />
    <div v-else class="file-list">
      <div v-for="file in files" :key="file.id" class="file-list-item">
        <div class="file-list-main">
          <strong :title="file.original_name">{{ file.original_name }}</strong>
          <span>{{ file.modality }} · {{ formatBytes(file.size_bytes) }}</span>
        </div>
        <div class="file-list-meta">
          <el-tag :type="fileStatusTag(file.status)" effect="plain" size="small">
            {{ fileStatusLabel(file.status) }}
          </el-tag>
          <el-button
            link
            type="danger"
            :disabled="running || deletingId === file.id"
            :loading="deletingId === file.id"
            @click="confirmDelete(file)"
          >
            删除
          </el-button>
        </div>
        <p v-if="file.error_message" class="file-error">{{ file.error_message }}</p>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";

import { apiClient } from "@/api/client";
import type { TaskFile } from "@/types/workbench";
import { extractErrorMessage } from "@/utils/errors";
import { fileStatusLabel, fileStatusTag, formatBytes } from "@/utils/status";

defineProps<{
  files: TaskFile[];
  running: boolean;
}>();

const emit = defineEmits<{
  deleted: [];
}>();

const deletingId = ref("");

async function confirmDelete(file: TaskFile) {
  await ElMessageBox.confirm(`确认删除文件「${file.original_name}」？`, "删除文件", {
    type: "warning",
    confirmButtonText: "删除",
    cancelButtonText: "取消"
  });
  deletingId.value = file.id;
  try {
    await apiClient.delete(`/files/${file.id}`);
    ElMessage.success("文件已删除");
    emit("deleted");
  } catch (error) {
    ElMessage.error(extractErrorMessage(error, "删除文件失败"));
  } finally {
    deletingId.value = "";
  }
}
</script>
