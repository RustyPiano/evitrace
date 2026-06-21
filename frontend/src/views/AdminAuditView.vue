<template>
  <section class="content-panel">
    <div class="section-header">
      <div>
        <h1>审计日志</h1>
        <p>查看关键操作记录</p>
      </div>
      <el-button :loading="loading" @click="loadAuditLogs">刷新</el-button>
    </div>

    <el-alert v-if="errorMessage" :title="errorMessage" type="error" show-icon />
    <el-table v-loading="loading" :data="items" class="admin-table">
      <el-table-column label="时间" width="220">
        <template #default="{ row }: { row: AuditLogItem }">{{ formatDate(row.created_at) }}</template>
      </el-table-column>
      <el-table-column prop="username" label="用户" width="150" />
      <el-table-column prop="action" label="动作" width="180" />
      <el-table-column prop="resource_type" label="资源类型" width="120" />
      <el-table-column prop="resource_id" label="资源 ID" min-width="220" show-overflow-tooltip />
      <el-table-column label="详情" min-width="260">
        <template #default="{ row }: { row: AuditLogItem }">
          <pre class="audit-detail">{{ JSON.stringify(row.detail, null, 2) }}</pre>
        </template>
      </el-table-column>
    </el-table>
    <el-pagination
      class="admin-pagination"
      layout="prev, pager, next, sizes, total"
      :current-page="page"
      :page-size="pageSize"
      :page-sizes="[10, 20, 50, 100]"
      :total="total"
      @current-change="changePage"
      @size-change="changePageSize"
    />
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from "vue";

import { apiClient } from "@/api/client";
import { extractErrorMessage } from "@/utils/errors";
import { formatDate } from "@/utils/status";

interface AuditLogItem {
  id: string;
  user_id: string | null;
  username: string | null;
  action: string;
  resource_type: string | null;
  resource_id: string | null;
  detail: Record<string, unknown>;
  created_at: string | null;
}

const items = ref<AuditLogItem[]>([]);
const total = ref(0);
const page = ref(1);
const pageSize = ref(20);
const loading = ref(false);
const errorMessage = ref("");

onMounted(loadAuditLogs);

async function loadAuditLogs() {
  loading.value = true;
  errorMessage.value = "";
  try {
    const response = await apiClient.get<{
      data: { items: AuditLogItem[]; total: number; page: number; page_size: number };
    }>("/admin/audit-logs", {
      params: { page: page.value, page_size: pageSize.value }
    });
    items.value = response.data.data.items;
    total.value = response.data.data.total;
    page.value = response.data.data.page;
    pageSize.value = response.data.data.page_size;
  } catch (error) {
    errorMessage.value = extractErrorMessage(error, "加载审计日志失败");
  } finally {
    loading.value = false;
  }
}

function changePage(nextPage: number) {
  page.value = nextPage;
  loadAuditLogs();
}

function changePageSize(nextSize: number) {
  pageSize.value = nextSize;
  page.value = 1;
  loadAuditLogs();
}
</script>
