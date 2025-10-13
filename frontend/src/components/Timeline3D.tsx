
import * as THREE from "three";
import { useEffect, useRef } from "react";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";

import type { TimelineModel } from "../api/client";
import { buildProviderAvatarUrl } from "../api/client";

type Timeline3DProps = {
  models: TimelineModel[];
};

const CANVAS_HEIGHT = 520;
const focusAnchor = new THREE.Vector3(6, -3, -8);
const WHEEL_STEP = 1;

const CAMERA_POSITION = new THREE.Vector3(-34, 26, 30);
const CAMERA_LOOK_TARGET = focusAnchor.clone();

const COLOR_BASE = 0xfacc15;
const COLOR_ACTIVE = 0xfb923c;
const COLOR_LINE = 0x1e293b;

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

const normalisePriceObject = (price: unknown): Record<string, unknown> | null => {
  if (!price) {
    return null;
  }
  if (typeof price === "string") {
    try {
      const parsed = JSON.parse(price);
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
        return parsed as Record<string, unknown>;
      }
      return null;
    } catch {
      return null;
    }
  }
  if (typeof price === "object" && !Array.isArray(price)) {
    return price as Record<string, unknown>;
  }
  return null;
};

const renderPriceTooltip = (price: unknown): string | null => {
  const priceObject = normalisePriceObject(price);
  if (!priceObject) {
    return null;
  }
  const entries: string[] = [];
  const formatEntry = (label: string, value: unknown) => {
    const numeric = Number(value);
    if (!Number.isFinite(numeric) || numeric <= 0) {
      return null;
    }
    const dollarsPerMillion = (numeric * 1_000_000).toFixed(2);
    return `<div>${label}: $${dollarsPerMillion}/M</div>`;
  };
  const promptEntry = formatEntry("Input Token", priceObject.prompt);
  const completionEntry = formatEntry("Output Token", priceObject.completion);
  if (promptEntry) {
    entries.push(promptEntry);
  }
  if (completionEntry) {
    entries.push(completionEntry);
  }
  if (entries.length === 0) {
    return null;
  }
  return `<div class="space-y-1 text-[11px] leading-relaxed text-text-muted">${entries.join("")}</div>`;
};

type ThreeMesh = InstanceType<typeof THREE.Mesh>;
type ThreeVector3 = InstanceType<typeof THREE.Vector3>;
type ThreeMeshStandardMaterial = InstanceType<typeof THREE.MeshStandardMaterial>;
type ThreeColor = InstanceType<typeof THREE.Color>;

const toTwoDigits = (value: number) => String(value).padStart(2, "0");

const formatDateLabel = (date: Date) =>
  `${date.getUTCFullYear()}-${toTwoDigits(date.getUTCMonth() + 1)}-${toTwoDigits(date.getUTCDate())}`;

const createLabelSprite = (text: string) => {
  const canvas = document.createElement("canvas");
  const width = 640;
  const height = 256;
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext("2d");
  if (!context) {
    throw new Error("Canvas not supported");
  }

  context.clearRect(0, 0, width, height);
  context.fillStyle = "rgba(255,255,255,0.9)";
  const barHeight = 112;
  const radius = 48;

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
};

const remapSampleCount = (count: number) => {
  if (count <= COUNT_LOWER_BOUND) {
    return 0;
  }
  if (count >= COUNT_UPPER_BOUND) {
    return 1;
  }
  return (count - COUNT_LOWER_BOUND) / (COUNT_UPPER_BOUND - COUNT_LOWER_BOUND);
};

const buildTimelineCurve = (sampleCount: number) => {
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
  const points: ThreeVector3[] = [];

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
  points.forEach((point) => point.add(focusAnchor));

  return new THREE.CatmullRomCurve3(points, false, "catmullrom", 0.6);
};

const Timeline3D = ({ models }: Timeline3DProps) => {
  const containerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container || models.length === 0) {
      if (container) {
        container.innerHTML = "";
      }
      return () => undefined;
    }

    container.innerHTML = "";

    const width = container.clientWidth;
    const height = CANVAS_HEIGHT;

    const tooltip = document.createElement("div");
    tooltip.className =
      "pointer-events-none rounded-md border border-border-default bg-surface-overlay px-3 py-2 text-xs text-text-primary shadow-lg shadow-accent transition-colors";
    tooltip.style.position = "absolute";
    tooltip.style.visibility = "hidden";
    tooltip.style.zIndex = "10";
    container.appendChild(tooltip);

    const focusPrimaryBubble = document.createElement("div");
    focusPrimaryBubble.className =
      "pointer-events-auto inline-block min-w-[18rem] max-w-3xl rounded-xl border border-border-default bg-surface-overlay px-4 py-3 text-xs text-text-primary shadow-xl shadow-accent transition-colors select-text";
    focusPrimaryBubble.style.position = "absolute";
    focusPrimaryBubble.style.visibility = "hidden";
    focusPrimaryBubble.style.zIndex = "9";
    container.appendChild(focusPrimaryBubble);

    const priceTooltip = document.createElement("div");
    priceTooltip.className =
      "pointer-events-none max-w-xs rounded-lg border border-border-default bg-surface-overlay px-3 py-2 text-[11px] text-text-primary shadow-lg shadow-accent transition-opacity";
    priceTooltip.style.position = "absolute";
    priceTooltip.style.visibility = "hidden";
    priceTooltip.style.zIndex = "11";
    container.appendChild(priceTooltip);

    const hidePriceTooltip = () => {
      priceTooltip.style.visibility = "hidden";
      priceTooltip.style.display = "none";
    };

    hidePriceTooltip();

    const leaderSvg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    leaderSvg.setAttribute("width", `${width}`);
    leaderSvg.setAttribute("height", `${height}`);
    leaderSvg.setAttribute("viewBox", `0 0 ${width} ${height}`);
    leaderSvg.style.position = "absolute";
    leaderSvg.style.top = "0";
    leaderSvg.style.left = "0";
    leaderSvg.style.pointerEvents = "none";
    leaderSvg.style.visibility = "hidden";
    container.appendChild(leaderSvg);

    const primaryLeader = document.createElementNS("http://www.w3.org/2000/svg", "line");
    primaryLeader.setAttribute("stroke", "#94a3b8");
    primaryLeader.setAttribute("stroke-width", "1.6");
    primaryLeader.setAttribute("stroke-linecap", "round");
    primaryLeader.setAttribute("stroke-opacity", "0.85");
    leaderSvg.appendChild(primaryLeader);


    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0xffffff);

    const camera = new THREE.PerspectiveCamera(48, width / height, 0.1, 1000);
    camera.position.copy(CAMERA_POSITION);
    camera.lookAt(CAMERA_LOOK_TARGET);

    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setSize(width, height);
    renderer.setPixelRatio(window.devicePixelRatio);
    container.appendChild(renderer.domElement);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enablePan = false;
    controls.enableZoom = false;
    controls.enableRotate = true;
    controls.minPolarAngle = THREE.MathUtils.degToRad(32);
    controls.maxPolarAngle = THREE.MathUtils.degToRad(58);
    controls.minAzimuthAngle = THREE.MathUtils.degToRad(-28);
    controls.maxAzimuthAngle = THREE.MathUtils.degToRad(6);
    controls.target.copy(CAMERA_LOOK_TARGET);
    controls.update();

    const ambientLight = new THREE.AmbientLight(0xffffff, 0.7);
    const directionalLight = new THREE.DirectionalLight(0xffffff, 0.6);
    directionalLight.position.set(10, 20, 30);
    scene.add(ambientLight, directionalLight);

    const sorted = [...models].sort(
      (a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
    );
    const times = sorted.map((item) => new Date(item.created_at).getTime());
    const minTime = Math.min(...times);
    const maxTime = Math.max(...times);
    const span = Math.max(maxTime - minTime, 1);

    const baseCurve = buildTimelineCurve(sorted.length);
    const tubeGeometry = new THREE.TubeGeometry(baseCurve, 420, 0.28, 16, false);
    const tubeMaterial = new THREE.MeshStandardMaterial({ color: COLOR_LINE, emissive: 0x0f172a });
    const tubeMesh = new THREE.Mesh(tubeGeometry, tubeMaterial);

    const timelineGroup = new THREE.Group();
    timelineGroup.add(tubeMesh);
    scene.add(timelineGroup);

    const markerGeometry = new THREE.SphereGeometry(0.7, 18, 18);
    type MarkerEntry = {
      mesh: ThreeMesh;
      basePosition: ThreeVector3;
      model: TimelineModel;
      material: ThreeMeshStandardMaterial;
      currentScale: number;
      targetScale: number;
      currentOpacity: number;
      targetOpacity: number;
      targetColor: ThreeColor;
    };
    const markers: MarkerEntry[] = [];

    sorted.forEach((model) => {
      const created = new Date(model.created_at).getTime();
      const t = (created - minTime) / span;
      const basePosition = baseCurve.getPointAt(t);
      const material = new THREE.MeshStandardMaterial({
        color: COLOR_BASE,
        emissive: 0x312e81,
        transparent: true,
        opacity: 1,
      });
      const mesh = new THREE.Mesh(markerGeometry.clone(), material);
      mesh.position.copy(basePosition);
      mesh.userData = { model };
      timelineGroup.add(mesh);
      markers.push({
        mesh,
        basePosition,
        model,
        material,
        currentScale: 1,
        targetScale: 1,
        currentOpacity: 1,
        targetOpacity: 1,
        targetColor: new THREE.Color(COLOR_BASE),
      });
      mesh.userData.markerIndex = markers.length - 1;
    });

    const focusPosition = new THREE.Vector3();
    let activeMarker: MarkerEntry | null = null;

    const escapeAttribute = (value: string) =>
      value.replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/'/g, "&#39;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

    const renderFocusBubbles = (marker: MarkerEntry | null) => {
      if (!marker) {
        activeMarker = null;
        focusPrimaryBubble.style.visibility = "hidden";
        leaderSvg.style.visibility = "hidden";
        hidePriceTooltip();
        return;
      }
      const { model } = marker;
      const createdAt = new Date(model.created_at).toLocaleString();
      const description = model.description ? model.description.slice(0, 120) : "";
      const providerInitial = model.provider ? model.provider.trim().charAt(0).toUpperCase() || "?" : "?";
      const safeProviderAttr = escapeAttribute(model.provider ?? "");
      const avatarUrl = model.avatar_url ? buildProviderAvatarUrl(model.provider) : null;
      const avatarMarkup = avatarUrl
        ? `<div class="relative flex h-10 w-10 shrink-0 items-center justify-center overflow-hidden rounded-full border border-border-default bg-surface-base text-sm font-semibold text-text-secondary">
            <span class="absolute inset-0 flex items-center justify-center transition-opacity avatar-placeholder">${providerInitial}</span>
            <img
              src="${avatarUrl}"
              alt="${safeProviderAttr}"
              class="absolute inset-0 h-full w-full object-cover opacity-0 transition-opacity duration-200"
              referrerpolicy="no-referrer"
              loading="lazy"
              onload="const placeholder=this.previousElementSibling; if(placeholder){placeholder.style.display='none';} this.style.opacity='1';"
              onerror="this.style.display='none'; const placeholder=this.previousElementSibling; if(placeholder){placeholder.style.display='flex'; placeholder.style.opacity='1';}"
            />
           </div>`
        : `<div class="flex h-10 w-10 shrink-0 items-center justify-center rounded-full border border-border-default bg-surface-base text-sm font-semibold text-text-secondary">${providerInitial}</div>`;
      const isOpenSource = model.is_open_source !== false;
      const licenseLabel = isOpenSource ? "\u5f00\u6e90" : "\u95ed\u6e90";
      const licenseClass = isOpenSource
        ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/30"
        : "bg-rose-500/10 text-rose-400 border border-rose-500/30";
      const priceTooltipMarkup =
        renderPriceTooltip(model.price) ??
        (!isOpenSource ? '<div class="text-[11px] text-text-muted">暂无价格信息</div>' : null);
      const descriptionMarkup = description
        ? `<div class="w-full text-[11px] leading-relaxed text-text-muted break-words whitespace-normal">${description}</div>`
        : "";
      focusPrimaryBubble.innerHTML = `
        <div class="inline-flex flex-col items-stretch gap-3">
          <div class="w-full rounded-lg bg-slate-100 p-3">
            <div class="flex items-start gap-3">
              ${avatarMarkup}
              <div class="min-w-0 flex-1">
                <div class="text-[11px] font-semibold uppercase tracking-wide text-accent-base">${model.provider}</div>
                <div class="mt-1 flex items-center gap-2">
                  <div class="flex-shrink-0 text-[13px] font-medium text-text-secondary whitespace-nowrap">${model.model_name}</div>
                  <span class="timeline-license-chip inline-flex items-center rounded-full px-2.5 py-0.5 text-[10px] font-medium ${licenseClass}">${licenseLabel}</span>
                </div>
              </div>
            </div>
          </div>
          <div class="text-[11px] text-text-muted">&#x53D1;&#x5E03;&#x65F6;&#x95F4;&#xFF1A;${createdAt}</div>
          ${descriptionMarkup}
        </div>
      `;
      focusPrimaryBubble.style.visibility = "visible";

      const licenseChip = focusPrimaryBubble.querySelector<HTMLSpanElement>(".timeline-license-chip");
      hidePriceTooltip();
      if (licenseChip) {
        licenseChip.onpointerenter = null;
        licenseChip.onpointerleave = null;
        licenseChip.onpointermove = null;
        if (priceTooltipMarkup) {
          licenseChip.style.cursor = "help";
          const showTooltip = () => {
            priceTooltip.innerHTML = priceTooltipMarkup;
            priceTooltip.style.display = "block";
            priceTooltip.style.visibility = "hidden";
            const containerRect = container.getBoundingClientRect();
            const chipRect = licenseChip.getBoundingClientRect();
            const tooltipRect = priceTooltip.getBoundingClientRect();
            const horizontalPadding = 8;
            const verticalOffset = 10;
            let left =
              chipRect.left -
              containerRect.left +
              chipRect.width / 2 -
              tooltipRect.width / 2;
            left = THREE.MathUtils.clamp(
              left,
              horizontalPadding,
              containerRect.width - tooltipRect.width - horizontalPadding,
            );
            let top = chipRect.top - containerRect.top - tooltipRect.height - verticalOffset;
            if (top < horizontalPadding) {
              top = chipRect.top - containerRect.top + chipRect.height + verticalOffset;
            }
            priceTooltip.style.left = `${left}px`;
            priceTooltip.style.top = `${top}px`;
            priceTooltip.style.visibility = "visible";
          };
          const handlePointerEnter = () => {
            showTooltip();
          };
          const handlePointerLeave = () => {
            hidePriceTooltip();
          };
          licenseChip.onpointerenter = handlePointerEnter;
          licenseChip.onpointerleave = handlePointerLeave;
          licenseChip.onpointermove = handlePointerEnter;
        } else {
          licenseChip.style.removeProperty("cursor");
        }
      }

      activeMarker = marker;
    };

    const curveSamples = baseCurve.getPoints(Math.max(Math.round(sorted.length * 3.2), 160));
    let sumX = 0;
    let sumZ = 0;
    let minY = Number.POSITIVE_INFINITY;
    let maxY = Number.NEGATIVE_INFINITY;
    curveSamples.forEach((sample) => {
      sumX += sample.x;
      sumZ += sample.z;
      if (sample.y < minY) {
        minY = sample.y;
      }
      if (sample.y > maxY) {
        maxY = sample.y;
      }
    });
    const hasSamples = curveSamples.length > 0;
    const axisCenterX = hasSamples ? sumX / curveSamples.length : focusAnchor.x;
    const axisCenterZ = hasSamples ? sumZ / curveSamples.length : focusAnchor.z;
    if (!Number.isFinite(minY)) {
      minY = focusAnchor.y - 3;
    }
    if (!Number.isFinite(maxY)) {
      maxY = focusAnchor.y + 3;
    }
    if (maxY - minY < 1) {
      maxY = minY + 6;
    }

    const axisGroup = new THREE.Group();
    const axisMaterial = new THREE.LineBasicMaterial({ color: 0x475569 });
    const arrowMaterial = new THREE.MeshBasicMaterial({ color: 0x475569 });
    const arrowGeometry = new THREE.ConeGeometry(0.38, 1.2, 12);
    arrowGeometry.translate(0, -0.6, 0);

    const axisStart = new THREE.Vector3(axisCenterX, minY - 2.4, axisCenterZ);
    const axisEnd = new THREE.Vector3(axisCenterX, maxY + 2.4, axisCenterZ);
    const axisGeometry = new THREE.BufferGeometry().setFromPoints([axisStart, axisEnd]);
    axisGroup.add(new THREE.Line(axisGeometry, axisMaterial));

    const axisDirection = axisEnd.clone().sub(axisStart).normalize();
    const arrowHead = new THREE.Mesh(arrowGeometry, arrowMaterial);
    arrowHead.position.copy(axisEnd);
    arrowHead.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), axisDirection);
    axisGroup.add(arrowHead);

    const axisVector = axisEnd.clone().sub(axisStart);
    const axisLength = axisVector.length();
    const tickCount = Math.min(8, Math.max(sorted.length, 2));

    for (let i = 0; i < tickCount; i += 1) {
      const fraction = i / Math.max(tickCount - 1, 1);
      const axisPoint = axisStart.clone().add(axisDirection.clone().multiplyScalar(axisLength * fraction));
      const curvePoint = baseCurve.getPointAt(fraction);
      const radial = curvePoint.clone().sub(axisPoint);
      if (radial.lengthSq() < 1e-5) {
        radial.set(1.4, 0, 0);
      }
      const radialLength = THREE.MathUtils.clamp(radial.length() * 0.68, 1.2, 4.2);
      radial.setLength(radialLength);

      const tickOuter = axisPoint.clone().add(radial);
      const tickGeometry = new THREE.BufferGeometry().setFromPoints([axisPoint, tickOuter]);
      axisGroup.add(new THREE.Line(tickGeometry, axisMaterial));

      const labelDate = new Date(minTime + span * fraction);
      const sprite = createLabelSprite(formatDateLabel(labelDate));
      const labelPosition = tickOuter.clone().add(radial.clone().setLength(0.6)).add(new THREE.Vector3(0, 0.9, 0));
      sprite.position.copy(labelPosition);
      axisGroup.add(sprite);
    }
    timelineGroup.add(axisGroup);

    let highlightIndex = markers.length - 1;
    let currentTimelineOffset = timelineGroup.position.clone();
    let targetTimelineOffset = timelineGroup.position.clone();
    const activeColor = new THREE.Color(COLOR_ACTIVE);
    const baseColor = new THREE.Color(COLOR_BASE);
    const cameraFocus = CAMERA_LOOK_TARGET.clone();
    let targetCameraFocus = CAMERA_LOOK_TARGET.clone();

    const focusMarkerAt = (index: number) => {
      if (!markers.length) {
        return;
      }
      const clamped = THREE.MathUtils.clamp(index, 0, markers.length - 1);
      if (clamped !== highlightIndex) {
        highlightIndex = clamped;
      }
      applyFocus();
    };

    const focusMarkerMesh = (mesh: ThreeMesh | null) => {
      if (!mesh) {
        return;
      }
      const index =
        typeof mesh.userData.markerIndex === "number"
          ? mesh.userData.markerIndex
          : markers.findIndex((entry) => entry.mesh === mesh);
      if (index >= 0) {
        focusMarkerAt(index);
      }
    };

    const applyFocus = () => {
      if (!markers.length) {
        renderFocusBubbles(null);
        return;
      }
      highlightIndex = Math.max(0, Math.min(highlightIndex, markers.length - 1));
      const targetMarker = markers[highlightIndex];
      const offset = focusAnchor.clone().sub(targetMarker.basePosition);
      targetTimelineOffset = offset;
      targetCameraFocus = focusAnchor.clone();
      renderFocusBubbles(targetMarker);

      markers.forEach((entry, index) => {
        if (index === highlightIndex) {
          entry.targetScale = 1.6;
          entry.targetOpacity = 1;
          entry.targetColor = activeColor.clone();
          return;
        }

        const distance = index - highlightIndex;
        if (distance < 0) {
          const backward = Math.abs(distance);
          entry.targetScale = backward === 1 ? 0.95 : backward === 2 ? 0.8 : 0.7;
          entry.targetOpacity = backward === 1 ? 0.55 : backward === 2 ? 0.4 : 0.3;
          entry.targetColor = baseColor.clone();
        } else {
          entry.targetScale = distance === 1 ? 1.15 : distance === 2 ? 1.05 : 1.0;
          entry.targetOpacity = distance === 1 ? 0.8 : distance === 2 ? 0.6 : 0.45;
          entry.targetColor = baseColor.clone();
        }
      });
    };

    applyFocus();

    const raycaster = new THREE.Raycaster();
    const pointer = new THREE.Vector2();
    const pointerDown = new THREE.Vector2();
    let pointerDownTimestamp = 0;

    const handlePointerMove = (event: PointerEvent) => {
      const bounds = renderer.domElement.getBoundingClientRect();
      pointer.x = ((event.clientX - bounds.left) / bounds.width) * 2 - 1;
      pointer.y = -((event.clientY - bounds.top) / bounds.height) * 2 + 1;

      raycaster.setFromCamera(pointer, camera);
      const intersects = raycaster.intersectObjects(markers.map((entry) => entry.mesh));

      tooltip.style.visibility = "hidden";
      if (intersects.length > 0) {
        const intersect = intersects[0].object as ThreeMesh;
        const model = intersect.userData.model as TimelineModel | undefined;
        if (model) {
          tooltip.innerHTML = `
            <div class="font-semibold text-accent-base">${model.provider}</div>
            <div class="text-sm text-text-secondary">${model.model_name}</div>
            <div class="mt-1 text-xs text-text-muted">${new Date(model.created_at).toLocaleString()}</div>
          `;
          const { clientX, clientY } = event;
          tooltip.style.left = `${clientX - bounds.left + 14}px`;
          tooltip.style.top = `${clientY - bounds.top + 14}px`;
          tooltip.style.visibility = "visible";
        }
      }
    };

    const handlePointerLeave = () => {
      tooltip.style.visibility = "hidden";
    };

    const handlePointerDown = (event: PointerEvent) => {
      if (event.button !== 0) {
        return;
      }
      const bounds = renderer.domElement.getBoundingClientRect();
      pointerDown.set(event.clientX - bounds.left, event.clientY - bounds.top);
      pointerDownTimestamp = performance.now();
    };

    const handlePointerUp = (event: PointerEvent) => {
      if (event.button !== 0) {
        return;
      }
      const now = performance.now();
      const bounds = renderer.domElement.getBoundingClientRect();
      const upX = event.clientX - bounds.left;
      const upY = event.clientY - bounds.top;
      const delta = Math.hypot(upX - pointerDown.x, upY - pointerDown.y);
      if (delta > 6 || now - pointerDownTimestamp > 350) {
        return;
      }
      pointer.x = (upX / bounds.width) * 2 - 1;
      pointer.y = -(upY / bounds.height) * 2 + 1;
      raycaster.setFromCamera(pointer, camera);
      const intersects = raycaster.intersectObjects(markers.map((entry) => entry.mesh));
      if (intersects.length > 0) {
        focusMarkerMesh(intersects[0].object as ThreeMesh);
      }
    };

    renderer.domElement.addEventListener("pointermove", handlePointerMove);
    renderer.domElement.addEventListener("pointerleave", handlePointerLeave);
    renderer.domElement.addEventListener("pointerdown", handlePointerDown);
    renderer.domElement.addEventListener("pointerup", handlePointerUp);

    const handleWheel = (event: WheelEvent) => {
      event.preventDefault();
      const direction = Math.sign(event.deltaY);
      const next = THREE.MathUtils.clamp(highlightIndex + direction * WHEEL_STEP, 0, markers.length - 1);
      if (next !== highlightIndex) {
        highlightIndex = next;
        applyFocus();
      }
    };
    renderer.domElement.addEventListener("wheel", handleWheel, { passive: false });

    const handleResize = () => {
      const newWidth = container.clientWidth;
      camera.aspect = newWidth / height;
      camera.updateProjectionMatrix();
      renderer.setSize(newWidth, height);
      leaderSvg.setAttribute("width", `${newWidth}`);
      leaderSvg.setAttribute("height", `${height}`);
      leaderSvg.setAttribute("viewBox", `0 0 ${newWidth} ${height}`);
    };
    window.addEventListener("resize", handleResize);

    let animationId = 0;
    const animate = () => {
      currentTimelineOffset.lerp(targetTimelineOffset, 0.12);
      timelineGroup.position.copy(currentTimelineOffset);

      cameraFocus.lerp(targetCameraFocus, 0.08);
      controls.target.copy(cameraFocus);
      controls.update();

      markers.forEach((entry) => {
        entry.currentScale = THREE.MathUtils.lerp(entry.currentScale, entry.targetScale, 0.2);
        entry.mesh.scale.setScalar(entry.currentScale);

        entry.currentOpacity = THREE.MathUtils.lerp(entry.currentOpacity, entry.targetOpacity, 0.18);
        entry.material.opacity = entry.currentOpacity;
        entry.material.color.lerp(entry.targetColor, 0.2);
      });

      const viewportWidth = renderer.domElement.clientWidth;
      const viewportHeight = renderer.domElement.clientHeight;
      if (activeMarker) {
        focusPosition.copy(activeMarker.basePosition).add(timelineGroup.position);
        const projected = focusPosition.clone().project(camera);
        if (projected.z < -1 || projected.z > 1) {
          focusPrimaryBubble.style.visibility = "hidden";
          leaderSvg.style.visibility = "hidden";
          hidePriceTooltip();
        } else {
          const screenX = (projected.x * 0.5 + 0.5) * viewportWidth;
          const screenY = (-projected.y * 0.5 + 0.5) * viewportHeight;

          const padding = 12;
          const primaryOffsets = { x: 78, y: -170 };

          const positionBubble = (bubble: HTMLDivElement, offsetX: number, offsetY: number) => {
            const widthPx = bubble.offsetWidth || 0;
            const heightPx = bubble.offsetHeight || 0;
            let left = screenX + offsetX;
            let top = screenY + offsetY;
            left = THREE.MathUtils.clamp(left, padding, viewportWidth - widthPx - padding);
            top = THREE.MathUtils.clamp(top, padding, viewportHeight - heightPx - padding);
            bubble.style.left = `${left}px`;
            bubble.style.top = `${top}px`;
            return { left, top, width: widthPx, height: heightPx };
          };

          const primaryRect = positionBubble(focusPrimaryBubble, primaryOffsets.x, primaryOffsets.y);

          focusPrimaryBubble.style.visibility = "visible";

          const markerX = screenX;
          const markerY = screenY;
          leaderSvg.style.visibility = "visible";
          leaderSvg.setAttribute("width", `${viewportWidth}`);
          leaderSvg.setAttribute("height", `${viewportHeight}`);
          leaderSvg.setAttribute("viewBox", `0 0 ${viewportWidth} ${viewportHeight}`);

          const primaryAnchorX = primaryRect.left;
          const primaryAnchorY = primaryRect.top + primaryRect.height / 2;
          primaryLeader.setAttribute("x1", `${markerX}`);
          primaryLeader.setAttribute("y1", `${markerY}`);
          primaryLeader.setAttribute("x2", `${primaryAnchorX}`);
          primaryLeader.setAttribute("y2", `${primaryAnchorY}`);
        }
      } else {
        focusPrimaryBubble.style.visibility = "hidden";
        leaderSvg.style.visibility = "hidden";
        hidePriceTooltip();
      }

      renderer.render(scene, camera);
      animationId = requestAnimationFrame(animate);
    };
    animationId = requestAnimationFrame(animate);

    return () => {
      cancelAnimationFrame(animationId);
      window.removeEventListener("resize", handleResize);
      renderer.domElement.removeEventListener("pointermove", handlePointerMove);
      renderer.domElement.removeEventListener("pointerleave", handlePointerLeave);
      renderer.domElement.removeEventListener("pointerdown", handlePointerDown);
      renderer.domElement.removeEventListener("pointerup", handlePointerUp);
      renderer.domElement.removeEventListener("wheel", handleWheel);
      tooltip.remove();
      focusPrimaryBubble.remove();
      priceTooltip.remove();
      leaderSvg.remove();
      controls.dispose();
      tubeGeometry.dispose();
      tubeMaterial.dispose();
      markerGeometry.dispose();
      markers.forEach(({ mesh, material }) => {
        material.dispose();
        timelineGroup.remove(mesh);
      });
      arrowGeometry.dispose();
      arrowMaterial.dispose();
      axisMaterial.dispose();
      axisGroup.clear();
      scene.remove(timelineGroup);
      renderer.dispose();
      renderer.domElement.remove();
    };
  }, [models]);

  return <div ref={containerRef} className="relative w-full" style={{ minHeight: CANVAS_HEIGHT }} />;
};

export default Timeline3D;

