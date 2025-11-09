import { useQuery } from "@tanstack/react-query";
import { useState, useMemo } from "react";
import { fetchAnalyzedModels } from "../api/client";
import type { ModelAnalysis } from "../api/client";

interface AnalysisGalleryProps {
  provider?: string;
  feature?: string;
  searchQuery?: string;
  pageSize?: number;
}

const AnalysisGallery = ({ provider, feature, searchQuery, pageSize = 10 }: AnalysisGalleryProps) => {
  const [currentPage, setCurrentPage] = useState(1);

  const { data: analyzedData, isLoading } = useQuery({
    queryKey: ["analyzed-models", provider, feature, searchQuery, currentPage, pageSize],
    queryFn: () =>
      fetchAnalyzedModels({
        provider,
        feature,
        search: searchQuery,
        page: currentPage,
        page_size: pageSize,
      }),
    staleTime: 1000 * 60 * 5, // 5分钟缓存
    retry: 1,
  });

  const totalPages = useMemo(
    () => (analyzedData ? Math.ceil(analyzedData.total / pageSize) : 1),
    [analyzedData, pageSize]
  );

  const handlePrevPage = () => {
    setCurrentPage((prev) => Math.max(1, prev - 1));
  };

  const handleNextPage = () => {
    setCurrentPage((prev) => Math.min(totalPages, prev + 1));
  };

  if (isLoading && !analyzedData) {
    return (
      <div className="space-y-3">
        {[1, 2, 3].map((i) => (
          <div key={i} className="rounded-lg border border-border-default/50 bg-surface-chip/20 p-3">
            <div className="space-y-2">
              <div className="h-4 w-3/4 animate-pulse rounded bg-surface-chip" />
              <div className="h-3 w-full animate-pulse rounded bg-surface-chip" />
              <div className="flex gap-2">
                <div className="h-6 w-16 animate-pulse rounded bg-surface-chip" />
                <div className="h-6 w-16 animate-pulse rounded bg-surface-chip" />
              </div>
            </div>
          </div>
        ))}
      </div>
    );
  }

  if (!analyzedData || analyzedData.items.length === 0) {
    return (
      <div className="rounded-lg border border-border-default/50 bg-surface-chip/20 py-8 text-center">
        <p className="text-sm text-text-muted">暂无AI分析结果</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* 模型列表 */}
      <div className="space-y-3">
        {analyzedData.items.map((model) => (
          <AnalysisCard key={model.model_id} model={model} />
        ))}
      </div>

      {/* 分页控件 */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between border-t border-border-default/30 pt-3">
          <div className="text-xs text-text-muted">
            第 {currentPage} / {totalPages} 页 （共 {analyzedData.total} 个模型）
          </div>
          <div className="flex gap-2">
            <button
              onClick={handlePrevPage}
              disabled={currentPage === 1}
              className="rounded-md border border-border-default bg-surface-raised px-3 py-1 text-xs font-medium text-text-secondary transition disabled:opacity-50 hover:enabled:border-accent-base hover:enabled:text-text-primary"
            >
              上一页
            </button>
            <button
              onClick={handleNextPage}
              disabled={currentPage === totalPages}
              className="rounded-md border border-border-default bg-surface-raised px-3 py-1 text-xs font-medium text-text-secondary transition disabled:opacity-50 hover:enabled:border-accent-base hover:enabled:text-text-primary"
            >
              下一页
            </button>
          </div>
        </div>
      )}
    </div>
  );
};

interface AnalysisCardProps {
  model: ModelAnalysis;
}

const AnalysisCard = ({ model }: AnalysisCardProps) => {
  return (
    <article className="rounded-lg border border-border-default/50 bg-surface-chip/20 p-3 transition hover:border-accent-base/50 hover:bg-surface-chip/30">
      <div className="space-y-2">
        {/* 模型名称 */}
        <div>
          <p className="text-xs font-semibold uppercase tracking-wider text-text-muted">
            {model.model_id.includes("/") ? model.model_id.split("/")[0] : "Unknown"}
          </p>
          <h4 className="text-sm font-semibold text-accent-base">
            {model.model_id.includes("/") ? model.model_id.split("/")[1] : model.model_id}
          </h4>
        </div>

        {/* 分析摘要 */}
        {model.analysis_summary && (
          <p className="line-clamp-2 text-xs text-text-secondary">{model.analysis_summary}</p>
        )}

        {/* AI特征 */}
        {model.key_features && model.key_features.length > 0 && (
          <div className="flex flex-wrap gap-1.5 pt-1">
            {model.key_features.slice(0, 3).map((feature) => (
              <span
                key={feature}
                className="rounded-full bg-accent-soft/40 px-2 py-0.5 text-xs text-accent-base"
              >
                {feature}
              </span>
            ))}
            {model.key_features.length > 3 && (
              <span className="text-xs text-text-muted">+{model.key_features.length - 3}</span>
            )}
          </div>
        )}

        {/* 标签 */}
        {model.tags && model.tags.length > 0 && (
          <div className="flex flex-wrap gap-1.5 pt-1">
            {model.tags.slice(0, 3).map((tag) => (
              <span
                key={tag}
                className="rounded-full bg-surface-chip/60 px-2 py-0.5 text-xs text-text-secondary"
              >
                {tag}
              </span>
            ))}
            {model.tags.length > 3 && (
              <span className="text-xs text-text-muted">+{model.tags.length - 3}</span>
            )}
          </div>
        )}

        {/* 时间戳 */}
        {model.analyzed_at && (
          <p className="text-xs text-text-muted">
            分析于 {new Date(model.analyzed_at).toLocaleString("zh-CN")}
          </p>
        )}
      </div>
    </article>
  );
};

export default AnalysisGallery;
