'use strict';

// Invalidate at input time (not request time), so an older response cannot win during debounce.
class LatestPreview {
  constructor() { this.generation=0; this.timer=null; }
  invalidate() { this.generation++; clearTimeout(this.timer); return this.generation; }
  async run(work, apply, generation=this.generation) {
    const result=await work();
    if(generation===this.generation) apply(result);
  }
  schedule(work, apply, onError) {
    const generation=this.invalidate();
    this.timer=setTimeout(()=>this.run(work,apply,generation).catch(e=>{
      if(generation===this.generation) onError(e);
    }),350);
  }
}

const adaptive={workspace:null,preview:null,dirty:false,live:false,proposal:null,checks:null,sequence:0,saving:false,pending:false};
const latestPreview=new LatestPreview();
const panel=document.createElement('section');
panel.className='panel';
panel.innerHTML=`<h2>Change detection &amp; policy adaptation</h2>
<p id="active-policy" role="status">Loading the active policy…</p>
<div class="actions"><button id="new-manual">New fictional claim</button><button id="load-current">Load saved current claims</button><button id="adapt-audit">Download change history</button></div>
<p class="muted">Claim edits preview automatically after a short pause. Use “Save claim revision” to finalize them. Saved claims use the approved active policy.</p>
<details><summary>Propose a policy document change</summary>
<p>AI extracts a draft with supporting quotations. Review the complete configuration, impact and independent acceptance tests before approving activation. Text inside documents has no application authority.</p>
<form id="adapt-propose"><div class="fields"><div><label for="adapt-version">Proposed version</label><input id="adapt-version" required maxlength="100" placeholder="v2-draft-1"></div><div><label for="adapt-token">Policy-owner credential</label><input id="adapt-token" type="password" autocomplete="off" required></div></div>
<label for="adapt-file">New policy document (.txt or .docx)</label><input type="file" id="adapt-file" accept=".txt,.docx">
<label for="adapt-document">New policy text (or upload a Word document)</label><textarea id="adapt-document" rows="6"></textarea>
<button type="submit" class="primary">Interpret and propose</button></form>
<p id="adapt-proposal-status" role="status"></p><div id="adapt-proposals"></div>
<div id="adapt-review" hidden><div id="adapt-impact"></div><details><summary>Supporting text, draft rules and validation</summary><pre id="adapt-draft"></pre></details>
<label for="adapt-tests">Independent acceptance tests (JSON; see backend/ADAPTATION.md)</label><textarea id="adapt-tests" rows="6" spellcheck="false">[]</textarea>
<div class="actions"><button id="adapt-check">Run safety checks &amp; refresh impact</button><button id="adapt-check-download">Download safety report</button></div><pre id="adapt-checks"></pre>
<label for="adapt-reason">Owner review reason</label><textarea id="adapt-reason" rows="2"></textarea>
<label><input id="adapt-ack" type="checkbox"> I reviewed the source quotations, rule configuration, impact and independent expectations, and acknowledge the stated coverage limitations.</label>
<div class="actions"><button id="adapt-approve" disabled>Approve &amp; activate policy</button><button id="adapt-reject">Reject proposal</button></div></div></details>`;
document.querySelector('.toolbar').after(panel);
const changeBox=document.createElement('div');
changeBox.innerHTML=`<div id="claim-change" role="status" aria-live="polite"></div><div class="fields"><div><label for="claim-actor">Editor</label><input id="claim-actor" value="Local reviewer" maxlength="120"></div><div><label for="claim-reason">Revision reason</label><input id="claim-reason" placeholder="Describe the evidence update" maxlength="2000"></div></div><button id="save-revision" type="button" disabled>Save claim revision</button><details><summary>Saved evaluation history</summary><div id="evaluation-history"></div></details>`;
$('edit-form').after(changeBox);
$('edit-form').parentElement.querySelector('p').textContent='Validated edits preview automatically under the active policy. Saving creates one immutable revision; previews are temporary.';

function showImpact(report){
  if(!report){$('adapt-impact').textContent='No impact preview available for this invalid or stale proposal.';return;}
  $('adapt-impact').innerHTML=`<p><strong>${report.affected_open_claims}</strong> open claims affected; <strong>${report.recommendations_changed}</strong> recommendations change; ${report.closed_retained} closed decisions retained.</p><div class="table-scroll"><table><thead><tr><th>Case</th><th>Policy</th><th>Previous → proposed</th><th>Matched rule</th><th>Recheck</th></tr></thead><tbody>${report.rows.map(r=>`<tr><td>${esc(r.case_id)}</td><td>${esc(r.current_policy_version)} → ${esc(r.proposed_policy_version)}</td><td>${badge(r.recommendation_v1)} → ${badge(r.recommendation_v2)}</td><td>${esc(r.rule_v1)} → ${esc(r.rule_v2)}</td><td>${r.needs_recheck?'Yes':'No'}<details><summary>Why</summary>${esc(r.explanation)}</details></td></tr>`).join('')}</tbody></table></div>`;
}
function showProposal(p){
  adaptive.proposal=p;adaptive.checks=null;$('adapt-approve').disabled=true;$('adapt-review').hidden=false;
  $('adapt-proposal-status').textContent=`${p.old_version} → ${p.version}: ${p.status}${p.stale?' · baseline changed; fresh proposal required':''}. ${p.interpretation.summary}`;
  $('adapt-draft').textContent=JSON.stringify(p,null,2);$('adapt-checks').textContent='Safety checks and independently authored expectations are required before activation.';
  showImpact(p.impact);
}
async function refreshWorkspace(){
  const data=await api('/api/adaptation');adaptive.workspace=data;adaptive.sequence=data.event_sequence;
  $('active-policy').textContent=`Active policy: ${data.policy.version}. ${data.claims.length} saved claims. Official v1 remains immutable.`;
  $('adapt-proposals').innerHTML=data.proposals.map(p=>`<button type="button" data-proposal="${esc(p.proposal_id)}">${esc(p.version)} · ${esc(p.status)}</button>`).join(' ');
  return data;
}
async function loadCurrent(){
  const data=await refreshWorkspace();adaptive.live=true;adaptive.dirty=false;
  state.baselineText=JSON.stringify(data.policy);state.baselinePolicyId=data.policy.policy_id;state.baselineName='Approved active policy';
  $('baseline-note').textContent=`Active policy ${data.policy.version}`;state.saved=true;state.inputIssues=undefined;
  state.claims=data.claims.map(s=>s.claim);$('candidate').value='none';
  if(!state.claims.length){clearResults();message('No saved claims. Create a fictional claim or explicitly save a claim from your upload.');return;}
  const decisions=data.claims.map(s=>s.decision);
  const rows=decisions.map(d=>({case_id:d.case_id,recommendation_v1:d.recommendation,recommendation_v2:d.case_status==='closed'?d.recommendation:'',needs_recheck:false,rule_v1:d.primary_rule_id,rule_v2:d.case_status==='closed'?d.primary_rule_id:'',explanation:d.concise_explanation}));
  const columns=['case_id','recommendation_v1','recommendation_v2','needs_recheck','rule_v1','rule_v2','explanation'];
  const csvCell=v=>`"${String(v).replaceAll('"','""')}"`;
  state.result={claims:state.claims,decisions,rows,audit_cases:decisions.map(d=>({case_id:d.case_id,original:d})),errors:[],comparison:null,baseline_version:data.policy.version,csv:[columns.join(','),...rows.map(r=>columns.map(k=>csvCell(r[k])).join(','))].join('\n')};
  $('dataset').textContent='Saved current claims · immutable evaluation history';render();
  await select(state.claims.some(c=>c.case_id===state.selected)?state.selected:state.claims[0].case_id);
}

const selectBeforeAdaptation=select;
select=async function(id,index){
  latestPreview.invalidate();adaptive.preview=null;adaptive.dirty=false;$('save-revision').disabled=true;$('claim-change').textContent='';
  await selectBeforeAdaptation(id,index);
  if(state.selected!==id)return;
  $('evaluation-history').textContent='No saved evaluation history for this local claim.';
  if(adaptive.workspace?.claims.some(s=>s.claim.case_id===id)){
    const detail=await api('/api/adaptation/claims/'+encodeURIComponent(id));if(state.selected!==id)return;
    $('evaluation-history').innerHTML=`<p>Original: ${badge(detail.original_decision.recommendation)} · ${esc(detail.original_decision.policy_version)}</p>`+detail.history.map(h=>`<article>Revision ${h.revision} · ${esc(h.created_at)} · ${esc(h.decision.policy_version)}<br>${badge(h.change.previous_recommendation)} → ${badge(h.decision.recommendation)}<br>${esc(h.change.what_changed)}<br>${esc(h.change.reason)}</article>`).join('');
  }
};
function draftClaim(){return {...state.claims[state.index],...Object.fromEntries(new FormData($('edit-form')))};}
function previewWork(){const raw=draftClaim();return api('/api/adaptation/preview',{claim:raw,before:state.claims[state.index]}).then(r=>({...r,draft:raw}));}
function applyPreview(result){
  adaptive.preview=result;$('save-revision').disabled=(result.revision>=0 && state.claims[state.index]?.case_status==='closed') || adaptive.saving;
  $('claim-change').innerHTML=`<p><strong>Active-policy preview · not saved</strong></p><p>${esc(result.what_changed)}</p><p>${badge(result.previous_recommendation)} → ${badge(result.recommendation)}</p><p>Newly triggered rules: ${esc(result.newly_triggered_rules.join(', ')||'None')}</p><p>${esc(result.validation.unresolved_fields.length?'Unresolved: '+result.validation.unresolved_fields.join(', '):'Structured input validated.')}</p>`;
  $('why-decision').innerHTML=renderWhy(result.decision,null,result.draft);$('trace').textContent=JSON.stringify(result.decision,null,2);
}
$('edit-form').addEventListener('input',()=>{
  adaptive.dirty=true;adaptive.preview=null;$('save-revision').disabled=true;
  $('claim-change').textContent='Edits pending validation…';
  latestPreview.schedule(previewWork,applyPreview,e=>{$('claim-change').textContent=e.message;});
});
$('edit-form').onsubmit=event=>{event.preventDefault();latestPreview.invalidate();latestPreview.run(previewWork,applyPreview).catch(e=>message(e.message,true));};
$('save-revision').onclick=()=>task(async()=>{
  const p=adaptive.preview;if(!p)throw new Error('Wait for a valid current preview.');
  if(!$('claim-reason').value.trim())throw new Error('Enter the reason for this finalized revision.');
  adaptive.saving=true;$('save-revision').disabled=true;
  try{await api('/api/adaptation/claims',{claim:p.draft,expected_revision:p.revision,expected_policy_hash:p.active_policy_hash,request_id:crypto.randomUUID(),actor:$('claim-actor').value,reason:$('claim-reason').value});adaptive.dirty=false;await loadCurrent();message('Claim revision saved. The previous evaluation remains in history.');}
  finally{adaptive.saving=false;}
});
$('new-manual').onclick=()=>task(async()=>{
  const data=await refreshWorkspace();adaptive.live=false;state.saved=false;state.selected=null;state.inputIssues=undefined;
  state.baselineText=JSON.stringify(data.policy);$('baseline-note').textContent=`Active policy ${data.policy.version}`;$('candidate').value='none';
  state.claims=[{case_id:'MANUAL-'+crypto.randomUUID().slice(0,8),case_status:'open',claim_type:'motor_own_damage',repair_type:'standard',quote_eur:'1200',policy_active_on_incident:'true',incident_report_present:'true',itemized_quote_present:'true',injury_reported:'false',liability_disputed:'false',duplicate_flag:'false',evidence_conflict:'false',claim_summary:'Manually entered fictional claim'}];
  await assess();$('edit-form').parentElement.open=true;latestPreview.invalidate();await latestPreview.run(previewWork,applyPreview);message('Fictional draft created. Review its facts and explicitly save a revision.');
});
$('load-current').onclick=()=>task(loadCurrent);
$('adapt-audit').onclick=()=>task(async()=>download('change-history.json',JSON.stringify(await api('/api/adaptation/audit'),null,2),'application/json'));
$('adapt-proposals').onclick=e=>{const button=e.target.closest('[data-proposal]');if(button)task(async()=>showProposal(await api('/api/adaptation/proposals/'+encodeURIComponent(button.dataset.proposal))));};
let documentUpload=null;
$('adapt-file').onchange=()=>task(async()=>{
  const file=$('adapt-file').files[0];if(!file)return;if(file.size>1000000)throw new Error('Document must be smaller than 1 MB.');
  if(/\.docx$/i.test(file.name)){documentUpload=toBase64(await file.arrayBuffer());$('adapt-document').value='';$('adapt-document').disabled=true;}
  else {documentUpload=null;$('adapt-document').disabled=false;$('adapt-document').value=await file.text();}
});
$('adapt-propose').onsubmit=event=>{event.preventDefault();task(async()=>{
  await refreshWorkspace();$('adapt-proposal-status').textContent='Interpreting policy text…';
  const body={version:$('adapt-version').value,request_id:crypto.randomUUID(),expected_policy_hash:adaptive.workspace.active_policy_hash,...(documentUpload?{document_docx:documentUpload}:{document_text:$('adapt-document').value})};
  try {showProposal(await api('/api/adaptation/proposals',body,$('adapt-token').value));await refreshWorkspace();}
  catch(e){$('adapt-proposal-status').textContent=e.message;throw e;}
});};
$('adapt-tests').oninput=()=>{adaptive.checks=null;$('adapt-approve').disabled=true;};
$('adapt-check').onclick=()=>task(async()=>{
  if(!adaptive.proposal)throw new Error('Select a proposal first.');
  const report=await api('/api/adaptation/proposals/'+adaptive.proposal.proposal_id+'/check',{tests:JSON.parse($('adapt-tests').value)},$('adapt-token').value);
  adaptive.checks=report;$('adapt-checks').textContent=JSON.stringify(report.checks,null,2);showImpact(report.impact);$('adapt-approve').disabled=!report.checks.passed;
});
$('adapt-check-download').onclick=()=>{if(adaptive.checks)download('policy-safety-report.json',JSON.stringify(adaptive.checks,null,2),'application/json');};
async function reviewProposal(action){
  if(!adaptive.proposal)throw new Error('Select a proposal first.');
  const result=await api('/api/adaptation/proposals/'+adaptive.proposal.proposal_id+'/review',{
    action,reason:$('adapt-reason').value,tests:JSON.parse($('adapt-tests').value),acknowledge_limitations:$('adapt-ack').checked,
    expected_impact_hash:adaptive.checks?.impact_hash},$('adapt-token').value);
  if(result.status==='blocked'){$('adapt-checks').textContent=JSON.stringify(result.checks,null,2);$('adapt-approve').disabled=true;return;}
  $('adapt-token').value='';showProposal(result);await loadCurrent();message(action==='approve'?'Approved policy activated; open claims reevaluated and closed decisions retained.':'Policy proposal rejected.');
}
$('adapt-approve').onclick=()=>task(()=>reviewProposal('approve'));
$('adapt-reject').onclick=()=>task(()=>reviewProposal('reject'));
// Event messages carry only a sequence number. Pull state only when a new persisted event arrives.
refreshWorkspace().catch(e=>message(e.message,true));
const updates=new EventSource('/api/adaptation/events');
updates.addEventListener('change',async event=>{
  const sequence=JSON.parse(event.data).sequence;if(sequence<=adaptive.sequence)return;
  if(adaptive.dirty||adaptive.saving||state.busy){adaptive.pending=true;$('active-policy').textContent='Saved data changed. Reload current claims before saving; your draft is preserved.';return;}
  try{if(adaptive.live)await loadCurrent();else await refreshWorkspace();}catch(e){message(e.message,true);}
});
window.addEventListener('beforeunload',()=>updates.close());
const taskBeforeAdaptation=task;
task=async function(fn){
  await taskBeforeAdaptation(fn);
  if(adaptive.pending&&!adaptive.dirty&&!adaptive.saving&&!state.busy){
    adaptive.pending=false;
    try{if(adaptive.live)await loadCurrent();else await refreshWorkspace();}catch(e){message(e.message,true);}
  }
};
