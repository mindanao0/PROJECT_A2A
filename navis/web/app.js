'use strict';
const $ = s => document.querySelector(s);
const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let token = new URLSearchParams(location.hash.slice(1)).get('token') || '';
history.replaceState(null, '', location.pathname);
let snapshot = null, cursor = 0, events = [], view = 'overview', project = 'all', search = '', stateFilter = 'all';
let connected = false, selectedTask = null, taskDetail = null, detailTab = 'results', detailSignature = '', polling = false, toastTimer;
let eventTask = 'all', eventType = 'all', eventLimit = 100, confirmPending = false;
const columnLimits = [12,12,12,12];
const names = {overview:'Control room',tasks:'Task board',agents:'Your agents',activity:'Activity log',artifacts:'Artifacts',resources:'Resources',settings:'Runtime settings'};
const subtitles = {overview:'Your directives. Your agents. Your control.',tasks:'Follow each task from queue to verified result.',agents:'Slots, cooldowns and available capabilities.',activity:'Trace decisions and controls for one task or the whole runtime.',artifacts:'Full results and verification evidence, tied to their attempt.',resources:'Dispatch capacity and measured resource availability.',settings:'Local transport, reconnect and current boundaries.'};
const terminal = ['COMPLETED','FAILED','CANCELLED','BLOCKED'];
const active = ['RUNNING','VERIFY','REVIEW','WAITING_INPUT','WAITING_APPROVAL','CANCELLING'];
const shortID = id => (id || 'Not assigned').slice(-6).toUpperCase();
const badge = state => `<span class="badge ${escapeHTML(state.toLowerCase().replaceAll('_','-'))}">${escapeHTML(state.replaceAll('_',' '))}</span>`;
const date = t => new Date(t * 1000).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'});
const simulation = () => snapshot?.mode !== 'real';
const currentTask = () => taskDetail?.task?.id === selectedTask ? taskDetail.task : snapshot?.tasks.find(t => t.id === selectedTask);

function toast(message) {
  $('#toast').textContent = message; $('#toast').hidden = false; $('#announcer').textContent=message;
  clearTimeout(toastTimer); toastTimer = setTimeout(() => $('#toast').hidden = true, 4200);
}
async function api(path, body) {
  const response = await fetch(path, {method:body ? 'POST':'GET',credentials:'same-origin',
    headers:{...(token ? {Authorization:`Bearer ${token}`} : {}),...(body ? {'Content-Type':'application/json'} : {})},
    ...(body ? {body:JSON.stringify(body)} : {}),signal:AbortSignal.timeout(7000)});
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || `Request failed (${response.status})`);
  return result;
}
async function command(body) {
  if (!connected) { toast('Reconnect before sending controls.'); return null; }
  try { const result = await api('/api/command',body); await poll(); return result; }
  catch (err) { toast(err.message); return null; }
}
function updateAttention(previous, result) {
  const pending = result.tasks.filter(t => t.pending);
  document.title = pending.length ? `(${pending.length} waiting) Navis — ${names[view]}` : `Navis — ${names[view]}`;
  if (!previous || !document.hidden || !('Notification' in window) || Notification.permission !== 'granted') return;
  const known = new Set(previous.tasks.filter(t=>t.pending).map(t=>t.pending.id));
  const added = pending.filter(t=>!known.has(t.pending.id));
  if (added.length) {
    try { const notification = new Notification('Navis needs your response', {body:`${added.length} task${added.length===1?'':'s'} waiting for input or approval.`,tag:'navis-attention'});
      notification.onclick = () => {window.focus();notification.close();};
    } catch (_) { /* Mobile browsers may require a service worker, which this local UI does not install. */ }
  }
}
async function poll() {
  if (polling) return;
  polling = true;
  try {
    const result = await api(`/api/snapshot?cursor=${cursor}`);
    events = [...events,...result.events].slice(-1000); cursor = result.cursor;
    updateAttention(snapshot,result);
    const changed = !snapshot || !connected || JSON.stringify({...result,events:[],cursor:0,latest_cursor:0}) !== JSON.stringify({...snapshot,events:[],cursor:0,latest_cursor:0});
    snapshot = result; connected = true;
    $('#connection-alert').hidden = true; $('#local-connection').textContent = 'Connected';
    $('#pause').disabled = false; $('#new-task').disabled = false;
    $('#add-project').hidden = false; $('#add-project').disabled = false;
    $('#runtime-banner').classList.toggle('real-mode',!simulation());
    $('#runtime-banner').innerHTML = simulation()
      ? '<span class="notice-icon" aria-hidden="true">◌</span><div><strong>Simulation workspace</strong><span>Fake-agent controls only. No repository files are changed.</span></div><span class="notice-badge">SIMULATION / 0.1</span>'
      : '<span class="notice-icon" aria-hidden="true">⌁</span><div><strong>Real runtime</strong><span>Controls and capabilities are provided by the active runner. Verify the task, attempt and diff before approval.</span></div><span class="notice-badge">REAL MODE</span>';
    if (changed || view === 'activity') render();
    if (selectedTask) {
      const summary=result.tasks.find(t=>t.id===selectedTask);
      if (summary && taskDetail?.task?.updated_at===summary.updated_at) updateDetail();
      else await loadTaskDetail(selectedTask);
    }
    updateCountdowns();
  } catch (err) {
    connected = false; $('#local-connection').textContent = 'Disconnected';
    $('#connection-alert').textContent = 'Connection unavailable. Controls are disabled. If Navis restarted, reopen the full launch link from your terminal or ~/.local/state/navis/launch.url.';
    $('#connection-alert').hidden = false;
    ['#pause','#new-task','#add-project'].forEach(s=>$(s).disabled=true);
    $('#task-detail').querySelectorAll('button[data-action],button[data-continue],button[type="submit"]').forEach(b=>b.disabled=true);
    if (!snapshot) $('#content').innerHTML = `<div class="panel">${empty('Connect your local runtime','Run python -m navis and open its full launch link. Browser-session access survives refresh until the runtime restarts.')}</div>`;
  } finally { polling = false; }
}
function empty(title, description, icon='◈') {
  return `<div class="empty-state"><span class="empty-icon" aria-hidden="true">${icon}</span><strong>${escapeHTML(title)}</strong><p>${escapeHTML(description)}</p></div>`;
}
function filteredTasks() {return snapshot.tasks.filter(t=>project==='all'||t.project_id===project);}
function countdown(until) {
  if (!Number.isFinite(until)) return 'Time unavailable';
  const remaining = Math.max(0,Math.ceil(until-Date.now()/1000));
  return remaining ? `${Math.floor(remaining/60)}:${String(remaining%60).padStart(2,'0')} remaining` : 'Awaiting runtime update';
}
function timer(until) {return `<span data-countdown="${Number(until)}">${escapeHTML(countdown(until))}</span>`;}
function updateCountdowns() {
  document.querySelectorAll('[data-countdown]').forEach(el=>el.textContent = connected ? countdown(Number(el.dataset.countdown)) : 'Disconnected / time unconfirmed');
}
function queueHint(task) {
  const reasons = task.queue_reasons || [];
  if (task.state === 'WAITING_QUOTA') return `Cooldown / ${timer(task.due)}`;
  return escapeHTML(reasons.map(r=>r.message).join(' · ') || task.activity || 'Waiting for runtime dispatch');
}
function stats(tasks) {
  const running = tasks.filter(t=>active.includes(t.state)).length;
  const waiting = tasks.filter(t=>['WAITING_INPUT','WAITING_APPROVAL','WAITING_QUOTA','BLOCKED'].includes(t.state)).length;
  return `<div class="stats">
    <div class="stat"><div class="stat-top">Total tasks<span aria-hidden="true">▦</span></div><div class="stat-value">${tasks.length}</div><div class="stat-footer">Across ${project==='all'?snapshot.projects.length:1} project${project==='all'&&snapshot.projects.length!==1?'s':''}</div></div>
    <div class="stat"><div class="stat-top">Active attempts<span aria-hidden="true">◌</span></div><div class="stat-value">${running}</div><div class="stat-footer">${snapshot.paused?'Dispatch paused / active work continues':'See Resources for slot capacity'}</div></div>
    <div class="stat"><div class="stat-top">Needs attention<span aria-hidden="true">◷</span></div><div class="stat-value">${waiting}</div><div class="stat-footer">${waiting?'Input, approval, cooldown or blocked':'Nothing waiting on you'}</div></div>
    <div class="stat"><div class="stat-top">Completed<span aria-hidden="true">✓</span></div><div class="stat-value">${tasks.filter(t=>t.state==='COMPLETED').length}</div><div class="stat-footer">${simulation()?'Simulated verification only':'Runtime verification evidence'}</div></div>
  </div>`;
}
function card(task) {
  return `<button id="card-${escapeHTML(task.id)}" class="task-card" data-task="${escapeHTML(task.id)}"><div class="card-top"><span>NAV-${escapeHTML(shortID(task.id))}</span>${badge(task.state)}</div><h3>${escapeHTML(task.title)}</h3><span class="scope-label">⌁ ${escapeHTML(task.scope.join(', '))}</span>${['QUEUED','WAITING_QUOTA'].includes(task.state)?`<p class="queue-hint">${queueHint(task)}</p>`:''}<div class="card-bottom"><span><span class="agent-avatar" aria-hidden="true">${simulation()?'F':'A'}</span>${escapeHTML(task.backend)}</span><span>${date(task.updated_at)}</span></div></button>`;
}
function board(tasks) {
  const groups = [['Queued',['QUEUED']],['In progress',['RUNNING','VERIFY','REVIEW','CANCELLING']],['Needs attention',['WAITING_INPUT','WAITING_APPROVAL','WAITING_QUOTA','BLOCKED']],['Finished',['COMPLETED','FAILED','CANCELLED']]];
  const visible = tasks.filter(t=>(stateFilter==='all'||t.state===stateFilter)&&`${t.title} ${t.spec} ${t.scope.join(' ')}`.toLowerCase().includes(search.toLowerCase()));
  return `<div class="board">${groups.map(([name,states],i)=>{
    const items = visible.filter(t=>states.includes(t.state));
    return `<section class="column" aria-label="${name}"><div class="column-heading"><span class="column-dot" aria-hidden="true"></span>${name}<span class="column-count">${items.length}</span></div>${items.length?items.slice(0,columnLimits[i]).map(card).join(''):'<div class="empty-column">No tasks here yet</div>'}${items.length>columnLimits[i]?`<button class="column-add" data-more-column="${i}">Show 12 more / ${items.length-columnLimits[i]} remaining</button>`:''}${name==='Queued'?'<button class="column-add" data-new-task>+ Add a task</button>':''}</section>`;
  }).join('')}</div>`;
}
function integrationStrip() {
  if (simulation()) return '';
  return (snapshot.integration||[]).filter(i=>project==='all'||i.project_id===project).map(i=>{
    const checks=i.checks.map(c=>`${escapeHTML(c.name)} ${c.rc?'✗':'✓'}`).join(', ')||'no checks configured';
    const detail=i.busy?`${i.busy==='verify'?'running every check on the merged commit…':`checking the merged commit for task ${escapeHTML(i.busy)}…`}`:`${i.tasks.length} task${i.tasks.length===1?'':'s'} merged at ${escapeHTML((i.commit||'').slice(0,10))} / checks on this exact commit: ${checks}`;
    const why=!i.busy&&!i.can_promote&&i.reason?`<br><small class="muted">${escapeHTML(i.reason)}</small>`:'';
    return `<div class="attention-strip integration-strip"><span aria-hidden="true">⇥</span><span><strong>${escapeHTML(i.project_id)}</strong> integration branch: ${detail}${why}</span><span class="strip-actions">${i.verify_needed&&!i.busy?`<button class="button secondary" data-verify-integration="${escapeHTML(i.project_id)}">Run all checks</button>`:''}${i.review_needed&&!i.busy?`<button class="button secondary" data-review-integration="${escapeHTML(i.project_id)}" ${snapshot.capabilities?.handoff?.claude_review===true?'':'disabled title="Claude is not logged in."'}>Review with Claude</button>`:''}<button class="button secondary" data-discard="${escapeHTML(i.project_id)}" ${i.busy?'disabled':''}>Discard</button><button class="button primary" data-promote="${escapeHTML(i.project_id)}" ${i.can_promote&&!i.busy?'':'disabled'}>Fast-forward ${escapeHTML(i.branch||'branch')} →</button></span></div>`;
  }).join('');
}
function agentRow(name, desc, mark, status, className='', sub='') {
  return `<div class="agent-row"><span class="provider-mark ${className}" aria-hidden="true">${mark}</span><div class="agent-info"><strong>${name}</strong><small>${desc}</small></div><div class="agent-status ${status==='Ready'?'ready':status==='Cooldown'?'cooldown':''}">${status}<span>${sub}</span></div></div>`;
}
function fakeAgentRow() {
  const busy = snapshot.tasks.some(t=>active.includes(t.state));
  const cooldown = snapshot.tasks.filter(t=>t.state==='WAITING_QUOTA'&&t.backend==='fake-agent');
  const until = cooldown.length ? Math.max(...cooldown.map(t=>t.due)) : null;
  return agentRow('Fake agent','In-process simulation / no tools','F',busy?'Busy':cooldown.length?'Cooldown':'Ready','fake',`${busy?'1':'0'} / 1 slots${until?`<br>Task cooldown / ${timer(until)}`:''}`);
}
function agentPanel() {
  return `<section class="panel"><div class="panel-header"><h2>Agent fleet</h2><button class="text-button" data-view="agents">View agents ↗</button></div>${fakeAgentRow()}${agentRow('Codex','CLI adapter / feasibility pending','✳','Not tested','','Disabled')}${agentRow('Claude Code','CLI adapter / feasibility pending','✽','Not tested','','Disabled')}${agentRow('Local LLM','Context summaries and log analysis','⌘','Not connected','','No write / exec tools')}</section>`;
}
function eventList(limit=8, taskFilter='all', typeFilter='all', sourceEvents=events) {
  const relevant = sourceEvents.filter(e=>(project==='all'||e.project_id===project)&&(taskFilter==='all'||e.task_id===taskFilter)&&(typeFilter==='all'||e.type===typeFilter)).slice(-limit).reverse();
  return relevant.length ? `<div class="timeline">${relevant.map(e=>`<div class="event-row"><span class="event-mark" aria-hidden="true">${e.type==='STATE'?'↗':e.type==='CONTROL'?'Ⅱ':'◇'}</span><div class="event-body"><p>${escapeHTML(e.message)}</p><small>${escapeHTML(e.type)} / ${e.task_id?'NAV-'+escapeHTML(shortID(e.task_id)):'Runtime'} / #${e.seq}</small>${e.task_id?`<button class="text-button" data-task="${escapeHTML(e.task_id)}" data-open-output>Open task output ↗</button>`:''}${typeof e.output==='string'?`<details><summary>Full event output</summary><pre>${escapeHTML(e.output)}</pre></details>`:''}</div><span class="event-time">${date(e.time)}</span></div>`).join('')}</div>` : empty('No matching events','Events retained in the current browser session appear here. Earlier events remain in the database.','≋');
}
async function loadTaskDetail(taskID) {
  if (!connected || !taskID) return;
  try {
    const result = await api(`/api/tasks/${encodeURIComponent(taskID)}`);
    if (selectedTask !== taskID) return;
    taskDetail = result; detailSignature = ''; updateDetail();
  } catch (err) {
    if (selectedTask === taskID) toast(`Task evidence unavailable: ${err.message}`);
  }
}
function eventToolbar(tasks) {
  return `<div class="event-toolbar"><label>Task<select id="event-task"><option value="all">All tasks and runtime</option>${tasks.map(t=>`<option value="${escapeHTML(t.id)}" ${eventTask===t.id?'selected':''}>${escapeHTML(t.title)}</option>`).join('')}</select></label><label>Event type<select id="event-type"><option value="all">All event types</option>${[...new Set(events.map(e=>e.type))].sort().map(type=>`<option ${eventType===type?'selected':''}>${escapeHTML(type)}</option>`).join('')}</select></label></div>`;
}
function artifactBlock(artifact, task, expanded=false) {
  return `<details ${expanded?'open':''}><summary>${escapeHTML(artifact.name)} / ${artifact.simulated?'SIMULATED':'RUNTIME EVIDENCE'}</summary><small>Attempt ${escapeHTML(artifact.attempt_id)} / SHA-256 ${escapeHTML(artifact.hash||'not supplied')}</small><pre>${escapeHTML(artifact.content)}</pre><button class="text-button" data-copy-artifact="${escapeHTML(artifact.id)}" data-copy-task="${escapeHTML(task.id)}">Copy full result</button></details>`;
}
function artifacts(tasks) {
  const items = tasks.flatMap(t=>t.artifacts.map(a=>({artifact:a,task:t})));
  return items.length ? `<div class="artifacts">${items.map(({artifact,task})=>`<section class="panel artifact"><button class="text-button" data-task="${escapeHTML(task.id)}">${escapeHTML(task.title)} ↗</button><h3>${escapeHTML(artifact.name)}</h3><small>${escapeHTML(artifact.kind)} / attempt ${escapeHTML(artifact.attempt_id)} / ${escapeHTML(artifact.hash||'hash unavailable')}</small><p class="muted">Full content loads when you open this task.</p><button class="button secondary" data-task="${escapeHTML(task.id)}">Open artifact →</button></section>`).join('')}</div>` : `<section class="panel">${empty('No artifacts yet','Completed steps produce result and verification evidence.','◇')}</section>`;
}
function formatBytes(bytes) {
  if (!Number.isFinite(Number(bytes)) || Number(bytes)<0) return 'Not measured';
  const units=['B','KiB','MiB','GiB']; let value=Number(bytes), index=0;
  while(value>=1024&&index<units.length-1){value/=1024;index++;}
  return `${value.toFixed(index?1:0)} ${units[index]}`;
}
function resourcePanel() {
  const slots = snapshot.resources?.slots || [];
  const attempts = filteredTasks().filter(t=>active.includes(t.state));
  const memoryFor=t=>{const attempt=t.attempts.find(a=>a.id===t.attempt_id);return attempt?.memory_bytes??snapshot.resources?.attempt_memory_bytes?.[t.attempt_id]??null;};
  const sampled=attempts.filter(t=>memoryFor(t)!==null).length;
  return `<section class="panel"><div class="panel-header"><h2>Dispatch capacity</h2><span class="badge">${simulation()?'SIMULATION':'RUNTIME'}</span></div><dl class="settings-list">${slots.map(s=>`<div><dt>${escapeHTML(s.backend)} slots</dt><dd>${escapeHTML(s.used)} / ${escapeHTML(s.limit)}</dd></div>`).join('')||'<div><dt>Slots</dt><dd>Not reported by runtime</dd></div>'}<div><dt>Dispatch</dt><dd>${snapshot.paused?'Paused':'Enabled'}</dd></div><div><dt>Attempt RAM</dt><dd>${sampled} of ${attempts.length} active attempts measured</dd></div></dl><div class="detail-section"><h3>Active attempts</h3>${attempts.length?`<div class="table-scroll"><table class="resource-table"><thead><tr><th scope="col">Task</th><th scope="col">Attempt</th><th scope="col">Agent</th><th scope="col">Memory</th></tr></thead><tbody>${attempts.map(t=>`<tr><td><button class="text-button" data-task="${escapeHTML(t.id)}">${escapeHTML(t.title)}</button></td><td>${escapeHTML(t.attempt_id)}</td><td>${escapeHTML(t.backend)}</td><td>${escapeHTML(formatBytes(memoryFor(t)))}</td></tr>`).join('')}</tbody></table></div>`:empty('No active attempts','Dispatch capacity is available when the runtime is not paused.')}</div><p class="muted">${simulation()?'The fake agent has no separate worker process or per-attempt RAM sample.':'RAM values are shown only when the runtime supplies measured memory_bytes.'}</p></section>`;
}
function settingsPanel() {
  const settings=snapshot.settings;
  if (!settings?.editable || !Array.isArray(settings.items)) return `<section class="panel"><h2>Runtime settings</h2><p class="muted">${simulation()?'The simulation uses one fixed slot.':'Settings are read-only until the runtime exposes editable settings.'}</p><dl class="settings-list">${[['Mode',simulation()?'Simulation only':'Real'],['Transport','Authenticated loopback'],['Remote listener','Disabled'],['Dispatch',snapshot.paused?'Paused':'Enabled']].map(([k,v])=>`<div><dt>${k}</dt><dd>${v}</dd></div>`).join('')}</dl></section>`;
  return `<section class="panel"><h2>Runtime settings</h2><form id="settings-form">${settings.items.map(x=>`<label>${escapeHTML(x.label)}<input name="${escapeHTML(x.key)}" type="${x.type==='number'?'number':'text'}" value="${escapeHTML(x.value)}" ${Number.isFinite(x.min)?`min="${x.min}"`:''} ${Number.isFinite(x.max)?`max="${x.max}"`:''} ${x.required?'required':''}></label>`).join('')}<p class="form-error" role="alert"></p><button class="button primary" type="submit">Save runtime settings</button></form></section>`;
}
function rememberFocus() {
  const element = document.activeElement;
  return {id:element?.id,start:element?.selectionStart,end:element?.selectionEnd};
}
function restoreFocus(saved) {
  if (!saved.id) return;
  const element = document.getElementById(saved.id);
  if (!element) return;
  element.focus({preventScroll:true});
  if (typeof element.setSelectionRange==='function'&&typeof saved.start==='number') element.setSelectionRange(saved.start,saved.end);
}
function render() {
  if (!snapshot) return;
  const focus = rememberFocus();
  $('#page-title').textContent = names[view]; $('#page-subtitle').textContent = subtitles[view]; $('#view-label').textContent = view==='overview'?'Overview':names[view];
  document.querySelectorAll('.sidebar .nav-item').forEach(b=>{b.classList.toggle('active',b.dataset.view===view);if(b.dataset.view===view)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current');});
  $('#pause').textContent = snapshot.paused?'▷ Resume dispatch':'Ⅱ Pause dispatch';
  $('#nav-task-count').textContent = snapshot.tasks.length;
  $('#add-project').hidden = false;
  $('#project-list').innerHTML = `<button id="project-all" class="project-item ${project==='all'?'active':''}" data-project="all"><span class="project-dot" aria-hidden="true"></span><span>All projects</span></button>`+snapshot.projects.map(p=>`<button id="project-${escapeHTML(p.id)}" class="project-item ${project===p.id?'active':''}" data-project="${escapeHTML(p.id)}"><span class="project-dot" aria-hidden="true"></span><span>${escapeHTML(p.name)}</span></button>`).join('');
  const tasks = filteredTasks(); let html = '';
  if (view==='overview'||view==='tasks') {
    html = stats(tasks);
    html += integrationStrip();
    const pending = tasks.filter(t=>t.pending);
    if (pending.length) html += `<div class="attention-strip"><span aria-hidden="true">◷</span><span>${pending.length} task${pending.length===1?'':'s'} waiting for your response</span><button class="text-button" data-task="${escapeHTML(pending[0].id)}">Review request →</button></div>`;
    html += `<div class="section-title"><h2>Task board <small>${project==='all'?'All projects':escapeHTML(snapshot.projects.find(p=>p.id===project)?.name)}</small></h2><button class="text-button" data-new-task>+ Create task</button></div>`;
    if (view==='tasks') html += `<div class="board-toolbar"><input id="task-search" placeholder="Search tasks…" aria-label="Search tasks" value="${escapeHTML(search)}"><select id="state-filter" aria-label="Filter by state"><option value="all">All states</option>${[...new Set(snapshot.tasks.map(t=>t.state))].sort().map(s=>`<option ${s===stateFilter?'selected':''}>${escapeHTML(s)}</option>`).join('')}</select></div>`;
    html += board(tasks);
    if (view==='overview') html += `<div class="lower-grid">${agentPanel()}<section class="panel"><div class="panel-header"><h2>Recent activity</h2><button class="text-button" data-view="activity">View audit log ↗</button></div>${eventList()}</section></div>`;
  } else if (view==='agents') {
    const providers=snapshot.providers||[];
    const providerCard=([name,mark,desc],provider)=>{const until=provider?.cooldown_until;const reported=provider?.status||(until?'Cooldown':'Unavailable');const state=['Ready','Busy','Cooldown','Unavailable','Not tested','Not connected','Error'].includes(reported)?reported:'Unavailable';const slotText=provider?.slot_limit!=null?`${provider.slots_used||0} / ${provider.slot_limit} slots`:provider?.reason||'No runtime status';const sub=`${escapeHTML(slotText)}${until?`<br>${timer(Number(until))}`:''}`;return `<section class="panel agent-card">${agentRow(name,desc,mark,state,state==='Ready'?'ready':state==='Cooldown'?'cooldown':'',sub)}<div class="capability-list"><span class="capability">${escapeHTML(provider?.capability||'Status supplied by runtime')}</span></div><p>${escapeHTML(provider?.message||'Rate-limit state appears here when the runtime reports a provider cooldown.')}</p></section>`;};
    html = `<div class="agent-grid"><section class="panel agent-card">${fakeAgentRow()}<div class="capability-list"><span class="capability">Lifecycle simulation</span><span class="capability">Task cooldown</span><span class="capability">Source artifact references</span></div><p>Controls run in-process. A task cooldown releases the slot; it does not imply the whole fake provider is blocked.</p></section>${[['Codex','✳','Provider CLI/session'],['Claude Code','✽','Provider CLI/session'],['Local LLM','⌘','Text summaries and log analysis']].map((entry,i)=>{const key=['codex','claude','local'][i], provider=providers.find(p=>p.id===key||p.name?.toLowerCase().replace(/ code/,'').replace(/ llm/,'')===entry[0].toLowerCase());return providerCard(entry,provider);}).join('')}</div>`;
  } else if (view==='activity') html = `<section class="panel event-log"><div class="panel-header"><h2>Runtime events</h2><span class="muted">Cursor ${cursor} / latest 1,000 retained in this tab</span></div>${eventToolbar(tasks)}${eventList(eventLimit,eventTask,eventType)}${eventLimit<1000?'<button class="text-button" id="more-events">Show more events</button>':''}</section>`;
  else if (view==='artifacts') html = artifacts(tasks);
  else if (view==='resources') html = resourcePanel();
  else html = settingsPanel();
  $('#content').innerHTML = html; restoreFocus(focus); updateAttention(null,snapshot); updateCountdowns();
}
function populateSources(selected='') {
  const projectID = $('#task-project').value;
  $('#task-source').innerHTML = '<option value="">New task / no source</option>'+snapshot.tasks.filter(t=>t.project_id===projectID&&t.state==='COMPLETED').map(t=>`<option value="${escapeHTML(t.id)}" data-attempt="${escapeHTML(t.attempt_id)}" ${t.id===selected?'selected':''}>${escapeHTML(t.title)} / ${escapeHTML(shortID(t.attempt_id))}</option>`).join('');
}
function openTaskForm(source=null) {
  $('#task-form').reset(); $('#task-form .form-error').textContent = '';
  const agentSelect = $('#task-agent'), isReal = !simulation();
  agentSelect.disabled = !isReal; agentSelect.name = isReal ? 'agent' : '';
  if (isReal) agentSelect.innerHTML = (snapshot.providers||[]).map(p=>`<option value="${escapeHTML(p.id)}" ${p.ok?'':'disabled'}>${escapeHTML(p.name)}${p.ok?'':` (${escapeHTML((p.reason||'unavailable').toLowerCase())})`}</option>`).join('');
  $('#task-scenario').closest('label').hidden = isReal;
  $('#create-description').textContent = isReal ? 'The agent works in a sandboxed clone of the project; your checkout is never touched.' : 'This task runs against a simulated agent. It cannot access your repository.';
  $('#source-description').textContent = isReal ? 'The new task starts from the result commit of that task (its refs/navis/attempts/* ref).' : 'Source artifacts are copied as a simulation context reference; no Git branch is created.';
  $('#task-project').innerHTML = snapshot.projects.map(p=>`<option value="${escapeHTML(p.id)}" ${(source?.project_id||project)===p.id?'selected':''}>${escapeHTML(p.name)}</option>`).join('');
  populateSources(source?.id||'');
  if (source) {$('#task-title').value = `Continue: ${source.title}`.slice(0,120);$('#task-spec').value = `Continue the work from “${source.title}”.\n\nDescribe the next outcome and acceptance criteria.`;$('#task-scope').value = source.scope.join(', ');}
  $('#task-dialog').showModal();
}
function renderDiff(task) {
  const patches = task.artifacts.filter(a=>a.kind==='diff');
  if (!patches.length) return empty('No Git diff is available',simulation()?'This simulation does not read or edit a repository. A real runner must supply a commit-bound patch and per-file policy classification.':'The runtime has not supplied a patch. A file-stat summary cannot substitute for reviewing code.','⌁');
  return patches.map(a=>`<section><small>Attempt ${escapeHTML(a.attempt_id)} / ${a.simulated?'SIMULATED PATCH':'RUNTIME PATCH'} / SHA-256 ${escapeHTML(a.hash||'not supplied')}</small>${(a.files||[]).map(f=>`<div class="file-row"><code>${escapeHTML(f.path)}</code><span class="badge">${f.out_of_scope===true?'OUT OF SCOPE':f.out_of_scope===false?'IN SCOPE':'SCOPE NOT CLASSIFIED'}</span><span class="badge">${f.protected===true?'PROTECTED':f.protected===false?'NOT PROTECTED':'PROTECTION NOT CLASSIFIED'}</span></div>`).join('')}<pre aria-label="Full code diff">${String(a.content||'').split('\n').map(line=>`<span class="diff-line ${line.startsWith('diff ')||line.startsWith('@@')?'diff-header':line.startsWith('+')?'diff-add':line.startsWith('-')?'diff-remove':''}">${escapeHTML(line)}</span>`).join('')}</pre><button class="text-button" data-copy-artifact="${escapeHTML(a.id)}" data-copy-task="${escapeHTML(task.id)}">Copy full patch</button></section>`).join('');
}
function detailPanel(task) {
  if (detailTab==='diff') return renderDiff(task);
  if (detailTab==='log') {
    const logs = task.artifacts.filter(a=>a.kind==='agent_log');
    return (logs.length ? logs.map(a=>artifactBlock(a,task,true)).join('') : empty('Agent output is unavailable','There is no real agent.log in this version. Runtime event output is shown below.','≋'))+eventList(1000,task.id,'all',taskDetail?.events||events);
  }
  if (detailTab==='prompt') {
    const prompts = task.artifacts.filter(a=>a.kind==='prompt');
    return prompts.length ? prompts.map(a=>artifactBlock(a,task,true)).join('') : `${empty('No provider prompt was sent','These are the task instructions saved in Navis. They are not a prompt delivered to a model.')}<pre>${escapeHTML(task.spec)}</pre>${task.instructions.map(i=>`<pre>Instruction v${i.version}\n${escapeHTML(i.text)}</pre>`).join('')}`;
  }
  if (detailTab==='attempts') return task.attempts.map(a=>`<div class="detail-section"><small>${escapeHTML(a.id)} / ${date(a.started_at)} / ${escapeHTML(a.backend)}</small>${badge(a.state||'RUNNING')}</div>`).join('') || empty('Waiting for dispatch','No attempt has started yet.');
  return task.artifacts.filter(a=>!['diff','agent_log','prompt'].includes(a.kind)).map(a=>artifactBlock(a,task,true)).join('') || empty('No results yet','Result and verification evidence will appear here after a simulated step.','◇');
}
function updateDetail(force=false) {
  const task = currentTask(); if (!task) return;
  const signature = JSON.stringify([task,detailTab,connected,events.length]);
  if (!force&&signature===detailSignature) return;
  const focus = rememberFocus();
  const saved = {}; $('#task-detail').querySelectorAll('textarea').forEach(el=>saved[el.name]=el.value);
  const disclosureState = [...$('#task-detail').querySelectorAll('details')].map(el=>el.open);
  detailSignature = signature;
  const controls = [];
  const gracefulStop=simulation()||snapshot.capabilities?.controls?.graceful_stop===true;
  if (!terminal.includes(task.state)) {
    if (gracefulStop) controls.push('<button class="button secondary" data-action="stop">■ Stop gracefully</button>');
    else if (active.includes(task.state)) controls.push('<button class="button danger" data-action="kill">Terminate attempt</button>');
    else controls.push('<button class="button secondary" data-action="stop">Cancel queued task</button>');
  }
  if (active.includes(task.state)&&gracefulStop) controls.push(`<button class="button danger" data-action="kill">${simulation()?'Kill simulation':'Force kill process tree'}</button>`);
  if (['FAILED','CANCELLED','BLOCKED'].includes(task.state)) controls.push('<button class="button primary" data-action="retry">↻ Retry as new attempt</button>');
  if (task.state==='COMPLETED') {
    controls.push(`<button class="button primary" data-continue="${escapeHTML(task.id)}">Continue from this task →</button>`);
    const handoff=snapshot.capabilities?.handoff||{};
    controls.push(`<button class="button secondary" data-action="review_with_claude" ${handoff.claude_review===true?'':'disabled title="Claude review is unavailable until the runtime reports a logged-in adapter."'}>Review with Claude</button>`);
    controls.push(`<button class="button secondary" data-action="continue_with_codex" ${handoff.codex_continue===true?'':'disabled title="Codex continuation is unavailable until the runtime reports a logged-in adapter."'}>Continue with Codex</button>`);
  }
  if (!simulation()&&task.state==='COMPLETED'&&typeof task.result_ref==='string'&&/^refs\/navis\/attempts\/[a-zA-Z0-9][a-zA-Z0-9._/-]*$/.test(task.result_ref)&&!task.result_ref.includes('..')) controls.push('<button class="button secondary" data-copy-merge>Copy merge command</button>');
  if (!simulation()&&task.state==='COMPLETED'&&task.head&&task.kind!=='review') controls.push('<button class="button primary" data-action="integrate" title="Merge this result into the Navis integration branch and run the checks on the merged commit. Your branch is not touched.">Add to integration branch</button>');
  const latestReview = (task.reviews||[])[0];
  if (!simulation()&&task.state==='COMPLETED'&&task.kind!=='review'&&latestReview&&latestReview.verdict==='changes'&&!latestReview.stale) controls.push('<button class="button primary" data-action="revise" title="Queue a bounded follow-up round that starts from this result and carries the reviewer findings.">Revise from review</button>');
  let request = '';
  if (task.pending) request = `<section class="request-box"><h3>${task.state==='WAITING_APPROVAL'?'Approval required':'Your input is needed'}</h3><p>${escapeHTML(task.pending.message)}</p><small>Expires at ${date(task.pending.expires)} / bound to the displayed attempt</small>${task.state==='WAITING_APPROVAL'?`<div class="detail-actions"><button class="button primary" data-action="approve">${simulation()?'Approve simulation':'Approve request'}</button><button class="button danger" data-action="reject">Reject</button></div>`:'<form id="answer-form"><label>Your answer<textarea id="task-answer" name="answer" required maxlength="2000" rows="2"></textarea></label><button class="button primary" type="submit">Send answer →</button></form>'}</section>`;
  else if (task.state==='REVIEW') request = `<section class="request-box"><h3>Approve reviewed attempt</h3><p>The runner has not supplied a separate approval question. Review the diff and verification evidence above before approving.</p><div class="detail-actions"><button class="button primary" data-action="approve">Approve attempt</button><button class="button danger" data-action="reject">Reject attempt</button></div></section>`;
  else if (task.state==='WAITING_INPUT') request = `<section class="request-box"><h3>Waiting for your input</h3><p>The runtime has not supplied the input prompt yet. Refresh the task details or inspect its event output.</p><button class="text-button" data-open-output data-task="${escapeHTML(task.id)}">Open task output ↗</button></section>`;
  const reviewItems = (task.reviews||[]).map(r=>`<li><strong>${r.verdict==='approve'?'Approved':'Changes requested'}</strong> by ${escapeHTML(r.reviewer)}${r.reviewer===r.implementer?' (same agent as the implementer)':''}${r.stale?' / reviewed an older result, not this commit':''}<br><span class="muted">${String(r.summary||'').split('\n').map(escapeHTML).join('<br>')}</span></li>`).join('');
  const reviewBlock = (reviewItems||task.round) ? `<section class="detail-section"><h3>Reviews</h3>${task.round?`<p class="muted">Revision round ${task.round}</p>`:''}<ul class="queue-reasons">${reviewItems}</ul></section>` : '';
  const reasons = task.queue_reasons || [];
  const tabLabels=[['results','Results'],['diff','Code diff'],['log','Agent output'],['prompt','Prompt / instructions'],['attempts','Attempts']];
  const activeLabel=tabLabels.find(([id])=>id===detailTab)?.[1]||'Results';
  $('#task-detail').innerHTML = `<div class="dialog-heading"><div><span class="eyebrow">NAV-${escapeHTML(shortID(task.id))} / ${simulation()?'SIMULATION':'RUNTIME'}</span><h2 id="detail-title">${escapeHTML(task.title)}</h2></div><button class="icon-button" data-close="detail-dialog" aria-label="Close task details">×</button></div><div class="detail-meta">${badge(task.state)}<span class="muted">${escapeHTML(task.backend)}</span></div>${task.state==='REVIEW'?'<div class="review-callout"><strong>Review required</strong><span>Inspect the complete diff, file policy labels and verification evidence before approving this attempt.</span></div>':''}<p class="detail-description">${escapeHTML(task.spec)}</p><div class="detail-fields"><div><span>Scope</span>${escapeHTML(task.scope.join(', '))}</div><div><span>Current attempt</span>${escapeHTML(task.attempt_id||'Not dispatched')}</div><div><span>Attempts</span>${task.attempts.length}</div>${simulation()?`<div><span>Scenario</span>${escapeHTML(task.scenario)}</div>`:`<div><span>Result commit</span>${escapeHTML((task.head||'none').slice(0,12))}</div>`}</div><p class="muted">${escapeHTML(task.activity)}</p>${reasons.length?`<ul class="queue-reasons">${reasons.map(r=>`<li>${escapeHTML(r.message)}${r.until?` / ${timer(r.until)}`:''}${r.task_id?`<button class="text-button" data-task="${escapeHTML(r.task_id)}">Open blocking task ↗</button>`:''}</li>`).join('')}</ul>`:''}${task.source?`<div class="detail-section"><h3>Source task</h3><button class="text-button" data-task="${escapeHTML(task.source.task_id)}">${escapeHTML(task.source.title)} ↗</button><small>Attempt ${escapeHTML(task.source.attempt_id)} / ${task.source.artifacts.length} saved artifact references</small></div>`:''}${request}${reviewBlock}<div class="detail-actions">${controls.join('')}</div><div class="detail-tabs" role="tablist" aria-label="Task evidence">${tabLabels.map(([id,label])=>`<button type="button" id="detail-tab-${id}" role="tab" class="detail-tab" data-detail-tab="${id}" aria-selected="${detailTab===id}" aria-controls="detail-evidence" tabindex="${detailTab===id?'0':'-1'}">${label}</button>`).join('')}</div><section id="detail-evidence" role="tabpanel" tabindex="0" aria-labelledby="detail-tab-${detailTab}" aria-label="${escapeHTML(activeLabel)}" aria-busy="${!taskDetail}">${!taskDetail?empty('Loading task evidence','Only the selected task’s full diff, log, prompt and artifacts are being loaded.'):detailPanel(task)}</section>${!terminal.includes(task.state)&&task.state!=='CANCELLING'?'<section class="detail-section"><h3>Add an instruction</h3><form id="instruction-form"><label>Versioned guidance for the next step<textarea id="task-instruction" name="instruction" rows="2" required maxlength="2000"></textarea></label><button class="button secondary" type="submit">Save instruction</button></form></section>':''}`;
  $('#task-detail').querySelectorAll('textarea').forEach(el=>{if(saved[el.name])el.value=saved[el.name];});
  if (!force) $('#task-detail').querySelectorAll('details').forEach((el,i)=>{if(i<disclosureState.length)el.open=disclosureState[i];});
  if (!connected) $('#task-detail').querySelectorAll('button[data-action],button[data-continue],button[type="submit"]').forEach(b=>b.disabled=true);
  restoreFocus(focus); updateCountdowns();
}
function taskCommand(action, extra={}) {
  const task = currentTask(); if (!task) return Promise.resolve(null);
  return command({action,task_id:task.id,attempt_id:task.attempt_id,...extra});
}
function confirmControl(action, task, info) {
  if (confirmPending) return Promise.resolve(false);
  confirmPending = true;
  const dialog = $('#confirm-dialog'); dialog.returnValue = '';
  if (action==='promote'||action==='discard') {
    const discard = action==='discard';
    $('#confirm-title').textContent = discard ? 'Discard the integration branch?' : 'Fast-forward your branch?';
    $('#confirm-description').textContent = discard ? 'Drops the Navis integration branch. Completed tasks stay completed and can be integrated again; your branch is not touched.' : `Moves ${info.branch} to the integration commit. Your working tree is checked first, no repository hooks run and nothing is pushed.`;
    $('#confirm-attempt').textContent = `${task.title} / commit ${task.attempt_id}`;
    $('#confirm-control').textContent = discard ? 'Confirm discard' : 'Confirm fast-forward';
    return new Promise(resolve=>{dialog.addEventListener('close',()=>{confirmPending=false;resolve(dialog.returnValue==='confirm');},{once:true});dialog.showModal();});
  }
  $('#confirm-title').textContent = action==='kill'?'Kill this attempt?':'Stop this task?';
  $('#confirm-description').textContent = action==='kill' ? (simulation()?'Immediately revoke this simulated attempt. There is no operating-system process to kill.':'Immediately terminate the entire attempt process tree. Uncommitted work may be lost.') : 'Request cancellation of this task. Active work waits for acknowledgement; queued work is cancelled before dispatch.';
  $('#confirm-attempt').textContent = `${task.title} / attempt ${task.attempt_id||'not dispatched'}`;
  $('#confirm-control').textContent = action==='kill'?'Confirm kill':'Confirm stop';
  return new Promise(resolve=>{dialog.addEventListener('close',()=>{confirmPending=false;resolve(dialog.returnValue==='confirm');},{once:true});dialog.showModal();});
}
async function copyText(text) {
  try { if (!navigator.clipboard?.writeText) throw new Error('Clipboard unavailable'); await navigator.clipboard.writeText(text);toast('Copied full text.'); }
  catch (_) { $('#copy-text').value=text;$('#copy-dialog').showModal();$('#copy-text').select(); }
}
document.addEventListener('click',async e=>{
  const close = e.target.closest('[data-close]'); if (close) {document.getElementById(close.dataset.close).close();return;}
  const nav = e.target.closest('[data-view]'); if (nav) {view=nav.dataset.view;search='';stateFilter='all';render();return;}
  const proj = e.target.closest('[data-project]'); if (proj) {project=proj.dataset.project;eventTask='all';render();return;}
  const more = e.target.closest('[data-more-column]'); if (more) {columnLimits[Number(more.dataset.moreColumn)]+=12;render();return;}
  if (e.target.closest('#more-events')) {eventLimit=Math.min(1000,eventLimit+100);render();return;}
  const tab = e.target.closest('[data-detail-tab]'); if (tab) {detailTab=tab.dataset.detailTab;updateDetail(true);return;}
  const copy = e.target.closest('[data-copy-artifact]'); if (copy) {const task=taskDetail?.task?.id===copy.dataset.copyTask?taskDetail.task:snapshot.tasks.find(t=>t.id===copy.dataset.copyTask);const artifact=task?.artifacts.find(a=>a.id===copy.dataset.copyArtifact);if(artifact?.content!==undefined)await copyText(artifact.content);return;}
  if(e.target.closest('[data-copy-merge]')) {const task=currentTask();if(task&&typeof task.result_ref==='string'&&/^refs\/navis\/attempts\/[a-zA-Z0-9][a-zA-Z0-9._/-]*$/.test(task.result_ref)&&!task.result_ref.includes('..'))await copyText(`git merge -- ${task.result_ref}`);return;}
  const follow = e.target.closest('[data-continue]'); if (follow) {const source=snapshot.tasks.find(t=>t.id===follow.dataset.continue);if(connected&&source){$('#detail-dialog').close();openTaskForm(source);}return;}
  if (e.target.closest('[data-new-task]')||e.target.closest('#new-task')) {if(connected)openTaskForm();return;}
  const taskButton = e.target.closest('[data-task]'); if (taskButton) {selectedTask=taskButton.dataset.task;taskDetail=null;const summary=snapshot.tasks.find(t=>t.id===selectedTask);detailTab=taskButton.hasAttribute('data-open-output')?'log':summary?.state==='REVIEW'?'diff':'results';detailSignature='';updateDetail(true);if(!$('#detail-dialog').open)$('#detail-dialog').showModal();await loadTaskDetail(selectedTask);return;}
  const control = e.target.closest('[data-action]');
  if (control) {
    const task = currentTask(); if (!task||!connected) return;
    const action = control.dataset.action;
    const captured = {task_id:task.id,attempt_id:task.attempt_id,pending_id:task.pending?.id};
    if (['stop','kill'].includes(action)&&!await confirmControl(action,task)) return;
    control.disabled = true;
    const result = await command({action,...captured});
    if (result) toast(result.message||(result.task_id&&action==='revise'?(result.duplicate?'That revision is already queued.':`Revision queued as task ${result.task_id}.`):result.expired?'Request expired; task blocked.':'Control accepted by runtime.'));
    control.disabled = false;
  }
  const promo = e.target.closest('[data-promote]'); if (promo) {
    if (!connected||promo.disabled) return;
    const i=(snapshot.integration||[]).find(x=>x.project_id===promo.dataset.promote); if (!i) return;
    if (!await confirmControl('promote',{title:`${i.project_id}: ${i.tasks.length} task${i.tasks.length===1?'':'s'}`,attempt_id:(i.commit||'').slice(0,10)},i)) return;
    promo.disabled=true;
    const result=await command({action:'promote_integration',project_id:i.project_id,commit:i.commit});
    if (result) toast(result.message||'Branch fast-forwarded.');
    promo.disabled=false; return;
  }
  const discardBtn = e.target.closest('[data-discard]'); if (discardBtn) {
    if (!connected||discardBtn.disabled) return;
    const i=(snapshot.integration||[]).find(x=>x.project_id===discardBtn.dataset.discard); if (!i) return;
    if (!await confirmControl('discard',{title:`${i.project_id}: ${i.tasks.length} task${i.tasks.length===1?'':'s'}`,attempt_id:(i.commit||'').slice(0,10)},i)) return;
    discardBtn.disabled=true;
    const result=await command({action:'discard_integration',project_id:i.project_id,commit:i.commit});
    if (result) toast(result.message||'Integration branch discarded.');
    discardBtn.disabled=false; return;
  }
  const verifyInt = e.target.closest('[data-verify-integration]'); if (verifyInt) {
    if (!connected||verifyInt.disabled) return;
    verifyInt.disabled=true;
    const result=await command({action:'verify_integration',project_id:verifyInt.dataset.verifyIntegration});
    if (result) toast(result.message||'Running every check.');
    verifyInt.disabled=false; return;
  }
  const reviewInt = e.target.closest('[data-review-integration]'); if (reviewInt) {
    if (!connected||reviewInt.disabled) return;
    reviewInt.disabled=true;
    const result=await command({action:'review_integration',project_id:reviewInt.dataset.reviewIntegration,agent:'claude'});
    if (result) toast(result.duplicate?'A matching review is already queued.':'Review queued; the verdict appears here when it finishes.');
    reviewInt.disabled=false; return;
  }
});
$('#detail-dialog').addEventListener('close',()=>{selectedTask=null;taskDetail=null;detailSignature='';});
$('#add-project').onclick = ()=>{if(!connected)return;$('#project-form').reset();$('#project-form .form-error').textContent='';$('#project-description').textContent=simulation()?'Creates a simulation-only project.':'Add a project through the active runtime. Repository access is granted only by that runtime.';$('#project-path-field').hidden=simulation();$('#project-dialog').showModal();};
$('#refresh').onclick = ()=>poll();
$('#pause').onclick = async ()=>{if(!snapshot)return;const result=await command({action:snapshot.paused?'resume':'pause'});if(result)toast(snapshot.paused?'Dispatch paused. Active attempts continue.':'Dispatch resumed.');};
$('#notifications').hidden = !('Notification' in window);
$('#notifications').onclick = async ()=>{
  if (!('Notification' in window)) return;
  try {const permission=await Notification.requestPermission();toast(permission==='granted'?'Notifications enabled while this page stays open.':'Notifications unavailable. The tab title still shows waiting tasks.');}
  catch (_) {toast('Notifications unavailable in this browser.');}
};
$('#task-project').onchange = ()=>populateSources();
$('#task-form').onsubmit = async e=>{
  e.preventDefault();if(!connected)return;
  const form=e.currentTarget, button=form.querySelector('[type="submit"]');button.disabled=true;
  const fields=Object.fromEntries(new FormData(form));
  if(fields.source_task_id)fields.source_attempt_id=$('#task-source').selectedOptions[0]?.dataset.attempt;
  try {const result=await api('/api/command',{action:'create_task',...fields});$('#task-dialog').close();await poll();toast(result.duplicate?'Matching task already exists; opening it.':simulation()?'Task queued for simulation.':'Task queued.');selectedTask=result.task_id;taskDetail=null;detailTab='results';updateDetail(true);$('#detail-dialog').showModal();await loadTaskDetail(selectedTask);}
  catch(err){form.querySelector('.form-error').textContent=err.message;}finally{button.disabled=false;}
};
$('#project-form').onsubmit = async e=>{
  e.preventDefault();if(!connected)return;
  const form=e.currentTarget,button=form.querySelector('[type="submit"]');button.disabled=true;
  try{const fields=Object.fromEntries(new FormData(form));const result=await api('/api/command',{action:'create_project',...fields});project=result.id;$('#project-dialog').close();await poll();toast(simulation()?'Simulation project added.':'Project added by runtime.');}
  catch(err){form.querySelector('.form-error').textContent=err.message;}finally{button.disabled=false;}
};
$('#content').addEventListener('submit',async e=>{
  if(e.target.id!=='settings-form')return;
  e.preventDefault();if(!connected)return;
  const form=e.target,button=form.querySelector('[type="submit"]');button.disabled=true;
  try{await api('/api/command',{action:'update_settings',values:Object.fromEntries(new FormData(form))});await poll();toast('Runtime settings saved.');}
  catch(err){form.querySelector('.form-error').textContent=err.message;}
  finally{button.disabled=false;}
});
$('#task-detail').addEventListener('submit',async e=>{
  e.preventDefault();const form=e.target,button=form.querySelector('[type="submit"]');if(!button)return;
  button.disabled=true;const task=currentTask();if(!task)return;
  const result=await taskCommand(form.id==='answer-form'?'answer':'instruction',{text:new FormData(form).get(form.id==='answer-form'?'answer':'instruction'),pending_id:task.pending?.id});
  if(result){toast('Saved for this attempt.');form.reset();}button.disabled=false;
});
$('#content').addEventListener('input',e=>{if(e.target.id==='task-search'){search=e.target.value;render();}});
$('#content').addEventListener('change',e=>{
  if(e.target.id==='state-filter')stateFilter=e.target.value;
  else if(e.target.id==='event-task')eventTask=e.target.value;
  else if(e.target.id==='event-type')eventType=e.target.value;
  else return;render();
});
$('#task-detail').addEventListener('keydown',e=>{
  if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key)||!e.target.matches('[role="tab"]'))return;
  const tabs=[...$('#task-detail').querySelectorAll('[role="tab"]')],index=tabs.indexOf(e.target);
  const next=e.key==='Home'?0:e.key==='End'?tabs.length-1:(index+(e.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length;
  e.preventDefault();tabs[next].focus();tabs[next].click();
});
async function start() {
  if(token) {try{await api('/api/session',{});token='';}catch(_){/* Bearer fallback if an older server does not support sessions. */}}
  await poll();setInterval(poll,1500);setInterval(updateCountdowns,1000);
}
start();
