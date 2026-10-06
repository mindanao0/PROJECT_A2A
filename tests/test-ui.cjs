/* Pure rendering/control checks; no browser or localhost access. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const nodes = new Map();
const listeners = new Map();
const node = selector => {
  if (!nodes.has(selector)) nodes.set(selector,{hidden:false,textContent:'',dataset:{},addEventListener(){},querySelectorAll(){return[];},close(){},showModal(){}});
  return nodes.get(selector);
};
const context = vm.createContext({document:{querySelector:node,querySelectorAll:()=>[],addEventListener(type,callback){listeners.set(type,callback);},title:'',hidden:false},
  window:{},location:{hash:'',pathname:'/'},history:{replaceState(){}},URLSearchParams,Date,console,setTimeout(){return 0;},clearTimeout,setInterval(){},navigator:{},
  FormData: class {constructor(form){this.form=form;}*[Symbol.iterator](){yield* Object.entries(this.form.fields);}}});
let source = fs.readFileSync('navis/web/app.js','utf8');
assert(source.endsWith('start();\n'));
source = source.slice(0,-'start();\n'.length);
vm.runInContext(source,context);
vm.runInContext(`
snapshot={mode:'simulation',paused:false,projects:[],tasks:[]};
globalThis.renderers={renderDiff,queueHint,artifactBlock,detailPanel,updateAttention,countdown};
`,context);
const fixture = {id:'task-safe',state:'COMPLETED',spec:'<script>prompt</script>',instructions:[],artifacts:[{
  id:'artifact-safe',name:'<img src=x onerror=alert(1)>',kind:'diff',attempt_id:'attempt-safe',hash:'abc',simulated:false,
  files:[{path:'src/<script>.py',out_of_scope:true,protected:true}],
  content:'diff --git a/test b/test\n+<script>alert(1)</script>\n-removed line\n'+'long result '.repeat(1000)
}]};
const patch = context.renderers.renderDiff(fixture);
assert(!patch.includes('<script>'));
assert(patch.includes('&lt;script&gt;'));
assert(patch.includes('OUT OF SCOPE'));
assert(patch.includes('PROTECTED'));
assert(patch.includes('long result '.repeat(1000)),'Full patch must remain available');
const result = context.renderers.artifactBlock(fixture.artifacts[0],fixture,true);
assert(!result.includes('<img'));
assert(result.includes('Copy full result'));
const hint = context.renderers.queueHint({state:'QUEUED',queue_reasons:[{message:'Scope held by <img>'}]});
assert(!hint.includes('<img>'));
assert(hint.includes('&lt;img&gt;'));
vm.runInContext(`detailTab='prompt';`,context);
const prompt = context.renderers.detailPanel({...fixture,artifacts:[]});
assert(prompt.includes('No provider prompt was sent'));
assert(!prompt.includes('<script>'));
context.renderers.updateAttention(null,{tasks:[{pending:{id:'request'}}]});
assert(context.document.title.includes('(1 waiting)'));
assert.equal(context.renderers.countdown(0),'Awaiting runtime update');
assert(!source.includes('localStorage'));
async function controls() {
  vm.runInContext(`
    connected=true;selectedTask='task-control';
    snapshot={tasks:[{id:'task-control',attempt_id:'old-attempt'}]};
    globalThis.controls=[];
    command=async body=>{controls.push(body);return {ok:true};};
    confirmControl=()=>new Promise(resolve=>{globalThis.confirmResolve=resolve;});
  `,context);
  const button={dataset:{action:'kill'},disabled:false};
  const click={target:{closest(selector){return selector==='[data-action]'?button:null;}}};
  const waiting=listeners.get('click')(click);
  vm.runInContext("snapshot.tasks[0].attempt_id='replacement-attempt';confirmResolve(true);",context);
  await waiting;
  assert.equal(context.controls[0].attempt_id,'old-attempt','Confirmation must not target a replacement attempt');
  const cancelled=listeners.get('click')(click);
  vm.runInContext('confirmResolve(false);',context);
  await cancelled;
  assert.equal(context.controls.length,1,'Cancelled confirmation must not send a command');

  vm.runInContext(`
    globalThis.submissions=[];
    api=async(path,body)=>{submissions.push(body);return {task_id:'new-task'};};
    poll=async()=>{};updateDetail=()=>{};
    snapshot={tasks:[{id:'source-task',attempt_id:'replacement-source'}]};
  `,context);
  node('#task-source').selectedOptions=[{dataset:{attempt:'displayed-source'}}];
  const form={fields:{source_task_id:'source-task'},querySelector(){return node('submit');}};
  await node('#task-form').onsubmit({preventDefault(){},currentTarget:form});
  assert.equal(context.submissions[0].source_attempt_id,'displayed-source','Source must bind to the displayed option rather than the latest snapshot');
}
controls().then(()=>console.log('UI checks passed: full patch/result escaping, policy labels, queue escaping, prompt distinction, attention title, confirmation cancellation/stale attempts, displayed source attempt.')).catch(error=>{console.error(error);process.exitCode=1;});
