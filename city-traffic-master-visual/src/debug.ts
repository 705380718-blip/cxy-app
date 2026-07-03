import { blockCounts } from "./blocks";
import { renderCity } from "./render";
import { updateState } from "./state";
import type { AppState } from "./types";

const FRAME_MS = 1000 / 60;
const MAX_STEPS = 600;

declare global {
  interface Window {
    render_game_to_text?: () => string;
    advanceTime?: (ms: number) => void;
  }
}

export function installDebugHooks(state: AppState, canvas: HTMLCanvasElement, enableManualClock: () => void): void {
  window.render_game_to_text = () =>
    JSON.stringify({
      coordinateSystem: "canvas pixels; origin top-left; x right; y down",
      mode: state.running ? "running" : "paused",
      weather: state.weather,
      night: state.night,
      selectedTool: state.selectedTool,
      score: state.score,
      cityMood: state.cityMood,
      camera: {
        x: Number(state.camera.x.toFixed(2)),
        y: Number(state.camera.y.toFixed(2)),
        zoom: Number(state.camera.zoom.toFixed(3)),
      },
      showCityCheck: state.showCityCheck,
      blocks: blockCounts(state.blocks),
      roadGroups: state.roadGroups.map((group) => ({
        id: group.id,
        name: group.name,
        cells: group.cells.length,
      })),
      selectedCell: state.selectedCell,
      selectedEntity: state.selectedEntity,
      loadedFromStorage: state.loadedFromStorage,
      vehicles: state.vehicles.map((vehicle) => ({
        id: vehicle.id,
        type: vehicle.type,
        name: vehicle.name,
        roadGroupId: vehicle.roadGroupId,
        cell: vehicle.cell,
        progress: Number(vehicle.progress.toFixed(3)),
        routeStopIds: vehicle.routeStopIds ?? [],
        routeBuildingIds: vehicle.routeBuildingIds ?? [],
        routeDirection: vehicle.routeDirection ?? 1,
        routeCellPath: vehicle.routeCellPath ?? [],
        currentStopIndex: vehicle.currentStopIndex ?? null,
        currentBuildingIndex: vehicle.currentBuildingIndex ?? null,
        dwellMs: Math.round(vehicle.dwellMs ?? 0),
        passengerPulseMs: Math.round(vehicle.passengerPulseMs ?? 0),
      })),
    });

  window.advanceTime = (ms: number) => {
    if (!Number.isFinite(ms) || ms < 0) {
      throw new TypeError("advanceTime requires a finite non-negative ms value");
    }
    enableManualClock();
    const wholeSteps = Math.floor(ms / FRAME_MS);
    if (wholeSteps > MAX_STEPS) {
      throw new RangeError("advanceTime step count is too large");
    }
    for (let i = 0; i < wholeSteps; i += 1) updateState(state, FRAME_MS);
    const remainder = ms - wholeSteps * FRAME_MS;
    if (remainder > 0) updateState(state, remainder);
    renderCity(canvas, state);
  };
}
