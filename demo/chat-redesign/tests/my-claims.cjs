// Run with jsdom available on NODE_PATH (the insurer app's dev dependencies include it).
const assert=require('node:assert/strict'),fs=require('node:fs');
const {JSDOM,VirtualConsole}=require('jsdom');
const html=fs.readFileSync('demo/chat-redesign/intake.html','utf8')
 .replace('<script src="/profile.js"></script>','<script>'+fs.readFileSync('demo/chat-redesign/profile.js','utf8')+'</script>')
 .replace('<body data-voice-agent=','<body class="embedded" data-voice-agent=')
 .replace('<script src="/assets/claim_assistance.js"></script>','<script>'+fs.readFileSync('backend/claim_assistance.js','utf8')+'</script>');
const values={description:'Fictional scraped bumper in the car park.',incident_date:'2026-11-07',location:'Fictional Demo Street',policy_number:'DEMO-42',email:'demo@example.org',injury_status:'no'};
const report={kind:'incident_report',name:'report.pdf',content_base64:Buffer.from('%PDF-demo').toString('base64')};
const quote={...report,kind:'itemized_quote',name:'quote.pdf'};
const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function until(check){for(let i=0;i<150;i++){if(check())return;await pause(10)}throw Error('Timed out waiting for the app');}
function setup(draft=null,profile=null){
 const messages=[],requests=[],records=new Map(),token='a'.repeat(64);let rev=0,delay=0;
 if(draft)records.set(token,{status:'draft',revision:0,draft});
 const parent={postMessage:data=>messages.push(data)};
 const dom=new JSDOM(html,{url:'http://localhost:8090/chat?embedded=1'+(draft?'&recorded=1#claim='+token:'&start=chat'),runScripts:'dangerously',virtualConsole:new VirtualConsole().sendTo(console),beforeParse(w){
  if(profile)w.localStorage.setItem('retakt.customer-profile.v1',JSON.stringify(profile));
  Object.defineProperty(w,'parent',{value:parent});w.HTMLElement.prototype.scrollIntoView=()=>{};
  w.fetch=async(url,options)=>{
   const body=JSON.parse(options.body),path=url.split('/').at(-1);requests.push({path,body});
   let data,status=200;
   if(path==='resume')data=records.get(body.token);
   else if(path==='quote')data={status:'verified',name:body.document.name,reason:'Sample quote checked.'};
   else if(path==='save-draft'){
    if(delay)await pause(delay);
    if(body.expected_revision!==rev){status=409;data={error:'Stale draft'};}
    else{data={status:'draft',revision:++rev};records.set(body.token,{...data,draft:structuredClone(body.draft)});}
   }else if(path==='submit'){
    if(body.expected_revision!==rev){status=409;data={error:'Stale submission'};}
    else if(!['incident_report','itemized_quote'].every(kind=>body.payload.documents.some(doc=>doc.kind===kind))){status=422;data={error:'Documents required'};}
    else{const documents=body.payload.documents.map(({kind,name})=>({kind,name}));data={status:'submitted',reference:'CLM-demo',documents,document_count:documents.length,missing_documents:[]};records.set(body.token,data);}
   }else throw Error('Unexpected request '+path);
   return{ok:status===200,status,json:async()=>data};
  };
 }});
 const w=dom.window;
 return{w,messages,requests,records,delay:ms=>delay=ms,close:()=>w.close(),message:data=>w.dispatchEvent(new w.MessageEvent('message',{origin:w.location.origin,source:parent,data})),button:name=>[...w.document.querySelectorAll('button')].find(b=>b.textContent===name),edit:label=>w.document.querySelector('button[aria-label="Edit '+label+'"]')};
}
(async()=>{
 const a=setup();
 try{
  a.message({type:'retakt:voice-details',requestId:'voice',values});
  a.message({type:'retakt:save-current-claim',requestId:'flush'});
  await until(()=>a.messages.some(m=>m.type==='retakt:claim-saved'));
  const saved=a.messages.find(m=>m.type==='retakt:claim-record');assert.equal(saved.status,'draft');assert.equal(saved.ready,false);assert.equal(saved.values.policy_number,'DEMO-42');assert.equal(saved.missing_documents.length,2);
  assert.equal(a.requests.filter(r=>r.path==='save-draft').length,1);assert.equal(a.requests.some(r=>r.path==='submit'),false);
  assert.ok(!a.w.document.querySelector('#current').textContent.includes('private resume link'));
 }finally{a.close();}
 const draft={values:{...values},documents:[report,quote],sources:{},notes:{photos:[],translations:[]},step:6};
 const b=setup(draft);
 try{
  await until(()=>b.button('Send claim'));
  assert.equal(b.button('Send claim').disabled,false);b.edit('Insurance number').click();
  const input=b.w.document.querySelector('#answer');input.value='DEMO-CORRECTED';input.dispatchEvent(new b.w.Event('input',{bubbles:true}));
  b.delay(120);await until(()=>b.requests.some(r=>r.path==='save-draft'));
  b.button('Save answer').click();b.button('Send claim').click();
  await until(()=>b.w.document.querySelector('#current').textContent.includes('Submitted claims are read-only.'));
  const submission=b.requests.find(r=>r.path==='submit');assert.equal(submission.body.expected_revision,1);assert.equal(submission.body.payload.policy_number,'DEMO-CORRECTED');
  const sent=b.messages.find(m=>m.type==='retakt:claim-receipt');assert.equal(sent.just_submitted,true);assert.equal(sent.values.policy_number,'DEMO-CORRECTED');
  assert.equal([...b.w.document.querySelectorAll('button')].some(el=>/^Edit |Add documents|Send claim|Attach|Remove|Copy private/.test(el.getAttribute('aria-label') || el.textContent)),false);
  assert.ok(!b.w.document.querySelector('#current').textContent.includes('Private follow-up link'));
  const profile=JSON.parse(b.w.localStorage.getItem('retakt.customer-profile.v1'));assert.equal(profile.email,values.email);assert.equal(profile.insurance_number,'DEMO-CORRECTED');
 }finally{b.close();}
 const c=setup({...draft,documents:[report]});
 try{
  await until(()=>c.button('Send claim'));assert.equal(c.button('Send claim').disabled,true);assert.ok(c.button('Upload missing documents'));
  c.edit('Insurance number').click();const input=c.w.document.querySelector('#answer');input.value='SAVED-CORRECTION';c.button('Save answer').click();
  c.message({type:'retakt:save-current-claim',requestId:'flush'});await until(()=>c.messages.some(m=>m.type==='retakt:claim-saved'));
  assert.equal(c.records.get('a'.repeat(64)).draft.values.policy_number,'SAVED-CORRECTION');assert.equal(c.requests.some(r=>r.path==='submit'),false);
 }finally{c.close();}
 const savedProfile={name:'Fictional Demo Customer',email:'saved@example.org',phone:'+49 30 00000000',address:'Example Street 12',insurance_number:'SAVED-42',description:'OLD INCIDENT MUST NEVER COPY',incident_date:'2026-01-01'};
 const d=setup(null,savedProfile);
 try{
  assert.match(d.w.document.querySelector('#current').textContent,/Are your details still current/);
  assert.equal(d.w.document.querySelector('#profile-insurance_number').value,'SAVED-42');
  assert.equal(d.w.document.querySelector('.composer'),null);
  d.w.document.querySelector('#profile-email').value='updated@example.org';d.button('Confirm and continue').click();
  assert.ok(d.w.document.querySelector('.composer'));
  await pause(700);assert.equal(d.requests.some(r=>r.path==='save-draft'),false);
  const confirmed=d.messages.find(m=>m.type==='retakt:profile-confirmed');assert.equal(confirmed.profile.email,'updated@example.org');assert.equal(confirmed.profile.name,'Fictional Demo Customer');assert.equal(confirmed.profile.description,undefined);
  d.message({type:'retakt:voice-partial-details',values:{description:'A fresh fictional incident with no previous paperwork.'}});
  d.message({type:'retakt:save-current-claim',requestId:'profile-flush'});await until(()=>d.messages.some(m=>m.type==='retakt:claim-saved'));
  const packet=d.requests.find(r=>r.path==='save-draft').body.draft;
  assert.equal(packet.values.email,'updated@example.org');assert.equal(packet.values.policy_number,'SAVED-42');assert.equal(packet.values.incident_date,undefined);assert.equal(packet.documents.length,0);assert.ok(!JSON.stringify(packet).includes('OLD INCIDENT'));
  const saved=JSON.parse(d.w.localStorage.getItem('retakt.customer-profile.v1'));assert.equal(saved.phone,savedProfile.phone);assert.equal(saved.description,undefined);
 }finally{d.close();}
 const e=setup(null,savedProfile);
 try{
  e.button('Use different details for this claim').click();e.message({type:'retakt:voice-partial-details',values:{description:'Another fresh fictional incident.'}});e.message({type:'retakt:save-current-claim',requestId:'skip-flush'});await until(()=>e.messages.some(m=>m.type==='retakt:claim-saved'));
  const packet=e.requests.find(r=>r.path==='save-draft').body.draft;assert.equal(packet.values.email,undefined);assert.equal(packet.values.policy_number,undefined);
 }finally{e.close();}
 console.log('Passed: voice claims save automatically, missing documents block sending, drafts reopen and retain corrections, in-flight saves serialize before sending, and submitted phone claims are locked, contact details persist, new claims require profile review, and old incidents/files never carry forward.');
})().catch(error=>{console.error(error);process.exitCode=1});
