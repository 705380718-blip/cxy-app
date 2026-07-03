import { describe, expect, it } from "vitest";
import { routeStopIdsForAllStops } from "./ui";

describe("route picker helpers", () => {
  it("selects every bus stop id in display order", () => {
    expect(
      routeStopIdsForAllStops([
        { id: "stop-1", name: "站台 1", cell: { x: 0, y: 1 } },
        { id: "stop-2", name: "站台 2", cell: { x: 1, y: 1 } },
        { id: "stop-3", name: "站台 3", cell: { x: 2, y: 1 } },
      ]),
    ).toEqual(["stop-1", "stop-2", "stop-3"]);
  });
});
