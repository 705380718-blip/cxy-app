import { blockCounts, longestRoadGroup } from "./blocks";
import { getSavedCloudUserName, loginAndSyncCityCloud, syncCurrentCityCloud } from "./cloud";
import {
  createCitySaveSlot,
  currentCitySaveSlot,
  deleteCitySaveSlot,
  listCitySaveSlots,
  listDeletedCitySaveSlots,
  restoreDeletedCitySaveSlot,
  switchCitySaveSlot,
} from "./storage";
import {
  buildingsInCity,
  busStopsInCity,
  cycleWeather,
  deleteSelectedCellContent,
  deleteSelectedVehicle,
  placeSelectedBlock,
  placeSelectedVehicle,
  renameSelectedEntity,
  replaceStateFromSave,
  resetCityState,
  saveVisualState,
  updateMood,
} from "./state";
import type { AppState, GridCell } from "./types";
import type { OverpassDirection } from "./types";

interface UiElements {
  statusCard: HTMLElement;
  modal: HTMLElement;
  toast: HTMLElement;
  roadNamePopover: HTMLElement;
  citySaveSelect: HTMLSelectElement;
}

let toastTimer: number | null = null;

export function setupUi(state: AppState, onChange: () => void): void {
  const statusCard = requireElement("#status-card");
  const modal = requireElement("#city-check-modal");
  const toast = requireElement("#toast");
  const roadNamePopover = requireElement("#road-name-popover");
  const citySaveSelect = requireElement("#city-save-select") as HTMLSelectElement;
  const elements = { statusCard, modal, toast, roadNamePopover, citySaveSelect };

  document.querySelectorAll<HTMLButtonElement>("[data-action]").forEach((button) => {
    button.addEventListener("click", () => handleAction(button.dataset.action ?? "", state, elements, onChange));
  });
  citySaveSelect.addEventListener("change", () => {
    const switched = switchCitySaveSlot(citySaveSelect.value);
    if (!switched) return;
    replaceStateFromSave(state);
    showToast(toast, `已切换到${switched.name}`);
    renderUi(state, elements);
    onChange();
  });

  renderUi(state, elements);
  const deletedSlots = listDeletedCitySaveSlots();
  updateRestoreButtonLabel(deletedSlots.length);
  updateCloudButtonLabel();
  if (deletedSlots.length > 0) {
    showDeletedCitiesModal(state, elements, onChange, "有城市在 7 天恢复区");
  }
  if (getSavedCloudUserName()) {
    void syncCloudAndRefresh(state, elements, onChange, false);
  }
  if (state.loadedFromStorage) showToast(toast, "已载入你的城市");
}

export function renderUi(state: AppState, elements?: Partial<UiElements>): void {
  renderToolbarState(state);
  updateRestoreButtonLabel(listDeletedCitySaveSlots().length);
  updateCloudButtonLabel();
  renderCitySaveSelect(elements?.citySaveSelect ?? document.querySelector<HTMLSelectElement>("#city-save-select"));
  const statusCard = elements?.statusCard ?? document.querySelector<HTMLElement>("#status-card");
  if (statusCard) {
    const counts = blockCounts(state.blocks);
    statusCard.classList.toggle("is-collapsed", state.statusCollapsed);
    statusCard.innerHTML = `
      <button class="status-toggle" type="button" aria-expanded="${!state.statusCollapsed}" aria-label="${state.statusCollapsed ? "展开城市状态" : "折叠城市状态"}">
        <span>城市状态</span>
        <strong>${state.statusCollapsed ? "展开" : "收起"}</strong>
      </button>
      ${
        state.statusCollapsed
          ? ""
          : `<div class="status-score">${state.score}</div>
             <div class="status-label">交通评分</div>
             <div class="status-grid">
               <span>车辆</span><strong>${state.vehicles.length}</strong>
               <span>积木</span><strong>${counts.road + counts.overpass + counts.roadwork + counts.trafficLight + counts.building + counts.park + counts.busStop}</strong>
               <span>天气</span><strong>${weatherLabel(state.weather)}</strong>
               <span>心情</span><strong>${state.cityMood}</strong>
             </div>`
      }
    `;
    statusCard.querySelector<HTMLButtonElement>(".status-toggle")?.addEventListener("click", () => {
      state.statusCollapsed = !state.statusCollapsed;
      renderUi(state, elements);
    });
  }

  renderRoadNamePopover(state, elements?.roadNamePopover ?? document.querySelector<HTMLElement>("#road-name-popover"));

  const modal = elements?.modal ?? document.querySelector<HTMLElement>("#city-check-modal");
  if (modal) {
    const counts = blockCounts(state.blocks);
    const longest = longestRoadGroup(state.roadGroups);
    const roadName = longest?.name ?? "你的道路";
    modal.hidden = !state.showCityCheck;
    modal.innerHTML = `
      <div class="modal-panel">
        <h2>城市体检</h2>
        <p class="modal-score">${state.score} 分</p>
        <p>你的城市已经有 ${counts.road} 块道路、${counts.overpass} 座立交桥、${counts.roadwork} 处施工、${counts.trafficLight} 个红绿灯、${counts.building} 座建筑、${counts.park} 个公园和 ${counts.busStop} 个公交站。</p>
        <p>试试给 ${roadName} 旁边加个公园，让大家开车也有好心情。</p>
        <button class="tool-button primary" data-close-city-check type="button">知道啦</button>
      </div>
    `;
    modal.querySelector("[data-close-city-check]")?.addEventListener("click", () => {
      state.showCityCheck = false;
      renderUi(state, elements);
    });
  }
}

export function showBusRoutePicker(state: AppState, cell: GridCell, onChange: () => void): boolean {
  const stops = busStopsInCity(state);
  const modal = document.querySelector<HTMLElement>("#city-check-modal");
  const toast = document.querySelector<HTMLElement>("#toast");
  if (!modal) return false;
  if (stops.length < 2) {
    if (toast) showToast(toast, "先放至少两个公交站");
    return false;
  }

  state.showCityCheck = false;
  let selectedStopIds: string[] = [];
  let busLineName = `公交车 ${state.vehicles.length + 1}`;

  const renderNameStep = (): void => {
    modal.hidden = false;
    modal.innerHTML = `
      <div class="modal-panel bus-route-panel">
        <div class="bus-route-panel__header">
          <h2>先给公交车命名</h2>
          <button class="modal-close-button" data-cancel-bus-route type="button" aria-label="关闭">×</button>
        </div>
        <div class="bus-route-panel__body">
          <label class="bus-name-field">
            <span>线路名字</span>
            <input data-bus-line-name value="${escapeHtml(busLineName)}" maxlength="12" placeholder="比如 17路" />
          </label>
          <div class="route-preview" aria-live="polite">
            <span>先起名字，再选择会到达的公交站顺序</span>
          </div>
        </div>
        <div class="modal-actions bus-route-panel__footer">
          <button class="tool-button" data-cancel-bus-route type="button">取消</button>
          <button class="tool-button primary" data-next-bus-route type="button">下一步</button>
        </div>
      </div>
    `;
    const input = modal.querySelector<HTMLInputElement>("[data-bus-line-name]");
    input?.focus();
    input?.select();
    modal.querySelector<HTMLButtonElement>("[data-cancel-bus-route]")?.addEventListener("click", closeBusRoutePicker);
    modal.querySelector<HTMLButtonElement>("[data-next-bus-route]")?.addEventListener("click", () => {
      const clean = (input?.value ?? "").trim();
      busLineName = clean || busLineName;
      renderPicker();
    });
  };

  const renderPicker = (): void => {
    modal.hidden = false;
    const selectedStops = selectedStopIds.map((id) => stops.find((stop) => stop.id === id)).filter((stop) => !!stop);
    modal.innerHTML = `
      <div class="modal-panel bus-route-panel">
        <div class="bus-route-panel__header">
          <h2>${escapeHtml(busLineName)}会到哪些站？</h2>
          <button class="modal-close-button" data-cancel-bus-route type="button" aria-label="关闭">×</button>
        </div>
        <div class="bus-route-panel__body">
          <div class="route-bulk-actions">
            <button class="tool-button" data-select-all-stops type="button">全选站台</button>
            <button class="tool-button" data-clear-stops type="button"${selectedStopIds.length === 0 ? " disabled" : ""}>清空</button>
          </div>
          <div class="route-choice-list" role="list">
            ${stops
              .map((stop) => {
                const index = selectedStopIds.indexOf(stop.id);
                return `<button class="route-stop-choice${index >= 0 ? " is-selected" : ""}" data-stop-id="${escapeHtml(stop.id)}" type="button">
                  <span>${escapeHtml(stop.name)}</span>
                  <strong>${index >= 0 ? index + 1 : "+"}</strong>
                </button>`;
              })
              .join("")}
          </div>
          <div class="route-preview" aria-live="polite">
            ${
              selectedStops.length > 0
                ? selectedStops.map((stop, index) => `<span>${index + 1}. ${escapeHtml(stop!.name)}</span>`).join("")
                : "<span>按想去的顺序点公交站</span>"
            }
          </div>
        </div>
        <div class="modal-actions bus-route-panel__footer">
          <button class="tool-button" data-back-bus-name type="button">上一步</button>
          <button class="tool-button primary" data-confirm-bus-route type="button"${selectedStopIds.length < 2 ? " disabled" : ""}>发车</button>
        </div>
      </div>
    `;

    modal.querySelectorAll<HTMLButtonElement>("[data-stop-id]").forEach((button) => {
      button.addEventListener("click", () => {
        const stopId = button.dataset.stopId;
        if (!stopId) return;
        selectedStopIds = selectedStopIds.includes(stopId) ? selectedStopIds.filter((id) => id !== stopId) : [...selectedStopIds, stopId];
        renderPicker();
      });
    });
    modal.querySelector<HTMLButtonElement>("[data-select-all-stops]")?.addEventListener("click", () => {
      selectedStopIds = routeStopIdsForAllStops(stops);
      renderPicker();
    });
    modal.querySelector<HTMLButtonElement>("[data-clear-stops]")?.addEventListener("click", () => {
      selectedStopIds = [];
      renderPicker();
    });
    modal.querySelector<HTMLButtonElement>("[data-cancel-bus-route]")?.addEventListener("click", closeBusRoutePicker);
    modal.querySelector<HTMLButtonElement>("[data-back-bus-name]")?.addEventListener("click", renderNameStep);
    modal.querySelector<HTMLButtonElement>("[data-confirm-bus-route]")?.addEventListener("click", () => {
      const placed = placeSelectedVehicle(state, cell, selectedStopIds, busLineName, false);
      modal.hidden = true;
      if (toast) showToast(toast, placed ? "公交车开始按站点循环" : "公交车要放在道路上");
      renderUi(state);
      onChange();
    });
  };

  const closeBusRoutePicker = (): void => {
    modal.hidden = true;
    renderUi(state);
  };

  renderNameStep();
  return true;
}

export function routeStopIdsForAllStops<T extends { id: string }>(stops: T[]): string[] {
  return stops.map((stop) => stop.id);
}

export function showCarRoutePicker(state: AppState, cell: GridCell, onChange: () => void): boolean {
  const buildings = buildingsInCity(state);
  const modal = document.querySelector<HTMLElement>("#city-check-modal");
  const toast = document.querySelector<HTMLElement>("#toast");
  if (!modal) return false;
  if (buildings.length < 2) {
    if (toast) showToast(toast, "先放至少两个建筑");
    return false;
  }

  state.showCityCheck = false;
  let selectedBuildingIds: string[] = [];
  let carName = `小轿车 ${state.vehicles.length + 1}`;

  const renderPicker = (): void => {
    modal.hidden = false;
    const selectedBuildings = selectedBuildingIds.map((id) => buildings.find((building) => building.id === id)).filter((building) => !!building);
    modal.innerHTML = `
      <div class="modal-panel bus-route-panel">
        <div class="bus-route-panel__header">
          <h2>小轿车从哪里到哪里？</h2>
          <button class="modal-close-button" data-cancel-car-route type="button" aria-label="关闭">×</button>
        </div>
        <div class="bus-route-panel__body">
          <label class="bus-name-field">
            <span>小车名字</span>
            <input data-car-route-name value="${escapeHtml(carName)}" maxlength="12" placeholder="比如 红色小车" />
          </label>
          <div class="route-choice-list" role="list">
            ${buildings
              .map((building) => {
                const index = selectedBuildingIds.indexOf(building.id);
                return `<button class="route-stop-choice${index >= 0 ? " is-selected" : ""}" data-building-id="${escapeHtml(building.id)}" type="button"${selectedBuildingIds.length >= 2 && index < 0 ? " disabled" : ""}>
                  <span>${escapeHtml(building.name)}</span>
                  <strong>${index >= 0 ? (index === 0 ? "起" : "终") : "+"}</strong>
                </button>`;
              })
              .join("")}
          </div>
          <div class="route-preview" aria-live="polite">
            ${
              selectedBuildings.length > 0
                ? selectedBuildings.map((building, index) => `<span>${index === 0 ? "起点" : "终点"}：${escapeHtml(building!.name)}</span>`).join("")
                : "<span>先点起点建筑，再点终点建筑</span>"
            }
          </div>
        </div>
        <div class="modal-actions bus-route-panel__footer">
          <button class="tool-button" data-cancel-car-route type="button">取消</button>
          <button class="tool-button primary" data-confirm-car-route type="button"${selectedBuildingIds.length < 2 ? " disabled" : ""}>出发</button>
        </div>
      </div>
    `;

    const input = modal.querySelector<HTMLInputElement>("[data-car-route-name]");
    modal.querySelectorAll<HTMLButtonElement>("[data-building-id]").forEach((button) => {
      button.addEventListener("click", () => {
        const buildingId = button.dataset.buildingId;
        if (!buildingId) return;
        selectedBuildingIds = selectedBuildingIds.includes(buildingId) ? selectedBuildingIds.filter((id) => id !== buildingId) : [...selectedBuildingIds, buildingId].slice(0, 2);
        carName = (input?.value ?? "").trim() || carName;
        renderPicker();
      });
    });
    modal.querySelectorAll<HTMLButtonElement>("[data-cancel-car-route]").forEach((button) => {
      button.addEventListener("click", () => {
        modal.hidden = true;
        renderUi(state);
      });
    });
    modal.querySelector<HTMLButtonElement>("[data-confirm-car-route]")?.addEventListener("click", () => {
      carName = (input?.value ?? "").trim() || carName;
      const placed = placeSelectedVehicle(state, cell, [], carName, false, selectedBuildingIds);
      modal.hidden = true;
      if (toast) showToast(toast, placed ? "小轿车开始往返建筑" : "小轿车要放在道路上");
      renderUi(state);
      onChange();
    });
  };

  renderPicker();
  return true;
}

export function showOverpassDirectionPicker(state: AppState, cell: GridCell, onChange: () => void): boolean {
  const modal = document.querySelector<HTMLElement>("#city-check-modal");
  const toast = document.querySelector<HTMLElement>("#toast");
  if (!modal) return false;
  state.showCityCheck = false;
  modal.hidden = false;
  modal.innerHTML = `
    <div class="modal-panel bus-route-panel">
      <div class="bus-route-panel__header">
        <h2>选择立交桥方向</h2>
        <button class="modal-close-button" data-cancel-overpass-direction type="button" aria-label="关闭">×</button>
      </div>
      <div class="bus-route-panel__body">
        <div class="route-choice-list" role="list">
          <button class="route-stop-choice" data-overpass-direction="horizontal" type="button">
            <span>左右</span>
            <strong>↔</strong>
          </button>
          <button class="route-stop-choice" data-overpass-direction="vertical" type="button">
            <span>上下</span>
            <strong>↕</strong>
          </button>
        </div>
      </div>
      <div class="modal-actions bus-route-panel__footer">
        <button class="tool-button" data-cancel-overpass-direction type="button">取消</button>
      </div>
    </div>
  `;

  modal.querySelectorAll<HTMLButtonElement>("[data-overpass-direction]").forEach((button) => {
    button.addEventListener("click", () => {
      const direction = button.dataset.overpassDirection as OverpassDirection;
      const placed = placeSelectedBlock(state, cell, direction);
      modal.hidden = true;
      if (toast) showToast(toast, placed ? (direction === "vertical" ? "已放置上下立交桥" : "已放置左右立交桥") : "这里不能放立交桥");
      renderUi(state);
      onChange();
    });
  });
  modal.querySelectorAll<HTMLButtonElement>("[data-cancel-overpass-direction]").forEach((button) => {
    button.addEventListener("click", () => {
      modal.hidden = true;
      renderUi(state);
    });
  });
  return true;
}

function handleAction(action: string, state: AppState, elements: UiElements, onChange: () => void): void {
  if (action === "toggle-running") {
    state.running = !state.running;
    const button = document.querySelector<HTMLButtonElement>('[data-action="toggle-running"]');
    if (button) {
      button.querySelector("strong")!.textContent = state.running ? "暂停" : "运行";
      button.setAttribute("aria-label", state.running ? "暂停城市动线" : "运行城市动线");
    }
  }
  if (action === "cycle-weather") {
    state.weather = cycleWeather(state.weather);
    updateMood(state);
  }
  if (action === "toggle-night") {
    state.night = !state.night;
    updateMood(state);
  }
  if (action === "city-check") {
    state.showCityCheck = true;
  }
  if (action === "save") {
    try {
      saveVisualState(state);
      renderCitySaveSelect(elements.citySaveSelect);
      showToast(elements.toast, "已保存你的城市");
    } catch {
      showToast(elements.toast, "保存失败，请稍后再试");
    }
  }
  if (action === "delete-cell") {
    const deleted = deleteSelectedCellContent(state);
    showToast(elements.toast, deleted ? "已删除选中格子" : "先点一个要删除的格子");
  }
  if (action === "delete-vehicle") {
    const deleted = deleteSelectedVehicle(state);
    showToast(elements.toast, deleted ? "已删除车辆" : "还没有可删除的车辆");
  }
  if (action === "reset-city") {
    resetCityState(state);
    saveVisualState(state);
    showToast(elements.toast, "当前城市已重置");
  }
  if (action === "new-city") {
    const slot = createCitySaveSlot(`我的城市 ${listCitySaveSlots().length + 1}`);
    replaceStateFromSave(state);
    renderCitySaveSelect(elements.citySaveSelect);
    showToast(elements.toast, `已新建${slot.name}`);
  }
  if (action === "delete-city") {
    const current = currentCitySaveSlot();
    const next = current ? deleteCitySaveSlot(current.id) : null;
    if (next) {
      replaceStateFromSave(state);
      renderCitySaveSelect(elements.citySaveSelect);
      showToast(elements.toast, `已暂存删除，切换到${next.name}`);
    } else {
      showToast(elements.toast, "没有可删除的城市");
    }
  }
  if (action === "restore-city") {
    showDeletedCitiesModal(state, elements, onChange);
    return;
  }
  if (action === "cloud-login") {
    void promptAndSyncCloud(state, elements, onChange);
    return;
  }
  if (action.startsWith("tool-")) {
    state.selectedTool = action.replace("tool-", "") as AppState["selectedTool"];
    showToast(elements.toast, `已选择${toolLabel(state.selectedTool)}`);
  }
  renderUi(state, elements);
  onChange();
  if (shouldSyncCloudAfterAction(action)) void syncCurrentCityCloud();
}

function showDeletedCitiesModal(state: AppState, elements: UiElements, onChange: () => void, notice = ""): void {
  const deletedSlots = listDeletedCitySaveSlots();
  elements.modal.hidden = false;
  elements.modal.innerHTML = `
    <div class="modal-panel deleted-cities-panel">
      <div class="bus-route-panel__header">
        <h2>恢复城市</h2>
        <button class="modal-close-button" data-close-restore-city type="button" aria-label="关闭">×</button>
      </div>
      ${notice ? `<p class="restore-notice">${escapeHtml(notice)}</p>` : ""}
      <div class="deleted-city-list" role="list">
        ${
          deletedSlots.length > 0
            ? deletedSlots
                .map(
                  (slot) => `<button class="deleted-city-item" data-restore-city-id="${escapeHtml(slot.id)}" type="button">
                    <span>${escapeHtml(slot.name)}</span>
                    <strong>${daysLeftLabel(slot.expiresAt)}</strong>
                  </button>`,
                )
                .join("")
            : `<p class="empty-restore-note">最近 7 天没有删除的城市</p>`
        }
      </div>
      <div class="modal-actions">
        <button class="tool-button primary" data-close-restore-city type="button">完成</button>
      </div>
    </div>
  `;

  elements.modal.querySelectorAll<HTMLButtonElement>("[data-close-restore-city]").forEach((button) => {
    button.addEventListener("click", () => {
      elements.modal.hidden = true;
      renderUi(state, elements);
    });
  });
  elements.modal.querySelectorAll<HTMLButtonElement>("[data-restore-city-id]").forEach((button) => {
    button.addEventListener("click", () => {
      const restored = restoreDeletedCitySaveSlot(button.dataset.restoreCityId ?? "");
      if (!restored) {
        showToast(elements.toast, "这个城市已经不能恢复了");
        showDeletedCitiesModal(state, elements, onChange);
        return;
      }
      replaceStateFromSave(state);
      renderCitySaveSelect(elements.citySaveSelect);
      elements.modal.hidden = true;
      showToast(elements.toast, `已恢复${restored.name}`);
      renderUi(state, elements);
      onChange();
      void syncCurrentCityCloud();
    });
  });
}

function updateRestoreButtonLabel(count: number): void {
  const label = document.querySelector<HTMLButtonElement>('[data-action="restore-city"] strong');
  if (!label) return;
  label.textContent = count > 0 ? `恢复(${count})` : "恢复";
}

function updateCloudButtonLabel(): void {
  const label = document.querySelector<HTMLButtonElement>('[data-action="cloud-login"] strong');
  if (!label) return;
  const user = getSavedCloudUserName();
  label.textContent = user ? "已云同步" : "云同步";
}

async function promptAndSyncCloud(state: AppState, elements: UiElements, onChange: () => void): Promise<void> {
  const current = getSavedCloudUserName();
  const name = window.prompt("输入玩家名，同名设备会同步到同一份云端城市数据", current || "小勇");
  if (name === null) return;
  const result = await loginAndSyncCityCloud(name);
  showToast(elements.toast, result.message);
  if (result.ok) {
    replaceStateFromSave(state);
    renderUi(state, elements);
    onChange();
  }
}

async function syncCloudAndRefresh(state: AppState, elements: UiElements, onChange: () => void, showResult: boolean): Promise<void> {
  const result = await loginAndSyncCityCloud(getSavedCloudUserName());
  if (showResult) showToast(elements.toast, result.message);
  if (result.ok) {
    replaceStateFromSave(state);
    renderUi(state, elements);
    onChange();
  }
}

function shouldSyncCloudAfterAction(action: string): boolean {
  return action === "save" || action === "new-city" || action === "delete-city" || action === "reset-city";
}

function renderCitySaveSelect(select: HTMLSelectElement | null): void {
  if (!select) return;
  const slots = listCitySaveSlots();
  const current = currentCitySaveSlot();
  select.innerHTML = "";
  if (slots.length === 0) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "未保存城市";
    select.append(option);
    select.disabled = true;
    return;
  }
  select.disabled = false;
  for (const slot of slots) {
    const option = document.createElement("option");
    option.value = slot.id;
    option.textContent = slot.name;
    select.append(option);
  }
  select.value = current?.id ?? slots[0].id;
}

function renderToolbarState(state: AppState): void {
  document.querySelectorAll<HTMLButtonElement>("[data-action^='tool-']").forEach((button) => {
    const tool = button.dataset.action?.replace("tool-", "");
    const selected = tool === state.selectedTool;
    button.classList.toggle("is-selected", selected);
    button.setAttribute("aria-pressed", String(selected));
  });
}

function renderRoadNamePopover(state: AppState, popover: HTMLElement | null): void {
  if (!popover || !state.selectedEntity || !state.selectedCell) {
    if (popover) popover.hidden = true;
    return;
  }
  const entity = selectedEntityDisplay(state);
  if (!entity) {
    popover.hidden = true;
    return;
  }
  popover.hidden = false;
  popover.innerHTML = `
    <label>
      <span>${entity.label}</span>
      <input data-entity-name-input value="${escapeHtml(entity.name)}" maxlength="12" />
    </label>
    <button class="tool-button primary" data-save-entity-name type="button">命名</button>
  `;
  popover.querySelector<HTMLButtonElement>("[data-save-entity-name]")?.addEventListener("click", () => {
    const input = popover.querySelector<HTMLInputElement>("[data-entity-name-input]");
    renameSelectedEntity(state, input?.value ?? "");
    renderUi(state);
  });
}

function selectedEntityDisplay(state: AppState): { label: string; name: string } | null {
  const entity = state.selectedEntity;
  if (!entity) return null;
  if (entity.kind === "roadGroup") {
    const group = state.roadGroups.find((item) => item.id === entity.id);
    return group ? { label: "道路名字", name: group.name } : null;
  }
  if (entity.kind === "block") {
    const block = Object.values(state.blocks).find((item) => item.id === entity.id);
    if (!block) return null;
    return { label: `${toolLabel(block.type)}名字`, name: block.name };
  }
  const vehicle = state.vehicles.find((item) => item.id === entity.id);
  return vehicle ? { label: `${toolLabel(vehicle.type)}名字`, name: vehicle.name } : null;
}

function showToast(toast: HTMLElement, text: string): void {
  if (toastTimer !== null) {
    window.clearTimeout(toastTimer);
    toastTimer = null;
  }
  toast.textContent = text;
  toast.hidden = false;
  toastTimer = window.setTimeout(() => {
    toast.hidden = true;
    toastTimer = null;
  }, 1400);
}

function weatherLabel(weather: AppState["weather"]): string {
  if (weather === "rainy") return "雨天";
  if (weather === "snowy") return "雪天";
  return "晴天";
}

function toolLabel(tool: AppState["selectedTool"]): string {
  if (tool === "overpass") return "立交桥";
  if (tool === "roadwork") return "道路施工";
  if (tool === "trafficLight") return "红绿灯";
  if (tool === "building") return "建筑";
  if (tool === "park") return "公园";
  if (tool === "busStop") return "公交站";
  if (tool === "sedan") return "小轿车";
  if (tool === "bus") return "公交车";
  if (tool === "offroad") return "越野车";
  if (tool === "sweeper") return "扫地车";
  return "道路";
}

function daysLeftLabel(expiresAt: string): string {
  const msLeft = Date.parse(expiresAt) - Date.now();
  const days = Math.max(1, Math.ceil(msLeft / (24 * 60 * 60 * 1000)));
  return `剩 ${days} 天`;
}

function escapeHtml(text: string): string {
  return text
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function requireElement(selector: string): HTMLElement {
  const element = document.querySelector<HTMLElement>(selector);
  if (!element) throw new Error(`Missing ${selector}`);
  return element;
}
