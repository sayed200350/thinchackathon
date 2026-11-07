'use strict';
// Run from the repository root: node backend/tests/test_employee_view.js
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {execFileSync} = require('node:child_process');
const decisions = JSON.parse(execFileSync('python', ['-c',
  "import csv,json; from engine import decide; print(json.dumps([decide(r) for r in csv.DictReader(open('data/taktile/labelled_development_cases.csv',encoding='utf-8-sig'))]))"
], {encoding:'utf8'}));
const context = vm.createContext({});
vm.runInContext(fs.readFileSync('backend/web/workbench.js', 'utf8').split('async function api')[0], context);
vm.runInContext(fs.readFileSync('backend/web/explain.js', 'utf8'), context);
for (const decision of decisions) {
  context.decision = decision;
  const html = vm.runInContext('renderWhy(decision, null, decision)', context);
  const overview = html.split('<details')[0];
  assert.match(overview, /<strong>Why:<\/strong>/);
  assert.match(overview, /<strong>Next step:<\/strong>/);
  assert.match(overview, /Policy v1/);
  assert.doesNotMatch(overview, /<code>|Deterministic|quote_eur|incident_report_present/);
  assert.ok(!overview.includes(decision.primary_rule_id));
  assert.match(html, /<details id="policy-checks">/); // audit starts collapsed
  assert.ok(html.includes(decision.primary_rule_id)); // still available for inspection
  if (decision.case_status === 'closed') assert.match(overview, /This claim is closed/);
}
// Uploaded policy wording must be escaped before being inserted into HTML.
context.decision = structuredClone(decisions[0]);
context.decision.audit.detail.employee.why = '<img src=x onerror=alert(1)>';
const escaped = vm.runInContext('renderWhy(decision, null, decision)', context);
assert.ok(!escaped.includes('<img'));
assert.ok(escaped.includes('&lt;img'));
console.log('Employee view: 14 cases, collapsed audit, closed claims, and escaping passed.');
