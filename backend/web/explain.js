'use strict';
// "Why this decision?" panel. Renders ONLY the explanation the engine recorded with each decision
// (decision.audit.detail). It holds no policy rules, thresholds or classification logic of its own.
const STATUS_CLASS = {'Triggered':'st-trig','Satisfied / Not triggered':'st-ok','Missing / Unknown':'st-unk','Not evaluated':'st-ne'};
const RESULT_CLASS = {matched:'st-trig',not_matched:'st-ok',unknown:'st-unk'};
const OP_SYMBOL = {eq:'=',ne:'≠',gt:'>',ge:'≥',lt:'<',le:'≤',in:'in',is_known:'is known',is_missing:'is missing'};
const pill = (text, cls) => `<span class="pill ${cls||''}">${esc(text)}</span>`;
const ruleCondition = node => node && node.field ? `${node.field} ${OP_SYMBOL[node.op]||node.op}${node.value===undefined?'':' '+JSON.stringify(node.value)}` : JSON.stringify(node);
const known = value => value===null||value===undefined ? 'Unknown — information needed' : String(value);

function conditionCell(rule){
  if(!rule.conditions.length) return `<span class="muted">${esc(rule.expression)}</span>`;
  return rule.conditions.map(c=>{
    const original = c.original_value===null||c.original_value===undefined||c.original_value==='' ? 'blank' : `"${c.original_value}"`;
    const unknown = c.actual===null||c.actual===undefined;
    const rhs = c.expected_display===null||c.expected_display===undefined ? '' : ' '+esc(c.expected_display);
    return `<div class="cond"><code>${esc(c.field)} ${esc(c.operator)}${rhs}</code><br><small>Actual: <strong>${esc(unknown?'Unknown — information needed':c.actual_display)}</strong> <span class="muted">(original ${esc(original)}${c.state!=='known'?'; '+esc(c.issue||c.state):''})</span></small></div>`;
  }).join('');
}

function factorHtml(f){
  const facts = f.facts.map(x=>`<li><strong>${esc(x.label)}:</strong> ${esc(x.value)} <span class="muted">— ${esc(x.comparison)}</span></li>`).join('');
  const blocks = f.blocks_rule_ids && f.blocks_rule_ids.length ? `<p class="muted">Cannot be evaluated until known: ${esc(f.blocks_rule_ids.join(', '))}</p>` : '';
  return `<article class="factor ${STATUS_CLASS[f.status]||''}">${pill(f.status,STATUS_CLASS[f.status])} <strong>${esc(f.title)}</strong>${f.rule_id?` <code>${esc(f.rule_id)}</code>`:''}${facts?`<ul>${facts}</ul>`:''}${blocks}</article>`;
}

function rulesTable(d){
  const body = d.rules.map(r=>`<tr class="${r.role==='decisive'?'decisive':''}"><td><code>${esc(r.rule_id)}</code><br><small>${esc(r.policy_version)}${r.built_in?' · built-in step':' · priority '+esc(r.priority)}</small><br>${esc(r.description)}</td><td>${conditionCell(r)}</td><td>${pill(r.status_label,RESULT_CLASS[r.result])}<br><small>${esc(r.result)}</small></td><td>${esc(r.role?({decisive:'Decisive',corroborating:'Also matched (corroborating)',lower_priority:'Matched, lower priority',unresolved:'Unresolved — information needed',not_applicable:'Not applicable (not triggered)'}[r.role]||r.role):'')}<br><small class="muted">${esc(names[r.route]||r.route)}</small></td></tr>`).join('');
  return `<div class="table-scroll"><table class="rules"><thead><tr><th>Rule</th><th>Condition and actual value</th><th>Result</th><th>Role</th></tr></thead><tbody>${body}</tbody></table></div>`;
}

function comparisonHtml(comparison, claim){
  if(!comparison) return '';
  const cd = comparison.candidate && comparison.candidate.audit && comparison.candidate.audit.detail;
  const diff = comparison.version_differences || {};
  const lines = [];
  (diff.changed_rules||[]).forEach(r=>lines.push(`<li><code>${esc(r.id)}</code> changed: ${esc(ruleCondition(r.before.if))} → <strong>${esc(ruleCondition(r.after.if))}</strong></li>`));
  (diff.added_rules||[]).forEach(r=>lines.push(`<li><code>${esc(r.id)}</code> added: ${esc(r.reason)} (${esc(ruleCondition(r.if))})</li>`));
  (diff.removed_rules||[]).forEach(r=>lines.push(`<li><code>${esc(r.id)}</code> removed: ${esc(r.reason)}</li>`));
  const closed = comparison.closed_retained || claim.case_status==='closed';
  return `<section class="why-compare"><h3>Under ${esc(state.result.candidate_version)} (comparison)</h3>
    ${closed?'<p class="muted"><strong>Closed claim:</strong> its v1 recommendation is retained as the historical outcome. The candidate result below is a hypothetical comparison only.</p>':''}
    <p>${badge(comparison.candidate.recommendation)} ${comparison.needs_recheck?pill('Recheck needed','st-unk'):pill('No recheck needed','st-ok')}</p>
    ${cd?.employee?`<p><strong>Why:</strong> ${esc(cd.employee.why)}</p><p><strong>Next step:</strong> ${esc(cd.employee.next_step)}</p>${cd.employee.notes.map(n=>`<p class="muted">${esc(n)}</p>`).join('')}`:`<p>${esc(cd?.summary || comparison.candidate.explanation)}</p>`}
    ${lines.length?`<p><strong>Rules that changed and affect this claim</strong></p><ul>${lines.join('')}</ul>`:'<p class="muted">None of the changed rules affects this claim.</p>'}
  </section>`;
}

function renderWhy(decision, comparison, claim){
  const d = decision.audit && decision.audit.detail;
  if(!d) return `<p class="muted">This stored decision was recorded before the explanation panel existed. Its original text is retained unchanged:</p><p>${esc(decision.explanation)}</p>`;
  const closed = claim.case_status==='closed';
  const employee = d.employee;
  const also = d.corroborating_rule_ids.length ? ` · Also matched: <code>${d.corroborating_rule_ids.map(esc).join('</code>, <code>')}</code>` : '';
  const counter = d.counterfactuals.length
    ? `<details><summary>What could change the outcome?</summary><p class="muted">Hypothetical only. Each example was re-checked with the same decision engine on a copy of this claim; the real evidence is unchanged.</p><ul>${d.counterfactuals.map(c=>`<li>${esc(c.text)}</li>`).join('')}</ul></details>` : '';
  return `<section class="why-summary ${esc(d.recommendation)}">
      <div class="why-head">${badge(d.recommendation)}${closed?' '+pill('Closed claim — historical outcome','st-ne'):''}</div>
      <p class="why-text"><strong>Why:</strong> ${esc(employee?.why || d.summary)}</p>
      <p class="why-text"><strong>Next step:</strong> ${esc(closed?'Keep the recorded decision. This claim is closed.':employee?.next_step || d.meaning)}</p>
      ${(employee?.notes || []).map(n=>`<p class="muted">${esc(n)}</p>`).join('')}
      <p class="muted">${esc(employee?.policy_basis || 'Policy '+d.policy_version)} · <a href="#policy-checks">View policy checks</a></p>
    </section>
    <details id="policy-checks"><summary>Policy checks and supporting facts</summary><p class="chips">${pill('Policy '+d.policy_version)} <span>Decisive rule: <code>${d.decisive_rule_ids.map(esc).join('</code>, <code>')}</code>${also}</span></p>
    <h3>Key decision factors</h3>${d.factors.map(factorHtml).join('')||'<p class="muted">No factors recorded.</p>'}
    <p class="muted">${esc(d.precedence.text)}</p><p class="muted">${esc(d.evaluation_mode)}</p>${rulesTable(d)}<p class="muted">Policy hash ${esc(d.policy_hash)}</p></details>
    <details><summary>Why not the other outcomes?</summary>${d.why_not.map(w=>`<p><strong>${esc(w.label)}:</strong> ${esc(w.text)}</p>`).join('')}</details>
    ${counter}${comparisonHtml(comparison, claim)}`;
}
