import * as THREE from "three";
import { BaseTimelineMode } from "./BaseTimelineMode";
import type { ModeSceneConfig, ModeDataset, ModeHUDConfig, CameraControlState } from "./ITimelineMode";
import type { TimelineEventNode } from "../core/event-node";
import { TimelineScene } from "../core/scene";
import { COLOR_ACTIVE, COLOR_BASE, getDefaultFocusAnchor } from "../core/constants";

/**
 * 星轨螺旋模式
 * 模型沿螺旋轨道排列如繁星，向上延伸
 */
export class HelixConstellationMode extends BaseTimelineMode {
  private timelineScene: TimelineScene | null = null;
  private timelineGroup: InstanceType<typeof THREE.Group> | null = null;
  private helixPath: InstanceType<typeof THREE.Line> | null = null;
  private particleSystem: InstanceType<typeof THREE.Points> | null = null;

  // 螺旋参数
  private readonly HELIX_RADIUS = 6.0; // 螺旋半径
  private readonly HELIX_HEIGHT_PER_TURN = 4.0; // 每圈的高度（降低以增加密度）
  private readonly TOTAL_TURNS = 6; // 总圈数（减少以适应较少节点）
  private readonly TOTAL_HEIGHT = this.HELIX_HEIGHT_PER_TURN * this.TOTAL_TURNS; // 总高度 = 24

  // 相机参数
  private cameraDistance = 12.0; // 相机水平距离
  private cameraHeightOffset = 5.0; // 相机高度偏移（在焦点上方）
  private cameraAngle = 0; // 相机水平角度
  private targetCameraAngle = 0;

  // 相机位置和目标
  private cameraPosition = new THREE.Vector3();
  private targetCameraPosition = new THREE.Vector3();
  private cameraLookAt = new THREE.Vector3();
  private targetLookAt = new THREE.Vector3();

  // 颜色
  private activeColor = new THREE.Color(COLOR_ACTIVE);
  private baseColor = new THREE.Color(COLOR_BASE);
  private focusStarColor = new THREE.Color(0xf4d03f); // 柔和暖黄色（聚焦星星效果）

  // 几何资源
  private markerGeometry: InstanceType<typeof THREE.SphereGeometry> | null = null;
  private helixGeometry: InstanceType<typeof THREE.BufferGeometry> | null = null;
  private helixMaterial: InstanceType<typeof THREE.LineBasicMaterial> | null = null;
  private particleGeometry: InstanceType<typeof THREE.BufferGeometry> | null = null;
  private particleMaterial: InstanceType<typeof THREE.PointsMaterial> | null = null;

  // 焦点发光效果
  private glowSprite: InstanceType<typeof THREE.Sprite> | null = null;
  private glowMaterial: InstanceType<typeof THREE.SpriteMaterial> | null = null;

  // 年份锚点相关
  private yearAnchors: Array<{
    year: number;
    timestamp: number;
    position: InstanceType<typeof THREE.Vector3>;
    mesh: InstanceType<typeof THREE.Mesh>;
  }> = [];
  private yearAnchorGeometry: InstanceType<typeof THREE.SphereGeometry> | null = null;
  private yearAnchorMaterial: InstanceType<typeof THREE.MeshStandardMaterial> | null = null;

  // 季度锚点相关
  private quarterAnchors: Array<{
    year: number;
    quarter: number;
    timestamp: number;
    position: InstanceType<typeof THREE.Vector3>;
    mesh: InstanceType<typeof THREE.Mesh>;
  }> = [];
  private quarterAnchorGeometry: InstanceType<typeof THREE.SphereGeometry> | null = null;
  private quarterAnchorMaterial: InstanceType<typeof THREE.MeshStandardMaterial> | null = null;

  // 月份锚点相关
  private monthAnchors: Array<{
    year: number;
    month: number;
    timestamp: number;
    position: InstanceType<typeof THREE.Vector3>;
    mesh: InstanceType<typeof THREE.Mesh>;
  }> = [];
  private monthAnchorGeometry: InstanceType<typeof THREE.SphereGeometry> | null = null;
  private monthAnchorMaterial: InstanceType<typeof THREE.MeshStandardMaterial> | null = null;

  private focusAnchor = getDefaultFocusAnchor();

  getName(): string {
    return "HelixConstellationMode";
  }

  async init(config: ModeSceneConfig, dataset: ModeDataset): Promise<void> {
    // 获取主题并计算背景颜色
    const theme = config.theme || (document.documentElement.dataset.theme as 'light' | 'dark') || 'dark';
    const getHelixBackground = (t: 'light' | 'dark') => {
      return t === 'light' ? 0xd6e4f5 : 0x0a0e27;
    };
    const bgColor = getHelixBackground(theme);
    const fogColor = bgColor;

    // 初始化场景
    this.timelineScene = new TimelineScene({
      container: config.container,
      size: config.size,
      background: bgColor,
      camera: config.camera,
    });

    this.scene = this.timelineScene.scene;
    this.camera = this.timelineScene.camera;
    this.renderer = this.timelineScene.renderer;
    this.controls = this.timelineScene.controls;
    this.dataset = dataset;

    // 禁用 OrbitControls，因为我们要完全控制相机
    if (this.controls) {
      this.controls.enabled = false;
    }

    // 创建时间轴组
    this.timelineGroup = new THREE.Group();
    this.scene.add(this.timelineGroup);

    // 添加雾化效果（太空深处）
    this.scene.fog = new THREE.Fog(fogColor, 30, 120);

    // 创建螺旋路径
    this.createHelixPath();

    // 创建粒子系统
    this.createParticleSystem();

    // 创建节点几何（小球用于星轨效果）
    this.markerGeometry = new THREE.SphereGeometry(0.08, 16, 16);

    // 创建焦点发光效果
    this.createFocusGlow();

    // 添加光照
    const ambientLight = new THREE.AmbientLight(0x4a5f8f, 0.3); // 微弱的蓝色环境光
    this.scene.add(ambientLight);

    const pointLight1 = new THREE.PointLight(0x64b5f6, 0.8, 50);
    pointLight1.position.set(0, this.TOTAL_HEIGHT / 2, 0);
    this.scene.add(pointLight1);

    const pointLight2 = new THREE.PointLight(0x9c27b0, 0.6, 40);
    pointLight2.position.set(10, this.TOTAL_HEIGHT * 0.3, 10);
    this.scene.add(pointLight2);

    const pointLight3 = new THREE.PointLight(0x00bcd4, 0.6, 40);
    pointLight3.position.set(-10, this.TOTAL_HEIGHT * 0.7, -10);
    this.scene.add(pointLight3);

    // 初始化相机位置（将在 layoutNodes 后设置到正确位置）
    this.cameraPosition.copy(this.focusAnchor.clone().add(new THREE.Vector3(10, 5, 10)));
    this.targetCameraPosition.copy(this.cameraPosition);
    this.cameraLookAt.copy(this.focusAnchor);
    this.targetLookAt.copy(this.focusAnchor);

    if (this.camera) {
      this.camera.position.copy(this.cameraPosition);
      this.camera.lookAt(this.cameraLookAt);
    }
  }

  /**
   * 创建螺旋路径可视化
   */
  private createHelixPath(): void {
    if (!this.timelineGroup) return;

    console.log(`[createHelixPath] Creating helix with TOTAL_HEIGHT=${this.TOTAL_HEIGHT}, TOTAL_TURNS=${this.TOTAL_TURNS}, HELIX_RADIUS=${this.HELIX_RADIUS}`);

    const points: InstanceType<typeof THREE.Vector3>[] = [];
    const segments = 500;

    for (let i = 0; i <= segments; i++) {
      const t = i / segments;
      const angle = t * Math.PI * 2 * this.TOTAL_TURNS;
      const height = t * this.TOTAL_HEIGHT;
      const x = Math.cos(angle) * this.HELIX_RADIUS;
      const z = Math.sin(angle) * this.HELIX_RADIUS;
      points.push(new THREE.Vector3(x, height, z));
    }

    console.log(`[createHelixPath] Created ${points.length} points. First: (${points[0].x.toFixed(2)}, ${points[0].y.toFixed(2)}, ${points[0].z.toFixed(2)}), Last: (${points[points.length-1].x.toFixed(2)}, ${points[points.length-1].y.toFixed(2)}, ${points[points.length-1].z.toFixed(2)})`);

    this.helixGeometry = new THREE.BufferGeometry().setFromPoints(points);
    this.helixMaterial = new THREE.LineBasicMaterial({
      color: 0x1e88e5,
      opacity: 0.3,
      transparent: true,
      linewidth: 1,
    });

    this.helixPath = new THREE.Line(this.helixGeometry, this.helixMaterial);
    this.timelineGroup.add(this.helixPath);
  }

  /**
   * 创建粒子系统（星空背景）
   */
  private createParticleSystem(): void {
    if (!this.timelineGroup) return;

    const particleCount = 1000;
    const positions = new Float32Array(particleCount * 3);

    for (let i = 0; i < particleCount; i++) {
      // 在螺旋周围随机分布粒子
      const angle = Math.random() * Math.PI * 2;
      const radius = this.HELIX_RADIUS + Math.random() * 20 - 10;
      const height = Math.random() * this.TOTAL_HEIGHT;

      positions[i * 3] = Math.cos(angle) * radius;
      positions[i * 3 + 1] = height;
      positions[i * 3 + 2] = Math.sin(angle) * radius;
    }

    this.particleGeometry = new THREE.BufferGeometry();
    this.particleGeometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));

    this.particleMaterial = new THREE.PointsMaterial({
      color: 0xffffff,
      size: 0.15,
      opacity: 0.6,
      transparent: true,
      sizeAttenuation: true,
    });

    this.particleSystem = new THREE.Points(this.particleGeometry, this.particleMaterial);
    this.timelineGroup.add(this.particleSystem);
  }

  /**
   * 创建焦点发光效果
   */
  private createFocusGlow(): void {
    if (!this.scene) return;

    // 创建径向渐变纹理
    const canvas = document.createElement("canvas");
    canvas.width = 256;
    canvas.height = 256;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    // 绘制径向渐变（中心亮，边缘透明）
    const gradient = ctx.createRadialGradient(128, 128, 0, 128, 128, 128);
    gradient.addColorStop(0, "rgba(255, 215, 0, 1)"); // 金色中心
    gradient.addColorStop(0.2, "rgba(255, 165, 0, 0.8)"); // 橙色
    gradient.addColorStop(0.5, "rgba(255, 100, 100, 0.4)"); // 红色
    gradient.addColorStop(1, "rgba(255, 255, 255, 0)"); // 透明边缘

    ctx.fillStyle = gradient;
    ctx.fillRect(0, 0, 256, 256);

    const texture = new THREE.CanvasTexture(canvas);

    this.glowMaterial = new THREE.SpriteMaterial({
      map: texture,
      color: 0xffd700, // 金色
      transparent: true,
      opacity: 0.7,
      blending: THREE.AdditiveBlending, // 加法混合产生发光效果
    });

    this.glowSprite = new THREE.Sprite(this.glowMaterial);
    this.glowSprite.scale.set(1.5, 1.5, 1); // 初始缩放
    this.glowSprite.visible = false; // 初始隐藏，等待焦点设置
    this.scene.add(this.glowSprite);
  }

  /**
   * 将时间戳转换为螺旋位置
   */
  private timeToHelixPosition(t: number): InstanceType<typeof THREE.Vector3> {
    const angle = t * Math.PI * 2 * this.TOTAL_TURNS;
    const height = t * this.TOTAL_HEIGHT;
    const x = Math.cos(angle) * this.HELIX_RADIUS;
    const z = Math.sin(angle) * this.HELIX_RADIUS;

    // 调试日志
    if (t === 0 || t === 1) {
      console.log(`[timeToHelixPosition] t=${t}, TOTAL_HEIGHT=${this.TOTAL_HEIGHT}, TOTAL_TURNS=${this.TOTAL_TURNS}, height=${height}, angle=${angle}`);
    }

    return new THREE.Vector3(x, height, z);
  }

  dispose(): void {
    try {
      // 清理几何资源
      this.markerGeometry?.dispose();
      this.helixGeometry?.dispose();
      this.helixMaterial?.dispose();
      this.particleGeometry?.dispose();
      this.particleMaterial?.dispose();

      // 清理发光精灵
      if (this.glowSprite && this.scene) {
        this.scene.remove(this.glowSprite);
        this.glowMaterial?.map?.dispose();
        this.glowMaterial?.dispose();
        this.glowSprite = null;
        this.glowMaterial = null;
      }

      // 清理年份锚点
      this.yearAnchors.forEach(anchor => {
        if (this.timelineGroup) {
          this.timelineGroup.remove(anchor.mesh);
        }
        (anchor.mesh.material as THREE.Material).dispose();
      });
      this.yearAnchors = [];
      this.yearAnchorGeometry?.dispose();
      this.yearAnchorMaterial?.dispose();
      this.yearAnchorGeometry = null;
      this.yearAnchorMaterial = null;

      // 清理季度锚点
      this.quarterAnchors.forEach(anchor => {
        if (this.timelineGroup) {
          this.timelineGroup.remove(anchor.mesh);
        }
        (anchor.mesh.material as THREE.Material).dispose();
      });
      this.quarterAnchors = [];
      this.quarterAnchorGeometry?.dispose();
      this.quarterAnchorMaterial?.dispose();
      this.quarterAnchorGeometry = null;
      this.quarterAnchorMaterial = null;

      // 清理月份锚点
      this.monthAnchors.forEach(anchor => {
        if (this.timelineGroup) {
          this.timelineGroup.remove(anchor.mesh);
        }
        (anchor.mesh.material as THREE.Material).dispose();
      });
      this.monthAnchors = [];
      this.monthAnchorGeometry?.dispose();
      this.monthAnchorMaterial?.dispose();
      this.monthAnchorGeometry = null;
      this.monthAnchorMaterial = null;

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
    } catch (error) {
      console.warn("Error during HelixConstellationMode disposal:", error);
    }
  }

  handleWheelEvent(direction: number, currentIndex: number): number {
    // 滚轮控制沿螺旋上升/下降
    const nextIndex = currentIndex + direction;
    return THREE.MathUtils.clamp(nextIndex, 0, this.nodes.length - 1);
  }

  handleNodeClick(mesh: InstanceType<typeof THREE.Mesh>): number | null {
    // 检查是否点击了年份锚点
    if (mesh.userData.isYearAnchor) {
      return this.handleYearAnchorClick(mesh);
    }

    // 检查是否点击了季度锚点
    if (mesh.userData.isQuarterAnchor) {
      return this.handleQuarterAnchorClick(mesh);
    }

    // 检查是否点击了月份锚点
    if (mesh.userData.isMonthAnchor) {
      return this.handleMonthAnchorClick(mesh);
    }

    const index =
      typeof mesh.userData.markerIndex === "number"
        ? mesh.userData.markerIndex
        : this.nodes.findIndex((node) => node.mesh === mesh);

    return index >= 0 && index < this.nodes.length ? index : null;
  }

  /**
   * 处理年份锚点点击
   * @returns 该年份后的第一个模型索引
   */
  private handleYearAnchorClick(mesh: THREE.Mesh): number | null {
    const year = mesh.userData.year as number;
    const yearTimestamp = mesh.userData.timestamp as number;

    console.log(`[YearAnchor] Clicked on year ${year} anchor`);

    // 查找该年份后的第一个模型节点
    const firstModelIndex = this.nodes.findIndex((node) => {
      const modelTime = new Date(node.model.created_at).getTime();
      return modelTime >= yearTimestamp;
    });

    if (firstModelIndex >= 0) {
      console.log(`[YearAnchor] Jumping to first model of ${year} at index ${firstModelIndex}`);
      return firstModelIndex;
    }

    // 如果该年份之后没有模型，返回 null
    console.log(`[YearAnchor] No models found after ${year}, staying at current position`);
    return null;
  }

  /**
   * 处理季度锚点点击
   */
  private handleQuarterAnchorClick(mesh: THREE.Mesh): number | null {
    const year = mesh.userData.year as number;
    const quarter = mesh.userData.quarter as number;
    const quarterTimestamp = mesh.userData.timestamp as number;

    console.log(`[QuarterAnchor] Clicked on Q${quarter} ${year} anchor`);

    // 查找该季度后的第一个模型节点
    const firstModelIndex = this.nodes.findIndex((node) => {
      const modelTime = new Date(node.model.created_at).getTime();
      return modelTime >= quarterTimestamp;
    });

    if (firstModelIndex >= 0) {
      console.log(`[QuarterAnchor] Jumping to first model of Q${quarter} ${year} at index ${firstModelIndex}`);
      return firstModelIndex;
    }

    console.log(`[QuarterAnchor] No models found after Q${quarter} ${year}`);
    return null;
  }

  /**
   * 处理月份锚点点击
   */
  private handleMonthAnchorClick(mesh: THREE.Mesh): number | null {
    const year = mesh.userData.year as number;
    const month = mesh.userData.month as number;
    const monthTimestamp = mesh.userData.timestamp as number;

    console.log(`[MonthAnchor] Clicked on ${year}-${String(month).padStart(2, '0')} anchor`);

    // 查找该月份后的第一个模型节点
    const firstModelIndex = this.nodes.findIndex((node) => {
      const modelTime = new Date(node.model.created_at).getTime();
      return modelTime >= monthTimestamp;
    });

    if (firstModelIndex >= 0) {
      console.log(`[MonthAnchor] Jumping to first model of ${year}-${String(month).padStart(2, '0')} at index ${firstModelIndex}`);
      return firstModelIndex;
    }

    console.log(`[MonthAnchor] No models found after ${year}-${String(month).padStart(2, '0')}`);
    return null;
  }

  layoutNodes(nodes: TimelineEventNode[]): void {
    if (!this.dataset || !this.timelineGroup || !this.markerGeometry) {
      return;
    }

    this.nodes = [];

    const sorted = this.dataset.models;
    const minTime = this.dataset.minTime;
    const span = this.dataset.span;

    console.log(`[HelixMode] Layout ${sorted.length} models, minTime: ${minTime}, span: ${span}`);

    // 存储已放置节点的位置用于碰撞检测
    const placedPositions: InstanceType<typeof THREE.Vector3>[] = [];
    const MIN_DISTANCE = 0.3; // 节点间最小距离

    // 遍历已排序的 dataset.models，然后在 nodes 中查找匹配的节点
    sorted.forEach((model, index) => {
      const created = new Date(model.created_at).getTime();
      const t = span > 0 ? (created - minTime) / span : 0;

      // 计算螺旋位置
      let nodePosition = this.timeToHelixPosition(t);

      // 碰撞检测：如果与已放置的节点距离太近，添加微小偏移
      let attempts = 0;
      const maxAttempts = 10;
      while (attempts < maxAttempts) {
        let collision = false;
        for (const placedPos of placedPositions) {
          const distance = nodePosition.distanceTo(placedPos);
          if (distance < MIN_DISTANCE) {
            collision = true;
            // 计算切向偏移（沿螺旋方向稍微前进）
            const newT = t + (attempts + 1) * 0.002; // 每次尝试增加一点点
            nodePosition = this.timeToHelixPosition(Math.min(newT, 1.0));
            break;
          }
        }
        if (!collision) break;
        attempts++;
      }

      // 记录此位置
      placedPositions.push(nodePosition.clone());

      if (index < 5 || index >= sorted.length - 5) {
        console.log(`[HelixMode] Model ${index}: t=${t.toFixed(4)}, pos=(${nodePosition.x.toFixed(2)}, ${nodePosition.y.toFixed(2)}, ${nodePosition.z.toFixed(2)}), date=${model.created_at}`);
      }

      // 在传入的 nodes 数组中查找匹配的节点
      const node = nodes.find((n) => n.model.model_id === model.model_id);

      if (node) {
        node.basePosition.copy(nodePosition);
        node.mesh.position.copy(nodePosition); // 同步更新 mesh 位置
        node.attachTo(this.timelineGroup!);
        this.nodes.push(node);
        node.setMarkerIndex(this.nodes.length - 1);
      }
    });

    console.log(`[HelixMode] Total nodes laid out: ${this.nodes.length}`);

    // 创建年份、季度、月份锚点
    this.createYearAnchors();
    this.createQuarterAnchors();
    this.createMonthAnchors();

    // 初始聚焦最新节点（最后一个）
    if (this.nodes.length > 0) {
      this.currentFocusIndex = this.nodes.length - 1;
      this.applyFocus();
    }
  }

  /**
   * 计算并创建年份锚点
   */
  private createYearAnchors(): void {
    if (!this.dataset || !this.timelineGroup) return;

    const minTime = this.dataset.minTime;
    const maxTime = this.dataset.maxTime;
    const span = this.dataset.span;

    // 提取起始年份和结束年份
    const startDate = new Date(minTime);
    const endDate = new Date(maxTime);
    const startYear = startDate.getUTCFullYear();
    const endYear = endDate.getUTCFullYear();

    console.log(`[YearAnchors] Timeline range: ${startYear}-${endYear}`);

    // 清空旧锚点
    this.yearAnchors.forEach(anchor => {
      if (this.timelineGroup) {
        this.timelineGroup.remove(anchor.mesh);
      }
      (anchor.mesh.material as THREE.Material).dispose();
    });
    this.yearAnchors = [];

    // 创建几何和材质（复用）
    if (!this.yearAnchorGeometry) {
      this.yearAnchorGeometry = new THREE.SphereGeometry(0.15, 16, 16);
    }

    if (!this.yearAnchorMaterial) {
      this.yearAnchorMaterial = new THREE.MeshStandardMaterial({
        color: 0xff3333,
        emissive: 0xff0000,
        emissiveIntensity: 0.8,
        transparent: true,
        opacity: 1.0,
      });
    }

    // 遍历每个整年份
    for (let year = startYear; year <= endYear + 1; year++) {
      // 计算该年份 1 月 1 日 00:00:00 UTC 的时间戳
      const yearStartDate = new Date(Date.UTC(year, 0, 1, 0, 0, 0));
      const yearTimestamp = yearStartDate.getTime();

      // 检查是否在时间轴范围内
      if (yearTimestamp < minTime || yearTimestamp > maxTime) {
        continue;
      }

      // 计算归一化位置 t（0.0 - 1.0）
      const t = span > 0 ? (yearTimestamp - minTime) / span : 0;

      // 转换为螺旋位置
      const position = this.timeToHelixPosition(t);

      // 创建锚点网格
      const anchorMesh = new THREE.Mesh(
        this.yearAnchorGeometry,
        this.yearAnchorMaterial.clone()
      );
      anchorMesh.position.copy(position);
      anchorMesh.userData.isYearAnchor = true;
      anchorMesh.userData.year = year;
      anchorMesh.userData.timestamp = yearTimestamp;

      this.timelineGroup.add(anchorMesh);

      // 记录锚点信息
      this.yearAnchors.push({
        year,
        timestamp: yearTimestamp,
        position: position.clone(),
        mesh: anchorMesh,
      });

      console.log(`[YearAnchors] Created anchor for ${year} at t=${t.toFixed(4)}, pos=(${position.x.toFixed(2)}, ${position.y.toFixed(2)}, ${position.z.toFixed(2)})`);
    }

    console.log(`[YearAnchors] Total anchors created: ${this.yearAnchors.length}`);
  }

  /**
   * 计算并创建季度锚点
   */
  private createQuarterAnchors(): void {
    if (!this.dataset || !this.timelineGroup) return;

    const minTime = this.dataset.minTime;
    const maxTime = this.dataset.maxTime;
    const span = this.dataset.span;

    const startDate = new Date(minTime);
    const endDate = new Date(maxTime);
    const startYear = startDate.getUTCFullYear();
    const endYear = endDate.getUTCFullYear();

    console.log(`[QuarterAnchors] Timeline range: ${startYear}-${endYear}`);

    // 清空旧锚点
    this.quarterAnchors.forEach(anchor => {
      if (this.timelineGroup) {
        this.timelineGroup.remove(anchor.mesh);
      }
      (anchor.mesh.material as THREE.Material).dispose();
    });
    this.quarterAnchors = [];

    // 创建几何和材质（复用）
    if (!this.quarterAnchorGeometry) {
      this.quarterAnchorGeometry = new THREE.SphereGeometry(0.12, 16, 16); // 比年份小
    }

    if (!this.quarterAnchorMaterial) {
      this.quarterAnchorMaterial = new THREE.MeshStandardMaterial({
        color: 0xff8833, // 橙色
        emissive: 0xff6600,
        emissiveIntensity: 0.6,
        transparent: true,
        opacity: 1.0,
      });
    }

    // 遍历每个季度
    for (let year = startYear; year <= endYear; year++) {
      for (let quarter = 1; quarter <= 4; quarter++) {
        const month = (quarter - 1) * 3; // Q1: 0, Q2: 3, Q3: 6, Q4: 9
        const quarterStartDate = new Date(Date.UTC(year, month, 1, 0, 0, 0));
        const quarterTimestamp = quarterStartDate.getTime();

        // 检查是否在时间轴范围内
        if (quarterTimestamp < minTime || quarterTimestamp > maxTime) {
          continue;
        }

        const t = span > 0 ? (quarterTimestamp - minTime) / span : 0;
        const position = this.timeToHelixPosition(t);

        const anchorMesh = new THREE.Mesh(
          this.quarterAnchorGeometry,
          this.quarterAnchorMaterial.clone()
        );
        anchorMesh.position.copy(position);
        anchorMesh.userData.isQuarterAnchor = true;
        anchorMesh.userData.year = year;
        anchorMesh.userData.quarter = quarter;
        anchorMesh.userData.timestamp = quarterTimestamp;

        this.timelineGroup.add(anchorMesh);

        this.quarterAnchors.push({
          year,
          quarter,
          timestamp: quarterTimestamp,
          position: position.clone(),
          mesh: anchorMesh,
        });

        console.log(`[QuarterAnchors] Created anchor for Q${quarter} ${year} at t=${t.toFixed(4)}`);
      }
    }

    console.log(`[QuarterAnchors] Total anchors created: ${this.quarterAnchors.length}`);
  }

  /**
   * 计算并创建月份锚点
   */
  private createMonthAnchors(): void {
    if (!this.dataset || !this.timelineGroup) return;

    const minTime = this.dataset.minTime;
    const maxTime = this.dataset.maxTime;
    const span = this.dataset.span;

    const startDate = new Date(minTime);
    const endDate = new Date(maxTime);
    const startYear = startDate.getUTCFullYear();
    const endYear = endDate.getUTCFullYear();

    console.log(`[MonthAnchors] Timeline range: ${startYear}-${endYear}`);

    // 清空旧锚点
    this.monthAnchors.forEach(anchor => {
      if (this.timelineGroup) {
        this.timelineGroup.remove(anchor.mesh);
      }
      (anchor.mesh.material as THREE.Material).dispose();
    });
    this.monthAnchors = [];

    // 创建几何和材质（复用）
    if (!this.monthAnchorGeometry) {
      this.monthAnchorGeometry = new THREE.SphereGeometry(0.08, 16, 16); // 最小
    }

    if (!this.monthAnchorMaterial) {
      this.monthAnchorMaterial = new THREE.MeshStandardMaterial({
        color: 0xffcc33, // 黄色
        emissive: 0xffbb00,
        emissiveIntensity: 0.4,
        transparent: true,
        opacity: 0.8,
      });
    }

    // 遍历每个月份
    for (let year = startYear; year <= endYear; year++) {
      for (let month = 0; month < 12; month++) {
        const monthStartDate = new Date(Date.UTC(year, month, 1, 0, 0, 0));
        const monthTimestamp = monthStartDate.getTime();

        // 检查是否在时间轴范围内
        if (monthTimestamp < minTime || monthTimestamp > maxTime) {
          continue;
        }

        const t = span > 0 ? (monthTimestamp - minTime) / span : 0;
        const position = this.timeToHelixPosition(t);

        const anchorMesh = new THREE.Mesh(
          this.monthAnchorGeometry,
          this.monthAnchorMaterial.clone()
        );
        anchorMesh.position.copy(position);
        anchorMesh.userData.isMonthAnchor = true;
        anchorMesh.userData.year = year;
        anchorMesh.userData.month = month + 1; // 1-12
        anchorMesh.userData.timestamp = monthTimestamp;

        this.timelineGroup.add(anchorMesh);

        this.monthAnchors.push({
          year,
          month: month + 1,
          timestamp: monthTimestamp,
          position: position.clone(),
          mesh: anchorMesh,
        });
      }
    }

    console.log(`[MonthAnchors] Total anchors created: ${this.monthAnchors.length}`);
  }

  private applyFocus(): void {
    if (!this.nodes.length) {
      return;
    }

    this.currentFocusIndex = THREE.MathUtils.clamp(this.currentFocusIndex, 0, this.nodes.length - 1);

    const focusedNode = this.nodes[this.currentFocusIndex];
    const focusPosition = focusedNode.basePosition.clone();

    // 验证：获取mesh的实际世界位置
    const meshWorldPos = new THREE.Vector3();
    focusedNode.mesh.getWorldPosition(meshWorldPos);

    console.log(`[applyFocus] Focus index: ${this.currentFocusIndex}, basePos: (${focusPosition.x.toFixed(2)}, ${focusPosition.y.toFixed(2)}, ${focusPosition.z.toFixed(2)}), meshPos: (${focusedNode.mesh.position.x.toFixed(2)}, ${focusedNode.mesh.position.y.toFixed(2)}, ${focusedNode.mesh.position.z.toFixed(2)}), meshWorldPos: (${meshWorldPos.x.toFixed(2)}, ${meshWorldPos.y.toFixed(2)}, ${meshWorldPos.z.toFixed(2)}), cameraTarget: (${this.targetCameraPosition.x.toFixed(2)}, ${this.targetCameraPosition.y.toFixed(2)}, ${this.targetCameraPosition.z.toFixed(2)})`);

    // 计算相机位置：在焦点节点周围水平环绕，并在上方偏移
    const offsetX = Math.cos(this.cameraAngle) * this.cameraDistance;
    const offsetZ = Math.sin(this.cameraAngle) * this.cameraDistance;

    this.targetCameraPosition.set(
      focusPosition.x + offsetX,
      focusPosition.y + this.cameraHeightOffset, // 在焦点上方固定高度
      focusPosition.z + offsetZ
    );

    // 相机看向焦点节点
    this.targetLookAt.copy(focusPosition);

    console.log(`[applyFocus] Focus index: ${this.currentFocusIndex}, focusPos: (${focusPosition.x.toFixed(2)}, ${focusPosition.y.toFixed(2)}, ${focusPosition.z.toFixed(2)}), cameraTarget: (${this.targetCameraPosition.x.toFixed(2)}, ${this.targetCameraPosition.y.toFixed(2)}, ${this.targetCameraPosition.z.toFixed(2)})`);

    // 更新发光精灵位置
    if (this.glowSprite) {
      this.glowSprite.position.copy(focusPosition);
      this.glowSprite.visible = true;
    }

    // 更新节点状态（基于距离当前焦点的远近）
    this.nodes.forEach((entry, index) => {
      const distance = Math.abs(index - this.currentFocusIndex);

      if (distance === 0) {
        // 当前焦点：柔和暖黄色星星，发光
        entry.setTargetState({ scale: 0.5, opacity: 1.0, color: this.focusStarColor });
      } else if (distance <= 3) {
        // 近距离节点
        const proximity = 1 - distance / 3;
        entry.setTargetState({
          scale: 0.27 + proximity * 0.17,
          opacity: 0.7 + proximity * 0.3,
          color: this.baseColor,
        });
      } else if (distance <= 10) {
        // 中等距离节点
        const proximity = 1 - (distance - 3) / 7;
        entry.setTargetState({
          scale: 0.17 + proximity * 0.1,
          opacity: 0.4 + proximity * 0.3,
          color: this.baseColor,
        });
      } else {
        // 远距离节点：几乎不可见（小星点）
        entry.setTargetState({ scale: 0.1, opacity: 0.15, color: this.baseColor });
      }
    });

    // 触发焦点回调
    this.focusCallbacks.forEach((cb) => cb(this.currentFocusIndex));
  }

  setFocus(markerIndex: number, focusCallback?: (index: number) => void): void {
    this.currentFocusIndex = THREE.MathUtils.clamp(markerIndex, 0, this.nodes.length - 1);

    if (focusCallback) {
      focusCallback(this.currentFocusIndex);
    }

    this.applyFocus();
  }

  getCurrentFocusIndex(): number {
    return this.currentFocusIndex;
  }

  /**
   * 获取年份锚点数组（用于交互）
   */
  getYearAnchors(): Array<{ year: number; mesh: InstanceType<typeof THREE.Mesh> }> {
    return this.yearAnchors.map(anchor => ({
      year: anchor.year,
      mesh: anchor.mesh,
    }));
  }

  /**
   * 获取季度锚点数组（用于交互）
   */
  getQuarterAnchors(): Array<{ year: number; quarter: number; mesh: InstanceType<typeof THREE.Mesh> }> {
    return this.quarterAnchors.map(anchor => ({
      year: anchor.year,
      quarter: anchor.quarter,
      mesh: anchor.mesh,
    }));
  }

  /**
   * 获取月份锚点数组（用于交互）
   */
  getMonthAnchors(): Array<{ year: number; month: number; mesh: InstanceType<typeof THREE.Mesh> }> {
    return this.monthAnchors.map(anchor => ({
      year: anchor.year,
      month: anchor.month,
      mesh: anchor.mesh,
    }));
  }

  getCameraControlState(): CameraControlState {
    return {
      position: this.camera?.position.clone() || new THREE.Vector3(),
      target: this.cameraLookAt.clone(),
      fov: this.camera?.fov,
    };
  }

  getHUDConfig(): ModeHUDConfig {
    return {
      showTimeline: true,
      showAxis: false,
      showHints: true,
      customElements: {
        helixInfo: this.createHelixInfo(),
      },
    };
  }

  private createHelixInfo(): HTMLElement {
    const container = document.createElement("div");
    container.className = "helix-info";
    container.style.cssText = `
      position: fixed;
      bottom: 80px;
      right: 20px;
      padding: 12px;
      background: rgba(10, 14, 39, 0.85);
      border: 1px solid rgba(100, 181, 246, 0.3);
      border-radius: 8px;
      backdrop-filter: blur(10px);
      box-shadow: 0 4px 12px rgba(0, 0, 0, 0.5);
    `;

    if (this.nodes.length > 0 && this.nodes[this.currentFocusIndex]) {
      const focusHeight = this.nodes[this.currentFocusIndex].basePosition.y;
      const currentTurn = Math.floor((focusHeight / this.TOTAL_HEIGHT) * this.TOTAL_TURNS);
      const progress = (focusHeight / this.TOTAL_HEIGHT) * this.TOTAL_TURNS; // 带小数的进度

      // 创建文本信息
      const textDiv = document.createElement("div");
      textDiv.className = "text-xs text-text-muted mb-2";
      textDiv.textContent = `螺旋圈层: ${currentTurn + 1} / ${this.TOTAL_TURNS}`;
      container.appendChild(textDiv);

      // 创建圆形进度指示器 (Canvas)
      const canvas = document.createElement("canvas");
      canvas.width = 80;
      canvas.height = 80;
      canvas.style.display = "block";
      const ctx = canvas.getContext("2d");

      if (ctx) {
        const centerX = 40;
        const centerY = 40;
        const radius = 30;

        // 绘制背景圆环
        ctx.strokeStyle = "rgba(100, 181, 246, 0.2)";
        ctx.lineWidth = 6;
        ctx.beginPath();
        ctx.arc(centerX, centerY, radius, 0, Math.PI * 2);
        ctx.stroke();

        // 绘制螺旋圈层分隔线
        for (let i = 0; i < this.TOTAL_TURNS; i++) {
          const angle = (i / this.TOTAL_TURNS) * Math.PI * 2 - Math.PI / 2;
          const x1 = centerX + Math.cos(angle) * (radius - 5);
          const y1 = centerY + Math.sin(angle) * (radius - 5);
          const x2 = centerX + Math.cos(angle) * (radius + 5);
          const y2 = centerY + Math.sin(angle) * (radius + 5);

          ctx.strokeStyle = "rgba(100, 181, 246, 0.4)";
          ctx.lineWidth = 1;
          ctx.beginPath();
          ctx.moveTo(x1, y1);
          ctx.lineTo(x2, y2);
          ctx.stroke();
        }

        // 绘制进度弧线（金色发光）
        const progressAngle = (progress / this.TOTAL_TURNS) * Math.PI * 2 - Math.PI / 2;
        ctx.strokeStyle = "#ffd700";
        ctx.lineWidth = 6;
        ctx.lineCap = "round";
        ctx.beginPath();
        ctx.arc(centerX, centerY, radius, -Math.PI / 2, progressAngle);
        ctx.stroke();

        // 绘制当前位置指示器（小圆点）
        const dotX = centerX + Math.cos(progressAngle) * radius;
        const dotY = centerY + Math.sin(progressAngle) * radius;
        ctx.fillStyle = "#ffd700";
        ctx.shadowColor = "#ffd700";
        ctx.shadowBlur = 10;
        ctx.beginPath();
        ctx.arc(dotX, dotY, 4, 0, Math.PI * 2);
        ctx.fill();
        ctx.shadowBlur = 0;

        // 绘制中心文本（当前圈数）
        ctx.fillStyle = "rgba(255, 255, 255, 0.9)";
        ctx.font = "bold 16px sans-serif";
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText(`${currentTurn + 1}`, centerX, centerY);
      }

      container.appendChild(canvas);
    }

    return container;
  }

  getScene(): InstanceType<typeof THREE.Scene> {
    if (!this.scene) {
      throw new Error("HelixConstellationMode: Scene not initialized");
    }
    return this.scene;
  }

  getCamera(): InstanceType<typeof THREE.PerspectiveCamera> {
    if (!this.camera) {
      throw new Error("HelixConstellationMode: Camera not initialized");
    }
    return this.camera;
  }

  getRenderer(): InstanceType<typeof THREE.WebGLRenderer> {
    if (!this.renderer) {
      throw new Error("HelixConstellationMode: Renderer not initialized");
    }
    return this.renderer;
  }

  getControls(): any | null {
    return this.controls;
  }

  update(deltaTime: number): void {
    if (!this.camera) return;

    // 禁用自动旋转，保持相机稳定
    // this.targetCameraAngle += 0.003;
    this.cameraAngle += (this.targetCameraAngle - this.cameraAngle) * 0.05;

    // 重新计算目标相机位置（基于当前角度）
    if (this.nodes.length > 0 && this.nodes[this.currentFocusIndex]) {
      const focusPosition = this.nodes[this.currentFocusIndex].basePosition.clone();

      const offsetX = Math.cos(this.cameraAngle) * this.cameraDistance;
      const offsetZ = Math.sin(this.cameraAngle) * this.cameraDistance;

      this.targetCameraPosition.set(
        focusPosition.x + offsetX,
        focusPosition.y + this.cameraHeightOffset, // 在焦点上方固定高度
        focusPosition.z + offsetZ
      );

      this.targetLookAt.copy(focusPosition);
    }

    // 相机位置和lookAt目标平滑过渡（动态缓动）
    // 计算距离目标的距离，距离越远速度越快
    const distanceToTarget = this.cameraPosition.distanceTo(this.targetCameraPosition);
    const lookAtDistance = this.cameraLookAt.distanceTo(this.targetLookAt);

    // 动态 lerp 系数：远距离时 0.15（快速），近距离时 0.05（慢速）
    const baseLerpSpeed = 0.05;
    const maxLerpSpeed = 0.15;
    const lerpFactor = THREE.MathUtils.clamp(
      baseLerpSpeed + (distanceToTarget / 10) * (maxLerpSpeed - baseLerpSpeed),
      baseLerpSpeed,
      maxLerpSpeed
    );

    this.cameraPosition.lerp(this.targetCameraPosition, lerpFactor);
    this.cameraLookAt.lerp(this.targetLookAt, lerpFactor);

    // 更新相机
    this.camera.position.copy(this.cameraPosition);
    this.camera.lookAt(this.cameraLookAt);
    this.camera.updateMatrixWorld(); // 强制更新世界矩阵

    // 调试：偶尔打印相机状态
    if (Math.random() < 0.01) {
      console.log(`[HelixMode Camera] Position: (${this.camera.position.x.toFixed(2)}, ${this.camera.position.y.toFixed(2)}, ${this.camera.position.z.toFixed(2)}), LookAt: (${this.cameraLookAt.x.toFixed(2)}, ${this.cameraLookAt.y.toFixed(2)}, ${this.cameraLookAt.z.toFixed(2)})`);
    }

    // 粒子轻微旋转
    if (this.particleSystem) {
      this.particleSystem.rotation.y += 0.0005;
    }

    // 发光精灵脉动动画
    if (this.glowSprite && this.glowSprite.visible) {
      const time = Date.now() * 0.001; // 转换为秒
      const pulse = 1.0 + Math.sin(time * 2.0) * 0.15; // 0.85 - 1.15 之间脉动
      this.glowSprite.scale.set(1.5 * pulse, 1.5 * pulse, 1);

      // 轻微旋转
      this.glowSprite.material.rotation = time * 0.5;
    }

    // 更新年份锚点闪烁动画
    this.updateYearAnchorAnimation();

    // 更新季度锚点闪烁动画
    this.updateQuarterAnchorAnimation();

    // 更新月份锚点闪烁动画
    this.updateMonthAnchorAnimation();

    // 更新所有节点的过渡动画
    this.nodes.forEach((entry) => {
      entry.updateTransition();
    });

    // 不调用 controls.update()，因为我们已经禁用了 OrbitControls
    // 完全由我们的代码控制相机位置和朝向
  }

  /**
   * 更新年份锚点的闪烁动画
   */
  private updateYearAnchorAnimation(): void {
    const time = Date.now() * 0.001; // 转换为秒

    this.yearAnchors.forEach((anchor) => {
      const material = anchor.mesh.material as THREE.MeshStandardMaterial;

      // 透明度闪烁（0.4 - 1.0 之间）
      const opacityPulse = 0.7 + Math.sin(time * 3.0) * 0.3;
      material.opacity = opacityPulse;

      // 发光强度闪烁（0.5 - 1.5 之间）
      const emissivePulse = 1.0 + Math.sin(time * 3.0) * 0.5;
      material.emissiveIntensity = emissivePulse;

      // 缩放脉动（更明显）
      const scalePulse = 1.0 + Math.sin(time * 3.0) * 0.2;
      anchor.mesh.scale.setScalar(scalePulse);
    });
  }

  /**
   * 更新季度锚点的闪烁动画
   */
  private updateQuarterAnchorAnimation(): void {
    const time = Date.now() * 0.001;

    this.quarterAnchors.forEach((anchor) => {
      const material = anchor.mesh.material as THREE.MeshStandardMaterial;

      // 透明度闪烁（略小于年份锚点）
      const opacityPulse = 0.6 + Math.sin(time * 2.5) * 0.3;
      material.opacity = opacityPulse;

      // 发光强度闪烁（频率略低）
      const emissivePulse = 0.8 + Math.sin(time * 2.5) * 0.4;
      material.emissiveIntensity = emissivePulse;

      // 缩放脉动
      const scalePulse = 1.0 + Math.sin(time * 2.5) * 0.15;
      anchor.mesh.scale.setScalar(scalePulse);
    });
  }

  /**
   * 更新月份锚点的闪烁动画
   */
  private updateMonthAnchorAnimation(): void {
    const time = Date.now() * 0.001;

    this.monthAnchors.forEach((anchor) => {
      const material = anchor.mesh.material as THREE.MeshStandardMaterial;

      // 透明度闪烁（最小的脉动）
      const opacityPulse = 0.5 + Math.sin(time * 2.0) * 0.25;
      material.opacity = opacityPulse;

      // 发光强度闪烁（频率最低）
      const emissivePulse = 0.6 + Math.sin(time * 2.0) * 0.3;
      material.emissiveIntensity = emissivePulse;

      // 缩放脉动
      const scalePulse = 1.0 + Math.sin(time * 2.0) * 0.1;
      anchor.mesh.scale.setScalar(scalePulse);
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
}
