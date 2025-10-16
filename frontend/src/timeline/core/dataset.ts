import * as THREE from "three";

import type { TimelineModel } from "../../api/client";
import { getDefaultFocusAnchor } from "./constants";

type CatmullRomCurveInstance = InstanceType<typeof THREE.CatmullRomCurve3>;
type Vector3Instance = InstanceType<typeof THREE.Vector3>;

const BASE_START_ANGLE = -Math.PI * 1.25;
const BASE_END_ANGLE = Math.PI * 1.4;
const BASE_START_RADIUS = 26;
const BASE_END_RADIUS = 6;
const BASE_START_HEIGHT = -16;
const BASE_END_HEIGHT = 14;
const BASE_DEPTH_SHIFT = -28;
const BASE_WAVE_AMPLITUDE = 4.2;
const COUNT_LOWER_BOUND = 12;
const COUNT_UPPER_BOUND = 220;

const remapSampleCount = (count: number) => {
  if (count <= COUNT_LOWER_BOUND) {
    return 0;
  }
  if (count >= COUNT_UPPER_BOUND) {
    return 1;
  }
  return (count - COUNT_LOWER_BOUND) / (COUNT_UPPER_BOUND - COUNT_LOWER_BOUND);
};

export const buildTimelineCurve = (sampleCount: number, anchor: Vector3Instance = getDefaultFocusAnchor()) => {
  const safeCount = Math.max(sampleCount, 1);
  const density = remapSampleCount(safeCount);
  const lengthMultiplier = THREE.MathUtils.lerp(0.72, 2.08, density);
  const angleCenter = (BASE_START_ANGLE + BASE_END_ANGLE) / 2;
  const baseSpan = BASE_END_ANGLE - BASE_START_ANGLE;
  const angleSpan = baseSpan * lengthMultiplier;
  const startAngle = angleCenter - angleSpan / 2;
  const endAngle = angleCenter + angleSpan / 2;

  const radiusScale = THREE.MathUtils.lerp(0.78, 1.18, density);
  const startRadius = BASE_START_RADIUS * radiusScale;
  const endRadius = BASE_END_RADIUS * THREE.MathUtils.lerp(0.9, 1.08, density);

  const heightScale = THREE.MathUtils.lerp(0.84, 1.36, density);
  const startHeight = BASE_START_HEIGHT * heightScale;
  const endHeight = BASE_END_HEIGHT * heightScale;

  const depthScale = THREE.MathUtils.lerp(0.72, 1.5, density);
  const depthShift = BASE_DEPTH_SHIFT * depthScale;

  const waveAmplitude = BASE_WAVE_AMPLITUDE * THREE.MathUtils.lerp(0.7, 1.28, density);

  const segments = Math.max(Math.round(safeCount * THREE.MathUtils.lerp(2, 4.2, density)), 48);
  const points: Vector3Instance[] = [];

  for (let index = 0; index < segments; index += 1) {
    const t = segments > 1 ? index / (segments - 1) : 0;
    const easedRadius = THREE.MathUtils.lerp(startRadius, endRadius, Math.pow(t, 0.88));
    const angle = THREE.MathUtils.lerp(startAngle, endAngle, t);
    const baseHeight = THREE.MathUtils.lerp(startHeight, endHeight, t);
    const wave = Math.sin(t * Math.PI * 1.15) * waveAmplitude * (1 - t * 0.4);
    const x = Math.cos(angle) * easedRadius;
    const z = Math.sin(angle) * easedRadius + depthShift * (1 - t * 0.7);
    const y = baseHeight + wave;
    points.push(new THREE.Vector3(x, y, z));
  }

  const endPoint = points[points.length - 1]?.clone() ?? new THREE.Vector3();
  points.forEach((point) => point.sub(endPoint));
  points.forEach((point) => point.add(anchor));

  return new THREE.CatmullRomCurve3(points, false, "catmullrom", 0.6);
};

export type TimelineDataset = {
  models: TimelineModel[];
  curve: CatmullRomCurveInstance;
  minTime: number;
  maxTime: number;
  span: number;
};

export const buildTimelineDataset = (models: TimelineModel[]): TimelineDataset => {
  const sorted = [...models].sort(
    (a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
  );

  if (sorted.length === 0) {
    const anchor = getDefaultFocusAnchor();
    const curve = new THREE.CatmullRomCurve3(
      [anchor.clone().add(new THREE.Vector3(-4, 0, 0)), anchor.clone(), anchor.clone().add(new THREE.Vector3(4, 0, 0))],
      false,
      "catmullrom",
      0.6
    );
    return {
      models: [],
      curve,
      minTime: 0,
      maxTime: 0,
      span: 1,
    };
  }

  const times = sorted.map((item) => new Date(item.created_at).getTime());
  const minTime = Math.min(...times);
  const maxTime = Math.max(...times);
  const span = Math.max(maxTime - minTime, 1);

  const curve = buildTimelineCurve(sorted.length);

  return {
    models: sorted,
    curve,
    minTime,
    maxTime,
    span,
  };
};
