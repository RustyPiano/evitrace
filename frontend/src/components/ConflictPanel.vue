<template>
  <section class="panel-surface">
    <div class="panel-toolbar">
      <el-segmented v-model="typeFilter" :options="filterOptions" />
      <span>{{ filteredConflicts.length }} / {{ conflicts.length }}</span>
    </div>

    <el-empty v-if="!conflicts.length" description="未发现规则范围内冲突" />
    <el-empty v-else-if="!filteredConflicts.length" description="当前筛选无冲突" />
    <div v-else class="conflict-list">
      <article v-for="conflict in filteredConflicts" :key="conflict.conflict_id" class="conflict-card">
        <header>
          <div>
            <el-tag effect="plain">{{ conflictTypeLabel(conflict.type) }}</el-tag>
            <strong>{{ conflict.conflict_id }}</strong>
          </div>
          <el-select
            :model-value="conflict.status"
            size="small"
            :disabled="running"
            :loading="updatingId === conflict.conflict_id"
            @change="updateStatus(conflict.conflict_id, String($event))"
          >
            <el-option label="待审核" value="unreviewed" />
            <el-option label="已确认" value="confirmed" />
            <el-option label="已忽略" value="ignored" />
          </el-select>
        </header>

        <p>{{ conflict.description }}</p>

        <div class="conflict-sides">
          <div class="conflict-side">
            <span>左侧</span>
            <strong>{{ conflict.left.value }}</strong>
            <small>{{ conflict.left.event_id }}</small>
            <div>
              <el-button
                v-for="displayId in conflict.left.evidence_ids"
                :key="`${conflict.conflict_id}-left-${displayId}`"
                link
                type="primary"
                @click="emit('selectEvidence', displayId)"
              >
                {{ displayId }}
              </el-button>
            </div>
          </div>
          <div class="conflict-side">
            <span>右侧</span>
            <strong>{{ conflict.right.value }}</strong>
            <small>{{ conflict.right.event_id }}</small>
            <div>
              <el-button
                v-for="displayId in conflict.right.evidence_ids"
                :key="`${conflict.conflict_id}-right-${displayId}`"
                link
                type="primary"
                @click="emit('selectEvidence', displayId)"
              >
                {{ displayId }}
              </el-button>
            </div>
          </div>
        </div>
      </article>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, ref } from "vue";
import { ElMessage } from "element-plus";

import { apiClient } from "@/api/client";
import type { AnalysisConflict } from "@/types/workbench";
import { extractErrorMessage } from "@/utils/errors";
import { conflictTypeLabel } from "@/utils/status";

const props = defineProps<{
  taskId: string;
  conflicts: AnalysisConflict[];
  running: boolean;
}>();

const emit = defineEmits<{
  selectEvidence: [displayId: string];
  updated: [];
}>();

const typeFilter = ref("all");
const updatingId = ref("");
const filterOptions = [
  { label: "全部", value: "all" },
  { label: "时间", value: "time" },
  { label: "地点", value: "location" },
  { label: "数量", value: "quantity" }
];

const filteredConflicts = computed(() => {
  if (typeFilter.value === "all") {
    return props.conflicts;
  }
  return props.conflicts.filter((conflict) => conflict.type === typeFilter.value);
});

async function updateStatus(conflictId: string, status: string) {
  updatingId.value = conflictId;
  try {
    await apiClient.patch(`/tasks/${props.taskId}/conflicts/${conflictId}`, { status });
    ElMessage.success("冲突状态已更新");
    emit("updated");
  } catch (error) {
    ElMessage.error(extractErrorMessage(error, "更新冲突状态失败"));
  } finally {
    updatingId.value = "";
  }
}
</script>
