import * as THREE from "three";
import { BaseTimelineMode } from "./BaseTimelineMode";
import type { ModeSceneConfig, ModeDataset, ModeHUDConfig, CameraControlState } from "./ITimelineMode";
import type { TimelineEventNode } from "../core/event-node";
import { TimelineScene } from "../core/scene";
import { COLOR_ACTIVE, COLOR_BASE, COLOR_LINE, getDefaultFocusAnchor } from "../core/constants";

/**
 * 经典螺旋时间轴模式
 * Silicon River 的默认可视化模式
 */
export class ClassicMode extends BaseTimelineMode {
  private timelineScene: TimelineScene | null = null;
  private timelineGroup: InstanceType<typeof THREE.Group> | null = null;
  private tubeMesh: InstanceType<typeof THREE.Mesh> | null = null;
  private axisGroup: InstanceType<typeof THREE.Group> | null = null;

  // 动画状态
  private highlightIndex = 0;
  private currentTimelineOffset = new THREE.Vector3();
  private targetTimelineOffset = new THREE.Vector3();
  private cameraFocus = new THREE.Vector3();
  private targetCameraFocus = new THREE.Vector3();
  private activeColor = new THREE.Color(COLOR_ACTIVE);
  private baseColor = new THREE.Color(COLOR_BASE);

  // 几何资源
  private markerGeometry: InstanceType<typeof THREE.SphereGeometry> | null = null;
  private tubeGeometry: InstanceType<typeof THREE.TubeGeometry> | null = null;
  private tubeMaterial: InstanceType<typeof THREE.MeshStandardMaterial> | null = null;
  private arrowGeometry: InstanceType<typeof THREE.ConeGeometry> | null = null;
  private arrowMaterial: InstanceType<typeof THREE.MeshBasicMaterial> | null = null;
  private axisMaterial: InstanceType<typeof THREE.LineBasicMaterial> | null = null;

  private animationFrameId = 0;
  private focusAnchor = getDefaultFocusAnchor();

  getName(): string {
    return "ClassicMode";
  }

  async init(config: ModeSceneConfig, dataset: ModeDataset): Promise<void> {
    // 初始化场景
    this.timelineScene = new TimelineScene({
      container: config.container,
      size: config.size,
      background: config.background || 0xffffff,
      camera: config.camera,
    });

    this.scene = this.timelineScene.scene;
    this.camera = this.timelineScene.camera;
    this.renderer = this.timelineScene.renderer;
    this.controls = this.timelineScene.controls;
    this.dataset = dataset;

    // 创建时间轴组
    this.timelineGroup = new THREE.Group();
    this.scene.add(this.timelineGroup);

    // 创建螺旋曲线管道
    this.createCurveTube(dataset.curve);

    // 创建节点几何
    this.markerGeometry = new THREE.SphereGeometry(0.7, 18, 18);

    // 创建时间轴坐标系
    this.createAxisSystem(dataset);

    // 初始化动画状态
    this.cameraFocus.copy(this.focusAnchor);
    this.targetCameraFocus.copy(this.focusAnchor);
  }

  private createCurveTube(curve: InstanceType<typeof THREE.CatmullRomCurve3>): void {
    if (!this.timelineGroup) return;

    this.tubeGeometry = new THREE.TubeGeometry(curve, 420, 0.28, 16, false);
    this.tubeMaterial = new THREE.MeshStandardMaterial({
      color: COLOR_LINE,
      emissive: 0x0f172a
    });
    this.tubeMesh = new THREE.Mesh(this.tubeGeometry, this.tubeMaterial);
    this.timelineGroup.add(this.tubeMesh);
  }

  private createAxisSystem(dataset: ModeDataset): void {
    if (!this.timelineGroup || !dataset.curve) return;

    const curve = dataset.curve;
    const sorted = dataset.models;

    // 计算曲线采样点的统计信息
    const curveSamples = curve.getPoints(Math.max(Math.round(sorted.length * 3.2), 160));
    let sumX = 0;
    let sumZ = 0;
    let minY = Number.POSITIVE_INFINITY;
    let maxY = Number.NEGATIVE_INFINITY;

    curveSamples.forEach((sample: InstanceType<typeof THREE.Vector3>) => {
      sumX += sample.x;
      sumZ += sample.z;
      minY = Math.min(minY, sample.y);
      maxY = Math.max(maxY, sample.y);
    });

    const hasSamples = curveSamples.length > 0;
    const axisCenterX = hasSamples ? sumX / curveSamples.length : this.focusAnchor.x;
    const axisCenterZ = hasSamples ? sumZ / curveSamples.length : this.focusAnchor.z;

    if (!Number.isFinite(minY)) minY = this.focusAnchor.y - 3;
    if (!Number.isFinite(maxY)) maxY = this.focusAnchor.y + 3;
    if (maxY - minY < 1) maxY = minY + 6;

    // 创建坐标轴
    this.axisGroup = new THREE.Group();
    this.axisMaterial = new THREE.LineBasicMaterial({ color: 0x475569 });
    this.arrowMaterial = new THREE.MeshBasicMaterial({ color: 0x475569 });
    this.arrowGeometry = new THREE.ConeGeometry(0.38, 1.2, 12);
    this.arrowGeometry.translate(0, -0.6, 0);

    const axisStart = new THREE.Vector3(axisCenterX, minY - 2.4, axisCenterZ);
    const axisEnd = new THREE.Vector3(axisCenterX, maxY + 2.4, axisCenterZ);
    const axisGeometry = new THREE.BufferGeometry().setFromPoints([axisStart, axisEnd]);
    this.axisGroup.add(new THREE.Line(axisGeometry, this.axisMaterial));

    // 添加箭头
    const axisDirection = axisEnd.clone().sub(axisStart).normalize();
    const arrowHead = new THREE.Mesh(this.arrowGeometry, this.arrowMaterial);
    arrowHead.position.copy(axisEnd);
    arrowHead.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), axisDirection);
    this.axisGroup.add(arrowHead);

    // 添加刻度标签
    const axisVector = axisEnd.clone().sub(axisStart);
    const axisLength = axisVector.length();
    const tickCount = Math.min(8, Math.max(sorted.length, 2));

    for (let i = 0; i < tickCount; i++) {
      const fraction = i / Math.max(tickCount - 1, 1);
      const axisPoint = axisStart.clone().add(axisDirection.clone().multiplyScalar(axisLength * fraction));
      const curvePoint = curve.getPointAt(fraction);
      const radial = curvePoint.clone().sub(axisPoint);

      if (radial.lengthSq() < 1e-5) {
        radial.set(1.4, 0, 0);
      }

      const radialLength = THREE.MathUtils.clamp(radial.length() * 0.68, 1.2, 4.2);
      radial.setLength(radialLength);

      const tickOuter = axisPoint.clone().add(radial);
      const tickGeometry = new THREE.BufferGeometry().setFromPoints([axisPoint, tickOuter]);
      this.axisGroup.add(new THREE.Line(tickGeometry, this.axisMaterial));

      // 创建日期标签精灵
      const labelDate = new Date(dataset.minTime + dataset.span * fraction);
      const sprite = this.createDateSprite(labelDate);
      const labelPosition = tickOuter.clone()
        .add(radial.clone().setLength(0.6))
        .add(new THREE.Vector3(0, 0.9, 0));
      sprite.position.copy(labelPosition);
      this.axisGroup.add(sprite);
    }

    this.timelineGroup.add(this.axisGroup);
  }

  private createDateSprite(date: Date): InstanceType<typeof THREE.Sprite> {
    const toTwoDigits = (value: number) => String(value).padStart(2, "0");
    const text = `${date.getUTCFullYear()}-${toTwoDigits(date.getUTCMonth() + 1)}-${toTwoDigits(date.getUTCDate())}`;

    const canvas = document.createElement("canvas");
    const width = 640;
    const height = 256;
    canvas.width = width;
    canvas.height = height;
    const context = canvas.getContext("2d");
    if (!context) throw new Error("Canvas not supported");

    context.clearRect(0, 0, width, height);
    context.fillStyle = "rgba(255,255,255,0.9)";
    const barHeight = 112;
    const radius = 48;

    // 绘制圆角矩形
    context.beginPath();
    context.moveTo(radius, height / 2 - barHeight / 2);
    context.lineTo(width - radius, height / 2 - barHeight / 2);
    context.quadraticCurveTo(width, height / 2 - barHeight / 2, width, height / 2);
    context.quadraticCurveTo(width, height / 2 + barHeight / 2, width - radius, height / 2 + barHeight / 2);
    context.lineTo(radius, height / 2 + barHeight / 2);
    context.quadraticCurveTo(0, height / 2 + barHeight / 2, 0, height / 2);
    context.quadraticCurveTo(0, height / 2 - barHeight / 2, radius, height / 2 - barHeight / 2);
    context.closePath();
    context.fill();

    context.strokeStyle = "rgba(15,23,42,0.14)";
    context.lineWidth = 6;
    context.stroke();

    context.fillStyle = "#0f172a";
    context.font = "88px sans-serif";
    context.textAlign = "center";
    context.textBaseline = "middle";
    context.fillText(text, width / 2, height / 2);

    const texture = new THREE.CanvasTexture(canvas);
    const material = new THREE.SpriteMaterial({ map: texture, transparent: true });
    const sprite = new THREE.Sprite(material);
    const scale = 4.2;
    sprite.scale.set((scale * canvas.width) / canvas.height, scale, 1);
    return sprite;
  }

  dispose(): void {
    // 停止动画循环
    if (this.animationFrameId) {
      cancelAnimationFrame(this.animationFrameId);
      this.animationFrameId = 0;
    }

    // 清理几何资源
    this.markerGeometry?.dispose();
    this.tubeGeometry?.dispose();
    this.tubeMaterial?.dispose();
    this.arrowGeometry?.dispose();
    this.arrowMaterial?.dispose();
    this.axisMaterial?.dispose();

    // 清理组和节点
    if (this.axisGroup) {
      this.axisGroup.clear();
      this.axisGroup = null;
    }

    if (this.timelineGroup && this.scene) {
      this.nodes.forEach((node) => node.dispose(this.timelineGroup!));
      this.scene.remove(this.timelineGroup);
      this.timelineGroup.clear();
      this.timelineGroup = null;
    }

    // 清理场景
    if (this.timelineScene) {
      this.timelineScene.dispose();
      this.timelineScene = null;
    }

    this.scene = null;
    this.camera = null;
    this.renderer = null;
    this.controls = null;
    this.dataset = null;
    this.nodes = [];
  }

  handleWheelEvent(direction: number, currentIndex: number): number {
    const step = 1;
    const nextIndex = currentIndex + direction * step;
    return THREE.MathUtils.clamp(nextIndex, 0, this.nodes.length - 1);
  }

  handleNodeClick(mesh: InstanceType<typeof THREE.Mesh>): number | null {
    const index = typeof mesh.userData.markerIndex === "number"
      ? mesh.userData.markerIndex
      : this.nodes.findIndex((node) => node.mesh === mesh);
    return index >= 0 ? index : null;
  }

  layoutNodes(nodes: TimelineEventNode[]): void {
    if (!this.dataset || !this.timelineGroup || !this.markerGeometry) {
      return;
    }

    this.nodes = [];
    const curve = this.dataset.curve;
    const sorted = this.dataset.models;
    const minTime = this.dataset.minTime;
    const span = this.dataset.span;

    sorted.forEach((model) => {
      const created = new Date(model.created_at).getTime();
      const t = (created - minTime) / span;
      const basePosition = curve.getPointAt(t);
      const node = nodes.find((n) => n.model.model_id === model.model_id);

      if (node) {
        node.basePosition.copy(basePosition);
        node.attachTo(this.timelineGroup!);
        this.nodes.push(node);
        node.setMarkerIndex(this.nodes.length - 1);
      }
    });

    // 初始聚焦最新节点
    if (this.nodes.length > 0) {
      this.highlightIndex = this.nodes.length - 1;
      this.applyFocus();
    }
  }

  private applyFocus(): void {
    if (!this.nodes.length) {
      return;
    }

    this.highlightIndex = THREE.MathUtils.clamp(this.highlightIndex, 0, this.nodes.length - 1);
    const targetMarker = this.nodes[this.highlightIndex];
    const offset = this.focusAnchor.clone().sub(targetMarker.basePosition);
    this.targetTimelineOffset.copy(offset);
    this.targetCameraFocus.copy(this.focusAnchor);

    // 更新所有节点的状态
    this.nodes.forEach((entry, index) => {
      if (index === this.highlightIndex) {
        entry.setTargetState({ scale: 1.6, opacity: 1, color: this.activeColor });
        return;
      }

      const distance = index - this.highlightIndex;
      if (distance < 0) {
        const backward = Math.abs(distance);
        entry.setTargetState({
          scale: backward === 1 ? 0.95 : backward === 2 ? 0.8 : 0.7,
          opacity: backward === 1 ? 0.55 : backward === 2 ? 0.4 : 0.3,
          color: this.baseColor,
        });
      } else {
        entry.setTargetState({
          scale: distance === 1 ? 1.15 : distance === 2 ? 1.05 : 1.0,
          opacity: distance === 1 ? 0.8 : distance === 2 ? 0.6 : 0.45,
          color: this.baseColor,
        });
      }
    });

    // 触发焦点回调
    this.focusCallbacks.forEach((cb) => cb(this.highlightIndex));
  }

  setFocus(markerIndex: number, focusCallback?: (index: number) => void): void {
    const clamped = THREE.MathUtils.clamp(markerIndex, 0, this.nodes.length - 1);
    this.highlightIndex = clamped;

    if (focusCallback) {
      focusCallback(this.currentFocusIndex);
    }

    this.applyFocus();
    this.currentFocusIndex = clamped;
  }

  getCurrentFocusIndex(): number {
    return this.highlightIndex;
  }

  getCameraControlState(): CameraControlState {
    return {
      position: this.camera?.position.clone() || new THREE.Vector3(),
      target: this.controls?.target?.clone() || new THREE.Vector3(),
      fov: this.camera?.fov,
    };
  }

  getHUDConfig(): ModeHUDConfig {
    return {
      showTimeline: true,
      showAxis: true,
      showHints: true,
    };
  }

  getScene(): InstanceType<typeof THREE.Scene> {
    if (!this.scene) {
      throw new Error("ClassicMode: Scene not initialized");
    }
    return this.scene;
  }

  getCamera(): InstanceType<typeof THREE.PerspectiveCamera> {
    if (!this.camera) {
      throw new Error("ClassicMode: Camera not initialized");
    }
    return this.camera;
  }

  getRenderer(): InstanceType<typeof THREE.WebGLRenderer> {
    if (!this.renderer) {
      throw new Error("ClassicMode: Renderer not initialized");
    }
    return this.renderer;
  }

  getControls(): any | null {
    return this.controls;
  }

  update(deltaTime: number): void {
    if (!this.timelineGroup || !this.camera || !this.controls) {
      return;
    }

    // 更新时间轴偏移（平滑过渡）
    this.currentTimelineOffset.lerp(this.targetTimelineOffset, 0.12);
    this.timelineGroup.position.copy(this.currentTimelineOffset);

    // 更新相机焦点
    this.cameraFocus.lerp(this.targetCameraFocus, 0.08);
    this.controls.target.copy(this.cameraFocus);
    this.controls.update();

    // 更新所有节点的过渡动画
    this.nodes.forEach((entry) => {
      entry.updateTransition();
    });
  }

  onWindowResize(width: number, height: number): void {
    if (this.timelineScene) {
      this.timelineScene.resize(width, height);
    }
  }

  onFocusChanged(callback: (markerIndex: number) => void): void {
    this.focusCallbacks.push(callback);
  }

  onWheelEvent(callback: (direction: number) => void): void {
    this.wheelCallbacks.push(callback);
  }

  /**
   * 获取当前聚焦的节点
   */
  getActiveNode(): TimelineEventNode | null {
    return this.nodes[this.highlightIndex] || null;
  }

  /**
   * 获取上一个和下一个节点
   */
  getAdjacentNodes(): { prev: TimelineEventNode | null; next: TimelineEventNode | null } {
    return {
      prev: this.nodes[this.highlightIndex + 1] || null,
      next: this.nodes[this.highlightIndex - 1] || null,
    };
  }
}
