const $ = id => document.getElementById(id);
const frame = $('claim-flow');
const storeKey = 'retakt.private-claims.v1';
const validClaim = c => c && /^[0-9a-f]{64}$/.test(c.token) && (c.status === 'draft' || (typeof c.reference === 'string' && c.reference.length <= 80));
const readClaims = () => { try { const v = JSON.parse(localStorage.getItem(storeKey) || '[]'); return Array.isArray(v) ? v.filter(validClaim).map(c=>({...c,status:c.status==='draft'?'draft':'submitted'})).slice(-30) : []; } catch { return []; } };
const detailFrame = $('claim-detail');
let activeTab='new', detailOpen=false, newClaimSubmitted=false, savingClaim=false, claimsError='';
const saveRequests=new Map();
const node = (tag, text, cls) => { const n = document.createElement(tag); n.textContent = text; if (cls) n.className = cls; return n; };
const labels = {routine_processing:'Being processed',request_information:'More information needed',human_review:'Under review by a person'};
const voiceTransfers = new Map();
const capturedDetails = {};
const profileStore=window.RetaktProfile;
let reviewedCustomer=null;
function updatePhoneClaimDetails(input) {
  const labels={name:'Name',description:'Incident',incident_date:'Date',location:'Location',insurance_number:'Insurance number',email:'Email',injury_status:'Injuries'};
  for(const key of Object.keys(labels)) {
    if(typeof input?.[key]==='string' && input[key].trim()) capturedDetails[key]=input[key].trim().slice(0,key==='description'?2000:254);
  }
  const box=$('call-facts');box.replaceChildren();
  for(const [key,label] of Object.entries(labels)) if(capturedDetails[key]) box.append(node('dt',label),node('dd',capturedDetails[key]));
  box.hidden=!Object.keys(capturedDetails).length;
  return JSON.stringify({status:'displayed',next_action:'Ask only the next missing question. The caller can correct these details.'});
}
async function prepareClaimInPhone(input) {
  input={...input,policy_number:input?.insurance_number || input?.policy_number};
  const limits={description:[10,2000],incident_date:[10,10],location:[1,160],policy_number:[1,80],email:[3,254],injury_status:[2,7]};
  const values={};
  for(const [key,[min,max]] of Object.entries(limits)) {
    const value=typeof input?.[key]==='string'?input[key].trim():'';
    if(value.length<min || value.length>max) return JSON.stringify({error:'Please correct the missing or invalid '+(key==='policy_number'?'insurance number':key.replaceAll('_',' '))+'.'});
    values[key]=value;
  }
  const date=new Date(values.incident_date+'T00:00:00Z');
  const parts=new Intl.DateTimeFormat('en-CA',{timeZone:'Europe/Berlin',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date());
  const today=['year','month','day'].map(k=>parts.find(p=>p.type===k).value).join('-');
  if(!/^\d{4}-\d{2}-\d{2}$/.test(values.incident_date) || !Number.isFinite(date.getTime()) || date.toISOString().slice(0,10)!==values.incident_date || values.incident_date>today) return JSON.stringify({error:'Please correct the incident date; it must be a real date on or before today.'});
  if(!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(values.email) || !['yes','no','unknown'].includes(values.injury_status) || /^(unknown|n\/a|none)$/i.test(values.policy_number)) return JSON.stringify({error:'Please correct the email, injury answer or insurance number.'});
  updatePhoneClaimDetails({...values,insurance_number:values.policy_number});
  const requestId=crypto.randomUUID();
  const result=await new Promise(resolve=>{
    const timeout=setTimeout(()=>{voiceTransfers.delete(requestId);resolve({error:'The phone did not acknowledge the details. Please continue in chat.'});},10000);
    voiceTransfers.set(requestId,result=>{clearTimeout(timeout);resolve(result);});
    frame.contentWindow.postMessage({type:'retakt:voice-details',requestId,values,contact:{...reviewedCustomer,...(capturedDetails.name?{name:capturedDetails.name}:{})}},location.origin);
  });
  if(result.status==='ready') {
    $('use-chat').textContent='Continue to documents';
    $('call-copy').textContent='Your upload screen is ready.';
  }
  return JSON.stringify(result);
}
function select(name) {
  activeTab=name;
  for (const t of ['new','claims']) { $('tab-'+t).setAttribute('aria-selected',String(t===name)); $(t).classList.toggle('on',t===name); }
  if (name === 'claims' && !detailOpen) showClaims();
}
function rememberClaim(data) {
  const saved=readClaims(), previous=saved.find(c=>c.token===data.token);
  // A late draft acknowledgement must never turn a sent claim back into a draft.
  if(previous?.status==='submitted' && data.status==='draft') return;
  const now=new Date().toISOString();
  const claim={...previous,...data,updated_at:previous?.status==='submitted'?previous.updated_at:data.updated_at || now};
  if(!Object.keys(claim.contact || {}).length) claim.contact=previous?.contact || {};
  if(data.status==='submitted' && data.just_submitted) claim.submitted_at=previous?.submitted_at || now;
  delete claim.type;
  if(!claim.title) claim.title=previous?.title || 'Your claim';
  if(!Object.keys(claim.values || {}).length) claim.values=previous?.values || {};
  try {localStorage.setItem(storeKey,JSON.stringify([...saved.filter(c=>c.token!==claim.token),claim].slice(-30)));}
  catch {claimsError='Could not save My claims on this device. Please keep this page open.';}
  if(activeTab==='claims' && !detailOpen) showClaims();
}
function flushClaim(target) {
  const requestId=crypto.randomUUID();
  return new Promise(resolve=>{
    const timeout=setTimeout(()=>{saveRequests.delete(requestId);resolve(false);},45000);
    saveRequests.set(requestId,ok=>{clearTimeout(timeout);resolve(ok);});
    target.contentWindow.postMessage({type:'retakt:save-current-claim',requestId},location.origin);
  });
}
async function listClaims(target=frame) {
  if(savingClaim) return;
  savingClaim=true;detailOpen=false;claimsError='';
  $('claim-detail-wrap').hidden=true;$('claims-list').hidden=false;
  select('claims');
  const saved=await flushClaim(target);
  savingClaim=false;
  if(!saved) {
    claimsError='Your latest changes are not saved yet. Please try Save and continue later.';
    if(target===detailFrame) {detailOpen=true;$('claims-list').hidden=true;$('claim-detail-wrap').hidden=false;detailFrame.contentWindow.postMessage({type:'retakt:save-failed'},location.origin);}
    else select('new');
  }
  showClaims();
}
function openClaim(claim) {
  if(savingClaim) return;
  detailOpen=true;$('claims-list').hidden=true;$('claim-detail-wrap').hidden=false;
  detailFrame.src='/chat?embedded=1&recorded=1#claim='+claim.token;
  // The previous new-claim draft is already saved before the list becomes interactive.
  frame.src='/chat?start=chat&embedded=1';newClaimSubmitted=false;
  select('claims');
}
function showClaims() {
  const box=$('claims-list');box.replaceChildren(node('span','Retakt','eyebrow'),node('h1','My claims'));
  if(savingClaim) box.append(node('p','Saving your claim…','sub'));
  if(claimsError) {const error=node('p',claimsError,'error');error.setAttribute('role','alert');box.append(error);}
  const saved=readClaims().sort((a,b)=>(b.updated_at || '').localeCompare(a.updated_at || ''));
  if(!saved.length && !savingClaim) box.append(node('p','Your saved and submitted claims will appear here.','sub empty'));
  for(const status of ['draft','submitted']) {
    const claims=saved.filter(c=>c.status===status);
    if(!claims.length) continue;
    box.append(node('h2',status==='draft'?'In progress':'Submitted','claim-section'));
    const list=node('div','','list');
    for(const c of claims) {
      const card=node('article','','item');
      card.append(node('span',(c.demo?'Demo · ':'')+(status==='draft'?(c.ready?'Ready to send':'Not sent'):'Submitted'), 'badge '+(status==='draft'?'draft':'sent')),
        node('h3',c.title || 'Your claim','claim-title'));
      if(c.submitted_at) card.append(node('p','Sent · '+new Date(c.submitted_at).toLocaleDateString('en-GB',{day:'numeric',month:'short',year:'numeric'}),'claim-meta'));
      if(c.incident_date) card.append(node('p','Incident · '+c.incident_date,'claim-meta'));
      if(status==='submitted' && c.reference) card.append(node('p',c.reference,'reference'));
      if(status==='draft') {
        const missing=(c.missing_documents || []).map(k=>({incident_report:'incident report',itemized_quote:'itemized repair quote'}[k] || k));
        card.append(node('p',missing.length?'Needed: '+missing.join(' and ')+'.':c.ready?'Your details and documents are complete.':'Finish your claim details.','claim-meta'));
      } else card.append(node('p',labels[c.route] || 'Received by the claims team','claim-meta'));
      const actions=node('div','','claim-actions');
      const open=node('button',status==='draft'?'Edit claim':'View claim');open.type='button';open.disabled=savingClaim;open.onclick=()=>openClaim(c);actions.append(open);
      if(status==='draft') {const send=node('button','Review and send','send-claim');send.type='button';send.disabled=savingClaim || !c.ready;send.onclick=()=>openClaim(c);actions.append(send);}
      card.append(actions);list.append(card);
    }
    box.append(list);
  }
}
window.addEventListener('message', e => {
  const fromNew=e.source===frame.contentWindow, fromDetail=e.source===detailFrame.contentWindow;
  if(e.origin!==location.origin || (!fromNew && !fromDetail)) return;
  if(e.data?.type==='retakt:profile-confirmed' && fromNew) {reviewedCustomer=profileStore?.clean(e.data.profile) || {};return;}
  if(e.data?.type==='retakt:profile-review-required' && fromNew) {reviewedCustomer=null;return;}
  if(e.data?.type==='retakt:claim-saved') {
    const resolve=saveRequests.get(e.data.requestId);
    if(resolve) {saveRequests.delete(e.data.requestId);resolve(e.data.ok===true);}
    return;
  }
  if(e.data?.type==='retakt:show-claims') {listClaims(fromDetail?detailFrame:frame);return;}
  if(e.data?.type==='retakt:voice-details-ready' && fromNew) {
    const resolve=voiceTransfers.get(e.data.requestId);
    if(resolve) {voiceTransfers.delete(e.data.requestId);resolve(e.data.status==='ready'?{status:'ready',next_action:'End the call and continue to documents. The claim has not been submitted.'}:{error:'A saved claim or pending request is open. Start a new claim before transferring voice details.'});}
    return;
  }
  if(!['retakt:claim-record','retakt:claim-receipt'].includes(e.data?.type) || !validClaim(e.data)) return;
  const status=e.data.type==='retakt:claim-receipt'?'submitted':e.data.status;
  if(!['draft','submitted'].includes(status)) return;
  rememberClaim({...e.data,status});
  if(status==='submitted' && e.data.just_submitted) {
    if(fromNew) newClaimSubmitted=true;
    detailOpen=false;$('claim-detail-wrap').hidden=true;$('claims-list').hidden=false;select('claims');
  }
});
$('tab-new').onclick=()=>{if(newClaimSubmitted) {frame.src='/chat?start=chat&embedded=1';newClaimSubmitted=false;}select('new');};
$('tab-claims').onclick=()=>listClaims(detailOpen?detailFrame:frame);
$('back-claims').onclick=()=>listClaims(detailFrame);
// The browser SDK is loaded only when a person chooses Start call. No API key is sent to the client.
let session=null, run=0, starting=false, mic=null, muted=false;
const stopMic=()=>{mic?.getTracks().forEach(t=>t.stop());mic=null;};
function resetCall(message) { starting=false;muted=false; $('start-call').hidden=false; $('start-call').disabled=false; $('start-call').textContent='Start call'; $('end-call').hidden=true; $('end-call').disabled=false; $('live-controls').hidden=true; $('mute-call').textContent='Mute'; $('mute-call').setAttribute('aria-pressed','false'); $('transcript-panel').hidden=true; $('transcript-panel').open=false; $('call-avatar').classList.remove('speaking'); $('call-state').textContent=message; }
function fail(message) { $('call-error').textContent=message; $('call-error').hidden=false; }
async function endCall(message='Call ended') { ++run; const active=session; session=null; stopMic(); resetCall(message); if(active) try {await active.endSession();} catch { /* Tracks are already released. */ } }
async function closeCall() { await endCall(session || starting ? 'Call ended' : 'Your claims assistant'); $('call').close(); $('rico').focus(); }
$('rico').onclick=()=>{ $('call-error').hidden=true; $('start-call').textContent=profileStore?.hasDetails() && reviewedCustomer===null?'Review saved details':'Start call'; $('call').showModal(); };
$('close-call').onclick=closeCall; $('call').addEventListener('cancel', e=>{e.preventDefault();closeCall();});
$('end-call').onclick=()=>endCall();
$('mute-call').onclick=()=>{
  if(!session) return;
  try {const next=!muted;session.setMicMuted(next);muted=next;$('mute-call').textContent=muted?'Unmute':'Mute';$('mute-call').setAttribute('aria-pressed',String(muted));$('call-state').textContent=muted?'Microphone muted':'Listening to you';}
  catch {fail('Could not change the microphone. Please end the call and try again.');}
};
$('use-chat').onclick=async()=>{
  await closeCall();
  frame.contentWindow.postMessage({type:'retakt:voice-partial-details',values:{...capturedDetails,policy_number:capturedDetails.insurance_number}},location.origin);
  select('new');
};
$('start-call').onclick=async()=>{
  if (starting || session) return;
  if(profileStore?.hasDetails() && reviewedCustomer===null) {await closeCall();select('new');frame.contentWindow.postMessage({type:'retakt:review-profile'},location.origin);return;}
  const current=++run; starting=true; $('call-error').hidden=true; $('transcript').replaceChildren();
  for(const key of Object.keys(capturedDetails)) delete capturedDetails[key];
  $('call-facts').replaceChildren(); $('call-facts').hidden=true;
  if(reviewedCustomer) updatePhoneClaimDetails(reviewedCustomer); $('use-chat').textContent='Continue in chat'; $('call-copy').textContent='';
  $('start-call').disabled=true; $('start-call').textContent='Connecting…'; $('end-call').hidden=false; $('live-controls').hidden=false; $('mute-call').disabled=true; $('transcript-panel').hidden=true; $('transcript-panel').open=false; $('call-state').textContent='Allow microphone access to start';
  try {
    if(!navigator.mediaDevices?.getUserMedia) throw new Error('Use a browser with microphone support on localhost or HTTPS.');
    const permissionStream=await navigator.mediaDevices.getUserMedia({audio:true});
    if(current!==run) {permissionStream.getTracks().forEach(t=>t.stop());return;}
    mic=permissionStream;
    // Release this permission-check stream; the SDK owns the actual call stream and its cleanup.
    stopMic(); $('call-state').textContent='Connecting to Rico…';
    const {Conversation}=await Promise.race([import('https://esm.sh/@elevenlabs/client@1.35.0'),new Promise((_,reject)=>setTimeout(()=>reject(new Error('The call service took too long to load. Please try again.')),20000))]);
    if(current!==run) return;
    const active=await Conversation.startSession({
      agentId:document.body.dataset.voiceAgent,connectionType:'websocket',
      dynamicVariables:{saved_customer_details:JSON.stringify(reviewedCustomer || {})},
      clientTools:{prepare_claim_in_phone:prepareClaimInPhone,update_phone_claim_details:updatePhoneClaimDetails},
      onConnect:()=>{if(current!==run)return; $('call-state').textContent='Connected · Rico is listening';$('start-call').hidden=true;},
      onModeChange:({mode})=>{if(current!==run)return; $('call-avatar').classList.toggle('speaking',mode==='speaking');$('call-state').textContent=muted?'Microphone muted':mode==='speaking'?'Rico is speaking':'Listening to you';},
      onMessage:({message,source})=>{if(current!==run||!message)return; const p=node('p',message,source==='user'?'user':'agent');$('transcript').append(p);$('transcript-panel').hidden=false;if($('transcript-panel').open)p.scrollIntoView({block:'nearest'});},
      onDisconnect:()=>{if(current!==run)return;++run;session=null;stopMic();resetCall('Call ended');},
      onError:()=>{if(current!==run)return; fail('Could not connect to the call service. Try again, or continue in chat.');endCall('Call unavailable');}
    });
    if(current!==run) {await active.endSession();return;}
    session=active;starting=false;$('start-call').hidden=true;$('mute-call').disabled=false;
  } catch(e) {
    if(current!==run)return;
    await endCall('Call not started');
    fail(e.name==='NotAllowedError'?'Microphone access was not allowed. You can enable it in your browser or continue in chat.':e.name==='NotFoundError'?'No microphone was found. Connect one, or continue in chat.':e.message || 'Could not start the call. Please try again.');
  }
};
window.addEventListener('pagehide',()=>{endCall();});

async function loadDemoClaims() {
  try {
    const response=await fetch('/api/phone-demo/claims',{cache:'no-store'});
    if(!response.ok) throw new Error();
    const demo=await response.json();
    for(const claim of demo.claims || []) if(validClaim(claim)) rememberClaim({...claim,contact:readClaims().find(saved=>saved.token===claim.token)?.contact || claim.contact});
    if(profileStore && !profileStore.hasDetails()) {
      const existing=readClaims().filter(claim=>!claim.demo && claim.values?.email && claim.values?.policy_number).at(-1);
      profileStore.save(existing?{...existing.contact,email:existing.values.email,insurance_number:existing.values.policy_number,demo:false}:demo.profile);
      frame.contentWindow.postMessage({type:'retakt:profile-available'},location.origin);
    }
  } catch {claimsError='Demo history could not be loaded. Refresh to try again.';if(activeTab==='claims' && !detailOpen) showClaims();}
}
if(typeof fetch==='function') loadDemoClaims();
