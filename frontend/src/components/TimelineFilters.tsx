import { FormEvent, KeyboardEvent, useId, useState, useEffect } from "react";

export type TimelinePresetRange = "all" | "30d" | "6m" | "1y";

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

// 与后端 /api/timeline 的 year 约束保持一致：Query(None, ge=1900, le=3000)（闭区间）
const YEAR_MIN = 1900;
const YEAR_MAX = 3000;

const OPEN_SOURCE_OPTIONS: { label: string; value: "all" | "open" | "closed"; description: string }[] = [
  { label: "全部", value: "all", description: "查看全部模型" },
  { label: "开源", value: "open", description: "仅查看开源模型" },
  { label: "闭源", value: "closed", description: "仅查看闭源模型" },
];

const FilterContent = ({
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
  inputId,
  providerSelectId,
  modelSearchId,
}: TimelineFiltersProps & {
  inputId: string;
  providerSelectId: string;
  modelSearchId: string;
}) => {
  // 年份输入用受控草稿值：输入过程中不被外部值打断，只在 customYear 真正变化时同步；
  // 「清除」按钮同时清空草稿，避免「筛选状态已清空、输入框还留着旧值」（ISSUE-012）。
  const [yearDraft, setYearDraft] = useState<string>(customYear != null ? String(customYear) : "");
  const [yearError, setYearError] = useState<string | null>(null);
  const yearErrorId = `${inputId}-year-error`;

  useEffect(() => {
    setYearDraft(customYear != null ? String(customYear) : "");
    setYearError(null);
  }, [customYear]);

  const handleCustomSubmit = (event: FormEvent<HTMLFormElement>) => {
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
      setYearError(`请输入 ${YEAR_MIN}–${YEAR_MAX} 之间的年份`);
      return;
    }
    setYearError(null);
    onCustomYearChange(year);
  };

  const handleTagKeyPress = (event: KeyboardEvent<HTMLSpanElement>, action: () => void) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      action();
    }
  };

  return (
    <div className="space-y-4">
      <div>
        <p className="text-xs font-semibold text-text-secondary mb-2">时间范围</p>
        <div className="flex flex-wrap gap-2">
          {PRESET_OPTIONS.map((preset) => (
            <span
              key={preset.value}
              role="button"
              tabIndex={0}
              onClick={() => onPresetChange(preset.value)}
              onKeyDown={(event) => handleTagKeyPress(event, () => onPresetChange(preset.value))}
              className={`inline-flex items-center rounded-full border px-3 py-1.5 text-xs font-medium transition cursor-pointer select-none touch-manipulation ${
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
      </div>

      <div>
        <p className="text-xs text-text-muted mb-2">或请选择具体年份：</p>
        <form className="flex flex-col gap-2 sm:flex-row sm:items-center" onSubmit={handleCustomSubmit}>
          <input
            id={inputId}
            name="year"
            type="number"
            placeholder="例如 2024"
            value={yearDraft}
            onChange={(event) => {
              setYearDraft(event.target.value);
              setYearError(null);
            }}
            aria-invalid={yearError ? true : undefined}
            aria-describedby={yearError ? yearErrorId : undefined}
            className="flex-1 rounded-md border border-border-default bg-surface-input px-3 py-2 text-sm text-text-primary transition-colors focus:border-accent-base focus:outline-none"
          />
          <div className="flex gap-2">
            <button
              type="submit"
              className="rounded-md border border-border-default px-3 py-2 text-xs font-medium text-text-secondary transition-colors hover:border-accent-base hover:text-text-primary touch-manipulation"
            >
              确定
            </button>
            {customYear ? (
              <button
                type="button"
                onClick={() => {
                  setYearDraft("");
                  setYearError(null);
                  onCustomYearChange(null);
                }}
                className="text-xs text-text-muted hover:text-text-primary"
              >
                清除
              </button>
            ) : null}
          </div>
        </form>
        {yearError ? (
          <p id={yearErrorId} className="text-xs text-rose-400">
            {yearError}
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
            <span
              key={option.value}
              role="button"
              tabIndex={0}
              onClick={() => onOpenSourceChange(option.value)}
              onKeyDown={(event) => handleTagKeyPress(event, () => onOpenSourceChange(option.value))}
              className={`inline-flex items-center rounded-full border px-3 py-1.5 text-xs font-medium transition cursor-pointer select-none touch-manipulation ${
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

const TimelineFilters = (props: TimelineFiltersProps) => {
  const inputId = useId();
  const providerSelectId = useId();
  const modelSearchId = useId();

  return (
    <div className="hidden md:flex md:flex-col gap-2 rounded-xl border border-border-default bg-surface-raised p-4 text-sm text-text-secondary transition-colors">
      <FilterContent
        {...props}
        inputId={inputId}
        providerSelectId={providerSelectId}
        modelSearchId={modelSearchId}
      />
    </div>
  );
};

export default TimelineFilters;
