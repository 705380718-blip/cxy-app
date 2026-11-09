(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  let allowedGroups = [], projects = [], preview = null, savedAI = null;
  const el = (tag, text, cls) => { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; if (cls) n.className = cls; return n; };
  function toast(message, error = false) {
    const n = el("div", message, error ? "toast error" : "toast"); n.setAttribute("role", error ? "alert" : "status");
    $("toast-region").append(n); setTimeout(() => n.remove(), 6500);
  }
  async function api(url, method = "GET", data) {
    const r = await fetch(url, {method, headers: {"Content-Type":"application/json"}, ...(data ? {body:JSON.stringify(data)} : {})});
    const result = await r.json();
    if (!r.ok) throw new Error(typeof result.detail === "string" ? result.detail : "字段格式不正确，请检查输入");
    return result;
  }
  async function busy(button, action) {
    if (button.disabled) return;
    button.disabled = true; button.setAttribute("aria-busy", "true");
    try { await action(); } catch (e) { toast(e.message, true); } finally { button.disabled = false; button.removeAttribute("aria-busy"); }
  }
  function options(select, rows, empty) {
    const old = select.value; select.replaceChildren();
    if (!rows.length) { const n = new Option(empty, ""); select.add(n); }
    else rows.forEach(([value, label]) => select.add(new Option(label, String(value))));
    if ([...select.options].some(o => o.value === old)) select.value = old;
  }
  function invalidatePreview() { preview = null; $("import-preview-card").hidden = true; $("import-commit").disabled = true; }
  function renderSources() {
    const selected = projects.find(p => String(p.id) === $("delivery-project").value);
    const sources = selected ? selected.sources.filter(s => allowedGroups.includes(s.source_key)) : [];
    $("delivery-source-list").replaceChildren();
    if (!sources.length) $("delivery-source-list").append(el("p", "此项目还没有消息来源。", "muted"));
    sources.forEach(s => {
      const card = el("article", undefined, "delivery-source");
      card.append(el("strong", s.display_name), el("p", `${s.source_kind === "import" ? "手动导入" : "本机采集"} · ${s.source_key} · ${s.message_count} 条`, "muted"));
      if (s.period_start) card.append(el("small", `覆盖 ${beijingTime(s.period_start)} 至 ${beijingTime(s.period_end)}（北京时间）`, "muted"));
      $("delivery-source-list").append(card);
    });
    options($("import-source"), sources.filter(s => s.source_kind === "import").map(s => [s.id,s.display_name]), "请先绑定手动导入来源");
  }
  function beijingTime(value) {
    return new Intl.DateTimeFormat("zh-CN", {timeZone:"Asia/Shanghai",year:"numeric",month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit",second:"2-digit",hour12:false}).format(new Date(value));
  }
  async function loadSources() {
    const [data, rules] = await Promise.all([api("/api/projects"),api("/api/settings")]);
    projects = data.items.filter(p => p.enabled); allowedGroups = rules.groups;
    options($("delivery-project"),projects.map(p => [p.id,p.name]),"请先创建项目");
    options($("source-group"),rules.groups.map(g => [g,g]),"请先添加群白名单");
    if (document.body.dataset.projectId) $("delivery-project").value = document.body.dataset.projectId;
    renderSources();
  }
  async function loadAI() {
    savedAI = await api("/api/ai/settings");
    $("ai-key-state").textContent = savedAI.key_configured ? "密钥已配置" : "未配置密钥";
    $("ai-enabled").checked = savedAI.enabled;
    $("ai-base-url").value = savedAI.base_url; $("ai-model").value = savedAI.model;
    $("ai-timeout").value = savedAI.timeout_seconds; $("ai-budget").value = savedAI.max_calls_per_day; $("ai-tokens").value = savedAI.max_output_tokens;
    $("ai-batch").value = savedAI.max_batch_messages; $("ai-input-limit").value = savedAI.max_input_chars;
    $("ai-key").value = ""; $("ai-clear-key").checked = false;
  }
  function renderPreview(data) {
    preview = data; $("import-preview-card").hidden = false;
    $("import-summary").textContent = `${data.row_count} 条有效消息 · ${data.errors.length} 处错误${data.rows.length > 200 ? " · 预览前 200 条" : ""}`;
    $("import-duplicates").textContent = data.status === "committed" ? "该文件已导入，再次确认将复用结果，新增为 0。" : (data.possible_duplicates ? `${data.possible_duplicates} 条疑似跨文件重复；缺少稳定外部 ID，确认后仍会导入，请核对。` : "确认后写入本机消息库。导入记录会标记为手动导入。");
    $("import-errors").replaceChildren(...data.errors.map(e => el("li",`原文件第 ${e.line} 行：${e.detail}`)));
    $("import-preview-rows").replaceChildren(...data.rows.slice(0,200).map(r => { const tr = el("tr"); [r.line,beijingTime(r.timestamp),r.sender,r.content].forEach(v => tr.append(el("td",v))); return tr; }));
    $("import-result").textContent = ""; $("import-accept-valid").checked = false;
    $("import-commit").disabled = !data.id;
  }
  $("project-create").addEventListener("submit", event => { event.preventDefault(); busy(event.submitter,async () => {
    const p = await api("/api/projects","POST",{name:$("project-name").value.trim()});
    $("project-name").value = ""; await loadSources(); $("delivery-project").value = String(p.id); renderSources(); invalidatePreview(); toast("项目已创建");
  }); });
  $("source-bind").addEventListener("submit", event => { event.preventDefault(); busy(event.submitter,async () => {
    await api(`/api/projects/${$("delivery-project").value}/sources`,"PUT",{source_kind:$("source-kind").value,source_key:$("source-group").value,display_name:$("source-display").value.trim()});
    await loadSources(); invalidatePreview(); toast("来源已绑定");
  }); });
  $("delivery-project").addEventListener("change",() => { renderSources(); invalidatePreview(); });
  ["import-source","import-format","import-content","import-default-sender","import-default-time"].forEach(id => $(id).addEventListener("input",invalidatePreview));
  $("import-file").addEventListener("change",async () => {
    invalidatePreview(); const file = $("import-file").files[0]; if (!file) return;
    try {
      if (file.size > 2*1024*1024) throw new Error("文件不能超过 2 MiB");
      $("import-content").value = new TextDecoder("utf-8",{fatal:true}).decode(await file.arrayBuffer());
      $("import-format").value = file.name.toLowerCase().endsWith(".csv") ? "csv" : "txt";
    } catch (e) { toast(e.message.includes("encoded") ? "请将文件另存为 UTF-8 编码" : e.message,true); }
  });
  $("import-preview-form").addEventListener("submit",event => { event.preventDefault(); busy(event.submitter,async () => {
    const data = {project_source_id:Number($("import-source").value),format:$("import-format").value,content:$("import-content").value};
    if ($("import-default-sender").value.trim()) data.default_sender = $("import-default-sender").value.trim();
    if ($("import-default-time").value) data.default_timestamp = $("import-default-time").value+"+08:00";
    renderPreview(await api("/api/imports/preview","POST",data)); $("import-preview-card").scrollIntoView({behavior:"smooth",block:"nearest"});
  }); });
  $("import-commit").addEventListener("click",() => busy($("import-commit"),async () => {
    if (!preview || !preview.id) return;
    const result = await api(`/api/imports/${preview.id}/commit`,"POST",{accept_valid_rows:$("import-accept-valid").checked});
    $("import-result").textContent = `新增 ${result.inserted} 条 · ${result.reused ? "已复用导入结果" : `重复 ${result.duplicates} 条`}`;
    await loadSources(); toast("消息已导入本机");
    document.dispatchEvent(new CustomEvent("delivery:imported"));
  }));
  $("model-settings-open").addEventListener("click",() => {
    if (!$("model-settings-dialog").open) $("model-settings-dialog").showModal();
    loadAI().catch(e => toast(e.message,true));
  });
  $("model-settings-close").addEventListener("click",() => $("model-settings-dialog").close());
  $("model-settings-dialog").addEventListener("close",() => { $("ai-key").value=""; });
  $("ai-config-form").addEventListener("submit",event => { event.preventDefault(); busy(event.submitter,async () => {
    if (!savedAI) throw new Error("模型配置尚未加载，请重新打开设置页");
    const {key_configured, ...base} = savedAI;
    const data = {...base,enabled:$("ai-enabled").checked,base_url:$("ai-base-url").value,model:$("ai-model").value.trim(),timeout_seconds:Number($("ai-timeout").value),max_calls_per_day:Number($("ai-budget").value),max_output_tokens:Number($("ai-tokens").value),max_batch_messages:Number($("ai-batch").value),max_input_chars:Number($("ai-input-limit").value),clear_key:$("ai-clear-key").checked};
    if ($("ai-key").value.trim()) data.api_key = $("ai-key").value.trim();
    try { await api("/api/ai/settings","PUT",data); await loadAI(); toast("模型配置已保存"); document.dispatchEvent(new CustomEvent("delivery:ai-saved")); } finally { $("ai-key").value = ""; }
  }); });
  $("ai-test").addEventListener("click",() => busy($("ai-test"),async () => {
    $("ai-test-result").textContent = "正在校验账号模型及构造样例 JSON…";
    try {
      const r = await api("/api/ai/test","POST",{});
      $("ai-test-result").textContent = `连接成功 · ${r.returned_model} · ${r.latency_ms} ms · ${r.item_count} 个样例事项 · JSON / 证据 ID 已校验`;
    } catch(e) { $("ai-test-result").textContent = `测试未完成：${e.message}`; throw e; }
  }));
  document.querySelectorAll("[data-tab]").forEach(button => button.addEventListener("click",() => {
    if (button.dataset.tab === "sources") loadSources().catch(e => toast(e.message,true));
    if (button.dataset.tab === "ai") loadAI().catch(e => toast(e.message,true));
  }));
  $("refresh-button").addEventListener("click",() => { loadSources().catch(e => toast(e.message,true)); });
  document.addEventListener("delivery:scope", () => { invalidatePreview(); loadSources().catch(e => toast(e.message,true)); });
  document.addEventListener("delivery:setup-saved", () => loadSources().catch(e => toast(e.message,true)));
  document.addEventListener("delivery:step", e => { if(e.detail.tab === "collect") loadSources().catch(e => toast(e.message,true)); });
  Promise.all([loadSources(),loadAI()]).catch(e => toast(e.message,true));
})();
