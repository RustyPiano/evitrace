export type RunMode = "real" | "mock" | "hybrid";

export interface SkillVersion {
  id: string;
  name: string;
  version: string;
}

export interface RunModeComponent {
  real: boolean;
  model?: string | null;
}

export interface RunModeSource {
  real: boolean;
  source: "http" | "lib" | "fixture";
}

export interface RunModeMetadata {
  mode: RunMode;
  mode_label: string;
  mock_llm: boolean;
  mock_media: boolean;
  mock_vision: boolean;
  llm: RunModeComponent;
  vision: RunModeComponent;
  ocr: RunModeSource;
  asr: RunModeSource;
  skills: SkillVersion[];
}
