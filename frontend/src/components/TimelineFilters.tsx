import { FormEvent, useId } from "react";

export type TimelinePresetRange = "30d" | "6m" | "1y";

type TimelineFiltersProps = {
  activeRange: TimelinePresetRange;
  customYear?: number | null;
  onPresetChange: (range: TimelinePresetRange) => void;
  onCustomYearChange: (year: number | null) => void;
};

const PRESET_OPTIONS: { label: string; value: TimelinePresetRange; description: string }[] = [
  { label: "Last 30 days", value: "30d", description: "Show models from the last 30 days" },
  { label: "Last 6 months", value: "6m", description: "Show models from the last 6 months" },
  { label: "This year", value: "1y", description: "Show models from the current year" },
];

const TimelineFilters = ({ activeRange, customYear, onPresetChange, onCustomYearChange }: TimelineFiltersProps) => {
  const inputId = useId();

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
              activeRange === preset.value ? "bg-accent-base text-accent-contrast shadow-sm" : "bg-surface-chip text-text-secondary hover:text-text-primary"
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
    </div>
  );
};

export default TimelineFilters;
