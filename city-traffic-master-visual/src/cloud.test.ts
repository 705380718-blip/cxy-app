import { describe, expect, it } from "vitest";
import { mergeCityCloudSnapshots, normalizeCloudUserName } from "./cloud";
import type { CityCloudSnapshot } from "./storage";

function snapshot(names: string[], updatedAt = "2026-06-21T10:00:00.000Z"): CityCloudSnapshot {
  return {
    version: 1,
    slots: names.map((name, index) => ({
      id: `city-${index + 1}`,
      name,
      savedAt: updatedAt,
      save: {
        blocks: {},
        roadGroups: [],
        camera: { x: 0, y: 0, zoom: 1 },
        vehicles: [],
        weather: "sunny",
        night: false,
        selectedTool: "road",
        savedAt: updatedAt,
      },
    })),
    deletedSlots: [],
    activeSlotId: "city-1",
    updatedAt,
  };
}

describe("cloud city sync", () => {
  it("normalizes a player name into a stable cloud key", () => {
    expect(normalizeCloudUserName(" 小勇的城市 ")).toBe("小勇的城市");
    expect(normalizeCloudUserName("")).toBe("");
  });

  it("merges local browser cities into the cloud snapshot without losing remote cities", () => {
    const remote = snapshot(["我的城市 1"], "2026-06-21T09:00:00.000Z");
    const local = snapshot(["我的城市 1", "我的城市 2"], "2026-06-21T10:00:00.000Z");

    const merged = mergeCityCloudSnapshots(remote, local, "2026-06-21T11:00:00.000Z");

    expect(merged.slots.map((slot) => slot.name)).toEqual(["我的城市 1", "我的城市 2"]);
    expect(merged.updatedAt).toBe("2026-06-21T11:00:00.000Z");
  });

  it("keeps seven-day deleted cities in the cloud snapshot", () => {
    const remote = snapshot(["我的城市 2"], "2026-06-21T09:00:00.000Z");
    const local = snapshot(["我的城市 2"], "2026-06-21T10:00:00.000Z");
    local.deletedSlots = [
      {
        id: "city-1",
        name: "我的城市 1",
        savedAt: "2026-06-21T09:00:00.000Z",
        deletedAt: "2026-06-21T10:00:00.000Z",
        expiresAt: "2026-06-28T10:00:00.000Z",
        save: remote.slots[0].save,
      },
    ];

    const merged = mergeCityCloudSnapshots(remote, local, "2026-06-21T11:00:00.000Z");

    expect(merged.deletedSlots.map((slot) => slot.name)).toEqual(["我的城市 1"]);
  });
});
