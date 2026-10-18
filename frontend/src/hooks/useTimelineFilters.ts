import { useEffect, useState } from "react";
import type { FormEvent } from "react";

/**
 * 时间轴筛选器的共享逻辑（ISSUE-026）。
 *
 * 桌面筛选器（components/TimelineFilters.tsx）与移动端抽屉（components/MobileFilterDrawer.tsx）
 * 原本各写一套「年份草稿态 + 校验 + 清除 + 选中态」的实现，任何筛选修复都要改两处。
 * 这里集中三件只有一处定义的事：
 *   1. 年份边界（与后端 /api/timeline 的 Query(None, ge=1900, le=3000) 一致）；
 *   2. 年份输入框的草稿值与内联错误（非法值就地提示，不静默丢弃）；
 *   3. 「清除」同时清空草稿（ISSUE-012：筛选状态已清空、输入框还留着旧值）。
 *
 * 筛选值本身仍是受控的：外部传 customYear / onCustomYearChange，hook 只在用户提交时回调一次，
 * 不引入额外 effect，保证每次变更只触发一次请求。
 */

export type TimelinePresetRange = "all" | "30d" | "6m" | "1y";

export type OpenSourceFilter = "all" | "open" | "closed";

export type TimelineFiltersProps = {
  activeRange: TimelinePresetRange;
  customYear?: number | null;
  providers: string[];
  selectedProvider: string | null;
  onProviderChange: (value: string | null) => void;
  modelQuery: string;
  onModelQueryChange: (value: string) => void;
  onModelQuerySubmit: () => void;
  onModelQueryClear: () => void;
  openSourceFilter: OpenSourceFilter;
  onOpenSourceChange: (value: OpenSourceFilter) => void;
  onPresetChange: (range: TimelinePresetRange) => void;
  onCustomYearChange: (year: number | null) => void;
};

// 与后端 /api/timeline 的 year 约束保持一致：Query(None, ge=1900, le=3000)（闭区间）
export const YEAR_MIN = 1900;
export const YEAR_MAX = 3000;

export const YEAR_RANGE_ERROR = `请输入 ${YEAR_MIN}–${YEAR_MAX} 之间的年份`;

/** 年份输入区的受控状态：草稿值 + 内联错误 + 三个事件（提交/清除/输入）。 */
export type TimelineYearField = {
  yearDraft: string;
  yearError: string | null;
  hasCustomYear: boolean;
  onYearDraftChange: (value: string) => void;
  onYearSubmit: (event: FormEvent<HTMLFormElement>) => void;
  onYearClear: () => void;
};

export type UseTimelineFiltersOptions = {
  customYear?: number | null;
  onCustomYearChange: (year: number | null) => void;
};

export const useTimelineFilters = ({
  customYear,
  onCustomYearChange,
}: UseTimelineFiltersOptions): TimelineYearField => {
  // 年份输入用受控草稿值：输入过程中不被外部值打断，只在 customYear 真正变化时同步。
  const [yearDraft, setYearDraft] = useState<string>(customYear != null ? String(customYear) : "");
  const [yearError, setYearError] = useState<string | null>(null);

  useEffect(() => {
    setYearDraft(customYear != null ? String(customYear) : "");
    setYearError(null);
  }, [customYear]);

  const onYearDraftChange = (value: string) => {
    setYearDraft(value);
    setYearError(null);
  };

  const onYearSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const yearValue = yearDraft.trim();
    if (!yearValue) {
      setYearError(null);
      onCustomYearChange(null);
      return;
    }
    // 闭区间与后端一致（ge=1900, le=3000）；非法值就地提示，不再静默丢弃（ISSUE-013）
    const year = Number(yearValue);
    if (!Number.isInteger(year) || year < YEAR_MIN || year > YEAR_MAX) {
      setYearError(YEAR_RANGE_ERROR);
      return;
    }
    setYearError(null);
    onCustomYearChange(year);
  };

  // 「清除」按钮同时清空草稿，避免「筛选状态已清空、输入框还留着旧值」（ISSUE-012）。
  const onYearClear = () => {
    setYearDraft("");
    setYearError(null);
    onCustomYearChange(null);
  };

  return {
    yearDraft,
    yearError,
    hasCustomYear: Boolean(customYear),
    onYearDraftChange,
    onYearSubmit,
    onYearClear,
  };
};
