import { useCallback, useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { buildProviderAvatarUrl, fetchStats, fetchTimeline, type ProviderStat, type TimelineResponse } from "../api/client";
import Timeline3D from "../components/Timeline3D";
import TimelineFilters, { TimelinePresetRange } from "../components/TimelineFilters";

const TIMELINE_PAGE_SIZE = 200;
const prefetchedAvatars = new Set<string>();

const Home = () => {
  const [timelineRange, setTimelineRange] = useState<TimelinePresetRange>("30d");
  const [timelineYear, setTimelineYear] = useState<number | null>(null);
  const [timelinePage, setTimelinePage] = useState(1);
  const [timelineProvider, setTimelineProvider] = useState<string | null>(null);
  const [timelineSearchInput, setTimelineSearchInput] = useState("");
  const [timelineSearchFilter, setTimelineSearchFilter] = useState("");
  const [timelineOpenSource, setTimelineOpenSource] = useState<"all" | "open" | "closed">("all");

  const { data: providerStats } = useQuery<ProviderStat[]>({
    queryKey: ["provider-stats"],
    queryFn: fetchStats,
    staleTime: 1000 * 60 * 5,
  });

  const providerOptions = useMemo(() => providerStats?.map((item) => item.provider) ?? [], [providerStats]);

  const { data: timelineData, isLoading: isTimelineLoading } = useQuery<TimelineResponse>({
    queryKey: [
      "timeline",
      timelineRange,
      timelineYear,
      timelinePage,
      timelineProvider,
      timelineSearchFilter,
      timelineOpenSource,
    ],
    queryFn: () =>
      fetchTimeline({
        preset: timelineRange,
        year: timelineYear,
        page: timelinePage,
        page_size: TIMELINE_PAGE_SIZE,
        sort: "asc",
        provider: timelineProvider,
        model_name: timelineSearchFilter || undefined,
        open_source:
          timelineOpenSource === "all" ? null : timelineOpenSource === "open" ? true : false,
      }),
  });

  const timelineItems = timelineData?.items ?? [];
  const timelineTotal = timelineData?.total ?? 0;
  const timelineTotalPages = timelineData ? Math.max(1, Math.ceil(timelineData.total / timelineData.page_size)) : 1;

  useEffect(() => {
    if (!timelineData) {
      return;
    }
    timelineData.items.forEach((item) => {
      if (!item.avatar_url) {
        return;
      }
      const provider = item.provider;
      if (!provider || prefetchedAvatars.has(provider)) {
        return;
      }
      prefetchedAvatars.add(provider);
      const img = new Image();
      img.referrerPolicy = "no-referrer";
      img.decoding = "async";
      img.src = buildProviderAvatarUrl(provider);
    });
  }, [timelineData]);

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

  const currentTimelinePage = timelineData?.page ?? timelinePage;
  const canGoPrevTimeline = currentTimelinePage > 1;
  const canGoNextTimeline = currentTimelinePage < timelineTotalPages;

  return (
    <div className="mx-auto grid w-full max-w-[1920px] gap-6 px-4 sm:px-6 lg:px-8 xl:grid-cols-[minmax(0,7fr)_minmax(0,3fr)] xl:gap-10">
      <section className="flex flex-col gap-6">
        <div className="rounded-2xl border border-border-default bg-surface-raised shadow-lg shadow-accent transition-colors">
          <header className="border-b border-border-default px-6 py-4">
            <h1 className="text-xl font-semibold text-text-primary">Timeline</h1>
            <p className="mt-1 text-sm text-text-muted">滚动或调整右侧筛选器，浏览最新模型节点。</p>
          </header>
          <div className="p-6">
            {isTimelineLoading ? (
              <p className="text-center text-sm text-text-muted">Loading timeline...</p>
            ) : timelineItems.length === 0 ? (
              <p className="text-center text-sm text-text-muted">No models available in this range.</p>
            ) : (
              <div className="w-full xl:px-2">
                <Timeline3D models={timelineItems} />
              </div>
            )}
          </div>
        </div>
      </section>

      <aside className="flex flex-col gap-4">
        <section className="rounded-2xl border border-border-default bg-surface-raised p-5 shadow-lg shadow-accent transition-colors">
          <header className="mb-4 space-y-1">
            <h2 className="text-sm font-semibold text-text-primary">{"\u6a21\u578b\u68c0\u7d22"}</h2>
            <p className="text-xs text-text-muted">{"\u6309\u65f6\u95f4\u3001\u53d1\u5e03\u516c\u53f8\u6216\u540d\u79f0\u5feb\u901f\u5b9a\u4f4d\u6a21\u578b\u8282\u70b9\u3002"}</p>
          </header>
          <TimelineFilters
            activeRange={timelineRange}
            customYear={timelineYear}
            providers={providerOptions}
            selectedProvider={timelineProvider}
            onProviderChange={(value) => {
              setTimelineProvider(value);
              setTimelinePage(1);
            }}
            modelQuery={timelineSearchInput}
            onModelQueryChange={setTimelineSearchInput}
            onModelQuerySubmit={() => {
              const trimmed = timelineSearchInput.trim();
              setTimelineSearchFilter(trimmed);
              setTimelinePage(1);
              if (trimmed.length > 0) {
                setTimelineRange("all");
                setTimelineYear(null);
              }
            }}
            onModelQueryClear={() => {
              setTimelineSearchFilter("");
              setTimelineSearchInput("");
              setTimelinePage(1);
              if (timelineRange === "all") {
                setTimelineRange("30d");
                setTimelineYear(null);
              }
            }}
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
            openSourceFilter={timelineOpenSource}
            onOpenSourceChange={(value) => {
              setTimelineOpenSource(value);
              setTimelinePage(1);
            }}
          />
          {timelineData && (
            <div className="mt-4 border-t border-border-default pt-4 text-xs text-text-muted">
              <p>
                {`💠 总计：`}
                <span className="font-semibold text-text-primary">
                  {timelineTotal.toLocaleString()}
                </span>
                {` 个模型节点`}
              </p>
            </div>
          )}
        </section>
      </aside>
    </div>
  );
};

export default Home;








