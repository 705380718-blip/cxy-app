export type Weather = "sunny" | "rainy" | "snowy";
export type BlockTool = "road" | "overpass" | "roadwork" | "trafficLight" | "building" | "park" | "busStop";
export type OverpassDirection = "horizontal" | "vertical";
export type VehicleType = "sedan" | "bus" | "offroad" | "sweeper";
export type Tool = BlockTool | VehicleType;
export type BlockType = "empty" | BlockTool;
export type EntityKind = "block" | "roadGroup" | "vehicle";

export interface DemoVehicle {
  id: string;
  color: string;
  pathId: string;
  progress: number;
  speed: number;
}

export interface AppState {
  running: boolean;
  weather: Weather;
  night: boolean;
  score: number;
  selectedTool: Tool;
  savedAt: string | null;
  cityMood: string;
  elapsedMs: number;
  showCityCheck: boolean;
  statusCollapsed: boolean;
  grid: GridConfig;
  camera: Camera;
  blocks: CityBlocks;
  roadGroups: RoadGroup[];
  selectedCell: GridCell | null;
  selectedEntity: SelectedEntity | null;
  loadedFromStorage: boolean;
  vehicles: CityVehicle[];
}

export interface Point {
  x: number;
  y: number;
}

export interface Building {
  id: string;
  x: number;
  y: number;
  w: number;
  h: number;
  color: string;
  roof: string;
  windows: number;
}

export interface Tree {
  x: number;
  y: number;
  r: number;
}

export interface Light {
  x: number;
  y: number;
}

export interface VehiclePath {
  id: string;
  points: Point[];
}

export interface GridConfig {
  cellSize: number;
}

export interface GridCell {
  x: number;
  y: number;
}

export type CityBlocks = Record<string, CityBlock>;

export interface CityBlock {
  id: string;
  type: BlockTool;
  cell: GridCell;
  name: string;
  overpassDirection?: OverpassDirection;
}

export interface Camera {
  x: number;
  y: number;
  zoom: number;
}

export interface SelectedEntity {
  kind: EntityKind;
  id: string;
}

export interface RoadGroup {
  id: string;
  name: string;
  cells: GridCell[];
}

export interface CityVehicle {
  id: string;
  type: VehicleType;
  name: string;
  cell: GridCell;
  roadGroupId: string | null;
  progress: number;
  speed: number;
  routeStopIds?: string[];
  routeBuildingIds?: string[];
  routeDirection?: 1 | -1;
  routeCellPath?: GridCell[];
  currentStopIndex?: number;
  currentBuildingIndex?: number;
  dwellMs?: number;
  passengerPulseMs?: number;
  passengerLoad?: number;
}
