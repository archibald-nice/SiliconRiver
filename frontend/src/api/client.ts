import axios from "axios";

// 当 VITE_API_BASE 为空时，使用相对路径（反向代理模式）
// 当 VITE_API_BASE 有值时，使用绝对 URL（直接访问模式）
const baseURL = import.meta.env.VITE_API_BASE || "";

export const API_BASE_URL = baseURL;

export const api = axios.create({
  baseURL: baseURL || "/",  // 空字符串时默认为相对路径
});

export const buildProviderAvatarUrl = (provider: string) => {
  const path = `/api/providers/${encodeURIComponent(provider)}/avatar`;
  // 如果 API_BASE_URL 为空，直接返回相对路径（反向代理模式）
  if (!API_BASE_URL) {
    return path;
  }
  // 否则拼接绝对 URL
  return new URL(path, API_BASE_URL).toString();
};

/** @deprecated 归档：模型列表视图已下线，接口保留以兼容历史用例。 */
export interface ModelSummary {
  model_id: string;
  provider: string;
  model_name: string;
  description?: string;
  tags: string[];
  created_at: string;
  downloads?: number;
  likes?: number;
  model_card_url: string;
}

export interface ModelListResponse {
  items: ModelSummary[];
  total: number;
  page: number;
  page_size: number;
}

export interface ProviderStat {
  provider: string;
  model_count: number;
}

export interface TimelineModel {
  model_id: string;
  provider: string;
  model_name: string;
  description?: string;
  created_at: string;
  model_card_url: string;
  tags: string[];
  avatar_url?: string;
  is_open_source?: boolean | null;
  price?: Record<string, unknown> | string | null;
  opencompass_rank?: number | null;
  huggingface_rank?: number | null;
  analysis_summary?: string;
}

export interface TimelineResponse {
  items: TimelineModel[];
  total: number;
  page: number;
  page_size: number;
  start: string;
  end: string;
  preset: string;
  label: string;
}

export interface ModelAnalysis {
  model_id: string;
  analysis_summary?: string;
  key_features: string[];
  use_cases: string[];
  performance_metrics?: Record<string, unknown>;
  llm_model_used?: string;
  analyzed_at?: string;
  tags: string[];
}

export interface AnalyzedModelsResponse {
  items: ModelAnalysis[];
  total: number;
  page: number;
  page_size: number;
}

export interface AnalysisStats {
  total_models: number;
  analyzed_models: number;
  unanalyzed_models: number;
  analysis_rate: number;
}

/** @deprecated 归档：模型列表视图已下线，接口保留以兼容历史用例。 */
export const fetchModels = async (params: Record<string, unknown>) => {
  const { data } = await api.get<ModelListResponse>("/api/models", { params });
  return data;
};

/** @deprecated 归档：厂商统计面板已下线，接口保留以兼容历史用例。 */
export const fetchStats = async () => {
  const { data } = await api.get<ProviderStat[]>("/api/stats/providers");
  return data;
};

export const fetchTimeline = async (params: {
  preset?: string;
  year?: number | null;
  page?: number;
  page_size?: number;
  sort?: "asc" | "desc";
  provider?: string | null;
  model_name?: string;
  open_source?: boolean | null;
}) => {
  const query: Record<string, unknown> = {};
  if (params.preset) {
    query.preset = params.preset;
  }
  if (typeof params.year === "number") {
    query.year = params.year;
  }
  if (typeof params.page === "number") {
    query.page = params.page;
  }
  if (typeof params.page_size === "number") {
    query.page_size = params.page_size;
  }
  if (params.sort) {
    query.sort = params.sort;
  }
  if (params.provider) {
    query.provider = params.provider;
  }
  if (params.model_name) {
    query.model_name = params.model_name;
  }
  if (typeof params.open_source === "boolean") {
    query.open_source = params.open_source ? "true" : "false";
  }
  const { data } = await api.get<TimelineResponse>("/api/timeline", { params: query });
  return data;
};

/**
 * 获取单个模型的AI分析结果。
 * @param modelId 模型ID (格式: provider/model_name)
 */
export const fetchModelAnalysis = async (modelId: string) => {
  const { data } = await api.post<ModelAnalysis>("/api/models/analysis", { model_id: modelId });
  return data;
};

/**
 * 获取已分析的模型列表。
 */
export const fetchAnalyzedModels = async (params: {
  page?: number;
  page_size?: number;
  provider?: string;
  feature?: string;
  search?: string;
}) => {
  const query: Record<string, unknown> = {};
  if (typeof params.page === "number") {
    query.page = params.page;
  }
  if (typeof params.page_size === "number") {
    query.page_size = params.page_size;
  }
  if (params.provider) {
    query.provider = params.provider;
  }
  if (params.feature) {
    query.feature = params.feature;
  }
  if (params.search) {
    query.search = params.search;
  }
  const { data } = await api.get<AnalyzedModelsResponse>("/api/models/analyzed", { params: query });
  return data;
};

/**
 * 获取AI分析统计信息。
 */
export const fetchAnalysisStats = async (provider?: string) => {
  const query: Record<string, unknown> = {};
  if (provider) {
    query.provider = provider;
  }
  const { data } = await api.get<AnalysisStats>("/api/analysis/stats", { params: query });
  return data;
};

/**
 * 获取所有可用的分析标签。
 */
export const fetchAnalysisTags = async () => {
  const { data } = await api.get<{ tags: string[] }>("/api/analysis/tags");
  return data.tags;
};
