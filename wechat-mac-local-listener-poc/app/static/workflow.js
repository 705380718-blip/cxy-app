(function () {
  "use strict";
  const $ = id => document.getElementById(id);
  const steps = {
    setup: [1,"配置微信与群聊","设置群名称和你的昵称，消息会按用途归到同一个整理空间。"],
    rules: [2,"设置采集规则","设置关键词和 @我的规则。采集的群消息也可以交给 AI 整理。"],
    collect: [3,"采集群消息","消息保存在本机。新消息可自动分析，结果会持续更新。"],
    workbench: [4,"AI 分析","自动提取问题、任务、决策和风险，直接进入结果页。历史消息也可手动分析。"],
    results: [5,"信息与报告","查看自动整理的信息，必要时修改或撤回，按日期生成报告并导出。"]
  };
  let automationDirty = false, automationProject = "";
  let current = "setup", status = null, dashboard = null, initialized = false, requestVersion = 0, saving = false;
  const emit = (name,detail) => document.dispatchEvent(new CustomEvent(`delivery:${name}`,{detail}));
  async function api(url,method="GET",data) {
    const response = await fetch(url,{method,headers:{"Content-Type":"application/json"},...(data?{body:JSON.stringify(data)}:{})});
    const result = await response.json();
    if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : "请检查群名、昵称和空间名称是否填写完整");
    return result;
  }
  function navigate(tab) { document.querySelector(`.tab[data-tab="${tab}"]`)?.click(); }
  function heading(tab) {
    current = tab;
    const [number,title,description] = steps[tab];
    $("flow-title").textContent=title; $("flow-description").textContent=description;
    $("flow-progress").textContent = number ? `第 ${number} 步 / 共 5 步` : "辅助功能";
    document.querySelectorAll(".flow-step").forEach(b=>{if(b.dataset.tab===tab)b.setAttribute("aria-current","step");else b.removeAttribute("aria-current");});
    $("flow-analysis-next").hidden=tab!=="workbench";
    emit("step",{tab}); render();
  }
  function scope(project) {
    const id = project ? String(project.id) : "";
    if (document.body.dataset.projectId!==id) { document.body.dataset.projectId=id; emit("scope",{project_id:id}); }
  }
  function fillSetup() {
    const old = status.project ? String(status.project.id) : "";
    $("flow-project").replaceChildren(new Option("新建整理空间",""),...status.projects.map(p=>new Option(p.name,String(p.id))));
    $("flow-project").value=old; $("flow-name-label").hidden=Boolean(old); $("flow-project-name").required=!old;
    $("flow-project-name").value=status.project?.name||"";
    $("flow-groups").value=status.groups.join("\n"); $("flow-self-names").value=status.self_names.join("\n");
    $("flow-source-kind").value=status.source_kind;
  }
  async function refresh(fill=false,projectId=document.body.dataset.projectId) {
    const version=++requestVersion;
    const data=await api(`/api/workflow/status${projectId?`?project_id=${projectId}`:""}`);
    if(version!==requestVersion)return;
    status=data;
    scope(status.project);
    if(!initialized||fill)fillSetup(); initialized=true;
    if (automationProject!==String(status.project?.id||"")) {automationDirty=false;automationProject=String(status.project?.id||"");}
    if(!automationDirty) {$("flow-auto-results").checked=status.automatic_results;$("flow-auto-consent").checked=status.automatic_results;}
    render();
  }
  function render() {
    if(!status)return;
    $("flow-context").textContent=status.project ? status.project.name : "先设置要整理的群消息";
    const sourceReady=status.source_ready;
    const count=status.message_count;
    $("flow-readiness").textContent= !sourceReady ? "待配置群聊" : count ? `已收到 ${count} 条消息` : "等待采集消息";
    $("flow-received-count").textContent=`${count} 条`;
    const automatic=status.automatic_results;
    const active=(status.automation_jobs.queued||0)+(status.automation_jobs.running||0);
    const failed=status.automation_jobs.failed||0;
    $("flow-auto-rule-state").textContent=automatic?(!status.key_configured?"已开启，等待在右上角设置中配置模型":!status.ai_enabled?"已开启，等待启用 AI":"已开启，后续新消息将持续更新结果"):"尚未开启，勾选后保存规则即可启用";
    $("flow-collect-next").dataset.goto=automatic?"results":"workbench";
    $("flow-collect-next").disabled=!count;
    $("flow-collect-next").textContent=automatic?"查看自动整理结果 →":count?"消息已就绪，去 AI 分析 →":"收到消息后，继续 AI 分析 →";
    $("flow-received-list").replaceChildren();
    if(!count){const p=document.createElement("p");p.className="muted";p.textContent="还没有收到消息。开始采集或导入群记录后，消息会显示在这里。";$("flow-received-list").append(p);}
    (status.recent_messages||[]).forEach(m=>{const row=document.createElement("article"),meta=document.createElement("small"),text=document.createElement("p");meta.textContent=`${m.chat_name} · ${m.sender} · ${new Intl.DateTimeFormat("zh-CN",{timeZone:"Asia/Shanghai",month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit",hour12:false}).format(new Date(m.source_time))}`;text.textContent=m.content;row.append(meta,text);$("flow-received-list").append(row);});
    $("flow-message-count").textContent=`当前空间 ${count} 条`;
    $("flow-model-state").textContent=!status.key_configured?"未配置":status.ai_enabled?"已启用":"已暂停";
    $("flow-ai-guidance").textContent=!count ? "还没有收到消息，请先到“开始采集”获取消息。" : !status.key_configured ? `已有 ${count} 条消息。点击右上角“设置”配置模型，再预览并分析。` : !status.ai_enabled ? "模型已配置，请在右上角“设置”启用 AI 分析后继续。" : `已有 ${count} 条消息。选择来源，预览后确认开始分析。`;
    if(automatic) $("flow-ai-guidance").textContent=!status.key_configured?"自动整理已开启，请在右上角设置中配置模型。":!status.ai_enabled?"自动整理已暂停，请在右上角设置中启用 AI。":`自动整理已开启 · ${active} 批进行中${failed?` · ${failed} 批失败，可在分析队列查看`:""}${status.intervention_count?` · ${status.intervention_count} 条涉及人工修改，保留为建议`:""}。新消息分析后直接进入“信息与报告”。`;
    $("flow-results-status").textContent=automatic?(!status.key_configured?"自动整理已开启，等待配置模型。":!status.ai_enabled?"自动整理已暂停，模型启用后继续处理新消息。":`新消息正在自动整理 · ${active} 批进行中${failed?` · ${failed} 批失败，请到 AI 分析查看队列`:""}${status.intervention_count?` · ${status.intervention_count} 条进展需核对人工修改`:""}。结果每 5 秒更新。`):"尚未开启自动整理，可到采集规则中一次启用。";
    const kind=status.source_kind;
    $("flow-live-card").hidden=kind==="import";
    $("flow-import-card").hidden=kind!=="import";
    $("flow-collect-groups").textContent=sourceReady?`采集范围：${status.groups.join("、")}`:"请先在第一步保存群名称。";
    const running=Boolean(dashboard?.process?.running),canDecode=Boolean(dashboard?.probe?.can_decode);
    $("flow-collect-status").textContent=!sourceReady?"还没有配置采集群。":running?(canDecode?"正在采集，请在下方查看新消息。":"当前仅监测文件变化，消息解析尚不可用。可以改用手动导入。"):canDecode?"微信解析已就绪，点击开始采集。":"当前微信尚不能解析消息，可以先手动导入群记录。环境状态在下方查看。";
    $("listener-toggle").disabled=!running&&(!sourceReady||!canDecode);
    if(dashboard?.probe){const p=dashboard.probe;$("flow-account-value").textContent=p.wechat.running?`微信已运行${p.data.selected_account_fingerprint?` · 账号 ${p.data.selected_account_fingerprint}`:" · 请确认已登录"}`:"微信未运行，可先配置群名称或手动导入。";}
    document.querySelectorAll(".flow-step").forEach(b=>{const n=Number(b.dataset.step);b.classList.toggle("is-ready",n===1?sourceReady:n===2?status.rules_saved:n===3?count>0:false);});
  }
  const lines=id=>$(id).value.split(/\r?\n/).map(v=>v.trim()).filter(Boolean);
  async function saveSetup(next="rules",overrideKind) {
    if(saving||!$("flow-setup-form").reportValidity())return;
    saving=true;$("flow-save-setup").disabled=true;$("flow-setup-status").textContent="正在保存…";
    try {
      const selected=status.projects.find(p=>String(p.id)===$("flow-project").value);
      status=await api("/api/workflow/setup","PUT",{project_name:selected?.name||$("flow-project-name").value.trim(),groups:lines("flow-groups"),self_names:lines("flow-self-names"),source_kind:overrideKind||$("flow-source-kind").value});
      ++requestVersion;scope(status.project);fillSetup();emit("setup-saved",{});$("flow-setup-status").textContent="群配置已保存";navigate(next);
    }catch(e){$("flow-setup-status").textContent=e.message;$("flow-setup-status").setAttribute("role","alert");}
    finally{saving=false;$("flow-save-setup").disabled=false;render();}
  }
  function init() {
    ["flow-auto-results","flow-auto-consent"].forEach(id=>$(id).addEventListener("change",()=>{automationDirty=true;}));
    document.querySelectorAll(".tab[data-tab]").forEach(b=>b.addEventListener("click",()=>heading(b.dataset.tab)));
    document.addEventListener("click",e=>{const b=e.target.closest("[data-goto]");if(b)navigate(b.dataset.goto);});
    $("flow-setup-form").onsubmit=e=>{e.preventDefault();saveSetup();};
    $("flow-project").onchange=async()=>{
      const id=$("flow-project").value;
      if(id){try{await refresh(true,id);}catch(e){$("flow-setup-status").textContent=e.message;}}
      else{$("flow-name-label").hidden=false;$("flow-project-name").required=true;$("flow-project-name").value="";$("flow-groups").value="";$("flow-source-kind").value="decoder";$("flow-setup-status").textContent="填写新空间的名称和群名单，保存后生效。";}
    };
    $("flow-use-import").onclick=()=>{if(!status?.source_ready){navigate("setup");return;}saveSetup("collect","import");};
    document.addEventListener("delivery:dashboard",e=>{dashboard=e.detail;render();});
    document.addEventListener("delivery:rules-saved",()=>{automationDirty=false;refresh().catch(()=>{});navigate("collect");});
    ["imported","ai-saved"].forEach(name=>document.addEventListener(`delivery:${name}`,()=>refresh().catch(()=>{})));
    $("refresh-button").addEventListener("click",()=>refresh().catch(e=>{$("flow-setup-status").textContent=e.message;}));
    Promise.all([refresh().then(()=>{if(status?.automatic_results)navigate("results");}),api("/api/dashboard").then(d=>{dashboard=d;render();})]).catch(e=>{$("flow-setup-status").textContent=e.message;});
    heading("setup");
    setInterval(()=>{if(document.visibilityState==="visible")refresh().catch(()=>{});},5000);
  }
  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",init);else init();
})();
