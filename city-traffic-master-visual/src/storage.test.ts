import { beforeEach, describe, expect, it } from "vitest";
import { placeBlock, recomputeRoadGroups, renameBlock } from "./blocks";
import { DEFAULT_CAMERA, DEFAULT_GRID } from "./grid";
import {
  createCitySaveSlot,
  deleteCitySaveSlot,
  findDeletedCitySaveSlot,
  listCitySaveSlots,
  listDeletedCitySaveSlots,
  loadCitySave,
  purgeExpiredDeletedCitySaveSlots,
  restoreDeletedCitySaveSlot,
  saveCity,
  switchCitySaveSlot,
} from "./storage";
import type { CityBlocks } from "./types";

const memoryStorage = new Map<string, string>();

Object.defineProperty(globalThis, "localStorage", {
  value: {
    clear: () => memoryStorage.clear(),
    getItem: (key: string) => memoryStorage.get(key) ?? null,
    removeItem: (key: string) => memoryStorage.delete(key),
    setItem: (key: string, value: string) => {
      memoryStorage.set(key, value);
    },
  },
  configurable: true,
});

describe("city storage", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("saves and loads named blocks, camera, vehicle, weather, night, and selected tool", () => {
    let blocks: CityBlocks = {};
    blocks = placeBlock(blocks, { x: 1, y: 1 }, "road");
    blocks = placeBlock(blocks, { x: 2, y: 1 }, "road");
    blocks = placeBlock(blocks, { x: -4, y: 5 }, "building");
    blocks = placeBlock(blocks, { x: 8, y: -2 }, "park");
    blocks = placeBlock(blocks, { x: 3, y: 1 }, "busStop");
    const building = Object.values(blocks).find((block) => block.type === "building")!;
    const park = Object.values(blocks).find((block) => block.type === "park")!;
    const stop = Object.values(blocks).find((block) => block.type === "busStop")!;
    blocks = renameBlock(blocks, building.id, "图书馆");
    blocks = renameBlock(blocks, park.id, "开心公园");
    blocks = renameBlock(blocks, stop.id, "阳光站");
    const roadGroups = recomputeRoadGroups(DEFAULT_GRID, blocks).map((group) => ({ ...group, name: "彩虹路" }));
    saveCity({
      blocks,
      roadGroups,
      camera: { x: 120, y: -80, zoom: 1.4 },
      vehicles: [{ id: "vehicle-1", type: "bus", name: "蓝色公交", cell: { x: 1, y: 1 }, roadGroupId: roadGroups[0].id, progress: 0.2, speed: 0.00003 }],
      weather: "rainy",
      night: true,
      selectedTool: "bus",
      savedAt: "2026-06-04T00:00:00.000Z",
    });
    const loaded = loadCitySave();
    expect(loaded?.weather).toBe("rainy");
    expect(loaded?.night).toBe(true);
    expect(loaded?.selectedTool).toBe("bus");
    expect(loaded?.camera.zoom).toBe(1.4);
    expect(Object.values(loaded?.blocks ?? {}).map((block) => block.name)).toContain("图书馆");
    expect(Object.values(loaded?.blocks ?? {}).map((block) => block.name)).toContain("开心公园");
    expect(Object.values(loaded?.blocks ?? {}).map((block) => block.name)).toContain("阳光站");
    expect(loaded?.vehicles[0].type).toBe("bus");
  });

  it("saves and loads an overpass direction", () => {
    const blocks = placeBlock({}, { x: 1, y: 1 }, "overpass", "vertical");
    saveCity({
      blocks,
      roadGroups: recomputeRoadGroups(DEFAULT_GRID, blocks),
      camera: DEFAULT_CAMERA,
      vehicles: [],
      weather: "sunny",
      night: false,
      selectedTool: "overpass",
      savedAt: "2026-06-25T00:00:00.000Z",
    });

    const overpass = Object.values(loadCitySave()?.blocks ?? {}).find((block) => block.type === "overpass");
    expect(overpass?.overpassDirection).toBe("vertical");
  });

  it("saves and loads roadwork and traffic light blocks", () => {
    let blocks: CityBlocks = {};
    blocks = placeBlock(blocks, { x: 0, y: 0 }, "road");
    blocks = placeBlock(blocks, { x: 1, y: 0 }, "trafficLight");
    blocks = placeBlock(blocks, { x: 2, y: 0 }, "roadwork");
    saveCity({
      blocks,
      roadGroups: recomputeRoadGroups(DEFAULT_GRID, blocks),
      camera: DEFAULT_CAMERA,
      vehicles: [],
      weather: "sunny",
      night: false,
      selectedTool: "trafficLight",
      savedAt: "2026-07-01T00:00:00.000Z",
    });

    expect(Object.values(loadCitySave()?.blocks ?? {}).map((block) => block.type).sort()).toEqual(["road", "roadwork", "trafficLight"]);
    expect(loadCitySave()?.selectedTool).toBe("trafficLight");
  });

  it("ignores malformed saved data", () => {
    localStorage.setItem("city-traffic-master-first-version", "{bad json");
    expect(loadCitySave()).toBeNull();
  });

  it("requires a valid camera", () => {
    saveCity({
      blocks: {},
      roadGroups: [],
      camera: DEFAULT_CAMERA,
      vehicles: [],
      weather: "sunny",
      night: false,
      selectedTool: "road",
      savedAt: "2026-06-04T00:00:00.000Z",
    });
    const raw = JSON.parse(localStorage.getItem("city-traffic-master-first-version")!);
    raw.camera = { x: "bad", y: 0, zoom: 1 };
    localStorage.setItem("city-traffic-master-first-version", JSON.stringify(raw));
    expect(loadCitySave()).toBeNull();
  });

  it("saves multiple cities and loads the active city", () => {
    let blocks: CityBlocks = {};
    blocks = placeBlock(blocks, { x: 1, y: 1 }, "road");
    saveCity({
      blocks,
      roadGroups: recomputeRoadGroups(DEFAULT_GRID, blocks),
      camera: DEFAULT_CAMERA,
      vehicles: [],
      weather: "sunny",
      night: false,
      selectedTool: "road",
      savedAt: "2026-06-04T00:00:00.000Z",
    });

    const second = createCitySaveSlot("第二座城市");
    switchCitySaveSlot(second.id);
    saveCity({
      blocks: {},
      roadGroups: [],
      camera: { x: 40, y: 20, zoom: 1.2 },
      vehicles: [],
      weather: "snowy",
      night: true,
      selectedTool: "park",
      savedAt: "2026-06-04T00:10:00.000Z",
    });

    const slots = listCitySaveSlots();
    expect(slots.map((slot) => slot.name)).toEqual(["我的城市 1", "第二座城市"]);
    expect(loadCitySave()?.weather).toBe("snowy");
    switchCitySaveSlot(slots[0].id);
    expect(loadCitySave()?.blocks).toEqual(blocks);
  });

  it("keeps the first saved city after creating five city slots", () => {
    let blocks: CityBlocks = {};
    blocks = placeBlock(blocks, { x: 1, y: 1 }, "road");
    saveCity({
      blocks,
      roadGroups: recomputeRoadGroups(DEFAULT_GRID, blocks),
      camera: DEFAULT_CAMERA,
      vehicles: [],
      weather: "sunny",
      night: false,
      selectedTool: "road",
      savedAt: "2026-06-04T00:00:00.000Z",
    });

    for (let index = 2; index <= 5; index += 1) {
      createCitySaveSlot(`第${index}座城市`);
    }

    const slots = listCitySaveSlots();
    expect(slots.map((slot) => slot.name)).toEqual(["我的城市 1", "第2座城市", "第3座城市", "第4座城市", "第5座城市"]);
    switchCitySaveSlot(slots[0].id);
    expect(loadCitySave()?.blocks).toEqual(blocks);
  });

  it("deletes the active city slot and switches to another saved city", () => {
    let blocks: CityBlocks = {};
    blocks = placeBlock(blocks, { x: 1, y: 1 }, "road");
    saveCity({
      blocks,
      roadGroups: recomputeRoadGroups(DEFAULT_GRID, blocks),
      camera: DEFAULT_CAMERA,
      vehicles: [],
      weather: "sunny",
      night: false,
      selectedTool: "road",
      savedAt: "2026-06-04T00:00:00.000Z",
    });
    const second = createCitySaveSlot("第二座城市");

    const switchedTo = deleteCitySaveSlot(second.id);

    expect(switchedTo?.name).toBe("我的城市 1");
    expect(listCitySaveSlots().map((slot) => slot.name)).toEqual(["我的城市 1"]);
    expect(loadCitySave()?.blocks).toEqual(blocks);
    expect(listDeletedCitySaveSlots()).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          id: second.id,
          name: "第二座城市",
        }),
      ]),
    );
  });

  it("keeps one blank city when deleting the only city slot", () => {
    saveCity({
      blocks: placeBlock({}, { x: 1, y: 1 }, "building"),
      roadGroups: [],
      camera: DEFAULT_CAMERA,
      vehicles: [],
      weather: "rainy",
      night: true,
      selectedTool: "building",
      savedAt: "2026-06-04T00:00:00.000Z",
    });
    const only = listCitySaveSlots()[0];

    const replacement = deleteCitySaveSlot(only.id);

    expect(replacement?.name).toBe("我的城市 1");
    expect(listCitySaveSlots()).toHaveLength(1);
    expect(Object.values(loadCitySave()?.blocks ?? {})).toHaveLength(0);
    expect(loadCitySave()?.weather).toBe("sunny");
    expect(listDeletedCitySaveSlots().map((slot) => slot.id)).toContain(only.id);
  });

  it("restores a deleted city within seven days", () => {
    let blocks: CityBlocks = {};
    blocks = placeBlock(blocks, { x: 1, y: 1 }, "building");
    saveCity({
      blocks,
      roadGroups: [],
      camera: DEFAULT_CAMERA,
      vehicles: [],
      weather: "rainy",
      night: true,
      selectedTool: "building",
      savedAt: "2026-06-04T00:00:00.000Z",
    });
    const deleted = listCitySaveSlots()[0];
    deleteCitySaveSlot(deleted.id, new Date("2026-06-04T10:00:00.000Z"));

    const restored = restoreDeletedCitySaveSlot(deleted.id, new Date("2026-06-10T10:00:00.000Z"));

    expect(restored?.name).toBe("我的城市 1");
    expect(listDeletedCitySaveSlots()).toHaveLength(0);
    expect(listCitySaveSlots().map((slot) => slot.id)).toContain(restored!.id);
    expect(loadCitySave()?.blocks).toEqual(blocks);
  });

  it("can inspect whether a missing city is in the seven day deleted area", () => {
    saveCity({
      blocks: placeBlock({}, { x: 1, y: 1 }, "road"),
      roadGroups: [],
      camera: DEFAULT_CAMERA,
      vehicles: [],
      weather: "sunny",
      night: false,
      selectedTool: "road",
      savedAt: "2026-06-04T00:00:00.000Z",
    });
    for (let index = 2; index <= 5; index += 1) {
      createCitySaveSlot(`我的城市 ${index}`);
    }
    deleteCitySaveSlot("city-1", new Date("2026-06-21T10:00:00.000Z"));

    expect(listCitySaveSlots(new Date("2026-06-22T10:00:00.000Z")).map((slot) => slot.name)).toEqual(["我的城市 2", "我的城市 3", "我的城市 4", "我的城市 5"]);
    expect(findDeletedCitySaveSlot("city-1", new Date("2026-06-22T10:00:00.000Z"))).toMatchObject({ name: "我的城市 1" });
  });

  it("keeps restored city one before later numbered cities", () => {
    saveCity({
      blocks: placeBlock({}, { x: 1, y: 1 }, "road"),
      roadGroups: [],
      camera: DEFAULT_CAMERA,
      vehicles: [],
      weather: "sunny",
      night: false,
      selectedTool: "road",
      savedAt: "2026-06-04T00:00:00.000Z",
    });
    for (let index = 2; index <= 5; index += 1) {
      createCitySaveSlot(`我的城市 ${index}`);
    }
    const first = listCitySaveSlots()[0];
    deleteCitySaveSlot(first.id, new Date("2026-06-04T10:00:00.000Z"));

    restoreDeletedCitySaveSlot(first.id, new Date("2026-06-05T10:00:00.000Z"));

    expect(listCitySaveSlots().map((slot) => slot.name)).toEqual(["我的城市 1", "我的城市 2", "我的城市 3", "我的城市 4", "我的城市 5"]);
  });

  it("permanently purges deleted cities after seven days", () => {
    saveCity({
      blocks: placeBlock({}, { x: 1, y: 1 }, "park"),
      roadGroups: [],
      camera: DEFAULT_CAMERA,
      vehicles: [],
      weather: "sunny",
      night: false,
      selectedTool: "park",
      savedAt: "2026-06-04T00:00:00.000Z",
    });
    const deleted = listCitySaveSlots()[0];
    deleteCitySaveSlot(deleted.id, new Date("2026-06-04T10:00:00.000Z"));

    purgeExpiredDeletedCitySaveSlots(new Date("2026-06-11T10:00:01.000Z"));

    expect(listDeletedCitySaveSlots()).toHaveLength(0);
    expect(restoreDeletedCitySaveSlot(deleted.id, new Date("2026-06-11T10:00:01.000Z"))).toBeNull();
  });
});
