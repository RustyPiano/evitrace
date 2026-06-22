import { apiClient } from "@/api/client";
import type { RunModeMetadata } from "@/types/system";

interface SystemModeResponse {
  data: RunModeMetadata;
  message: string;
}

export async function getSystemMode(): Promise<RunModeMetadata> {
  const response = await apiClient.get<SystemModeResponse>("/system/mode");
  return response.data.data;
}
