<template>
  <section class="panel-surface">
    <el-empty v-if="!items.length" description="暂无时间线结果" />
    <template v-else>
      <div v-if="datedItems.length" class="timeline-list">
        <div v-for="item in datedItems" :key="item.event_id" class="timeline-item">
          <div class="timeline-time">{{ displayTime(item) }}</div>
          <div class="timeline-body">
            <h3>{{ item.title }}</h3>
            <p>{{ item.location || "地点未标注" }}</p>
            <div class="timeline-meta">
              <el-tag v-if="typeof item.confidence === 'number'" effect="plain" size="small">
                置信度 {{ Math.round(item.confidence * 100) }}%
              </el-tag>
              <el-button
                v-for="displayId in item.evidence_ids"
                :key="`${item.event_id}-${displayId}`"
                link
                type="primary"
                @click="emit('selectEvidence', displayId)"
              >
                {{ displayId }}
              </el-button>
            </div>
          </div>
        </div>
      </div>

      <section v-if="uncertainItems.length" class="uncertain-timeline">
        <h3>时间未确定</h3>
        <div v-for="item in uncertainItems" :key="item.event_id" class="timeline-item compact">
          <div class="timeline-body">
            <h3>{{ item.title }}</h3>
            <p>{{ item.time_text || "未提供原始时间" }} · {{ item.location || "地点未标注" }}</p>
            <div class="timeline-meta">
              <el-button
                v-for="displayId in item.evidence_ids"
                :key="`${item.event_id}-${displayId}`"
                link
                type="primary"
                @click="emit('selectEvidence', displayId)"
              >
                {{ displayId }}
              </el-button>
            </div>
          </div>
        </div>
      </section>
    </template>
  </section>
</template>

<script setup lang="ts">
import { computed } from "vue";

import type { TimelineItem } from "@/types/workbench";

const props = defineProps<{
  items: TimelineItem[];
}>();

const emit = defineEmits<{
  selectEvidence: [displayId: string];
}>();

const datedItems = computed(() =>
  props.items
    .filter((item) => Boolean(item.time_normalized))
    .slice()
    .sort((left, right) => timeKey(left) - timeKey(right))
);

const uncertainItems = computed(() => props.items.filter((item) => !item.time_normalized));

function timeKey(item: TimelineItem): number {
  const parsed = Date.parse(item.time_normalized ?? "");
  if (!Number.isNaN(parsed)) {
    return parsed;
  }
  return item.time_normalized?.localeCompare("") ?? 0;
}

function displayTime(item: TimelineItem): string {
  return item.time_normalized || item.time_text || "时间未确定";
}
</script>
