'use strict';

const byId = id => document.getElementById(id);
const labels = {human_review: 'Human review', request_information: 'Request information', routine_processing: 'Routine processing'};
const money = value => new Intl.NumberFormat('en-IE', {style: 'currency', currency: 'EUR', maximumFractionDigits: 2}).format(value);
const date = value => new Date(value).toLocaleString();
const seen = new Set();
let cursor = null, selected = null, generation = 0;

function element(tag, text, className) {
  const node = document.createElement(tag);
  node.textContent = text;
  if (className) node.className = className;
  return node;
}

function clearCase() {
  selected = null;
  byId('heading').textContent = 'Claim detail';
  byId('detail').replaceChildren();
  byId('comparison').replaceChildren();
  byId('version-panel').hidden = true;
  byId('versions-result').replaceChildren();
  byId('proposal').hidden = true;
  byId('proposal').open = false;
  byId('case').hidden = true;
  byId('queue').hidden = false;
}

function clearInbox() {
  ++generation;
  cursor = null;
  seen.clear();
  byId('reference').value = '';
  clearCase();
  byId('rows').replaceChildren();
  byId('workspace').hidden = byId('more').hidden = true;
  byId('notice').textContent = '';
  setBusy(false);
}

function setBusy(busy) {
  document.querySelectorAll('button, #limit').forEach(control => control.disabled = busy);
}

async function request(action, fields, apply) {
  const sequence = ++generation;
  byId('notice').textContent = 'Loading…';
  setBusy(true);
  try {
    const response = await fetch('/api/incoming/' + action, {method: 'POST', cache: 'no-store',
      headers: {'Content-Type': 'application/json'}, body: JSON.stringify(fields)});
    const data = await response.json();
    if (sequence !== generation) return;
    if (!response.ok) {
      if (response.status === 403) clearInbox();
      byId('notice').textContent = data.error || 'Could not load the claim.';
      return;
    }
    byId('notice').textContent = '';
    apply(data);
  } catch {
    if (sequence === generation) byId('notice').textContent = 'Unable to reach the workbench. Please retry.';
  } finally {
    if (sequence === generation) setBusy(false);
  }
}

function loadPage(nextPage) {
  request('list', nextPage ? {cursor} : {}, data => {
    if (!nextPage) {
      seen.clear();
      byId('rows').replaceChildren();
      clearCase();
    }
    byId('workspace').hidden = false;
    cursor = data.next_cursor;
    byId('more').hidden = !cursor;
    for (const claim of data.claims) {
      if (seen.has(claim.reference)) continue;
      seen.add(claim.reference);
      const row = document.createElement('tr');
      const cell = document.createElement('td');
      const button = element('button', claim.reference, 'link ref');
      button.addEventListener('click', () => openClaim(claim.reference));
      cell.append(button);
      const handling = document.createElement('td');
      handling.append(routeBadge(claim.category.effective_recommendation));
      if (claim.category.effective_recommendation !== claim.category.recommendation) {
        handling.append(element('small', 'Reviewer correction'));
      }
      row.append(cell, handling, element('td', claim.category.rule_id || '—', 'optional ref'),
        element('td', claim.document_count, 'optional ref'),
        element('td', date(claim.submitted_at), 'optional date'));
      byId('rows').append(row);
    }
    if (!byId('rows').children.length) byId('notice').textContent = 'No submitted claims yet.';
  });
}

function downloadOriginal(position) {
  request('document', {reference: selected.reference, position}, data => {
    const bytes = Uint8Array.from(atob(data.content_base64), c => c.charCodeAt(0));
    const url = URL.createObjectURL(new Blob([bytes]));
    const link = document.createElement('a');
    link.href = url;
    link.download = data.name;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  });
}

function routeBadge(route) {
  return element('span', labels[route] || route || 'Awaiting assessment',
    'chip ' + (Object.hasOwn(labels, route) ? route : ''));
}

function panel(title) {
  const section = document.createElement('article');
  section.append(element('h2', title));
  return section;
}

function facts(entries) {
  const list = document.createElement('dl');
  for (const [label, value] of entries) {
    if (value == null || value === '') continue;
    list.append(element('dt', label), element('dd', value));
  }
  return list;
}

function claimPanels(data) {
  const left = document.createElement('div');
  const right = document.createElement('div');
  const assessment = panel('Recorded engine decision');
  const decision = data.evidence.decision;
  if (decision) {
    assessment.append(routeBadge(decision.recommendation));
    const why = decision.audit?.detail?.employee?.why || decision.explanation;
    if (why) assessment.append(element('p', why));
    const quote = data.evidence.quotes.at(-1);
    assessment.append(facts([
      ['Matched rule', decision.primary_rule_id || decision.matched_rule],
      ['Policy version', decision.policy_version],
      ['Latest quote', quote?.amount_eur != null ? money(quote.amount_eur) : null],
    ]));
  } else {
    assessment.append(element('p', 'No engine decision was recorded for this submission.'));
  }
  left.append(assessment);

  if (data.corrections.length) {
    const history = panel('Reviewer corrections');
    history.append(element('h3', 'Current handling step'), routeBadge(data.category.effective_recommendation));
    const list = document.createElement('ol');
    for (const entry of [...data.corrections].reverse()) {
      const item = document.createElement('li');
      item.append(element('strong', labels[entry.recommendation] || entry.recommendation),
        element('p', entry.reason), element('small', entry.reviewer + ' · ' + date(entry.created_at)));
      list.append(item);
    }
    history.append(list);
    left.append(history);
  }

  const files = panel('Original documents');
  const list = element('ul', '', 'files');
  data.documents.forEach((doc, index) => {
    const item = document.createElement('li');
    const button = element('button', 'Download ' + doc.name, 'link');
    button.addEventListener('click', () => downloadOriginal(doc.position ?? index));
    item.append(button, element('small', doc.kind.replaceAll('_', ' ')));
    list.append(item);
  });
  files.append(data.documents.length ? list : element('p', 'No documents submitted.'));
  right.append(files);
  const incident = panel('Claim details');
  const claimant = data.claimant;
  incident.append(facts([['Policy number', claimant.policy_number], ['Incident date', claimant.incident_date],
    ['Location', claimant.location], ['Submitted', date(data.submitted_at)]]));
  if (claimant.description) incident.append(element('p', claimant.description));
  if (data.next_action) incident.append(element('h3', 'Next action'), element('p', data.next_action.message));
  right.append(incident);
  return [left, right];
}

function openClaim(reference) {
  clearCase();
  request('detail', {reference}, data => {
    selected = data;
    byId('heading').textContent = data.reference;
    byId('queue').hidden = true;
    byId('case').hidden = false;
    byId('detail').replaceChildren(...claimPanels(data));
    byId('heading').focus();
    if (data.evidence.decision?.raw_evidence && data.evidence.decision.input_fingerprint) {
      byId('simulate').reset();
      byId('version-panel').hidden = false;
      byId('proposal').hidden = false;
    }
  });
}

byId('lookup').onsubmit = event => {
  event.preventDefault();
  const reference = byId('reference').value.trim();
  if (!/^CLM-[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(reference)) {
    byId('notice').textContent = 'Enter the full CLM- reference from the claim receipt.';
    byId('reference').focus();
    return;
  }
  openClaim('CLM-' + reference.slice(4).toLowerCase());
};
byId('back').onclick = () => {
  const reference = selected?.reference;
  clearCase();
  byId('notice').textContent = '';
  const rowButton = Array.from(byId('rows').querySelectorAll('button')).find(b => b.textContent === reference);
  history.replaceState(null, '', location.pathname);
  if (!seen.size) loadPage(false);
  (rowButton || byId('reference')).focus();
};
byId('refresh').onclick = () => loadPage(false);
byId('more').onclick = () => loadPage(true);
window.addEventListener('pagehide', clearInbox);
window.addEventListener('pageshow', () => {
  const reference = location.hash.slice(1);
  if (/^CLM-[0-9a-f-]{36}$/i.test(reference)) openClaim(reference);
  else loadPage(false);
});
byId('versions').onclick = () => {
  const box = byId('versions-result');
  box.replaceChildren();
  request('policy-replay', {reference: selected.reference, expected_revision: selected.category.revision,
    target_version: 'v2'}, result => {
    for (const [title, item] of [['Recorded', result.recorded], [result.closed_retained ? 'Retained' : 'Preview', result.proposed]]) {
      box.append(element('h3', title + ' · ' + item.version), routeBadge(item.recommendation),
        element('p', item.why), element('code', item.rule));
    }
    if (result.impacted_rules.length) box.append(element('p', 'Affected rules · ' + result.impacted_rules.join(', ')));
    box.append(element('p', result.closed_retained ? 'Closed claim · historical decision retained.'
      : result.needs_recheck ? 'Open claim · needs recheck.' : 'No recheck needed.'));
  });
};
byId('limit').oninput = () => byId('comparison').replaceChildren();
byId('simulate').onsubmit = event => {
  event.preventDefault();
  byId('comparison').replaceChildren();
  request('replay', {reference: selected.reference, expected_revision: selected.category.revision,
    quote_limit_eur: byId('limit').valueAsNumber}, result => {
    for (const [title, limit, decision] of [
      ['Recorded policy', result.recorded_limit_eur, result.recorded],
      ['Simulated policy', result.proposed_limit_eur, result.proposed]]) {
      const card = document.createElement('article');
      card.className = 'why-summary ' + decision.recommendation;
      card.append(element('h3', title + ' · ' + money(limit)),
        element('strong', labels[decision.recommendation]), element('p', decision.why),
        element('code', decision.rule));
      byId('comparison').append(card);
    }
    byId('notice').textContent = 'Simulation complete using the recorded claim evidence.';
  });
};
