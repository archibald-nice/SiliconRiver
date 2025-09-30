interface FilterPanelProps {
  providers: string[];
  provider?: string;
  onProviderChange: (value: string) => void;
  search: string;
  onSearchChange: (value: string) => void;
}

const FilterPanel = ({ providers, provider, onProviderChange, search, onSearchChange }: FilterPanelProps) => {
  return (
    <div className="flex flex-col gap-4 rounded-xl border border-slate-800 bg-black/40 p-4 md:flex-row md:items-center md:justify-between">
      <div className="flex items-center gap-2">
        <label className="text-sm text-slate-400" htmlFor="provider-select">
          厂商
        </label>
        <select
          id="provider-select"
          value={provider ?? ""}
          onChange={(event) => onProviderChange(event.target.value)}
          className="rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm focus:border-river-accent focus:outline-none"
        >
          <option value="">全部</option>
          {providers.map((item) => (
            <option key={item} value={item}>
              {item}
            </option>
          ))}
        </select>
      </div>
      <div className="flex items-center gap-2">
        <label className="text-sm text-slate-400" htmlFor="search-input">
          搜索
        </label>
        <input
          id="search-input"
          type="search"
          placeholder="模型名称或描述"
          value={search}
          onChange={(event) => onSearchChange(event.target.value)}
          className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm focus:border-river-accent focus:outline-none md:w-64"
        />
      </div>
    </div>
  );
};

export default FilterPanel;
