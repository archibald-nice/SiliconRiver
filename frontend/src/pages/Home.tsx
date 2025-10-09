import { useCallback, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { fetchTimeline, type TimelineResponse } from "../api/client";
import Timeline3D from "../components/Timeline3D";
import TimelineFilters, { TimelinePresetRange } from "../components/TimelineFilters";

const TIMELINE_PAGE_SIZE = 200;

const Home = () => {
  const [timelineRange, setTimelineRange] = useState<TimelinePresetRange>("30d");
  const [timelineYear, setTimelineYear] = useState<number | null>(null);
  const [timelinePage, setTimelinePage] = useState(1);

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

  const timelineItems = timelineData?.items ?? [];
  const timelineWindowStart = timelineData?.start;
  const timelineWindowEnd = timelineData?.end;
  const timelineTotalPages = timelineData ? Math.max(1, Math.ceil(timelineData.total / timelineData.page_size)) : 1;

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
