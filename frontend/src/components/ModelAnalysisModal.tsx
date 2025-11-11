import { Dialog, Transition } from "@headlessui/react";
import { Fragment, useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchModelAnalysis, buildProviderAvatarUrl } from "../api/client";

interface ModelAnalysisModalProps {
  isOpen: boolean;
  onClose: () => void;
  modelId: string;
}

const ModelAnalysisModal = ({ isOpen, onClose, modelId }: ModelAnalysisModalProps) => {
  const [avatarError, setAvatarError] = useState(false);
  const { data: analysis, isLoading, error } = useQuery({
    queryKey: ["model-analysis", modelId],
    queryFn: () => fetchModelAnalysis(modelId),
    enabled: isOpen && !!modelId,
  });

  // 添加自定义滚动条样式到 DOM
  useEffect(() => {
    if (!document.getElementById("modal-scrollbar-styles")) {
      const style = document.createElement("style");
      style.id = "modal-scrollbar-styles";
      style.textContent = `
        .custom-scrollbar::-webkit-scrollbar {
          width: 6px;
        }
        .custom-scrollbar::-webkit-scrollbar-track {
          background: transparent;
        }
        .custom-scrollbar::-webkit-scrollbar-thumb {
          background: rgba(148, 163, 184, 0.3);
          border-radius: 3px;
          transition: background 0.2s;
        }
        .custom-scrollbar::-webkit-scrollbar-thumb:hover {
          background: rgba(148, 163, 184, 0.5);
        }
        .custom-scrollbar {
          scrollbar-width: thin;
          scrollbar-color: rgba(148, 163, 184, 0.3) transparent;
        }
      `;
      document.head.appendChild(style);
    }
  }, []);

  // 获取提供商名称
  const provider = analysis ? analysis.model_id.split("/")[0] : null;
  const avatarUrl = provider ? buildProviderAvatarUrl(provider) : null;

  return (
    <Transition appear show={isOpen} as={Fragment}>
      <Dialog as="div" className="relative z-50" onClose={onClose}>
        {/* 背景蒙层 */}
        <Transition.Child
          as={Fragment}
          enter="ease-out duration-200"
          enterFrom="opacity-0"
          enterTo="opacity-100"
          leave="ease-in duration-200"
          leaveFrom="opacity-100"
          leaveTo="opacity-0"
        >
          <div className="fixed inset-0 bg-black/40 backdrop-blur-sm" />
        </Transition.Child>

        {/* 弹窗容器 */}
        <div className="fixed inset-0 overflow-y-auto">
          <div className="flex min-h-full items-center justify-center p-4">
            <Transition.Child
              as={Fragment}
              enter="ease-out duration-300"
              enterFrom="opacity-0 scale-95"
              enterTo="opacity-100 scale-100"
              leave="ease-in duration-200"
              leaveFrom="opacity-100 scale-100"
              leaveTo="opacity-0 scale-95"
            >
              <Dialog.Panel className="custom-scrollbar w-full max-w-6xl transform overflow-hidden rounded-2xl border border-border-default bg-surface-raised p-6 text-left align-middle shadow-xl shadow-accent transition-all max-h-[85vh] overflow-y-auto">
                {/* 关闭按钮 */}
                <button
                  onClick={onClose}
                  className="absolute right-6 top-6 rounded-lg p-1.5 hover:bg-surface-chip transition-colors"
                  aria-label="关闭"
                >
                  <svg className="h-6 w-6 text-text-secondary" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>

                {/* 加载状态 */}
                {isLoading && (
                  <div className="flex items-center justify-center py-12">
                    <p className="text-text-muted">加载分析数据中...</p>
                  </div>
                )}

                {/* 错误状态 */}
                {error && (
                  <div className="flex items-center justify-center py-12">
                    <p className="text-rose-400">加载分析数据失败，请重试</p>
                  </div>
                )}

                {/* 内容区域 - 双栏布局 */}
                {!isLoading && !error && analysis && (
                  <div className="space-y-6">
                    {/* 顶部：提供商 + 模型名称 */}
                    <div className="flex items-start gap-4 pb-4 border-b border-border-default/40">
                      <div className="flex h-12 w-12 shrink-0 items-center justify-center overflow-hidden rounded-lg border border-border-default bg-avatar-bg">
                        {avatarUrl && !avatarError ? (
                          <img
                            src={avatarUrl}
                            alt={provider || "provider"}
                            className="h-full w-full object-cover"
                            onError={() => setAvatarError(true)}
                          />
                        ) : (
                          <span className="text-sm font-semibold text-text-secondary">
                            {provider?.charAt(0).toUpperCase() || "?"}
                          </span>
                        )}
                      </div>
                      <div className="flex-1 min-w-0">
                        <p className="text-xs font-semibold uppercase tracking-wide text-accent-base">
                          {provider || "unknown"}
                        </p>
                        <h2 className="mt-1 text-lg font-semibold text-text-primary truncate">
                          {analysis.model_id.split("/")[1] || analysis.model_id}
                        </h2>
                      </div>
                    </div>

                    {/* 主体：双栏布局 */}
                    <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                      {/* 左栏：分析内容（占 2 列） */}
                      <div className="lg:col-span-2 space-y-6">
                        {/* 核心特征 - 标签云 */}
                        {analysis.key_features && analysis.key_features.length > 0 && (
                          <div>
                            <h3 className="text-sm font-semibold text-text-primary mb-3">核心特征</h3>
                            <div className="flex flex-wrap gap-2">
                              {analysis.key_features.map((feature, idx) => (
                                <span
                                  key={idx}
                                  className="inline-flex items-center rounded-full bg-accent-soft px-3 py-1.5 text-xs font-medium text-accent-base border border-accent-base/30"
                                >
                                  ✨ {feature}
                                </span>
                              ))}
                            </div>
                          </div>
                        )}

                        {/* 使用场景 - 列表 */}
                        {analysis.use_cases && analysis.use_cases.length > 0 && (
                          <div>
                            <h3 className="text-sm font-semibold text-text-primary mb-3">使用场景</h3>
                            <ul className="space-y-2">
                              {analysis.use_cases.map((useCase, idx) => (
                                <li key={idx} className="flex items-start gap-2">
                                  <span className="mt-1 text-accent-base">→</span>
                                  <span className="text-sm text-text-secondary">{useCase}</span>
                                </li>
                              ))}
                            </ul>
                          </div>
                        )}

                        {/* 性能指标 - 表格/网格 */}
                        {analysis.performance_metrics && Object.keys(analysis.performance_metrics).length > 0 && (
                          <div>
                            <h3 className="text-sm font-semibold text-text-primary mb-3">性能指标</h3>
                            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                              {Object.entries(analysis.performance_metrics).map(([key, value]) => (
                                <div key={key} className="rounded-lg border border-border-default/40 bg-surface-chip p-3">
                                  <p className="text-xs font-semibold uppercase tracking-wide text-text-muted">{key}</p>
                                  <p className="mt-1 text-sm font-medium text-text-primary">
                                    {typeof value === "object" ? JSON.stringify(value) : String(value)}
                                  </p>
                                </div>
                              ))}
                            </div>
                          </div>
                        )}

                        {/* 分割线 */}
                        <div className="border-t border-border-default/40" />

                        {/* 分析摘要 */}
                        {analysis.analysis_summary && (
                          <div>
                            <h3 className="text-sm font-semibold text-text-primary mb-3">AI 分析</h3>
                            <p className="leading-relaxed text-sm text-text-secondary whitespace-pre-wrap">
                              {analysis.analysis_summary}
                            </p>
                          </div>
                        )}
                      </div>

                      {/* 右栏：里程碑和评分信息 */}
                      <div className="lg:col-span-1 space-y-4">
                        {/* 里程碑信息 */}
                        <div className="rounded-lg border border-border-default/40 bg-surface-chip p-4">
                          <div className="flex items-center gap-2 mb-3">
                            {analysis.is_milestone ? (
                              <>
                                <span className="text-lg">🏆</span>
                                <h4 className="text-sm font-semibold text-text-primary">里程碑模型</h4>
                              </>
                            ) : (
                              <>
                                <span className="text-lg">📈</span>
                                <h4 className="text-sm font-semibold text-text-primary">潜力模型</h4>
                              </>
                            )}
                          </div>

                          {analysis.is_milestone ? (
                            <>
                              <div className="mb-3 rounded-lg bg-amber-900/20 px-3 py-2 border border-amber-600/30">
                                <p className="text-xs font-semibold text-amber-600 uppercase tracking-wide mb-1">
                                  里程碑特性
                                </p>
                                <p className="text-sm text-text-secondary leading-relaxed">
                                  {analysis.milestone_features || "行业内具有重要影响力的模型"}
                                </p>
                              </div>
                              <p className="text-xs text-text-muted">
                                ✓ 该模型在行业内具有突破性的技术贡献或创新能力
                              </p>
                            </>
                          ) : (
                            <>
                              <div className="mb-3 rounded-lg bg-blue-900/20 px-3 py-2 border border-blue-600/30">
                                <p className="text-xs font-semibold text-blue-600 uppercase tracking-wide mb-1">
                                  发展潜力
                                </p>
                                <p className="text-sm text-text-secondary leading-relaxed">
                                  {analysis.milestone_features || "持续完善中的优秀模型"}
                                </p>
                              </div>
                              <p className="text-xs text-text-muted">
                                → 关注其后续发展动向
                              </p>
                            </>
                          )}
                        </div>

                        {/* 行业评分 - 占位符 */}
                        <div className="rounded-lg border border-border-default/40 bg-surface-chip p-4">
                          <div className="flex items-center gap-2 mb-3">
                            <span className="text-lg">⭐</span>
                            <h4 className="text-sm font-semibold text-text-primary">行业评分</h4>
                          </div>
                          <div className="space-y-3">
                            <div className="rounded-lg bg-surface-default p-3 border border-border-default/40">
                              <p className="text-xs font-semibold text-text-muted uppercase tracking-wide mb-2">
                                数据源
                              </p>
                              <div className="flex flex-wrap gap-2">
                                <span className="inline-flex items-center rounded-full bg-slate-700/30 px-2.5 py-1 text-xs font-medium text-slate-300 border border-slate-600/30">
                                  HuggingFace
                                </span>
                              </div>
                            </div>
                            <p className="text-xs text-text-muted text-center py-2">
                              📊 评分数据加载中...
                            </p>
                          </div>
                        </div>

                        {/* 附加信息 */}
                        <div className="rounded-lg border border-border-default/40 bg-surface-chip p-4">
                          <p className="text-xs font-semibold text-text-muted uppercase tracking-wide mb-2">
                            分析信息
                          </p>
                          <div className="space-y-2 text-xs text-text-muted">
                            <p>
                              使用 LLM: <span className="text-text-secondary font-medium">{analysis.llm_model_used || "Unknown"}</span>
                            </p>
                            {analysis.analyzed_at && (
                              <p>
                                分析时间: <span className="text-text-secondary font-medium">{new Date(analysis.analyzed_at).toLocaleDateString("zh-CN")}</span>
                              </p>
                            )}
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>
                )}
              </Dialog.Panel>
            </Transition.Child>
          </div>
        </div>
      </Dialog>
    </Transition>
  );
};

export default ModelAnalysisModal;
