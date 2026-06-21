import { createRouter, createWebHistory } from "vue-router";

import AppLayout from "@/components/AppLayout.vue";
import AdminPlaceholderView from "@/views/AdminPlaceholderView.vue";
import TaskDetailView from "@/views/TaskDetailView.vue";
import LoginView from "@/views/LoginView.vue";
import NewTaskView from "@/views/NewTaskView.vue";
import TaskListView from "@/views/TaskListView.vue";
import { useAuthStore } from "@/stores/auth";

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: "/",
      redirect: "/tasks"
    },
    {
      path: "/login",
      name: "login",
      component: LoginView
    },
    {
      path: "/tasks",
      component: AppLayout,
      meta: { requiresAuth: true },
      children: [
        {
          path: "",
          name: "tasks",
          component: TaskListView,
          meta: { requiresAuth: true }
        },
        {
          path: "new",
          name: "tasks-new",
          component: NewTaskView,
          meta: { requiresAuth: true }
        },
        {
          path: ":id",
          name: "task-detail",
          component: TaskDetailView,
          meta: { requiresAuth: true }
        }
      ]
    },
    {
      path: "/admin",
      component: AppLayout,
      meta: { requiresAuth: true, adminOnly: true },
      children: [
        {
          path: "users",
          name: "admin-users",
          component: AdminPlaceholderView,
          meta: { requiresAuth: true, adminOnly: true, title: "用户管理" }
        },
        {
          path: "skills",
          name: "admin-skills",
          component: AdminPlaceholderView,
          meta: { requiresAuth: true, adminOnly: true, title: "Skill 管理" }
        },
        {
          path: "health",
          name: "admin-health",
          component: AdminPlaceholderView,
          meta: { requiresAuth: true, adminOnly: true, title: "健康状态" }
        },
        {
          path: "audit",
          name: "admin-audit",
          component: AdminPlaceholderView,
          meta: { requiresAuth: true, adminOnly: true, title: "审计日志" }
        }
      ]
    }
  ]
});

router.beforeEach(async (to) => {
  const authStore = useAuthStore();
  const requiresAuth = to.matched.some((route) => route.meta.requiresAuth);
  const adminOnly = to.matched.some((route) => route.meta.adminOnly);

  if (to.path === "/login" && authStore.token) {
    return "/tasks";
  }

  if (!requiresAuth) {
    return true;
  }

  if (!authStore.token) {
    return { path: "/login", query: { redirect: to.fullPath } };
  }

  if (!authStore.user) {
    try {
      await authStore.fetchMe();
    } catch {
      return { path: "/login", query: { redirect: to.fullPath } };
    }
  }

  if (adminOnly && !authStore.isAdmin) {
    return "/tasks";
  }

  return true;
});
