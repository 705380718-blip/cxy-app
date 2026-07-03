import { exportCityCloudSnapshot, importCityCloudSnapshot } from "./storage";
import type { CityCloudDeletedSaveSlot, CityCloudSaveSlot, CityCloudSnapshot } from "./storage";

export const CITY_CLOUD_USER_KEY = "city-traffic-master-cloud-user";

export interface CloudSyncResult {
  ok: boolean;
  message: string;
  snapshot?: CityCloudSnapshot;
}

export function normalizeCloudUserName(name: string): string {
  return name.trim().slice(0, 32);
}

export function getSavedCloudUserName(): string {
  return localStorage.getItem(CITY_CLOUD_USER_KEY) ?? "";
}

export function saveCloudUserName(name: string): void {
  localStorage.setItem(CITY_CLOUD_USER_KEY, normalizeCloudUserName(name));
}

export function mergeCityCloudSnapshots(remote: CityCloudSnapshot | null, local: CityCloudSnapshot, updatedAt = new Date().toISOString()): CityCloudSnapshot {
  const slotsById = new Map<string, CityCloudSaveSlot>();
  for (const slot of remote?.slots ?? []) slotsById.set(slot.id, slot);
  for (const slot of local.slots) {
    const previous = slotsById.get(slot.id);
    if (!previous || Date.parse(slot.savedAt) >= Date.parse(previous.savedAt)) slotsById.set(slot.id, slot);
  }

  const deletedById = new Map<string, CityCloudDeletedSaveSlot>();
  for (const slot of remote?.deletedSlots ?? []) deletedById.set(slot.id, slot);
  for (const slot of local.deletedSlots) {
    const previous = deletedById.get(slot.id);
    if (!previous || Date.parse(slot.deletedAt) >= Date.parse(previous.deletedAt)) deletedById.set(slot.id, slot);
  }
  for (const id of deletedById.keys()) slotsById.delete(id);

  return {
    version: 1,
    slots: sortCloudSlots([...slotsById.values()]),
    deletedSlots: [...deletedById.values()],
    activeSlotId: local.activeSlotId ?? remote?.activeSlotId ?? null,
    updatedAt,
  };
}

export async function loginAndSyncCityCloud(playerName: string): Promise<CloudSyncResult> {
  const user = normalizeCloudUserName(playerName);
  if (!user) return { ok: false, message: "先输入玩家名" };
  saveCloudUserName(user);
  const local = exportCityCloudSnapshot();
  const remote = await fetchCityCloudSnapshot(user);
  const merged = mergeCityCloudSnapshots(remote, local);
  const saved = await saveCityCloudSnapshot(user, merged);
  if (!saved.ok) return saved;
  importCityCloudSnapshot(merged);
  return { ok: true, message: "已把本机城市同步到云端", snapshot: merged };
}

export async function syncCurrentCityCloud(): Promise<CloudSyncResult> {
  const user = getSavedCloudUserName();
  if (!user) return { ok: false, message: "尚未登录云同步" };
  return saveCityCloudSnapshot(user, exportCityCloudSnapshot());
}

async function fetchCityCloudSnapshot(user: string): Promise<CityCloudSnapshot | null> {
  const response = await fetch(`/.netlify/functions/cities?user=${encodeURIComponent(user)}`);
  if (response.status === 404) return null;
  if (!response.ok) throw new Error("cloud load failed");
  const payload = (await response.json()) as { snapshot?: CityCloudSnapshot | null };
  return payload.snapshot ?? null;
}

async function saveCityCloudSnapshot(user: string, snapshot: CityCloudSnapshot): Promise<CloudSyncResult> {
  try {
    const response = await fetch("/.netlify/functions/cities", {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ user, snapshot }),
    });
    if (!response.ok) return { ok: false, message: "云端保存失败，本地仍已保存" };
    return { ok: true, message: "已同步到云端", snapshot };
  } catch {
    return { ok: false, message: "云端连接失败，本地仍已保存" };
  }
}

function sortCloudSlots<T extends { id: string; savedAt: string; name: string }>(slots: T[]): T[] {
  return [...slots].sort((a, b) => slotSortKey(a) - slotSortKey(b) || a.savedAt.localeCompare(b.savedAt) || a.name.localeCompare(b.name));
}

function slotSortKey(slot: { id: string; name: string }): number {
  const idMatch = /^city-(\d+)$/.exec(slot.id);
  if (idMatch) return Number(idMatch[1]);
  const nameMatch = /(\d+)$/.exec(slot.name);
  if (nameMatch) return Number(nameMatch[1]);
  return Number.MAX_SAFE_INTEGER;
}
