interface MilestonePanelProps {
  isMilestone: boolean;
  features?: string | null;
  className?: string;
}

const MilestonePanel = ({
  isMilestone,
  features,
  className = "",
}: MilestonePanelProps) => {
  return (
    <div className={`rounded-lg border border-border-default/40 bg-surface-chip p-4 ${className}`}>
      <div className="flex items-center gap-2 mb-3">
        {isMilestone ? (
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

      {isMilestone ? (
        <>
          <div className="mb-3 rounded-lg bg-amber-900/20 px-3 py-2 border border-amber-600/30">
            <p className="text-xs font-semibold text-amber-600 uppercase tracking-wide mb-1">
              里程碑特性
            </p>
            <p className="text-sm text-text-secondary leading-relaxed">
              {features || "行业内具有重要影响力的模型"}
            </p>
          </div>
          <div className="space-y-2 text-xs text-text-muted">
            <p>✓ 该模型在行业内具有突破性的技术贡献</p>
            <p>✓ 代表了当前技术发展的前沿方向</p>
            <p>✓ 对后续模型发展有重要参考意义</p>
          </div>
        </>
      ) : (
        <>
          <div className="mb-3 rounded-lg bg-blue-900/20 px-3 py-2 border border-blue-600/30">
            <p className="text-xs font-semibold text-blue-600 uppercase tracking-wide mb-1">
              发展潜力
            </p>
            <p className="text-sm text-text-secondary leading-relaxed">
              {features || "持续完善中的优秀模型"}
            </p>
          </div>
          <div className="space-y-2 text-xs text-text-muted">
            <p>→ 具有良好的技术基础和发展空间</p>
            <p>→ 值得关注其后续优化方向</p>
            <p>→ 可能在特定应用场景中表现突出</p>
          </div>
        </>
      )}
    </div>
  );
};

export default MilestonePanel;
