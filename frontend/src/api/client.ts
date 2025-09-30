import axios from "axios";

const baseURL = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

export const api = axios.create({
  baseURL,
});

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

export const fetchModels = async (params: Record<string, unknown>) => {
  const { data } = await api.get<ModelListResponse>("/api/models", { params });
  return data;
};

export const fetchStats = async () => {
  const { data } = await api.get<ProviderStat[]>("/api/stats/providers");
  return data;
};
