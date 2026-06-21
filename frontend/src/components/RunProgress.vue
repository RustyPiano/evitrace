<template>
  <section class="workbench-section">
    <div class="workbench-section-header">
      <h2>执行</h2>
      <span>{{ run ? runStatusLabel(run.status) : "尚未运行" }}</span>
    </div>

    <el-progress
      :percentage="run?.progress ?? 0"
      :status="progressStatus"
      :stroke-width="10"
    />

    <div class="run-step-list">
      <div
        v-for="step in steps"
        :key="step.key"
        class="run-step"
        :class="{ active: step.key === currentStepKey, done: step.done }"
      >
        <span>{{ step.label }}</span>
        <el-tag v-if="step.warningCount" type="warning" effect="plain" size="small">
          {{ step.warningCount }} warning
        </el-tag>
      </div>
    </div>

    <el-alert
      v-if="run?.error_message"
      type="error"
      :title="run.error_message"
      :closable="false"
      show-icon
    />
    <el-alert
      v-else-if="run?.warnings?.length"
      type="warning"
      :closable="false"
      show-icon
      title="运行警告"
    >
      <ul class="warning-list">
        <li v-for="warning in run.warnings" :key="warning">{{ warning }}</li>
      </ul>
    </el-alert>

    <div class="workbench-section-header plan-header">
      <h2>执行计划</h2>
      <span>只读</span>
    </div>
    <pre class="plan-json">{{ formattedPlan }}</pre>
  </section>
</template>

<script setup lang="ts">
import { computed } from "vue";

import type { RunStatus } from "@/types/workbench";
import { runStatusLabel } from "@/utils/status";

const props = defineProps<{
  run: RunStatus | null;
}>();

const stepOrder = ["parsing", "extracting", "detecting_conflicts", "generating_report"];
const stepLabels: Record<string, string> = {
  parsing: "解析",
  extracting: "提取",
  detecting_conflicts: "冲突",
  generating_report: "报告"
};

const currentStepKey = computed(() => {
  const current = props.run?.current_step;
  if (current === "queued") {
    return "parsing";
  }
  return current ?? "";
});

const currentStepIndex = computed(() => stepOrder.indexOf(currentStepKey.value));

const steps = computed(() =>
  stepOrder.map((key, index) => ({
    key,
    label: stepLabels[key],
    done: props.run?.status === "succeeded" || (currentStepIndex.value > index && currentStepIndex.value !== -1),
    warningCount: key === currentStepKey.value ? props.run?.warnings.length ?? 0 : 0
  }))
);

const progressStatus = computed(() => {
  if (props.run?.status === "failed") {
    return "exception";
  }
  if (props.run?.status === "succeeded") {
    return "success";
  }
  return undefined;
});

const formattedPlan = computed(() => {
  const plan = props.run?.plan_json;
  if (!plan) {
    return "暂无执行计划";
  }
  if (typeof plan === "string") {
    try {
      return JSON.stringify(JSON.parse(plan), null, 2);
    } catch {
      return plan;
    }
  }
  return JSON.stringify(plan, null, 2);
});
</script>
