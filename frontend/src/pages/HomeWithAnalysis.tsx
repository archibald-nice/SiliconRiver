import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQueries, useQuery, useQueryClient, type QueryObserverResult } from "@tanstack/react-query";

import {
  buildProviderAvatarUrl,
  fetchStats,
  fetchTimeline,
  type ProviderStat,
  type TimelineModel,
  type TimelineResponse,
} from "../api/client";
import Timeline3D from "../components/Timeline3D";
import TimelineFilters, { TimelinePresetRange } from "../components/TimelineFilters";
import MobileFilterButton from "../components/MobileFilterButton";
import MobileFilterDrawer from "../components/MobileFilterDrawer";
import { ModeSwitcher, type TimelineModeName } from "../components/ModeSwitcher";

const TIMELINE_PAGE_SIZE = 200;
const prefetchedAvatars = new Set<string>();

type TimelinePageResult = QueryObserverResult<TimelineResponse, Error>;

type TimelinePagesState = {
  items: TimelineModel[];
  total: number;
  pageSize: number;
  lastPageItemCount: number;
  isFirstPageLoading: boolean;
  isLoadingMore: boolean;
  firstPageError: boolean;
  laterPageError: boolean;
};

// 把已请求的各页 timeline 合并成一份列表（第 1 页在前，其后是「加载更多」追加的页）。
// 用 useQueries 的 combine 而不是 useMemo：combine 的返回值会经过 react-query 的
// replaceEqualDeep，内容没变时沿用上一次的对象/数组引用，
// 避免 Timeline3D 只因为拿到新数组就把整个 Three.js 场景重建一遍。
const mergeTimelinePages = (results: TimelinePageResult[]): TimelinePagesState => {
  const items: TimelineModel[] = [];
  const seenModelIds = new Set<string>();
  let lastPageItemCount = 0;

  results.forEach((result) => {
    const pageItems = result.data?.items ?? [];
    lastPageItemCount = pageItems.length;
    pageItems.forEach((item) => {
      // 跨页去重：翻页间隙有新模型落库时，同一条可能同时出现在相邻两页
      if (seenModelIds.has(item.model_id)) {
        return;
      }
      seenModelIds.add(item.model_id);
      items.push(item);
    });
  });

  const firstPage = results[0];
  return {
    items,
    total: firstPage?.data?.total ?? 0,
    pageSize: firstPage?.data?.page_size ?? TIMELINE_PAGE_SIZE,
    lastPageItemCount,
    isFirstPageLoading: firstPage ? firstPage.isLoading : true,
    isLoadingMore: results.some((result, index) => index > 0 && result.isLoading),
    firstPageError: !!firstPage?.isError && !firstPage.data,
    laterPageError: results.some((result, index) => index > 0 && result.isError),
  };
};

const HomeWithAnalysis = () => {
  const queryClient = useQueryClient();
  // Timeline 状态
  const [timelineRange, setTimelineRange] = useState<TimelinePresetRange>("30d");
  const [timelineYear, setTimelineYear] = useState<number | null>(null);
  const [timelineLoadedPages, setTimelineLoadedPages] = useState(1);
  const [timelineProvider, setTimelineProvider] = useState<string | null>(null);
  const [timelineSearchInput, setTimelineSearchInput] = useState("");
  const [timelineSearchFilter, setTimelineSearchFilter] = useState("");
  const [timelineOpenSource, setTimelineOpenSource] = useState<"all" | "open" | "closed">("all");
  const [timelineMode, setTimelineMode] = useState<TimelineModeName>("helix");
  const [isDrawerOpen, setIsDrawerOpen] = useState(false);
  // 进入搜索前的时间范围：搜索会把范围改成「不限」，清空搜索时用它还原（ISSUE-014）
  const rangeBeforeSearchRef = useRef<TimelinePresetRange | null>(null);

  const { data: providerStats } = useQuery<ProviderStat[]>({
    queryKey: ["provider-stats"],
    queryFn: fetchStats,
    staleTime: 1000 * 60 * 5,
  });

  const providerOptions = useMemo(() => providerStats?.map((item) => item.provider) ?? [], [providerStats]);

  // Timeline 数据：按「已加载页数」逐页请求，每页独立缓存，追加新页时不会重取旧页。
  // sort 用 "desc"：最新发布的模型落在第 1 页，首屏即可见；
  // 「加载更多」再往更早的页追加（接口没有 offset/limit，等价参数是 page/page_size）。
  // 用 useMemo 缓存查询配置，避免搜索框逐字输入时把每页的 options 重建一遍。
  const timelineQueries = useMemo(
    () =>
      Array.from({ length: timelineLoadedPages }, (_, index) => {
        const pageNumber = index + 1;
        return {
          queryKey: [
            "timeline",
            timelineRange,
            timelineYear,
            pageNumber,
            timelineProvider,
            timelineSearchFilter,
            timelineOpenSource,
          ],
          queryFn: () =>
            fetchTimeline({
              // 自定义年份与 preset 互斥：后端在 year 存在时会忽略 preset，
              // 这里直接不传，避免请求里出现「近一年 + 具体年份」的语义矛盾（ISSUE-028）
              preset: timelineYear !== null ? undefined : timelineRange,
              year: timelineYear,
              page: pageNumber,
              page_size: TIMELINE_PAGE_SIZE,
              sort: "desc",
              provider: timelineProvider,
              model_name: timelineSearchFilter || undefined,
              open_source:
                timelineOpenSource === "all" ? null : timelineOpenSource === "open" ? true : false,
            }),
        };
      }),
    [
      timelineLoadedPages,
      timelineRange,
      timelineYear,
      timelineProvider,
      timelineSearchFilter,
      timelineOpenSource,
    ]
  );

  const timelinePages = useQueries({
    queries: timelineQueries,
    combine: mergeTimelinePages,
  });

  const {
    items: timelineItems,
    total: timelineTotal,
    pageSize: timelinePageSize,
    lastPageItemCount,
    isFirstPageLoading,
    isLoadingMore: isTimelineLoadingMore,
    firstPageError,
    laterPageError,
  } = timelinePages;

  const isTimelineLoading = isFirstPageLoading;
  // 还有更早的模型：总数没加载完，且最后一页是装满的（没装满说明已经到末页，
  // 这样既不会越界请求空页，也能容忍跨页去重导致的条数略少）
  const canLoadMoreTimeline = timelineTotal > timelineItems.length && lastPageItemCount >= timelinePageSize;
  const timelineRemaining = Math.max(0, timelineTotal - timelineItems.length);

  useEffect(() => {
    if (timelineItems.length === 0) {
      return;
    }
    timelineItems.forEach((item) => {
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
  }, [timelineItems]);

  // 「加载更多」：sort="desc" 下页码越大离今天越远，追加下一页即把更早的模型接进画布
  const handleLoadMoreTimeline = useCallback(() => {
    setTimelineLoadedPages((current) => current + 1);
  }, []);

  const resetFilters = () => {
    rangeBeforeSearchRef.current = null;
    setTimelineRange("30d"); setTimelineYear(null); setTimelineProvider(null);
    setTimelineSearchInput(""); setTimelineSearchFilter("");
    setTimelineOpenSource("all"); setTimelineLoadedPages(1);
  };
  const clearSearch = () => {
    setTimelineSearchFilter(""); setTimelineSearchInput(""); setTimelineLoadedPages(1);
    const remembered = rangeBeforeSearchRef.current;
    rangeBeforeSearchRef.current = null;
    if (remembered !== null) { setTimelineRange(remembered); setTimelineYear(null); }
  };
  const retryTimeline = () => { void queryClient.refetchQueries({ queryKey: ["timeline"], type: "active", predicate: (query) => query.state.status === "error" }); };
  const loadedDates = useMemo(() => {
    const dates = timelineItems.map((item) => new Date(item.created_at).getTime()).filter(Number.isFinite);
    if (!dates.length) return null;
    return `${new Date(Math.min(...dates)).toLocaleDateString()}–${new Date(Math.max(...dates)).toLocaleDateString()}`;
  }, [timelineItems]);
  const rangeLabel = timelineYear !== null ? `${timelineYear} 年` : ({ all: "不限", "30d": "近30天", "6m": "近6个月", "1y": "今年" } as const)[timelineRange];

  return (
    <div className="timeline-workspace flex w-full min-h-0 flex-1 gap-4 relative">
      {/* 移动端悬浮菜单按钮 */}
      <MobileFilterButton isOpen={isDrawerOpen} onToggle={setIsDrawerOpen} />

      {/* 移动端抽屉 */}
      <MobileFilterDrawer
        isOpen={isDrawerOpen}
        onClose={() => setIsDrawerOpen(false)}
        activeRange={timelineRange}
        customYear={timelineYear}
        providers={providerOptions}
        selectedProvider={timelineProvider}
        onProviderChange={(value: string | null) => {
          setTimelineProvider(value);
          setTimelineLoadedPages(1);
        }}
        modelQuery={timelineSearchInput}
        onModelQueryChange={setTimelineSearchInput}
        onModelQuerySubmit={() => {
          const trimmed = timelineSearchInput.trim();
          setTimelineSearchFilter(trimmed);
          setTimelineLoadedPages(1);
          if (trimmed.length > 0) {
            // 只记住第一次进入搜索前的范围，重复提交不覆盖（ISSUE-014）
            if (rangeBeforeSearchRef.current === null) {
              rangeBeforeSearchRef.current = timelineRange;
            }
            setTimelineRange("all");
            setTimelineYear(null);
          }
        }}
        onModelQueryClear={() => {
          setTimelineSearchFilter("");
          setTimelineSearchInput("");
          setTimelineLoadedPages(1);
          // 还原进入搜索前的时间范围，而不是硬编码回 "30d"（ISSUE-014）
          const rememberedRange = rangeBeforeSearchRef.current;
          rangeBeforeSearchRef.current = null;
          if (rememberedRange !== null) {
            setTimelineRange(rememberedRange);
            setTimelineYear(null);
          }
        }}
        onPresetChange={(range: TimelinePresetRange) => {
          // 用户显式改范围后，不再用搜索前的记忆覆盖（ISSUE-014）
          rangeBeforeSearchRef.current = null;
          setTimelineRange(range);
          setTimelineYear(null);
          setTimelineLoadedPages(1);
        }}
        onCustomYearChange={(year: number | null) => {
          rangeBeforeSearchRef.current = null;
          setTimelineYear(year);
          if (year !== null) {
            setTimelineRange("1y");
          } else {
            setTimelineRange("30d");
          }
          setTimelineLoadedPages(1);
        }}
        openSourceFilter={timelineOpenSource}
        onOpenSourceChange={(value: "all" | "open" | "closed") => {
          setTimelineOpenSource(value);
          setTimelineLoadedPages(1);
        }}
      />

      <section className="flex min-w-0 flex-1 flex-col">
        <div className="flex min-h-0 flex-1 flex-col rounded-2xl border border-border-default bg-surface-raised transition-colors">
          {/* 标题 */}
          <header className="shrink-0 border-b border-border-default px-4 py-2 sm:px-6 sm:py-3">
            <div className="flex flex-col gap-2 sm:gap-3 lg:flex-row lg:items-center lg:justify-between">
              <div>
                <h1 className="text-xl font-semibold text-text-primary">Timeline</h1>
                <p className="mt-1 hidden text-sm text-text-muted sm:block">
                  滚动浏览节点，或使用筛选定位模型。
                </p>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                {/* 分页入口：结果被截断时把更早的页追加进画布。
                    常驻挂载（只是禁用/换文案），避免出现/消失时画布尺寸变化导致 Three.js 渲染尺寸错位。 */}
                {timelineTotal > 0 && (
                  <button
                    type="button"
                    onClick={handleLoadMoreTimeline}
                    disabled={!canLoadMoreTimeline || isTimelineLoadingMore}
                    title={
                      laterPageError ? "追加加载失败，请重试" : canLoadMoreTimeline
                        ? `还有 ${timelineRemaining.toLocaleString()} 个更早发布的模型，点此追加到画布`
                        : "全部模型已加载"
                    }
                    className="rounded-md border border-border-default px-3 py-2 text-xs font-medium text-text-secondary transition-colors hover:border-accent-base hover:text-text-primary disabled:cursor-not-allowed disabled:opacity-60 touch-manipulation"
                  >
                    {isTimelineLoadingMore
                      ? "加载中…"
                      : laterPageError ? "加载中断" : canLoadMoreTimeline
                        ? `加载更多（剩余 ${timelineRemaining.toLocaleString()} 个）`
                        : `已加载全部 ${timelineTotal.toLocaleString()} 个`}
                  </button>
                )}
                <ModeSwitcher
                  currentMode={timelineMode}
                  onModeChange={setTimelineMode}
                  disabled={isTimelineLoading || timelineItems.length === 0}
                />
              </div>
            </div>
          </header>

          <div className="flex shrink-0 flex-wrap items-center gap-x-2 gap-y-1 border-b border-border-default px-4 py-2 text-xs text-text-secondary" aria-label="当前筛选与结果">
            <button type="button" onClick={() => { setTimelineRange("30d"); setTimelineYear(null); setTimelineLoadedPages(1); rangeBeforeSearchRef.current = null; }} aria-label="将时间范围重置为近30天">范围：{rangeLabel}{timelineRange !== "30d" || timelineYear !== null ? " ×" : ""}</button>
            {!firstPageError && !isTimelineLoading && <span>已加载 {timelineItems.length.toLocaleString()} / 匹配 {timelineTotal.toLocaleString()}</span>}
            {loadedDates && <span>已加载日期：{loadedDates}</span>}
            {timelineProvider && <button type="button" onClick={() => { setTimelineProvider(null); setTimelineLoadedPages(1); }} aria-label={`清除厂商 ${timelineProvider}`}>厂商：{timelineProvider} ×</button>}
            {timelineOpenSource !== "all" && <button type="button" onClick={() => { setTimelineOpenSource("all"); setTimelineLoadedPages(1); }}>授权：{timelineOpenSource === "open" ? "开源" : "闭源"} ×</button>}
            {timelineSearchFilter && <button type="button" onClick={clearSearch} title={`清除搜索：${timelineSearchFilter}`} className="max-w-[11rem] truncate">搜索：{timelineSearchFilter} ×</button>}
            {(timelineRange !== "30d" || timelineYear !== null || timelineProvider || timelineOpenSource !== "all" || timelineSearchFilter) && <button type="button" onClick={resetFilters} className="text-accent-base">重置筛选</button>}
          </div>
          {laterPageError && <div role="alert" className="px-4 py-2 text-xs text-text-secondary">追加加载失败，已加载内容仍可浏览。 <button type="button" className="text-accent-base underline" onClick={retryTimeline}>重试</button></div>}

          {/* 内容区域 */}
          <div className="min-h-0 flex-1 overflow-hidden p-2 sm:p-4">
            {isTimelineLoading ? (
              <p className="text-center text-sm text-text-muted">时间轴加载中…</p>
            ) : firstPageError ? (
              <div role="alert" className="p-4 text-center text-sm text-text-secondary">时间轴加载失败。 <button type="button" className="text-accent-base underline" onClick={retryTimeline}>重试</button></div>
            ) : timelineItems.length === 0 ? (
              <div className="p-4 text-center text-sm text-text-secondary">当前筛选没有匹配模型。 <button type="button" className="text-accent-base underline" onClick={resetFilters}>重置筛选</button></div>
            ) : (
              <div className="h-full w-full">
                <Timeline3D models={timelineItems} mode={timelineMode} />
              </div>
            )}
          </div>
        </div>
      </section>

      {/* 右侧面板 */}
      <aside className="hidden md:flex md:w-[300px] md:min-w-0 md:flex-none md:flex-col xl:w-[340px]" style={{ maxWidth: "380px" }}>
        <section className="flex min-h-0 flex-1 w-full flex-col overflow-hidden rounded-2xl border border-border-default bg-surface-raised shadow-lg shadow-accent transition-colors">
          {/* Timeline 过滤器 */}
          <header className="shrink-0 mb-2 space-y-1 px-4 pt-3">
            <h2 className="text-sm font-semibold text-text-primary">模型检索</h2>
            <p className="text-xs text-text-muted">按时间、发布公司或名称快速定位模型节点。</p>
          </header>
          <div className="min-h-0 flex-1 overflow-y-auto px-4 pb-3">
            <TimelineFilters
              activeRange={timelineRange}
              customYear={timelineYear}
              providers={providerOptions}
              selectedProvider={timelineProvider}
              onProviderChange={(value) => {
                setTimelineProvider(value);
                setTimelineLoadedPages(1);
              }}
              modelQuery={timelineSearchInput}
              onModelQueryChange={setTimelineSearchInput}
              onModelQuerySubmit={() => {
                const trimmed = timelineSearchInput.trim();
                setTimelineSearchFilter(trimmed);
                setTimelineLoadedPages(1);
                if (trimmed.length > 0) {
                  // 只记住第一次进入搜索前的范围，重复提交不覆盖（ISSUE-014）
                  if (rangeBeforeSearchRef.current === null) {
                    rangeBeforeSearchRef.current = timelineRange;
                  }
                  setTimelineRange("all");
                  setTimelineYear(null);
                }
              }}
              onModelQueryClear={() => {
                setTimelineSearchFilter("");
                setTimelineSearchInput("");
                setTimelineLoadedPages(1);
                // 还原进入搜索前的时间范围，而不是硬编码回 "30d"（ISSUE-014）
                const rememberedRange = rangeBeforeSearchRef.current;
                rangeBeforeSearchRef.current = null;
                if (rememberedRange !== null) {
                  setTimelineRange(rememberedRange);
                  setTimelineYear(null);
                }
              }}
              onPresetChange={(range) => {
                // 用户显式改范围后，不再用搜索前的记忆覆盖（ISSUE-014）
                rangeBeforeSearchRef.current = null;
                setTimelineRange(range);
                setTimelineYear(null);
                setTimelineLoadedPages(1);
              }}
              onCustomYearChange={(year) => {
                rangeBeforeSearchRef.current = null;
                setTimelineYear(year);
                if (year !== null) {
                  setTimelineRange("1y");
                } else {
                  setTimelineRange("30d");
                }
                setTimelineLoadedPages(1);
              }}
              openSourceFilter={timelineOpenSource}
              onOpenSourceChange={(value) => {
                setTimelineOpenSource(value);
                setTimelineLoadedPages(1);
              }}
            />
            {timelineTotal > 0 && (
              <div className="mt-2 border-t border-border-default pt-2 text-xs text-text-muted">
                <p>
                  {`匹配：`}
                  <span className="font-semibold text-text-primary">
                    {timelineTotal.toLocaleString()}
                  </span>
                  {` 个模型节点`}
                </p>
                <p className="mt-1">
                  {`已加载：`}
                  <span className="font-semibold text-text-primary">
                    {timelineItems.length.toLocaleString()}
                  </span>
                  {timelineRemaining > 0 ? ` 个（最新的一批）` : ` 个（全部已加载）`}
                </p>
              </div>
            )}
          </div>
        </section>
      </aside>
    </div>
  );
};

export default HomeWithAnalysis;
