import { useQuery } from "@tanstack/react-query";
import { useState, useMemo } from "react";
import { ChevronDownIcon } from "@heroicons/react/24/outline";
import { fetchAnalyzedModels } from "../api/client";

interface AnalysisFeatureBrowserProps {
  onFeatureSelect?: (feature: string | undefined) => void;
  selectedFeature?: string;
}

const AnalysisFeatureBrowser = ({ onFeatureSelect, selectedFeature }: AnalysisFeatureBrowserProps) => {
  const [isExpanded, setIsExpanded] = useState(false);

  // 获取所有已分析的模型以提取特征列表
  const { data: analyzedData, isLoading } = useQuery({
    queryKey: ["analyzed-models-all-features"],
    queryFn: () =>
      fetchAnalyzedModels({
        page: 1,
        page_size: 100, // 获取足够的模型来提取特征
      }),
    staleTime: 1000 * 60 * 30, // 30分钟缓存
  });

  // 从所有模型中提取并去重特征
  const features = useMemo(() => {
    if (!analyzedData || !analyzedData.items) return [];

    const featureSet = new Set<string>();
    analyzedData.items.forEach((model) => {
      if (model.key_features && Array.isArray(model.key_features)) {
        model.key_features.forEach((feature) => {
          if (feature && typeof feature === "string") {
            featureSet.add(feature);
          }
        });
      }
    });

    return Array.from(featureSet).sort();
  }, [analyzedData]);

  const handleFeatureClick = (feature: string) => {
    onFeatureSelect?.(feature);
    setIsExpanded(false);
  };

  return (
    <div className="space-y-2">
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="flex w-full items-center justify-between rounded-lg border border-border-default bg-surface-raised px-3 py-2 text-xs font-medium text-text-secondary transition hover:border-accent-base hover:text-text-primary"
      >
        <span>
          {selectedFeature ? `已选择: ${selectedFeature}` : "按AI特征筛选"}
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
          ) : features.length > 0 ? (
            <div className="flex flex-wrap gap-2">
              {features.map((feature) => (
                <button
                  key={feature}
                  onClick={() => handleFeatureClick(feature)}
                  className={`rounded-full px-2.5 py-1 text-xs font-medium transition ${
                    selectedFeature === feature
                      ? "border border-accent-base bg-accent-soft text-accent-base"
                      : "border border-border-default/50 bg-surface-raised text-text-secondary hover:border-accent-base/50 hover:text-text-primary"
                  }`}
                >
                  {feature}
                </button>
              ))}
            </div>
          ) : (
            <div className="py-4 text-center text-xs text-text-muted">
              暂无特征
            </div>
          )}

          {/* 清除选择 */}
          {selectedFeature && (
            <button
              onClick={() => {
                onFeatureSelect?.(undefined);
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

export default AnalysisFeatureBrowser;
