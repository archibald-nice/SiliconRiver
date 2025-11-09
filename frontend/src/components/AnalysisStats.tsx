import { useQuery } from "@tanstack/react-query";
import { fetchAnalysisStats } from "../api/client";
import type { AnalysisStats as AnalysisStatsType } from "../api/client";

interface AnalysisStatsProps {
  provider?: string;
  compact?: boolean;
}

const AnalysisStats = ({ provider, compact = false }: AnalysisStatsProps) => {
  const { data: stats, isLoading } = useQuery<AnalysisStatsType>({
    queryKey: ["analysis-stats", provider],
    queryFn: () => fetchAnalysisStats(provider),
    staleTime: 1000 * 60 * 5, // 5分钟缓存
    retry: 1,
  });

  if (isLoading) {
    return (
      <div className={compact ? "space-y-1" : "space-y-2"}>
        <div className={`h-3 w-32 animate-pulse rounded ${compact ? "bg-surface-chip/50" : "bg-surface-chip"}`} />
        <div className={`h-3 w-24 animate-pulse rounded ${compact ? "bg-surface-chip/50" : "bg-surface-chip"}`} />
      </div>
    );
  }

  if (!stats) {
    return null;
  }

  const progressPercent = stats.total_models > 0 ? (stats.analyzed_models / stats.total_models) * 100 : 0;

  if (compact) {
    return (
      <div className="space-y-2 rounded-lg border border-border-default/50 bg-surface-chip/20 p-3">
        <div className="flex items-center justify-between text-xs">
          <span className="text-text-muted">AI分析进度</span>
          <span className="font-semibold text-accent-base">{stats.analysis_rate.toFixed(1)}%</span>
        </div>
        <div className="h-1.5 w-full overflow-hidden rounded-full bg-surface-chip/50">
          <div
            className="h-full bg-gradient-to-r from-accent-base to-accent-soft transition-all duration-300"
            style={{ width: `${progressPercent}%` }}
          />
        </div>
        <div className="flex items-center justify-between text-xs text-text-muted">
          <span>已分析：{stats.analyzed_models}</span>
          <span>总计：{stats.total_models}</span>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4 rounded-xl border border-border-default bg-surface-raised p-4">
      <div>
        <h3 className="mb-3 text-sm font-semibold text-text-primary">📊 AI分析统计</h3>
      </div>

      {/* 统计卡片 */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {/* 总模型数 */}
        <div className="rounded-lg bg-surface-chip/30 p-3">
          <p className="text-xs text-text-muted">总模型数</p>
          <p className="mt-1 text-lg font-semibold text-text-primary">{stats.total_models}</p>
        </div>

        {/* 已分析 */}
        <div className="rounded-lg bg-surface-chip/30 p-3">
          <p className="text-xs text-text-muted">已分析</p>
          <p className="mt-1 text-lg font-semibold text-accent-base">{stats.analyzed_models}</p>
        </div>

        {/* 未分析 */}
        <div className="rounded-lg bg-surface-chip/30 p-3">
          <p className="text-xs text-text-muted">未分析</p>
          <p className="mt-1 text-lg font-semibold text-text-secondary">{stats.unanalyzed_models}</p>
        </div>

        {/* 分析率 */}
        <div className="rounded-lg bg-surface-chip/30 p-3">
          <p className="text-xs text-text-muted">分析率</p>
          <p className="mt-1 text-lg font-semibold text-accent-base">{stats.analysis_rate.toFixed(1)}%</p>
        </div>
      </div>

      {/* 进度条 */}
      <div className="space-y-2">
        <div className="flex items-center justify-between text-xs text-text-muted">
          <span>分析进度</span>
          <span>{stats.analyzed_models} / {stats.total_models}</span>
        </div>
        <div className="h-2 w-full overflow-hidden rounded-full bg-surface-chip">
          <div
            className="h-full bg-gradient-to-r from-accent-base via-accent-base to-accent-soft transition-all duration-500"
            style={{ width: `${progressPercent}%` }}
          />
        </div>
      </div>

      {/* 信息提示 */}
      <div className="border-t border-border-default/30 pt-3">
        {stats.analysis_rate === 100 ? (
          <p className="text-xs text-text-muted">✅ 所有模型已完成AI分析</p>
        ) : stats.analysis_rate > 50 ? (
          <p className="text-xs text-text-muted">⏳ AI分析进行中，已完成大部分模型</p>
        ) : (
          <p className="text-xs text-text-muted">🔄 AI分析进行中...</p>
        )}
      </div>
    </div>
  );
};

export default AnalysisStats;
