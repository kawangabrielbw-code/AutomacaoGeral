const $ = (s, root=document) => root.querySelector(s);
const $$ = (s, root=document) => [...root.querySelectorAll(s)];
let csrf = "", sourcePage = 1, sourceFilters = {}, historyPage = 1, activePoll = null;
const section = document.body.dataset.section;
const labels = {dashboard:"Dashboard",sources:"Fontes de dados",collections:"Central de coletas",exports:"Google Sheets Central",history:"Histórico de execuções",settings:"Configurações"};
const escapeHtml = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const fmtDate = value => value ? new Intl.DateTimeFormat("pt-BR", {dateStyle:"short",timeStyle:"short",timeZone:"America/Sao_Paulo"}).format(new Date(value)) : "—";
const fmtNum = value => new Intl.NumberFormat("pt-BR").format(Number(value || 0));
const api = async (url, options={}) => {
  const headers = {...(options.headers || {})};
  if (options.body && !headers["Content-Type"]) headers["Content-Type"] = "application/json";
  if (["POST","PATCH","DELETE"].includes((options.method || "GET").toUpperCase())) headers["X-CSRF-Token"] = csrf;
  let response;
  try {
    const signal=options.signal || (AbortSignal.timeout ? AbortSignal.timeout(30000) : undefined);
    response = await fetch(url, {...options, headers, signal});
  } catch(error) {
    throw new Error(error.name==="TimeoutError"||error.name==="AbortError" ? "A solicitação excedeu o tempo limite." : "Não foi possível conectar ao servidor.");
  }
  if (response.status === 401) { location.href = "/login"; throw new Error("Sessão expirada."); }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || `Erro HTTP ${response.status}`);
  return data;
};
const statusPill = value => `<span class="pill ${escapeHtml(value)}">${escapeHtml(value || "desconhecido")}</span>`;
const empty = message => `<div class="empty">${escapeHtml(message)}</div>`;
const table = (headers, rows) => rows.length ? `<div class="table-wrap"><table><thead><tr>${headers.map(h=>`<th>${escapeHtml(h)}</th>`).join("")}</tr></thead><tbody>${rows.join("")}</tbody></table></div>` : empty("Nenhum registro encontrado.");
function errorBox(error) { return `<div class="alert error">${escapeHtml(error.message || error)}</div>`; }
function metric(label, value, detail, color="") { return `<article class="metric ${color}"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong><small>${escapeHtml(detail || "")}</small></article>`; }
function confirmAction(title, description) {
  return new Promise(resolve => {
    const dialog = $("#confirm-dialog"); $("#confirm-title").textContent=title; $("#confirm-description").textContent=description;
    const yes=$("#confirm-yes"); const done=e=>{yes.removeEventListener("click",done); resolve(e.target.value==="confirm");};
    yes.addEventListener("click",done); dialog.showModal();
    dialog.addEventListener("close",()=>resolve(dialog.returnValue==="confirm"),{once:true});
  });
}
async function startOperation(operation, sourceId=null) {
  const batches = ["all","due","due_metabase","sheets","metabase","failed"];
  if (batches.includes(operation) && !await confirmAction("Iniciar coleta", `A operação ${operation} será executada em segundo plano. O sistema usa o lock atual para impedir concorrência.`)) return;
  try {
    const job=await api("/api/operations",{method:"POST",body:JSON.stringify({operation,source_id:sourceId,confirm:batches.includes(operation)})});
    toast("Coleta aceita; acompanhando o resultado real.","success"); location.href="/collections?job="+encodeURIComponent(job.id);
  } catch(e) { toast(e.message,"error"); }
}
function toast(text, kind="info") {
  let box=$("#toast"); if(!box){box=document.createElement("div");box.id="toast";box.className="toast";document.body.append(box);}
  box.className=`toast ${kind}`;box.textContent=text;box.hidden=false;setTimeout(()=>box.hidden=true,5000);
}
async function renderExports() {
  const d=await api("/api/exports");
  const rows=(d.sources||[]).map(s=>`<tr><td><input type="checkbox" data-export-id="${escapeHtml(s.id)}" aria-label="Selecionar ${escapeHtml(s.name)}"></td><td><b>${escapeHtml(s.name)}</b><small class="mono">${escapeHtml(s.id)}</small></td><td>${escapeHtml(s.type)}</td><td>${statusPill(s.status)}</td><td>${fmtDate(s.last_success)}</td><td>${s.export?statusPill(s.export.resultado):"Pendente"}</td><td>${s.export?`${fmtNum(s.export.linhas)} x ${fmtNum(s.export.colunas)}`:"-"}</td><td>${escapeHtml(s.export?.mensagem||"")}</td></tr>`);
  const latest=(d.history||[]).map(x=>`<tr><td>${fmtDate(x.fim_utc)}</td><td>${escapeHtml(x.fonte_id)}</td><td>${statusPill(x.resultado)}</td><td>${escapeHtml(x.sheet_title||"-")}</td><td>${fmtNum(x.linhas)} x ${fmtNum(x.colunas)}</td><td>${escapeHtml(x.mensagem||"")}</td></tr>`);
  const dest=d.spreadsheet_url?`<a class="inline-link" target="_blank" rel="noopener noreferrer" href="${escapeHtml(d.spreadsheet_url)}">Abrir planilha central</a>`:"";
  $("#page-content").innerHTML=`<div class="section-heading"><div><h2>Google Sheets Central</h2><p>A planilha e uma copia dos CSVs locais; coleta e exportacao tem estados separados.</p></div></div><article class="panel"><div class="panel-title"><div><h3>${d.configured?"Configuracao presente":"Exportacao ainda nao configurada"}</h3><p>${escapeHtml(d.message)}</p></div>${dest}</div><p>Fontes exportadas com sucesso: <b>${fmtNum(d.exported_count||0)}</b> | Ultimo teste: ${fmtDate(d.last_check?.checked_at)} | ${d.last_check?statusPill(d.last_check.ok?"SUCESSO":"FALHA"):"Nao testado"}</p><div class="button-row"><button class="button secondary" id="test-export">Testar conexao</button><button class="button secondary" id="export-selected">Exportar selecionadas</button><button class="button secondary" id="export-failed">Repetir falhas</button><button class="button primary" id="export-all">Exportar todas</button></div><div id="export-result" aria-live="polite"></div></article><article class="panel"><h3>Fontes e situacao da exportacao</h3>${table(["","Fonte","Tipo","Coleta local","Exportacao","Linhas x colunas","Mensagem"],rows)}</article><article class="panel"><h3>Historico de exportacoes (SQLite)</h3>${table(["Fim","Fonte","Resultado","Aba","Linhas x colunas","Mensagem"],latest)}</article>`;
  const run=async(ids,all=false)=>{const out=$("#export-result");out.innerHTML='<p class="muted">Preparando exportacao...</p>';try{const job=await api("/api/exports",{method:"POST",body:JSON.stringify({source_ids:ids,all,confirm:all})});let result;do{result=await api(`/api/exports/jobs/${encodeURIComponent(job.id)}`);out.innerHTML=`<p class="muted">Exportacao ${escapeHtml(result.status)}: ${fmtNum(result.completed)} de ${fmtNum(result.total)} fontes processadas.</p>`;if(result.status==="EM_ANDAMENTO")await new Promise(resolve=>setTimeout(resolve,700));}while(result.status==="EM_ANDAMENTO");out.innerHTML=`<div class="alert ${result.failed?"error":"success"}">${fmtNum(result.success)} exportadas | ${fmtNum(result.failed)} falharam</div>${table(["Fonte","Resultado","Aba","Linhas x colunas","Mensagem"],result.items.map(x=>`<tr><td>${escapeHtml(x.source_id)}</td><td>${statusPill(x.status)}</td><td>${escapeHtml(x.sheet_title||"-")}</td><td>${fmtNum(x.rows)} x ${fmtNum(x.columns)}</td><td>${escapeHtml(x.message)}</td></tr>`))}`;}catch(e){out.innerHTML=errorBox(e);}};
  $("#test-export").onclick=async()=>{const out=$("#export-result");out.textContent="Verificando conexao com Google...";try{const r=await api("/api/exports/test",{method:"POST",body:"{}"});out.innerHTML=`<div class="alert success">Conexao de leitura confirmada: ${escapeHtml(r.title||r.spreadsheet_id)} (${fmtNum(r.tabs)} abas).</div>`;}catch(e){out.innerHTML=errorBox(e);}};
  $("#export-selected").onclick=()=>{const ids=$$("[data-export-id]:checked").map(x=>x.dataset.exportId);if(!ids.length){toast("Selecione uma ou mais fontes.","error");return;}run(ids);};
  $("#export-failed").onclick=()=>{const ids=Object.entries(d.latest||{}).filter(([,x])=>x.resultado==="FALHA").map(([id])=>id);if(!ids.length){toast("Nao ha exportacoes com falha.");return;}run(ids);};
  $("#export-all").onclick=async()=>{if(await confirmAction("Exportar todas as fontes",`Serao exportadas ${d.sources.length} fontes. Essa acao nao altera as planilhas de origem.`))run([],true);};
}
function operationRows(items) { return items.map(x=>`<tr><td>${escapeHtml(x.id.slice(0,8))}</td><td>${escapeHtml(x.operacao)}${x.alvo?`<small>${escapeHtml(x.alvo)}</small>`:""}</td><td>${statusPill(x.status)}</td><td>${fmtDate(x.inicio_utc)}</td><td>${fmtDate(x.fim_utc)}</td><td>${x.duracao_segundos==null?"—":`${fmtNum(x.duracao_segundos)} s`}</td><td>${escapeHtml(x.mensagem_erro || x.resultado?.mensagem || "")}</td></tr>`); }
async function renderDashboard() {
  const d=await api("/api/dashboard"); const c=d.counts||{};
  $("#page-content").innerHTML=`<div class="section-heading"><div><h2>Visão operacional</h2><p>Estado derivado dos catálogos e do histórico SQLite.</p></div><button class="button secondary" data-refresh>Recarregar dados</button></div>
  <div class="metrics-grid">${metric("Fontes cadastradas",fmtNum(d.total_sources),"Metabase + Google Sheets")}${metric("Atualizadas",fmtNum(c.atualizada||0),"na periodicidade configurada","green")}${metric("Vencidas",fmtNum(c.vencida||0),"precisam de coleta","amber")}${metric("Com falha",fmtNum(c.falha||0),"última tentativa falhou","red")}${metric("Manuais",fmtNum(c.manual||0),"sem atualização automática")}</div>
  <div class="dashboard-grid"><article class="panel"><div class="panel-title"><div><h3>Execuções por dia</h3><p>Registros reais no SQLite</p></div></div>${renderTrend(d.trend)}</article><article class="panel"><div class="panel-title"><div><h3>Agendador Windows</h3><p>${escapeHtml(d.schedule.state)}</p></div>${statusPill(d.schedule.enabled===true?"habilitada":d.schedule.enabled===false?"pausada":"não confirmada")}</div><p class="muted">${escapeHtml(d.schedule.detail||"")}</p><a class="inline-link" href="/settings">Ver configurações →</a></article></div>
  <article class="panel"><div class="panel-title"><div><h3>Operações web recentes</h3><p>Último registro de coleta no SQLite: ${fmtDate(d.last_execution?.data_fim_utc)}</p></div><a href="/history" class="inline-link">Histórico completo →</a></div>${table(["Identificador","Operação","Resultado","Início","Fim","Duração","Mensagem"],operationRows(d.recent_operations||[]))}</article>
  ${d.active_operation?`<div class="alert info">Coleta em andamento: ${escapeHtml(d.active_operation.operacao)} (${escapeHtml(d.active_operation.id.slice(0,8))}). <a href="/collections">Acompanhar</a></div>`:""}`;
  $$('[data-refresh]').forEach(b=>b.onclick=()=>renderDashboard().catch(showError));
}
function renderTrend(days) {
  if(!days?.length)return empty("Ainda não há execuções registradas para o gráfico.");
  const max=Math.max(1,...days.map(d=>d.success+d.failure));
  return `<div class="trend">${days.map(d=>`<div class="trend-col" title="${escapeHtml(d.date)} · ${d.success} sucessos · ${d.failure} falhas"><div class="bar-stack"><i class="bar-success" style="height:${Math.max(2,100*d.success/max)}%"></i><i class="bar-failure" style="height:${Math.max(0,100*d.failure/max)}%"></i></div><small>${escapeHtml(d.date.slice(5))}</small></div>`).join("")}</div><div class="legend"><span><i class="legend-success"></i>Sucesso</span><span><i class="legend-failure"></i>Falha</span></div>`;
}
function sourceTable(items) {
  return items.map(s=>`<tr><td><b>${escapeHtml(s.name)}</b><small>${escapeHtml(s.id)}</small></td><td>${s.type==="metabase"?"Metabase":"Google Sheets"}</td><td>${escapeHtml(s.dashboard||"—")}</td><td>${escapeHtml(s.frequency)}</td><td>${statusPill(s.status)}</td><td>${fmtDate(s.last_success)}</td><td>${s.rows==null?"—":fmtNum(s.rows)} × ${s.columns==null?"—":fmtNum(s.columns)}</td><td class="row-actions"><button class="link-button" data-detail="${escapeHtml(s.id)}">Detalhes</button><button class="link-button" data-run="${escapeHtml(s.id)}">Coletar</button></td></tr>`);
}
async function renderSources(page=sourcePage) {
  sourcePage=page; const params=new URLSearchParams({page:String(page),page_size:"25",search:$("#source-search")?.value||"",type:$("#source-type")?.value||"",status:$("#source-status")?.value||""});
  const d=await api(`/api/sources?${params}`);
  $("#source-results").innerHTML=table(["Fonte / ID","Tipo","Dashboard","Periodicidade","Estado","Último sucesso","Linhas × colunas","Ações"],sourceTable(d.items));
  $("#source-page-info").textContent=`${d.total?((page-1)*25+1):0}–${Math.min(page*25,d.total)} de ${d.total}`;
  $("#source-prev").disabled=page<=1;$("#source-next").disabled=page*25>=d.total;
  $$("#source-results th").forEach((th,index)=>{th.title="Ordenar nesta página";th.tabIndex=0;th.setAttribute("role","button");const sort=()=>{$$("#source-results th").forEach(other=>other.removeAttribute("aria-sort"));const body=$("#source-results tbody"),rows=$$("tr",body),asc=th.dataset.order!=="asc";th.dataset.order=asc?"asc":"desc";th.setAttribute("aria-sort",asc?"ascending":"descending");rows.sort((a,b)=>{const x=a.cells[index].innerText.toLocaleLowerCase(),y=b.cells[index].innerText.toLocaleLowerCase();return x.localeCompare(y,"pt-BR",{numeric:true})*(asc?1:-1);}).forEach(row=>body.append(row));};th.onclick=sort;th.onkeydown=e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();sort();}};});
  $$('[data-detail]').forEach(b=>b.onclick=()=>showSource(b.dataset.detail));
  $$('[data-run]').forEach(b=>b.onclick=()=>startOperation("source",b.dataset.run));
}
async function showSource(id) {
  try { const d=await api(`/api/sources/${encodeURIComponent(id)}`); const s=d.source;
    const dialog=$("#source-dialog"); const st=s.storage||{}; $("#source-dialog-content").innerHTML=`<button class="dialog-close" data-close>×</button><p class="eyebrow">${escapeHtml(s.type)}</p><h2>${escapeHtml(s.name)}</h2><p class="mono">${escapeHtml(s.id)}</p><dl class="detail-grid"><dt>Dashboard</dt><dd>${escapeHtml(s.dashboard||"—")}</dd><dt>Periodicidade</dt><dd>${escapeHtml(s.frequency)}</dd><dt>Estado</dt><dd>${escapeHtml(s.status)}</dd><dt>Última tentativa</dt><dd>${fmtDate(s.last_attempt)}</dd><dt>Último sucesso</dt><dd>${fmtDate(s.last_success)}</dd><dt>Próxima coleta</dt><dd>${fmtDate(s.next_run)}</dd><dt>Linhas e colunas</dt><dd>${fmtNum(s.rows)} × ${fmtNum(s.columns)}</dd><dt>CSV</dt><dd class="mono">${escapeHtml(s.csv_path||"—")}</dd><dt>Último erro</dt><dd>${escapeHtml(s.error||"—")}</dd></dl><p>${s.url?`<a class="inline-link" href="${escapeHtml(s.url)}" rel="noreferrer">Abrir fonte pública ↗</a>`:""}</p><h3>Tentativas recentes</h3>${table(["Data","Resultado","Linhas","Colunas","Mensagem"],d.history.slice().reverse().slice(0,15).map(h=>`<tr><td>${fmtDate(h.data_fim_utc)}</td><td>${statusPill(h.status)}</td><td>${fmtNum(h.linhas_coletadas)}</td><td>${fmtNum(h.colunas)}</td><td>${escapeHtml(h.mensagem||"")}</td></tr>`))}`;
    $("[data-close]",dialog).onclick=()=>dialog.close();
    dialog.showModal();
  } catch(e) { toast(e.message,"error"); }
}
async function renderCollections() {
  const d=await api("/api/operations?limit=100"); const active=d.active;
  $("#page-content").innerHTML=`<div class="section-heading"><div><h2>Central de coletas</h2><p>Ações executadas pelo coletor existente. Ações em lote pedem confirmação.</p></div></div>
  ${active?`<article class="panel active-job"><span class="spinner"></span><div><b>Operação em andamento</b><p>${escapeHtml(active.operacao)} · iniciada ${fmtDate(active.inicio_utc)} · ${escapeHtml(active.id)}</p></div><button class="button secondary" id="poll-now">Atualizar estado</button></article>`:empty("Nenhuma coleta está em andamento.")}
  <div class="operation-grid">${[["all","Coletar todas","Executa Metabase e Google Sheets."],["due","Atualizar vencidas","Somente fontes vencidas com frequência configurada."],["due_metabase","Cards Metabase vencidos","Somente cards Metabase configurados e vencidos."],["sheets","Google Sheets","Coleta todas as planilhas configuradas."],["metabase","Metabase","Coleta os cards dos dashboards conhecidos."],["failed","Repetir falhas","Somente fontes com falha na última tentativa."]].map(x=>`<article class="operation-card"><span class="operation-icon">↻</span><h3>${x[1]}</h3><p>${x[2]}</p><button class="button ${x[0]==="all"?"primary":"secondary"}" data-operation="${x[0]}">Iniciar</button></article>`).join("")}</div>
  <article class="panel"><div class="panel-title"><div><h3>Execuções recentes</h3><p>Resultado gravado no SQLite.</p></div></div>${table(["ID","Operação","Estado","Início","Fim","Duração","Resumo / erro"],operationRows(d.items||[]))}</article>`;
  $$('[data-operation]').forEach(b=>b.onclick=()=>startOperation(b.dataset.operation));
  $("#poll-now")?.addEventListener("click",()=>renderCollections().catch(showError));
  if(active && !activePoll) activePoll=setInterval(()=>renderCollections().catch(()=>{}),2500); else if(!active && activePoll){clearInterval(activePoll);activePoll=null;}
}
async function renderHistory() {
  const params=new URLSearchParams({page:String(historyPage),page_size:"50",source_id:$("#history-source")?.value||"",source_type:$("#history-type")?.value||"",status:$("#history-status")?.value||"",date_from:$("#date-from")?.value||"",date_to:$("#date-to")?.value||""});
  const d=await api(`/api/history?${params}`);
  $("#history-results").innerHTML=table(["Execução","Tipo","Fonte","Estado","Data","Linhas × colunas","Duração","Mensagem"],d.items.map(r=>`<tr><td class="mono">${escapeHtml(r.execucao_id)}</td><td>${escapeHtml(r.fonte_tipo)}</td><td>${escapeHtml(r.fonte_id)}</td><td>${statusPill(r.status)}</td><td>${fmtDate(r.data_fim_utc)}</td><td>${fmtNum(r.linhas_coletadas)} × ${fmtNum(r.colunas)}</td><td>${fmtNum(r.duracao_segundos)} s</td><td>${escapeHtml(r.mensagem||"")}</td></tr>`));
  $("#history-count").textContent=`${d.total} tentativas`; $("#history-prev").disabled=historyPage<=1;$("#history-next").disabled=historyPage*50>=d.total;
  $("#operation-history").innerHTML=table(["ID","Operação","Estado","Início","Fim","Duração","Erro"],operationRows(d.operations||[]));
}
async function updateFrequency(sourceId, frequency, note) {
  try { await api(`/api/sources/${encodeURIComponent(sourceId)}/frequency`,{method:"PATCH",body:JSON.stringify({frequency,periodicity_source:note||null})}); toast("Periodicidade salva.","success"); }
  catch(e){toast(e.message,"error");}
}
async function renderSettings() {
  const [settings,firstPage]=await Promise.all([api("/api/settings"),api("/api/sources?page=1&page_size=100")]);
  const sources=firstPage.total>firstPage.items.length?{items:[...firstPage.items,...(await api("/api/sources?page=2&page_size=100")).items]}:firstPage;
  const freqOptions=Object.entries(settings.frequencies).map(([key])=>key).sort();
  const cardRows=sources.items.map(s=>`<tr><td><b>${escapeHtml(s.name)}</b><small class="mono">${escapeHtml(s.id)}</small></td><td>${s.type}</td><td><select data-frequency="${escapeHtml(s.id)}">${freqOptions.map(f=>`<option value="${f}" ${f===s.frequency?"selected":""}>${f}</option>`).join("")}</select></td><td><input data-note="${escapeHtml(s.id)}" maxlength="240" placeholder="Fonte/peridiocidade oficial" value="${escapeHtml(s.periodicity_source||"")}"></td><td>${fmtDate(s.next_run)}</td><td><button class="link-button" data-save-frequency="${escapeHtml(s.id)}">Salvar</button></td></tr>`);
  $("#page-content").innerHTML=`<div class="section-heading"><div><h2>Configurações operacionais</h2><p>Credenciais nunca são exibidas. Caminhos vêm da configuração local.</p></div></div>
  <div class="dashboard-grid"><article class="panel"><h3>Agendamento Windows</h3><p>Estado consultado no sistema: ${statusPill(settings.scheduler.enabled===true?"habilitada":settings.scheduler.enabled===false?"pausada":settings.scheduler.exists?"estado desconhecido":"não configurada")}</p><pre class="code-block">${escapeHtml(settings.scheduler.detail||"")}</pre><p class="muted">A tarefa só é alterada após confirmação explícita. Requer sessão do usuário conectada.</p><div class="form-row"><select id="schedule-action"><option value="install">Instalar</option><option value="pause">Pausar</option><option value="resume">Retomar</option><option value="remove">Remover</option></select><select id="schedule-frequency"><option value="daily">Diária</option><option value="weekly" selected>Semanal</option><option value="monthly">Mensal</option></select><input id="schedule-time" type="time" value="06:00"></div><div class="button-row"><button class="button secondary" id="schedule-preview">Dry-run</button><button class="button primary" id="schedule-change">Executar ação…</button></div><pre id="schedule-output" class="code-block" hidden></pre></article>
  <article class="panel"><h3>Diretórios configurados</h3><dl class="detail-grid">${Object.entries(settings.paths||{}).map(([k,v])=>`<dt>${escapeHtml(k)}</dt><dd class="mono">${escapeHtml(v)}</dd>`).join("")}</dl><a class="inline-link" href="#reports" id="open-reports">Relatórios existentes →</a><div id="reports-list"></div></article></div>
  <article class="panel"><div class="panel-title"><div><h3>Periodicidade por fonte</h3><p>Para Metabase, informe a fonte da periodicidade. Sem frequência documentada, mantenha “manual”.</p></div></div>${table(["Fonte / identificador","Tipo","Frequência","Justificativa / fonte","Próxima coleta","Ação"],cardRows)}</article>`;
  $$('[data-save-frequency]').forEach(b=>b.onclick=()=>updateFrequency(b.dataset.saveFrequency,$(`[data-frequency="${CSS.escape(b.dataset.saveFrequency)}"]`).value,$(`[data-note="${CSS.escape(b.dataset.saveFrequency)}"]`).value));
  $("#schedule-preview").onclick=async()=>{try{const d=await api("/api/scheduler/dry-run",{method:"POST",body:JSON.stringify({action:$("#schedule-action").value,frequency:$("#schedule-frequency").value,time:$("#schedule-time").value})});const out=$("#schedule-output");out.hidden=false;out.textContent=d.command_preview+"\nTarefa criada: não";}catch(e){toast(e.message,"error");}};
  $("#schedule-change").onclick=async()=>{const action=$("#schedule-action").value;if(!await confirmAction("Confirmar alteração no Agendador",`A ação “${action}” será enviada ao Agendador do Windows. O sistema consultará o resultado real.`))return;try{const d=await api("/api/scheduler",{method:"POST",body:JSON.stringify({action,frequency:$("#schedule-frequency").value,time:$("#schedule-time").value,confirm:true})});toast(d.success?"Comando do Agendador concluído.":"O Agendador retornou falha.",d.success?"success":"error");$("#schedule-output").hidden=false;$("#schedule-output").textContent=d.output+"\nEstado após ação: "+d.status.state;}catch(e){toast(e.message,"error");}};
  $("#open-reports").onclick=async event=>{event.preventDefault();try{const d=await api("/api/reports");$("#reports-list").innerHTML=d.items.map(x=>`<button class="link-button report-link" data-report="${escapeHtml(x.name)}">${escapeHtml(x.name)}</button>`).join("");$$('[data-report]').forEach(b=>b.onclick=async()=>{const report=await api(`/api/reports/${encodeURIComponent(b.dataset.report)}`);$("#reports-list").innerHTML=`<h4>${escapeHtml(report.name)}</h4><pre class="code-block report-content">${escapeHtml(report.content)}</pre>`;});}catch(e){toast(e.message,"error");}};
}
function shell() {
  $("#page-title").textContent=labels[section]||"OPPES"; $$('[data-nav]').forEach(a=>a.classList.toggle("active",a.dataset.nav===section));
  $("#server-clock").textContent=new Intl.DateTimeFormat("pt-BR",{timeStyle:"short",timeZone:"America/Sao_Paulo"}).format(new Date());
  $("#refresh").onclick=()=>loadPage().catch(showError);
  $("#logout").onclick=async()=>{try{await api("/api/logout",{method:"POST",body:"{}"});location.href="/login";}catch(e){toast(e.message,"error");}};
}
function showError(e){$("#page-content").innerHTML=errorBox(e);}
async function loadPage() {
  const view=$("#page-content"); view.innerHTML='<div class="loading"><span class="spinner"></span> Consultando SQLite e catálogos…</div>';
  try {
    if(section==="dashboard") await renderDashboard();
    if(section==="sources") {view.innerHTML=`<div class="section-heading"><div><h2>Catálogo de fontes</h2><p>Busca, filtros e acesso às execuções individuais.</p></div></div><div class="filter-row"><input id="source-search" placeholder="Buscar nome, ID, dashboard ou URL"><select id="source-type"><option value="">Todos os tipos</option><option value="metabase">Metabase</option><option value="sheets">Google Sheets</option></select><select id="source-status"><option value="">Todos os estados</option><option>atualizada</option><option>vencida</option><option>manual</option><option>falha</option><option>pendente</option></select><button class="button secondary" id="apply-source-filter">Filtrar</button></div><div id="source-results"></div><div class="pagination"><span id="source-page-info"></span><button id="source-prev" class="button secondary">Anterior</button><button id="source-next" class="button secondary">Próxima</button></div><dialog id="source-dialog"><div class="dialog-card"><button class="dialog-close" data-close>×</button><div id="source-dialog-content"></div></div></dialog>`;$("#source-dialog [data-close]").onclick=()=>$("#source-dialog").close();$("#apply-source-filter").onclick=()=>renderSources(1).catch(showError);$("#source-prev").onclick=()=>renderSources(sourcePage-1).catch(showError);$("#source-next").onclick=()=>renderSources(sourcePage+1).catch(showError);$("#source-search").onkeydown=e=>{if(e.key==="Enter")renderSources(1).catch(showError);};await renderSources(1); }
    if(section==="collections") await renderCollections();
    if(section==="exports") await renderExports();
    if(section==="history") {view.innerHTML=`<div class="section-heading"><div><h2>Histórico persistente</h2><p>Tentativas por fonte e operações em lote, consultadas no SQLite.</p></div></div><div class="filter-row"><input id="date-from" type="date"><input id="date-to" type="date"><input id="history-source" placeholder="ID da fonte"><select id="history-type"><option value="">Todos os tipos</option><option value="metabase">Metabase</option><option value="sheets">Google Sheets</option></select><input id="history-status" placeholder="Status exato"><button id="history-filter" class="button secondary">Filtrar</button><span id="history-count"></span></div><div id="history-results"></div><div class="pagination"><button id="history-prev" class="button secondary">Anterior</button><button id="history-next" class="button secondary">Próxima</button></div><article class="panel"><h3>Operações web</h3><div id="operation-history"></div></article><article class="panel"><h3>Relatórios</h3><div id="history-reports"></div></article>`;$("#history-filter").onclick=()=>{historyPage=1;renderHistory().catch(showError);};$("#history-prev").onclick=()=>{historyPage--;renderHistory().catch(showError);};$("#history-next").onclick=()=>{historyPage++;renderHistory().catch(showError);};await renderHistory();const reports=await api("/api/reports");$("#history-reports").innerHTML=reports.items.map(x=>`<button class="link-button report-history" data-file="${escapeHtml(x.name)}">${escapeHtml(x.name)}</button>`).join("");$$('[data-file]').forEach(b=>b.onclick=async()=>{const x=await api(`/api/reports/${encodeURIComponent(b.dataset.file)}`);const dlg=document.createElement("dialog");dlg.className="report-dialog";dlg.innerHTML=`<article class="dialog-card"><button class="dialog-close">×</button><h2>${escapeHtml(x.name)}</h2><pre class="code-block report-content">${escapeHtml(x.content)}</pre></article>`;document.body.append(dlg);$(".dialog-close",dlg).onclick=()=>dlg.close();dlg.addEventListener("close",()=>dlg.remove());dlg.showModal();}); }
    if(section==="settings") await renderSettings();
  } catch(e) {showError(e);}
}
(async()=>{try{const s=await api("/api/session");if(typeof s.csrf_token!=="string"||!s.csrf_token)throw new Error("Sessão inválida; recarregue a página.");csrf=s.csrf_token;if(!s.authenticated){location.href="/login";return;}shell();await loadPage();}catch(e){showError(e);}})();
