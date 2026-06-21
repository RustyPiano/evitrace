export type ElementTagType = "primary" | "success" | "warning" | "info" | "danger";

export const taskStatusOptions = [
  { value: "draft", label: "草稿" },
  { value: "ready", label: "可分析" },
  { value: "queued", label: "排队中" },
  { value: "parsing", label: "解析中" },
  { value: "extracting", label: "提取中" },
  { value: "detecting_conflicts", label: "冲突检测" },
  { value: "generating_report", label: "生成报告" },
  { value: "awaiting_review", label: "待审核" },
  { value: "completed", label: "已完成" },
  { value: "failed", label: "失败" }
];

export const runningTaskStatuses = [
  "queued",
  "parsing",
  "extracting",
  "detecting_conflicts",
  "generating_report"
];

export function isRunningStatus(status: string): boolean {
  return runningTaskStatuses.includes(status);
}

export function taskStatusLabel(status: string): string {
  return taskStatusOptions.find((option) => option.value === status)?.label ?? status;
}

export function taskStatusTag(status: string): ElementTagType {
  if (status === "failed") {
    return "danger";
  }
  if (status === "completed") {
    return "success";
  }
  if (status === "awaiting_review") {
    return "warning";
  }
  if (runningTaskStatuses.includes(status)) {
    return "primary";
  }
  if (status === "ready") {
    return "success";
  }
  return "info";
}

export function fileStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    uploaded: "待解析",
    parsing: "解析中",
    parsed: "已解析",
    warning: "有警告",
    failed: "失败"
  };
  return labels[status] ?? status;
}

export function fileStatusTag(status: string): ElementTagType {
  if (status === "failed") {
    return "danger";
  }
  if (status === "warning") {
    return "warning";
  }
  if (status === "parsed") {
    return "success";
  }
  if (status === "parsing") {
    return "primary";
  }
  return "info";
}

export function runStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    queued: "排队中",
    running: "运行中",
    succeeded: "已完成",
    failed: "失败"
  };
  return labels[status] ?? status;
}

export function runStepLabel(step: string | null | undefined): string {
  const labels: Record<string, string> = {
    queued: "排队",
    parsing: "解析",
    extracting: "提取",
    detecting_conflicts: "冲突",
    generating_report: "报告",
    awaiting_review: "待审核",
    failed: "失败"
  };
  return step ? labels[step] ?? step : "-";
}

export function conflictTypeLabel(type: string): string {
  const labels: Record<string, string> = {
    time: "时间",
    location: "地点",
    quantity: "数量"
  };
  return labels[type] ?? type;
}

export function conflictStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    unreviewed: "待审核",
    confirmed: "已确认",
    ignored: "已忽略"
  };
  return labels[status] ?? status;
}

export function healthStatusTag(status: string): ElementTagType {
  if (status === "healthy") {
    return "success";
  }
  if (status === "skipped") {
    return "info";
  }
  return "danger";
}

export function formatDate(value: string | null | undefined): string {
  if (!value) {
    return "-";
  }
  return new Date(value).toLocaleString();
}

export function formatBytes(value: number): string {
  if (value < 1024) {
    return `${value} B`;
  }
  if (value < 1024 * 1024) {
    return `${(value / 1024).toFixed(1)} KB`;
  }
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

export function formatPercent(value: number | null | undefined): string {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return "-";
  }
  return `${Math.round(value * 100)}%`;
}
