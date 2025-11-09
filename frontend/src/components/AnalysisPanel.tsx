import { useQuery } from "@tanstack/react-query";
import { fetchModelAnalysis } from "../api/client";
import type { ModelAnalysis } from "../api/client";

interface AnalysisPanelProps {
  modelId: string;
  modelName: string;
}

const AnalysisPanel = ({ modelId, modelName }: AnalysisPanelProps) => {
  const { data: analysis, isLoading, error } = useQuery<ModelAnalysis>({
    queryKey: ["model-analysis", modelId],
    queryFn: () => fetchModelAnalysis(modelId),
    staleTime: 1000 * 60 * 10, // 10分钟缓存
    retry: 1,
  });

  if (isLoading) {
    return (
      <div className="space-y-3">
        <div className="h-4 w-24 animate-pulse rounded bg-surface-chip" />
        <div className="space-y-2">
          <div className="h-3 w-full animate-pulse rounded bg-surface-chip" />
          <div className="h-3 w-3/4 animate-pulse rounded bg-surface-chip" />
        </div>
      </div>
    );
  }

  if (error || !analysis) {
    return (
      <div className="rounded-lg border border-border-default/50 bg-surface-chip/30 px-3 py-2">
        <p className="text-xs text-text-muted">暂无AI分析结果</p>
      </div>
    );
  }

  return (
    <div className="space-y-4 rounded-lg border border-border-default/50 bg-surface-chip/20 p-4">
      {/* 分析摘要 */}
      {analysis.analysis_summary && (
        <div>
          <h4 className="mb-2 text-xs font-semibold uppercase tracking-wider text-text-muted">
            📋 分析摘要
          </h4>
          <p className="text-sm leading-relaxed text-text-secondary">{analysis.analysis_summary}</p>
        </div>
      )}

      {/* 关键特性 */}
      {analysis.key_features && analysis.key_features.length > 0 && (
        <div>
          <h4 className="mb-2 text-xs font-semibold uppercase tracking-wider text-text-muted">
            ✨ 关键特性
          </h4>
          <ul className="space-y-1">
            {analysis.key_features.slice(0, 3).map((feature, idx) => (
              <li key={idx} className="flex items-start gap-2 text-sm text-text-secondary">
                <span className="mt-1 inline-flex h-1.5 w-1.5 shrink-0 rounded-full bg-accent-base" />
                <span>{feature}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* 应用场景 */}
      {analysis.use_cases && analysis.use_cases.length > 0 && (
        <div>
          <h4 className="mb-2 text-xs font-semibold uppercase tracking-wider text-text-muted">
            🎯 应用场景
          </h4>
          <ul className="space-y-1">
            {analysis.use_cases.slice(0, 3).map((useCase, idx) => (
              <li key={idx} className="flex items-start gap-2 text-sm text-text-secondary">
                <span className="mt-1 inline-flex h-1.5 w-1.5 shrink-0 rounded-full bg-accent-base" />
                <span>{useCase}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* AI标签 */}
      {analysis.tags && analysis.tags.length > 0 && (
        <div>
          <h4 className="mb-2 text-xs font-semibold uppercase tracking-wider text-text-muted">
            🏷️ AI标签
          </h4>
          <div className="flex flex-wrap gap-2">
            {analysis.tags.slice(0, 5).map((tag) => (
              <span
                key={tag}
                className="rounded-full bg-accent-soft/50 px-2.5 py-1 text-xs font-medium text-accent-base"
              >
                {tag}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* 分析信息 */}
      {analysis.analyzed_at && (
        <div className="border-t border-border-default/30 pt-3">
          <p className="text-xs text-text-muted">
            🤖 分析工具：{analysis.llm_model_used || "DeepSeek R1"} · 更新时间：
            {new Date(analysis.analyzed_at).toLocaleString("zh-CN")}
          </p>
        </div>
      )}
    </div>
  );
};

export default AnalysisPanel;
