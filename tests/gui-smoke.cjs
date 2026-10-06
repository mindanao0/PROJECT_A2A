/* Optional browser integration checks. Install Playwright outside the repository:
 * npm install --prefix /tmp/navis-browser-check playwright
 * NODE_PATH=/tmp/navis-browser-check/node_modules node tests/gui-smoke.cjs
 * npx --prefix /tmp/navis-browser-check playwright install chromium
 */
const { chromium } = require('playwright');
const { spawn } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const assert = require('node:assert/strict');
const wait = ms => new Promise(r => setTimeout(r, ms));
(async () => {
  const folder = fs.mkdtempSync(path.join(os.tmpdir(), 'navis-gui-'));
  const server = spawn(process.env.PYTHON || 'python3', ['-m','navis','--no-browser','--state-dir',folder], {stdio:'ignore'});
  let browser;
  try {
    for (let i=0;i<100&&!fs.existsSync(path.join(folder,'launch.url'));i++) await wait(100);
    const url=fs.readFileSync(path.join(folder,'launch.url'),'utf8').trim();
    const base=url.split('/#')[0], token=new URL(url).hash.split('token=')[1];
    browser=await chromium.launch({headless:true});
    const page=await browser.newPage({viewport:{width:1440,height:1050}});
    const errors=[]; page.on('pageerror',e=>errors.push(e.message));
    await page.goto(url);
    await page.getByText('Nothing waiting on you').waitFor();
    assert(!page.url().includes('token='),'Token must be removed from address bar');
    await page.reload();
    await page.getByText('Nothing waiting on you').waitFor();
    async function create(title,scenario) {
      await page.getByRole('button',{name:'+ New task',exact:true}).click();
      await page.getByLabel('Task title',{exact:true}).fill(title);
      await page.getByLabel('Task description',{exact:true}).fill('Acceptance criteria for '+title);
      await page.getByLabel('Simulation scenario',{exact:true}).selectOption(scenario);
      await page.getByRole('button',{name:'Create task →',exact:true}).click();
      await page.locator('#detail-dialog[open]').waitFor();
    }
    await create('Approval lifecycle', 'approval');
    await page.getByRole('button',{name:'Approve simulation',exact:true}).waitFor();
    await page.getByRole('button',{name:'Approve simulation',exact:true}).click();
    await page.locator('#task-detail .badge.completed').waitFor();
    await page.locator('#detail-dialog').getByRole('button',{name:'Close',exact:true}).click();
    await create('Input lifecycle', 'input');
    await page.getByLabel('Your answer',{exact:true}).fill('Test the control contract');
    await page.getByRole('button',{name:'Send answer →',exact:true}).click();
    await page.locator('#task-detail .badge.completed').waitFor();
    await page.locator('#detail-dialog').getByRole('button',{name:'Close',exact:true}).click();
    await create('Interrupt lifecycle','hang');
    await page.getByRole('button',{name:'Kill simulation',exact:true}).waitFor();
    await page.getByRole('button',{name:'■ Stop',exact:true}).click();
    await page.locator('#confirm-dialog').getByRole('button',{name:'Keep task',exact:true}).click();
    assert.equal(await page.locator('#task-detail .badge.running').count(),1,'Cancelled confirmation must keep the task running');
    await page.getByRole('button',{name:'■ Stop',exact:true}).click();
    await page.locator('#confirm-dialog').getByRole('button',{name:'Confirm stop',exact:true}).click();
    await page.locator('#task-detail .badge.cancelled').waitFor();
    await page.getByRole('button',{name:'↻ Retry as new attempt',exact:true}).click();
    await page.getByRole('button',{name:'Kill simulation',exact:true}).waitFor();
    await page.getByRole('button',{name:'Kill simulation',exact:true}).click();
    await page.locator('#confirm-dialog').getByRole('button',{name:'Confirm kill',exact:true}).click();
    await page.locator('#task-detail .badge.cancelled').waitFor();
    await page.locator('#detail-dialog').getByRole('button',{name:'Close',exact:true}).click();
    await page.locator('.sidebar').getByRole('button',{name:'Artifacts',exact:true}).click();
    assert.equal(await page.locator('.artifact').count(),4);
    await page.locator('.sidebar').getByRole('button',{name:/Task board/}).click();
    await page.getByRole('textbox',{name:'Search tasks',exact:true}).fill('Approval');
    assert.equal(await page.locator('.task-card').count(),1);
    await page.getByRole('textbox',{name:'Search tasks',exact:true}).fill('<script>');
    assert.equal(await page.locator('.task-card').count(),0);
    await page.locator('.sidebar').getByRole('button',{name:'Overview',exact:true}).click();
    await page.getByRole('button',{name:'Ⅱ Pause dispatch',exact:true}).click();
    await page.getByRole('button',{name:'▷ Resume dispatch',exact:true}).waitFor();
    await page.getByRole('button',{name:'Add project',exact:true}).click();
    await page.getByLabel('Project name',{exact:true}).fill('PROJECT_NAVIS');
    await page.locator('#project-dialog').getByRole('button',{name:'Add project',exact:true}).click();
    await page.locator('#project-dialog').waitFor({state:'hidden'});
    await page.getByRole('button',{name:'All projects',exact:true}).click();
    const send = async body => {const r=await fetch(base+'/api/command',{method:'POST',headers:{Authorization:'Bearer '+token,Origin:base,'Content-Type':'application/json'},body:JSON.stringify(body)});assert(r.ok);return r.json();};
    const snap=await (await fetch(base+'/api/snapshot',{headers:{Authorization:'Bearer '+token}})).json();
    await send({action:'create_task',project_id:'project-vela',title:'<img src=x onerror=alert(1)>',spec:'Untrusted title rendering',scope:'docs/',scenario:'success'});
    await page.getByRole('button',{name:'Refresh',exact:true}).click();
    await page.getByRole('heading',{name:'<img src=x onerror=alert(1)>',exact:true}).waitFor();
    assert.equal(await page.locator('.task-card img').count(),0);
    // Fresh screenshot with clearly simulated, descriptive work.
    await send({action:'create_task',project_id:'project-vela',title:'Review context broker boundaries',spec:'Confirm local-only context routing in the simulation.',scope:'src/context/',scenario:'approval'});
    await send({action:'create_task',project_id:snap.projects.find(p=>p.name==='PROJECT_NAVIS').id,title:'Design the agent control contract',spec:'Exercise lifecycle controls using fake-agent.',scope:'navis/',scenario:'success'});
    await send({action:'resume'});
    await wait(6500);
    await send({action:'pause'});
    await page.getByRole('button',{name:'Refresh',exact:true}).click();
    await wait(500);
    if(process.env.NAVIS_SCREENSHOT){fs.mkdirSync(path.dirname(process.env.NAVIS_SCREENSHOT),{recursive:true});await page.screenshot({path:process.env.NAVIS_SCREENSHOT,fullPage:true});}
    await page.setViewportSize({width:390,height:844});
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Mobile horizontal overflow');
    await page.getByRole('button',{name:'+ New task',exact:true}).click();
    await page.getByLabel('Task title',{exact:true}).fill('Mobile task');
    await page.getByLabel('Task description',{exact:true}).fill('Confirm mobile form');
    await page.getByRole('button',{name:'Create task →',exact:true}).click();
    await page.locator('#detail-dialog[open]').waitFor();
    assert.equal(errors.length,0,errors.join('\n'));
    server.kill('SIGINT');
    await page.locator('#detail-dialog').getByRole('button',{name:'Close',exact:true}).click();
    await page.getByRole('alert').filter({hasText:'Connection lost'}).waitFor();
    assert(await page.getByRole('button',{name:'+ New task',exact:true}).isDisabled());
    console.log('Browser checks passed: approval, input, stop, retry, kill, filters, project creation, escaping, mobile, disconnect.');
  } finally {
    if(browser) await browser.close();
    server.kill('SIGINT');
    await new Promise(resolve=>{if(server.exitCode!==null)return resolve();server.once('exit',resolve);setTimeout(()=>{server.kill('SIGKILL');resolve();},2000).unref();});
    fs.rmSync(folder,{recursive:true,force:true});
  }
})().catch(e=>{console.error(e);process.exit(1);});
