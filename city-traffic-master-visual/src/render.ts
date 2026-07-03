import { blockCounts, findRoadGroupForCell, isDrivableBlockType, longestRoadGroup, routePointsForGroup } from "./blocks";
import { cellCenter, cellKey, worldToScreen } from "./grid";
import type { AppState, CityBlock, CityVehicle, DemoVehicle, GridCell, Point, RoadGroup, VehiclePath, VehicleType } from "./types";

interface RenderContext {
  ctx: CanvasRenderingContext2D;
  width: number;
  height: number;
  dpr: number;
  cssWidth: number;
  cssHeight: number;
}

const demoPaths: VehiclePath[] = [
  {
    id: "loop-main",
    points: [
      { x: -240, y: -40 },
      { x: -70, y: -136 },
      { x: 110, y: -80 },
      { x: 230, y: 30 },
      { x: 58, y: 130 },
      { x: -196, y: 92 },
    ],
  },
];

const demoVehicles: DemoVehicle[] = [
  { id: "demo-red", color: "#ef5d5d", pathId: "loop-main", progress: 0.02, speed: 0.000055 },
  { id: "demo-blue", color: "#477ee8", pathId: "loop-main", progress: 0.32, speed: 0.000047 },
];

export function renderCity(canvas: HTMLCanvasElement, state: AppState): void {
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  const width = canvas.width;
  const height = canvas.height;
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const rc = { ctx, width, height, dpr, cssWidth: width / dpr, cssHeight: height / dpr };

  ctx.clearRect(0, 0, width, height);
  drawBackground(rc, state);
  drawInfiniteGrid(rc, state);
  drawPlacedBlocks(rc, state);
  drawRoadLabels(rc, state);
  drawVehicles(rc, state);
  drawWeather(rc, state);
  drawNightOverlay(rc, state);
}

function sx(rc: RenderContext, state: AppState, point: Point): Point {
  const p = worldToScreen(point, state.camera, rc.cssWidth, rc.cssHeight);
  return { x: p.x * rc.dpr, y: p.y * rc.dpr };
}

function worldSize(rc: RenderContext, state: AppState, value: number): number {
  return value * state.camera.zoom * rc.dpr;
}

function drawBackground({ ctx, width, height }: RenderContext, state: AppState): void {
  const sky = ctx.createLinearGradient(0, 0, 0, height);
  sky.addColorStop(0, state.weather === "snowy" ? "#d7edf7" : "#8fd8ff");
  sky.addColorStop(0.42, state.weather === "rainy" ? "#abc8d6" : "#c9f1ff");
  sky.addColorStop(0.421, state.weather === "snowy" ? "#d8f0df" : "#8bd884");
  sky.addColorStop(1, state.weather === "snowy" ? "#eef7ee" : "#77c96f");
  ctx.fillStyle = sky;
  ctx.fillRect(0, 0, width, height);

  ctx.fillStyle = "rgba(255,255,255,0.72)";
  for (let i = 0; i < 4; i += 1) {
    const x = ((i * 270 + 60 + state.elapsedMs * 0.008) % (width + 180)) - 90;
    const y = 70 + i * 32;
    cloud(ctx, x, y, 1 + i * 0.1);
  }
}

function cloud(ctx: CanvasRenderingContext2D, x: number, y: number, s: number): void {
  ctx.beginPath();
  ctx.ellipse(x, y, 34 * s, 18 * s, 0, 0, Math.PI * 2);
  ctx.ellipse(x + 28 * s, y + 2 * s, 28 * s, 15 * s, 0, 0, Math.PI * 2);
  ctx.ellipse(x - 26 * s, y + 4 * s, 24 * s, 14 * s, 0, 0, Math.PI * 2);
  ctx.fill();
}

function drawInfiniteGrid(rc: RenderContext, state: AppState): void {
  const { ctx } = rc;
  const size = state.grid.cellSize;
  const left = state.camera.x - rc.cssWidth / 2 / state.camera.zoom;
  const right = state.camera.x + rc.cssWidth / 2 / state.camera.zoom;
  const top = state.camera.y - rc.cssHeight / 2 / state.camera.zoom;
  const bottom = state.camera.y + rc.cssHeight / 2 / state.camera.zoom;
  const startX = Math.floor(left / size) - 1;
  const endX = Math.ceil(right / size) + 1;
  const startY = Math.floor(top / size) - 1;
  const endY = Math.ceil(bottom / size) + 1;

  ctx.save();
  ctx.strokeStyle = "rgba(255,255,255,0.42)";
  ctx.lineWidth = Math.max(1, state.camera.zoom * rc.dpr);
  for (let x = startX; x <= endX; x += 1) {
    const a = sx(rc, state, { x: x * size, y: top - size });
    const b = sx(rc, state, { x: x * size, y: bottom + size });
    ctx.beginPath();
    ctx.moveTo(a.x, a.y);
    ctx.lineTo(b.x, b.y);
    ctx.stroke();
  }
  for (let y = startY; y <= endY; y += 1) {
    const a = sx(rc, state, { x: left - size, y: y * size });
    const b = sx(rc, state, { x: right + size, y: y * size });
    ctx.beginPath();
    ctx.moveTo(a.x, a.y);
    ctx.lineTo(b.x, b.y);
    ctx.stroke();
  }
  ctx.restore();
}

function drawPlacedBlocks(rc: RenderContext, state: AppState): void {
  for (const block of Object.values(state.blocks)) {
    if (block.type === "road") drawRoadBlock(rc, state, block.cell);
    if (block.type === "overpass") drawOverpassBlock(rc, state, block);
    if (block.type === "roadwork") drawRoadworkBlock(rc, state, block.cell);
    if (block.type === "trafficLight") drawTrafficLightBlock(rc, state, block.cell);
    if (block.type === "building") drawBuildingBlock(rc, state, block.cell);
    if (block.type === "park") drawParkBlock(rc, state, block.cell);
    if (block.type === "busStop") drawBusStopBlock(rc, state, block.cell);
  }
  if (state.selectedCell) drawSelectedCell(rc, state, state.selectedCell);
}

function drawOverpassBlock(rc: RenderContext, state: AppState, block: CityBlock): void {
  const { ctx } = rc;
  const center = sx(rc, state, cellCenter(state.grid, block.cell));
  const size = worldSize(rc, state, state.grid.cellSize);
  const direction = block.overpassDirection ?? "horizontal";
  ctx.save();
  ctx.translate(center.x, center.y);
  if (direction === "horizontal") ctx.rotate(Math.PI / 2);
  drawOverpassLowerRoad(rc, state, size);
  ctx.restore();

  ctx.save();
  ctx.translate(center.x, center.y);
  if (direction === "vertical") ctx.rotate(Math.PI / 2);
  drawOverpassDeck(rc, state, size);
  ctx.restore();
}

function drawOverpassLowerRoad(rc: RenderContext, state: AppState, size: number): void {
  const { ctx } = rc;
  ctx.fillStyle = "rgba(47, 66, 72, 0.18)";
  ctx.beginPath();
  ctx.roundRect(-size * 0.44 + 4 * rc.dpr, -size * 0.35 + 5 * rc.dpr, size * 0.88, size * 0.7, 14 * rc.dpr);
  ctx.fill();
  ctx.fillStyle = "#4f5d66";
  ctx.beginPath();
  ctx.roundRect(-size * 0.44, -size * 0.35, size * 0.88, size * 0.7, 14 * rc.dpr);
  ctx.fill();
  ctx.strokeStyle = "#f8e28a";
  ctx.lineWidth = 2 * state.camera.zoom * rc.dpr;
  ctx.setLineDash([8 * state.camera.zoom * rc.dpr, 8 * state.camera.zoom * rc.dpr]);
  ctx.beginPath();
  ctx.moveTo(-size * 0.28, 0);
  ctx.lineTo(size * 0.28, 0);
  ctx.stroke();
  ctx.setLineDash([]);
}

function drawOverpassDeck(rc: RenderContext, state: AppState, size: number): void {
  const { ctx } = rc;
  ctx.fillStyle = "rgba(49, 82, 96, 0.2)";
  ctx.fillRect(-size * 0.38, size * 0.22, size * 0.76, 5 * rc.dpr);
  ctx.fillStyle = "#8b98a6";
  ctx.beginPath();
  ctx.roundRect(-size * 0.48, -size * 0.2, size * 0.96, size * 0.4, 12 * rc.dpr);
  ctx.fill();
  ctx.strokeStyle = "#d6eef8";
  ctx.lineWidth = 4 * state.camera.zoom * rc.dpr;
  ctx.beginPath();
  ctx.moveTo(-size * 0.35, 0);
  ctx.lineTo(size * 0.35, 0);
  ctx.stroke();
  ctx.strokeStyle = "#f8e28a";
  ctx.lineWidth = 2 * state.camera.zoom * rc.dpr;
  ctx.beginPath();
  ctx.moveTo(-size * 0.34, -size * 0.08);
  ctx.lineTo(size * 0.34, -size * 0.08);
  ctx.moveTo(-size * 0.34, size * 0.08);
  ctx.lineTo(size * 0.34, size * 0.08);
  ctx.stroke();
}

function drawRoadBlock(rc: RenderContext, state: AppState, cell: GridCell): void {
  const { ctx } = rc;
  const center = sx(rc, state, cellCenter(state.grid, cell));
  const size = worldSize(rc, state, state.grid.cellSize);
  ctx.fillStyle = "rgba(47, 66, 72, 0.2)";
  ctx.beginPath();
  ctx.roundRect(center.x - size * 0.44 + 4 * rc.dpr, center.y - size * 0.35 + 5 * rc.dpr, size * 0.88, size * 0.7, 14 * rc.dpr);
  ctx.fill();
  ctx.fillStyle = "#5b6570";
  ctx.beginPath();
  ctx.roundRect(center.x - size * 0.44, center.y - size * 0.35, size * 0.88, size * 0.7, 14 * rc.dpr);
  ctx.fill();
  ctx.strokeStyle = "#f8e28a";
  ctx.lineWidth = 3 * state.camera.zoom * rc.dpr;
  ctx.setLineDash([9 * state.camera.zoom * rc.dpr, 8 * state.camera.zoom * rc.dpr]);
  ctx.beginPath();
  ctx.moveTo(center.x - size * 0.3, center.y);
  ctx.lineTo(center.x + size * 0.3, center.y);
  ctx.stroke();
  ctx.setLineDash([]);
}

function drawRoadworkBlock(rc: RenderContext, state: AppState, cell: GridCell): void {
  const { ctx } = rc;
  const center = sx(rc, state, cellCenter(state.grid, cell));
  const size = worldSize(rc, state, state.grid.cellSize);
  ctx.fillStyle = "rgba(47, 66, 72, 0.16)";
  ctx.beginPath();
  ctx.roundRect(center.x - size * 0.42, center.y - size * 0.32, size * 0.84, size * 0.64, 12 * rc.dpr);
  ctx.fill();
  ctx.fillStyle = "#f5c542";
  ctx.beginPath();
  ctx.roundRect(center.x - size * 0.34, center.y - size * 0.2, size * 0.68, size * 0.4, 8 * rc.dpr);
  ctx.fill();
  ctx.save();
  ctx.strokeStyle = "#315260";
  ctx.lineWidth = 5 * state.camera.zoom * rc.dpr;
  for (let index = -2; index <= 2; index += 1) {
    ctx.beginPath();
    ctx.moveTo(center.x + index * size * 0.16 - size * 0.12, center.y + size * 0.2);
    ctx.lineTo(center.x + index * size * 0.16 + size * 0.12, center.y - size * 0.2);
    ctx.stroke();
  }
  ctx.restore();
  ctx.fillStyle = "#d85f5f";
  ctx.fillRect(center.x - size * 0.38, center.y + size * 0.22, size * 0.76, 5 * rc.dpr);
}

function drawTrafficLightBlock(rc: RenderContext, state: AppState, cell: GridCell): void {
  const { ctx } = rc;
  const center = sx(rc, state, cellCenter(state.grid, cell));
  const size = worldSize(rc, state, state.grid.cellSize);
  const horizontalGreen = Math.floor(state.elapsedMs / 3000) % 2 === 0;
  drawRoadBlock(rc, state, cell);
  ctx.fillStyle = "#5b6570";
  ctx.beginPath();
  ctx.roundRect(center.x - size * 0.18, center.y - size * 0.44, size * 0.36, size * 0.88, 12 * rc.dpr);
  ctx.fill();
  ctx.strokeStyle = "#f8e28a";
  ctx.lineWidth = 2 * state.camera.zoom * rc.dpr;
  ctx.beginPath();
  ctx.moveTo(center.x, center.y - size * 0.28);
  ctx.lineTo(center.x, center.y + size * 0.28);
  ctx.stroke();
  drawSignalLamp(ctx, center.x - size * 0.28, center.y - size * 0.28, horizontalGreen, rc.dpr, state.camera.zoom);
  drawSignalLamp(ctx, center.x + size * 0.28, center.y + size * 0.28, horizontalGreen, rc.dpr, state.camera.zoom);
  drawSignalLamp(ctx, center.x + size * 0.28, center.y - size * 0.28, !horizontalGreen, rc.dpr, state.camera.zoom);
  drawSignalLamp(ctx, center.x - size * 0.28, center.y + size * 0.28, !horizontalGreen, rc.dpr, state.camera.zoom);
}

function drawSignalLamp(ctx: CanvasRenderingContext2D, x: number, y: number, green: boolean, dpr: number, zoom: number): void {
  const scale = dpr * zoom;
  ctx.save();
  ctx.fillStyle = "#315260";
  ctx.beginPath();
  ctx.roundRect(x - 7 * scale, y - 10 * scale, 14 * scale, 20 * scale, 6 * scale);
  ctx.fill();
  ctx.fillStyle = green ? "#35b56d" : "#ef5d5d";
  ctx.beginPath();
  ctx.arc(x, y, 4.5 * scale, 0, Math.PI * 2);
  ctx.fill();
  ctx.restore();
}

function drawBuildingBlock(rc: RenderContext, state: AppState, cell: GridCell): void {
  const { ctx } = rc;
  const center = sx(rc, state, cellCenter(state.grid, cell));
  const size = worldSize(rc, state, state.grid.cellSize);
  const palette = cell.x % 2 === 0 ? { body: "#ff8a78", roof: "#cf5f55" } : { body: "#ffd166", roof: "#f59f46" };
  ctx.fillStyle = "rgba(47, 66, 72, 0.18)";
  ctx.beginPath();
  ctx.roundRect(center.x - size * 0.32 + 5 * rc.dpr, center.y - size * 0.34 + 6 * rc.dpr, size * 0.64, size * 0.68, 10 * rc.dpr);
  ctx.fill();
  ctx.fillStyle = palette.body;
  ctx.beginPath();
  ctx.roundRect(center.x - size * 0.32, center.y - size * 0.34, size * 0.64, size * 0.68, 10 * rc.dpr);
  ctx.fill();
  ctx.fillStyle = palette.roof;
  ctx.fillRect(center.x - size * 0.32, center.y + size * 0.18, size * 0.64, size * 0.12);
  ctx.fillStyle = state.night ? "#ffe98f" : "rgba(255,255,255,0.74)";
  for (let i = 0; i < 4; i += 1) {
    const wx = center.x - size * 0.2 + (i % 2) * size * 0.22;
    const wy = center.y - size * 0.2 + Math.floor(i / 2) * size * 0.2;
    ctx.fillRect(wx, wy, size * 0.1, size * 0.1);
  }
}

function drawParkBlock(rc: RenderContext, state: AppState, cell: GridCell): void {
  const { ctx } = rc;
  const center = sx(rc, state, cellCenter(state.grid, cell));
  const size = worldSize(rc, state, state.grid.cellSize);
  ctx.fillStyle = "rgba(47, 66, 72, 0.14)";
  ctx.beginPath();
  ctx.ellipse(center.x + 4 * rc.dpr, center.y + 8 * rc.dpr, size * 0.28, size * 0.16, 0, 0, Math.PI * 2);
  ctx.fill();
  ctx.fillStyle = "#4cc47a";
  ctx.beginPath();
  ctx.roundRect(center.x - size * 0.34, center.y - size * 0.18, size * 0.68, size * 0.44, 12 * rc.dpr);
  ctx.fill();
  ctx.fillStyle = "#7a5a3d";
  ctx.fillRect(center.x - 3 * rc.dpr, center.y - size * 0.08, 6 * rc.dpr, size * 0.28);
  ctx.fillStyle = "#2fae65";
  ctx.beginPath();
  ctx.arc(center.x, center.y - size * 0.12, size * 0.18, 0, Math.PI * 2);
  ctx.fill();
}

function drawBusStopBlock(rc: RenderContext, state: AppState, cell: GridCell): void {
  const { ctx } = rc;
  const center = sx(rc, state, cellCenter(state.grid, cell));
  const size = worldSize(rc, state, state.grid.cellSize);
  ctx.fillStyle = "#315260";
  ctx.fillRect(center.x - size * 0.2, center.y - size * 0.28, size * 0.08, size * 0.58);
  ctx.fillStyle = "#477ee8";
  ctx.beginPath();
  ctx.roundRect(center.x - size * 0.08, center.y - size * 0.3, size * 0.42, size * 0.26, 6 * rc.dpr);
  ctx.fill();
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(center.x, center.y - size * 0.24, size * 0.22, size * 0.06);
}

function drawSelectedCell(rc: RenderContext, state: AppState, cell: GridCell): void {
  const { ctx } = rc;
  const center = sx(rc, state, cellCenter(state.grid, cell));
  const size = worldSize(rc, state, state.grid.cellSize);
  ctx.save();
  ctx.strokeStyle = "rgba(28, 132, 255, 0.9)";
  ctx.lineWidth = 4 * rc.dpr;
  ctx.setLineDash([8 * rc.dpr, 6 * rc.dpr]);
  ctx.beginPath();
  ctx.roundRect(center.x - size * 0.46, center.y - size * 0.46, size * 0.92, size * 0.92, 14 * rc.dpr);
  ctx.stroke();
  ctx.restore();
}

function drawRoadLabels(rc: RenderContext, state: AppState): void {
  for (const group of state.roadGroups) {
    if (group.cells.length < 2) continue;
    const cell = group.cells[Math.floor(group.cells.length / 2)];
    const p = sx(rc, state, cellCenter(state.grid, cell));
    drawLabel(rc, p.x, p.y - 30 * state.camera.zoom * rc.dpr, group.name, state.selectedEntity?.kind === "roadGroup" && state.selectedEntity.id === group.id);
  }
  for (const block of Object.values(state.blocks)) {
    if (isDrivableBlockType(block.type)) continue;
    const p = sx(rc, state, cellCenter(state.grid, block.cell));
    drawLabel(rc, p.x, p.y - 32 * state.camera.zoom * rc.dpr, block.name, state.selectedEntity?.kind === "block" && state.selectedEntity.id === block.id);
  }
}

function drawLabel(rc: RenderContext, x: number, y: number, text: string, selected: boolean): void {
  const { ctx } = rc;
  ctx.save();
  ctx.font = `${Math.max(12, 15 * rc.dpr)}px Inter, "Noto Sans SC", sans-serif`;
  const width = ctx.measureText(text).width + 20 * rc.dpr;
  const height = 28 * rc.dpr;
  ctx.fillStyle = selected ? "#ffffff" : "rgba(255,255,255,0.78)";
  ctx.strokeStyle = selected ? "#1e90ff" : "rgba(255,255,255,0.45)";
  ctx.lineWidth = selected ? 2 * rc.dpr : 1 * rc.dpr;
  ctx.beginPath();
  ctx.roundRect(x - width / 2, y - height / 2, width, height, 999);
  ctx.fill();
  ctx.stroke();
  ctx.fillStyle = "#315260";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(text, x, y + 1 * rc.dpr);
  ctx.restore();
}

function drawVehicles(rc: RenderContext, state: AppState): void {
  if (state.vehicles.length > 0) {
    for (const vehicle of state.vehicles) {
      const group = state.roadGroups.find((item) => item.id === vehicle.roadGroupId) ?? findRoadGroupForCell(state.roadGroups, vehicle.cell);
      drawVehicle(rc, state, vehicle, pointForCityVehicle(state, vehicle, group));
    }
    return;
  }

  if (blockCounts(state.blocks).road >= 3) return;
  for (const vehicle of demoVehicles) {
    const path = demoPaths.find((item) => item.id === vehicle.pathId);
    if (!path) continue;
    drawDemoVehicle(rc, state, vehicle, pointOnPath(path, vehicle.progress));
  }
}

function drawVehicle(rc: RenderContext, state: AppState, vehicle: CityVehicle, point: Point): void {
  const selected = state.selectedEntity?.kind === "vehicle" && state.selectedEntity.id === vehicle.id;
  if (vehicle.type === "bus" && (vehicle.passengerPulseMs ?? 0) > 0) drawPassengerExchange(rc, state, point, vehicle);
  drawVehicleBody(rc, state, point, vehicle.type, selected, undefined, vehicle.name);
}

function drawDemoVehicle(rc: RenderContext, state: AppState, vehicle: DemoVehicle, point: Point): void {
  drawVehicleBody(rc, state, point, "sedan", false, vehicle.color);
}

function drawVehicleBody(rc: RenderContext, state: AppState, point: Point, type: VehicleType, selected: boolean, colorOverride?: string, vehicleName = ""): void {
  const { ctx } = rc;
  const p = sx(rc, state, point);
  const scale = state.camera.zoom * rc.dpr;
  const specs: Record<VehicleType, { w: number; h: number; color: string }> = {
    sedan: { w: 32, h: 19, color: "#ef5d5d" },
    bus: { w: 48, h: 22, color: "#477ee8" },
    offroad: { w: 36, h: 24, color: "#f5c542" },
    sweeper: { w: 34, h: 20, color: "#7fcf9f" },
  };
  const spec = specs[type];
  ctx.save();
  ctx.translate(p.x, p.y);
  ctx.fillStyle = "rgba(31,45,50,0.22)";
  ctx.beginPath();
  ctx.roundRect((-spec.w / 2 + 2) * scale, 6 * scale, spec.w * scale, 13 * scale, 8 * scale);
  ctx.fill();
  ctx.fillStyle = colorOverride ?? spec.color;
  ctx.beginPath();
  ctx.roundRect((-spec.w / 2) * scale, (-spec.h / 2) * scale, spec.w * scale, spec.h * scale, 8 * scale);
  ctx.fill();
  ctx.fillStyle = "rgba(255,255,255,0.72)";
  if (type === "bus") {
    for (let i = 0; i < 3; i += 1) ctx.fillRect((-14 + i * 10) * scale, -7 * scale, 7 * scale, 5 * scale);
    drawBusLineBadge(ctx, scale, vehicleName);
  } else {
    ctx.fillRect(-7 * scale, -7 * scale, 14 * scale, 5 * scale);
  }
  ctx.fillStyle = "#27343a";
  ctx.beginPath();
  ctx.arc(-10 * scale, 10 * scale, 4 * scale, 0, Math.PI * 2);
  ctx.arc(10 * scale, 10 * scale, 4 * scale, 0, Math.PI * 2);
  ctx.fill();
  if (type === "sweeper") {
    ctx.strokeStyle = "#315260";
    ctx.lineWidth = 3 * scale;
    ctx.beginPath();
    ctx.arc(14 * scale, 11 * scale, 7 * scale, 0, Math.PI);
    ctx.stroke();
  }
  if (selected) {
    ctx.strokeStyle = "#1e90ff";
    ctx.lineWidth = 3 * scale;
    ctx.strokeRect((-spec.w / 2 - 4) * scale, (-spec.h / 2 - 4) * scale, (spec.w + 8) * scale, (spec.h + 8) * scale);
  }
  ctx.restore();
}

function drawBusLineBadge(ctx: CanvasRenderingContext2D, scale: number, vehicleName: string): void {
  const text = lineNumberForVehicleName(vehicleName);
  if (!text) return;
  ctx.save();
  ctx.fillStyle = "#ffffff";
  ctx.strokeStyle = "rgba(49,82,96,0.32)";
  ctx.lineWidth = 1.4 * scale;
  ctx.beginPath();
  ctx.roundRect(-20 * scale, -9.5 * scale, 16 * scale, 11 * scale, 3 * scale);
  ctx.fill();
  ctx.stroke();
  ctx.fillStyle = "#315260";
  ctx.font = `${Math.max(8, 8.5 * scale)}px Inter, "Noto Sans SC", sans-serif`;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(text, -12 * scale, -4 * scale, 14 * scale);
  ctx.restore();
}

export function lineNumberForVehicleName(name: string): string {
  const clean = name.trim();
  const number = clean.match(/\d{1,3}/)?.[0];
  if (number) return number;
  return clean.slice(0, 3);
}

function drawPassengerExchange(rc: RenderContext, state: AppState, point: Point, vehicle: CityVehicle): void {
  const { ctx } = rc;
  const p = sx(rc, state, point);
  const scale = state.camera.zoom * rc.dpr;
  const pulse = Math.max(0, Math.min(1, (vehicle.passengerPulseMs ?? 0) / 1400));
  const bob = Math.sin(state.elapsedMs * 0.012) * 3 * scale;
  const people = [
    { x: -32, y: -27, color: "#ffd166", dir: -1 },
    { x: -22, y: -38, color: "#ef5d5d", dir: 1 },
    { x: 30, y: -30, color: "#35b56d", dir: -1 },
    { x: 20, y: -42, color: "#8f7ee8", dir: 1 },
  ];
  ctx.save();
  ctx.globalAlpha = 0.25 + pulse * 0.75;
  ctx.lineWidth = 3 * scale;
  for (const person of people) {
    const px = p.x + person.x * scale + person.dir * (1 - pulse) * 16 * scale;
    const py = p.y + person.y * scale + bob;
    ctx.fillStyle = person.color;
    ctx.beginPath();
    ctx.arc(px, py, 5 * scale, 0, Math.PI * 2);
    ctx.fill();
    ctx.strokeStyle = "#315260";
    ctx.beginPath();
    ctx.moveTo(px, py + 6 * scale);
    ctx.lineTo(px, py + 16 * scale);
    ctx.moveTo(px - 7 * scale, py + 10 * scale);
    ctx.lineTo(px + 7 * scale, py + 10 * scale);
    ctx.stroke();
  }
  ctx.fillStyle = "rgba(255,255,255,0.88)";
  ctx.strokeStyle = "rgba(49,82,96,0.18)";
  ctx.beginPath();
  ctx.roundRect(p.x - 56 * scale, p.y - 68 * scale, 112 * scale, 24 * scale, 999);
  ctx.fill();
  ctx.stroke();
  ctx.fillStyle = "#315260";
  ctx.font = `${Math.max(11, 12 * rc.dpr)}px Inter, "Noto Sans SC", sans-serif`;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText("上下车", p.x, p.y - 56 * scale);
  ctx.restore();
}

function pointOnPath(path: VehiclePath, progress: number): Point {
  const points = path.points;
  const segment = Math.floor(progress * points.length);
  const next = (segment + 1) % points.length;
  const local = progress * points.length - segment;
  const a = points[segment];
  const b = points[next];
  return { x: a.x + (b.x - a.x) * local, y: a.y + (b.y - a.y) * local };
}

function pointOnPolyline(points: Point[], progress: number): Point {
  if (points.length === 1) return points[0];
  const route = points.length > 2 ? [...points, ...points.slice(1, -1).reverse()] : points;
  const segment = Math.floor(progress * route.length);
  const next = (segment + 1) % route.length;
  const local = progress * route.length - segment;
  const a = route[segment];
  const b = route[next];
  return { x: a.x + (b.x - a.x) * local, y: a.y + (b.y - a.y) * local };
}

export function pointForCityVehicle(state: AppState, vehicle: CityVehicle, group: RoadGroup | null): Point {
  const busPoint = vehicle.type === "bus" ? pointOnBusRoute(state, vehicle, group) : null;
  if (busPoint) return busPoint;
  const sedanPoint = vehicle.type === "sedan" ? pointOnBuildingRoute(state, vehicle) : null;
  if (sedanPoint) return sedanPoint;
  if (vehicle.routeCellPath && vehicle.routeCellPath.length >= 2) {
    return pointOnPolyline(
      vehicle.routeCellPath.map((cell) => cellCenter(state.grid, cell)),
      vehicle.progress,
    );
  }
  const route = group && group.cells.length >= 2 ? routePointsForGroup(state.grid, group) : [cellCenter(state.grid, vehicle.cell)];
  return pointOnPolyline(route, vehicle.progress);
}

function pointOnBuildingRoute(state: AppState, vehicle: CityVehicle): Point | null {
  if (!vehicle.routeBuildingIds || vehicle.routeBuildingIds.length < 2) return null;
  const currentIndex = vehicle.currentBuildingIndex ?? 0;
  const currentId = vehicle.routeBuildingIds[currentIndex % vehicle.routeBuildingIds.length];
  const nextId = vehicle.routeBuildingIds[nextRouteIndex(vehicle.routeBuildingIds.length, currentIndex, vehicle.routeDirection ?? 1)];
  const current = blockById(state, currentId);
  const next = blockById(state, nextId);
  if (!current || !next) return null;
  const route = roadRouteBetweenBlocks(state, current, next);
  return route ? pointOnOpenPolyline(route, vehicle.progress) : null;
}

function pointOnBusRoute(state: AppState, vehicle: CityVehicle, group: RoadGroup | null): Point | null {
  if (!vehicle.routeStopIds || vehicle.routeStopIds.length < 2) return null;
  const currentIndex = vehicle.currentStopIndex ?? 0;
  const currentId = vehicle.routeStopIds[currentIndex % vehicle.routeStopIds.length];
  const nextId = vehicle.routeStopIds[nextRouteIndex(vehicle.routeStopIds.length, currentIndex, vehicle.routeDirection ?? 1)];
  const current = blockById(state, currentId);
  const next = blockById(state, nextId);
  if (!current || !next) return null;
  const connectedRoute = roadRouteBetweenBlocks(state, current, next);
  if (connectedRoute) return pointOnOpenPolyline(connectedRoute, vehicle.progress);
  if (!group || group.cells.length === 0) return null;
  const route = routePointsForGroup(state.grid, group);
  const currentRoadIndex = nearestPointIndex(route, cellCenter(state.grid, current.cell));
  const nextRoadIndex = nearestPointIndex(route, cellCenter(state.grid, next.cell));
  const segment = routeBetweenIndexes(route, currentRoadIndex, nextRoadIndex);
  return pointOnOpenPolyline(segment, vehicle.progress);
}

function nextRouteIndex(length: number, currentIndex: number, direction: 1 | -1): number {
  return (currentIndex + direction + length) % length;
}

function roadRouteBetweenBlocks(state: AppState, current: CityBlock, next: CityBlock): Point[] | null {
  const roadCells = Object.values(state.blocks).filter((block) => isDrivableBlockType(block.type)).map((block) => block.cell);
  const start = nearestCell(roadCells, current.cell);
  const end = nearestCell(roadCells, next.cell);
  if (!start || !end) return null;
  const path = roadCellPath(roadCells, start, end);
  return path ? path.map((cell) => cellCenter(state.grid, cell)) : null;
}

function nearestCell(cells: GridCell[], target: GridCell): GridCell | null {
  let best: GridCell | null = null;
  let bestDistance = Number.POSITIVE_INFINITY;
  for (const cell of cells) {
    const distance = (cell.x - target.x) ** 2 + (cell.y - target.y) ** 2;
    if (distance < bestDistance) {
      best = cell;
      bestDistance = distance;
    }
  }
  return best;
}

function roadCellPath(roadCells: GridCell[], start: GridCell, end: GridCell): GridCell[] | null {
  const roads = new Set(roadCells.map((cell) => cellKey(cell)));
  const startKey = cellKey(start);
  const endKey = cellKey(end);
  if (!roads.has(startKey) || !roads.has(endKey)) return null;
  const queue: GridCell[] = [start];
  const cameFrom = new Map<string, string | null>([[startKey, null]]);
  const cellsByKey = new Map(roadCells.map((cell) => [cellKey(cell), cell]));

  for (let index = 0; index < queue.length; index += 1) {
    const cell = queue[index];
    const key = cellKey(cell);
    if (key === endKey) break;
    for (const next of neighboringRoadCells(cell, roads)) {
      const nextKey = cellKey(next);
      if (cameFrom.has(nextKey)) continue;
      cameFrom.set(nextKey, key);
      queue.push(cellsByKey.get(nextKey) ?? next);
    }
  }

  if (!cameFrom.has(endKey)) return null;
  const path: GridCell[] = [];
  let key: string | null = endKey;
  while (key) {
    const cell = cellsByKey.get(key);
    if (!cell) return null;
    path.push(cell);
    key = cameFrom.get(key) ?? null;
  }
  return path.reverse();
}

function neighboringRoadCells(cell: GridCell, roads: Set<string>): GridCell[] {
  return [
    { x: cell.x + 1, y: cell.y },
    { x: cell.x, y: cell.y + 1 },
    { x: cell.x - 1, y: cell.y },
    { x: cell.x, y: cell.y - 1 },
  ].filter((candidate) => roads.has(cellKey(candidate)));
}

function blockById(state: AppState, id: string): CityBlock | null {
  return Object.values(state.blocks).find((block) => block.id === id) ?? null;
}

function nearestPointIndex(points: Point[], target: Point): number {
  let bestIndex = 0;
  let bestDistance = Number.POSITIVE_INFINITY;
  points.forEach((point, index) => {
    const distance = (point.x - target.x) ** 2 + (point.y - target.y) ** 2;
    if (distance < bestDistance) {
      bestDistance = distance;
      bestIndex = index;
    }
  });
  return bestIndex;
}

function routeBetweenIndexes(points: Point[], fromIndex: number, toIndex: number): Point[] {
  if (fromIndex === toIndex) return [points[fromIndex]];
  if (fromIndex < toIndex) return points.slice(fromIndex, toIndex + 1);
  return points.slice(toIndex, fromIndex + 1).reverse();
}

function pointOnOpenPolyline(points: Point[], progress: number): Point {
  if (points.length === 1) return points[0];
  const clamped = Math.max(0, Math.min(1, progress));
  const scaled = clamped * (points.length - 1);
  const segment = Math.min(points.length - 2, Math.floor(scaled));
  const local = scaled - segment;
  const a = points[segment];
  const b = points[segment + 1];
  return { x: a.x + (b.x - a.x) * local, y: a.y + (b.y - a.y) * local };
}

function drawWeather(rc: RenderContext, state: AppState): void {
  const { ctx, width, height } = rc;
  if (state.weather === "rainy") {
    ctx.strokeStyle = "rgba(58,95,118,0.34)";
    ctx.lineWidth = 2;
    for (let i = 0; i < 80; i += 1) {
      const x = (i * 53 + state.elapsedMs * 0.22) % width;
      const y = (i * 37 + state.elapsedMs * 0.35) % height;
      ctx.beginPath();
      ctx.moveTo(x, y);
      ctx.lineTo(x - 10, y + 20);
      ctx.stroke();
    }
  }
  if (state.weather === "snowy") {
    ctx.fillStyle = "rgba(255,255,255,0.75)";
    for (let i = 0; i < 72; i += 1) {
      const x = (i * 61 + state.elapsedMs * 0.035) % width;
      const y = (i * 43 + state.elapsedMs * 0.08) % height;
      ctx.beginPath();
      ctx.arc(x, y, 3, 0, Math.PI * 2);
      ctx.fill();
    }
  }
}

function drawNightOverlay(rc: RenderContext, state: AppState): void {
  if (!state.night) return;
  const { ctx, width, height } = rc;
  ctx.fillStyle = "rgba(20,45,85,0.32)";
  ctx.fillRect(0, 0, width, height);
}
