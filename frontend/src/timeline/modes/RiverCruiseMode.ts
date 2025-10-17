import * as THREE from "three";
import { BaseTimelineMode } from "./BaseTimelineMode";
import type { ModeSceneConfig, ModeDataset, ModeHUDConfig, CameraControlState } from "./ITimelineMode";
import type { TimelineEventNode } from "../core/event-node";
import { TimelineScene } from "../core/scene";
import { COLOR_ACTIVE, COLOR_BASE, getDefaultFocusAnchor } from "../core/constants";

/**
 * 河流巡航模式
 * 像乘船游览一样浏览时间线，沿着流动的河道在停靠点间移动
 */
export class RiverCruiseMode extends BaseTimelineMode {
  private timelineScene: TimelineScene | null = null;
  private timelineGroup: InstanceType<typeof THREE.Group> | null = null;
  private riverMesh: InstanceType<typeof THREE.Mesh> | null = null;
  private dockPoints: InstanceType<typeof THREE.Vector3>[] = [];
  private currentDockIndex = 0;

  // 河道参数
  private readonly RIVER_WIDTH = 4.5;
  private readonly RIVER_SEGMENTS = 200;
  private readonly DOCK_INTERVAL = 10; // 每 N 个模型设置一个停靠点

  // 动画状态
  private cameraPosition = new THREE.Vector3();
  private targetCameraPosition = new THREE.Vector3();
  private cameraLookAt = new THREE.Vector3();
  private targetLookAt = new THREE.Vector3();
  private riverUvOffset = 0;

  // 颜色
  private activeColor = new THREE.Color(COLOR_ACTIVE);
  private baseColor = new THREE.Color(COLOR_BASE);

  // 几何资源
  private markerGeometry: InstanceType<typeof THREE.SphereGeometry> | null = null;
  private riverGeometry: InstanceType<typeof THREE.BufferGeometry> | null = null;
  private riverMaterial: InstanceType<typeof THREE.MeshStandardMaterial> | null = null;
  private waterNormalMap: InstanceType<typeof THREE.DataTexture> | null = null;
  private originalVertices: Float32Array | null = null; // 存储原始顶点位置

  private focusAnchor = getDefaultFocusAnchor();

  getName(): string {
    return "RiverCruiseMode";
  }

  async init(config: ModeSceneConfig, dataset: ModeDataset): Promise<void> {
    // 初始化场景
    this.timelineScene = new TimelineScene({
      container: config.container,
      size: config.size,
      background: 0xe0f2fe, // 浅蓝色天空背景
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

    // 添加雾化效果
    this.scene.fog = new THREE.Fog(0xe0f2fe, 15, 60);

    // 创建河道
    this.createRiverMesh(dataset.curve);

    // 创建节点几何
    this.markerGeometry = new THREE.SphereGeometry(0.7, 18, 18);

    // 添加环境光和平行光
    const ambientLight = new THREE.AmbientLight(0xffffff, 0.6);
    this.scene.add(ambientLight);

    const directionalLight = new THREE.DirectionalLight(0xffffff, 0.8);
    directionalLight.position.set(10, 20, 10);
    this.scene.add(directionalLight);

    // 初始化相机位置
    this.cameraPosition.copy(this.focusAnchor.clone().add(new THREE.Vector3(0, 8, 12)));
    this.targetCameraPosition.copy(this.cameraPosition);
    this.cameraLookAt.copy(this.focusAnchor);
    this.targetLookAt.copy(this.focusAnchor);

    if (this.camera) {
      this.camera.position.copy(this.cameraPosition);
      this.camera.lookAt(this.cameraLookAt);
    }
  }

  private createRiverMesh(curve: InstanceType<typeof THREE.CatmullRomCurve3>): void {
    if (!this.timelineGroup) return;

    // 沿曲线生成河道几何
    const points = curve.getPoints(this.RIVER_SEGMENTS);
    const vertices: number[] = [];
    const uvs: number[] = [];
    const indices: number[] = [];

    // 为每个点创建河道横截面
    for (let i = 0; i < points.length; i++) {
      const point = points[i];
      const nextPoint = points[Math.min(i + 1, points.length - 1)];

      // 计算切线方向
      const tangent = new THREE.Vector3().subVectors(nextPoint, point).normalize();

      // 计算垂直于切线的方向（河道宽度方向）
      const perpendicular = new THREE.Vector3(-tangent.z, 0, tangent.x).normalize();

      // 创建河道两侧的顶点
      const leftPoint = point.clone().add(perpendicular.clone().multiplyScalar(this.RIVER_WIDTH / 2));
      const rightPoint = point.clone().add(perpendicular.clone().multiplyScalar(-this.RIVER_WIDTH / 2));

      // 添加左侧顶点
      vertices.push(leftPoint.x, leftPoint.y - 0.5, leftPoint.z);
      uvs.push(0, i / points.length * 5); // UV 拉伸以显示更多波纹

      // 添加右侧顶点
      vertices.push(rightPoint.x, rightPoint.y - 0.5, rightPoint.z);
      uvs.push(1, i / points.length * 5); // UV 拉伸以显示更多波纹

      // 创建三角形索引
      if (i < points.length - 1) {
        const baseIndex = i * 2;
        // 第一个三角形
        indices.push(baseIndex, baseIndex + 1, baseIndex + 2);
        // 第二个三角形
        indices.push(baseIndex + 1, baseIndex + 3, baseIndex + 2);
      }
    }

    // 创建几何体
    this.riverGeometry = new THREE.BufferGeometry();
    const positionAttribute = new THREE.Float32BufferAttribute(vertices, 3);
    this.riverGeometry.setAttribute('position', positionAttribute);
    this.riverGeometry.setAttribute('uv', new THREE.Float32BufferAttribute(uvs, 2));
    this.riverGeometry.setIndex(indices);
    this.riverGeometry.computeVertexNormals();

    // 保存原始顶点位置以用于动画
    this.originalVertices = new Float32Array(vertices);

    // 创建程序化水波法线贴图
    this.waterNormalMap = this.createWaterNormalMap();

    // 创建增强的水面材质 - 使用更强烈的效果
    this.riverMaterial = new THREE.MeshStandardMaterial({
      color: 0x1e88e5, // 更深的蓝色
      metalness: 0.8,  // 极高的金属度产生强反射
      roughness: 0.1,  // 极低的粗糙度使水面非常光滑
      emissive: 0x0d47a1, // 深蓝色发光
      emissiveIntensity: 0.4, // 更强的发光强度
      transparent: true,
      opacity: 0.85,
      normalMap: this.waterNormalMap,
      normalScale: new THREE.Vector2(2.5, 2.5), // 显著增强法线效果
      side: THREE.DoubleSide, // 双面渲染
    });

    this.riverMesh = new THREE.Mesh(this.riverGeometry, this.riverMaterial);
    this.riverMesh.receiveShadow = true; // 接收阴影
    this.timelineGroup.add(this.riverMesh);
  }

  /**
   * 创建程序化水波法线贴图
   */
  private createWaterNormalMap(): InstanceType<typeof THREE.DataTexture> {
    const size = 256; // 提高分辨率
    const data = new Uint8Array(size * size * 4);

    for (let i = 0; i < size; i++) {
      for (let j = 0; j < size; j++) {
        const x = (i / size) * Math.PI * 8;
        const y = (j / size) * Math.PI * 8;

        // 创建更强烈的波纹图案（多个正弦波叠加）
        const wave1 = Math.sin(x * 3 + y * 0.5) * 0.6;
        const wave2 = Math.sin(x * 0.5 + y * 3) * 0.5;
        const wave3 = Math.sin((x + y) * 2) * 0.4;
        const wave4 = Math.sin((x - y) * 1.5) * 0.3;
        const height = wave1 + wave2 + wave3 + wave4;

        // 计算法线（使用数值导数）
        const normalX = Math.cos(x * 3) * 0.8 + Math.cos((x - y) * 1.5) * 0.3;
        const normalY = Math.cos(y * 3) * 0.8 + Math.cos((x + y) * 2) * 0.4;

        const index = (i * size + j) * 4;
        // RGB 存储法线向量，范围从 [-1,1] 映射到 [0,255]
        data[index] = ((normalX + 1) * 0.5 * 255) | 0;     // R (X)
        data[index + 1] = ((normalY + 1) * 0.5 * 255) | 0; // G (Y)
        data[index + 2] = 180;                              // B (Z - 向上，降低以增强法线效果)
        data[index + 3] = 255;                              // A
      }
    }

    const texture = new THREE.DataTexture(data, size, size, THREE.RGBAFormat);
    texture.wrapS = THREE.RepeatWrapping;
    texture.wrapT = THREE.RepeatWrapping;
    texture.repeat.set(3, 3); // 重复纹理以增加细节
    texture.needsUpdate = true;

    return texture;
  }

  dispose(): void {
    try {
      // 清理几何资源
      this.markerGeometry?.dispose();
      this.riverGeometry?.dispose();
      this.riverMaterial?.dispose();
      this.waterNormalMap?.dispose();

      // 清理组和节点
      if (this.timelineGroup && this.scene) {
        this.nodes.forEach((node) => node.dispose(this.timelineGroup!));
        this.scene.remove(this.timelineGroup);
        this.timelineGroup.clear();
        this.timelineGroup = null;
      }

      // 移除雾化
      if (this.scene) {
        this.scene.fog = null;
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
      this.dockPoints = [];
      this.originalVertices = null;
    } catch (error) {
      console.warn("Error during RiverCruiseMode disposal:", error);
    }
  }

  handleWheelEvent(direction: number, currentIndex: number): number {
    // 在河流模式中，滚轮逐个节点移动
    const nextIndex = currentIndex + direction;
    const clampedIndex = THREE.MathUtils.clamp(nextIndex, 0, this.nodes.length - 1);

    // 更新停靠点索引（用于相机定位）
    this.currentDockIndex = Math.floor(clampedIndex / this.DOCK_INTERVAL);

    return clampedIndex;
  }

  handleNodeClick(mesh: InstanceType<typeof THREE.Mesh>): number | null {
    const index = typeof mesh.userData.markerIndex === "number"
      ? mesh.userData.markerIndex
      : this.nodes.findIndex((node) => node.mesh === mesh);

    if (index >= 0) {
      // 找到最近的停靠点
      this.currentDockIndex = Math.floor(index / this.DOCK_INTERVAL);
      return index;
    }

    return null;
  }

  layoutNodes(nodes: TimelineEventNode[]): void {
    if (!this.dataset || !this.timelineGroup || !this.markerGeometry) {
      return;
    }

    this.nodes = [];
    this.dockPoints = [];

    const curve = this.dataset.curve;
    const sorted = this.dataset.models;
    const minTime = this.dataset.minTime;
    const span = this.dataset.span;

    sorted.forEach((model, index) => {
      const created = new Date(model.created_at).getTime();
      const t = (created - minTime) / span;
      const curvePoint = curve.getPointAt(t);

      // 节点位于河道右侧
      const nextPoint = curve.getPointAt(Math.min(t + 0.01, 1));
      const tangent = new THREE.Vector3().subVectors(nextPoint, curvePoint).normalize();
      const perpendicular = new THREE.Vector3(-tangent.z, 0, tangent.x).normalize();
      const offset = perpendicular.clone().multiplyScalar(-2.5); // 河道右侧

      const nodePosition = curvePoint.clone().add(offset).add(new THREE.Vector3(0, 0.5, 0));
      const node = nodes.find((n) => n.model.model_id === model.model_id);

      if (node) {
        node.basePosition.copy(nodePosition);
        node.attachTo(this.timelineGroup!);
        this.nodes.push(node);
        node.setMarkerIndex(this.nodes.length - 1);

        // 每 N 个节点创建一个停靠点
        if (index % this.DOCK_INTERVAL === 0 || index === sorted.length - 1) {
          this.dockPoints.push(curvePoint.clone());
        }
      }
    });

    // 初始聚焦最新节点
    if (this.nodes.length > 0) {
      this.currentFocusIndex = this.nodes.length - 1;
      this.currentDockIndex = this.dockPoints.length - 1;
      this.applyFocus();
    }
  }

  private applyFocus(): void {
    if (!this.nodes.length) {
      return;
    }

    this.currentFocusIndex = THREE.MathUtils.clamp(this.currentFocusIndex, 0, this.nodes.length - 1);

    // 获取当前聚焦节点的位置
    const focusedNode = this.nodes[this.currentFocusIndex];
    if (!focusedNode) return;

    const focusPosition = focusedNode.basePosition.clone();

    // 相机定位到当前聚焦节点的上方和后方
    this.targetCameraPosition.copy(focusPosition.clone().add(new THREE.Vector3(0, 8, 12)));
    this.targetLookAt.copy(focusPosition.clone().add(new THREE.Vector3(0, 0, -5)));

    // 更新节点状态（基于距离当前焦点的远近）
    this.nodes.forEach((entry, index) => {
      const distance = Math.abs(index - this.currentFocusIndex);

      if (distance === 0) {
        entry.setTargetState({ scale: 1.6, opacity: 1, color: this.activeColor });
      } else if (distance <= 5) {
        const proximity = 1 - (distance / 5);
        entry.setTargetState({
          scale: 0.8 + proximity * 0.5,
          opacity: 0.4 + proximity * 0.5,
          color: this.baseColor,
        });
      } else {
        entry.setTargetState({
          scale: 0.6,
          opacity: 0.2,
          color: this.baseColor,
        });
      }
    });

    // 触发焦点回调
    this.focusCallbacks.forEach((cb) => cb(this.currentFocusIndex));
  }

  setFocus(markerIndex: number, focusCallback?: (index: number) => void): void {
    this.currentFocusIndex = THREE.MathUtils.clamp(markerIndex, 0, this.nodes.length - 1);
    this.currentDockIndex = Math.floor(this.currentFocusIndex / this.DOCK_INTERVAL);

    if (focusCallback) {
      focusCallback(this.currentFocusIndex);
    }

    this.applyFocus();
  }

  getCurrentFocusIndex(): number {
    return this.currentFocusIndex;
  }

  getCameraControlState(): CameraControlState {
    return {
      position: this.cameraPosition.clone(),
      target: this.cameraLookAt.clone(),
      fov: this.camera?.fov,
    };
  }

  getHUDConfig(): ModeHUDConfig {
    return {
      showTimeline: true,
      showAxis: false, // 河流模式不显示坐标轴
      showHints: true,
      customElements: {
        dockIndicator: this.createDockIndicator(),
      },
    };
  }

  private createDockIndicator(): HTMLElement {
    const indicator = document.createElement("div");
    indicator.className = "river-dock-indicator";
    indicator.innerHTML = `
      <div class="text-xs text-text-muted">
        停靠点: ${this.currentDockIndex + 1} / ${this.dockPoints.length}
      </div>
    `;
    return indicator;
  }

  getScene(): InstanceType<typeof THREE.Scene> {
    if (!this.scene) {
      throw new Error("RiverCruiseMode: Scene not initialized");
    }
    return this.scene;
  }

  getCamera(): InstanceType<typeof THREE.PerspectiveCamera> {
    if (!this.camera) {
      throw new Error("RiverCruiseMode: Camera not initialized");
    }
    return this.camera;
  }

  getRenderer(): InstanceType<typeof THREE.WebGLRenderer> {
    if (!this.renderer) {
      throw new Error("RiverCruiseMode: Renderer not initialized");
    }
    return this.renderer;
  }

  getControls(): any | null {
    return this.controls;
  }

  update(deltaTime: number): void {
    if (!this.camera) return;

    // 更新相机位置（平滑过渡）
    this.cameraPosition.lerp(this.targetCameraPosition, 0.05);
    this.cameraLookAt.lerp(this.targetLookAt, 0.05);

    this.camera.position.copy(this.cameraPosition);
    this.camera.lookAt(this.cameraLookAt);

    // 更新水流动画 - 通过偏移法线贴图来模拟流动
    this.riverUvOffset += 0.004; // 增加流动速度

    // 实时顶点动画 - 让水面真正波动
    if (this.riverGeometry && this.originalVertices) {
      const positionAttribute = this.riverGeometry.getAttribute('position');
      const positions = positionAttribute.array as Float32Array;
      const time = this.riverUvOffset;

      for (let i = 0; i < positions.length; i += 3) {
        const x = this.originalVertices[i];
        const z = this.originalVertices[i + 2];

        // 多层波浪叠加
        const wave1 = Math.sin(x * 0.5 + time * 2) * 0.15;
        const wave2 = Math.sin(z * 0.8 + time * 3) * 0.12;
        const wave3 = Math.sin((x + z) * 0.3 + time * 1.5) * 0.08;

        // 应用波浪高度
        positions[i + 1] = this.originalVertices[i + 1] + wave1 + wave2 + wave3;
      }

      positionAttribute.needsUpdate = true;
      this.riverGeometry.computeVertexNormals();
    }

    // 法线贴图动画
    if (this.waterNormalMap) {
      // 设置纹理偏移以创建流动效果
      this.waterNormalMap.offset.x = Math.sin(this.riverUvOffset * 0.5) * 0.1;
      this.waterNormalMap.offset.y = this.riverUvOffset;
      this.waterNormalMap.needsUpdate = true;
    }

    // 材质动画效果
    if (this.riverMaterial) {
      // 波动法线强度
      const wave = Math.sin(this.riverUvOffset * 5) * 0.5 + 1.5;
      this.riverMaterial.normalScale.set(wave * 2.5, wave * 2.5);

      // 发光强度脉动
      const pulse = Math.sin(this.riverUvOffset * 3) * 0.15 + 0.4;
      this.riverMaterial.emissiveIntensity = pulse;

      // 颜色微妙变化
      const colorShift = Math.sin(this.riverUvOffset * 2) * 0.05;
      const baseColor = 0x1e88e5;
      const r = ((baseColor >> 16) & 0xff) / 255;
      const g = ((baseColor >> 8) & 0xff) / 255;
      const b = (baseColor & 0xff) / 255;
      this.riverMaterial.color.setRGB(
        r + colorShift,
        g + colorShift * 0.5,
        b - colorShift * 0.5
      );
    }

    // 更新所有节点的过渡动画
    this.nodes.forEach((entry) => {
      entry.updateTransition();
    });

    // 更新控制器（如果存在）
    if (this.controls) {
      this.controls.target.copy(this.cameraLookAt);
      this.controls.update();
    }
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
   * 获取当前停靠点索引
   */
  getCurrentDockIndex(): number {
    return this.currentDockIndex;
  }

  /**
   * 获取总停靠点数量
   */
  getTotalDocks(): number {
    return this.dockPoints.length;
  }
}
