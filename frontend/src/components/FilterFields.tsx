import type { KeyboardEvent } from "react";

import type {
  OpenSourceFilter,
  TimelineFiltersProps,
  TimelinePresetRange,
  TimelineYearField,
} from "../hooks/useTimelineFilters";

/**
 * 筛选字段的共享展示层（ISSUE-026）。
 *
 * 桌面筛选器与移动端抽屉的五个区块（时间范围 / 年份 / 厂商 / 授权 / 搜索）原本各写一遍，
 * 现在只有这一份 JSX；两个容器只负责外壳布局与开合方式。
 * 年份的草稿态、校验与清除在 hooks/useTimelineFilters.ts 里，这里只通过 year prop 消费。
 */

const PRESET_OPTIONS: { label: string; value: TimelinePresetRange; description: string }[] = [
  { label: "不限", value: "all", description: "显示所有时间范围的模型" },
  { label: "近30天", value: "30d", description: "呈现最近30天新增的模型" },
  { label: "近6个月", value: "6m", description: "呈现最近6个月新增的模型" },
  { label: "今年", value: "1y", description: "呈现今年发布的模型" },
];

const OPEN_SOURCE_OPTIONS: { label: string; value: OpenSourceFilter; description: string }[] = [
  { label: "全部", value: "all", description: "查看全部模型" },
  { label: "开源", value: "open", description: "仅查看开源模型" },
  { label: "闭源", value: "closed", description: "仅查看闭源模型" },
];

export type FilterFieldIds = {
  inputId: string;
  providerSelectId: string;
  modelSearchId: string;
};

export type FilterFieldsProps = TimelineFiltersProps & {
  fieldIds: FilterFieldIds;
  year: TimelineYearField;
};

const handleTagKeyPress = (event: KeyboardEvent<HTMLSpanElement>, action: () => void) => {
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    action();
  }
};

// 可点/可键盘操作的胶囊单选（时间范围与模型授权共用同一套选中态样式）
const FilterChip = ({
  label,
  description,
  active,
  onClick,
}: {
  label: string;
  description: string;
  active: boolean;
  onClick: () => void;
}) => (
  <span
    role="button"
    tabIndex={0}
    onClick={onClick}
    onKeyDown={(event) => handleTagKeyPress(event, onClick)}
    className={`inline-flex items-center rounded-full border px-3 py-1.5 text-xs font-medium transition cursor-pointer select-none touch-manipulation ${
      active
        ? "border-accent-base bg-accent-base/10 text-accent-base shadow-sm"
        : "border-border-default bg-surface-overlay text-text-secondary hover:border-accent-base hover:bg-surface-raised hover:text-text-primary"
    }`}
    title={description}
  >
    {label}
  </span>
);

const FilterFields = ({
  activeRange,
  providers,
  selectedProvider,
  onProviderChange,
  modelQuery,
  onModelQueryChange,
  onModelQuerySubmit,
  onModelQueryClear,
  openSourceFilter,
  onOpenSourceChange,
  onPresetChange,
  fieldIds,
  year,
}: FilterFieldsProps) => {
  const { inputId, providerSelectId, modelSearchId } = fieldIds;
  const yearErrorId = `${inputId}-year-error`;

  return (
    <div className="space-y-4">
      <div>
        <p className="text-xs font-semibold text-text-secondary mb-2">时间范围</p>
        <div className="flex flex-wrap gap-2">
          {PRESET_OPTIONS.map((preset) => (
            <FilterChip
              key={preset.value}
              label={preset.label}
              description={preset.description}
              active={activeRange === preset.value}
              onClick={() => onPresetChange(preset.value)}
            />
          ))}
        </div>
      </div>

      <div>
        <p className="text-xs text-text-muted mb-2">或请选择具体年份：</p>
        <form className="flex flex-col gap-2 sm:flex-row sm:items-center" onSubmit={year.onYearSubmit}>
          <input
            id={inputId}
            name="year"
            type="number"
            placeholder="例如 2024"
            value={year.yearDraft}
            onChange={(event) => year.onYearDraftChange(event.target.value)}
            aria-invalid={year.yearError ? true : undefined}
            aria-describedby={year.yearError ? yearErrorId : undefined}
            className="flex-1 rounded-md border border-border-default bg-surface-input px-3 py-2 text-sm text-text-primary transition-colors focus:border-accent-base focus:outline-none"
          />
          <div className="flex gap-2">
            <button
              type="submit"
              className="rounded-md border border-border-default px-3 py-2 text-xs font-medium text-text-secondary transition-colors hover:border-accent-base hover:text-text-primary touch-manipulation"
            >
              确定
            </button>
            {year.hasCustomYear ? (
              <button
                type="button"
                onClick={year.onYearClear}
                className="text-xs text-text-muted hover:text-text-primary"
              >
                清除
              </button>
            ) : null}
          </div>
        </form>
        {year.yearError ? (
          <p id={yearErrorId} className="text-xs text-rose-400">
            {year.yearError}
          </p>
        ) : null}
      </div>

      {providers.length > 0 ? (
        <div className="space-y-2 border-t border-border-default pt-4">
          <label
            htmlFor={providerSelectId}
            className="block text-xs font-semibold uppercase tracking-wide text-text-muted"
          >
            厂商
          </label>
          <select
            id={providerSelectId}
            value={selectedProvider ?? ""}
            onChange={(event) => onProviderChange(event.target.value === "" ? null : event.target.value)}
            className="w-full rounded-md border border-border-default bg-surface-input px-3 py-2 text-sm text-text-primary transition-colors focus:border-accent-base focus:outline-none touch-manipulation"
          >
            <option value="">全部厂商</option>
            {providers.map((provider) => (
              <option key={provider} value={provider}>
                {provider}
              </option>
            ))}
          </select>
          {selectedProvider ? (
            <button
              type="button"
              onClick={() => onProviderChange(null)}
              className="text-xs text-text-muted transition-colors hover:text-text-primary"
            >
              清除厂商
            </button>
          ) : null}
        </div>
      ) : null}

      <div className="space-y-2 border-t border-border-default pt-4">
        <p className="text-xs font-semibold uppercase tracking-wide text-text-muted">模型授权</p>
        <div className="flex flex-wrap gap-2">
          {OPEN_SOURCE_OPTIONS.map((option) => (
            <FilterChip
              key={option.value}
              label={option.label}
              description={option.description}
              active={openSourceFilter === option.value}
              onClick={() => onOpenSourceChange(option.value)}
            />
          ))}
        </div>
      </div>

      <div className="space-y-2 border-t border-border-default pt-4">
        <label
          htmlFor={modelSearchId}
          className="block text-xs font-semibold uppercase tracking-wide text-text-muted"
        >
          模型名称
        </label>
        <form
          className="flex flex-col gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            onModelQuerySubmit();
          }}
        >
          <input
            id={modelSearchId}
            type="search"
            value={modelQuery}
            onChange={(event) => onModelQueryChange(event.target.value)}
            placeholder="例如：Llama"
            className="w-full rounded-md border border-border-default bg-surface-input px-3 py-2 text-sm text-text-primary transition-colors focus:border-accent-base focus:outline-none touch-manipulation"
          />
          <div className="flex gap-2">
            <button
              type="submit"
              className="flex-1 rounded-md border border-border-default px-3 py-2 text-xs font-medium text-text-secondary transition-colors hover:border-accent-base hover:text-text-primary touch-manipulation"
            >
              搜索
            </button>
            {modelQuery ? (
              <button
                type="button"
                onClick={onModelQueryClear}
                className="flex-1 rounded-md border border-transparent px-3 py-2 text-xs text-text-muted transition-colors hover:text-text-primary touch-manipulation"
              >
                清空
              </button>
            ) : null}
          </div>
        </form>
      </div>
    </div>
  );
};

export default FilterFields;
