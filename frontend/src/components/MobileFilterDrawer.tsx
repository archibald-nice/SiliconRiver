import { Dialog } from "@headlessui/react";
import { useId } from "react";
import { XMarkIcon } from "@heroicons/react/24/outline";

import FilterFields from "./FilterFields";
import { useTimelineFilters } from "../hooks/useTimelineFilters";
import type { TimelineFiltersProps } from "../hooks/useTimelineFilters";

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

  return (
    <Dialog open={isOpen} onClose={onClose} className="relative z-50">
      <div className="fixed inset-0 bg-black/50" aria-hidden="true" />
      <div className="fixed inset-0 flex items-end">
        <Dialog.Panel className="flex max-h-[85dvh] w-full flex-col overflow-hidden rounded-t-2xl border-t border-border-default bg-surface-raised shadow-2xl">
          <header className="flex shrink-0 items-center justify-between border-b border-border-default px-4 py-3">
            <div>
              <Dialog.Title className="text-base font-semibold text-text-primary">模型检索</Dialog.Title>
              <p className="mt-1 text-xs text-text-muted">按时间、发布公司或名称定位</p>
            </div>
            <button type="button" onClick={onClose} className="flex h-11 w-11 items-center justify-center rounded-lg text-text-secondary hover:bg-surface-input" aria-label="关闭筛选器">
              <XMarkIcon className="h-5 w-5" aria-hidden="true" />
            </button>
          </header>
          <div className="min-h-0 overflow-y-auto p-4 pb-[max(1rem,env(safe-area-inset-bottom))]">
            <FilterFields {...filterProps} fieldIds={fieldIds} year={year} />
          </div>
        </Dialog.Panel>
      </div>
    </Dialog>
  );
};

export default MobileFilterDrawer;
