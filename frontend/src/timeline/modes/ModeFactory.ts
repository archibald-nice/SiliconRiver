import type { ITimelineMode, IModeFactory } from "./ITimelineMode";
import { ClassicMode } from "./ClassicMode";
import { RiverCruiseMode } from "./RiverCruiseMode";
import { HelixConstellationMode } from "./HelixConstellationMode";

/**
 * Timeline 模式工厂
 * 负责创建和管理不同的时间轴可视化模式
 */
export class TimelineModeFactory implements IModeFactory {
  /**
   * 创建指定名称的模式实例
   * @param modeName 模式名称
   * @returns 模式实例
   * @throws 如果模式名称未知则抛出错误
   */
  createMode(modeName: string): ITimelineMode {
    switch (modeName.toLowerCase()) {
      case "classic":
        return new ClassicMode();

      case "river":
        return new RiverCruiseMode();

      case "helix":
        return new HelixConstellationMode();

      // 预留未来模式
      // case "sandbox":
      //   return new SandboxExplorerMode();

      default:
        throw new Error(`Unknown timeline mode: ${modeName}`);
    }
  }

  /**
   * 获取所有可用的模式名称
   * @returns 模式名称数组
   */
  getAvailableModes(): string[] {
    return [
      "helix",
      "river",
      "classic",
      // 未来模式（当前被注释）
      // "canyon",
      // "sandbox",
    ];
  }

  /**
   * 检查模式是否可用
   * @param modeName 模式名称
   * @returns 是否可用
   */
  isModeAvailable(modeName: string): boolean {
    return this.getAvailableModes().includes(modeName.toLowerCase());
  }

  /**
   * 获取模式的显示名称（用于 UI）
   * @param modeName 模式名称
   * @returns 中文显示名称
   */
  getModeDisplayName(modeName: string): string {
    const displayNames: Record<string, string> = {
      classic: "经典螺旋",
      river: "河流巡航",
      canyon: "峡谷漫游",
      helix: "星轨螺旋",
      sandbox: "砂箱探索",
    };
    return displayNames[modeName.toLowerCase()] || modeName;
  }
}

// 导出单例工厂实例
export const timelineModeFactory = new TimelineModeFactory();
