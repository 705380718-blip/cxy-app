import type { Building, Light, Point, Tree, VehiclePath } from "./types";

export const paths: VehiclePath[] = [
  {
    id: "loop-main",
    points: [
      { x: 170, y: 470 },
      { x: 300, y: 390 },
      { x: 440, y: 336 },
      { x: 590, y: 310 },
      { x: 760, y: 360 },
      { x: 860, y: 455 },
      { x: 720, y: 540 },
      { x: 500, y: 575 },
      { x: 300, y: 535 },
    ],
  },
  {
    id: "loop-park",
    points: [
      { x: 420, y: 250 },
      { x: 540, y: 210 },
      { x: 680, y: 245 },
      { x: 740, y: 330 },
      { x: 660, y: 420 },
      { x: 520, y: 440 },
      { x: 430, y: 360 },
    ],
  },
];

export const buildings: Building[] = [
  { id: "school", x: 210, y: 280, w: 92, h: 70, color: "#ffd166", roof: "#ef9f3e", windows: 4 },
  { id: "home-a", x: 780, y: 235, w: 96, h: 82, color: "#ff8f80", roof: "#df6b62", windows: 6 },
  { id: "home-b", x: 180, y: 570, w: 86, h: 62, color: "#7ed59b", roof: "#4aa669", windows: 4 },
  { id: "station", x: 690, y: 555, w: 120, h: 78, color: "#67b7dc", roof: "#3e8db5", windows: 5 },
  { id: "shop", x: 910, y: 425, w: 92, h: 68, color: "#f6a65f", roof: "#dd7f43", windows: 4 },
];

export const trees: Tree[] = [
  { x: 340, y: 245, r: 20 },
  { x: 370, y: 612, r: 22 },
  { x: 615, y: 500, r: 18 },
  { x: 850, y: 580, r: 24 },
  { x: 940, y: 320, r: 18 },
  { x: 250, y: 420, r: 16 },
];

export const lights: Light[] = [
  { x: 350, y: 390 },
  { x: 545, y: 325 },
  { x: 780, y: 385 },
  { x: 610, y: 555 },
  { x: 285, y: 515 },
];

export const lake: Point[] = [
  { x: 930, y: 570 },
  { x: 1040, y: 545 },
  { x: 1120, y: 610 },
  { x: 1070, y: 700 },
  { x: 920, y: 710 },
  { x: 860, y: 635 },
];
