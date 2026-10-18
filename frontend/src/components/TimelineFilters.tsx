import { useId } from "react";

import FilterFields from "./FilterFields";
import { useTimelineFilters } from "../hooks/useTimelineFilters";
import type { TimelineFiltersProps } from "../hooks/useTimelineFilters";

// ISSUE-026：字段 UI 在 components/FilterFields.tsx，年份校验/清除在 hooks/useTimelineFilters.ts。
// 这里只保留桌面端的外壳布局；字段的 JSX 与移动端抽屉完全共用同一份实现。
export type { OpenSourceFilter, TimelineFiltersProps, TimelinePresetRange } from "../hooks/useTimelineFilters";

const TimelineFilters = (props: TimelineFiltersProps) => {
  const fieldIds = { inputId: useId(), providerSelectId: useId(), modelSearchId: useId() };
  const year = useTimelineFilters({
    customYear: props.customYear,
    onCustomYearChange: props.onCustomYearChange,
  });

  return (
    <div className="hidden md:flex md:flex-col gap-2 rounded-xl border border-border-default bg-surface-raised p-4 text-sm text-text-secondary transition-colors">
      <FilterFields {...props} fieldIds={fieldIds} year={year} />
    </div>
  );
};

export default TimelineFilters;
