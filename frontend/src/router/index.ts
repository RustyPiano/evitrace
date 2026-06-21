import { createRouter, createWebHistory } from "vue-router";

import AppLayout from "@/components/AppLayout.vue";
import LoginView from "@/views/LoginView.vue";
import TaskListView from "@/views/TaskListView.vue";

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
      children: [
        {
          path: "",
          name: "tasks",
          component: TaskListView
        }
      ]
    }
  ]
});
