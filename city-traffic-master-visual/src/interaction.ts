import { clampZoom, screenToWorld } from "./grid";
import type { Camera, Point } from "./types";

export interface PinchZoomInput {
  camera: Camera;
  viewport: { width: number; height: number };
  startCenter: Point;
  startDistance: number;
  currentCenter: Point;
  currentDistance: number;
}

export function applyPinchZoom(input: PinchZoomInput): Camera {
  if (input.startDistance <= 0 || input.currentDistance <= 0) return input.camera;
  const before = screenToWorld(input.startCenter, input.camera, input.viewport.width, input.viewport.height);
  const nextCamera = {
    ...input.camera,
    zoom: clampZoom(input.camera.zoom * (input.currentDistance / input.startDistance)),
  };
  const after = screenToWorld(input.currentCenter, nextCamera, input.viewport.width, input.viewport.height);
  return {
    ...nextCamera,
    x: nextCamera.x + before.x - after.x,
    y: nextCamera.y + before.y - after.y,
  };
}
