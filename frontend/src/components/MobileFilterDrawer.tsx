import { KeyboardEvent, useId, useEffect } from "react";

import FilterFields from "./FilterFields";
import { useTimelineFilters } from "../hooks/useTimelineFilters";
import type { TimelineFiltersProps } from "../hooks/useTimelineFilters";

// ISSUE-026：字段 UI 在 components/FilterFields.tsx，年份校验/清除在 hooks/useTimelineFilters.ts。
// 这里只保留移动端抽屉的外壳（遮罩、面板、关闭按钮、Esc 关闭）。
type MobileFilterDrawerProps = TimelineFiltersProps & {
  isOpen: boolean;
  onClose: () => void;
};

const MobileFilterDrawer = ({ isOpen, onClose, ...filterProps }: MobileFilterDrawerProps) => {
  const fieldIds = { inputId: useId(), providerSelectId: useId(), modelSearchId: useId() };
  const year = useTimelineFilters({
    customYear: filterProps.customYear,
    onCustomYearChange: filterProps.onCustomYearChange,
  });

  // 关闭抽屉
  useEffect(() => {
    const handleEscape = (e: Event) => {
      const keyboardEvent = e as unknown as KeyboardEvent;
      if (keyboardEvent.key === "Escape" && isOpen) {
        onClose();
      }
    };
    if (isOpen) {
      document.addEventListener("keydown", handleEscape);
      return () => document.removeEventListener("keydown", handleEscape);
    }
  }, [isOpen, onClose]);

  return (
    <>
      {/* 背景遮罩 */}
      {isOpen && (
        <button
          onClick={onClose}
          className="fixed inset-0 z-30 bg-black/40 backdrop-blur-sm transition-opacity duration-200"
          aria-hidden="true"
        />
      )}

      {/* 抽屉面板 */}
      <div
        className={`fixed bottom-0 left-0 right-0 z-50 bg-surface-raised rounded-t-2xl border-t border-border-default shadow-2xl transition-all duration-300 ease-out ${
          isOpen ? "translate-y-0" : "translate-y-full"
        }`}
        style={{ maxHeight: "85vh" }}
      >
        {/* 抽屉头部 */}
        <div className="sticky top-0 flex items-center justify-between p-4 border-b border-border-default bg-surface-raised rounded-t-2xl">
          <div>
            <h2 className="text-sm font-semibold text-text-primary">模型检索</h2>
            <p className="text-xs text-text-muted mt-1">按时间、发布公司或名称定位</p>
          </div>
          <button
            onClick={onClose}
            className="flex-shrink-0 rounded-lg p-2 text-text-secondary hover:bg-surface-input transition-colors"
            aria-label="关闭"
          >
            <svg
              className="w-5 h-5"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path strokeLinecap="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* 抽屉内容 */}
        <div className="overflow-y-auto p-4">
          <FilterFields {...filterProps} fieldIds={fieldIds} year={year} />
        </div>
      </div>
    </>
  );
};

export default MobileFilterDrawer;
