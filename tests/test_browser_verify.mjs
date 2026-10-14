import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {verify,validateContract,saveScreenshot,SCREENSHOT_LIMITS} from '../ascendra/browser_verify.mjs';
const contract=steps=>({version:1,scenarios:[{name:'Independent acceptance',steps}]});
test('contract rejects executable assertions, missing expectations and external URLs',()=>{
  for(const c of [contract([{action:'evaluate',value:'alert(1)'}]),contract([{action:'click',selector:'button'}]),contract([{action:'goto',path:'https://evil.example'},{action:'expect_visible',selector:'body'}])]) assert.throws(()=>validateContract(c));
});
test('real browser proves persistence, completion, mobile and opaque storage fallback',async()=>{
  const root=await fs.mkdtemp(path.join(os.tmpdir(),'ascendra-browser-'));
  try {
    await fs.writeFile(path.join(root,'index.html'),`<!doctype html><html><head><meta name="viewport" content="width=device-width"></head><body><input id="title"><button id="add">Add</button><label><input id="done" type="checkbox">Done</label><p id="item"></p><script>let saved='';try{saved=localStorage.getItem('item')||''}catch{}document.querySelector('#item').textContent=saved;document.querySelector('#add').onclick=()=>{const value=document.querySelector('#title').value;document.querySelector('#item').textContent=value;try{localStorage.setItem('item',value)}catch{}};</script></body></html>`);
    const steps=[{action:'fill',selector:'#title',value:'Independent test'},{action:'click',selector:'#add'},{action:'expect_text',selector:'#item',text:'Independent test'},{action:'check',selector:'#done'},{action:'expect_checked',selector:'#done'}];
    const c={version:1,scenarios:[{name:'Persistence',steps:[...steps,{action:'reload'},{action:'expect_text',selector:'#item',text:'Independent test'}]},{name:'Opaque mobile',mode:'opaque',viewport:{width:390,height:844},steps:[...steps,{action:'mobile_overflow'}]}]};
    const report=await verify(root,c,path.join(root,'report.json'));assert.equal(report.passed,true,JSON.stringify(report));assert.equal(report.screenshots.length,2);
    const failed=await verify(root,contract([{action:'expect_text',selector:'#item',text:'MISSING'}]),path.join(root,'failure.json'));assert.equal(failed.passed,false);
    await fs.writeFile(path.join(root,'index.html'),'<!doctype html><html><body>App<script>throw Error("fixture runtime crash")</script></body></html>');
    const crash=await verify(root,contract([{action:'expect_visible',selector:'body'}]),path.join(root,'crash.json'));assert.equal(crash.passed,false);assert.match(crash.page_errors[0].error,/fixture runtime crash/);
  }finally{await fs.rm(root,{recursive:true,force:true});}
});
test('external requests are blocked and symlinks cannot expose outside files',async()=>{
  const root=await fs.mkdtemp(path.join(os.tmpdir(),'ascendra-network-'));
  const outside=await fs.mkdtemp(path.join(os.tmpdir(),'ascendra-secret-'));
  try {
    await fs.writeFile(path.join(outside,'secret.html'),'PRIVATE SENTINEL');
    await fs.symlink(path.join(outside,'secret.html'),path.join(root,'escape.html'));
    await fs.writeFile(path.join(root,'index.html'),'<!doctype html><html><body>Safe<img src="https://example.invalid/blocked.png"></body></html>');
    const report=await verify(root,contract([{action:'expect_text',selector:'body',text:'Safe'},{action:'goto',path:'/escape.html'},{action:'expect_text',selector:'body',text:'Not found'}]),path.join(root,'report.json'));
    assert.equal(report.passed,true,JSON.stringify(report));assert(report.external_requests.some(r=>r.url==='https://example.invalid/blocked.png'));
  }finally{await fs.rm(root,{recursive:true,force:true});await fs.rm(outside,{recursive:true,force:true});}
});

test('screenshot evidence enforces file and aggregate quotas before writing',async()=>{
  const root=await fs.mkdtemp(path.join(os.tmpdir(),'ascendra-evidence-'));
  try {
    const budget={bytes:0};
    const pageFor=size=>({screenshot:async options=>{
      assert.equal(options.path,undefined);
      assert.equal(options.fullPage,false);
      return Buffer.alloc(size);
    }});
    const oversize=path.join(root,'oversize.jpg');
    assert.equal(await saveScreenshot(pageFor(SCREENSHOT_LIMITS.perFile+1),oversize,budget),false);
    await assert.rejects(fs.access(oversize));
    assert.equal(budget.bytes,0);
    for(let i=0;i<12;i++) {
      const saved=await saveScreenshot(pageFor(SCREENSHOT_LIMITS.perFile),path.join(root,`${i}.jpg`),budget);
      assert.equal(saved,i<SCREENSHOT_LIMITS.total/SCREENSHOT_LIMITS.perFile);
    }
    const files=await fs.readdir(root);
    const sizes=await Promise.all(files.map(async file=>(await fs.stat(path.join(root,file))).size));
    assert(sizes.every(size=>size<=SCREENSHOT_LIMITS.perFile));
    assert.equal(sizes.reduce((a,b)=>a+b,0),SCREENSHOT_LIMITS.total);
    // A pre-existing file is never overwritten or counted a second time.
    const fresh={bytes:0};
    await assert.rejects(saveScreenshot(pageFor(1),path.join(root,'0.jpg'),fresh),/EEXIST/);
    assert.equal(fresh.bytes,0);
  }finally{await fs.rm(root,{recursive:true,force:true});}
});
