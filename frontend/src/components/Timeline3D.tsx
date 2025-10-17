import * as THREE from "three";
import { useEffect, useRef, useState } from "react";

import type { TimelineModel } from "../api/client";
import { buildProviderAvatarUrl } from "../api/client";
import { getDefaultCameraPosition, getDefaultFocusAnchor } from "../timeline/core/constants";
import { buildTimelineDataset } from "../timeline/core/dataset";
import { TimelineEventNode } from "../timeline/core/event-node";
import type { ITimelineMode } from "../timeline/modes/ITimelineMode";
import { timelineModeFactory } from "../timeline/modes/ModeFactory";

type Timeline3DProps = {
  models: TimelineModel[];
  mode?: string; // 模式名称，默认 "classic"
};

const CANVAS_HEIGHT = 520;
const focusAnchor = getDefaultFocusAnchor();
const defaultCameraPosition = getDefaultCameraPosition();

// UI 工具函数
const normalisePriceObject = (price: unknown): Record<string, unknown> | null => {
  if (!price) return null;
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
  if (!priceObject) return null;

  const entries: string[] = [];
  const formatEntry = (label: string, value: unknown) => {
    const numeric = Number(value);
    if (!Number.isFinite(numeric) || numeric <= 0) return null;
    const dollarsPerMillion = (numeric * 1_000_000).toFixed(2);
    return `<div>${label}: $${dollarsPerMillion}/M</div>`;
  };

  const promptEntry = formatEntry("Input Token", priceObject.prompt);
  const completionEntry = formatEntry("Output Token", priceObject.completion);
  if (promptEntry) entries.push(promptEntry);
  if (completionEntry) entries.push(completionEntry);
  if (entries.length === 0) return null;

  return `<div class="space-y-1 text-[11px] leading-relaxed text-text-muted">${entries.join("")}</div>`;
};

const escapeAttribute = (value: string) =>
  value
    .replace(/&/g, "&amp;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");

const buildPreviewMarkup = (model: TimelineModel) => {
  const provider = escapeAttribute(model.provider ?? "");
  const avatarUrl = model.avatar_url ? buildProviderAvatarUrl(model.provider) : null;
  const providerInitial = model.provider ? model.provider.trim().charAt(0).toUpperCase() || "?" : "?";

  const avatar = avatarUrl
    ? `<div class="relative flex h-8 w-8 shrink-0 items-center justify-center overflow-hidden rounded-full border border-border-default bg-surface-base text-xs font-semibold text-text-secondary">
        <span class="absolute inset-0 flex items-center justify-center transition-opacity avatar-placeholder">${providerInitial}</span>
        <img
          src="${avatarUrl}"
          alt="${provider}"
          class="absolute inset-0 h-full w-full object-cover opacity-0 transition-opacity duration-200"
          referrerpolicy="no-referrer"
          loading="lazy"
          onload="const placeholder=this.previousElementSibling; if(placeholder){placeholder.style.display='none';} this.style.opacity='1';"
          onerror="this.style.display='none'; const placeholder=this.previousElementSibling; if(placeholder){placeholder.style.display='flex'; placeholder.style.opacity='1';}"
        />
      </div>`
    : `<div class="flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-border-default bg-surface-base text-xs font-semibold text-text-secondary">${providerInitial}</div>`;

  return `
    <div class="flex items-center gap-2">
      ${avatar}
      <div class="min-w-0 flex-1">
        <div class="text-[10px] font-semibold uppercase tracking-wide text-accent-base">${provider}</div>
        <div class="truncate text-[11px] font-medium text-text-primary">${escapeAttribute(model.model_name)}</div>
      </div>
    </div>
  `;
};

const Timeline3D = ({ models, mode = "classic" }: Timeline3DProps) => {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const modeInstanceRef = useRef<ITimelineMode | null>(null);
  const animationFrameIdRef = useRef<number>(0);
  const [currentFocusIndex, setCurrentFocusIndex] = useState(0);

  useEffect(() => {
    const container = containerRef.current;
    if (!container || models.length === 0) {
      if (container) container.innerHTML = "";
      return () => undefined;
    }

    // 取消标记 - 防止过时的异步回调执行
    let cancelled = false;

    // 立即清理旧实例
    if (modeInstanceRef.current) {
      try {
        modeInstanceRef.current.dispose();
      } catch (error) {
        console.warn("Error disposing previous mode instance:", error);
      }
      modeInstanceRef.current = null;
    }

    if (animationFrameIdRef.current) {
      cancelAnimationFrame(animationFrameIdRef.current);
      animationFrameIdRef.current = 0;
    }

    container.innerHTML = "";

    const width = container.clientWidth;
    const height = CANVAS_HEIGHT;

    // ==================== 创建 DOM UI 元素 ====================

    // 悬停提示
    const tooltip = document.createElement("div");
    tooltip.className =
      "pointer-events-none rounded-md border border-border-default bg-surface-overlay px-3 py-2 text-xs text-text-primary shadow-lg shadow-accent transition-colors";
    tooltip.style.position = "absolute";
    tooltip.style.visibility = "hidden";
    tooltip.style.zIndex = "10";
    container.appendChild(tooltip);

    // 焦点主气泡
    const focusPrimaryBubble = document.createElement("div");
    focusPrimaryBubble.className =
      "pointer-events-auto inline-block min-w-[18rem] max-w-3xl rounded-xl border border-border-default bg-surface-overlay px-4 py-3 text-xs text-text-primary shadow-xl shadow-accent transition-colors select-text";
    focusPrimaryBubble.style.position = "absolute";
    focusPrimaryBubble.style.visibility = "hidden";
    focusPrimaryBubble.style.zIndex = "9";
    container.appendChild(focusPrimaryBubble);

    // 创建预览气泡
    const createPreviewBubble = () => {
      const bubble = document.createElement("div");
      bubble.className =
        "pointer-events-none inline-flex min-w-[12rem] max-w-xs items-center gap-2 rounded-lg border border-border-default bg-surface-overlay px-3 py-2 text-[11px] text-text-secondary shadow-lg shadow-accent transition-colors";
      bubble.style.position = "absolute";
      bubble.style.visibility = "hidden";
      bubble.style.zIndex = "8";
      return bubble;
    };

    const focusPrevBubble = createPreviewBubble();
    const focusNextBubble = createPreviewBubble();
    container.appendChild(focusPrevBubble);
    container.appendChild(focusNextBubble);

    // 提示标签
    const createHint = (text: string) => {
      const hint = document.createElement("div");
      hint.className = "pointer-events-none text-[10px] font-semibold uppercase tracking-wide text-text-muted";
      hint.textContent = text;
      hint.style.position = "absolute";
      hint.style.visibility = "hidden";
      hint.style.zIndex = "6";
      return hint;
    };

    const nextHintLabel = createHint("Next...");
    const prevHintLabel = createHint("Prev...");
    container.appendChild(nextHintLabel);
    container.appendChild(prevHintLabel);

    // 价格提示
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

    // SVG 引导线
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

    // ==================== 初始化模式 ====================

    const dataset = buildTimelineDataset(models);
    const sorted = dataset.models;

    // 创建模式实例
    let modeInstance: ITimelineMode;
    try {
      modeInstance = timelineModeFactory.createMode(mode);
      modeInstanceRef.current = modeInstance;
    } catch (error) {
      console.error(`Failed to create timeline mode "${mode}":`, error);
      container.innerHTML = `<div class="flex items-center justify-center h-full text-text-muted">无法加载时间轴模式: ${mode}</div>`;
      return () => undefined;
    }

    // 初始化模式
    const initPromise = modeInstance.init(
      {
        container,
        size: { width, height },
        background: 0xffffff,
        camera: {
          position: defaultCameraPosition.clone(),
          target: focusAnchor.clone(),
        },
      },
      dataset
    );

    // 等待初始化完成
    initPromise
      .then(() => {
        // 检查是否已取消（组件已卸载或models/mode已变化）
        if (cancelled) {
          console.log("Timeline initialization cancelled (effect cleaned up)");
          modeInstance.dispose();
          return;
        }

        const scene = modeInstance.getScene();
        const camera = modeInstance.getCamera();
        const renderer = modeInstance.getRenderer();

        // 创建节点
        const markerGeometry = new THREE.SphereGeometry(0.7, 18, 18);
        const markers: TimelineEventNode[] = [];

        sorted.forEach((model) => {
          const created = new Date(model.created_at).getTime();
          const t = (created - dataset.minTime) / dataset.span;
          const basePosition = dataset.curve.getPointAt(t);
          const node = new TimelineEventNode(model, basePosition, { geometry: markerGeometry });
          markers.push(node);
        });

        // 布局节点
        modeInstance.layoutNodes(markers);

        // ==================== UI 更新逻辑 ====================

        let activeMarker: TimelineEventNode | null = null;
        let previousMarker: TimelineEventNode | null = null;
        let nextMarker: TimelineEventNode | null = null;
        let lastFocusDirection = 0;

        const resetPreviewBubble = (bubble: HTMLDivElement) => {
          bubble.style.visibility = "hidden";
          bubble.innerHTML = "";
        };

        const animateBubble = (bubble: HTMLDivElement, direction: number) => {
          const offset = direction === 0 ? 0 : direction > 0 ? -18 : 18;
          bubble.style.willChange = "opacity, transform";
          bubble.style.transition = "none";
          bubble.style.opacity = "0";
          bubble.style.transform = `translateY(${offset}px) scale(0.92)`;
          void bubble.offsetHeight;
          requestAnimationFrame(() => {
            bubble.style.transition =
              "opacity 260ms cubic-bezier(0.18, 0.72, 0.32, 1), transform 260ms cubic-bezier(0.18, 0.72, 0.32, 1)";
            bubble.style.opacity = "1";
            bubble.style.transform = "translateY(0) scale(1)";
          });
        };

        const renderFocusBubbles = (index: number) => {
          const marker = markers[index];
          if (!marker) {
            activeMarker = null;
            focusPrimaryBubble.style.visibility = "hidden";
            leaderSvg.style.visibility = "hidden";
            hidePriceTooltip();
            previousMarker = null;
            nextMarker = null;
            resetPreviewBubble(focusPrevBubble);
            resetPreviewBubble(focusNextBubble);
            nextHintLabel.style.visibility = "hidden";
            prevHintLabel.style.visibility = "hidden";
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
          const licenseLabel = isOpenSource ? "开源" : "闭源";
          const licenseClass = isOpenSource
            ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/30"
            : "bg-rose-500/10 text-rose-400 border border-rose-500/30";
          const priceTooltipMarkup =
            renderPriceTooltip(model.price) ??
            (!isOpenSource ? '<div class="text-[11px] text-text-muted">暂无价格信息</div>' : null);
          const priceIconMarkup = isOpenSource
            ? ""
            : '<span class="timeline-license-tooltip inline-flex h-5 w-5 items-center justify-center rounded-full border border-amber-400 bg-amber-500/15 text-[10px] font-semibold text-amber-500 shadow-sm cursor-help" role="img" aria-label="Closed-source pricing info">$</span>';
          const licenseChipMarkup = `<span class="timeline-license-chip inline-flex items-center rounded-full px-2.5 py-0.5 text-[10px] font-medium ${licenseClass}">${licenseLabel}</span>`;
          const licenseSectionMarkup = priceIconMarkup
            ? `<span class="inline-flex items-center gap-1">${licenseChipMarkup}${priceIconMarkup}</span>`
            : licenseChipMarkup;
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
                      ${licenseSectionMarkup}
                    </div>
                  </div>
                </div>
              </div>
              <div class="text-[11px] text-text-muted">发布时间：${createdAt}</div>
              ${descriptionMarkup}
            </div>
          `;

          focusPrimaryBubble.style.visibility = "visible";

          // 重置预览气泡
          previousMarker = null;
          nextMarker = null;
          resetPreviewBubble(focusPrevBubble);
          resetPreviewBubble(focusNextBubble);
          nextHintLabel.style.visibility = "hidden";
          prevHintLabel.style.visibility = "hidden";

          // 显示上一个节点预览
          const prevIndex = index + 1;
          if (prevIndex < markers.length) {
            previousMarker = markers[prevIndex];
            focusPrevBubble.innerHTML = buildPreviewMarkup(previousMarker.model);
            focusPrevBubble.style.visibility = "visible";
            animateBubble(focusPrevBubble, lastFocusDirection);
            nextHintLabel.style.visibility = "visible";
          }

          // 显示下一个节点预览
          const nextIndex = index - 1;
          if (nextIndex >= 0) {
            nextMarker = markers[nextIndex];
            focusNextBubble.innerHTML = buildPreviewMarkup(nextMarker.model);
            focusNextBubble.style.visibility = "visible";
            animateBubble(focusNextBubble, -lastFocusDirection);
            prevHintLabel.style.visibility = "visible";
          }

          animateBubble(focusPrimaryBubble, lastFocusDirection);

          // 价格提示交互
          const priceTooltipTarget = focusPrimaryBubble.querySelector<HTMLSpanElement>(".timeline-license-tooltip");
          hidePriceTooltip();

          if (priceTooltipTarget && priceTooltipMarkup) {
            priceTooltipTarget.onpointerenter = null;
            priceTooltipTarget.onpointerleave = null;
            priceTooltipTarget.onpointermove = null;
            priceTooltipTarget.style.cursor = "help";

            const showTooltip = () => {
              priceTooltip.innerHTML = priceTooltipMarkup;
              priceTooltip.style.display = "block";
              priceTooltip.style.visibility = "hidden";
              const containerRect = container.getBoundingClientRect();
              const targetRect = priceTooltipTarget.getBoundingClientRect();
              const tooltipRect = priceTooltip.getBoundingClientRect();
              const horizontalPadding = 8;
              const verticalOffset = 10;
              let left =
                targetRect.left -
                containerRect.left +
                targetRect.width / 2 -
                tooltipRect.width / 2;
              left = THREE.MathUtils.clamp(
                left,
                horizontalPadding,
                containerRect.width - tooltipRect.width - horizontalPadding
              );
              let top = targetRect.top - containerRect.top - tooltipRect.height - verticalOffset;
              if (top < horizontalPadding) {
                top = targetRect.top - containerRect.top + targetRect.height + verticalOffset;
              }
              priceTooltip.style.left = `${left}px`;
              priceTooltip.style.top = `${top}px`;
              priceTooltip.style.visibility = "visible";
            };

            priceTooltipTarget.onpointerenter = showTooltip;
            priceTooltipTarget.onpointerleave = hidePriceTooltip;
            priceTooltipTarget.onpointermove = showTooltip;
          }

          activeMarker = marker;
        };

        // 注册焦点变化回调
        modeInstance.onFocusChanged((index) => {
          setCurrentFocusIndex(index);
          renderFocusBubbles(index);
        });

        // 渲染初始焦点
        renderFocusBubbles(modeInstance.getCurrentFocusIndex());

        // ==================== 事件处理 ====================

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
            const intersect = intersects[0].object as InstanceType<typeof THREE.Mesh>;
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
          if (event.button !== 0) return;
          const bounds = renderer.domElement.getBoundingClientRect();
          pointerDown.set(event.clientX - bounds.left, event.clientY - bounds.top);
          pointerDownTimestamp = performance.now();
        };

        const handlePointerUp = (event: PointerEvent) => {
          if (event.button !== 0) return;
          const now = performance.now();
          const bounds = renderer.domElement.getBoundingClientRect();
          const upX = event.clientX - bounds.left;
          const upY = event.clientY - bounds.top;
          const delta = Math.hypot(upX - pointerDown.x, upY - pointerDown.y);
          if (delta > 6 || now - pointerDownTimestamp > 350) return;

          pointer.x = (upX / bounds.width) * 2 - 1;
          pointer.y = -(upY / bounds.height) * 2 + 1;
          raycaster.setFromCamera(pointer, camera);
          const intersects = raycaster.intersectObjects(markers.map((entry) => entry.mesh));

          if (intersects.length > 0) {
            const mesh = intersects[0].object as InstanceType<typeof THREE.Mesh>;
            const clickedIndex = modeInstance.handleNodeClick(mesh);
            if (clickedIndex !== null) {
              lastFocusDirection = clickedIndex > currentFocusIndex ? 1 : -1;
              modeInstance.setFocus(clickedIndex);
            }
          }
        };

        const handleWheel = (event: WheelEvent) => {
          event.preventDefault();
          const direction = -Math.sign(event.deltaY);
          const currentIndex = modeInstance.getCurrentFocusIndex();
          const nextIndex = modeInstance.handleWheelEvent(direction, currentIndex);

          if (nextIndex !== currentIndex) {
            lastFocusDirection = direction;
            modeInstance.setFocus(nextIndex);
          }
        };

        renderer.domElement.addEventListener("pointermove", handlePointerMove);
        renderer.domElement.addEventListener("pointerleave", handlePointerLeave);
        renderer.domElement.addEventListener("pointerdown", handlePointerDown);
        renderer.domElement.addEventListener("pointerup", handlePointerUp);
        renderer.domElement.addEventListener("wheel", handleWheel, { passive: false });

        const handleResize = () => {
          const newWidth = container.clientWidth;
          modeInstance.onWindowResize(newWidth, height);
          leaderSvg.setAttribute("width", `${newWidth}`);
          leaderSvg.setAttribute("height", `${height}`);
          leaderSvg.setAttribute("viewBox", `0 0 ${newWidth} ${height}`);
        };
        window.addEventListener("resize", handleResize);

        // ==================== 动画循环 ====================

        const focusPosition = new THREE.Vector3();

        const animate = () => {
          // 更新模式
          modeInstance.update(0);

          // 更新气泡位置
          const viewportWidth = renderer.domElement.clientWidth;
          const viewportHeight = renderer.domElement.clientHeight;

          if (activeMarker) {
            const timelineGroup = modeInstance.getScene().children.find(
              (child: InstanceType<typeof THREE.Object3D>) => child.type === "Group"
            ) as InstanceType<typeof THREE.Group> | undefined;

            if (timelineGroup) {
              focusPosition.copy(activeMarker.basePosition).add(timelineGroup.position);
              const projected = focusPosition.clone().project(camera);

              if (projected.z < -1 || projected.z > 1) {
                focusPrimaryBubble.style.visibility = "hidden";
                leaderSvg.style.visibility = "hidden";
                hidePriceTooltip();
                focusPrevBubble.style.visibility = "hidden";
                focusNextBubble.style.visibility = "hidden";
                nextHintLabel.style.visibility = "hidden";
                prevHintLabel.style.visibility = "hidden";
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

                // 更新引导线
                leaderSvg.style.visibility = "visible";
                leaderSvg.setAttribute("width", `${viewportWidth}`);
                leaderSvg.setAttribute("height", `${viewportHeight}`);
                leaderSvg.setAttribute("viewBox", `0 0 ${viewportWidth} ${viewportHeight}`);

                const primaryAnchorX = primaryRect.left;
                const primaryAnchorY = primaryRect.top + primaryRect.height / 2;
                primaryLeader.setAttribute("x1", `${screenX}`);
                primaryLeader.setAttribute("y1", `${screenY}`);
                primaryLeader.setAttribute("x2", `${primaryAnchorX}`);
                primaryLeader.setAttribute("y2", `${primaryAnchorY}`);

                const primaryRight = Math.min(primaryRect.left + primaryRect.width, viewportWidth - padding);

                // 定位上一个气泡
                if (previousMarker) {
                  const prevWidth = focusPrevBubble.offsetWidth || 0;
                  const prevHeight = focusPrevBubble.offsetHeight || 0;
                  let prevLeft = primaryRight - prevWidth;
                  prevLeft = Math.max(padding, prevLeft);
                  const prevRight = prevLeft + prevWidth;
                  if (prevRight > viewportWidth - padding) {
                    prevLeft = viewportWidth - padding - prevWidth;
                  }
                  let prevTop = primaryRect.top - prevHeight - 12;
                  if (prevTop < padding) prevTop = padding;
                  if (prevTop + prevHeight > viewportHeight - padding) {
                    prevTop = viewportHeight - prevHeight - padding;
                  }
                  focusPrevBubble.style.left = `${prevLeft}px`;
                  focusPrevBubble.style.top = `${prevTop}px`;
                  focusPrevBubble.style.visibility = "visible";

                  const hintWidth = nextHintLabel.offsetWidth || 0;
                  const hintHeight = nextHintLabel.offsetHeight || 0;
                  let hintLeft = primaryRight - hintWidth;
                  hintLeft = Math.max(padding, Math.min(hintLeft, viewportWidth - padding - hintWidth));
                  let hintTop = prevTop - hintHeight - 6;
                  if (hintTop < padding) hintTop = padding;
                  nextHintLabel.style.left = `${hintLeft}px`;
                  nextHintLabel.style.top = `${hintTop}px`;
                  nextHintLabel.style.visibility = "visible";
                } else {
                  focusPrevBubble.style.visibility = "hidden";
                  nextHintLabel.style.visibility = "hidden";
                }

                // 定位下一个气泡
                if (nextMarker) {
                  const nextWidth = focusNextBubble.offsetWidth || 0;
                  const nextHeight = focusNextBubble.offsetHeight || 0;
                  let nextLeft = primaryRight - nextWidth;
                  nextLeft = Math.max(padding, nextLeft);
                  const nextRight = nextLeft + nextWidth;
                  if (nextRight > viewportWidth - padding) {
                    nextLeft = viewportWidth - padding - nextWidth;
                  }
                  let nextTop = primaryRect.top + primaryRect.height + 12;
                  if (nextTop + nextHeight > viewportHeight - padding) {
                    nextTop = viewportHeight - nextHeight - padding;
                  }
                  if (nextTop < padding) nextTop = padding;
                  focusNextBubble.style.left = `${nextLeft}px`;
                  focusNextBubble.style.top = `${nextTop}px`;
                  focusNextBubble.style.visibility = "visible";

                  const hintWidth = prevHintLabel.offsetWidth || 0;
                  const hintHeight = prevHintLabel.offsetHeight || 0;
                  let hintLeft = primaryRight - hintWidth;
                  hintLeft = Math.max(padding, Math.min(hintLeft, viewportWidth - padding - hintWidth));
                  let hintTop = nextTop + nextHeight + 4;
                  if (hintTop + hintHeight > viewportHeight - padding) {
                    hintTop = viewportHeight - padding - hintHeight;
                  }
                  prevHintLabel.style.left = `${hintLeft}px`;
                  prevHintLabel.style.top = `${hintTop}px`;
                  prevHintLabel.style.visibility = "visible";
                } else {
                  focusNextBubble.style.visibility = "hidden";
                  prevHintLabel.style.visibility = "hidden";
                }
              }
            }
          } else {
            focusPrimaryBubble.style.visibility = "hidden";
            leaderSvg.style.visibility = "hidden";
            hidePriceTooltip();
            focusPrevBubble.style.visibility = "hidden";
            focusNextBubble.style.visibility = "hidden";
            nextHintLabel.style.visibility = "hidden";
            prevHintLabel.style.visibility = "hidden";
          }

          renderer.render(scene, camera);
          animationFrameIdRef.current = requestAnimationFrame(animate);
        };

        animationFrameIdRef.current = requestAnimationFrame(animate);

        // ==================== 清理函数 ====================

        return () => {
          cancelAnimationFrame(animationFrameIdRef.current);
          window.removeEventListener("resize", handleResize);
          renderer.domElement.removeEventListener("pointermove", handlePointerMove);
          renderer.domElement.removeEventListener("pointerleave", handlePointerLeave);
          renderer.domElement.removeEventListener("pointerdown", handlePointerDown);
          renderer.domElement.removeEventListener("pointerup", handlePointerUp);
          renderer.domElement.removeEventListener("wheel", handleWheel);

          tooltip.remove();
          focusPrimaryBubble.remove();
          focusPrevBubble.remove();
          focusNextBubble.remove();
          nextHintLabel.remove();
          prevHintLabel.remove();
          priceTooltip.remove();
          leaderSvg.remove();

          markerGeometry.dispose();
          markers.forEach((marker) => marker.dispose(scene as any));

          if (modeInstanceRef.current) {
            modeInstanceRef.current.dispose();
            modeInstanceRef.current = null;
          }
        };
      })
      .catch((error) => {
        console.error("Failed to initialize timeline mode:", error);
        container.innerHTML = `<div class="flex items-center justify-center h-full text-text-muted">初始化时间轴失败</div>`;
      });

    // 返回清理函数
    return () => {
      cancelled = true; // 标记为已取消
      if (animationFrameIdRef.current) {
        cancelAnimationFrame(animationFrameIdRef.current);
      }
      if (modeInstanceRef.current) {
        modeInstanceRef.current.dispose();
        modeInstanceRef.current = null;
      }
    };
  }, [models, mode]);

  return <div ref={containerRef} className="relative w-full" style={{ minHeight: CANVAS_HEIGHT }} />;
};

export default Timeline3D;
