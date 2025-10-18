import { useState } from "react";
import { timelineModeFactory } from "../timeline/modes/ModeFactory";

export type TimelineModeName = "classic" | "river" | "canyon" | "helix" | "sandbox";

export interface ModeSwitcherProps {
  currentMode: TimelineModeName;
  onModeChange: (mode: TimelineModeName) => void;
  disabled?: boolean;
}

/**
 * 时间轴模式切换器组件
 * 提供用户友好的 UI 来切换不同的时间轴可视化模式
 */
export const ModeSwitcher = ({ currentMode, onModeChange, disabled = false }: ModeSwitcherProps) => {
  const availableModes = timelineModeFactory.getAvailableModes() as TimelineModeName[];
  const [isTransitioning, setIsTransitioning] = useState(false);

  const handleModeClick = async (mode: TimelineModeName) => {
    if (mode === currentMode || disabled || isTransitioning) {
      return;
    }

    setIsTransitioning(true);
    try {
      // 触发模式切换
      onModeChange(mode);
    } finally {
      // 给予短暂的过渡时间
      setTimeout(() => setIsTransitioning(false), 300);
    }
  };

  return (
    <div className="inline-flex items-center gap-2 rounded-lg border border-border-default bg-surface-overlay p-1 shadow-sm">
      {availableModes.map((mode) => {
        const isActive = mode === currentMode;
        const displayName = timelineModeFactory.getModeDisplayName(mode);

        return (
          <button
            key={mode}
            type="button"
            onClick={() => handleModeClick(mode)}
            disabled={disabled || isTransitioning}
            className={`
              relative rounded-md px-4 py-2 text-sm font-medium transition-all duration-200
              ${
                isActive
                  ? "bg-accent-base text-white shadow-md"
                  : "text-text-secondary hover:bg-surface-raised hover:text-text-primary"
              }
              ${disabled || isTransitioning ? "cursor-not-allowed opacity-50" : "cursor-pointer"}
              disabled:pointer-events-none
            `}
            aria-label={`切换到${displayName}模式`}
            aria-pressed={isActive}
          >
            <span className="relative z-10">{displayName}</span>
            {isActive && (
              <span className="absolute inset-0 rounded-md bg-accent-base opacity-10 blur-sm" aria-hidden="true" />
            )}
          </button>
        );
      })}

      {isTransitioning && (
        <div className="ml-2 flex items-center gap-2 text-xs text-text-muted">
          <svg
            className="h-4 w-4 animate-spin"
            xmlns="http://www.w3.org/2000/svg"
            fill="none"
            viewBox="0 0 24 24"
          >
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path
              className="opacity-75"
              fill="currentColor"
              d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
            />
          </svg>
          <span>切换中...</span>
        </div>
      )}
    </div>
  );
};

/**
 * 模式信息卡片组件
 * 显示当前模式的详细信息和使用提示
 */
export interface ModeInfoCardProps {
  mode: TimelineModeName;
}

export const ModeInfoCard = ({ mode }: ModeInfoCardProps) => {
  const modeInfo: Record<
    TimelineModeName,
    {
      description: string;
      features: string[];
      controls: string[];
    }
  > = {
    classic: {
      description: "经典的螺旋时间轴布局，沿 3D 曲线展示模型发布历史",
      features: ["平滑的相机过渡", "交互式焦点气泡", "时间轴刻度标签", "悬停提示"],
      controls: ["滚轮: 前进/后退", "点击节点: 聚焦", "拖拽: 旋转视角"],
    },
    river: {
      description: "河流巡航模式，像乘船游览一样浏览时间线",
      features: ["流动的水面效果", "固定停靠点", "远景雾化", "位置指示器"],
      controls: ["滚轮: 停靠点间移动", "点击节点: 快速跳转"],
    },
    canyon: {
      description: "峡谷漫游模式，在两侧峡谷墙之间的栈道上行走",
      features: ["半透明峡谷墙体", "左右交替节点", "相机侧倾效果", "厂商标签墙"],
      controls: ["滚轮: 沿栈道前进", "点击节点: 聚焦", "左右键: 查看两侧"],
    },
    helix: {
      description: "星轨螺旋模式，模型沿螺旋轨道排列如繁星",
      features: ["6圈螺旋结构", "星空粒子背景", "环绕视角", "发光焦点"],
      controls: ["滚轮: 上升/下降节点", "点击节点: 聚焦"],
    },
    sandbox: {
      description: "砂箱探索模式，自由漫游整个时间线空间",
      features: ["第一人称控制", "WASD 移动", "热力图密度", "快速锚点"],
      controls: ["WASD: 移动", "鼠标: 视角", "滚轮: 前进/后退", "点击锚点: 传送"],
    },
  };

  const info = modeInfo[mode] || modeInfo.classic;

  return (
    <div className="rounded-lg border border-border-default bg-surface-overlay p-4 shadow-sm">
      <h3 className="mb-2 text-sm font-semibold text-text-primary">
        {timelineModeFactory.getModeDisplayName(mode)}
      </h3>
      <p className="mb-3 text-xs text-text-muted">{info.description}</p>

      <div className="mb-3">
        <h4 className="mb-1 text-xs font-medium text-text-secondary">特性</h4>
        <ul className="space-y-1">
          {info.features.map((feature, index) => (
            <li key={index} className="flex items-start gap-2 text-xs text-text-muted">
              <span className="mt-0.5 text-accent-base">•</span>
              <span>{feature}</span>
            </li>
          ))}
        </ul>
      </div>

      <div>
        <h4 className="mb-1 text-xs font-medium text-text-secondary">操作</h4>
        <ul className="space-y-1">
          {info.controls.map((control, index) => (
            <li key={index} className="flex items-start gap-2 text-xs text-text-muted">
              <span className="mt-0.5 text-accent-base">→</span>
              <span>{control}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
};
