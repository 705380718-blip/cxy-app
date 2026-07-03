import { createEmptyBlocks } from "./blocks";
import { DEFAULT_CAMERA } from "./grid";
import type { Camera, CityBlocks, CityVehicle, RoadGroup, Tool, Weather } from "./types";

export const CITY_STORAGE_KEY = "city-traffic-master-first-version";
export const CITY_SAVE_SLOTS_KEY = "city-traffic-master-save-slots";
export const CITY_ACTIVE_SLOT_KEY = "city-traffic-master-active-slot";
export const CITY_DELETED_SLOTS_KEY = "city-traffic-master-deleted-slots";
export const CITY_DELETED_RETENTION_MS = 7 * 24 * 60 * 60 * 1000;

export interface CitySave {
  blocks: CityBlocks;
  roadGroups: RoadGroup[];
  camera: Camera;
  vehicles: CityVehicle[];
  weather: Weather;
  night: boolean;
  selectedTool: Tool;
  savedAt: string;
}

export interface CitySaveSlot {
  id: string;
  name: string;
  savedAt: string;
}

export interface DeletedCitySaveSlot extends CitySaveSlot {
  deletedAt: string;
  expiresAt: string;
}

export interface CityCloudSaveSlot extends CitySaveSlot {
  save: CitySave;
}

export interface CityCloudDeletedSaveSlot extends CityCloudSaveSlot {
  deletedAt: string;
  expiresAt: string;
}

export interface CityCloudSnapshot {
  version: 1;
  slots: CityCloudSaveSlot[];
  deletedSlots: CityCloudDeletedSaveSlot[];
  activeSlotId: string | null;
  updatedAt: string;
}

type StoredCitySaveSlot = CityCloudSaveSlot;
type StoredDeletedCitySaveSlot = CityCloudDeletedSaveSlot;

interface CitySaveSlotCollection {
  version: 1;
  slots: StoredCitySaveSlot[];
}

interface DeletedCitySaveSlotCollection {
  version: 1;
  slots: StoredDeletedCitySaveSlot[];
}

export function saveCity(save: CitySave): void {
  localStorage.setItem(CITY_STORAGE_KEY, JSON.stringify({ version: 2, ...save }));
  const slots = loadStoredSlots();
  const activeId = localStorage.getItem(CITY_ACTIVE_SLOT_KEY) ?? slots[0]?.id ?? "city-1";
  const currentIndex = slots.findIndex((slot) => slot.id === activeId);
  const nextSlot: StoredCitySaveSlot = {
    id: activeId,
    name: currentIndex >= 0 ? slots[currentIndex].name : defaultCityName(slots.length + 1),
    savedAt: save.savedAt,
    save,
  };
  const nextSlots = currentIndex >= 0 ? slots.map((slot) => (slot.id === activeId ? nextSlot : slot)) : [...slots, nextSlot];
  localStorage.setItem(CITY_ACTIVE_SLOT_KEY, activeId);
  saveStoredSlots(nextSlots);
}

export function loadCitySave(): CitySave | null {
  try {
    const raw = localStorage.getItem(CITY_STORAGE_KEY);
    if (!raw) return null;
    const parsed: unknown = JSON.parse(raw);
    if (!isCitySave(parsed)) return null;
    return {
      blocks: parsed.blocks,
      roadGroups: parsed.roadGroups,
      camera: parsed.camera ?? DEFAULT_CAMERA,
      vehicles: parsed.vehicles ?? [],
      weather: parsed.weather,
      night: parsed.night,
      selectedTool: parsed.selectedTool,
      savedAt: parsed.savedAt,
    };
  } catch {
    return null;
  }
}

export function listCitySaveSlots(now = new Date()): CitySaveSlot[] {
  purgeExpiredDeletedCitySaveSlots(now);
  return sortedStoredSlots(loadStoredSlots()).map(({ id, name, savedAt }) => ({ id, name, savedAt }));
}

export function createCitySaveSlot(name?: string): CitySaveSlot {
  const slots = loadStoredSlots();
  const id = nextCityId(slots);
  const save = createBlankCitySave();
  const slot = {
    id,
    name: cleanSlotName(name) || defaultCityName(slots.length + 1),
    savedAt: save.savedAt,
    save,
  };
  saveStoredSlots([...slots, slot]);
  switchCitySaveSlot(id);
  return { id: slot.id, name: slot.name, savedAt: slot.savedAt };
}

export function switchCitySaveSlot(id: string): CitySaveSlot | null {
  const slot = loadStoredSlots().find((item) => item.id === id);
  if (!slot) return null;
  localStorage.setItem(CITY_ACTIVE_SLOT_KEY, slot.id);
  localStorage.setItem(CITY_STORAGE_KEY, JSON.stringify({ version: 2, ...slot.save }));
  return { id: slot.id, name: slot.name, savedAt: slot.savedAt };
}

export function deleteCitySaveSlot(id: string, now = new Date()): CitySaveSlot | null {
  purgeExpiredDeletedCitySaveSlots(now);
  const slots = loadStoredSlots();
  const currentIndex = slots.findIndex((slot) => slot.id === id);
  if (currentIndex < 0) return null;
  moveSlotToDeleted(slots[currentIndex], now);
  if (slots.length === 1) {
    const save = createBlankCitySave();
    const replacement = { id: "city-1", name: defaultCityName(1), savedAt: save.savedAt, save };
    saveStoredSlots([replacement]);
    localStorage.setItem(CITY_ACTIVE_SLOT_KEY, replacement.id);
    localStorage.setItem(CITY_STORAGE_KEY, JSON.stringify({ version: 2, ...replacement.save }));
    return { id: replacement.id, name: replacement.name, savedAt: replacement.savedAt };
  }
  const nextSlots = slots.filter((slot) => slot.id !== id);
  saveStoredSlots(nextSlots);
  const nextSlot = nextSlots[Math.max(0, currentIndex - 1)] ?? nextSlots[0];
  return switchCitySaveSlot(nextSlot.id);
}

export function listDeletedCitySaveSlots(now = new Date()): DeletedCitySaveSlot[] {
  purgeExpiredDeletedCitySaveSlots(now);
  return loadDeletedStoredSlots().map(({ id, name, savedAt, deletedAt, expiresAt }) => ({ id, name, savedAt, deletedAt, expiresAt }));
}

export function findDeletedCitySaveSlot(id: string, now = new Date()): DeletedCitySaveSlot | null {
  return listDeletedCitySaveSlots(now).find((slot) => slot.id === id) ?? null;
}

export function restoreDeletedCitySaveSlot(id: string, now = new Date()): CitySaveSlot | null {
  purgeExpiredDeletedCitySaveSlots(now);
  const deletedSlots = loadDeletedStoredSlots();
  const deleted = deletedSlots.find((slot) => slot.id === id);
  if (!deleted) return null;
  const slots = loadStoredSlots();
  const restoredId = slots.some((slot) => slot.id === deleted.id) ? nextCityId(slots) : deleted.id;
  const restored: StoredCitySaveSlot = {
    id: restoredId,
    name: deleted.name,
    savedAt: deleted.savedAt,
    save: deleted.save,
  };
  saveStoredSlots(sortedStoredSlots([...slots, restored]));
  saveDeletedStoredSlots(deletedSlots.filter((slot) => slot.id !== id));
  switchCitySaveSlot(restored.id);
  return { id: restored.id, name: restored.name, savedAt: restored.savedAt };
}

export function purgeExpiredDeletedCitySaveSlots(now = new Date()): void {
  const nowMs = now.getTime();
  const slots = loadDeletedStoredSlots();
  const freshSlots = slots.filter((slot) => Date.parse(slot.expiresAt) > nowMs);
  if (freshSlots.length !== slots.length) saveDeletedStoredSlots(freshSlots);
}

export function currentCitySaveSlot(): CitySaveSlot | null {
  const activeId = localStorage.getItem(CITY_ACTIVE_SLOT_KEY);
  const slots = sortedStoredSlots(loadStoredSlots());
  const slot = slots.find((item) => item.id === activeId) ?? slots[0] ?? null;
  return slot ? { id: slot.id, name: slot.name, savedAt: slot.savedAt } : null;
}

export function exportCityCloudSnapshot(now = new Date()): CityCloudSnapshot {
  purgeExpiredDeletedCitySaveSlots(now);
  return {
    version: 1,
    slots: sortedStoredSlots(loadStoredSlots()),
    deletedSlots: loadDeletedStoredSlots(),
    activeSlotId: localStorage.getItem(CITY_ACTIVE_SLOT_KEY),
    updatedAt: now.toISOString(),
  };
}

export function importCityCloudSnapshot(snapshot: CityCloudSnapshot): void {
  saveStoredSlots(snapshot.slots);
  saveDeletedStoredSlots(snapshot.deletedSlots);
  const activeSlot = snapshot.activeSlotId && snapshot.slots.some((slot) => slot.id === snapshot.activeSlotId) ? snapshot.activeSlotId : snapshot.slots[0]?.id;
  if (activeSlot) {
    switchCitySaveSlot(activeSlot);
  }
}

function createBlankCitySave(): CitySave {
  return {
    blocks: createEmptyBlocks(),
    roadGroups: [],
    camera: DEFAULT_CAMERA,
    vehicles: [],
    weather: "sunny",
    night: false,
    selectedTool: "road",
    savedAt: new Date().toISOString(),
  };
}

function loadStoredSlots(): StoredCitySaveSlot[] {
  try {
    const raw = localStorage.getItem(CITY_SAVE_SLOTS_KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    if (!isSlotCollection(parsed)) return [];
    return parsed.slots;
  } catch {
    return [];
  }
}

function loadDeletedStoredSlots(): StoredDeletedCitySaveSlot[] {
  try {
    const raw = localStorage.getItem(CITY_DELETED_SLOTS_KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    if (!isDeletedSlotCollection(parsed)) return [];
    return parsed.slots;
  } catch {
    return [];
  }
}

function saveStoredSlots(slots: StoredCitySaveSlot[]): void {
  localStorage.setItem(CITY_SAVE_SLOTS_KEY, JSON.stringify({ version: 1, slots: sortedStoredSlots(slots) }));
}

function saveDeletedStoredSlots(slots: StoredDeletedCitySaveSlot[]): void {
  localStorage.setItem(CITY_DELETED_SLOTS_KEY, JSON.stringify({ version: 1, slots }));
}

function moveSlotToDeleted(slot: StoredCitySaveSlot, now: Date): void {
  const deletedAt = now.toISOString();
  const expiresAt = new Date(now.getTime() + CITY_DELETED_RETENTION_MS).toISOString();
  const deletedSlot: StoredDeletedCitySaveSlot = { ...slot, deletedAt, expiresAt };
  const deletedSlots = loadDeletedStoredSlots().filter((item) => item.id !== slot.id);
  saveDeletedStoredSlots([...deletedSlots, deletedSlot]);
}

function isSlotCollection(value: unknown): value is CitySaveSlotCollection {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Record<string, unknown>;
  return candidate.version === 1 && Array.isArray(candidate.slots) && candidate.slots.every((slot) => isStoredSlot(slot));
}

function isDeletedSlotCollection(value: unknown): value is DeletedCitySaveSlotCollection {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Record<string, unknown>;
  return candidate.version === 1 && Array.isArray(candidate.slots) && candidate.slots.every((slot) => isStoredDeletedSlot(slot));
}

function isStoredSlot(value: unknown): value is StoredCitySaveSlot {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Record<string, unknown>;
  return typeof candidate.id === "string" && typeof candidate.name === "string" && typeof candidate.savedAt === "string" && isCitySaveBody(candidate.save);
}

function isStoredDeletedSlot(value: unknown): value is StoredDeletedCitySaveSlot {
  if (!isStoredSlot(value)) return false;
  const candidate = value as unknown as Record<string, unknown>;
  return typeof candidate.deletedAt === "string" && typeof candidate.expiresAt === "string";
}

function nextCityId(slots: StoredCitySaveSlot[]): string {
  let index = slots.length + 1;
  const ids = new Set(slots.map((slot) => slot.id));
  while (ids.has(`city-${index}`)) index += 1;
  return `city-${index}`;
}

function sortedStoredSlots<T extends CitySaveSlot>(slots: T[]): T[] {
  return [...slots].sort((a, b) => slotSortKey(a) - slotSortKey(b) || a.savedAt.localeCompare(b.savedAt) || a.name.localeCompare(b.name));
}

function slotSortKey(slot: CitySaveSlot): number {
  const idMatch = /^city-(\d+)$/.exec(slot.id);
  if (idMatch) return Number(idMatch[1]);
  const nameMatch = /(\d+)$/.exec(slot.name);
  if (nameMatch) return Number(nameMatch[1]);
  return Number.MAX_SAFE_INTEGER;
}

function defaultCityName(index: number): string {
  return `我的城市 ${index}`;
}

function cleanSlotName(name: string | undefined): string {
  return (name ?? "").trim().slice(0, 16);
}

function isCitySave(value: unknown): value is CitySave & { version: 2 } {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Record<string, unknown>;
  return candidate.version === 2 && isCitySaveBody(value);
}

function isCitySaveBody(value: unknown): value is CitySave {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Record<string, unknown>;
  return (
    isBlocks(candidate.blocks) &&
    Array.isArray(candidate.roadGroups) &&
    candidate.roadGroups.every((group) => isRoadGroup(group)) &&
    isCamera(candidate.camera) &&
    Array.isArray(candidate.vehicles) &&
    candidate.vehicles.every((vehicle) => isVehicle(vehicle)) &&
    (candidate.weather === "sunny" || candidate.weather === "rainy" || candidate.weather === "snowy") &&
    typeof candidate.night === "boolean" &&
    isTool(candidate.selectedTool) &&
    typeof candidate.savedAt === "string"
  );
}

function isBlocks(value: unknown): value is CityBlocks {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  return Object.values(value).every((block) => {
    if (!block || typeof block !== "object") return false;
    const item = block as Record<string, unknown>;
    return (
      typeof item.id === "string" &&
      (item.type === "road" ||
        item.type === "overpass" ||
        item.type === "roadwork" ||
        item.type === "trafficLight" ||
        item.type === "building" ||
        item.type === "park" ||
        item.type === "busStop") &&
      isCell(item.cell) &&
      typeof item.name === "string" &&
      (item.overpassDirection === undefined || item.overpassDirection === "horizontal" || item.overpassDirection === "vertical")
    );
  });
}

function isRoadGroup(value: unknown): value is RoadGroup {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Record<string, unknown>;
  return (
    typeof candidate.id === "string" &&
    typeof candidate.name === "string" &&
    Array.isArray(candidate.cells) &&
    candidate.cells.every((cell) => isCell(cell))
  );
}

function isVehicle(value: unknown): value is CityVehicle {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Record<string, unknown>;
  return (
    typeof candidate.id === "string" &&
    (candidate.type === "sedan" || candidate.type === "bus" || candidate.type === "offroad" || candidate.type === "sweeper") &&
    typeof candidate.name === "string" &&
    isCell(candidate.cell) &&
    (candidate.roadGroupId === null || typeof candidate.roadGroupId === "string") &&
    typeof candidate.progress === "number" &&
    typeof candidate.speed === "number" &&
    isOptionalStopRoute(candidate.routeStopIds) &&
    isOptionalStopRoute(candidate.routeBuildingIds) &&
    (candidate.routeDirection === undefined || candidate.routeDirection === 1 || candidate.routeDirection === -1) &&
    isOptionalCellRoute(candidate.routeCellPath) &&
    isOptionalNumber(candidate.currentStopIndex) &&
    isOptionalNumber(candidate.currentBuildingIndex) &&
    isOptionalNumber(candidate.dwellMs) &&
    isOptionalNumber(candidate.passengerPulseMs) &&
    isOptionalNumber(candidate.passengerLoad)
  );
}

function isOptionalStopRoute(value: unknown): boolean {
  return value === undefined || (Array.isArray(value) && value.every((item) => typeof item === "string"));
}

function isOptionalCellRoute(value: unknown): boolean {
  return value === undefined || (Array.isArray(value) && value.every((item) => isCell(item)));
}

function isOptionalNumber(value: unknown): boolean {
  return value === undefined || typeof value === "number";
}

function isCamera(value: unknown): value is Camera {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Record<string, unknown>;
  return typeof candidate.x === "number" && typeof candidate.y === "number" && typeof candidate.zoom === "number";
}

function isCell(value: unknown): value is { x: number; y: number } {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Record<string, unknown>;
  return Number.isInteger(candidate.x) && Number.isInteger(candidate.y);
}

function isTool(value: unknown): value is Tool {
  return (
    value === "road" ||
    value === "overpass" ||
    value === "roadwork" ||
    value === "trafficLight" ||
    value === "building" ||
    value === "park" ||
    value === "busStop" ||
    value === "sedan" ||
    value === "bus" ||
    value === "offroad" ||
    value === "sweeper"
  );
}
