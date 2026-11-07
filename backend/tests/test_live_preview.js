'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const context=vm.createContext({setTimeout,clearTimeout});
vm.runInContext(fs.readFileSync('backend/web/adaptation.js','utf8').split('const adaptive=')[0]+'\nglobalThis.LatestPreview=LatestPreview;',context);
const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve};};
(async()=>{
  const gate=new context.LatestPreview();const presented=[];
  const old=deferred();const newest=deferred();
  const a=gate.run(()=>old.promise,r=>presented.push(r));
  gate.invalidate();
  const b=gate.run(()=>newest.promise,r=>presented.push(r));
  newest.resolve('1800 / human_review');await b;old.resolve('1200 / routine_processing');await a;
  assert.deepEqual(presented,['1800 / human_review']);
  // A pending response must be ignored immediately when editing resumes, before debounce fires.
  const pending=deferred();const c=gate.run(()=>pending.promise,r=>presented.push(r));
  let calls=0;
  gate.schedule(async()=>{calls++;return 'first';},r=>presented.push(r),e=>{throw e;});
  gate.schedule(async()=>{calls++;return 'second';},r=>presented.push(r),e=>{throw e;});
  gate.schedule(async()=>{calls++;return 'latest';},r=>presented.push(r),e=>{throw e;});
  pending.resolve('stale');await c;
  await new Promise(r=>setTimeout(r,420));
  assert.equal(calls,1);assert.deepEqual(presented,['1800 / human_review','latest']);
  console.log('Live preview: out-of-order responses, edit-time invalidation and rapid debounce passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
