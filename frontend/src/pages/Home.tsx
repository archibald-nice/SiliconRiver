import { useCallback, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import {
  fetchModels,
  fetchStats,
  fetchTimeline,
  type ModelListResponse,
  type ModelSummary,
  type ProviderStat,
  type TimelineResponse,
} from "../api/client";
import FilterPanel from "../components/FilterPanel";
import ModelCard from "../components/ModelCard";
import TabSwitcher from "../components/TabSwitcher";
import Timeline3D from "../components/Timeline3D";
import TimelineFilters, { TimelinePresetRange } from "../components/TimelineFilters";

type QueryParams = {
  page: number;
  provider?: string;
  search: string;
};

type TabId = "timeline" | "list";

const Home = () => {
  const [filters, setFilters] = useState<QueryParams>({ page: 1, search: "" });
  const [activeTab, setActiveTab] = useState<TabId>("timeline");
  const [timelineRange, setTimelineRange] = useState<TimelinePresetRange>("30d");
  const [timelineYear, setTimelineYear] = useState<number | null>(null);
  const [timelinePage, setTimelinePage] = useState(1);
  const TIMELINE_PAGE_SIZE = 200;

  const { data: listData, isLoading } = useQuery<ModelListResponse>({
    queryKey: ["models", filters],
    queryFn: () =>
      fetchModels({
        page: filters.page,
        provider: filters.provider || undefined,
        search: filters.search || undefined,
      }),
  });

  const { data: statsData } = useQuery<ProviderStat[]>({
    queryKey: ["stats"],
    queryFn: fetchStats,
  });

  const { data: timelineData, isLoading: isTimelineLoading } = useQuery<TimelineResponse>({
    queryKey: ["timeline", timelineRange, timelineYear, timelinePage],
    queryFn: () =>
      fetchTimeline({
        preset: timelineRange,
        year: timelineYear,
        page: timelinePage,
        page_size: TIMELINE_PAGE_SIZE,
        sort: "asc",
      }),
  });

  const providers = useMemo(() => statsData?.map((item) => item.provider) ?? [], [statsData]);
  const timelineItems = timelineData?.items ?? [];
  const timelineWindowStart = timelineData?.start;
  const timelineWindowEnd = timelineData?.end;
  const timelineTotalPages = timelineData ? Math.max(1, Math.ceil(timelineData.total / timelineData.page_size)) : 1;

  const onProviderChange = useCallback((value: string) => {
    setFilters((current) => ({ ...current, provider: value || undefined, page: 1 }));
  }, []);

  const onSearchChange = useCallback((value: string) => {
    setFilters((current) => ({ ...current, search: value, page: 1 }));
  }, []);

  const onPageChange = useCallback((direction: "prev" | "next") => {
    setFilters((current) => {
      const nextPage = direction === "next" ? current.page + 1 : Math.max(1, current.page - 1);
      return { ...current, page: nextPage };
    });
  }, []);

  const totalPages = listData ? Math.max(1, Math.ceil(listData.total / listData.page_size)) : 1;

  const onTimelinePageChange = useCallback(
    (direction: "prev" | "next") => {
      setTimelinePage((current) => {
        const target = direction === "next" ? current + 1 : current - 1;
        const clamped = Math.min(Math.max(target, 1), timelineTotalPages);
        return clamped;
      });
    },
    [timelineTotalPages]
  );

  const tabs = useMemo(() => {
    const timelineContent = (
      <div className="flex flex-col gap-6">
        {isTimelineLoading ? (
          <p className="text-center text-sm text-text-muted">Loading timeline...</p>
        ) : timelineItems.length === 0 ? (
          <p className="text-center text-sm text-text-muted">No models available in this range.</p>
        ) : (
          <>
            <div className="w-full max-w-5xl self-center">
              <Timeline3D models={timelineItems} />
            </div>
          </>
        )}
      </div>
    );

    const listContent = (
      <section className="space-y-4">
        <header className="flex items-center justify-between">
          <h2 className="text-lg font-semibold text-text-primary">Latest models</h2>
          <div className="flex items-center gap-3 text-sm text-text-muted">
            <button
              type="button"
              onClick={() => onPageChange("prev")}
              disabled={filters.page <= 1}
              className="rounded-md border border-border-default px-3 py-1 text-text-secondary transition-colors hover:border-accent-base hover:text-text-primary disabled:opacity-40"
            >
              Prev page
            </button>
            <span>
              Page {filters.page} / {totalPages}
            </span>
            <button
              type="button"
              onClick={() => onPageChange("next")}
              disabled={listData ? filters.page >= totalPages : true}
              className="rounded-md border border-border-default px-3 py-1 text-text-secondary transition-colors hover:border-accent-base hover:text-text-primary disabled:opacity-40"
            >
              Next page
            </button>
          </div>
        </header>

        {isLoading && <p className="text-text-muted">Loading...</p>}

        {listData && listData.items.length === 0 && !isLoading && (
          <p className="text-text-muted">No data available, adjust filters.</p>
        )}

        {listData && listData.items.length > 0 && (
          <div className="grid gap-6 md:grid-cols-2">
            {listData.items.map((model: ModelSummary) => (
              <ModelCard key={model.model_id} model={model} />
            ))}
          </div>
        )}
      </section>
    );

    return [
      { id: "timeline" as const, label: "Timeline", content: timelineContent },
      { id: "list" as const, label: "Model list", content: listContent },
    ];
  }, [
    filters.page,
    isLoading,
    isTimelineLoading,
    listData,
    onPageChange,
    timelineData,
    timelineItems,
    timelineTotalPages,
    totalPages,
  ]);

  const currentTimelinePage = timelineData?.page ?? timelinePage;
  const canGoPrevTimeline = currentTimelinePage > 1;
  const canGoNextTimeline = currentTimelinePage < timelineTotalPages;

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_320px] xl:grid-cols-[minmax(0,1fr)_360px]">
      <div className="flex flex-col gap-6">
        <TabSwitcher
          tabs={tabs}
          activeId={activeTab}
          onTabChange={(id) => setActiveTab(id as TabId)}
          toolbar={
            <FilterPanel
              providers={providers}
              provider={filters.provider}
              onProviderChange={onProviderChange}
              search={filters.search}
              onSearchChange={onSearchChange}
              className="justify-start lg:justify-end"
            />
          }
        />
      </div>

      <aside className="flex flex-col gap-4">
        <section className="rounded-2xl border border-border-default bg-surface-raised p-5 shadow-lg shadow-accent transition-colors">
          <header className="mb-4 space-y-1">
            <h2 className="text-sm font-semibold text-text-primary">时间筛选</h2>
            <p className="text-xs text-text-muted">调整右侧时间窗口以更新时间线展示。</p>
          </header>
          <TimelineFilters
            activeRange={timelineRange}
            customYear={timelineYear}
            onPresetChange={(range) => {
              setTimelineRange(range);
              setTimelineYear(null);
              setTimelinePage(1);
            }}
            onCustomYearChange={(year) => {
              setTimelineYear(year);
              if (year !== null) {
                setTimelineRange("1y");
              } else {
                setTimelineRange("30d");
              }
              setTimelinePage(1);
            }}
          />
          {timelineData && (
            <div className="mt-4 border-t border-border-default pt-4 text-xs text-text-muted">
              {timelineWindowStart && timelineWindowEnd ? (
                <p>窗口：{timelineWindowStart} ➝ {timelineWindowEnd}</p>
              ) : null}
              <p className="mt-1">页码：{currentTimelinePage} / {timelineTotalPages}</p>
              <div className="mt-3 flex items-center justify-between gap-2">
                <button
                  type="button"
                  onClick={() => onTimelinePageChange("prev")}
                  disabled={!canGoPrevTimeline}
                  className="rounded-md border border-border-default px-3 py-1 text-xs text-text-secondary transition-colors hover:border-accent-base hover:text-text-primary disabled:opacity-40"
                >
                  上一页
                </button>
                <button
                  type="button"
                  onClick={() => onTimelinePageChange("next")}
                  disabled={!canGoNextTimeline}
                  className="rounded-md border border-border-default px-3 py-1 text-xs text-text-secondary transition-colors hover:border-accent-base hover:text-text-primary disabled:opacity-40"
                >
                  下一页
                </button>
              </div>
            </div>
          )}
        </section>
      </aside>
    </div>
  );
};

export default Home;
