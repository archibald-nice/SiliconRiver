interface FilterPanelProps {
  providers: string[];
  provider?: string;
  onProviderChange: (value: string) => void;
  search: string;
  onSearchChange: (value: string) => void;
  className?: string;
}

const FilterPanel = ({
  providers,
  provider,
  onProviderChange,
  search,
  onSearchChange,
  className,
}: FilterPanelProps) => {
  const containerClasses = ["flex w-full flex-wrap items-center gap-3 text-text-secondary", className]
    .filter(Boolean)
    .join(" ");

  return (
    <div className={containerClasses}>
      <div className="flex items-center gap-2">
        <label className="text-xs uppercase tracking-wide text-text-muted" htmlFor="provider-select">
          厂商
        </label>
        <select
          id="provider-select"
          value={provider ?? ""}
          onChange={(event) => onProviderChange(event.target.value)}
          className="min-w-[8rem] rounded-md border border-border-default bg-surface-input px-3 py-2 text-sm text-text-primary transition-colors focus:border-accent-base focus:outline-none"
        >
          <option value="">全部</option>
          {providers.map((item) => (
            <option key={item} value={item}>
              {item}
            </option>
          ))}
        </select>
      </div>
      <div className="flex flex-1 items-center gap-2 md:flex-none">
        <label className="text-xs uppercase tracking-wide text-text-muted" htmlFor="search-input">
          搜索
        </label>
        <input
          id="search-input"
          type="search"
          placeholder="模型名称或描述"
          value={search}
          onChange={(event) => onSearchChange(event.target.value)}
          className="w-full rounded-md border border-border-default bg-surface-input px-3 py-2 text-sm text-text-primary transition-colors focus:border-accent-base focus:outline-none md:w-64"
        />
      </div>
    </div>
  );
};

export default FilterPanel;
