import type { Camera, GridCell, GridConfig, Point } from "./types";

export const DEFAULT_GRID: GridConfig = {
  cellSize: 56,
};

export const DEFAULT_CAMERA: Camera = {
  x: 0,
  y: 0,
  zoom: 1,
};

export function cellKey(cell: GridCell): string {
  return `${cell.x},${cell.y}`;
}

export function parseCellKey(key: string): GridCell {
  const [x, y] = key.split(",").map((value) => Number.parseInt(value, 10));
  return { x, y };
}

export function pointToCell(grid: GridConfig, point: Point): GridCell {
  return {
    x: Math.floor(point.x / grid.cellSize),
    y: Math.floor(point.y / grid.cellSize),
  };
}

export function cellCenter(grid: GridConfig, cell: GridCell): Point {
  return {
    x: cell.x * grid.cellSize + grid.cellSize / 2,
    y: cell.y * grid.cellSize + grid.cellSize / 2,
  };
}

export function cellsEqual(a: GridCell | null, b: GridCell | null): boolean {
  return !!a && !!b && a.x === b.x && a.y === b.y;
}

export function screenToWorld(point: Point, camera: Camera, viewportWidth: number, viewportHeight: number): Point {
  return {
    x: camera.x + (point.x - viewportWidth / 2) / camera.zoom,
    y: camera.y + (point.y - viewportHeight / 2) / camera.zoom,
  };
}

export function worldToScreen(point: Point, camera: Camera, viewportWidth: number, viewportHeight: number): Point {
  return {
    x: (point.x - camera.x) * camera.zoom + viewportWidth / 2,
    y: (point.y - camera.y) * camera.zoom + viewportHeight / 2,
  };
}

export function clampZoom(zoom: number): number {
  return Math.min(2.4, Math.max(0.45, zoom));
}
