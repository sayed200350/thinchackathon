'use strict';

window.ClaimAssistance = (() => {
  function element(tag, text) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function addStyles() {
    if (document.getElementById('claim-assistance-styles')) return;
    const css = element('style', `
      .photo-guide, .photo-note, .translation-review { margin: 1rem 0; }
      .photo-guide .examples { display:grid; gap:12px; grid-template-columns:repeat(auto-fit,minmax(min(100%,135px),1fr)); }
      .photo-guide figure { margin:0; min-width:0; }
      .photo-guide img { display:block; width:100%; height:auto; aspect-ratio:3/2; border-radius:7px; }
      .photo-guide figcaption { font-size:14px; padding-top:5px; }
      .photo-guide figcaption strong { display:block; }
      .photo-note { flex-basis:100%; min-width:0; }
      .photo-note [hidden] { display:none; }
      .photo-note dl { display:flex; flex-wrap:wrap; gap:8px 24px; margin:8px 0; }
      .photo-note dl dt, .translation-review .source-page { color:var(--muted); font-size:14px; }
      .photo-note dl dd { margin:0; font-weight:600; }
      .photo-note p { margin:8px 0; }
      .photo-note label, .translation-review label { display:block; margin:10px 0; }
      .photo-note label > span, .translation-review label > span { font-weight:600; display:block; margin-bottom:4px; }
      .translation-review { border-top:1px solid var(--line); padding-top:8px; }
      .translation-review blockquote { margin:0; padding:8px 12px; border-inline-start:3px solid var(--accent); white-space:pre-wrap; overflow-wrap:anywhere; }
      .translation-review .actions { margin-top:8px; }
      .translation-review .confirmation { font-size:14px; color:var(--accent); font-weight:600; min-height:1.5em; margin:8px 0; }
    `);
    css.id = 'claim-assistance-styles';
    document.head.append(css);
  }

  function photoGuide(container) {
    addStyles();
    const section = element('section');
    section.className = 'photo-guide';
    section.setAttribute('aria-label', 'Photo examples');
    section.append(element('h3', 'How to photograph the damage'));
    const examples = element('div');
    examples.className = 'examples';
    for (const [name, title, alt, hint] of [
      ['wide.jpg', 'Wide shot', 'A parked car with the damaged rear door visible in context.', 'Step back to show the whole vehicle.'],
      ['close-up.jpg', 'Damage close-up', 'Three scratches on the rear door beside the wheel arch.', 'Show the damage and a nearby feature for scale.']
    ]) {
      const figure = element('figure');
      const image = element('img');
      image.src = '/examples/photo-guide/' + name;
      image.alt = alt;
      image.width = 660;
      image.height = 440;
      const caption = element('figcaption');
      caption.append(element('strong', title), document.createTextNode(hint));
      figure.append(image, caption);
      examples.append(figure);
    }
    section.append(examples);
    container.append(section);
  }

  // Read only the standard camera capture timestamp. A browser's lastModified
  // may be the download or export time, and is never substituted for EXIF.
  async function photoCaptureDate(file) {
    if (!file || file.size > 12 * 1024 * 1024) return null;
    try {
      const view = new DataView(await file.arrayBuffer());
      const ascii = (at, size) => {
        let result = '';
        for (let i = 0; i < size; i++) result += String.fromCharCode(view.getUint8(at + i));
        return result;
      };
      function tiff(begin, end) {
        const order = ascii(begin, 2);
        if (order !== 'II' && order !== 'MM') return null;
        const le = order === 'II';
        const u16 = offset => view.getUint16(offset, le);
        const u32 = offset => view.getUint32(offset, le);
        if (begin + 8 > end || u16(begin + 2) !== 42) return null;
        const offsets = [u32(begin + 4)];
        const visited = new Set();
        while (offsets.length && visited.size < 4) {
          const offset = offsets.pop();
          if (offset < 8 || visited.has(offset)) continue;
          visited.add(offset);
          const dir = begin + offset;
          if (dir + 2 > end) return null;
          const count = u16(dir);
          if (dir + 2 + count * 12 > end) return null;
          for (let i = 0; i < count; i++) {
            const pos = dir + 2 + i * 12;
            const tag = u16(pos), type = u16(pos + 2), size = u32(pos + 4), pointer = u32(pos + 8);
            if (tag === 0x8769 && type === 4 && size === 1) offsets.push(pointer);
            if (tag !== 0x9003 || type !== 2 || (size !== 19 && size !== 20) || begin + pointer + 19 > end) continue;
            const stamp = ascii(begin + pointer, 19);
            const m = /^(\d{4}):(\d{2}):(\d{2}) (\d{2}):(\d{2}):(\d{2})$/.exec(stamp);
            if (!m) continue;
            const day = m[1] + '-' + m[2] + '-' + m[3];
            const utc = new Date(day + 'T' + m[4] + ':' + m[5] + ':' + m[6] + 'Z');
            if (Number.isFinite(utc.valueOf()) && utc.toISOString().slice(0, 10) === day) return day;
          }
        }
        return null;
      }
      if (view.byteLength >= 8 && ascii(1, 3) === 'PNG' && view.getUint8(0) === 0x89) {
        for (let pos = 8; pos + 12 <= view.byteLength;) {
          const end = pos + 8 + view.getUint32(pos);
          if (end + 4 > view.byteLength) break;
          if (ascii(pos + 4, 4) === 'eXIf') return tiff(pos + 8, end);
          pos = end + 4;
        }
      } else if (view.byteLength >= 2 && view.getUint16(0) === 0xffd8) {
        let pos = 2;
        while (pos + 3 <= view.byteLength && view.getUint8(pos) === 0xff) {
          while (pos < view.byteLength && view.getUint8(pos) === 0xff) pos++;
          if (pos + 3 > view.byteLength) break;
          const marker = view.getUint8(pos);
          if (marker === 0xda || marker === 0xd9) break;
          const len = view.getUint16(pos + 1);
          const end = pos + 1 + len;
          if (len < 2 || end > view.byteLength) break;
          if (marker === 0xe1 && len >= 8 && ascii(pos + 3, 6) === 'Exif\0\0') {
            const day = tiff(pos + 9, end);
            if (day) return day;
          }
          pos = end;
        }
      }
    } catch {
      // Malformed EXIF does not prevent attaching otherwise supported image bytes.
    }
    return null;
  }

  function label(name, control) {
    const wrap = element('label');
    wrap.append(element('span', name), control);
    return wrap;
  }

  function datePair(name, value) {
    const pair = element('div');
    pair.append(element('dt', name), element('dd', value));
    return pair;
  }

  function photoDetails(container, doc, incidentDate, onChange) {
    addStyles();
    const note = {view:'', exif_date:null, manual_date:'', explanation:'', ...doc.assistance};
    const section = element('section');
    section.className = 'photo-note';
    section.setAttribute('aria-label', 'Photo details for ' + doc.name);
    const dates = element('dl');
    dates.append(datePair('Incident date', incidentDate || 'Unknown'),
                 datePair('Photo date from camera', note.exif_date || 'Unavailable'));
    section.append(dates);
    const select = element('select');
    for (const [id,text] of [['','Unspecified'],['wide','Wide shot'],['close_up','Damage close-up']]) {
      select.add(new Option(text, id));
    }
    select.value = note.view;
    const manual = element('input');
    manual.type = 'date';
    manual.value = note.manual_date;
    const explanation = element('textarea');
    explanation.maxLength = 1000;
    explanation.rows = 2;
    explanation.value = note.explanation;
    const detail = label('Explain the difference', explanation);
    const mismatch = element('p', 'These dates differ. You can add a note for the reviewer.');
    function refresh() {
      const day = note.exif_date || note.manual_date;
      mismatch.hidden = !(day && incidentDate && day !== incidentDate);
      detail.hidden = mismatch.hidden && !note.explanation;
    }
    function changed() {
      refresh();
      if (onChange) onChange({...note});
    }
    if (onChange) {
      select.addEventListener('change', () => { note.view = select.value; changed(); });
      section.append(label('Photo view', select));
      if (!note.exif_date) {
        manual.addEventListener('input', () => { note.manual_date = manual.value; changed(); });
        section.append(label('Photo date supplied by you', manual));
      }
      explanation.addEventListener('input', () => { note.explanation = explanation.value; changed(); });
      section.append(mismatch, detail);
    } else {
      if (note.view) section.append(element('p', select.selectedOptions[0].text));
      if (note.manual_date) dates.append(datePair('Photo date supplied by you', note.manual_date));
      section.append(mismatch);
      if (note.explanation) section.append(element('p', note.explanation));
    }
    refresh();
    container.append(section);
  }

  function translationReview(container, translation, onChange) {
    if (!translation) return;
    addStyles();
    const value = {...translation};
    const section = element('section');
    section.className = 'translation-review';
    section.setAttribute('aria-label', 'German and English report review');
    section.append(element('h3', 'Check the German report'));
    const source = element('p', 'German original · page ' + value.page);
    source.className = 'source-page';
    const original = element('blockquote', value.original);
    original.lang = 'de';
    section.append(source, original);
    if (!onChange) {
      if (value.confirmed) section.append(element('h4', 'Confirmed English translation'), element('p', value.english));
      else section.append(element('p', 'Original German retained.'));
      container.append(section);
      return;
    }
    const input = element('textarea');
    input.rows = 3;
    input.maxLength = 4000;
    input.value = value.english;
    const sourceHint = element('p', value.source === 'manual' && !value.english
        ? 'An English suggestion is unavailable. You can provide a translation or keep the German original.'
        : 'Compare the wording, then confirm your translation or keep the German original.');
    section.append(sourceHint, label('English translation', input));
    const actions = element('div');
    actions.className = 'actions';
    const confirm = element('button', 'Confirm English translation');
    const useOriginal = element('button', 'Continue with original German');
    for (const button of [confirm, useOriginal]) {
      button.type = 'button';
      button.className = 'btn';
      actions.append(button);
    }
    const message = element('p');
    message.className = 'confirmation';
    message.setAttribute('role', 'status');
    function refresh() {
      confirm.disabled = !input.value.trim();
      confirm.setAttribute('aria-pressed', String(value.confirmed));
      useOriginal.setAttribute('aria-pressed', String(value.use_original || false));
      message.textContent = value.confirmed ? 'English translation confirmed.'
        : value.use_original ? 'The German original will be used.' : '';
    }
    function update(confirmed, german) {
      value.confirmed = confirmed;
      value.use_original = german;
      refresh();
      onChange({...value});
    }
    input.addEventListener('input', () => {
      value.english = input.value;
      value.source = 'manual';
      update(false, false);
    });
    confirm.addEventListener('click', () => update(true, false));
    useOriginal.addEventListener('click', () => update(false, true));
    refresh();
    section.append(actions, message);
    container.append(section);
  }

  return {photoGuide, photoDetails, photoCaptureDate, translationReview};
})();
