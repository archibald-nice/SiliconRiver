import * as THREE from "three";

import type { TimelineModel } from "../../api/client";

type BufferGeometryInstance = InstanceType<typeof THREE.BufferGeometry>;
type MeshInstance = InstanceType<typeof THREE.Mesh>;
type MeshStandardMaterialInstance = InstanceType<typeof THREE.MeshStandardMaterial>;
type Vector3Instance = InstanceType<typeof THREE.Vector3>;
type GroupInstance = InstanceType<typeof THREE.Group>;
type ColorInstance = InstanceType<typeof THREE.Color>;
type ColorRepresentation = ConstructorParameters<typeof THREE.Color>[0];

export type TimelineEventNodeTargetState = {
  scale?: number;
  opacity?: number;
  color?: ColorInstance | ColorRepresentation;
};

export type TimelineEventNodeOptions = {
  geometry: BufferGeometryInstance;
  baseColor?: ColorRepresentation;
  emissive?: ColorRepresentation;
  transparent?: boolean;
  opacity?: number;
  ownsGeometry?: boolean;
};

export class TimelineEventNode {
  readonly model: TimelineModel;
  readonly basePosition: Vector3Instance;
  readonly mesh: MeshInstance;
  readonly material: MeshStandardMaterialInstance;

  private currentScale = 1;
  private targetScale = 1;
  private currentOpacity = 1;
  private targetOpacity = 1;
  private targetColor: ColorInstance;
  private ownsGeometry: boolean;

  constructor(model: TimelineModel, position: Vector3Instance, options: TimelineEventNodeOptions) {
    this.model = model;
    this.basePosition = position.clone();

    const { geometry, baseColor = 0xfacc15, emissive = 0x312e81, transparent = true, opacity = 1, ownsGeometry = false } =
      options;

    this.material = new THREE.MeshStandardMaterial({
      color: baseColor,
      emissive,
      transparent,
      opacity,
    });
    this.mesh = new THREE.Mesh(ownsGeometry ? geometry.clone() : geometry, this.material);
    this.mesh.position.copy(this.basePosition);
    this.mesh.userData.model = model;
    this.mesh.userData.timelineNode = this;

    this.currentOpacity = opacity;
    this.targetOpacity = opacity;
    this.targetScale = 1;
    this.currentScale = 1;
    this.targetColor = new THREE.Color(baseColor);
    this.ownsGeometry = ownsGeometry;
  }

  setMarkerIndex(index: number) {
    this.mesh.userData.markerIndex = index;
  }

  setTargetState(state: TimelineEventNodeTargetState) {
    if (typeof state.scale === "number") {
      this.targetScale = state.scale;
    }
    if (typeof state.opacity === "number") {
      this.targetOpacity = state.opacity;
    }
    if (state.color !== undefined) {
      this.targetColor =
        state.color instanceof THREE.Color ? state.color.clone() : new THREE.Color(state.color as ColorRepresentation);
    }
  }

  updateTransition() {
    this.currentScale = THREE.MathUtils.lerp(this.currentScale, this.targetScale, 0.2);
    this.mesh.scale.setScalar(this.currentScale);

    this.currentOpacity = THREE.MathUtils.lerp(this.currentOpacity, this.targetOpacity, 0.18);
    this.material.opacity = this.currentOpacity;
    this.material.color.lerp(this.targetColor, 0.2);
  }

  attachTo(group: GroupInstance) {
    group.add(this.mesh);
  }

  dispose(group?: GroupInstance) {
    if (group) {
      group.remove(this.mesh);
    }
    this.material.dispose();
    if (this.ownsGeometry) {
      this.mesh.geometry.dispose();
    }
  }
}
