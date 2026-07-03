import { describe, expect, it } from "vitest";
import { applyPinchZoom } from "./interaction";

describe("touch interactions", () => {
  it("zooms around the pinch center when two fingers move apart", () => {
    const camera = { x: 0, y: 0, zoom: 1 };

    const next = applyPinchZoom({
      camera,
      viewport: { width: 400, height: 300 },
      startCenter: { x: 200, y: 150 },
      startDistance: 100,
      currentCenter: { x: 200, y: 150 },
      currentDistance: 180,
    });

    expect(next.zoom).toBeCloseTo(1.8);
    expect(next.x).toBeCloseTo(0);
    expect(next.y).toBeCloseTo(0);
  });
});
