'use strict';
const $ = (s) => document.querySelector(s);
const escapeHTML = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const token = new URLSearchParams(location.hash.slice(1)).get('token') || '';
history.replaceState(null, '', location.pathname);
let snapshot = null, cursor = 0, events = [], view = 'overview', project = 'all', search = '', stateFilter = 'all', connected = false, selectedTask = null, detailSignature = '', polling = false, toastTimer;
const names = {overview:'Control room', tasks:'Task board', agents:'Your agents', activity:'Activity log', artifacts:'Artifacts', settings:'Runtime settings'};
const subtitles = {overview:'A clear view of the work. You stay at the helm.',tasks:'Follow each task from queue to verified result.',agents:'Capabilities are visible. Unknown stays unknown.',activity:'A durable record of decisions, transitions and user controls.',artifacts:'Results and verification evidence, tied to a specific attempt.',settings:'Local transport, runtime boundaries and current limitations.'};
const shortID = (id) => (id || 'Not assigned').slice(-6).toUpperCase();
const badge = (state) => `<span class="badge ${state.toLowerCase().replaceAll('_','-')}">${escapeHTML(state.replaceAll('_',' '))}</span>`;
const date = (t) => new Date(t * 1000).toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'});
const terminal = ['COMPLETED','FAILED','CANCELLED','BLOCKED'];
const active = ['RUNNING','VERIFY','REVIEW','WAITING_INPUT','WAITING_APPROVAL','CANCELLING'];

function toast(message) { $('#toast').textContent = message; $('#toast').hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => $('#toast').hidden = true, 4200); }
async function api(path, body) {
  const response = await fetch(path, {method:body ? 'POST':'GET', headers:{Authorization:`Bearer ${token}`, ...(body ? {'Content-Type':'application/json'} : {})}, ...(body ? {body:JSON.stringify(body)} : {}), signal:AbortSignal.timeout(7000)});
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || `Request failed (${response.status})`);
  return result;
}
async function command(body) {
  if (!connected) { toast('Reconnect before sending controls.'); return null; }
  try { const result = await api('/api/command', body); await poll(); return result; }
  catch (err) { toast(err.message); return null; }
}
async function poll() {
  if (polling) return;
  polling = true;
  try {
    const result = await api(`/api/snapshot?cursor=${cursor}`);
    events = [...events, ...result.events].slice(-1000); cursor = result.cursor;
    const changed = !snapshot || JSON.stringify({...result,events:[],cursor:0,latest_cursor:0}) !== JSON.stringify({...snapshot,events:[],cursor:0,latest_cursor:0});
    snapshot = result; connected = true;
    $('#connection-alert').hidden = true; $('#local-connection').textContent = 'Connected';
    $('#pause').disabled = false; $('#new-task').disabled = false; $('#add-project').disabled = false;
    if (changed || view === 'activity') render();
    if (selectedTask) updateDetail();
  } catch (err) {
    connected = false; $('#local-connection').textContent = 'Disconnected';
    $('#connection-alert').textContent = token ? 'Connection lost. Displayed state may be stale; controls are disabled. Reconnecting…' : 'Open the full launch link printed by “python -m navis” to authenticate. Reloading the page requires reopening that link.';
    $('#connection-alert').hidden = false; $('#pause').disabled = true; $('#new-task').disabled = true; $('#add-project').disabled = true;
    $('#task-detail').querySelectorAll('button[data-action],button[type="submit"]').forEach(b => b.disabled = true);
    if (!snapshot) $('#content').innerHTML = '<div class="panel empty-state"><span class="empty-icon">◈</span><strong>Connect your local runtime</strong><p>Run python -m navis and open its launch link. The control room will appear here.</p></div>';
  } finally { polling = false; }
}
function filteredTasks() { return snapshot.tasks.filter(t => project === 'all' || t.project_id === project); }
function empty(title, description, icon='◈') {return `<div class="empty-state"><span class="empty-icon">${icon}</span><strong>${escapeHTML(title)}</strong><p>${escapeHTML(description)}</p></div>`;}
function stats(tasks) {
  const running = tasks.filter(t => active.includes(t.state)).length;
  const waiting = tasks.filter(t => ['WAITING_INPUT','WAITING_APPROVAL','WAITING_QUOTA','BLOCKED'].includes(t.state)).length;
  return `<div class="stats">
    <div class="stat"><div class="stat-top">Total tasks<span>▦</span></div><div class="stat-value">${tasks.length}</div><div class="stat-footer">Across ${project === 'all' ? snapshot.projects.length : 1} project${project === 'all' && snapshot.projects.length !== 1 ? 's' : ''}</div></div>
    <div class="stat"><div class="stat-top">Active attempts<span>◌</span></div><div class="stat-value">${running}<span class="muted"> / 1</span></div><div class="stat-footer purple">${snapshot.paused ? 'Dispatch paused · active work continues' : 'One simulated agent slot'}</div></div>
    <div class="stat"><div class="stat-top">Needs attention<span>◷</span></div><div class="stat-value">${waiting}</div><div class="stat-footer">${waiting ? 'Input, approval, cooldown or blocked' : 'Nothing waiting on you'}</div></div>
    <div class="stat"><div class="stat-top">Completed<span>✓</span></div><div class="stat-value">${tasks.filter(t=>t.state==='COMPLETED').length}</div><div class="stat-footer green">Simulated verification only</div></div>
  </div>`;
}
function card(t) {
  return `<button class="task-card" data-task="${escapeHTML(t.id)}"><div class="card-top"><span>NAV-${shortID(t.id)}</span>${badge(t.state)}</div><h3>${escapeHTML(t.title)}</h3><span class="scope-label">⌁ ${escapeHTML(t.scope.join(', '))}</span><div class="card-bottom"><span><span class="agent-avatar">F</span>fake-agent</span><span>${date(t.updated_at)}</span></div></button>`;
}
function board(tasks) {
  const groups = [['Queued',['QUEUED']],['In progress',['RUNNING','VERIFY','REVIEW','CANCELLING']],['Needs attention',['WAITING_INPUT','WAITING_APPROVAL','WAITING_QUOTA','BLOCKED']],['Finished',['COMPLETED','FAILED','CANCELLED']]];
  const visible = tasks.filter(t=>(stateFilter==='all'||t.state===stateFilter) && `${t.title} ${t.spec} ${t.scope.join(' ')}`.toLowerCase().includes(search.toLowerCase()));
  return `<div class="board">${groups.map(([name,states])=>{const items=visible.filter(t=>states.includes(t.state));return `<section class="column"><div class="column-heading"><span class="column-dot"></span>${name}<span class="column-count">${items.length}</span></div>${items.length ? items.map(card).join('') : '<div class="empty-column">No tasks here yet</div>'}${name==='Queued' ? '<button class="column-add" data-new-task>+ Add a task</button>' : ''}</section>`;}).join('')}</div>`;
}
function agentRow(name, desc, mark, status, className='', sub='') {
  return `<div class="agent-row"><span class="provider-mark ${className}">${mark}</span><div class="agent-info"><strong>${name}</strong><small>${desc}</small></div><div class="agent-status ${status==='Ready' ? 'ready' : ''}">${status}<span>${sub}</span></div></div>`;
}
function agentPanel() {
  const busy = snapshot.tasks.some(t=>active.includes(t.state));
  return `<section class="panel"><div class="panel-header"><h2>Agent fleet</h2><button class="text-button" data-view="agents">View agents ↗</button></div>
  ${agentRow('Fake agent','Deterministic simulation · no tools','F',busy ? 'Busy' : 'Ready','fake',busy ? '1 / 1 slots' : '0 / 1 slots')}
  ${agentRow('Codex','CLI adapter · feasibility pending','✳','Not tested','','Disabled')}
  ${agentRow('Claude Code','CLI adapter · feasibility pending','✽','Not tested','claude','Disabled')}
  ${agentRow('Local LLM','Context summary & log analysis only','⌘','Not connected','local','No write / exec tools')}
  </section>`;
}
function eventList(limit=8) {
  const relevant = events.filter(e=>project==='all'||e.project_id===project).slice(-limit).reverse();
  return relevant.length ? `<div class="timeline">${relevant.map(e=>`<div class="event-row"><span class="event-mark">${e.type==='STATE' ? '↗' : e.type==='CONTROL' ? 'Ⅱ' : '◇'}</span><div class="event-body"><p>${escapeHTML(e.message)}</p><small>${escapeHTML(e.type)} · ${e.task_id ? 'NAV-'+shortID(e.task_id) : 'Runtime'} · #${e.seq}</small></div><span class="event-time">${date(e.time)}</span></div>`).join('')}</div>` : empty('Your audit trail starts here','Create a task or use a control to see runtime events.','≋');
}
function artifacts(tasks) {
  const items=tasks.flatMap(t=>t.artifacts.map(a=>({...a,task:t})));
  return items.length ? `<div class="artifacts">${items.map(a=>`<section class="panel artifact"><div class="panel-header"><h3>${escapeHTML(a.name)}</h3><span class="badge">SIMULATED</span></div><button class="text-button" data-task="${a.task.id}">${escapeHTML(a.task.title)} ↗</button><small>Attempt ${escapeHTML(a.attempt_id)}</small><pre>${escapeHTML(a.content)}</pre><small>SHA-256 ${escapeHTML(a.hash)}</small></section>`).join('')}</div>` : `<section class="panel">${empty('No artifacts yet','Completed simulation steps will produce result and verification evidence.','◇')}</section>`;
}
function render() {
  if (!snapshot) return;
  const focused = document.activeElement;
  const focusID = focused?.id, selection = focused?.selectionStart;
  $('#page-title').textContent=names[view]; $('#page-subtitle').textContent=subtitles[view]; $('#view-label').textContent=view==='overview' ? 'Overview' : names[view];
  document.querySelectorAll('.sidebar .nav-item').forEach(b=>b.classList.toggle('active',b.dataset.view===view));
  $('#pause').textContent=snapshot.paused ? '▷ Resume dispatch' : 'Ⅱ Pause dispatch';
  $('#nav-task-count').textContent=snapshot.tasks.length;
  $('#project-list').innerHTML=`<button class="project-item ${project==='all' ? 'active':''}" data-project="all"><span class="project-dot"></span><span>All projects</span></button>`+snapshot.projects.map(p=>`<button class="project-item ${project===p.id ? 'active':''}" data-project="${p.id}"><span class="project-dot"></span><span>${escapeHTML(p.name)}</span></button>`).join('');
  const tasks=filteredTasks(); let html='';
  if(view==='overview'||view==='tasks') {
    html=stats(tasks);
    const pending=tasks.filter(t=>t.pending);
    if(pending.length) html+=`<div class="attention-strip"><span>◷</span><span>${pending.length} task${pending.length!==1?'s':''} waiting for your response</span><button class="text-button" data-task="${pending[0].id}">Review request →</button></div>`;
    html+=`<div class="section-title"><h2>Task board <small>${project==='all'?'All projects':escapeHTML(snapshot.projects.find(p=>p.id===project)?.name)}</small></h2><button class="text-button" data-new-task>+ Create task</button></div>`;
    if(view==='tasks') html+=`<div class="board-toolbar"><input id="task-search" class="search" placeholder="Search tasks…" aria-label="Search tasks" value="${escapeHTML(search)}"><select id="state-filter" aria-label="Filter by state"><option value="all">All states</option>${[...new Set(snapshot.tasks.map(t=>t.state))].sort().map(s=>`<option ${s===stateFilter?'selected':''}>${s}</option>`).join('')}</select></div>`;
    html+=board(tasks);
    if(view==='overview') html+=`<div class="lower-grid">${agentPanel()}<section class="panel"><div class="panel-header"><h2>Recent activity</h2><button class="text-button" data-view="activity">View audit log ↗</button></div>${eventList()}</section></div>`;
  } else if(view==='agents') {
    html=`<div class="agent-grid"><section class="panel agent-card">${agentRow('Fake agent','In-process UI contract fixture','F','Ready','fake','1 slot')}<div class="capability-list"><span class="capability">Lifecycle simulation</span><span class="capability">User requests</span><span class="capability">Deterministic verification</span></div><p>Exercises controls without starting processes, reading files or consuming provider quota. This is not the sandboxed fake-agent CLI described in the execution design.</p></section>${[['Codex','✳','','Provider CLI/session'],['Claude Code','✽','claude','Provider CLI/session'],['Local LLM','⌘','local','Text summaries and log analysis']].map(([name,mark,cls,desc])=>`<section class="panel agent-card">${agentRow(name,desc,mark,'Unavailable',cls,'Not implemented')}<div class="capability-list"><span class="capability">Capability: unknown</span><span class="capability">Execution disabled</span></div><p>Enable only after the Agent Runner and the backend acceptance probes pass. No credentials are requested by this GUI.</p></section>`).join('')}</div>`;
  } else if(view==='activity') html=`<section class="panel"><div class="panel-header"><h2>Runtime events</h2><span class="muted">Cursor ${cursor} · latest 1,000 shown</span></div>${eventList(1000)}</section>`;
  else if(view==='artifacts') html=artifacts(tasks);
  else html=`<section class="panel"><h2>Runtime boundary</h2><dl class="settings-list">${[['Mode','Simulation only'],['Core','Python 3.11+ · standard library'],['State','SQLite · atomic state + events'],['Transport','Authenticated HTTP · 127.0.0.1 only'],['Client identity','Per-launch bearer capability · single local user'],['Remote listener','Disabled'],['Dispatch',snapshot.paused?'Paused; active attempt continues':'Enabled · 1 fake-agent slot'],['Restart recovery','Active attempts revoked → BLOCKED'],['Provider CLI / Local inference','Not implemented'],['Workspace / sandbox / cgroups','Not implemented · no real execution'],['Push / merge / deploy','No runtime endpoints'],['Artifact evidence','Simulated content + SHA-256'],['Dependencies / rollback / reassignment','Deferred until real runner']].map(([a,b])=>`<div><dt>${escapeHTML(a)}</dt><dd>${escapeHTML(b)}</dd></div>`).join('')}</dl></section>`;
  $('#content').innerHTML=html;
  if(focusID) { const el=document.getElementById(focusID); if(el) {el.focus(); if(selection!==null&&typeof el.setSelectionRange==='function') el.setSelectionRange(selection,selection);} }
}
function openTaskForm() {
  $('#task-form').reset(); $('#task-form .form-error').textContent='';
  $('#task-project').innerHTML=snapshot.projects.map(p=>`<option value="${p.id}" ${project===p.id?'selected':''}>${escapeHTML(p.name)}</option>`).join('');
  $('#task-dialog').showModal();
}
function updateDetail(force=false) {
  const task=snapshot.tasks.find(t=>t.id===selectedTask); if(!task) return;
  const signature=JSON.stringify([task.state,task.attempt_id,task.pending,task.artifacts,task.instructions,task.activity,connected]);
  if(!force&&signature===detailSignature)return;
  const saved={}; $('#task-detail').querySelectorAll('textarea').forEach(el=>saved[el.name]=el.value);
  detailSignature=signature;
  const controls=[];
  if(!terminal.includes(task.state)) controls.push(`<button class="button secondary" data-action="stop">■ Stop</button>`);
  if(active.includes(task.state)) controls.push(`<button class="button danger" data-action="kill">Kill simulation</button>`);
  if(['FAILED','CANCELLED','BLOCKED'].includes(task.state)) controls.push(`<button class="button primary" data-action="retry">↻ Retry as new attempt</button>`);
  let request='';
  if(task.pending) {
    request=`<section class="request-box"><h3>${task.state==='WAITING_APPROVAL'?'Approval required':'Your input is needed'}</h3><p>${escapeHTML(task.pending.message)}</p><small>Expires at ${date(task.pending.expires)} · bound to this attempt and payload</small>${task.state==='WAITING_APPROVAL'?'<div class="detail-actions"><button class="button primary" data-action="approve">Approve simulation</button><button class="button danger" data-action="reject">Reject</button></div>':'<form id="answer-form"><label>Your answer<textarea name="answer" required maxlength="2000" rows="2"></textarea></label><button class="button primary" type="submit">Send answer →</button></form>'}</section>`;
  }
  $('#task-detail').innerHTML=`<div class="dialog-heading"><div><span class="eyebrow">NAV-${shortID(task.id)} · SIMULATION</span><h2>${escapeHTML(task.title)}</h2></div><button class="icon-button" data-close="detail-dialog" aria-label="Close">×</button></div><div class="detail-meta">${badge(task.state)}<span class="muted">fake-agent</span></div><p class="detail-description">${escapeHTML(task.spec)}</p><div class="detail-fields"><div><span>Scope</span>${escapeHTML(task.scope.join(', '))}</div><div><span>Current attempt</span>${escapeHTML(task.attempt_id||'Not dispatched')}</div><div><span>Attempts</span>${task.attempts.length}</div><div><span>Scenario</span>${escapeHTML(task.scenario)}</div></div><p class="muted">${escapeHTML(task.activity)}</p>${request}<div class="detail-actions">${controls.join('')}</div>${!terminal.includes(task.state)&&task.state!=='CANCELLING'?'<section class="detail-section"><h3>Add an instruction</h3><form id="instruction-form"><label>Versioned guidance for the next simulated step<textarea name="instruction" rows="2" required maxlength="2000"></textarea></label><button class="button secondary" type="submit">Save instruction</button></form></section>':''}${task.instructions.length?`<section class="detail-section"><h3>Instruction history</h3>${task.instructions.map(i=>`<pre>v${i.version} · ${escapeHTML(i.text)}</pre>`).join('')}</section>`:''}<section class="detail-section"><h3>Results & verification</h3>${task.artifacts.length?task.artifacts.map(a=>`<small>${escapeHTML(a.name)} · SIMULATED · SHA-256 ${escapeHTML(a.hash)}</small><pre>${escapeHTML(a.content)}</pre>`).join(''): '<p class="muted">No evidence produced yet.</p>'}</section><section class="detail-section"><h3>Attempt history</h3>${task.attempts.map(a=>`<small>${escapeHTML(a.id)} · ${date(a.started_at)} · ${escapeHTML(a.backend)} · ${escapeHTML(a.state||'RUNNING')}</small>`).join('')||'<p class="muted">Waiting for dispatch.</p>'}</section>`;
  $('#task-detail').querySelectorAll('textarea').forEach(el=>{if(saved[el.name])el.value=saved[el.name];});
  if(!connected)$('#task-detail').querySelectorAll('button[data-action],button[type="submit"]').forEach(b=>b.disabled=true);
}
function taskCommand(action, extra={}) {
  const task=snapshot.tasks.find(t=>t.id===selectedTask);
  return command({action,task_id:task.id,attempt_id:task.attempt_id,...extra});
}
document.addEventListener('click', async (e)=>{
  const close=e.target.closest('[data-close]'); if(close){document.getElementById(close.dataset.close).close();return;}
  const nav=e.target.closest('[data-view]'); if(nav){view=nav.dataset.view;search='';stateFilter='all';render();return;}
  const proj=e.target.closest('[data-project]'); if(proj){project=proj.dataset.project;render();return;}
  if(e.target.closest('[data-new-task]')||e.target.closest('#new-task')) {if(connected)openTaskForm();return;}
  const task=e.target.closest('[data-task]'); if(task){selectedTask=task.dataset.task;updateDetail(true);$('#detail-dialog').showModal();return;}
  const action=e.target.closest('[data-action]'); if(action){const current=snapshot.tasks.find(t=>t.id===selectedTask);action.disabled=true;const result=await taskCommand(action.dataset.action, {pending_id:current.pending?.id});if(result)toast(result.expired?'Request expired; task blocked.':'Control accepted by runtime.');action.disabled=false;}
});
$('#detail-dialog').addEventListener('close',()=>{selectedTask=null;detailSignature='';});
$('#add-project').onclick=()=>{$('#project-form').reset();$('#project-form .form-error').textContent='';$('#project-dialog').showModal();};
$('#refresh').onclick=()=>poll();
$('#pause').onclick=async()=>{const result=await command({action:snapshot.paused?'resume':'pause'});if(result)toast(snapshot.paused?'Dispatch paused. Active simulation continues.':'Dispatch resumed.');};
$('#task-form').onsubmit=async(e)=>{
  e.preventDefault();const form=e.currentTarget;const button=form.querySelector('[type="submit"]');button.disabled=true;
  try{const result=await api('/api/command',{action:'create_task',...Object.fromEntries(new FormData(form))});$('#task-dialog').close();await poll();toast(result.duplicate?'Matching task already exists; opening it.':'Task queued for simulation.');selectedTask=result.task_id;updateDetail(true);$('#detail-dialog').showModal();}
  catch(err){form.querySelector('.form-error').textContent=err.message;}finally{button.disabled=false;}
};
$('#project-form').onsubmit=async(e)=>{e.preventDefault();const form=e.currentTarget;const button=form.querySelector('[type="submit"]');button.disabled=true;try{const result=await api('/api/command',{action:'create_project',name:new FormData(form).get('name')});project=result.id;$('#project-dialog').close();await poll();toast('Simulation project added.');}catch(err){form.querySelector('.form-error').textContent=err.message;}finally{button.disabled=false;}};
$('#task-detail').addEventListener('submit',async(e)=>{e.preventDefault();const form=e.target;const button=form.querySelector('[type="submit"]');button.disabled=true;const result=await taskCommand(form.id==='answer-form'?'answer':'instruction', {text:new FormData(form).get(form.id==='answer-form'?'answer':'instruction'),pending_id:snapshot.tasks.find(t=>t.id===selectedTask).pending?.id});if(result){toast('Saved for this attempt.');form.reset();}button.disabled=false;});
$('#content').addEventListener('input',(e)=>{if(e.target.id==='task-search'){search=e.target.value;render();}});
$('#content').addEventListener('change',(e)=>{if(e.target.id==='state-filter'){stateFilter=e.target.value;render();}});
poll();setInterval(poll,1500);
