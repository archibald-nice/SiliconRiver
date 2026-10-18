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

/**
 * 把后端路径拼成可直接请求的 URL。
 * - API_BASE_URL 为空：返回相对路径（同域部署，如 Vercel Services 把 /api 路由到后端）
 * - API_BASE_URL 有值：拼成绝对 URL（前后端分域部署）
 */
export const buildApiUrl = (path: string) => {
  if (!API_BASE_URL) {
    return path;
  }
  return new URL(path, API_BASE_URL).toString();
};

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
  /**
   * 库里的展示用厂商名（`models.provider`，如 `aionlabs` / `spacexai` / `meta`）。
   * 与 `model_id` 前缀（仓库组织名，如 `aion-labs` / `x-ai` / `meta-llama`）**不是一回事**，
   * 头像接口与左侧厂商筛选器都按这个值匹配（ISSUE-016）。
   * 可选：后端补字段前的旧响应里没有，调用方需要退回 `model_id` 前缀兜底。
   */
  provider?: string;
  analysis_summary?: string;
  key_features: string[];
  use_cases: string[];
  performance_metrics?: Record<string, unknown>;
  llm_model_used?: string;
  analyzed_at?: string;
  tags: string[];
  // 里程碑字段：与 backend/models.py 的 ModelAnalysis 对齐
  is_milestone?: boolean;
  milestone_features?: string | null;
  updated_at?: string;
}

export interface AnalyzedModelsResponse {
  items: ModelAnalysis[];
  total: number;
  page: number;
  page_size: number;
}

/**
 * 拉取厂商统计（`/api/stats/providers`）。
 * **仍在用**：`frontend/src/pages/HomeWithAnalysis.tsx` 用它生成左侧厂商筛选列表。
 * 它不是归档接口，别据此当死代码删掉（ISSUE-027 曾把这句注释写错）。
 */
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
 * 从 axios 错误里取出 HTTP 状态码，供调用方区分「业务上的空状态」与真正的失败。
 * axios reject 时已经保留了 `error.response.status`，因此不需要重新包装错误对象。
 */
export const getApiErrorStatus = (error: unknown): number | undefined => {
  if (axios.isAxiosError(error)) {
    return error.response?.status;
  }
  return undefined;
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
