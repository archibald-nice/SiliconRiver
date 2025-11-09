import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { ChevronDownIcon } from "@heroicons/react/24/outline";
import { fetchAnalysisTags } from "../api/client";

interface AnalysisTagBrowserProps {
  onTagSelect?: (tag: string | undefined) => void;
  selectedTag?: string;
}

const AnalysisTagBrowser = ({ onTagSelect, selectedTag }: AnalysisTagBrowserProps) => {
  const [isExpanded, setIsExpanded] = useState(false);

  // 从 API 获取标签列表
  const { data: tags = [], isLoading } = useQuery({
    queryKey: ["analysis-tags"],
    queryFn: fetchAnalysisTags,
    staleTime: 1000 * 60 * 30, // 30分钟缓存
  });

  const handleTagClick = (tag: string) => {
    onTagSelect?.(tag);
    setIsExpanded(false);
  };

  return (
    <div className="space-y-2">
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="flex w-full items-center justify-between rounded-lg border border-border-default bg-surface-raised px-3 py-2 text-xs font-medium text-text-secondary transition hover:border-accent-base hover:text-text-primary"
      >
        <span>
          {selectedTag ? `已选择: ${selectedTag}` : "按AI标签筛选"}
        </span>
        <ChevronDownIcon
          className={`h-4 w-4 transition ${isExpanded ? "rotate-180" : ""}`}
        />
      </button>

      {isExpanded && (
        <div className="space-y-3 rounded-lg border border-border-default/50 bg-surface-chip/20 p-3">
          {isLoading ? (
            <div className="py-4 text-center text-xs text-text-muted">
              加载中...
            </div>
          ) : tags.length > 0 ? (
            <div className="flex flex-wrap gap-2">
              {tags.map((tag) => (
                <button
                  key={tag}
                  onClick={() => handleTagClick(tag)}
                  className={`rounded-full px-2.5 py-1 text-xs font-medium transition ${
                    selectedTag === tag
                      ? "border border-accent-base bg-accent-soft text-accent-base"
                      : "border border-border-default/50 bg-surface-raised text-text-secondary hover:border-accent-base/50 hover:text-text-primary"
                  }`}
                >
                  {tag}
                </button>
              ))}
            </div>
          ) : (
            <div className="py-4 text-center text-xs text-text-muted">
              暂无标签
            </div>
          )}

          {/* 清除选择 */}
          {selectedTag && (
            <button
              onClick={() => {
                onTagSelect?.(undefined);
                setIsExpanded(false);
              }}
              className="w-full rounded-lg border border-border-default/30 bg-surface-chip/10 px-2 py-1.5 text-xs font-medium text-text-muted transition hover:border-border-default hover:text-text-secondary"
            >
              清除选择
            </button>
          )}
        </div>
      )}
    </div>
  );
};

export default AnalysisTagBrowser;
