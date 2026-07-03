import {
  blockCounts,
  createEmptyBlocks,
  findRoadGroupForCell,
  getBlock,
  isDrivableBlockType,
  longestRoadGroup,
  placeBlock,
  recomputeRoadGroups,
  renameBlock,
  renameRoadGroup,
  routePointsForGroup,
} from "./blocks";
import { cellKey, DEFAULT_CAMERA, DEFAULT_GRID } from "./grid";
import { loadCitySave, saveCity } from "./storage";
import type { AppState, BlockTool, CityVehicle, GridCell, OverpassDirection, Point, Tool, VehicleType, Weather } from "./types";

const VEHICLE_DEFAULTS: Record<VehicleType, { name: string; speed: number }> = {
  sedan: { name: "小轿车", speed: 0.000055 },
  bus: { name: "公交车", speed: 0.000035 },
  offroad: { name: "越野车", speed: 0.000046 },
  sweeper: { name: "扫地车", speed: 0.000028 },
};
const BUS_DWELL_MS = 1800;
const PASSENGER_PULSE_MS = 1400;

export function createInitialState(): AppState {
  const savedCity = loadCitySave();
  const weather = savedCity?.weather ?? "sunny";
  const night = savedCity?.night ?? false;
  const blocks = savedCity?.blocks ?? createEmptyBlocks();
  const roadGroups = recomputeRoadGroups(DEFAULT_GRID, blocks, savedCity?.roadGroups ?? []);
  const vehicles = savedCity?.vehicles ?? [];
  const mood = scoreCity(blocks, roadGroups, vehicles, weather, night);
  return {
    running: true,
    weather,
    night,
    score: mood.score,
    selectedTool: savedCity?.selectedTool ?? "road",
    savedAt: savedCity?.savedAt ?? null,
    cityMood: mood.cityMood,
    vehicles,
    elapsedMs: 0,
    showCityCheck: false,
    statusCollapsed: false,
    grid: DEFAULT_GRID,
    camera: savedCity?.camera ?? DEFAULT_CAMERA,
    blocks,
    roadGroups,
    selectedCell: null,
    selectedEntity: null,
    loadedFromStorage: !!savedCity,
  };
}

export function updateState(state: AppState, deltaMs: number): void {
  state.elapsedMs += deltaMs;
  if (!state.running) return;
  const weatherFactor = state.weather === "sunny" ? 1 : state.weather === "rainy" ? 0.78 : 0.62;
  for (const vehicle of state.vehicles) {
    updateVehicle(state, vehicle, deltaMs, weatherFactor);
  }
}

export function cycleWeather(current: Weather): Weather {
  if (current === "sunny") return "rainy";
  if (current === "rainy") return "snowy";
  return "sunny";
}

export function updateMood(state: AppState): void {
  const mood = deriveMood(state);
  state.cityMood = mood.cityMood;
  state.score = mood.score;
}

export function saveVisualState(state: AppState): void {
  state.savedAt = new Date().toISOString();
  saveCity({
    blocks: state.blocks,
    roadGroups: state.roadGroups,
    camera: state.camera,
    vehicles: state.vehicles,
    weather: state.weather,
    night: state.night,
    selectedTool: state.selectedTool,
    savedAt: state.savedAt,
  });
}

export function isBlockTool(tool: Tool): tool is BlockTool {
  return tool === "road" || tool === "overpass" || tool === "roadwork" || tool === "trafficLight" || tool === "building" || tool === "park" || tool === "busStop";
}

export function isVehicleTool(tool: Tool): tool is VehicleType {
  return tool === "sedan" || tool === "bus" || tool === "offroad" || tool === "sweeper";
}

export function selectCell(state: AppState, cell: GridCell | null): void {
  state.selectedCell = cell;
  state.selectedEntity = null;
  if (!cell) return;
  const block = getBlock(state.blocks, cell);
  if (block) state.selectedEntity = { kind: "block", id: block.id };
  const group = findRoadGroupForCell(state.roadGroups, cell);
  if (group && block && isDrivableBlockType(block.type)) state.selectedEntity = { kind: "roadGroup", id: group.id };
}

export function placeSelectedBlock(state: AppState, cell: GridCell | null, overpassDirection: OverpassDirection = "horizontal"): boolean {
  if (!cell || !isBlockTool(state.selectedTool)) return false;
  const nextBlocks = placeBlock(state.blocks, cell, state.selectedTool, overpassDirection);
  if (nextBlocks === state.blocks) return false;
  state.blocks = nextBlocks;
  state.roadGroups = recomputeRoadGroups(state.grid, state.blocks, state.roadGroups);
  state.vehicles = bindVehiclesToCurrentRoadGroups(state);
  selectCell(state, cell);
  updateMood(state);
  return true;
}

export function placeSelectedVehicle(
  state: AppState,
  cell: GridCell | null,
  routeStopIds: string[] = [],
  vehicleName = "",
  selectAfterCreate = true,
  routeBuildingIds: string[] = [],
): boolean {
  if (!cell || !isVehicleTool(state.selectedTool)) return false;
  const roadGroup = findRoadGroupForCell(state.roadGroups, cell);
  if (!roadGroup) return false;
  const defaults = VEHICLE_DEFAULTS[state.selectedTool];
  const validRouteStopIds = state.selectedTool === "bus" ? cleanRouteStopIds(state, routeStopIds) : [];
  const validRouteBuildingIds = state.selectedTool === "sedan" ? cleanRouteBuildingIds(state, routeBuildingIds) : [];
  const cleanName = vehicleName.trim();
  const vehicle: CityVehicle = {
    id: `vehicle-${Date.now()}-${state.vehicles.length + 1}`,
    type: state.selectedTool,
    name: cleanName || `${defaults.name} ${state.vehicles.length + 1}`,
    cell,
    roadGroupId: roadGroup.id,
    progress: 0,
    speed: defaults.speed,
    ...(validRouteStopIds.length >= 2
        ? {
            routeStopIds: validRouteStopIds,
            routeDirection: 1,
            currentStopIndex: 0,
            dwellMs: 0,
            passengerPulseMs: 0,
          passengerLoad: 0,
        }
      : {}),
    ...(validRouteBuildingIds.length >= 2
        ? {
            routeBuildingIds: validRouteBuildingIds,
            routeDirection: 1,
            currentBuildingIndex: 0,
          }
        : {}),
  };
  state.vehicles = [...state.vehicles, vehicle];
  state.selectedCell = cell;
  state.selectedEntity = selectAfterCreate ? { kind: "vehicle", id: vehicle.id } : null;
  updateMood(state);
  return true;
}

export function renameSelectedEntity(state: AppState, name: string): void {
  if (!state.selectedEntity) return;
  if (state.selectedEntity.kind === "roadGroup") {
    const renamed = renameRoadGroup(state.blocks, state.roadGroups, state.selectedEntity.id, name);
    state.blocks = renamed.blocks;
    state.roadGroups = renamed.groups;
  }
  if (state.selectedEntity.kind === "block") {
    state.blocks = renameBlock(state.blocks, state.selectedEntity.id, name);
  }
  if (state.selectedEntity.kind === "vehicle") {
    const clean = name.trim();
    if (clean) state.vehicles = state.vehicles.map((vehicle) => (vehicle.id === state.selectedEntity?.id ? { ...vehicle, name: clean } : vehicle));
  }
}

export function deleteSelectedCellContent(state: AppState): boolean {
  if (!state.selectedCell) return false;
  const selectedCell = state.selectedCell;
  const key = cellKey(selectedCell);
  const hadBlock = !!state.blocks[key];
  const hadVehicle = state.vehicles.some((vehicle) => vehicle.cell.x === selectedCell.x && vehicle.cell.y === selectedCell.y);
  if (!hadBlock && !hadVehicle) return false;

  const nextBlocks = { ...state.blocks };
  delete nextBlocks[key];
  state.blocks = nextBlocks;
  state.roadGroups = recomputeRoadGroups(state.grid, state.blocks, state.roadGroups);
  state.vehicles = bindVehiclesToCurrentRoadGroups(state).filter((vehicle) => vehicle.cell.x !== selectedCell.x || vehicle.cell.y !== selectedCell.y);
  state.selectedEntity = null;
  updateMood(state);
  return true;
}

export function deleteSelectedVehicle(state: AppState): boolean {
  if (state.vehicles.length === 0) return false;
  const selectedId = state.selectedEntity?.kind === "vehicle" ? state.selectedEntity.id : state.vehicles.at(-1)?.id;
  if (!selectedId) return false;
  const nextVehicles = state.vehicles.filter((vehicle) => vehicle.id !== selectedId);
  if (nextVehicles.length === state.vehicles.length) return false;
  state.vehicles = nextVehicles;
  state.selectedEntity = null;
  updateMood(state);
  return true;
}

export function resetCityState(state: AppState): void {
  const mood = scoreCity(createEmptyBlocks(), [], [], "sunny", false);
  state.running = true;
  state.weather = "sunny";
  state.night = false;
  state.score = mood.score;
  state.cityMood = mood.cityMood;
  state.selectedTool = "road";
  state.savedAt = null;
  state.vehicles = [];
  state.elapsedMs = 0;
  state.showCityCheck = false;
  state.statusCollapsed = false;
  state.camera = DEFAULT_CAMERA;
  state.blocks = createEmptyBlocks();
  state.roadGroups = [];
  state.selectedCell = null;
  state.selectedEntity = null;
  state.loadedFromStorage = false;
}

export function replaceStateFromSave(state: AppState): void {
  const savedCity = loadCitySave();
  resetCityState(state);
  if (!savedCity) return;
  const roadGroups = recomputeRoadGroups(DEFAULT_GRID, savedCity.blocks, savedCity.roadGroups);
  const mood = scoreCity(savedCity.blocks, roadGroups, savedCity.vehicles, savedCity.weather, savedCity.night);
  state.weather = savedCity.weather;
  state.night = savedCity.night;
  state.score = mood.score;
  state.cityMood = mood.cityMood;
  state.selectedTool = savedCity.selectedTool;
  state.savedAt = savedCity.savedAt;
  state.vehicles = savedCity.vehicles;
  state.camera = savedCity.camera;
  state.blocks = savedCity.blocks;
  state.roadGroups = roadGroups;
  state.loadedFromStorage = true;
}

export function routeForVehicles(state: AppState): Point[] {
  const group = longestRoadGroup(state.roadGroups);
  if (!group || group.cells.length < 3) return [];
  return routePointsForGroup(state.grid, group);
}

export function busStopsInCity(state: AppState): { id: string; name: string; cell: GridCell }[] {
  return Object.values(state.blocks)
    .filter((block) => block.type === "busStop")
    .sort((a, b) => a.cell.y - b.cell.y || a.cell.x - b.cell.x)
    .map((block) => ({ id: block.id, name: block.name, cell: block.cell }));
}

function updateVehicle(state: AppState, vehicle: CityVehicle, deltaMs: number, weatherFactor: number): void {
  if (vehicle.type === "bus" && hasValidBusRoute(state, vehicle)) {
    const direction = vehicle.routeDirection ?? 1;
    if (!hasReachableRouteSegment(state, vehicle.routeStopIds!, vehicle.currentStopIndex ?? 0, direction)) {
      const reverseDirection = reversedRouteDirection(direction);
      if (hasReachableRouteSegment(state, vehicle.routeStopIds!, vehicle.currentStopIndex ?? 0, reverseDirection)) {
        vehicle.routeDirection = reverseDirection;
      } else {
        vehicle.progress = 0;
        return;
      }
      vehicle.progress = 0;
    }
    vehicle.passengerPulseMs = Math.max(0, (vehicle.passengerPulseMs ?? 0) - deltaMs);
    if ((vehicle.dwellMs ?? 0) > 0) {
      vehicle.dwellMs = Math.max(0, (vehicle.dwellMs ?? 0) - deltaMs);
      return;
    }
    vehicle.progress += vehicle.speed * deltaMs * weatherFactor;
    if (vehicle.progress >= 1) {
      vehicle.progress = 0;
      vehicle.currentStopIndex = nextRouteIndex(vehicle.routeStopIds!.length, vehicle.currentStopIndex ?? 0, vehicle.routeDirection ?? 1);
      vehicle.dwellMs = BUS_DWELL_MS;
      vehicle.passengerPulseMs = PASSENGER_PULSE_MS;
      vehicle.passengerLoad = ((vehicle.passengerLoad ?? 0) + 3) % 18;
    }
    return;
  }
  if (vehicle.type === "sedan" && hasValidBuildingRoute(state, vehicle)) {
    const direction = vehicle.routeDirection ?? 1;
    if (!hasReachableRouteSegment(state, vehicle.routeBuildingIds!, vehicle.currentBuildingIndex ?? 0, direction)) {
      const reverseDirection = reversedRouteDirection(direction);
      if (hasReachableRouteSegment(state, vehicle.routeBuildingIds!, vehicle.currentBuildingIndex ?? 0, reverseDirection)) {
        vehicle.routeDirection = reverseDirection;
      } else {
        vehicle.progress = 0;
        return;
      }
      vehicle.progress = 0;
    }
    vehicle.progress += vehicle.speed * deltaMs * weatherFactor;
    if (vehicle.progress >= 1) {
      vehicle.progress = 0;
      vehicle.currentBuildingIndex = nextRouteIndex(vehicle.routeBuildingIds!.length, vehicle.currentBuildingIndex ?? 0, vehicle.routeDirection ?? 1);
    }
    return;
  }
  if (vehicle.routeCellPath && vehicle.routeCellPath.length >= 2) {
    vehicle.progress = (vehicle.progress + vehicle.speed * deltaMs * weatherFactor) % 1;
    return;
  }
  const nextProgress = vehicle.progress + vehicle.speed * deltaMs * weatherFactor;
  vehicle.progress = progressAfterTrafficLights(state, vehicle, nextProgress);
}

function nextRouteIndex(length: number, currentIndex: number, direction: 1 | -1): number {
  return (currentIndex + direction + length) % length;
}

function reversedRouteDirection(direction: 1 | -1): 1 | -1 {
  return direction === 1 ? -1 : 1;
}

function cleanRouteStopIds(state: AppState, routeStopIds: string[]): string[] {
  const knownStops = new Set(busStopsInCity(state).map((stop) => stop.id));
  const clean: string[] = [];
  for (const stopId of routeStopIds) {
    if (!knownStops.has(stopId) || clean.includes(stopId)) continue;
    clean.push(stopId);
  }
  return clean;
}

function hasValidBusRoute(state: AppState, vehicle: CityVehicle): boolean {
  if (!vehicle.routeStopIds || vehicle.routeStopIds.length < 2) return false;
  const knownStops = new Set(busStopsInCity(state).map((stop) => stop.id));
  return vehicle.routeStopIds.every((stopId) => knownStops.has(stopId));
}

export function buildingsInCity(state: AppState): { id: string; name: string; cell: GridCell }[] {
  return Object.values(state.blocks)
    .filter((block) => block.type === "building")
    .sort((a, b) => a.cell.y - b.cell.y || a.cell.x - b.cell.x)
    .map((block) => ({ id: block.id, name: block.name, cell: block.cell }));
}

function cleanRouteBuildingIds(state: AppState, routeBuildingIds: string[]): string[] {
  const knownBuildings = new Set(buildingsInCity(state).map((building) => building.id));
  const clean: string[] = [];
  for (const buildingId of routeBuildingIds) {
    if (!knownBuildings.has(buildingId) || clean.includes(buildingId)) continue;
    clean.push(buildingId);
  }
  return clean;
}

function hasValidBuildingRoute(state: AppState, vehicle: CityVehicle): boolean {
  if (!vehicle.routeBuildingIds || vehicle.routeBuildingIds.length < 2) return false;
  const knownBuildings = new Set(buildingsInCity(state).map((building) => building.id));
  return vehicle.routeBuildingIds.every((buildingId) => knownBuildings.has(buildingId));
}

function progressAfterTrafficLights(state: AppState, vehicle: CityVehicle, nextProgress: number): number {
  const group = state.roadGroups.find((item) => item.id === vehicle.roadGroupId) ?? findRoadGroupForCell(state.roadGroups, vehicle.cell);
  if (!group || group.cells.length < 2) return 0;
  const direction = roadGroupDirection(group);
  if (!direction || isTrafficLightGreen(state.elapsedMs, direction)) return nextProgress % 1;
  const routeLength = group.cells.length > 2 ? group.cells.length * 2 - 2 : group.cells.length;
  for (let index = 1; index < group.cells.length; index += 1) {
    const block = getBlock(state.blocks, group.cells[index]);
    if (block?.type !== "trafficLight") continue;
    const lightProgress = index / routeLength;
    if (vehicle.progress < lightProgress && nextProgress >= lightProgress) {
      return Math.max(vehicle.progress, lightProgress - 0.03);
    }
  }
  return nextProgress % 1;
}

function bindVehiclesToCurrentRoadGroups(state: AppState): CityVehicle[] {
  const vehicles: CityVehicle[] = [];
  for (const vehicle of state.vehicles) {
    const group = findRoadGroupForCell(state.roadGroups, vehicle.cell);
    if (!group) continue;
    const routeCellPath = routeCellPathFromCell(state, vehicle.cell);
    vehicles.push({
      ...vehicle,
      roadGroupId: group.id,
      routeCellPath: routeCellPath.length >= 2 ? routeCellPath : undefined,
      progress: group.cells.length < 2 ? 0 : vehicle.progress,
    });
  }
  return vehicles;
}

function hasReachableRouteSegment(state: AppState, routeBlockIds: string[], currentIndex: number, direction: 1 | -1 = 1): boolean {
  if (routeBlockIds.length < 2) return false;
  const current = blockById(state, routeBlockIds[currentIndex % routeBlockIds.length]);
  const next = blockById(state, routeBlockIds[nextRouteIndex(routeBlockIds.length, currentIndex, direction)]);
  if (!current || !next) return false;
  const drivableCells = Object.values(state.blocks).filter((block) => isDrivableBlockType(block.type)).map((block) => block.cell);
  const start = routeAccessCell(state, drivableCells, current.cell);
  const end = routeAccessCell(state, drivableCells, next.cell);
  return !!start && !!end && hasCellPath(drivableCells, start, end);
}

function blockById(state: AppState, id: string): { cell: GridCell } | null {
  return Object.values(state.blocks).find((block) => block.id === id) ?? null;
}

function nearestDrivableCell(cells: GridCell[], target: GridCell): GridCell | null {
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

function routeAccessCell(state: AppState, cells: GridCell[], target: GridCell): GridCell | null {
  const drivableKeys = new Set(cells.map((cell) => cellKey(cell)));
  const adjacent = neighboringCells(target);
  const adjacentDrivable = adjacent.find((cell) => drivableKeys.has(cellKey(cell)));
  if (adjacentDrivable) return adjacentDrivable;
  const hasAdjacentBlockedBlock = adjacent.some((cell) => {
    const block = getBlock(state.blocks, cell);
    return block && !isDrivableBlockType(block.type);
  });
  return hasAdjacentBlockedBlock ? null : nearestDrivableCell(cells, target);
}

function routeCellPathFromCell(state: AppState, start: GridCell): GridCell[] {
  const drivableCells = Object.values(state.blocks).filter((block) => isDrivableBlockType(block.type)).map((block) => block.cell);
  const drivableKeys = new Set(drivableCells.map((cell) => cellKey(cell)));
  const startKey = cellKey(start);
  if (!drivableKeys.has(startKey)) return [];
  const visited = new Set<string>();
  const route: GridCell[] = [];
  const queue = [start];
  for (let index = 0; index < queue.length; index += 1) {
    const cell = queue[index];
    const key = cellKey(cell);
    if (visited.has(key)) continue;
    visited.add(key);
    route.push(cell);
    for (const next of neighboringCells(cell)) {
      if (drivableKeys.has(cellKey(next)) && !visited.has(cellKey(next))) queue.push(next);
    }
  }
  return route;
}

function hasCellPath(cells: GridCell[], start: GridCell, end: GridCell): boolean {
  const available = new Set(cells.map((cell) => cellKey(cell)));
  const endKey = cellKey(end);
  const queue = [start];
  const visited = new Set<string>();
  for (let index = 0; index < queue.length; index += 1) {
    const cell = queue[index];
    const key = cellKey(cell);
    if (visited.has(key)) continue;
    if (key === endKey) return true;
    visited.add(key);
    for (const next of neighboringCells(cell)) {
      if (available.has(cellKey(next)) && !visited.has(cellKey(next))) queue.push(next);
    }
  }
  return false;
}

function neighboringCells(cell: GridCell): GridCell[] {
  return [
    { x: cell.x + 1, y: cell.y },
    { x: cell.x, y: cell.y + 1 },
    { x: cell.x - 1, y: cell.y },
    { x: cell.x, y: cell.y - 1 },
  ];
}

function roadGroupDirection(group: { cells: GridCell[] }): "horizontal" | "vertical" | null {
  const first = group.cells[0];
  const last = group.cells[group.cells.length - 1];
  if (first.y === last.y) return "horizontal";
  if (first.x === last.x) return "vertical";
  return null;
}

function isTrafficLightGreen(elapsedMs: number, direction: "horizontal" | "vertical"): boolean {
  const horizontalGreen = Math.floor(elapsedMs / 3000) % 2 === 0;
  return direction === "horizontal" ? horizontalGreen : !horizontalGreen;
}

function deriveMood(state: AppState): Pick<AppState, "cityMood" | "score"> {
  return scoreCity(state.blocks, state.roadGroups, state.vehicles, state.weather, state.night);
}

function scoreCity(blocks: AppState["blocks"], roadGroups: AppState["roadGroups"], vehicles: AppState["vehicles"], weather: Weather, night: boolean): Pick<AppState, "cityMood" | "score"> {
  const counts = blockCounts(blocks);
  const routedBuses = vehicles.filter((vehicle) => vehicle.type === "bus" && (vehicle.routeStopIds?.length ?? 0) >= 2).length;
  const roadConnectivity = roadGroups.reduce((total, group) => total + Math.max(0, group.cells.length - 1), 0);
  const drivableCount = counts.road + counts.overpass + counts.trafficLight;
  const balanceBonus = Math.min(drivableCount, counts.building + counts.park + counts.busStop) * 2;
  let score = 50;
  score += Math.min(18, drivableCount * 3 + roadConnectivity);
  score += Math.min(14, counts.building * 4);
  score += Math.min(12, counts.park * 5);
  score += Math.min(12, counts.busStop * 4 + routedBuses * 4);
  score += Math.min(8, vehicles.length * 2);
  score += Math.min(8, balanceBonus);
  if (drivableCount > 0 && vehicles.length === 0) score -= 4;
  if (counts.roadwork > 0) score -= Math.min(6, counts.roadwork * 2);
  if (counts.building >= 3 && counts.park === 0) score -= 6;
  if (counts.busStop >= 2 && routedBuses === 0) score -= 5;
  if (weather === "rainy") score -= 4;
  if (weather === "snowy") score -= 7;
  if (night) score -= 2;
  const finalScore = Math.max(45, Math.min(100, Math.round(score)));
  return { score: finalScore, cityMood: cityMoodForScore(finalScore, weather, night, routedBuses) };
}

function cityMoodForScore(score: number, weather: Weather, night: boolean, routedBuses: number): string {
  if (weather === "snowy") return score >= 82 ? "雪天稳行" : "雪天注意";
  if (weather === "rainy") return score >= 82 ? "雨中有序" : "雨天慢行";
  if (routedBuses > 0 && score >= 85) return "公交顺畅";
  if (score >= 90) return "很棒";
  if (score >= 78) return night ? "夜色安静" : "顺畅";
  if (score >= 65) return "还在成长";
  return "需要规划";
}
