Original prompt: 读取 WorkBuddy 优化过的《城市交通大师》游戏设计方案，选择 C 方向，先打磨“不着急玩”的视觉原型。

## Progress

- Spec approved: `docs/superpowers/specs/2026-06-03-city-traffic-master-visual-prototype-design.md`
- Selected visual direction: 活着的微缩城市。
- Selected layout: 大画布优先。
- Added state, types, and static miniature city scene data.
- Rendered static miniature city canvas with moving visual scene scaffold.
- Added toolbar actions, city status card, city check modal, and toast behavior.
- Added deterministic debug hooks for web game validation.
- Verified visual prototype with Playwright screenshots and debug text state.
- Polished status-card collapse behavior, toolbar icon labels, and favicon; re-verified build, browser interactions, desktop/mobile screenshots, and debug text state.
- Converted the formal first version from a fixed visual prototype into a Lego-like grid city builder: grid blocks, road naming, dynamic vehicle route, save/load, and Playwright validation.

- Added selected-cell deletion, current-city reset, and multi-city save slot controls; tests cover state deletion/reset and storage slot switching.
- Verified delete, reset, save reload, new city, and save-slot switching with local Playwright on http://127.0.0.1:5179; bundled web game client could not resolve playwright from its script directory in this environment.

- Added delete-current-city save-slot behavior; deleting the only city keeps one blank city, while deleting one of many switches to a remaining city.
- Verified delete-city UI flow with Playwright screenshot and debug state.

- Fixed mobile pinch zoom by adding two-pointer zoom handling with pointer-capture fallback; debug text now includes camera.
- Changed road grouping from connected components to horizontal/vertical line segments so connected branches can be named separately.
- Verified pinch zoom and T-road branch naming with local Playwright; bundled web-game client still cannot resolve playwright from its script directory.

- Added delete-vehicle action: removes the selected vehicle, or the most recently added vehicle as an undo-like fallback, without deleting road blocks.
- Verified with unit tests, build, and Playwright delete-vehicle flow.

- Added routed bus creation: adding a bus now opens a stop picker when at least two bus stops exist, and the selected click order becomes the bus loop order.
- Routed buses move between selected stops, pause at each stop, and show a passenger boarding/alighting animation during the dwell window.
- Verified with unit tests, production build, the develop-web-game Playwright client via a project-local temporary copy, and a full Playwright flow that builds roads/stops, selects a route, advances to a stop, and captures `output/web-game-bus-basic/bus-route-passengers.png`.

- Fixed routed buses drifting off-road when bus stops are placed beside the road: stop positions are now projected to the nearest cell in the bus road group before rendering the route.
- Added a regression test for road-adjacent bus stops and verified with Playwright screenshot `output/web-game-bus-road-fixed.png`, web-game client smoke run, full unit tests, and production build.

- Built the 2026-06-06 publish package after `npm test`, `npm run build`, Vite preview smoke, and web-game client screenshot validation.
- Release ZIP: `output/releases/city-traffic-master-20260606.zip`; copied convenience package to `/Users/chenxiaoyong/Documents/个人/codex/output/city-traffic-master-20260606.zip`.

- Updated bus creation flow so children name the bus line first, then choose the stop order. Verified a "17路" flow creates a routed bus named "17路" and does not show the old post-creation rename popover.
- Added state regression coverage for custom bus names and optional post-create selection behavior; verified with full unit tests, production build, Playwright flow screenshot `output/bus-name-before-route-final.png`, and web-game client smoke run.

- Added bus line badges on bus bodies, so a named route like "17路" shows "17" on the vehicle itself.
- Replaced the fixed city health score with a dynamic score based on roads, connected road groups, buildings, parks, bus stops, routed buses, vehicles, weather, and night mode; edits now refresh the score immediately.
- Verified the line badge and dynamic score with full unit tests, production build, Playwright screenshot `output/bus-body-score-dynamic.png`, and the develop-web-game browser smoke client.

- Built the 2026-06-06 v2 publish package after `npm test`, `npm run build`, Vite production preview smoke, web-game client screenshot validation, and ZIP content checks for the bus route/passenger/dynamic score code.
- Release ZIP: `output/releases/city-traffic-master-20260606-v2.zip`; copied convenience package to `/Users/chenxiaoyong/Documents/个人/codex/output/city-traffic-master-20260606-v2.zip`.

- Fixed routed buses selecting stops across connected road branches: bus rendering now finds a path through all connected road cells between the chosen stops instead of projecting every stop onto the bus's original road segment.
- Added regression coverage for choosing stop 1 and stop 3 while skipping an unselected middle stop; verified route state excludes stop 2 and the bus reaches stop 3 in Playwright screenshot `output/bus-route-skip-middle-stop.png`.

- Built the 2026-06-06 v3 publish package after the connected-road bus route fix.
- Verified `npm test`, `npm run build`, Vite production preview smoke, a release-preview Playwright scenario where a bus selects stops 1 and 3 while skipping stop 2, ZIP integrity, and ZIP JS contents.
- Release ZIP: `output/releases/city-traffic-master-20260606-v3.zip`; copied convenience package to `/Users/chenxiaoyong/Documents/个人/codex/output/city-traffic-master-20260606-v3.zip`.

- Fixed the bus route picker overflowing when many bus stops exist: the route modal now has a fixed viewport-bound panel, a scrollable stop list, a persistent footer, and a top close button.
- Verified with `npm test`, `npm run build`, desktop Playwright reproduction with 15 bus stops (`output/bus-route-many-stops-modal.png`), mobile Playwright reproduction (`output/bus-route-many-stops-modal-mobile.png`), and the develop-web-game client via a project-local temporary copy.

- Built and exported the 2026-06-15 publish package after `npm test` and `npm run build`.
- Release ZIP: `output/releases/city-traffic-master-20260615.zip`; copied desktop package to `/Users/chenxiaoyong/Desktop/city-traffic-master-20260615.zip`.

- Added two gameplay features on 2026-06-25: a drivable `立交桥` infrastructure tool that can replace/bridge a road cell, and a sedan route picker for choosing an origin building and destination building.
- Updated storage/debug/render/state coverage so overpasses persist, count in city scoring, participate in road groups, and sedan routes save as `routeBuildingIds`.
- Verified with `npm test` (37 tests), `npm run build`, web-game client smoke, Playwright feature flow screenshot `output/city-traffic-overpass-car-route.png`, and production Netlify deploy `6a3c8252bdf4449865c6e343`.

- Added overpass direction selection on 2026-06-25: placing `立交桥` now asks for `左右` or `上下`, persists the direction as `overpassDirection`, and renders the bridge deck in the chosen orientation.
- Verified with `npm test` (40 tests), `npm run build`, and a browser flow that selected `上下` and captured `output/city-traffic-overpass-vertical.png`.
- Deployed the direction selector to Netlify production deploy `6a3c859daa243fac922e7c6a` and confirmed the live JS includes `overpassDirection` plus `左右/上下`.

- Updated road naming on 2026-06-25 so road and overpass cells in the same straight road segment are named once via the road group, instead of showing or editing individual overpass names.
- Verified with `npm test` (41 tests), `npm run build`, web-game client smoke via a project-local temporary copy, and browser screenshot `output/city-traffic-one-road-name-overpass-fixed.png`.
- Deployed to Netlify production deploy `6a3c88cc94d97da219eefdf0`.

- Added roadwork and traffic-light intersection components on 2026-07-01. Roadwork can replace road cells and breaks drivable segments; traffic-light intersections remain drivable and alternate horizontal/vertical green phases every 3 seconds.
- Vehicles on a road group stop before a red traffic light and continue when their direction turns green.
- Reworked the top toolbar into grouped tool clusters for road facilities, city components, vehicles, and city actions as the tool count grows.
- Verified with `npm test` (45 tests), `npm run build`, web-game client smoke via a project-local temporary copy, and browser screenshot `output/city-traffic-roadwork-traffic-light.png`.
- Deployed to Netlify production deploy `6a44671569bd568089ad1c28` and confirmed the live JS includes `roadwork` and `trafficLight`.

- Tightened roadwork behavior on 2026-07-01 so existing generic vehicles remap to the current road segment and stop when construction breaks a road, while routed buses and sedans wait when roadwork blocks the path to the next stop or building.
- Added bus route picker bulk controls: `全选站台` selects every displayed bus stop in order, and `清空` resets the selection.
- Verified with `npm test` (48 tests), `npm run build`, the develop-web-game client via a project-local temporary copy, and browser screenshot `output/city-traffic-roadwork-bus-select-all.png`.
- Deployed to Netlify production deploy `6a446966bd23b3887e4b0294` and confirmed the live JS/CSS include the bus stop bulk controls and roadwork route-blocking logic.

- Updated construction avoidance on 2026-07-01: ordinary vehicles now keep a drivable cell path and continue along a bypass when roadwork breaks their current road, while routed buses/sedans reverse direction when the next chosen stop/building is blocked and another route target is reachable.
- Tightened route access so bus stops/buildings prefer adjacent drivable cells and do not snap through a neighboring roadwork cell.
- Verified with `npm test` (48 tests), `npm run build`, browser debug flows for ordinary-vehicle bypass and bus reverse direction, screenshot `output/city-traffic-roadwork-reroute.png`, and the develop-web-game client via a project-local temporary copy.
- Deployed to Netlify production deploy `6a446c2e625cc0a12b82c210` and confirmed the live JS includes `routeCellPath` and `routeDirection`.
