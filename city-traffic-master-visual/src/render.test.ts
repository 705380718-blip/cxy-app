import { describe, expect, it } from "vitest";
import { cellCenter } from "./grid";
import { lineNumberForVehicleName, pointForCityVehicle } from "./render";
import { createInitialState, placeSelectedBlock, placeSelectedVehicle } from "./state";

describe("vehicle rendering positions", () => {
  it("keeps a routed bus on the road next to selected bus stops", () => {
    const state = createInitialState();
    state.selectedTool = "road";
    for (const x of [0, 1, 2, 3]) placeSelectedBlock(state, { x, y: 2 });
    state.selectedTool = "busStop";
    placeSelectedBlock(state, { x: 0, y: 1 });
    placeSelectedBlock(state, { x: 3, y: 1 });
    const stops = Object.values(state.blocks).filter((block) => block.type === "busStop");

    state.selectedTool = "bus";
    placeSelectedVehicle(state, { x: 0, y: 2 }, stops.map((stop) => stop.id));
    const vehicle = state.vehicles[0];
    const group = state.roadGroups.find((item) => item.id === vehicle.roadGroupId)!;

    const atFirstStop = pointForCityVehicle(state, { ...vehicle, progress: 0 }, group);
    const halfway = pointForCityVehicle(state, { ...vehicle, progress: 0.5 }, group);

    expect(atFirstStop.y).toBe(cellCenter(state.grid, { x: 0, y: 2 }).y);
    expect(halfway.y).toBe(cellCenter(state.grid, { x: 1, y: 2 }).y);
  });

  it("routes a bus to a selected stop on a connected road branch instead of an unselected middle stop", () => {
    const state = createInitialState();
    state.selectedTool = "road";
    for (const x of [0, 1, 2]) placeSelectedBlock(state, { x, y: 0 });
    for (const y of [1, 2]) placeSelectedBlock(state, { x: 2, y });
    state.selectedTool = "busStop";
    placeSelectedBlock(state, { x: 0, y: 1 });
    placeSelectedBlock(state, { x: 1, y: 1 });
    placeSelectedBlock(state, { x: 3, y: 2 });
    const stops = Object.values(state.blocks).filter((block) => block.type === "busStop");
    const [stop1, stop2, stop3] = stops;

    state.selectedTool = "bus";
    placeSelectedVehicle(state, { x: 0, y: 0 }, [stop1.id, stop3.id], "17路");
    const vehicle = state.vehicles[0];
    const group = state.roadGroups.find((item) => item.id === vehicle.roadGroupId)!;

    const destination = pointForCityVehicle(state, { ...vehicle, progress: 1 }, group);

    expect(vehicle.routeStopIds).not.toContain(stop2.id);
    expect(destination).toEqual(cellCenter(state.grid, { x: 2, y: 2 }));
  });

  it("extracts a short route number for the bus body", () => {
    expect(lineNumberForVehicleName("17路")).toBe("17");
    expect(lineNumberForVehicleName("公交快线 102")).toBe("102");
    expect(lineNumberForVehicleName("校车")).toBe("校车");
  });

  it("moves a sedan along the road route between two buildings", () => {
    const state = createInitialState();
    state.selectedTool = "road";
    for (const x of [0, 1, 2, 3, 4]) placeSelectedBlock(state, { x, y: 0 });
    state.selectedTool = "building";
    placeSelectedBlock(state, { x: 0, y: 1 });
    placeSelectedBlock(state, { x: 4, y: 1 });
    const buildings = Object.values(state.blocks).filter((block) => block.type === "building");
    state.selectedTool = "sedan";
    placeSelectedVehicle(state, { x: 0, y: 0 }, [], "红色小车", true, buildings.map((building) => building.id));

    const vehicle = state.vehicles[0];
    const halfway = pointForCityVehicle(state, { ...vehicle, progress: 0.5 }, state.roadGroups[0]);

    expect(Math.round(halfway.y)).toBe(28);
    expect(Math.round(halfway.x)).toBeGreaterThan(80);
    expect(Math.round(halfway.x)).toBeLessThan(200);
  });
});
