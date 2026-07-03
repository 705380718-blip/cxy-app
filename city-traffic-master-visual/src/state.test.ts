import { describe, expect, it } from "vitest";
import { blockCounts } from "./blocks";
import { createInitialState, deleteSelectedCellContent, deleteSelectedVehicle, placeSelectedBlock, placeSelectedVehicle, resetCityState, selectCell, updateMood, updateState } from "./state";

describe("city state editing", () => {
  it("deletes the selected block and vehicles anchored to that cell", () => {
    const state = createInitialState();
    state.selectedTool = "road";
    placeSelectedBlock(state, { x: 0, y: 0 });
    placeSelectedBlock(state, { x: 1, y: 0 });
    state.selectedTool = "bus";
    placeSelectedVehicle(state, { x: 0, y: 0 });

    selectCell(state, { x: 0, y: 0 });
    const deleted = deleteSelectedCellContent(state);

    expect(deleted).toBe(true);
    expect(blockCounts(state.blocks).road).toBe(1);
    expect(state.vehicles).toHaveLength(0);
    expect(state.selectedCell).toEqual({ x: 0, y: 0 });
    expect(state.selectedEntity).toBeNull();
  });

  it("resets a built city to an empty editable state", () => {
    const state = createInitialState();
    state.selectedTool = "building";
    placeSelectedBlock(state, { x: 4, y: -2 });
    state.weather = "rainy";
    state.night = true;
    state.camera = { x: 200, y: -120, zoom: 1.6 };

    resetCityState(state);

    expect(blockCounts(state.blocks)).toEqual({ empty: 0, road: 0, overpass: 0, roadwork: 0, trafficLight: 0, building: 0, park: 0, busStop: 0 });
    expect(state.vehicles).toEqual([]);
    expect(state.roadGroups).toEqual([]);
    expect(state.weather).toBe("sunny");
    expect(state.night).toBe(false);
    expect(state.selectedTool).toBe("road");
    expect(state.camera).toEqual({ x: 0, y: 0, zoom: 1 });
  });

  it("deletes the selected vehicle without deleting its road cell", () => {
    const state = createInitialState();
    state.selectedTool = "road";
    placeSelectedBlock(state, { x: 0, y: 0 });
    placeSelectedBlock(state, { x: 1, y: 0 });
    state.selectedTool = "sedan";
    placeSelectedVehicle(state, { x: 0, y: 0 });

    const deleted = deleteSelectedVehicle(state);

    expect(deleted).toBe(true);
    expect(state.vehicles).toHaveLength(0);
    expect(blockCounts(state.blocks).road).toBe(2);
    expect(state.selectedEntity).toBeNull();
  });

  it("places an overpass over an existing selected road cell", () => {
    const state = createInitialState();
    state.selectedTool = "road";
    placeSelectedBlock(state, { x: 0, y: 0 });
    selectCell(state, { x: 0, y: 0 });

    state.selectedTool = "overpass";
    const placed = placeSelectedBlock(state, { x: 0, y: 0 });

    expect(placed).toBe(true);
    expect(Object.values(state.blocks).find((block) => block.cell.x === 0 && block.cell.y === 0)?.type).toBe("overpass");
    expect(state.roadGroups[0].cells).toEqual([{ x: 0, y: 0 }]);
  });

  it("places an overpass with a vertical direction", () => {
    const state = createInitialState();
    state.selectedTool = "overpass";

    const placed = placeSelectedBlock(state, { x: 0, y: 0 }, "vertical");

    expect(placed).toBe(true);
    expect(Object.values(state.blocks).find((block) => block.type === "overpass")?.overpassDirection).toBe("vertical");
  });

  it("selects an overpass as part of its road segment for one-time naming", () => {
    const state = createInitialState();
    state.selectedTool = "road";
    placeSelectedBlock(state, { x: 0, y: 0 });
    placeSelectedBlock(state, { x: 1, y: 0 });
    placeSelectedBlock(state, { x: 2, y: 0 });
    state.selectedTool = "overpass";
    placeSelectedBlock(state, { x: 1, y: 0 }, "vertical");

    selectCell(state, { x: 1, y: 0 });

    expect(state.selectedEntity).toEqual({ kind: "roadGroup", id: "road-line-h-0-0" });
    expect(state.roadGroups).toHaveLength(1);
    expect(state.roadGroups[0].cells).toEqual([
      { x: 0, y: 0 },
      { x: 1, y: 0 },
      { x: 2, y: 0 },
    ]);
  });

  it("creates a bus route from the chosen stops in order", () => {
    const state = createInitialState();
    state.selectedTool = "road";
    placeSelectedBlock(state, { x: 0, y: 0 });
    placeSelectedBlock(state, { x: 1, y: 0 });
    state.selectedTool = "busStop";
    placeSelectedBlock(state, { x: 0, y: 1 });
    placeSelectedBlock(state, { x: 4, y: 1 });
    const stops = Object.values(state.blocks).filter((block) => block.type === "busStop");

    state.selectedTool = "bus";
    const placed = placeSelectedVehicle(state, { x: 0, y: 0 }, [stops[1].id, stops[0].id]);

    expect(placed).toBe(true);
    expect(state.vehicles[0]).toMatchObject({
      type: "bus",
      routeStopIds: [stops[1].id, stops[0].id],
      currentStopIndex: 0,
      dwellMs: 0,
    });
  });

  it("uses the child-entered bus line name when creating a route", () => {
    const state = createInitialState();
    state.selectedTool = "road";
    placeSelectedBlock(state, { x: 0, y: 0 });
    placeSelectedBlock(state, { x: 1, y: 0 });
    state.selectedTool = "busStop";
    placeSelectedBlock(state, { x: 0, y: 1 });
    placeSelectedBlock(state, { x: 4, y: 1 });
    const stops = Object.values(state.blocks).filter((block) => block.type === "busStop");

    state.selectedTool = "bus";
    placeSelectedVehicle(state, { x: 0, y: 0 }, stops.map((stop) => stop.id), "17路");

    expect(state.vehicles[0].name).toBe("17路");
  });

  it("creates a sedan route from one building to another", () => {
    const state = createInitialState();
    state.selectedTool = "road";
    for (const x of [0, 1, 2, 3, 4]) placeSelectedBlock(state, { x, y: 0 });
    state.selectedTool = "building";
    placeSelectedBlock(state, { x: 0, y: 1 });
    placeSelectedBlock(state, { x: 4, y: 1 });
    const buildings = Object.values(state.blocks).filter((block) => block.type === "building");

    state.selectedTool = "sedan";
    const placed = placeSelectedVehicle(state, { x: 0, y: 0 }, [], "", true, buildings.map((building) => building.id));

    expect(placed).toBe(true);
    expect(state.vehicles[0]).toMatchObject({
      type: "sedan",
      routeBuildingIds: buildings.map((building) => building.id),
      currentBuildingIndex: 0,
    });
  });

  it("stops a vehicle before a red traffic light and releases it on green", () => {
    const state = createInitialState();
    state.selectedTool = "road";
    placeSelectedBlock(state, { x: 0, y: 0 });
    placeSelectedBlock(state, { x: 2, y: 0 });
    state.selectedTool = "trafficLight";
    placeSelectedBlock(state, { x: 1, y: 0 });
    state.selectedTool = "sedan";
    placeSelectedVehicle(state, { x: 0, y: 0 });
    const vehicle = state.vehicles[0];
    vehicle.progress = 0.2;

    state.elapsedMs = 3500;
    updateState(state, 1000);
    const stoppedProgress = vehicle.progress;

    expect(stoppedProgress).toBeLessThanOrEqual(0.23);

    state.elapsedMs = 0;
    updateState(state, 1000);

    expect(vehicle.progress).toBeGreaterThan(stoppedProgress);
  });

  it("reroutes an existing vehicle onto a bypass when roadwork breaks its road segment", () => {
    const state = createInitialState();
    state.selectedTool = "road";
    for (const cell of [
      { x: 0, y: 0 },
      { x: 1, y: 0 },
      { x: 2, y: 0 },
      { x: 0, y: 1 },
      { x: 1, y: 1 },
      { x: 2, y: 1 },
    ]) {
      placeSelectedBlock(state, cell);
    }
    state.selectedTool = "offroad";
    placeSelectedVehicle(state, { x: 0, y: 0 });
    state.selectedTool = "roadwork";
    placeSelectedBlock(state, { x: 1, y: 0 });

    updateState(state, 5000);

    expect(state.vehicles[0].routeCellPath).toEqual(
      expect.arrayContaining([
        { x: 0, y: 1 },
        { x: 1, y: 1 },
        { x: 2, y: 1 },
      ]),
    );
    expect(state.vehicles[0].routeCellPath).not.toContainEqual({ x: 1, y: 0 });
    expect(state.vehicles[0].progress).toBeGreaterThan(0);
  });

  it("turns a routed bus back to the previous reachable stop when roadwork blocks the next stop", () => {
    const state = createInitialState();
    state.selectedTool = "road";
    for (const cell of [
      { x: 0, y: 0 },
      { x: 1, y: 0 },
      { x: 2, y: 0 },
      { x: 0, y: 1 },
      { x: 1, y: 1 },
      { x: 2, y: 1 },
    ]) {
      placeSelectedBlock(state, cell);
    }
    state.selectedTool = "busStop";
    placeSelectedBlock(state, { x: 0, y: -1 });
    placeSelectedBlock(state, { x: 1, y: -1 });
    placeSelectedBlock(state, { x: 2, y: 2 });
    const stops = Object.values(state.blocks).filter((block) => block.type === "busStop");
    const [stopA, stopB, stopC] = stops;
    state.selectedTool = "bus";
    placeSelectedVehicle(state, { x: 0, y: 0 }, [stopA.id, stopB.id, stopC.id]);
    state.selectedTool = "roadwork";
    placeSelectedBlock(state, { x: 1, y: 0 });
    state.vehicles[0].progress = 0.99;

    updateState(state, 1000);

    expect(state.vehicles[0].routeDirection).toBe(-1);
    expect(state.vehicles[0].currentStopIndex).toBe(0);
    expect(state.vehicles[0].progress).toBeGreaterThan(0);

    updateState(state, 30000);

    expect(state.vehicles[0].currentStopIndex).toBe(2);
    expect(state.vehicles[0].progress).toBe(0);
  });

  it("can skip selecting a named routed bus after creation", () => {
    const state = createInitialState();
    state.selectedTool = "road";
    placeSelectedBlock(state, { x: 0, y: 0 });
    placeSelectedBlock(state, { x: 1, y: 0 });
    state.selectedTool = "busStop";
    placeSelectedBlock(state, { x: 0, y: 1 });
    placeSelectedBlock(state, { x: 4, y: 1 });
    const stops = Object.values(state.blocks).filter((block) => block.type === "busStop");

    state.selectedTool = "bus";
    placeSelectedVehicle(state, { x: 0, y: 0 }, stops.map((stop) => stop.id), "17路", false);

    expect(state.vehicles[0].name).toBe("17路");
    expect(state.selectedEntity).toBeNull();
  });

  it("holds a routed bus at each stop with passenger boarding animation", () => {
    const state = createInitialState();
    state.selectedTool = "road";
    placeSelectedBlock(state, { x: 0, y: 0 });
    placeSelectedBlock(state, { x: 1, y: 0 });
    state.selectedTool = "busStop";
    placeSelectedBlock(state, { x: 0, y: 1 });
    placeSelectedBlock(state, { x: 4, y: 1 });
    const stops = Object.values(state.blocks).filter((block) => block.type === "busStop");

    state.selectedTool = "bus";
    placeSelectedVehicle(state, { x: 0, y: 0 }, stops.map((stop) => stop.id));
    state.vehicles[0].progress = 0.99;

    updateState(state, 1000);

    expect(state.vehicles[0].currentStopIndex).toBe(1);
    expect(state.vehicles[0].progress).toBe(0);
    expect(state.vehicles[0].dwellMs).toBeGreaterThan(0);
    expect(state.vehicles[0].passengerPulseMs).toBeGreaterThan(0);

    updateState(state, 5000);

    expect(state.vehicles[0].dwellMs).toBe(0);
    expect(state.vehicles[0].currentStopIndex).toBe(1);
  });

  it("skips unselected middle stops when looping through chosen bus stops", () => {
    const state = createInitialState();
    state.selectedTool = "road";
    for (const x of [0, 1, 2, 3, 4]) placeSelectedBlock(state, { x, y: 0 });
    state.selectedTool = "busStop";
    placeSelectedBlock(state, { x: 0, y: 1 });
    placeSelectedBlock(state, { x: 2, y: 1 });
    placeSelectedBlock(state, { x: 4, y: 1 });
    const stops = Object.values(state.blocks).filter((block) => block.type === "busStop");
    const [stop1, stop2, stop3] = stops;

    state.selectedTool = "bus";
    placeSelectedVehicle(state, { x: 0, y: 0 }, [stop1.id, stop3.id], "17路");
    state.vehicles[0].progress = 0.99;

    updateState(state, 1000);

    expect(state.vehicles[0].routeStopIds).toEqual([stop1.id, stop3.id]);
    expect(state.vehicles[0].routeStopIds).not.toContain(stop2.id);
    expect(state.vehicles[0].currentStopIndex).toBe(1);
    expect(state.vehicles[0].passengerPulseMs).toBeGreaterThan(0);
  });

  it("scores the city from the actual building and traffic setup", () => {
    const empty = createInitialState();
    updateMood(empty);

    const built = createInitialState();
    built.selectedTool = "road";
    for (const x of [0, 1, 2, 3]) placeSelectedBlock(built, { x, y: 0 });
    built.selectedTool = "building";
    placeSelectedBlock(built, { x: 0, y: 1 });
    placeSelectedBlock(built, { x: 1, y: 1 });
    built.selectedTool = "park";
    placeSelectedBlock(built, { x: 2, y: 1 });
    built.selectedTool = "busStop";
    placeSelectedBlock(built, { x: 0, y: -1 });
    placeSelectedBlock(built, { x: 3, y: -1 });
    const stops = Object.values(built.blocks).filter((block) => block.type === "busStop");
    built.selectedTool = "bus";
    placeSelectedVehicle(built, { x: 0, y: 0 }, stops.map((stop) => stop.id), "17路", false);
    updateMood(built);

    expect(built.score).toBeGreaterThan(empty.score);
    expect(built.cityMood).not.toBe(empty.cityMood);
  });

  it("refreshes the city score immediately after editing blocks and vehicles", () => {
    const state = createInitialState();
    const initialScore = state.score;

    state.selectedTool = "road";
    placeSelectedBlock(state, { x: 0, y: 0 });
    placeSelectedBlock(state, { x: 1, y: 0 });
    state.selectedTool = "building";
    placeSelectedBlock(state, { x: 0, y: 1 });

    expect(state.score).not.toBe(initialScore);
  });
});
