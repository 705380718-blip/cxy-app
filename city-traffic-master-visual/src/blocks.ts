import { cellCenter, cellKey } from "./grid";
import type { BlockTool, CityBlock, CityBlocks, GridCell, GridConfig, OverpassDirection, Point, RoadGroup } from "./types";

const DIRECTIONS: GridCell[] = [
  { x: 1, y: 0 },
  { x: -1, y: 0 },
  { x: 0, y: 1 },
  { x: 0, y: -1 },
];

const DEFAULT_NAMES: Record<BlockTool, string> = {
  road: "新道路",
  overpass: "立交桥",
  roadwork: "道路施工",
  trafficLight: "红绿灯路口",
  building: "新建筑",
  park: "新公园",
  busStop: "阳光站",
};

export function createEmptyBlocks(): CityBlocks {
  return {};
}

export function getBlock(blocks: CityBlocks, cell: GridCell): CityBlock | null {
  return blocks[cellKey(cell)] ?? null;
}

export function placeBlock(blocks: CityBlocks, cell: GridCell, tool: BlockTool, overpassDirection: OverpassDirection = "horizontal"): CityBlocks {
  const key = cellKey(cell);
  const current = blocks[key];
  if (current && current.type !== tool && !canReplaceBlock(current.type, tool)) return blocks;
  const next = { ...blocks };
  const overpassFields = tool === "overpass" ? { overpassDirection } : { overpassDirection: undefined };
  next[key] = current
    ? {
        ...current,
        id: `${tool}-${key}`,
        type: tool,
        name: current.type === tool ? current.name : defaultName(tool, Object.values(blocks).filter((block) => block.type === tool).length + 1),
        ...overpassFields,
      }
    : {
    id: `${tool}-${key}`,
    type: tool,
    cell,
    name: defaultName(tool, Object.values(blocks).filter((block) => block.type === tool).length + 1),
    ...overpassFields,
  };
  return next;
}

export function renameBlock(blocks: CityBlocks, blockId: string, name: string): CityBlocks {
  const clean = name.trim();
  if (!clean) return blocks;
  const next = { ...blocks };
  for (const [key, block] of Object.entries(next)) {
    if (block.id === blockId) next[key] = { ...block, name: clean };
  }
  return next;
}

export function blockCounts(blocks: CityBlocks): Record<BlockTool, number> & { empty: number } {
  const counts = { empty: 0, road: 0, overpass: 0, roadwork: 0, trafficLight: 0, building: 0, park: 0, busStop: 0 };
  for (const block of Object.values(blocks)) counts[block.type] += 1;
  return counts;
}

export function recomputeRoadGroups(_grid: GridConfig, blocks: CityBlocks, previous: RoadGroup[] = []): RoadGroup[] {
  const roadCells = Object.values(blocks)
    .filter((block) => isDrivableBlockType(block.type))
    .map((block) => block.cell)
    .sort((a, b) => a.y - b.y || a.x - b.x);
  const roadKeys = new Set(roadCells.map((cell) => cellKey(cell)));
  const groupedKeys = new Set<string>();
  const groups: RoadGroup[] = [];

  for (const cells of collectLineSegments(roadCells, roadKeys, "h")) {
    addRoadGroup(groups, blocks, previous, cells, "h");
    cells.forEach((cell) => groupedKeys.add(cellKey(cell)));
  }
  for (const cells of collectLineSegments(roadCells, roadKeys, "v")) {
    addRoadGroup(groups, blocks, previous, cells, "v");
    cells.forEach((cell) => groupedKeys.add(cellKey(cell)));
  }
  for (const cell of roadCells) {
    if (groupedKeys.has(cellKey(cell))) continue;
    addRoadGroup(groups, blocks, previous, [cell], "single");
  }
  return groups;
}

export function findRoadGroupForCell(groups: RoadGroup[], cell: GridCell): RoadGroup | null {
  return groups.find((group) => group.cells.some((item) => item.x === cell.x && item.y === cell.y)) ?? null;
}

export function renameRoadGroup(blocks: CityBlocks, groups: RoadGroup[], groupId: string, name: string): { blocks: CityBlocks; groups: RoadGroup[] } {
  const clean = name.trim();
  if (!clean) return { blocks, groups };
  const group = groups.find((item) => item.id === groupId);
  if (!group) return { blocks, groups };
  let nextBlocks = { ...blocks };
  for (const cell of group.cells) {
    const key = cellKey(cell);
    const block = nextBlocks[key];
    if (block && isDrivableBlockType(block.type)) nextBlocks = { ...nextBlocks, [key]: { ...block, name: clean } };
  }
  return { blocks: nextBlocks, groups: groups.map((item) => (item.id === groupId ? { ...item, name: clean } : item)) };
}

export function longestRoadGroup(groups: RoadGroup[]): RoadGroup | null {
  return [...groups].sort((a, b) => b.cells.length - a.cells.length)[0] ?? null;
}

export function routePointsForGroup(grid: GridConfig, group: RoadGroup): Point[] {
  const cells = [...group.cells].sort((a, b) => a.y - b.y || a.x - b.x);
  return cells.map((cell) => cellCenter(grid, cell));
}

function collectLineSegments(roadCells: GridCell[], roadKeys: Set<string>, direction: "h" | "v"): GridCell[][] {
  const starts = roadCells.filter((cell) => {
    const previous = direction === "h" ? { x: cell.x - 1, y: cell.y } : { x: cell.x, y: cell.y - 1 };
    const next = direction === "h" ? { x: cell.x + 1, y: cell.y } : { x: cell.x, y: cell.y + 1 };
    return !roadKeys.has(cellKey(previous)) && roadKeys.has(cellKey(next));
  });
  return starts.map((start) => {
    const cells = [start];
    let current = start;
    while (true) {
      const next = direction === "h" ? { x: current.x + 1, y: current.y } : { x: current.x, y: current.y + 1 };
      if (!roadKeys.has(cellKey(next))) break;
      cells.push(next);
      current = next;
    }
    return cells;
  });
}

function addRoadGroup(groups: RoadGroup[], blocks: CityBlocks, previous: RoadGroup[], cells: GridCell[], direction: "h" | "v" | "single"): void {
  const first = cells[0];
  const id = direction === "single" ? `road-single-${first.x}-${first.y}` : `road-line-${direction}-${first.x}-${first.y}`;
  const name = findPreviousName(cells, previous) ?? blocks[cellKey(first)]?.name ?? `新道路 ${groups.length + 1}`;
  groups.push({ id, name, cells });
}

function findPreviousName(cells: GridCell[], previous: RoadGroup[]): string | null {
  const exact = previous.find((group) => sameCells(group.cells, cells));
  if (exact) return exact.name;
  let best: { name: string; score: number } | null = null;
  for (const group of previous) {
    const score = group.cells.filter((oldCell) => cells.some((cell) => cell.x === oldCell.x && cell.y === oldCell.y)).length;
    if (score > 0 && (!best || score > best.score)) best = { name: group.name, score };
  }
  return best?.name ?? null;
}

function sameCells(a: GridCell[], b: GridCell[]): boolean {
  if (a.length !== b.length) return false;
  const keys = new Set(a.map((cell) => cellKey(cell)));
  return b.every((cell) => keys.has(cellKey(cell)));
}

function defaultName(tool: BlockTool, count: number): string {
  return tool === "busStop" ? `${DEFAULT_NAMES[tool]} ${count}` : `${DEFAULT_NAMES[tool]} ${count}`;
}

export function isDrivableBlockType(type: BlockTool): boolean {
  return type === "road" || type === "overpass" || type === "trafficLight";
}

function canReplaceBlock(current: BlockTool, next: BlockTool): boolean {
  if (next === "roadwork" && isDrivableBlockType(current)) return true;
  if (current === "roadwork" && isDrivableBlockType(next)) return true;
  return isDrivableBlockType(current) && isDrivableBlockType(next);
}
