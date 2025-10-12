import { FormEvent, useId } from "react";

export type TimelinePresetRange = "30d" | "6m" | "1y";

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
  { label: "Last 30 days", value: "30d", description: "Show models from the last 30 days" },
  { label: "Last 6 months", value: "6m", description: "Show models from the last 6 months" },
  { label: "This year", value: "1y", description: "Show models from the current year" },
];

const OPEN_SOURCE_OPTIONS: { label: string; value: "all" | "open" | "closed"; description: string }[] = [
  { label: "All", value: "all", description: "Show all models" },
  { label: "Open Source", value: "open", description: "Show open-source models only" },
  { label: "Closed Source", value: "closed", description: "Show closed-source models only" },
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

  return (
    <div className="flex flex-col gap-4 rounded-xl border border-border-default bg-surface-raised p-4 text-sm text-text-secondary transition-colors">
      <p className="text-sm text-text-secondary">Pick a time window:</p>
      <div className="flex flex-wrap gap-3">
        {PRESET_OPTIONS.map((preset) => (
          <button
            key={preset.value}
            type="button"
            onClick={() => onPresetChange(preset.value)}
            className={`rounded-full px-4 py-2 transition ${
              activeRange === preset.value
                ? "bg-accent-base text-accent-contrast shadow-sm"
                : "bg-surface-chip text-text-secondary hover:text-text-primary"
            }`}
          >
            {preset.label}
          </button>
        ))}
      </div>
      <p className="text-xs text-text-muted">Or pick a specific year:</p>
      <form className="flex items-center gap-3" onSubmit={handleCustomSubmit}>
        <input
          id={inputId}
          name="year"
          type="number"
          placeholder="e.g. 2024"
          defaultValue={customYear ?? ""}
          className="w-28 rounded-md border border-border-default bg-surface-input px-3 py-1 text-sm text-text-primary transition-colors focus:border-accent-base focus:outline-none"
        />
        <button
          type="submit"
          className="rounded-md border border-border-default px-3 py-1 text-sm text-text-secondary transition-colors hover:border-accent-base hover:text-text-primary"
        >
          Apply
        </button>
        {customYear && (
          <button
            type="button"
            onClick={() => onCustomYearChange(null)}
            className="text-xs text-text-muted hover:text-text-primary"
          >
            Clear year
          </button>
        )}
      </form>

      {providers.length > 0 ? (
        <div className="space-y-2 border-t border-border-default pt-4">
          <label
            htmlFor={providerSelectId}
            className="block text-xs font-semibold uppercase tracking-wide text-text-muted"
          >
            Provider
          </label>
          <select
            id={providerSelectId}
            value={selectedProvider ?? ""}
            onChange={(event) => onProviderChange(event.target.value === "" ? null : event.target.value)}
            className="w-full rounded-md border border-border-default bg-surface-input px-3 py-2 text-sm text-text-primary transition-colors focus:border-accent-base focus:outline-none"
          >
            <option value="">All providers</option>
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
              Clear provider
            </button>
          ) : null}
        </div>
      ) : null}

      <div className="space-y-2 border-t border-border-default pt-4">
        <p className="text-xs font-semibold uppercase tracking-wide text-text-muted">Model type</p>
        <div className="flex flex-wrap gap-2">
          {OPEN_SOURCE_OPTIONS.map((option) => (
            <button
              key={option.value}
              type="button"
              onClick={() => onOpenSourceChange(option.value)}
              className={`rounded-full px-3 py-1.5 text-xs transition ${
                openSourceFilter === option.value
                  ? "bg-accent-base text-accent-contrast shadow-sm"
                  : "bg-surface-chip text-text-secondary hover:text-text-primary"
              }`}
              title={option.description}
            >
              {option.label}
            </button>
          ))}
        </div>
      </div>

      <div className="space-y-2 border-t border-border-default pt-4">
        <label
          htmlFor={modelSearchId}
          className="block text-xs font-semibold uppercase tracking-wide text-text-muted"
        >
          Model name
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
            placeholder="e.g. Llama"
            className="flex-1 rounded-md border border-border-default bg-surface-input px-3 py-2 text-sm text-text-primary transition-colors focus:border-accent-base focus:outline-none"
          />
          <div className="flex gap-2">
            <button
              type="submit"
              className="rounded-md border border-border-default px-3 py-1.5 text-xs font-medium text-text-secondary transition-colors hover:border-accent-base hover:text-text-primary"
            >
              Search
            </button>
            {modelQuery ? (
              <button
                type="button"
                onClick={onModelQueryClear}
                className="rounded-md border border-transparent px-3 py-1.5 text-xs text-text-muted transition-colors hover:text-text-primary"
              >
                Clear
              </button>
            ) : null}
          </div>
        </form>
      </div>
    </div>
  );
};

export default TimelineFilters;
