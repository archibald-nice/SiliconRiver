import { FormEvent, KeyboardEvent, useId } from "react";

export type TimelinePresetRange = "all" | "30d" | "6m" | "1y";

type TimelineFiltersProps = {
  activeRange: TimelinePresetRange;
  customYear?: number | null;
  providers: string[];
  selectedProvider: string | null;
  onProviderChange: (value: string | null) => void;
  modelQuery: string;
  onModelQueryChange: (value: string) => void;
  onModelQuerySubmit: () => void;
  onModelQueryClear: () => void;
  openSourceFilter: "all" | "open" | "closed";
  onOpenSourceChange: (value: "all" | "open" | "closed") => void;
  onPresetChange: (range: TimelinePresetRange) => void;
  onCustomYearChange: (year: number | null) => void;
};

const PRESET_OPTIONS: { label: string; value: TimelinePresetRange; description: string }[] = [
  { label: "不限", value: "all", description: "显示所有时间范围的模型" },
  { label: "近30天", value: "30d", description: "呈现最近30天新增的模型" },
  { label: "近6个月", value: "6m", description: "呈现最近6个月新增的模型" },
  { label: "今年", value: "1y", description: "呈现今年发布的模型" },
];

const OPEN_SOURCE_OPTIONS: { label: string; value: "all" | "open" | "closed"; description: string }[] = [
  { label: "全部", value: "all", description: "查看全部模型" },
  { label: "开源", value: "open", description: "仅查看开源模型" },
  { label: "闭源", value: "closed", description: "仅查看闭源模型" },
];

const TimelineFilters = ({
  activeRange,
  customYear,
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
  onCustomYearChange,
}: TimelineFiltersProps) => {
  const inputId = useId();
  const providerSelectId = useId();
  const modelSearchId = useId();

  const handleCustomSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const formData = new FormData(event.currentTarget);
    const yearValue = formData.get("year")?.toString();
    if (!yearValue) {
      onCustomYearChange(null);
      return;
    }
    const year = Number.parseInt(yearValue, 10);
    if (!Number.isNaN(year) && year > 1900 && year < 3000) {
      onCustomYearChange(year);
    }
  };

  const handleTagKeyPress = (event: KeyboardEvent<HTMLSpanElement>, action: () => void) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      action();
    }
  };

  return (
    <div className="flex flex-col gap-2 rounded-xl border border-border-default bg-surface-raised p-4 text-sm text-text-secondary transition-colors">
      <p className="text-xs font-semibold text-text-secondary">时间范围</p>
      <div className="flex flex-wrap gap-2">
        {PRESET_OPTIONS.map((preset) => (
          <span
            key={preset.value}
            role="button"
            tabIndex={0}
            onClick={() => onPresetChange(preset.value)}
            onKeyDown={(event) => handleTagKeyPress(event, () => onPresetChange(preset.value))}
            className={`inline-flex items-center rounded-full border px-2 py-1 text-xs font-medium transition cursor-pointer select-none ${
              activeRange === preset.value
                ? "border-accent-base bg-accent-base/10 text-accent-base shadow-sm"
                : "border-border-default bg-surface-overlay text-text-secondary hover:border-accent-base hover:bg-surface-raised hover:text-text-primary"
            }`}
            title={preset.description}
          >
            {preset.label}
          </span>
        ))}
      </div>
      <p className="text-xs text-text-muted">或请选择具体年份：</p>
      <form className="flex items-center gap-3" onSubmit={handleCustomSubmit}>
        <input
          id={inputId}
          name="year"
          type="number"
          placeholder="例如 2024"
          defaultValue={customYear ?? ""}
          className="w-28 rounded-md border border-border-default bg-surface-input px-3 py-1 text-sm text-text-primary transition-colors focus:border-accent-base focus:outline-none"
        />
        <button
          type="submit"
          className="rounded-md border border-border-default px-2 py-1 text-xs font-medium text-text-secondary transition-colors hover:border-accent-base hover:text-text-primary"
        >
          确定
        </button>
        {customYear ? (
          <button
            type="button"
            onClick={() => onCustomYearChange(null)}
            className="text-xs text-text-muted hover:text-text-primary"
          >
            清除年份
          </button>
        ) : null}
      </form>

      {providers.length > 0 ? (
        <div className="space-y-2 border-t border-border-default pt-2">
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
            className="w-full rounded-md border border-border-default bg-surface-input px-3 py-1 text-sm text-text-primary transition-colors focus:border-accent-base focus:outline-none"
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

      <div className="space-y-2 border-t border-border-default pt-2">
        <p className="text-xs font-semibold uppercase tracking-wide text-text-muted">模型授权</p>
        <div className="flex flex-wrap gap-2">
          {OPEN_SOURCE_OPTIONS.map((option) => (
            <span
              key={option.value}
              role="button"
              tabIndex={0}
              onClick={() => onOpenSourceChange(option.value)}
              onKeyDown={(event) => handleTagKeyPress(event, () => onOpenSourceChange(option.value))}
              className={`inline-flex items-center rounded-full border px-2 py-1 text-xs font-medium transition cursor-pointer select-none ${
                openSourceFilter === option.value
                  ? "border-accent-base bg-accent-base/10 text-accent-base shadow-sm"
                  : "border-border-default bg-surface-overlay text-text-secondary hover:border-accent-base hover:bg-surface-raised hover:text-text-primary"
              }`}
              title={option.description}
            >
              {option.label}
            </span>
          ))}
        </div>
      </div>

      <div className="space-y-2 border-t border-border-default pt-2">
        <label
          htmlFor={modelSearchId}
          className="block text-xs font-semibold uppercase tracking-wide text-text-muted"
        >
          模型名称
        </label>
        <form
          className="flex flex-col gap-2 sm:flex-row sm:items-center"
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
            className="flex-1 rounded-md border border-border-default bg-surface-input px-3 py-2 text-sm text-text-primary transition-colors focus:border-accent-base focus:outline-none"
          />
          <div className="flex gap-2">
            <button
              type="submit"
              className="rounded-md border border-border-default px-2 py-1 text-xs font-medium text-text-secondary transition-colors hover:border-accent-base hover:text-text-primary"
            >
              搜索
            </button>
            {modelQuery ? (
              <button
                type="button"
                onClick={onModelQueryClear}
                className="rounded-md border border-transparent px-2 py-1 text-xs text-text-muted transition-colors hover:text-text-primary"
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

export default TimelineFilters;
