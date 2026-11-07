'use strict';

const byId = id => document.getElementById(id);
const labels = {human_review: 'Human review', request_information: 'Request information', routine_processing: 'Routine processing'};
const money = value => new Intl.NumberFormat('en-IE', {style: 'currency', currency: 'EUR', maximumFractionDigits: 2}).format(value);
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
  byId('simulate').hidden = true;
}

function clearInbox() {
  ++generation;
  cursor = null;
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
      byId('rows').replaceChildren();
      clearCase();
    }
    byId('workspace').hidden = false;
    cursor = data.next_cursor;
    byId('more').hidden = !cursor;
    for (const claim of data.claims) {
      const row = document.createElement('tr');
      const cell = document.createElement('td');
      const button = element('button', claim.reference);
      button.addEventListener('click', () => openClaim(claim.reference));
      cell.append(button, element('small', new Date(claim.submitted_at).toLocaleString()));
      row.append(cell, element('td', labels[claim.category.effective_recommendation] || 'Awaiting assessment'));
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

function openClaim(reference) {
  clearCase();
  request('detail', {reference}, data => {
    selected = data;
    byId('heading').textContent = data.reference;
    const box = byId('detail');
    const decision = data.evidence.decision;
    box.append(element('h3', 'Current handling step'), element('strong',
      labels[data.category.effective_recommendation] || 'Awaiting assessment'));
    if (decision) {
      box.append(element('h3', 'Recorded engine assessment'),
        element('p', decision.audit?.detail?.employee?.why || decision.explanation),
        element('code', [decision.primary_rule_id || decision.matched_rule, decision.policy_version].join(' · ')));
    }
    const quote = data.evidence.quotes.at(-1);
    if (quote?.amount_eur != null) box.append(element('p', 'Latest quote · ' + money(quote.amount_eur)));
    if (data.next_action) box.append(element('h3', 'Next action'), element('p', data.next_action.message));
    if (data.documents.length) {
      box.append(element('h3', 'Original documents'));
      data.documents.forEach((doc, index) => {
        const button = element('button', 'Download ' + doc.name);
        button.addEventListener('click', () => downloadOriginal(doc.position ?? index));
        box.append(button);
      });
    }
    if (decision?.raw_evidence && decision.input_fingerprint) {
      byId('simulate').reset();
      byId('simulate').hidden = false;
    } else {
      box.append(element('p', 'This submission has no saved engine evidence to replay.', 'muted'));
    }
  });
}

byId('refresh').onclick = () => loadPage(false);
byId('more').onclick = () => loadPage(true);
window.addEventListener('pagehide', clearInbox);
window.addEventListener('pageshow', () => loadPage(false));
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
