<template>
  <section class="content-panel">
    <div class="section-header">
      <div>
        <h1>用户管理</h1>
        <p>管理分析员与管理员账号状态</p>
      </div>
      <el-button type="primary" @click="openCreateDialog">新建用户</el-button>
    </div>

    <el-alert v-if="errorMessage" :title="errorMessage" type="error" show-icon />
    <el-table v-loading="loading" :data="users" class="admin-table">
      <el-table-column prop="username" label="用户名" min-width="180" />
      <el-table-column label="角色" width="180">
        <template #default="{ row }: { row: AdminUser }">
          <el-select
            :model-value="row.role"
            size="small"
            :disabled="isSelf(row) || wouldRemoveLastAdmin(row)"
            @change="changeRole(row, String($event))"
          >
            <el-option label="分析员" value="analyst" />
            <el-option label="管理员" value="admin" />
          </el-select>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="150">
        <template #default="{ row }: { row: AdminUser }">
          <el-switch
            :model-value="row.is_active"
            :disabled="isSelf(row) || wouldRemoveLastAdmin(row)"
            active-text="启用"
            inactive-text="停用"
            @change="updateUser(row, { is_active: Boolean($event) })"
          />
        </template>
      </el-table-column>
      <el-table-column label="创建时间" width="220">
        <template #default="{ row }: { row: AdminUser }">{{ formatDate(row.created_at) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="140" fixed="right">
        <template #default="{ row }: { row: AdminUser }">
          <el-button link type="primary" @click="resetPassword(row)">重置密码</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="createDialogVisible" title="新建用户" width="420px">
      <el-form :model="createForm" label-position="top" @submit.prevent>
        <el-form-item label="用户名">
          <el-input v-model="createForm.username" maxlength="100" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input v-model="createForm.password" type="password" show-password />
        </el-form-item>
        <el-form-item label="角色">
          <el-select v-model="createForm.role">
            <el-option label="分析员" value="analyst" />
            <el-option label="管理员" value="admin" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="createUser">创建</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";

import { apiClient } from "@/api/client";
import { useAuthStore } from "@/stores/auth";
import { extractErrorMessage } from "@/utils/errors";
import { formatDate } from "@/utils/status";

interface AdminUser {
  id: string;
  username: string;
  role: AdminRole;
  is_active: boolean;
  created_at: string | null;
}

type AdminRole = "analyst" | "admin";
type AdminUserPatch = Partial<Pick<AdminUser, "role" | "is_active">> & { password?: string };

const authStore = useAuthStore();
const users = ref<AdminUser[]>([]);
const loading = ref(false);
const submitting = ref(false);
const errorMessage = ref("");
const createDialogVisible = ref(false);
const createForm = reactive<{ username: string; password: string; role: AdminRole }>({
  username: "",
  password: "",
  role: "analyst"
});
const activeAdminCount = computed(
  () => users.value.filter((user) => user.role === "admin" && user.is_active).length
);

onMounted(loadUsers);

async function loadUsers() {
  loading.value = true;
  errorMessage.value = "";
  try {
    const response = await apiClient.get<{ data: AdminUser[] }>("/admin/users");
    users.value = response.data.data;
  } catch (error) {
    errorMessage.value = extractErrorMessage(error, "加载用户失败");
  } finally {
    loading.value = false;
  }
}

function openCreateDialog() {
  createForm.username = "";
  createForm.password = "";
  createForm.role = "analyst";
  createDialogVisible.value = true;
}

async function createUser() {
  if (!createForm.username.trim() || !createForm.password) {
    ElMessage.warning("请输入用户名和密码");
    return;
  }
  submitting.value = true;
  try {
    await apiClient.post("/admin/users", createForm);
    ElMessage.success("用户已创建");
    createDialogVisible.value = false;
    await loadUsers();
  } catch (error) {
    ElMessage.error(extractErrorMessage(error, "创建用户失败"));
  } finally {
    submitting.value = false;
  }
}

async function updateUser(user: AdminUser, patch: AdminUserPatch) {
  try {
    await apiClient.patch(`/admin/users/${user.id}`, patch);
    ElMessage.success("用户已更新");
    await loadUsers();
  } catch (error) {
    ElMessage.error(extractErrorMessage(error, "更新用户失败"));
    await loadUsers();
  }
}

async function changeRole(user: AdminUser, role: string) {
  if (role !== "analyst" && role !== "admin") {
    return;
  }
  await updateUser(user, { role });
}

async function resetPassword(user: AdminUser) {
  const result = await ElMessageBox.prompt(`为「${user.username}」设置新密码`, "重置密码", {
    confirmButtonText: "重置",
    cancelButtonText: "取消",
    inputType: "password",
    inputValidator: (value) => Boolean(value) || "请输入新密码"
  });
  await updateUser(user, { password: result.value });
}

function isSelf(user: AdminUser): boolean {
  return user.id === authStore.user?.id;
}

function wouldRemoveLastAdmin(user: AdminUser): boolean {
  return user.role === "admin" && user.is_active && activeAdminCount.value <= 1;
}
</script>
