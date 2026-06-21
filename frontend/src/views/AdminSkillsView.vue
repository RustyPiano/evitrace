<template>
  <section class="content-panel">
    <div class="section-header">
      <div>
        <h1>Skill 管理</h1>
        <p>查看内置 Skill 状态并管理可选能力</p>
      </div>
      <el-button :loading="loading" @click="loadSkills">刷新</el-button>
    </div>

    <el-alert v-if="errorMessage" :title="errorMessage" type="error" show-icon />
    <el-table v-loading="loading" :data="skills" class="admin-table">
      <el-table-column prop="name" label="名称" min-width="200" />
      <el-table-column prop="version" label="版本" width="120" />
      <el-table-column label="必需" width="100">
        <template #default="{ row }: { row: AdminSkill }">
          <el-tag :type="row.required ? 'warning' : 'info'" effect="plain">
            {{ row.required ? "required" : "optional" }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="启用" width="120">
        <template #default="{ row }: { row: AdminSkill }">
          <el-switch
            :model-value="row.enabled"
            :disabled="row.required || updatingId === row.skill_id"
            @change="toggleSkill(row, Boolean($event))"
          />
        </template>
      </el-table-column>
      <el-table-column label="最近健康状态" min-width="220">
        <template #default="{ row }: { row: AdminSkill }">
          <div class="health-cell">
            <el-tag :type="healthStatusTag(row.last_status)" effect="plain">
              {{ row.last_status }}
            </el-tag>
            <span>{{ row.last_error || "-" }}</span>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="更新时间" width="220">
        <template #default="{ row }: { row: AdminSkill }">{{ formatDate(row.updated_at) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="140" fixed="right">
        <template #default="{ row }: { row: AdminSkill }">
          <el-button
            link
            type="primary"
            :loading="checkingId === row.skill_id"
            @click="checkHealth(row)"
          >
            健康探测
          </el-button>
        </template>
      </el-table-column>
    </el-table>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from "vue";
import { ElMessage } from "element-plus";

import { apiClient } from "@/api/client";
import { extractErrorMessage } from "@/utils/errors";
import { formatDate, healthStatusTag } from "@/utils/status";

interface AdminSkill {
  skill_id: string;
  name: string;
  version: string;
  enabled: boolean;
  required: boolean;
  last_status: string;
  last_error: string | null;
  updated_at: string | null;
}

const skills = ref<AdminSkill[]>([]);
const loading = ref(false);
const updatingId = ref("");
const checkingId = ref("");
const errorMessage = ref("");

onMounted(loadSkills);

async function loadSkills() {
  loading.value = true;
  errorMessage.value = "";
  try {
    const response = await apiClient.get<{ data: AdminSkill[] }>("/admin/skills");
    skills.value = response.data.data;
  } catch (error) {
    errorMessage.value = extractErrorMessage(error, "加载 Skill 失败");
  } finally {
    loading.value = false;
  }
}

async function toggleSkill(skill: AdminSkill, enabled: boolean) {
  updatingId.value = skill.skill_id;
  try {
    await apiClient.patch(`/admin/skills/${skill.skill_id}`, { enabled });
    ElMessage.success("Skill 状态已更新");
    await loadSkills();
  } catch (error) {
    ElMessage.error(extractErrorMessage(error, "更新 Skill 失败"));
    await loadSkills();
  } finally {
    updatingId.value = "";
  }
}

async function checkHealth(skill: AdminSkill) {
  checkingId.value = skill.skill_id;
  try {
    await apiClient.post(`/admin/skills/${skill.skill_id}/health`);
    ElMessage.success("健康探测已完成");
    await loadSkills();
  } catch (error) {
    ElMessage.error(extractErrorMessage(error, "健康探测失败"));
  } finally {
    checkingId.value = "";
  }
}
</script>
