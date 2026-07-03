import "./styles.css";
import { getBlock } from "./blocks";
import { installDebugHooks } from "./debug";
import { clampZoom, pointToCell, screenToWorld } from "./grid";
import { applyPinchZoom } from "./interaction";
import { renderCity } from "./render";
import {
  createInitialState,
  isBlockTool,
  isVehicleTool,
  placeSelectedBlock,
  placeSelectedVehicle,
  selectCell,
  updateMood,
  updateState,
} from "./state";
import { renderUi, setupUi, showBusRoutePicker, showCarRoutePicker, showOverpassDirectionPicker } from "./ui";

const canvas = document.querySelector<HTMLCanvasElement>("#city-canvas");
if (!canvas) throw new Error("Missing #city-canvas");
const cityCanvas = canvas;

const state = createInitialState();
updateMood(state);

function resizeCanvas(): void {
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const rect = cityCanvas.getBoundingClientRect();
  cityCanvas.width = Math.floor(rect.width * dpr);
  cityCanvas.height = Math.floor(rect.height * dpr);
}

function canvasPointToWorld(event: PointerEvent): { x: number; y: number } {
  const rect = cityCanvas.getBoundingClientRect();
  return screenToWorld({ x: event.clientX - rect.left, y: event.clientY - rect.top }, state.camera, rect.width, rect.height);
}

let dragStart: { x: number; y: number; cameraX: number; cameraY: number } | null = null;
let dragged = false;
const activePointers = new Map<number, { x: number; y: number }>();
let pinchStart: { center: { x: number; y: number }; distance: number; camera: typeof state.camera } | null = null;

let last = performance.now();
let manualClock = false;
function frame(now: number): void {
  const deltaMs = Math.min(50, now - last);
  last = now;
  if (!manualClock) updateState(state, deltaMs);
  renderCity(cityCanvas, state);
  requestAnimationFrame(frame);
}

setupUi(state, () => {
  renderUi(state);
  renderCity(cityCanvas, state);
});
cityCanvas.addEventListener("pointerdown", (event) => {
  event.preventDefault();
  try {
    cityCanvas.setPointerCapture(event.pointerId);
  } catch {
    // Some mobile/simulated touch events do not expose an active pointer capture target.
  }
  activePointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
  dragged = false;
  if (activePointers.size >= 2) {
    pinchStart = createPinchStart();
    dragStart = null;
    dragged = true;
    return;
  }
  dragStart = { x: event.clientX, y: event.clientY, cameraX: state.camera.x, cameraY: state.camera.y };
});

cityCanvas.addEventListener("pointermove", (event) => {
  event.preventDefault();
  if (activePointers.has(event.pointerId)) activePointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
  if (pinchStart && activePointers.size >= 2) {
    const current = pointerPairMetrics();
    const rect = cityCanvas.getBoundingClientRect();
    state.camera = applyPinchZoom({
      camera: pinchStart.camera,
      viewport: { width: rect.width, height: rect.height },
      startCenter: canvasRelativePoint(pinchStart.center),
      startDistance: pinchStart.distance,
      currentCenter: canvasRelativePoint(current.center),
      currentDistance: current.distance,
    });
    dragged = true;
    renderCity(cityCanvas, state);
    return;
  }
  if (!dragStart) return;
  const dx = event.clientX - dragStart.x;
  const dy = event.clientY - dragStart.y;
  if (Math.hypot(dx, dy) > 6) dragged = true;
  if (dragged) {
    state.camera.x = dragStart.cameraX - dx / state.camera.zoom;
    state.camera.y = dragStart.cameraY - dy / state.camera.zoom;
    renderCity(cityCanvas, state);
  }
});

cityCanvas.addEventListener("pointerup", (event) => {
  event.preventDefault();
  if (cityCanvas.hasPointerCapture(event.pointerId)) cityCanvas.releasePointerCapture(event.pointerId);
  activePointers.delete(event.pointerId);
  const wasPinching = !!pinchStart;
  if (activePointers.size < 2) pinchStart = null;
  if (activePointers.size === 1) {
    const pointer = [...activePointers.values()][0];
    dragStart = { x: pointer.x, y: pointer.y, cameraX: state.camera.x, cameraY: state.camera.y };
    dragged = true;
  }
  const shouldPlace = !dragged;
  dragStart = null;
  if (!shouldPlace || wasPinching) return;
  const cell = pointToCell(state.grid, canvasPointToWorld(event));
  selectCell(state, cell);
  if (cell && state.selectedTool === "overpass" && getBlock(state.blocks, cell)?.type === "overpass") {
    renderUi(state);
    renderCity(cityCanvas, state);
    return;
  }
  if (cell && state.selectedTool === "overpass") {
    const opened = showOverpassDirectionPicker(state, cell, () => {
      renderUi(state);
      renderCity(cityCanvas, state);
    });
    if (opened) {
      renderCity(cityCanvas, state);
      return;
    }
  }
  if (cell && isBlockTool(state.selectedTool)) {
    placeSelectedBlock(state, cell);
    selectCell(state, cell);
  }
  if (cell && state.selectedTool === "sedan") {
    const opened = showCarRoutePicker(state, cell, () => {
      renderUi(state);
      renderCity(cityCanvas, state);
    });
    if (opened) {
      renderCity(cityCanvas, state);
      return;
    }
  } else if (cell && state.selectedTool === "bus") {
    const opened = showBusRoutePicker(state, cell, () => {
      renderUi(state);
      renderCity(cityCanvas, state);
    });
    if (opened) {
      renderCity(cityCanvas, state);
      return;
    }
  } else if (cell && isVehicleTool(state.selectedTool)) {
    placeSelectedVehicle(state, cell);
  }
  renderUi(state);
  renderCity(cityCanvas, state);
});

cityCanvas.addEventListener("pointercancel", (event) => {
  activePointers.delete(event.pointerId);
  pinchStart = null;
  dragStart = null;
  dragged = false;
});

cityCanvas.addEventListener("wheel", (event) => {
  event.preventDefault();
  const rect = cityCanvas.getBoundingClientRect();
  const before = screenToWorld({ x: event.clientX - rect.left, y: event.clientY - rect.top }, state.camera, rect.width, rect.height);
  const factor = event.deltaY > 0 ? 0.9 : 1.1;
  state.camera.zoom = clampZoom(state.camera.zoom * factor);
  const after = screenToWorld({ x: event.clientX - rect.left, y: event.clientY - rect.top }, state.camera, rect.width, rect.height);
  state.camera.x += before.x - after.x;
  state.camera.y += before.y - after.y;
  renderCity(cityCanvas, state);
});
installDebugHooks(state, cityCanvas, () => {
  manualClock = true;
  last = performance.now();
});
window.addEventListener("resize", resizeCanvas);
resizeCanvas();
requestAnimationFrame(frame);

function createPinchStart(): { center: { x: number; y: number }; distance: number; camera: typeof state.camera } {
  const metrics = pointerPairMetrics();
  return { ...metrics, camera: { ...state.camera } };
}

function pointerPairMetrics(): { center: { x: number; y: number }; distance: number } {
  const [a, b] = [...activePointers.values()];
  const center = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
  return { center, distance: Math.hypot(a.x - b.x, a.y - b.y) };
}

function canvasRelativePoint(point: { x: number; y: number }): { x: number; y: number } {
  const rect = cityCanvas.getBoundingClientRect();
  return { x: point.x - rect.left, y: point.y - rect.top };
}
