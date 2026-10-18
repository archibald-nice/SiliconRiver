import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { buildApiUrl } from "../api/client";

interface ArenaScoreDisplayProps {
  modelId: string;
  layout?: "compact" | "detailed";
  className?: string;
}

interface ArenaScore {
  model_id: string;
  source: string;
  rank?: number;
  score?: number;
  category: string;
  updated_at?: string;
}

interface ArenaScoreSummary {
  has_score: boolean;
  sources: string[];
  combined_score?: number;
  details: ArenaScore[];
}

const ArenaScoreDisplay = ({
  modelId,
  layout = "detailed",
  className = "",
}: ArenaScoreDisplayProps) => {
  const { data: scores, isLoading, error } = useQuery({
    queryKey: ["arena-scores", modelId],
    queryFn: async () => {
      const url = buildApiUrl(`/api/arena/scores/${modelId}`);
      const response = await fetch(url);
      if (!response.ok) throw new Error("Failed to fetch scores");
      return (await response.json()) as ArenaScoreSummary;
    },
  });

  // LMArena 有 29 个 category，全列出来会把弹窗拉成一屏半；overall 优先，其余按分数降序，只显示前几个。
  const DETAIL_LIMIT = 6;
  const sortedDetails = useMemo(() => {
    const rows = scores?.details ?? [];
    return [...rows].sort((a, b) => {
      if (a.category === "overall" && b.category !== "overall") return -1;
      if (b.category === "overall" && a.category !== "overall") return 1;
      return (b.score ?? 0) - (a.score ?? 0);
    });
  }, [scores]);
  const visibleDetails = sortedDetails.slice(0, DETAIL_LIMIT);
  const hiddenCount = Math.max(0, sortedDetails.length - visibleDetails.length);

  // 紧凑模式
  if (layout === "compact") {
    if (!scores?.has_score) {
      return (
        <div className={`text-xs text-slate-400 ${className}`}>
          <span className="inline-block px-2 py-1 rounded-full bg-slate-700/20 border border-slate-600/30">
            无评测分数
          </span>
        </div>
      );
    }

    return (
      <div className={`flex items-center gap-2 ${className}`}>
        {scores.combined_score && (
          <div className="inline-flex items-center rounded-full bg-amber-900/20 px-3 py-1 text-xs font-semibold text-amber-400 border border-amber-600/30">
            ⭐ {scores.combined_score}
          </div>
        )}
        <div className="flex gap-1">
          {scores.sources.map((source) => (
            <span
              key={source}
              className="inline-block px-2 py-1 text-xs font-medium rounded-full bg-slate-700/20 text-slate-300 border border-slate-600/30"
            >
              {source}
            </span>
          ))}
        </div>
      </div>
    );
  }

  // 详细模式
  if (isLoading) {
    return (
      <div className={`text-sm text-slate-400 ${className}`}>
        加载评分中...
      </div>
    );
  }

  if (error || !scores) {
    return (
      <div className={`text-sm text-rose-400 ${className}`}>
        加载评分失败
      </div>
    );
  }

  if (!scores.has_score) {
    return (
      <div className={`rounded-lg border border-slate-700 bg-slate-800/30 p-4 ${className}`}>
        <div className="flex items-center gap-2 mb-3">
          <span className="text-lg">📊</span>
          <h4 className="text-sm font-semibold text-slate-300">行业评分</h4>
        </div>
        <p className="text-sm text-slate-400">暂无评分数据</p>
      </div>
    );
  }

  return (
    <div className={`rounded-lg border border-slate-700 bg-slate-800/30 p-4 ${className}`}>
      <div className="flex items-center gap-2 mb-4">
        <span className="text-lg">⭐</span>
        <h4 className="text-sm font-semibold text-slate-200">行业评分</h4>
      </div>

      {/* 综合评分 */}
      {scores.combined_score && (
        <div className="mb-4 rounded-lg bg-gradient-to-r from-amber-900/40 to-amber-900/20 p-4 border border-amber-700/50">
          <p className="text-xs font-semibold text-amber-400 uppercase tracking-wide mb-1">
            综合评分
          </p>
          <p className="text-3xl font-bold text-amber-400">{scores.combined_score}</p>
          <p className="text-xs text-amber-300 mt-1">基于多个数据源的加权平均</p>
        </div>
      )}

      {/* 评分详情表格 */}
      <div className="space-y-2">
        <p className="text-xs font-semibold text-slate-400 uppercase tracking-wide mb-3">
          详细评分
        </p>
        {visibleDetails.map((detail, idx) => (
          <div
            key={idx}
            className="flex items-center justify-between rounded-lg bg-slate-700/20 p-3 border border-slate-700/40"
          >
            <div className="flex-1">
              <p className="text-xs font-semibold text-slate-300 capitalize">
                {detail.source}
                {detail.category !== "overall" && ` - ${detail.category}`}
              </p>
              {detail.rank && (
                <p className="text-xs text-slate-500 mt-1">
                  排名: #{detail.rank}
                </p>
              )}
            </div>
            {detail.score && (
              <div className="text-right">
                <p className="text-lg font-bold text-slate-200">{detail.score}</p>
              </div>
            )}
            {!detail.score && detail.rank && (
              <div className="text-right">
                <p className="text-sm font-medium text-slate-400">评分中...</p>
              </div>
            )}
          </div>
        ))}
        {hiddenCount > 0 && (
          <p className="text-xs text-slate-500 pt-1">另有 {hiddenCount} 个分类未显示</p>
        )}
      </div>

      {/* 数据源信息 */}
      {scores.sources.length > 0 && (
        <div className="mt-4 border-t border-slate-700/50 pt-3">
          <p className="text-xs font-semibold text-slate-400 uppercase tracking-wide mb-2">
            数据来源
          </p>
          <div className="flex flex-wrap gap-2">
            {scores.sources.map((source) => (
              <span
                key={source}
                className="inline-block px-2.5 py-1.5 rounded-full bg-slate-700/40 text-xs font-medium text-slate-300 border border-slate-600/30"
              >
                {source}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};

export default ArenaScoreDisplay;
