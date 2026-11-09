(function () {
  "use strict";
  const $ = id => document.getElementById(id);
  const types = {issue:"问题",task:"任务",decision:"决策",risk:"风险"};
  const reviews = {pending:"待复核",confirmed:"已确认",ignored:"已忽略"};
  const statuses = {open:"待处理",in_progress:"处理中",waiting_confirmation:"待确认结果",resolved:"已解决"};
  const jobs = {queued:"排队中",running:"分析中",succeeded:"分析完成",failed:"分析失败",cancelled:"已取消"};
  const errors = {authentication:"Key 无效",key_missing:"未配置 Key",permission:"账号权限不足",balance:"账号余额不足",rate_limit:"服务限流",server_error:"模型服务异常",network:"网络连接失败",timeout:"请求超时",task_timeout:"任务超时",result_invalid:"输出或依据校验失败",empty_content:"模型返回空正文",truncated:"模型输出被截断",daily_budget:"已达每日请求上限",interrupted:"服务中断",evidence_expired:"依据已过期",group_not_allowed:"来源已移出白名单",input_too_large:"正文超过字符上限",attempt_limit:"已达三次请求上限",context_invalid:"旧任务缺少上下文",prompt_changed:"提示词已更新，请重新预览",internal_error:"任务处理异常"};
  let proposalPage = 1, proposalPages = 1, previewPage = 1, previewVersion = 0, jobRows = [], jobPage = 1;
  const selectedProposals = new Map();
  let visibleProposals = [], selectionScope = "", selectionVersion = 0, batchRunning = false;
  let allowedGroups = [], refreshAgain = false, projects = [], items = [], page = 1, total = 0, preview = null, refreshing = false;
  const el = (tag,text,cls) => { const n=document.createElement(tag); if(text!==undefined)n.textContent=text; if(cls)n.className=cls; return n; };
  function notify(message,error=false) { const n=el("div",message,error?"toast error":"toast");n.setAttribute("role",error?"alert":"status");$("toast-region").append(n);setTimeout(()=>n.remove(),6500); }
  async function api(url,method="GET",data) { const r=await fetch(url,{method,headers:{"Content-Type":"application/json"},...(data?{body:JSON.stringify(data)}:{})});const result=await r.json();if(!r.ok)throw new Error(typeof result.detail==="string"?result.detail:"字段格式不正确，请检查输入");return result; }
  async function busy(button,action) { if(button.disabled)return;button.disabled=true;button.setAttribute("aria-busy","true");try{await action();}catch(e){notify(e.message,true);}finally{button.disabled=false;button.removeAttribute("aria-busy");} }
  const action = (text,fn,primary=false) => { const b=el("button",text,primary?"button primary":"button");b.type="button";b.addEventListener("click",()=>busy(b,fn));return b; };
  const time = value => value?new Intl.DateTimeFormat("zh-CN",{timeZone:"Asia/Shanghai",month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit",hour12:false}).format(new Date(value)):"未明确";
  function options(select,rows,empty) { const old=select.value;select.replaceChildren();if(!rows.length)select.add(new Option(empty,""));else rows.forEach(([v,t])=>select.add(new Option(t,String(v))));if([...select.options].some(o=>o.value===old))select.value=old; }
  function invalidate() { ++previewVersion; previewPage=1; if($("work-dialog").open && $("work-dialog").dataset.kind==="preview")$("work-dialog").close(); preview=null;$("analysis-preview").hidden=true;$("analysis-consent").checked=false;$("analysis-next").hidden=true; }
  function renderSourceOptions() { const project=projects.find(p=>String(p.id)===$("work-project").value);options($("work-source"),(project?.sources||[]).filter(s=>allowedGroups.includes(s.source_key)).map(s=>[s.id,`${s.display_name} · ${s.message_count} 条`]),"请先在微信与群聊中保存配置");sourceStatus(); }
  function sourceStatus() {
    const source=projects.flatMap(p=>p.sources).find(s=>String(s.id)===$("work-source").value);
    const automatic=Boolean(source?.auto_analysis_enabled && source?.auto_publish_enabled);
    $("automation-state").textContent=source?(source.auto_analysis_enabled?`后续分析已启用 · 已入队至消息 #${source.last_enqueued_message_id}`:"后续分析未启用")+(source.analysis_error?` · ${errors[source.analysis_error]||"来源暂不可分析"}`:""):"";
    $("automatic-analysis-state").textContent=automatic?"新消息将自动分析并更新结果，无需选择范围或逐条采纳。":"在采集规则中开启自动整理后，新消息可直接进入结果页。";
    const controls=$("analysis-manual-controls");
    if(controls.dataset.automatic!==String(automatic)){controls.open=!automatic;controls.dataset.automatic=String(automatic);}
  }
  async function refresh() {
    if(refreshing){refreshAgain=true;return;}refreshing=true;
    try {
      const [projectData,config,rules]=await Promise.all([api("/api/projects"),api("/api/ai/settings"),api("/api/settings")]);projects=projectData.items.filter(p=>p.enabled);allowedGroups=rules.groups;
      const oldProject=$("work-project").value, oldSource=$("work-source").value;
      options($("work-project"),projects.map(p=>[p.id,p.name]),"请先配置整理空间");
      if(document.body.dataset.projectId)$("work-project").value=document.body.dataset.projectId;
      renderSourceOptions();
      if(oldProject!==$("work-project").value||oldSource!==$("work-source").value)invalidate();
      $("work-ai-state").textContent=!config.key_configured?"未配置密钥":config.enabled?"AI 已启用":"AI 未启用";
      const project=$("work-project").value;
      syncSelectionScope();
      if(!project){renderItems({items:[],total:0});renderProposals({items:[],total:0,page:1,pages:1});renderJobs([]);return;}
      const query=new URLSearchParams({project_id:project,page:String(page),page_size:"20"});
      if($("work-visibility").value==="withdrawn")query.set("withdrawn","true");
      if($("work-review").value)query.set("review_status",$("work-review").value);
      if($("work-status").value)query.set("work_status",$("work-status").value);
      const proposalQuery=new URLSearchParams({project_id:project,page:String(proposalPage),page_size:"5"});
      const selectedType=$("proposal-type").value;
      if(selectedType)proposalQuery.set("type",selectedType);
      const [itemData,proposalData,jobData]=await Promise.all([api(`/api/work-items?${query}`),api(`/api/item-proposals?${proposalQuery}`),api(`/api/ai/jobs?project_id=${project}`)]);
      const staleItems=query.get("page")!==String(page) || (query.get("withdrawn")==="true")!==($("work-visibility").value==="withdrawn") || (query.get("review_status")||"")!==$("work-review").value || (query.get("work_status")||"")!==$("work-status").value;
      if((document.body.dataset.projectId && project!==document.body.dataset.projectId) || staleItems || selectedType!==$("proposal-type").value || proposalQuery.get("page")!==String(proposalPage)){refreshAgain=true;return;}
      renderItems(itemData);renderProposals(proposalData);renderJobs(jobData.items);
    } finally { refreshing=false; if(refreshAgain){refreshAgain=false;refresh().catch(e=>notify(e.message,true));} }
  }
  function evidenceRows(rows) {
    const list=el("div",undefined,"evidence-list");
    if(!rows.length)list.append(el("p","暂无有效原文依据。","muted"));
    rows.forEach(r=>{const card=el("article",undefined,"evidence-entry");card.append(el("small",`#${r.id} · ${r.sender||r.sender_ref||"未知成员"} · ${time(r.source_time||r.timestamp)}${r.field?` · ${{title:"事项",owner:"责任人",deadline:"期限",progress:"进展"}[r.field]||"依据"}`:""}`));card.append(el("p",r.content_text??r.text??""));if(r.quote_content||r.quote_text)card.append(el("p",`引用 ${r.quote_sender||r.quote_sender_ref||""}：${r.quote_content||r.quote_text}`));list.append(card);});return list;
  }
  function openDialog(title,kind="detail") { $("work-dialog").dataset.kind=kind; $("work-dialog-title").textContent=title;$("work-dialog-body").replaceChildren();$("work-dialog-body").scrollTop=0;if(!$("work-dialog").open)$("work-dialog").showModal(); }
  async function showEvidence(url,title) { const data=await api(url);openDialog(title);$("work-dialog-body").append(evidenceRows(data.items)); }
  function field(label,input) { const n=el("label",label);n.append(input);return n; }
  function input(value,max=200) { const n=el("input");n.className="text-input";n.value=value||"";n.maxLength=max;return n; }
  function select(mapping,current) { const n=el("select");Object.entries(mapping).forEach(([v,t])=>n.add(new Option(t,v)));n.value=current;return n; }
  function detailsText(fields) { return [`责任人：${fields.owner||"待确认"}`,`期限：${fields.due_text||"未明确"}${fields.due_at?`（${time(fields.due_at)}）`:""}`,`进展：${fields.latest_progress||"暂无"}`].join("\n"); }
  function syncSelectionScope() {
    const scope=`${$("work-project").value}:${$("proposal-type").value}`;
    if(scope!==selectionScope){selectionScope=scope;selectedProposals.clear();visibleProposals=[];selectionVersion++;updateBatchControls();}
  }
  function updateBatchControls() {
    const count=selectedProposals.size, selectedHere=visibleProposals.filter(p=>selectedProposals.has(p.id)).length;
    $("proposal-selected-count").textContent=`已选 ${count} 条${count>selectedHere?`（其他页 ${count-selectedHere} 条）`:""}`;
    $("proposal-select-page").checked=!!visibleProposals.length && selectedHere===visibleProposals.length;
    $("proposal-select-page").indeterminate=selectedHere>0 && selectedHere<visibleProposals.length;
    $("proposal-select-page").disabled=batchRunning || !visibleProposals.length;
    ["proposal-clear","proposal-batch-dismiss","proposal-batch-apply"].forEach(id=>$(id).disabled=batchRunning || !count);
    ["proposal-type","proposal-prev","proposal-next"].forEach(id=>$(id).disabled=batchRunning || (id==="proposal-prev"?proposalPage<=1:id==="proposal-next"?proposalPage>=proposalPages:false));
    $("proposal-list").querySelectorAll("article").forEach(row=>{
      const checked=selectedProposals.has(Number(row.dataset.proposalId));row.classList.toggle("is-selected",checked);
      row.querySelector("input").checked=checked;row.querySelector("input").disabled=batchRunning;
      row.querySelector("button").disabled=batchRunning;
    });
  }
  function chooseProposal(p,checked) {
    if(checked && !selectedProposals.has(p.id) && selectedProposals.size>=100){notify("每批最多选择 100 条，请先处理已选建议",true);return;}
    if(checked)selectedProposals.set(p.id,p);else selectedProposals.delete(p.id);
  }
  function renderProposals(data) {
    syncSelectionScope();
    proposalPage=data.page; proposalPages=data.pages;visibleProposals=data.items;
    $("proposal-count").textContent=data.total;
    $("proposal-list").replaceChildren();
    if(!data.items.length)$("proposal-list").append(el("p",$("proposal-type").value?"该类型暂无待复核建议。":"暂无待复核建议。自动整理结果直接进入“信息与报告”；涉及人工修改的进展会保留为建议。","proposal-empty muted"));
    data.items.forEach(p=>{
      if(selectedProposals.has(p.id))selectedProposals.set(p.id,p);
      const row=el("article",undefined,"proposal-row"),checkbox=el("input");row.dataset.proposalId=p.id;checkbox.type="checkbox";checkbox.setAttribute("aria-label",`选择建议：${p.fields.title}`);
      checkbox.addEventListener("change",()=>{chooseProposal(p,checkbox.checked);updateBatchControls();});
      const text=el("div",undefined,"proposal-copy"),meta=el("div",undefined,"proposal-meta");
      meta.append(el("span",types[p.fields.type],"proposal-kind"),el("span",p.target_item_id?"进展更新":"新事项"),el("span",statuses[p.fields.work_status]));
      text.append(meta,el("h3",p.fields.title),el("p",`${p.fields.owner||"责任人待确认"} · ${p.fields.due_text||"期限未明确"} · ${p.evidence_message_ids.length} 条依据`,"muted"));
      const review=action("复核 →",()=>reviewProposal(p));review.setAttribute("aria-label",`复核建议：${p.fields.title}`);
      const selector=el("label",undefined,"proposal-selector");selector.append(checkbox);
      row.append(selector,text,review);$("proposal-list").append(row);
    });
    $("proposal-page-info").textContent=`共 ${data.total} 条 · ${proposalPage} / ${proposalPages} 页`;
    updateBatchControls();
  }
  function confirmBatch(mode) {
    if(batchRunning || !selectedProposals.size)return;
    const chosen=[...selectedProposals.values()],scope=selectionScope,version=selectionVersion,projectId=Number($("work-project").value),verb=mode==="apply"?"采纳":"忽略";
    openDialog(`批量${verb} ${chosen.length} 条建议`,"batch");const body=$("work-dialog-body");
    body.append(el("p",mode==="apply"?"核对以下建议后确认采纳。新建议将建立已确认事项；进展建议更新原事项。需关联到已有事项的新建议，请先单独复核。":"确认后，所选建议将从待复核列表移除，已确认事项不受影响。","muted"));
    if(mode==="apply" && chosen.some(p=>p.fields.needs_confirmation?.length || !p.fields.owner))body.append(el("p","部分建议的责任人、期限或结果尚待确认，请展开原文核对。","work-error"));
    chosen.forEach(p=>{
      const card=el("article",undefined,"batch-review-entry");card.append(el("span",`${types[p.fields.type]} · ${p.target_item_id?`更新 #${p.target_item_id}`:"新事项"} · ${statuses[p.fields.work_status]}`,"badge"),el("h3",p.fields.title),el("p",detailsText(p.fields)));
      if(p.fields.task_basis)card.append(el("p",`行动依据 · #${p.fields.task_basis.message_id}：${p.fields.task_basis.quote}`,"coverage-note"));
      const original=el("details"),summary=el("summary",`查看 ${p.evidence_message_ids.length} 条原文依据`);original.append(summary);let loaded=false;
      original.addEventListener("toggle",async()=>{if(!original.open || loaded)return;loaded=true;try{const evidence=await api(`/api/item-proposals/${p.id}/evidence`);original.append(evidenceRows(evidence.items));}catch(e){loaded=false;notify(e.message,true);}});
      card.append(original);body.append(card);
    });
    const controls=el("div",undefined,"drawer-actions"),confirm=action(`确认${verb} ${chosen.length} 条`,async()=>{
      if(scope!==selectionScope || version!==selectionVersion)throw new Error("选择范围已变化，请重新选择建议");
      batchRunning=true;updateBatchControls();
      try {
        const result=await api("/api/item-proposals/batch","POST",{project_id:projectId,action:mode,items:chosen.map(p=>({id:p.id,expected_version:p.target_item_id?p.target_version:null}))});
        if(scope!==selectionScope || version!==selectionVersion){notify(`批量${verb}完成：成功 ${result.succeeded} 条，失败 ${result.failed} 条`);return;}
        result.results.filter(r=>r.ok).forEach(r=>selectedProposals.delete(r.id));
        openDialog(`批量${verb}结果`,"batch-result");const output=$("work-dialog-body");output.append(el("p",`成功 ${result.succeeded} 条，失败 ${result.failed} 条。`,"coverage-note"));
        result.results.filter(r=>!r.ok).forEach(r=>{const p=chosen.find(p=>p.id===r.id);output.append(el("p",`${p.fields.title}：${r.detail}`,"work-error"));});
        if(result.failed)output.append(el("p","失败建议保留选择，可单独复核。版本冲突需要重新分析或忽略该建议。","muted"));
        output.append(action("完成",()=>$("work-dialog").close()));
        await refresh();notify(`已${verb} ${result.succeeded} 条建议${result.failed?`，${result.failed} 条未处理`:""}`);
      } finally {batchRunning=false;updateBatchControls();}
    },true);
    controls.append(action("取消",()=>$("work-dialog").close()),confirm);body.insertBefore(controls,body.querySelector(".batch-review-entry"));
  }
  async function reviewProposal(p) {
    const evidence=await api(`/api/item-proposals/${p.id}/evidence`);
    if(String(p.project_id)!==$("work-project").value)return;
    openDialog("复核事项建议");const body=$("work-dialog-body");body.append(el("span",`${types[p.fields.type]} · ${statuses[p.fields.work_status]}`,"badge"),el("h3",p.fields.title),el("p",detailsText(p.fields)),el("p",`建议处理状态：${statuses[p.fields.work_status]}。采纳表示识别已确认；关闭事项仍需人工操作。更新建议中未明确的字段会保留人工值，新的模糊期限会清除旧的精确日期。`,"muted"),evidenceRows(evidence.items));
    if(p.fields.needs_confirmation?.length)body.append(el("p","存在待确认信息，请结合原文核对责任人、期限和结果。","work-error"));
    if(p.fields.task_basis)body.append(el("p",`行动依据 · #${p.fields.task_basis.message_id}：${p.fields.task_basis.quote}`,"coverage-note"));
    let link=null, targets=[];
    if(!p.target_item_id) {
      const data=await api(`/api/work-items?project_id=${p.project_id}&page_size=100`);targets=data.items.filter(i=>i.project_source_id===p.project_source_id&&!i.evidence_expired&&!i.withdrawn_at&&i.work_status!=="resolved");
      link=el("select");link.add(new Option("作为新事项", ""));targets.forEach(i=>link.add(new Option(`关联 #${i.id} ${i.title} · v${i.version}`,String(i.id))));body.append(field("归属事项（同来源最近 100 条）",link));
    } else body.append(el("p",`更新事项 #${p.target_item_id}，基于版本 ${p.target_version}。版本冲突时需重新分析。`,"muted"));
    if(!$("work-dialog").open || String(p.project_id)!==$("work-project").value)return;
    const controls=el("div",undefined,"drawer-actions");
    controls.append(action("确认采纳建议",async()=>{const target=targets.find(i=>String(i.id)===link?.value);await api(`/api/item-proposals/${p.id}/apply`,"POST",{expected_version:p.target_item_id?p.target_version:target?.version??null,target_item_id:target?.id??null});selectedProposals.delete(p.id);$("work-dialog").close();await refresh();notify("建议已采纳，可在事项详情中修改字段与处理状态");},true),action("忽略建议",async()=>{await api(`/api/item-proposals/${p.id}/dismiss`,"POST",{});selectedProposals.delete(p.id);$("work-dialog").close();await refresh();}));body.append(controls);
  }
  function renderItems(data) {
    items=data.items;total=data.total;page=data.page||1;$("item-count").textContent=`${total} 项`;$("item-list").replaceChildren();
    if(!items.length)$("item-list").append(el("p","此筛选范围暂无事项。开启自动整理后，新消息分析结果会显示在这里。","muted"));
    items.forEach(item=>{
      const card=el("article",undefined,"work-entry"),heading=el("div",undefined,"item-card-heading"),badges=el("div",undefined,"item-card-badges");
      badges.append(el("span",item.withdrawn_at?"已撤回":item.auto_generated&&item.review_status==="pending"?"AI 自动整理":reviews[item.review_status],"badge"),el("span",statuses[item.work_status],"badge"));heading.append(badges);
      if(!item.withdrawn_at && (item.review_status==="confirmed" || item.auto_generated)) {const remove=action("删除",()=>confirmWithdrawal(item));remove.classList.add("item-withdraw");remove.setAttribute("aria-label",`删除事项：${item.title}`);heading.append(remove);}
      card.append(heading,el("h3",item.title),el("p",`${types[item.type]} · ${item.display_name}\n${detailsText(item)}`),el("small",`#${item.id} · 版本 ${item.version}${item.evidence_expired?" · 依据已过期":""}`,"muted"));
      const controls=el("div",undefined,"delivery-inline");controls.append(action("查看依据",()=>showEvidence(`/api/work-items/${item.id}/evidence`,"事项的原文依据")));
      if(!item.evidence_expired)controls.append(item.withdrawn_at?action("恢复事项",async()=>{await api(`/api/work-items/${item.id}/restore`,"POST",{expected_version:item.version});await refresh();notify("事项已恢复到当前事项列表");},true):action("修改与跟进",()=>editItem(item),true));
      card.append(controls);$("item-list").append(card);
    });
    $("work-page").textContent=`${page} / ${Math.max(1,Math.ceil(total/20))}`;$("work-prev").disabled=page<=1;$("work-next").disabled=page*20>=total;
  }
  function confirmWithdrawal(item) {
    openDialog("撤回事项");
    const body=$("work-dialog-body");body.append(el("h3",item.title),el("p","撤回后，该事项不再出现在当前事项列表和新生成的报告中。原文依据会保留，你可通过“显示事项 → 已撤回”恢复。已经生成的报告保留原快照，需要重新生成报告以更新内容。","muted"));
    body.append(action("确认撤回",async()=>{await api(`/api/work-items/${item.id}`,"DELETE",{expected_version:item.version});$("work-dialog").close();await refresh();notify("事项已撤回，可在已撤回列表恢复");},true));
  }
  async function editItem(item) {
    const evidence=await api(`/api/work-items/${item.id}/evidence`);openDialog(`事项 #${item.id} · 修改与跟进`);const body=$("work-dialog-body"),form=el("form",undefined,"delivery-form");
    const title=input(item.title),owner=input(item.owner),due=input(item.due_text),dueAt=input(item.due_at?new Date(new Date(item.due_at).getTime()+8*3600000).toISOString().slice(0,16):"");title.required=true;dueAt.type="datetime-local";
    const progress=el("textarea");progress.className="text-input";progress.rows=3;progress.maxLength=2000;progress.value=item.latest_progress||"";
    const review=select(reviews,item.review_status),status=select(statuses,item.work_status);
    form.append(field("标题",title),field("责任人",owner),field("原文期限",due),field("确认后的截止时间（北京时间，可留空）",dueAt),field("最新进展",progress),field("复核状态",review),field("处理状态",status),el("p","“已确认”表示识别正确。确认业务完成后，将处理状态设为“已解决”。","muted"));
    const save=el("button","保存修改","button primary");save.type="submit";form.append(save);form.addEventListener("submit",event=>{event.preventDefault();busy(save,async()=>{await api(`/api/work-items/${item.id}`,"PATCH",{expected_version:item.version,title:title.value,owner:owner.value||null,due_text:due.value||null,due_at:dueAt.value?dueAt.value+"+08:00":null,latest_progress:progress.value||null,review_status:review.value,work_status:status.value});$("work-dialog").close();await refresh();notify("事项已更新");});});body.append(form,el("h3","原文依据"),evidenceRows(evidence.items));
    const data=await api(`/api/work-items?project_id=${item.project_id}&page_size=100`);const targets=data.items.filter(i=>i.id!==item.id&&i.project_source_id===item.project_source_id&&!i.evidence_expired);
    if(targets.length){const merge=el("details"),choice=el("select");targets.forEach(i=>choice.add(new Option(`#${i.id} ${i.title} · v${i.version}`,String(i.id))));merge.append(el("summary","将本事项合并至其他事项"),el("p","保留目标事项字段，并合并原文依据；本事项保留来源链，不再单独计入事项列表。","muted"),choice,action("确认合并",async()=>{const target=targets.find(i=>String(i.id)===choice.value);await api(`/api/work-items/${item.id}/merge`,"POST",{target_item_id:target.id,expected_version:item.version,target_version:target.version});$("work-dialog").close();await refresh();notify("事项已合并");}));body.append(merge);}
  }
  function renderJobs(rows) {
    jobRows=rows;$("job-count").textContent=rows.length?`最近 ${rows.length} 批 · ${rows.filter(j=>["queued","running"].includes(j.status)).length} 批进行中`:"暂无分析任务";
    if($("work-dialog").open && $("work-dialog").dataset.kind==="queue")showJobs();
  }
  function showJobs() {
    jobPage=Math.min(jobPage,Math.max(1,Math.ceil(jobRows.length/8)));
    openDialog("分析队列","queue");const body=$("work-dialog-body"),list=el("div",undefined,"work-list queue-list");
    if(!jobRows.length)list.append(el("p","暂无分析任务。","muted"));
    jobRows.slice((jobPage-1)*8,jobPage*8).forEach(job=>{const card=el("article",undefined,"work-entry");card.append(el("strong",`#${job.id} ${jobs[job.status]}`),el("p",`${job.display_name} · ${job.model}\n${JSON.parse(job.input_message_ids).length} 条新消息 · 已尝试 ${job.attempts}/3 次`));if(job.filtered_task_count)card.append(el("p",`已排除 ${job.filtered_task_count} 条缺少明确行动依据的待办建议`,"muted"));if(job.error_code)card.append(el("p",errors[job.error_code]||"模型接口拒绝请求，请核对配置与账号","work-error"));const controls=el("div",undefined,"delivery-inline");controls.append(action("查看请求记录",async()=>{const d=await api(`/api/ai/jobs/${job.id}`);openDialog(`分析任务 #${job.id}`);$("work-dialog-body").append(el("p",`${jobs[d.status]} · 输入 ${d.input_message_ids}`));d.attempt_details.forEach(a=>$("work-dialog-body").append(el("p",`第 ${a.attempt} 次 · ${a.requested_model} → ${a.returned_model||"未返回"} · ${a.latency_ms??"—"} ms · ${a.tokens??"—"} token · ${a.error_code?errors[a.error_code]||"请求失败":a.finish_reason||"进行中"}`)));}));
      if(job.status==="queued"||job.status==="running")controls.append(action("取消",async()=>{await api(`/api/ai/jobs/${job.id}/cancel`,"POST",{});await refresh();}));
      if(job.status==="failed"&&job.attempts<3)controls.append(action("重试剩余次数",async()=>{await api(`/api/ai/jobs/${job.id}/retry`,"POST",{});await refresh();}));card.append(controls);list.append(card);});
    body.append(list);
    const pagination=el("div",undefined,"list-pagination"),previous=action("上一页",()=>{jobPage--;showJobs();}),next=action("下一页",()=>{jobPage++;showJobs();});
    previous.disabled=jobPage<=1;next.disabled=jobPage*8>=jobRows.length;
    pagination.append(previous,el("span",`${jobPage} / ${Math.max(1,Math.ceil(jobRows.length/8))} 页`),next);body.append(pagination);
  }
  function showPreview() {
    if(!preview)return;
    const messages=preview.context.messages,pages=Math.max(1,Math.ceil(messages.length/8));previewPage=Math.min(previewPage,pages);
    openDialog("核对待发送文本","preview");const body=$("work-dialog-body");
    body.append(el("p",$("analysis-coverage").textContent,"coverage-note"),el("p","以下正文、引用及事项上下文会发送至 DeepSeek。","muted"),evidenceRows(messages.slice((previewPage-1)*8,previewPage*8)));
    const pagination=el("div",undefined,"list-pagination"),previous=action("上一页",()=>{previewPage--;showPreview();}),next=action("下一页",()=>{previewPage++;showPreview();});
    previous.disabled=previewPage<=1;next.disabled=previewPage>=pages;pagination.append(previous,el("span",`共 ${messages.length} 条 · ${previewPage} / ${pages} 页`),next);body.append(pagination);
    const context=el("details"),raw=el("pre");raw.textContent=JSON.stringify({persons:preview.context.persons,open_items:preview.context.open_items},null,2);context.append(el("summary","既有事项与人物代号"),raw);body.append(context);
    body.append(action("核对完成，返回分析",()=>$("work-dialog").close(),true));
  }
  $("analysis-form").addEventListener("submit",event=>{event.preventDefault();busy(event.submitter,async()=>{invalidate();const generation=previewVersion;const p=await api("/api/ai/jobs/preview","POST",{project_source_id:Number($("work-source").value),after_message_id:Number($("analysis-after").value),through_message_id:$("analysis-through").value?Number($("analysis-through").value):null});if(generation!==previewVersion)return;preview=p;$("analysis-preview").hidden=false;$("analysis-coverage").textContent=`新消息 ${p.input_message_ids.length} 条 · 共 ${p.context.messages.length} 条上下文 · ${p.model}${p.has_more?" · 还有后续批次":""}${p.context.coverage.partial_context?" · 上下文有限，请结合原文复核":""}`;$("analysis-preview-open").textContent=`查看待发送文本 · ${p.context.messages.length} 条`;showPreview();});});
  $("analysis-send").addEventListener("click",()=>busy($("analysis-send"),async()=>{if(!preview)throw new Error("请先预览范围");if(!$("analysis-consent").checked)throw new Error("请先确认本批文本可以发送至 DeepSeek");const job=await api("/api/ai/jobs","POST",{preview_token:preview.preview_token,consent:true});notify(`任务 #${job.id} 已入队`);$("analysis-next").hidden=!preview.has_more;await refresh();}));
  $("analysis-next").addEventListener("click",()=>{if(!preview)return;const through=preview.through_message_id;invalidate();$("analysis-after").value=through;$("analysis-form").requestSubmit();});
  $("automation-enable").addEventListener("click",()=>busy($("automation-enable"),async()=>{await api(`/api/sources/${$("work-source").value}/automation`,"PUT",{enabled:true,consent:$("automation-consent").checked});await refresh();notify("已启用该来源的后续分析");}));
  $("automation-disable").addEventListener("click",()=>busy($("automation-disable"),async()=>{await api(`/api/sources/${$("work-source").value}/automation`,"PUT",{enabled:false});$("automation-consent").checked=false;await refresh();notify("已停止新增自动分析任务；已入队任务可在队列中取消");}));
  $("manual-item-form").addEventListener("submit",event=>{event.preventDefault();busy(event.submitter,async()=>{const text=$("manual-evidence").value.trim();if(!/^\d+(\s*[,，]\s*\d+)*$/.test(text))throw new Error("请填写以逗号分隔的消息 ID");await api("/api/work-items","POST",{project_source_id:Number($("work-source").value),type:$("manual-type").value,title:$("manual-title").value,evidence_message_ids:text.split(/[,，]/).map(Number)});$("manual-title").value="";$("manual-evidence").value="";await refresh();notify("已保存待复核事项");});});
  $("work-project").addEventListener("change",()=>{page=1;proposalPage=1;syncSelectionScope();renderSourceOptions();invalidate();refresh().catch(e=>notify(e.message,true));});
  $("work-source").addEventListener("change",()=>{invalidate();$("automation-consent").checked=false;sourceStatus();});
  ["analysis-after","analysis-through"].forEach(id=>$(id).addEventListener("input",invalidate));
  ["work-review","work-status","work-visibility"].forEach(id=>$(id).addEventListener("change",()=>{page=1;refresh().catch(e=>notify(e.message,true));}));
  $("work-prev").addEventListener("click",()=>{page--;refresh().catch(e=>notify(e.message,true));});$("work-next").addEventListener("click",()=>{page++;refresh().catch(e=>notify(e.message,true));});
  $("proposal-type").addEventListener("change",()=>{proposalPage=1;syncSelectionScope();refresh().catch(e=>notify(e.message,true));});
  $("proposal-prev").addEventListener("click",()=>{proposalPage--;refresh().catch(e=>notify(e.message,true));});
  $("proposal-next").addEventListener("click",()=>{proposalPage++;refresh().catch(e=>notify(e.message,true));});
  $("proposal-select-page").addEventListener("change",()=>{visibleProposals.forEach(p=>chooseProposal(p,$("proposal-select-page").checked));updateBatchControls();});
  $("proposal-clear").addEventListener("click",()=>{selectedProposals.clear();updateBatchControls();});
  $("proposal-batch-apply").addEventListener("click",()=>confirmBatch("apply"));
  $("proposal-batch-dismiss").addEventListener("click",()=>confirmBatch("dismiss"));
  $("analysis-preview-open").addEventListener("click",showPreview);
  $("job-open").addEventListener("click",()=>{jobPage=1;showJobs();});
  document.addEventListener("delivery:ai-saved",()=>{invalidate();refresh().catch(e=>notify(e.message,true));});
  $("work-dialog-close").addEventListener("click",()=>$("work-dialog").close());
  $("work-refresh").addEventListener("click",()=>busy($("work-refresh"),refresh));$("refresh-button").addEventListener("click",()=>refresh().catch(e=>notify(e.message,true)));
  document.querySelector('[data-tab="workbench"]').addEventListener("click",()=>refresh().catch(e=>notify(e.message,true)));
  document.addEventListener("delivery:step", e=>{if(e.detail.tab==="results")refresh().catch(e=>notify(e.message,true));});
  document.addEventListener("delivery:scope", ()=>{page=1;proposalPage=1;selectedProposals.clear();visibleProposals=[];selectionScope="";selectionVersion++;updateBatchControls();if($("work-dialog").open)$("work-dialog").close();invalidate();refresh().catch(e=>notify(e.message,true));});
  setInterval(()=>{if(document.visibilityState==="visible"&&[$("tab-workbench"),$("tab-results")].some(n=>n.classList.contains("active"))&&!$("work-dialog").open)refresh().catch(()=>{});},5000);
  refresh().catch(e=>notify(e.message,true));
})();
