(function () {
  "use strict";

  const API = {
    dashboard: "/api/dashboard",
    probe: "/api/probe",
    start: "/api/listener/start",
    stop: "/api/listener/stop",
    settings: "/api/settings",
    messages: "/api/messages",
    questions: "/api/questions?status=pending",
    demo: "/api/demo/messages",
  };
  const $ = (selector) => document.querySelector(selector);
  let dashboard = null;
  let rulesDirty = false;
  let messageQuery = { page: 1, pageSize: 20, search: "", pages: 1 };
  let questionQuery = { page: 1, pageSize: 50, pages: 1, total: 0 };
  const selectedQuestions = new Map();

  async function request(url, options = {}) {
    let response;
    try {
      response = await fetch(url, {
        ...options,
        headers: { "Content-Type": "application/json", ...(options.headers || {}) },
      });
    } catch (_) {
      throw new Error("无法连接本地服务。请运行“2-启动服务”入口，等待终端显示启动成功后刷新页面。");
    }
    if (!response.ok) {
      let detail = "";
      try { detail = (await response.json()).detail || ""; } catch (_) { detail = await response.text(); }
      throw new Error(detail || `请求失败（${response.status}）`);
    }
    return response.status === 204 ? null : response.json();
  }

  function make(tag, className, value) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (value !== undefined) node.textContent = String(value);
    return node;
  }

  function showToast(message, error = false) {
    const toast = make("div", `toast${error ? " error" : ""}`, message);
    toast.setAttribute("role", error ? "alert" : "status");
    $("#toast-region").append(toast);
    window.setTimeout(() => toast.remove(), error ? 7200 : 3800);
  }

  function formatTime(value, seconds = false) {
    if (!value) return "—";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    return new Intl.DateTimeFormat("zh-CN", {
      month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
      second: seconds ? "2-digit" : undefined, hour12: false,
    }).format(date);
  }


  function setText(selector, value) {
    const node = $(selector);
    if (node) node.textContent = value === null || value === undefined || value === "" ? "—" : String(value);
  }

  function renderProbe(probe) {
    const platform = probe.platform || "本机";
    const platformCode = probe.platform_code || (platform === "Windows" ? "windows" : "macos");
    const canDecode = Boolean(probe.can_decode);
    const canObserve = Boolean(probe.can_observe_wal);
    const blockers = probe.blockers || [];
    const banner = $("#compatibility-banner");
    banner.className = `compatibility-banner ${canDecode ? "good" : canObserve ? "" : "bad"}`;
    setText("#compatibility-title", canDecode ? `${platform} 本机监听与解码链路可用` : canObserve ? "数据变化监听可用，消息解析仍被门禁阻断" : `${platform} 本机监听环境不完整`);
    setText("#compatibility-detail", canDecode ? "检测到微信数据变化后，将自动解析并按规则筛选新消息。" : blockers.join("；") || "请查看环境诊断。 ");
    setText("#compatibility-tag", canDecode ? "可监听" : canObserve ? "观察模式" : "已阻断");

    setText("#wechat-running", probe.wechat.running ? "正在运行" : "未运行");
    setText("#wechat-version", probe.wechat.version ? `${probe.wechat.version} (${probe.wechat.build || "—"})` : "未识别");
    setText("#database-count", `${probe.data.database_count || 0} 个`);
    setText("#wal-count", `${probe.data.wal_count || 0} 个`);
    setText("#shm-count", `${probe.data.shm_count || 0} 个`);
    setText("#selected-account", probe.data.selected_account_fingerprint || (probe.data.selected ? "已选择" : "未选择"));
    setText("#decoder-profile", probe.decoder.profile_id || (probe.decoder.profile_exact_match ? "已匹配" : "未验证"));
    setText("#key-validated", probe.decoder.key_validated_at ? formatTime(probe.decoder.key_validated_at, true) : "未准备");
    setText("#schema-fingerprint", probe.decoder.schema_fingerprint || "未验证");
    setText("#layout-fingerprint", probe.data.layout_fingerprint || "未识别");
    setText("#platform-subtitle", "群消息整理与跟进");
    setText("#listener-detail-platform", `${platform} 监听链路`);
    setText("#footer-platform", "消息保存在本机");
    const list = $("#blocker-list");
    if (list) {
      list.replaceChildren();
      const details = probe.blocker_details || [];
      (details.length ? details : blockers.map((message) => ({ message }))).forEach((item) => {
        const text = item.action ? `${item.message}；下一步：${item.action}` : item.message;
        list.append(make("li", "", text));
      });
      if (!details.length && !blockers.length) list.append(make("li", "", "未发现环境阻断项。仍需使用测试群验证消息完整性。"));
    }
  }

  function renderDashboard(payload) {
    dashboard = payload;
    const stats = payload.stats || {};
    const listener = payload.listener || {};
    const process = payload.process || {};
    setText("#metric-messages", stats.message_count ?? 0);
    setText("#metric-pending", stats.pending_count ?? 0);
    setText("#metric-confirmed", stats.confirmed_count ?? 0);
    setText("#metric-wal-events", listener.wal_event_count ?? 0);
    setText("#last-wal-activity", formatTime(listener.last_wal_activity_at, true));
    setText("#last-decode", formatTime(listener.last_decode_at, true));
    const highWaterValues = Object.values(payload.high_water || {}).map(Number).filter(Number.isFinite);
    setText("#message-high-water", highWaterValues.length ? formatTime(new Date(Math.max(...highWaterValues) * 1000), true) : "尚未建立");
    setText("#runtime-state", stateLabel(listener.state));
    setText("#listener-runtime-detail", listener.detail || "—");
    setText("#last-updated", `更新于 ${formatTime(new Date(), true)}`);
    renderProbe(payload.probe);

    const running = Boolean(process.running);
    const state = listener.state || "stopped";
    const dot = $("#listener-dot");
    dot.className = `status-dot ${running && ["listening", "importing_history"].includes(state) ? "online" : running && state === "observe_only" ? "observe" : running ? "error" : ""}`;
    setText("#listener-status", running ? (state === "listening" ? "监听并解码中" : state === "importing_history" ? "首次历史导入中" : state === "observe_only" ? "仅观察 WAL" : stateLabel(state)) : "监听已停止");
    const button = $("#listener-toggle");
    button.disabled = !running && !payload.probe.can_decode;
    button.dataset.action = running ? "stop" : "start";
    button.textContent = running ? "停止采集" : "开始采集";
    button.className = `button ${running ? "danger" : "primary"}`;
    document.dispatchEvent(new CustomEvent("delivery:dashboard", {detail:payload}));
  }

  function stateLabel(state) {
    return ({ stopped: "已停止", stopping: "正在停止", probing: "探测中", importing_history: "导入历史中", observe_only: "数据观察", listening: "监听中", blocked: "已阻断", partial_blocked: "部分群已阻断", decoder_error: "解码异常" })[state] || state || "未知";
  }

  function renderQuestions(payload) {
    const items = payload.items || [];
    const visibleIds = new Set(items.map((item) => String(item.id)));
    [...selectedQuestions.keys()].forEach((id) => { if (!visibleIds.has(id)) selectedQuestions.delete(id); });
    const container = $("#question-list");
    container.className = "question-list";
    container.replaceChildren();
    questionQuery.page = payload.page || 1;
    questionQuery.pages = payload.pages || 1;
    questionQuery.total = payload.total ?? items.length;
    setText("#pending-badge", new Intl.NumberFormat("zh-CN").format(questionQuery.total));
    $("#question-batch-toolbar").hidden = !items.length;
    $("#question-pagination").hidden = questionQuery.total <= questionQuery.pageSize;
    setText("#question-page-info", `第 ${questionQuery.page}/${questionQuery.pages} 页 · 共 ${questionQuery.total} 条`);
    $("#question-prev").disabled = questionQuery.page <= 1;
    $("#question-next").disabled = questionQuery.page >= questionQuery.pages;
    if (!items.length) {
      updateQuestionSelection();
      container.append(make("div", "empty", "暂无待复核问题"));
      return;
    }
    items.forEach((item) => {
      const card = make("article", "question-card");
      card.dataset.id = item.id;
      card.dataset.version = item.version;
      const selector = make("label", "question-selector");
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.dataset.questionSelect = "true";
      checkbox.checked = selectedQuestions.has(String(item.id));
      checkbox.setAttribute("aria-label", `选择问题：${item.title}`);
      selector.append(checkbox);
      const body = make("div");
      const meta = make("div", "question-meta");
      [item.chat_name, item.sender, formatTime(item.source_time), `识别 ${Math.round(item.confidence * 100)}%`]
        .forEach((value) => meta.append(make("span", "", value)));
      body.append(meta, make("h3", "", item.title));
      if (item.content !== item.title) body.append(make("p", "question-source", `原消息：${item.content}`));
      const actions = make("div", "question-actions");
      const confirm = make("button", "button primary small", "确认");
      confirm.type = "button"; confirm.dataset.status = "confirmed";
      const ignore = make("button", "button small", "忽略");
      ignore.type = "button"; ignore.dataset.status = "ignored";
      actions.append(confirm, ignore);
      card.append(selector, body, actions);
      container.append(card);
    });
    updateQuestionSelection();
  }

  function updateQuestionSelection() {
    const checkboxes = [...document.querySelectorAll("input[data-question-select]")];
    const checked = checkboxes.filter((checkbox) => checkbox.checked);
    setText("#question-selected-count", `已选 ${checked.length} 条`);
    $("#question-batch-confirm").disabled = checked.length === 0;
    $("#question-batch-ignore").disabled = checked.length === 0;
    const selectAll = $("#question-select-all");
    selectAll.checked = Boolean(checkboxes.length && checked.length === checkboxes.length);
    selectAll.indeterminate = checked.length > 0 && checked.length < checkboxes.length;
  }

  function renderMessages(payload) {
    const body = $("#message-list");
    body.replaceChildren();
    const items = payload.items || [];
    if (!items.length) {
      const row = document.createElement("tr");
      const cell = make("td", "empty", "尚无已解码消息"); cell.colSpan = 5; row.append(cell); body.append(row);
    }
    items.forEach((item) => {
      const row = document.createElement("tr");
      row.append(make("td", "", formatTime(item.source_time)), make("td", "", item.chat_name), make("td", "", item.sender));
      const content = make("td", "message-content");
      const bodyText = item.content_text || item.content;
      content.append(make("div", "message-text", bodyText));
      if (item.content_kind === "quote") {
        const quote = make("blockquote", `message-quote${item.quote_kind === "image" ? " image" : ""}`);
        quote.append(
          make("span", "message-quote-label", item.quote_sender ? `引用 ${item.quote_sender}` : "引用原消息"),
          make("p", "", item.quote_content || "原消息内容为空")
        );
        content.append(quote);
      }
      content.title = item.content; row.append(content);
      const tagCell = make("td");
      const tags = make("div", "tags");
      const rules = item.matched_rules || [];
      (rules.length ? rules : [item.source_kind === "demo" ? "模拟" : "未命中"])
        .forEach((rule) => tags.append(make("span", `tag${rules.length ? "" : " neutral"}`, rule)));
      tagCell.append(tags); row.append(tagCell); body.append(row);
    });
    messageQuery.pages = payload.pages || 1;
    setText("#message-page-info", `第 ${payload.page || 1}/${messageQuery.pages} 页 · 共 ${payload.total || 0} 条`);
    $("#message-prev").disabled = messageQuery.page <= 1;
    $("#message-next").disabled = messageQuery.page >= messageQuery.pages;
  }

  function renderSettings(data) {
    $("#allowed-groups").value = (data.groups || []).join("\n");
    $("#self-names").value = (data.self_names || []).join("\n");
    if (rulesDirty) return;
    $("#target-names").value = (data.target_names || []).join("\n");
    $("#keywords").value = (data.keywords || []).join("\n");
    $("#require-at-me").checked = Boolean(data.require_at_me);
    $("#retention-days").value = data.retention_days || 7;
    setText("#rules-updated", data.updated_at ? `更新于 ${formatTime(data.updated_at)}` : "");
  }

  async function loadMessages() {
    const params = new URLSearchParams({ page: String(messageQuery.page), page_size: String(messageQuery.pageSize), search: messageQuery.search });
    renderMessages(await request(`${API.messages}?${params}`));
  }

  async function loadQuestions() {
    const params = new URLSearchParams({
      status: "pending",
      page: String(questionQuery.page),
      page_size: String(questionQuery.pageSize),
    });
    renderQuestions(await request(`/api/questions?${params}`));
  }

  async function loadAll(silent = false) {
    const refreshButton = $("#refresh-button");
    refreshButton.disabled = true;
    const jobs = [
      request(API.dashboard).then(renderDashboard),
      loadQuestions(),
      loadMessages(),
      request(API.settings).then(renderSettings),
    ];
    const results = await Promise.allSettled(jobs);
    if (!silent) results.filter((r) => r.status === "rejected").forEach((r) => showToast(r.reason.message, true));
    refreshButton.disabled = false;
    return results;
  }

  async function refreshAll() {
    const button = $("#refresh-button");
    button.disabled = true;
    button.classList.add("is-refreshing");
    button.setAttribute("aria-busy", "true");
    button.textContent = "刷新中…";
    try {
      const results = await loadAll(true);
      const failures = results.filter((result) => result.status === "rejected");
      if (failures.length) {
        showToast(`部分数据刷新失败（${failures.length} 项）`, true);
      } else {
        showToast("数据已刷新");
      }
    } finally {
      button.textContent = "刷新";
      button.classList.remove("is-refreshing");
      button.removeAttribute("aria-busy");
      button.disabled = false;
    }
  }

  async function toggleListener() {
    const button = $("#listener-toggle");
    const action = button.dataset.action || "start";
    button.disabled = true;
    try {
      await request(action === "start" ? API.start : API.stop, { method: "POST", body: "{}" });
      showToast(action === "start" ? "本机监听已启动" : "监听已停止");
      await new Promise((resolve) => setTimeout(resolve, 650));
      await loadAll(true);
    } catch (error) { showToast(error.message, true); } finally { if (dashboard) renderDashboard(dashboard); }
  }

  async function reviewQuestion(card, status) {
    card.querySelectorAll("button").forEach((button) => { button.disabled = true; });
    try {
      await request(`/api/questions/${card.dataset.id}`, {
        method: "PATCH",
        body: JSON.stringify({ status, expected_version: Number(card.dataset.version) }),
      });
      showToast(status === "confirmed" ? "问题已确认" : "问题已忽略");
      await loadAll(true);
    } catch (error) { showToast(error.message, true); card.querySelectorAll("button").forEach((button) => { button.disabled = false; }); }
  }

  async function batchReview(status) {
    const selected = [...selectedQuestions.values()];
    if (!selected.length) return;
    const label = status === "confirmed" ? "确认" : "忽略";
    if (!window.confirm(`确定批量${label}已选的 ${selected.length} 条问题吗？`)) return;
    const buttons = [$("#question-batch-confirm"), $("#question-batch-ignore")];
    buttons.forEach((button) => { button.disabled = true; });
    try {
      const result = await request("/api/questions/batch-review", {
        method: "POST",
        body: JSON.stringify({ status, items: selected }),
      });
      selectedQuestions.clear();
      await loadAll(true);
      showToast(`已批量${label} ${result.updated} 条${result.skipped ? `，跳过 ${result.skipped} 条已变化记录` : ""}`);
    } catch (error) {
      showToast(error.message, true);
      updateQuestionSelection();
    }
  }

  async function saveRules(event) {
    event.preventDefault();
    const lines = (selector) => $(selector).value.split(/\r?\n/).map((v) => v.trim()).filter(Boolean);
    const button = event.submitter; button.disabled = true;
    try {
      const automatic = $("#flow-auto-results").checked;
      if (automatic && !$("#flow-auto-consent").checked) throw new Error("开启自动整理前，请同意后续脱敏文本发送至 DeepSeek");
      const projectId = Number(document.body.dataset.projectId);
      if (!projectId) throw new Error("请先在“微信与群聊”保存整理空间");
      const canonical = await request(API.settings);
      if (!canonical.groups.length || !canonical.self_names.length) throw new Error("请先在“微信与群聊”保存群名称和昵称");
      const data = await request(API.settings, {
        method: "PUT",
        body: JSON.stringify({
          groups: canonical.groups, self_names: canonical.self_names,
          target_names: lines("#target-names"), keywords: lines("#keywords"),
          require_at_me: $("#require-at-me").checked, retention_days: Number($("#retention-days").value),
        }),
      });
      try {
        await request("/api/workflow/automation", {method:"PUT",body:JSON.stringify({project_id:projectId,enabled:automatic,consent:automatic && $("#flow-auto-consent").checked})});
      } catch (error) { throw new Error(`采集规则已保存，自动整理设置未生效：${error.message}`); }
      rulesDirty = false; renderSettings(data); showToast(automatic?"规则已保存，新消息将自动整理":"规则已保存，使用手动分析");
      document.dispatchEvent(new CustomEvent("delivery:rules-saved", {detail:data}));
    } catch (error) { showToast(error.message, true); } finally { button.disabled = false; }
  }

  function bindEvents() {
    document.querySelectorAll(".tab").forEach((tab) => tab.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach((node) => node.classList.toggle("active", node === tab));
      document.querySelectorAll(".tab-panel").forEach((panel) => panel.classList.toggle("active", panel.id === `tab-${tab.dataset.tab}`));
    }));
    $("#refresh-button").addEventListener("click", refreshAll);
    $("#listener-toggle").addEventListener("click", toggleListener);
    $("#rules-form").addEventListener("submit", saveRules);
    $("#rules-form").addEventListener("input", () => { rulesDirty = true; });
    document.addEventListener("delivery:setup-saved", () => request(API.settings).then(renderSettings).catch(e => showToast(e.message, true)));
    $("#question-list").addEventListener("click", (event) => { const button = event.target.closest("button[data-status]"); if (button) reviewQuestion(button.closest(".question-card"), button.dataset.status); });
    $("#question-list").addEventListener("change", (event) => {
      const checkbox = event.target.closest("input[data-question-select]");
      if (!checkbox) return;
      const card = checkbox.closest(".question-card");
      if (checkbox.checked) selectedQuestions.set(card.dataset.id, { id: Number(card.dataset.id), expected_version: Number(card.dataset.version) });
      else selectedQuestions.delete(card.dataset.id);
      updateQuestionSelection();
    });
    $("#question-select-all").addEventListener("change", (event) => {
      document.querySelectorAll("input[data-question-select]").forEach((checkbox) => {
        checkbox.checked = event.target.checked;
        const card = checkbox.closest(".question-card");
        if (checkbox.checked) selectedQuestions.set(card.dataset.id, { id: Number(card.dataset.id), expected_version: Number(card.dataset.version) });
        else selectedQuestions.delete(card.dataset.id);
      });
      updateQuestionSelection();
    });
    $("#question-batch-confirm").addEventListener("click", () => batchReview("confirmed"));
    $("#question-batch-ignore").addEventListener("click", () => batchReview("ignored"));
    $("#question-prev").addEventListener("click", () => {
      if (questionQuery.page <= 1) return;
      selectedQuestions.clear();
      questionQuery.page -= 1;
      loadQuestions().catch((error) => showToast(error.message, true));
    });
    $("#question-next").addEventListener("click", () => {
      if (questionQuery.page >= questionQuery.pages) return;
      selectedQuestions.clear();
      questionQuery.page += 1;
      loadQuestions().catch((error) => showToast(error.message, true));
    });
    $("#message-search-form").addEventListener("submit", (event) => { event.preventDefault(); messageQuery.search = $("#message-search").value.trim(); messageQuery.page = 1; loadMessages().catch((e) => showToast(e.message, true)); });
    $("#message-search-clear").addEventListener("click", () => { $("#message-search").value = ""; messageQuery.search = ""; messageQuery.page = 1; loadMessages(); });
    $("#message-page-size").addEventListener("change", (event) => { messageQuery.pageSize = Number(event.target.value); messageQuery.page = 1; loadMessages(); });
    $("#message-prev").addEventListener("click", () => { if (messageQuery.page > 1) { messageQuery.page -= 1; loadMessages(); } });
    $("#message-next").addEventListener("click", () => { if (messageQuery.page < messageQuery.pages) { messageQuery.page += 1; loadMessages(); } });

  }

  async function init() {
    bindEvents();
    await loadAll();
    window.setInterval(() => loadAll(true), 30000);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
