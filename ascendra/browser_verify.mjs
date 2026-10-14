/** Independent declarative browser checks. Run generated code in a disposable OS/container
 * sandbox: browser request filtering is defense in depth, not an OS security boundary. */
import fs from 'node:fs/promises';
import path from 'node:path';
import http from 'node:http';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
import assert from 'node:assert/strict';

const actions = new Set(['goto','fill','click','check','select','reload','expect_text','expect_visible','expect_checked','mobile_overflow']);
export function validateContract(c) {
  if (!c || c.version !== 1 || !Array.isArray(c.scenarios) || !c.scenarios.length || c.scenarios.length > 12) throw Error('Contract requires version 1 and 1–12 scenarios');
  let assertions=0;
  for(const s of c.scenarios) {
    if(typeof s.name !== 'string' || !s.name || !['standalone','opaque'].includes(s.mode || 'standalone') || !Array.isArray(s.steps) || !s.steps.length || s.steps.length>60) throw Error('Invalid scenario');
    if(s.viewport && (!Number.isInteger(s.viewport.width)||!Number.isInteger(s.viewport.height)||s.viewport.width<240||s.viewport.width>1920||s.viewport.height<240||s.viewport.height>1200)) throw Error('Invalid viewport');
    for(const step of s.steps) {
      if(!actions.has(step.action)) throw Error('Unsupported action');
      if(!['goto','reload','mobile_overflow'].includes(step.action) && (typeof step.selector!=='string'||!step.selector||step.selector.length>1000)) throw Error('Action requires bounded selector');
      if(['fill','select'].includes(step.action) && (typeof step.value!=='string'||step.value.length>10000)) throw Error('Action requires bounded string value');
      if(step.action==='expect_text' && (typeof step.text!=='string'||!step.text||step.text.length>10000)) throw Error('Text expectation requires nonempty text');
      if(step.action==='expect_checked' && step.checked!==undefined && typeof step.checked!=='boolean') throw Error('Invalid checked expectation');
      if(step.action==='goto' && step.path!==undefined && (typeof step.path!=='string'||!step.path.startsWith('/')||step.path.startsWith('//')||step.path.includes('\\'))) throw Error('Navigation must be local');
      if(step.action.startsWith('expect_')||step.action==='mobile_overflow') assertions++;
    }
  }
  if(!assertions) throw Error('Contract must contain an assertion');
  return c;
}
function playwright() {
  const candidates=[process.env.ASCENDRA_PLAYWRIGHT_PACKAGE, path.resolve('package.json'), '/workspace/sites/ascendra-observatory/package.json'].filter(Boolean);
  for(const candidate of candidates) {try{return createRequire(path.resolve(candidate))('playwright');}catch{}}
  throw Error('Playwright unavailable; set ASCENDRA_PLAYWRIGHT_PACKAGE to package.json beside installed node_modules');
}
// Screenshots are optional evidence, never an unbounded filesystem sink.
export const SCREENSHOT_LIMITS = Object.freeze({perFile: 512 * 1024, total: 2 * 1024 * 1024});
export async function saveScreenshot(page, destination, budget) {
  if (budget.bytes >= SCREENSHOT_LIMITS.total) return false;
  // Capture the bounded viewport into memory first: Playwright must not write an
  // oversized image before we inspect its encoded size.
  const bytes = await page.screenshot({type:'jpeg',quality:60,fullPage:false,timeout:3000});
  if (bytes.length > SCREENSHOT_LIMITS.perFile || budget.bytes + bytes.length > SCREENSHOT_LIMITS.total) return false;
  await fs.writeFile(destination, bytes, {flag:'wx'});
  budget.bytes += bytes.length;
  return true;
}
export async function verify(project, contract, output) {
  validateContract(contract);
  const root=await fs.realpath(project);await fs.access(path.join(root,'index.html'));
  const outputPath=path.resolve(output), evidence=outputPath+'.evidence';await fs.mkdir(evidence,{recursive:true});
  const screenshotBudget={bytes:0};
  // Include evidence retained from previous attempts in the same report budget.
  for(const entry of await fs.readdir(evidence,{withFileTypes:true})) {
    if(entry.isFile()) screenshotBudget.bytes += (await fs.stat(path.join(evidence,entry.name))).size;
  }
  const report={version:1,passed:false,checks:[],page_errors:[],external_requests:[],screenshots:[],started_at:new Date().toISOString()};
  const mime={'.html':'text/html','.js':'text/javascript','.css':'text/css','.svg':'image/svg+xml','.png':'image/png','.json':'application/json'};
  const server=http.createServer(async(req,res)=>{
    try {
      if(req.method!=='GET'){res.writeHead(405);res.end();return;}
      const url=new URL(req.url,'http://localhost');
      if(url.pathname==='/__ascendra_opaque__') {
        const target=url.searchParams.get('path')||'/';
        if(!target.startsWith('/')||target.startsWith('//')||target.includes('\\')) throw Error('Invalid frame path');
        const escaped=target.replaceAll('&','&amp;').replaceAll('"','&quot;').replaceAll('<','&lt;');
        res.writeHead(200,{'Content-Type':'text/html'});res.end(`<html><body style="margin:0"><iframe sandbox="allow-scripts" src="${escaped}" style="border:0;width:100%;height:100vh"></iframe></body></html>`);return;
      }
      const rel=decodeURIComponent(url.pathname).replace(/^\/+/, '')||'index.html';
      if(rel.split('/').some(s=>s.startsWith('.'))) throw Error('Hidden path');
      const file=await fs.realpath(path.resolve(root,rel));if(!file.startsWith(root+path.sep)) throw Error('Outside root');
      const stat=await fs.stat(file);if(!stat.isFile()||stat.size>2*1024*1024) throw Error('Invalid asset');
      res.writeHead(200,{'Content-Type':mime[path.extname(file)]||'application/octet-stream','Cache-Control':'no-store','Content-Security-Policy':"connect-src 'none'; frame-src 'self'; object-src 'none'; worker-src 'none'; form-action 'none'"});res.end(await fs.readFile(file));
    }catch{res.writeHead(404);res.end('Not found');}
  });
  await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(0,'127.0.0.1',resolve);});
  const origin=`http://127.0.0.1:${server.address().port}`;let browser;
  try {
    browser=await playwright().chromium.launch({executablePath:process.env.ASCENDRA_CHROMIUM||'/usr/bin/chromium',headless:true,args:['--no-sandbox']});
    for(const [index,scenario] of contract.scenarios.entries()) {
      const context=await browser.newContext({viewport:scenario.viewport||{width:1280,height:900},permissions:[],acceptDownloads:false,serviceWorkers:scenario.mode==='opaque'?'allow':'block'});
      await context.route('**/*',route=>{
        const target=new URL(route.request().url());
        if(target.origin===origin && ['GET','HEAD'].includes(route.request().method())) return route.continue();
        if(report.external_requests.length<100) report.external_requests.push({scenario:scenario.name,url:target.origin+target.pathname});
        return route.abort();
      });
      if(context.routeWebSocket) await context.routeWebSocket('**/*',socket=>socket.close());
      const page=await context.newPage();page.setDefaultTimeout(3000);page.setDefaultNavigationTimeout(5000);
      page.on('pageerror',error=>{if(report.page_errors.length<100)report.page_errors.push({scenario:scenario.name,error:error.message.slice(0,2000)});});
      context.on('page',other=>{if(other!==page)other.close().catch(()=>{});});
      page.on('dialog',dialog=>dialog.dismiss());
      let scope=page;
      async function navigate(local='/') {
        const target=new URL(local,origin);if(target.origin!==origin)throw Error('External navigation forbidden');
        await page.goto(scenario.mode==='opaque'?origin+'/__ascendra_opaque__?path='+encodeURIComponent(local):target.href,{waitUntil:'load'});
        scope=scenario.mode==='opaque'?page.frames().find(f=>f!==page.mainFrame()):page;
        if(!scope)throw Error('Opaque frame unavailable');
      }
      try {
        await navigate();
        for(const [number,step] of scenario.steps.entries()) {
          try {
            const locator=step.selector?scope.locator(step.selector):null;
            switch(step.action) {
              case 'goto':await navigate(step.path||'/');break;
              case 'fill':await locator.fill(step.value);break;
              case 'click':await locator.click();break;
              case 'check':await locator.check();break;
              case 'select':await locator.selectOption(step.value);break;
              case 'reload':await page.reload({waitUntil:'load'});scope=scenario.mode==='opaque'?page.frames().find(f=>f!==page.mainFrame()):page;break;
              case 'expect_visible':await locator.waitFor({state:'visible'});break;
              case 'expect_text':{await locator.waitFor({state:'visible'});const until=Date.now()+3000;while(!(await locator.innerText()).includes(step.text)&&Date.now()<until)await new Promise(r=>setTimeout(r,50));assert((await locator.innerText()).includes(step.text),'Expected text absent');break;}
              case 'expect_checked':assert.equal(await locator.isChecked(),step.checked??true);break;
              case 'mobile_overflow':{
                const d=await scope.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth}));assert(d.scroll<=d.width+1,`Horizontal overflow: ${d.scroll}>${d.width}`);break;
              }
            }
            report.checks.push({scenario:scenario.name,step:number,action:step.action,passed:true});
          } catch(error) {report.checks.push({scenario:scenario.name,step:number,action:step.action,passed:false,error:error.message.slice(0,2000)});break;}
        }
      }catch(error){report.checks.push({scenario:scenario.name,passed:false,error:error.message.slice(0,2000)});}
      try{const shot=path.join(evidence,`scenario-${index}.jpg`);if(await saveScreenshot(page,shot,screenshotBudget))report.screenshots.push(shot);}catch{}
      await context.close();
    }
  }catch(error){report.checks.push({action:'harness',passed:false,error:error.message.slice(0,2000)});}
  finally {
    if(browser)await browser.close();await new Promise(resolve=>server.close(resolve));
    report.finished_at=new Date().toISOString();report.passed=report.checks.length>0&&report.checks.every(c=>c.passed)&&report.page_errors.length===0;
    await fs.writeFile(outputPath,JSON.stringify(report,null,2)+'\n');
  }
  return report;
}
if(process.argv[1] && path.resolve(process.argv[1])===fileURLToPath(import.meta.url)) {
  try {
    if(process.argv.length!==5)throw Error('Usage: node browser_verify.mjs PROJECT_DIR CONTRACT_JSON OUTPUT_JSON');
    const contractFile=await fs.readFile(process.argv[3]);if(contractFile.length>128*1024)throw Error('Contract too large');
    const result=await verify(process.argv[2],JSON.parse(contractFile),process.argv[4]);console.log(JSON.stringify({passed:result.passed,checks:result.checks.length,report:path.resolve(process.argv[4])}));process.exitCode=result.passed?0:1;
  }catch(error){console.error(error.message);process.exitCode=2;}
}
