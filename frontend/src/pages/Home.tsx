import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { fetchModels, fetchStats } from "../api/client";
import FilterPanel from "../components/FilterPanel";
import ModelCard from "../components/ModelCard";
import TimelineRiver from "../components/TimelineRiver";

type QueryParams = {
  page: number;
  provider?: string;
  search: string;
};

const Home = () => {
  const [filters, setFilters] = useState<QueryParams>({ page: 1, search: "" });

  const { data: listData, isLoading } = useQuery({
    queryKey: ["models", filters],
    queryFn: () =>
      fetchModels({
        page: filters.page,
        provider: filters.provider || undefined,
        search: filters.search || undefined,
      }),
    keepPreviousData: true,
  });

  const { data: statsData } = useQuery({
    queryKey: ["stats"],
    queryFn: fetchStats,
  });

  const providers = useMemo(() => statsData?.map((item) => item.provider) ?? [], [statsData]);

  const onProviderChange = (value: string) => {
    setFilters((current) => ({ ...current, provider: value || undefined, page: 1 }));
  };

  const onSearchChange = (value: string) => {
    setFilters((current) => ({ ...current, search: value, page: 1 }));
  };

  const onPageChange = (direction: "prev" | "next") => {
    setFilters((current) => {
      const nextPage = direction === "next" ? current.page + 1 : Math.max(1, current.page - 1);
      return { ...current, page: nextPage };
    });
  };

  const totalPages = listData ? Math.max(1, Math.ceil(listData.total / listData.page_size)) : 1;

  return (
    <div className="flex flex-col gap-6">
      <FilterPanel
        providers={providers}
        provider={filters.provider}
        onProviderChange={onProviderChange}
        search={filters.search}
        onSearchChange={onSearchChange}
      />

      <section className="space-y-4">
        <header className="flex items-center justify-between">
          <h2 className="text-lg font-semibold text-white">最新模型</h2>
          <div className="flex items-center gap-3 text-sm text-slate-400">
            <button
              type="button"
              onClick={() => onPageChange("prev")}
              disabled={filters.page <= 1}
              className="rounded-md border border-slate-700 px-3 py-1 transition disabled:opacity-40"
            >
              上一页
            </button>
            <span>
              第 {filters.page} / {totalPages} 页
            </span>
            <button
              type="button"
              onClick={() => onPageChange("next")}
              disabled={listData ? filters.page >= totalPages : true}
              className="rounded-md border border-slate-700 px-3 py-1 transition disabled:opacity-40"
            >
              下一页
            </button>
          </div>
        </header>

        {isLoading && <p className="text-slate-400">加载中...</p>}

        {listData && listData.items.length === 0 && !isLoading && (
          <p className="text-slate-400">暂无数据，换个筛选条件试试。</p>
        )}

        {listData && listData.items.length > 0 && (
          <div className="grid gap-6 md:grid-cols-2">
            {listData.items.map((model) => (
              <ModelCard key={model.model_id} model={model} />
            ))}
          </div>
        )}
      </section>

      {listData && listData.items.length > 0 && (
        <section className="space-y-4">
          <header className="flex items-center justify-between">
            <h2 className="text-lg font-semibold text-white">历史长河</h2>
            <p className="text-sm text-slate-400">按时间顺序回顾最近发布的模型</p>
          </header>
          <TimelineRiver models={listData.items.slice(0, 10)} />
        </section>
      )}
    </div>
  );
};

export default Home;
