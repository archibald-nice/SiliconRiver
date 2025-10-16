import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";

import { getDefaultCameraPosition, getDefaultFocusAnchor } from "./constants";

type Vector3Instance = InstanceType<typeof THREE.Vector3>;
type ColorRepresentation = ConstructorParameters<typeof THREE.Color>[0];
type PerspectiveCameraInstance = InstanceType<typeof THREE.PerspectiveCamera>;
type SceneInstance = InstanceType<typeof THREE.Scene>;
type WebGLRendererInstance = InstanceType<typeof THREE.WebGLRenderer>;
type OrbitControlsInstance = InstanceType<typeof OrbitControls>;

export type TimelineSceneCameraOptions = {
  fov?: number;
  near?: number;
  far?: number;
  position?: Vector3Instance;
  target?: Vector3Instance;
};

export type TimelineSceneOptions = {
  container: HTMLElement;
  size: { width: number; height: number };
  background?: ColorRepresentation;
  camera?: TimelineSceneCameraOptions;
};

export class TimelineScene {
  readonly scene: SceneInstance;
  readonly camera: PerspectiveCameraInstance;
  readonly renderer: WebGLRendererInstance;
  readonly controls: OrbitControlsInstance;

  private container: HTMLElement;
  private disposed = false;

  constructor(options: TimelineSceneOptions) {
    const { container, size, background, camera: cameraOptions } = options;
    this.container = container;

    this.scene = new THREE.Scene();
    if (background !== undefined) {
      this.scene.background = new THREE.Color(background);
    }

    this.renderer = new THREE.WebGLRenderer({ antialias: true });
    this.renderer.setPixelRatio(window.devicePixelRatio);
    this.renderer.setSize(size.width, size.height);

    this.camera = new THREE.PerspectiveCamera(
      cameraOptions?.fov ?? 48,
      size.width / size.height,
      cameraOptions?.near ?? 0.1,
      cameraOptions?.far ?? 1000
    );

    const cameraPosition = cameraOptions?.position ?? getDefaultCameraPosition();
    this.camera.position.copy(cameraPosition);

    const focusTarget = cameraOptions?.target ?? getDefaultFocusAnchor();
    this.camera.lookAt(focusTarget);

    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enablePan = false;
    this.controls.enableZoom = false;
    this.controls.enableRotate = true;
    this.controls.minPolarAngle = THREE.MathUtils.degToRad(32);
    this.controls.maxPolarAngle = THREE.MathUtils.degToRad(58);
    this.controls.minAzimuthAngle = THREE.MathUtils.degToRad(-28);
    this.controls.maxAzimuthAngle = THREE.MathUtils.degToRad(6);
    this.controls.target.copy(focusTarget);
    this.controls.update();

    const ambientLight = new THREE.AmbientLight(0xffffff, 0.7);
    const directionalLight = new THREE.DirectionalLight(0xffffff, 0.6);
    directionalLight.position.set(10, 20, 30);
    this.scene.add(ambientLight, directionalLight);

    this.container.appendChild(this.renderer.domElement);
  }

  get domElement(): HTMLCanvasElement {
    return this.renderer.domElement;
  }

  resize(width: number, height: number) {
    if (this.disposed) {
      return;
    }

    this.renderer.setSize(width, height);
    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();
  }

  dispose() {
    if (this.disposed) {
      return;
    }

    this.controls.dispose();
    this.renderer.dispose();
    if (this.renderer.domElement.parentElement === this.container) {
      this.container.removeChild(this.renderer.domElement);
    }
    this.scene.clear();
    this.disposed = true;
  }
}
