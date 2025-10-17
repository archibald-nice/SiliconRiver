import * as THREE from "three";
import type { ITimelineMode, ModeSceneConfig, ModeDataset, FocusCallback, WheelEventCallback, ModeHUDConfig, CameraControlState } from "./ITimelineMode";
import type { TimelineEventNode } from "../core/event-node";

/**
 * Abstract base class for all timeline modes
 * Provides common functionality and enforces interface contract
 */
export abstract class BaseTimelineMode implements ITimelineMode {
  protected scene: InstanceType<typeof THREE.Scene> | null = null;
  protected camera: InstanceType<typeof THREE.PerspectiveCamera> | null = null;
  protected renderer: InstanceType<typeof THREE.WebGLRenderer> | null = null;
  protected controls: any = null;

  protected dataset: ModeDataset | null = null;
  protected nodes: TimelineEventNode[] = [];
  protected currentFocusIndex = 0;

  protected focusCallbacks: FocusCallback[] = [];
  protected wheelCallbacks: WheelEventCallback[] = [];

  /**
   * Get human-readable mode name
   */
  abstract getName(): string;

  /**
   * Initialize the mode with scene config and dataset
   */
  abstract init(config: ModeSceneConfig, dataset: ModeDataset): Promise<void>;

  /**
   * Dispose of resources
   */
  abstract dispose(): void;

  /**
   * Handle wheel scroll event
   */
  abstract handleWheelEvent(direction: number, currentIndex: number): number;

  /**
   * Handle node click
   */
  abstract handleNodeClick(mesh: InstanceType<typeof THREE.Mesh>): number | null;

  /**
   * Layout nodes according to mode-specific positioning
   */
  abstract layoutNodes(nodes: TimelineEventNode[]): void;

  /**
   * Get camera control state for this mode
   */
  abstract getCameraControlState(): CameraControlState;

  /**
   * Get HUD configuration for this mode
   */
  abstract getHUDConfig(): ModeHUDConfig;

  /**
   * Per-frame update
   */
  abstract update(deltaTime: number): void;

  /**
   * Concrete implementations for common functionality
   */

  setFocus(markerIndex: number, focusCallback?: FocusCallback): void {
    const clamped = Math.max(0, Math.min(markerIndex, this.nodes.length - 1));
    if (clamped !== this.currentFocusIndex) {
      this.currentFocusIndex = clamped;
      this.notifyFocusChanged(clamped);
      focusCallback?.(clamped);
    }
  }

  getCurrentFocusIndex(): number {
    return this.currentFocusIndex;
  }

  getScene(): InstanceType<typeof THREE.Scene> {
    if (!this.scene) {
      throw new Error(`${this.getName()} mode not initialized`);
    }
    return this.scene;
  }

  getCamera(): InstanceType<typeof THREE.PerspectiveCamera> {
    if (!this.camera) {
      throw new Error(`${this.getName()} mode not initialized`);
    }
    return this.camera;
  }

  getRenderer(): InstanceType<typeof THREE.WebGLRenderer> {
    if (!this.renderer) {
      throw new Error(`${this.getName()} mode not initialized`);
    }
    return this.renderer;
  }

  getControls(): any | null {
    return this.controls;
  }

  onWindowResize(width: number, height: number): void {
    if (!this.camera || !this.renderer) {
      return;
    }
    this.renderer.setSize(width, height);
    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();
  }

  onFocusChanged(callback: FocusCallback): void {
    this.focusCallbacks.push(callback);
  }

  onWheelEvent(callback: WheelEventCallback): void {
    this.wheelCallbacks.push(callback);
  }

  /**
   * Optional: Pre-warming resources (override in subclass if needed)
   */
  warmup?(): Promise<void>;

  /**
   * Optional: Mode-specific options UI (override in subclass if needed)
   */
  getOptionsUI?(): HTMLElement | null;

  /**
   * Protected helper methods
   */

  protected notifyFocusChanged(markerIndex: number): void {
    this.focusCallbacks.forEach(callback => callback(markerIndex));
  }

  protected notifyWheelEvent(direction: number): void {
    this.wheelCallbacks.forEach(callback => callback(direction));
  }

  /**
   * Common utility: Clamp index to valid range
   */
  protected clampIndex(index: number): number {
    return Math.max(0, Math.min(index, this.nodes.length - 1));
  }
}
