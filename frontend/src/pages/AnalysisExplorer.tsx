import { useState, useMemo } from "react";
import { MagnifyingGlassIcon, XMarkIcon } from "@heroicons/react/24/outline";
import AnalysisStats from "../components/AnalysisStats";
import AnalysisGallery from "../components/AnalysisGallery";

const AnalysisExplorer = () => {
  const [selectedFeature, setSelectedFeature] = useState<string | undefined>();
  const [selectedProvider, setSelectedProvider] = useState<string | undefined>();
  const [searchQuery, setSearchQuery] = useState("");

  // 常见的AI特征
  const commonFeatures = [
    { label: "多语言", category: "Language" },
    { label: "代码生成", category: "Ability" },
    { label: "上下文窗口长", category: "Feature" },
    { label: "对话能力", category: "Ability" },
    { label: "推理能力", category: "Ability" },
    { label: "指令跟随", category: "Ability" },
    { label: "长文本处理", category: "Feature" },
    { label: "成本优化", category: "Feature" },
  ];

  const providers = [
    "meta-llama",
    "google",
    "microsoft",
    "openai",
    "anthropic",
    "mistral",
    "others",
  ];

  const handleFeatureToggle = (feature: string) => {
    setSelectedFeature(selectedFeature === feature ? undefined : feature);
  };

  const handleProviderToggle = (provider: string) => {
    setSelectedProvider(selectedProvider === provider ? undefined : provider);
  };

  const handleClearFilters = () => {
    setSelectedFeature(undefined);
    setSelectedProvider(undefined);
    setSearchQuery("");
  };

  const hasActiveFilters = selectedFeature || selectedProvider || searchQuery;

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-surface-base text-text-primary transition-colors">
      {/* 页面头 */}
      <header className="shrink-0 border-b border-border-strong bg-surface-overlay backdrop-blur-md transition-colors">
        <div className="flex w-full items-center justify-between gap-4 px-6 py-3">
          <div>
            <h1 className="text-lg font-semibold text-text-primary">AI分析浏览器</h1>
            <p className="text-xs text-text-muted">探索已分析的模型及其AI衍生见解</p>
          </div>
        </div>
      </header>

      {/* 主容器 */}
      <main className="flex min-w-0 flex-1 overflow-hidden px-6 py-3 gap-6">
        {/* 左侧面板：统计和过滤器 */}
        <aside className="w-80 shrink-0 flex flex-col gap-4 overflow-y-auto">
          {/* AI分析统计 */}
          <AnalysisStats />

          {/* 分割线 */}
          <div className="border-b border-border-default/30" />

          {/* 过滤器面板 */}
          <div className="space-y-4">
            <h3 className="text-sm font-semibold text-text-primary">📋 过滤器</h3>

            {/* 搜索框 */}
            <div className="space-y-2">
              <label className="text-xs font-semibold uppercase tracking-wider text-text-muted">
                🔍 搜索模型
              </label>
              <div className="relative">
                <MagnifyingGlassIcon className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-text-muted" />
                <input
                  type="text"
                  placeholder="输入模型名称或ID..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="w-full rounded-lg border border-border-default bg-surface-raised px-3 py-2 pl-9 text-sm text-text-primary placeholder-text-muted transition focus:border-accent-base focus:outline-none focus:ring-1 focus:ring-accent-base/30"
                />
              </div>
            </div>

            {/* 提供商过滤 */}
            <div className="space-y-2">
              <label className="text-xs font-semibold uppercase tracking-wider text-text-muted">
                🏢 提供商
              </label>
              <div className="flex flex-wrap gap-2">
                {providers.map((provider) => (
                  <button
                    key={provider}
                    onClick={() => handleProviderToggle(provider)}
                    className={`rounded-full px-3 py-1 text-xs font-medium transition ${
                      selectedProvider === provider
                        ? "border-accent-base bg-accent-soft text-accent-base"
                        : "border border-border-default bg-surface-raised text-text-secondary hover:border-accent-base hover:text-text-primary"
                    }`}
                  >
                    {provider}
                  </button>
                ))}
              </div>
            </div>

            {/* 特征过滤 */}
            <div className="space-y-2">
              <label className="text-xs font-semibold uppercase tracking-wider text-text-muted">
                ⭐ 常见特征
              </label>
              <div className="flex flex-wrap gap-2">
                {commonFeatures.map((feature) => (
                  <button
                    key={feature.label}
                    onClick={() => handleFeatureToggle(feature.label)}
                    className={`rounded-full px-3 py-1 text-xs font-medium transition ${
                      selectedFeature === feature.label
                        ? "border-accent-base bg-accent-soft text-accent-base"
                        : "border border-border-default bg-surface-raised text-text-secondary hover:border-accent-base hover:text-text-primary"
                    }`}
                  >
                    {feature.label}
                  </button>
                ))}
              </div>
            </div>

            {/* 清除过滤 */}
            {hasActiveFilters && (
              <button
                onClick={handleClearFilters}
                className="flex w-full items-center justify-center gap-2 rounded-lg border border-border-default/50 bg-surface-chip/30 px-3 py-2 text-xs font-medium text-text-secondary transition hover:border-accent-base/50 hover:text-text-primary"
              >
                <XMarkIcon className="h-4 w-4" />
                清除过滤器
              </button>
            )}
          </div>
        </aside>

        {/* 右侧面板：模型列表 */}
        <section className="flex min-w-0 flex-1 flex-col">
          <div className="flex min-h-0 flex-1 flex-col rounded-2xl border border-border-default bg-surface-raised shadow-lg shadow-accent transition-colors">
            <header className="shrink-0 border-b border-border-default px-6 py-3">
              <div className="flex items-center justify-between">
                <div>
                  <h2 className="text-lg font-semibold text-text-primary">分析结果</h2>
                  <p className="mt-1 text-xs text-text-muted">
                    {selectedProvider && `提供商: ${selectedProvider}`}
                    {selectedProvider && selectedFeature && " · "}
                    {selectedFeature && `特征: ${selectedFeature}`}
                    {searchQuery && (
                      <>
                        {(selectedProvider || selectedFeature) && " · "}
                        搜索: "{searchQuery}"
                      </>
                    )}
                  </p>
                </div>
              </div>
            </header>

            <div className="min-h-0 flex-1 overflow-y-auto px-6 py-4">
              <AnalysisGallery
                provider={selectedProvider}
                feature={selectedFeature}
                searchQuery={searchQuery}
                pageSize={15}
              />
            </div>
          </div>
        </section>
      </main>
    </div>
  );
};

export default AnalysisExplorer;
