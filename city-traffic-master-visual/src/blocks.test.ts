import { describe, expect, it } from "vitest";
import { blockCounts, createEmptyBlocks, getBlock, placeBlock, recomputeRoadGroups, routePointsForGroup } from "./blocks";
import { DEFAULT_GRID } from "./grid";

describe("city blocks", () => {
  it("places blocks on far-away cells and blocks incompatible overwrites", () => {
    let blocks = createEmptyBlocks();
    blocks = placeBlock(blocks, { x: 100, y: -42 }, "road");
    expect(getBlock(blocks, { x: 100, y: -42 })?.type).toBe("road");
    const unchanged = placeBlock(blocks, { x: 100, y: -42 }, "building");
    expect(getBlock(unchanged, { x: 100, y: -42 })?.type).toBe("road");
  });

  it("lets an overpass replace a road cell while keeping it drivable", () => {
    let blocks = createEmptyBlocks();
    blocks = placeBlock(blocks, { x: 0, y: 0 }, "road");
    blocks = placeBlock(blocks, { x: 0, y: 0 }, "overpass");
    blocks = placeBlock(blocks, { x: 1, y: 0 }, "road");

    expect(getBlock(blocks, { x: 0, y: 0 })?.type).toBe("overpass");
    expect(blockCounts(blocks).overpass).toBe(1);
    expect(recomputeRoadGroups(DEFAULT_GRID, blocks)[0].cells).toEqual([
      { x: 0, y: 0 },
      { x: 1, y: 0 },
    ]);
  });

  it("lets a traffic light intersection connect horizontal and vertical roads", () => {
    let blocks = createEmptyBlocks();
    blocks = placeBlock(blocks, { x: 0, y: 1 }, "road");
    blocks = placeBlock(blocks, { x: 1, y: 1 }, "trafficLight");
    blocks = placeBlock(blocks, { x: 2, y: 1 }, "road");
    blocks = placeBlock(blocks, { x: 1, y: 0 }, "road");
    blocks = placeBlock(blocks, { x: 1, y: 2 }, "road");

    const groups = recomputeRoadGroups(DEFAULT_GRID, blocks);

    expect(getBlock(blocks, { x: 1, y: 1 })?.type).toBe("trafficLight");
    expect(groups.find((group) => group.id === "road-line-h-0-1")?.cells).toEqual([
      { x: 0, y: 1 },
      { x: 1, y: 1 },
      { x: 2, y: 1 },
    ]);
    expect(groups.find((group) => group.id === "road-line-v-1-0")?.cells).toEqual([
      { x: 1, y: 0 },
      { x: 1, y: 1 },
      { x: 1, y: 2 },
    ]);
  });

  it("lets roadwork replace a road cell and break the drivable segment", () => {
    let blocks = createEmptyBlocks();
    blocks = placeBlock(blocks, { x: 0, y: 0 }, "road");
    blocks = placeBlock(blocks, { x: 1, y: 0 }, "road");
    blocks = placeBlock(blocks, { x: 2, y: 0 }, "road");
    blocks = placeBlock(blocks, { x: 1, y: 0 }, "roadwork");

    expect(getBlock(blocks, { x: 1, y: 0 })?.type).toBe("roadwork");
    expect(recomputeRoadGroups(DEFAULT_GRID, blocks).map((group) => group.cells)).toEqual([[{ x: 0, y: 0 }], [{ x: 2, y: 0 }]]);
  });

  it("stores the chosen overpass direction", () => {
    let blocks = createEmptyBlocks();
    blocks = placeBlock(blocks, { x: 0, y: 0 }, "overpass", "vertical");

    expect(getBlock(blocks, { x: 0, y: 0 })?.overpassDirection).toBe("vertical");
  });

  it("places and names a bus stop block", () => {
    const blocks = placeBlock(createEmptyBlocks(), { x: -3, y: 7 }, "busStop");
    const block = getBlock(blocks, { x: -3, y: 7 });
    expect(block?.type).toBe("busStop");
    expect(block?.name).toContain("阳光站");
  });

  it("groups adjacent road cells and preserves a previous road name", () => {
    let blocks = createEmptyBlocks();
    blocks = placeBlock(blocks, { x: 1, y: 1 }, "road");
    blocks = placeBlock(blocks, { x: 2, y: 1 }, "road");
    blocks = placeBlock(blocks, { x: 3, y: 1 }, "road");
    const named = recomputeRoadGroups(DEFAULT_GRID, blocks, [{ id: "road-1-1", name: "彩虹路", cells: [{ x: 1, y: 1 }] }]);
    expect(named).toHaveLength(1);
    expect(named[0].name).toBe("彩虹路");
    expect(named[0].cells).toHaveLength(3);
  });

  it("keeps a connected road branch as a separately named segment", () => {
    let blocks = createEmptyBlocks();
    blocks = placeBlock(blocks, { x: 0, y: 0 }, "road");
    blocks = placeBlock(blocks, { x: 1, y: 0 }, "road");
    blocks = placeBlock(blocks, { x: 2, y: 0 }, "road");
    blocks = placeBlock(blocks, { x: 1, y: 1 }, "road");

    const groups = recomputeRoadGroups(DEFAULT_GRID, blocks, [
      {
        id: "road-line-h-0-0",
        name: "学校大道",
        cells: [
          { x: 0, y: 0 },
          { x: 1, y: 0 },
          { x: 2, y: 0 },
        ],
      },
      {
        id: "road-line-v-1-0",
        name: "公园支路",
        cells: [
          { x: 1, y: 0 },
          { x: 1, y: 1 },
        ],
      },
    ]);

    expect(groups.map((group) => group.name).sort()).toEqual(["公园支路", "学校大道"]);
    expect(groups.find((group) => group.name === "学校大道")?.cells).toHaveLength(3);
    expect(groups.find((group) => group.name === "公园支路")?.cells).toHaveLength(2);
  });

  it("extracts route points from a road group in grid order", () => {
    const group = {
      id: "road-1-1",
      name: "学校大道",
      cells: [
        { x: 1, y: 1 },
        { x: 2, y: 1 },
        { x: 3, y: 1 },
      ],
    };
    const points = routePointsForGroup(DEFAULT_GRID, group);
    expect(points.map((point) => Math.round(point.x))).toEqual([84, 140, 196]);
  });
});
