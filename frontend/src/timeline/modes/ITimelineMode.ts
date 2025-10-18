import * as THREE from "three";
import type { TimelineModel } from "../../api/client";
import type { TimelineEventNode } from "../core/event-node";

/**
 * 焦点管理的回调接口
 */
export type FocusCallback = (markerIndex: number) => void;

/**
 * 滚轮事件处理的回调接口
 */
export type WheelEventCallback = (direction: number) => void;

/**
 * 场景配置选项
 */
export type ModeSceneConfig = {
  container: HTMLElement;
  size: { width: number; height: number };
  background?: ConstructorParameters<typeof THREE.Color>[0];
  theme?: 'light' | 'dark';
  camera?: {
    fov?: number;
    near?: number;
    far?: number;
    position?: InstanceType<typeof THREE.Vector3>;
    target?: InstanceType<typeof THREE.Vector3>;
  };
};

/**
 * HUD 配置（抬头显示）
 */
export type ModeHUDConfig = {
  showTimeline?: boolean;
  showAxis?: boolean;
  showHints?: boolean;
  customElements?: Record<string, HTMLElement>;
};

/**
 * 数据集信息
 */
export type ModeDataset = {
  models: TimelineModel[];
  curve: InstanceType<typeof THREE.CatmullRomCurve3>;
  minTime: number;
  maxTime: number;
  span: number;
};

/**
 * 节点位置和状态信息
 */
export type NodeLayoutInfo = {
  mesh: InstanceType<typeof THREE.Mesh>;
  position: InstanceType<typeof THREE.Vector3>;
  scale: number;
  opacity: number;
  markerIndex: number;
};

/**
 * 相机控制状态
 */
export type CameraControlState = {
  position: InstanceType<typeof THREE.Vector3>;
  target: InstanceType<typeof THREE.Vector3>;
  fov?: number;
};

/**
 * TimelineMode 接口
 * 定义了模式需要实现的所有核心方法
 */
export interface ITimelineMode {
  /**
   * 模式名称（用于标识和日志）
   */
  getName(): string;

  /**
   * 初始化模式
   * @param config 场景配置
   * @param dataset 时间线数据集
   * @returns Promise<void>
   */
  init(config: ModeSceneConfig, dataset: ModeDataset): Promise<void>;

  /**
   * 清理并释放模式资源
   */
  dispose(): void;

  /**
   * 处理滚轮事件
   * @param direction 滚轮方向（1 向下，-1 向上）
   * @param currentIndex 当前焦点索引
   * @returns 下一个应该聚焦的索引
   */
  handleWheelEvent(direction: number, currentIndex: number): number;

  /**
   * 处理点击焦点
   * @param mesh 被点击的 Mesh
   * @returns 应该聚焦的索引
   */
  handleNodeClick(mesh: InstanceType<typeof THREE.Mesh>): number | null;

  /**
   * 设置焦点到指定索引
   * @param markerIndex 标记索引
   * @param focusCallback 焦点变更时的回调
   */
  setFocus(markerIndex: number, focusCallback?: FocusCallback): void;

  /**
   * 获取当前焦点索引
   */
  getCurrentFocusIndex(): number;

  /**
   * 生成和布局节点
   * @param nodes 时间线事件节点数组
   */
  layoutNodes(nodes: TimelineEventNode[]): void;

  /**
   * 获取相机控制状态
   */
  getCameraControlState(): CameraControlState;

  /**
   * 获取 HUD 配置
   */
  getHUDConfig(): ModeHUDConfig;

  /**
   * 获取主 Three.js 场景
   */
  getScene(): InstanceType<typeof THREE.Scene>;

  /**
   * 获取相机对象
   */
  getCamera(): InstanceType<typeof THREE.PerspectiveCamera>;

  /**
   * 获取渲染器对象
   */
  getRenderer(): InstanceType<typeof THREE.WebGLRenderer>;

  /**
   * 获取 OrbitControls 对象（可能为 null）
   */
  getControls(): any | null;

  /**
   * 更新模式渲染
   * @param deltaTime 帧间隔时间（毫秒）
   */
  update(deltaTime: number): void;

  /**
   * 处理窗口大小变更
   * @param width 新宽度
   * @param height 新高度
   */
  onWindowResize(width: number, height: number): void;

  /**
   * 注册焦点变更回调
   */
  onFocusChanged(callback: FocusCallback): void;

  /**
   * 注册滚轮事件回调
   */
  onWheelEvent(callback: WheelEventCallback): void;

  /**
   * 获取年份锚点数组（用于交互）
   */
  getYearAnchors?(): Array<{ year: number; mesh: InstanceType<typeof THREE.Mesh> }>;

  /**
   * 获取季度锚点数组（用于交互）
   */
  getQuarterAnchors?(): Array<{ year: number; quarter: number; mesh: InstanceType<typeof THREE.Mesh> }>;

  /**
   * 获取月份锚点数组（用于交互）
   */
  getMonthAnchors?(): Array<{ year: number; month: number; mesh: InstanceType<typeof THREE.Mesh> }>;

  /**
   * 预热（预加载资源等）
   */
  warmup?(): Promise<void>;
}

/**
 * 模式工厂接口
 */
export interface IModeFactory {
  /**
   * 创建指定名称的模式实例
   */
  createMode(modeName: string): ITimelineMode;

  /**
   * 获取所有可用模式名称
   */
  getAvailableModes(): string[];
}
