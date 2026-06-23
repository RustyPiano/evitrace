export type RunMode = "real" | "mock" | "hybrid";
export type DeploymentMode = "local" | "remote" | "mixed";
export type ComponentDeployment = "local" | "remote";

export interface SkillVersion {
  id: string;
  name: string;
  version: string;
}

export interface RunModeComponent {
  real: boolean;
  model?: string | null;
  deployment?: ComponentDeployment | null;
}

export interface RunModeSource {
  real: boolean;
  source: "http" | "lib" | "fixture";
  deployment?: ComponentDeployment | null;
}

export interface RunModeMetadata {
  mode: RunMode;
  execution_mode: RunMode;
  mode_label: string;
  deployment_mode: DeploymentMode | null;
  mock_llm: boolean;
  mock_media: boolean;
  mock_vision: boolean;
  llm: RunModeComponent;
  vision: RunModeComponent;
  ocr: RunModeSource;
  asr: RunModeSource;
  skills: SkillVersion[];
}
