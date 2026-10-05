(function () {
  var docs = [];        // brief list from GET /api/documents
  var sel = null;       // selected document id
  var current = null;   // full detail of the selected document
  var searchTimer = null;

  var $ = function (id) { return document.getElementById(id); };

  var STATE_LABELS = { ok: 'Read', missing: 'Missing', unclear: 'Unclear', corrected: 'Corrected' };
  var STATE_TAGS = { ok: 'ok', missing: 'bad', unclear: 'warn', corrected: 'info' };

  function msg(t, c) {
    var m = $('msg');
    m.textContent = t;
    m.className = 'msg show ' + c;
  }

  function fmt(n) {
    return n < 1024 ? n + ' B' : n < 1048576 ? (n / 1024).toFixed(1) + ' KB' : (n / 1048576).toFixed(1) + ' MB';
  }

  function human(name) {
    var s = name.replace(/_/g, ' ');
    return s.charAt(0).toUpperCase() + s.slice(1);
  }

  function date(iso) {
    return iso ? new Date(iso).toLocaleString() : '';
  }

  function el(tag, cls, txt) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (txt != null) e.textContent = txt;
    return e;
  }

  function button(label, cls, onClick) {
    var b = el('button', cls, label);
    b.type = 'button';
    b.onclick = onClick;
    return b;
  }

  async function api(url, options) {
    options = options || {};
    options.headers = Object.assign({ 'Accept': 'application/json' }, options.headers || {});
    var res = await fetch(url, options);
    if (res.status === 401) { window.location.href = '/login'; throw new Error('Not authenticated'); }
    var data = await res.json().catch(function () { return {}; });
    return { ok: res.ok, status: res.status, data: data };
  }

  // ---------------------------------------------------------------- list
  async function fetchDocs() {
    var q = $('q').value.trim();
    var r = await api('/api/documents' + (q ? '?q=' + encodeURIComponent(q) : ''));
    docs = r.ok ? r.data : [];
    renderList(q);
  }

  function statusTag(d) {
    if (d.status === 'failed') return ['bad', 'Unreadable'];
    if (d.reviewed) return ['ok', 'Reviewed'];
    return ['warn', 'Needs review'];
  }

  function renderList(q) {
    $('cnt').textContent = '(' + docs.length + ')';
    var t = $('tbl');
    t.innerHTML = '';
    var h = el('div', 'tr h');
    ['Document', 'Type', 'Size', 'Status'].forEach(function (x) { h.appendChild(el('span', null, x)); });
    t.appendChild(h);

    if (!docs.length) {
      t.appendChild(el('div', 'empty', q ? 'Nothing matches “' + q + '”.' : 'No documents yet. Upload a PDF or DOCX to get started.'));
    }

    docs.forEach(function (d) {
      var row = el('button', 'tr' + (d.id === sel ? ' sel' : ''));
      row.type = 'button';
      row.appendChild(el('span', 'n', d.filename));
      row.appendChild(el('span', null, d.doc_type_label || '—'));
      row.appendChild(el('span', null, fmt(d.size)));
      var s = statusTag(d);
      row.appendChild(el('span', 'tag ' + s[0], s[1]));
      row.onclick = function () { select(d.id); };
      t.appendChild(row);
    });
  }

  async function select(id) {
    sel = id;
    renderList($('q').value.trim());
    var r = await api('/api/documents/' + id);
    current = r.ok ? r.data : null;
    renderDetail();
  }

  async function refresh() {
    await fetchDocs();
    if (sel) await select(sel);
  }

  // ---------------------------------------------------------------- upload
  async function handle(file) {
    if (!file) return;
    var ext = (file.name.split('.').pop() || '').toLowerCase();
    if (ext !== 'pdf' && ext !== 'docx') { msg('Unsupported file format. Please upload a PDF or DOCX file.', 'err'); return; }
    if (file.size === 0) { msg('The file is empty.', 'err'); return; }

    msg('Uploading and reading “' + file.name + '”…', 'info');
    var fd = new FormData();
    fd.append('file', file);
    try {
      var r = await api('/api/documents', { method: 'POST', body: fd });
      if (!r.ok) { msg(r.data.error || 'Upload failed.', 'err'); return; }
      msg(r.data.message, r.data.status === 'failed' ? 'err' : 'ok');
      sel = r.data.id;
      await fetchDocs();
      current = r.data;
      renderDetail();
    } catch (err) {
      if (err.message !== 'Not authenticated') msg('Could not reach the server. Try again.', 'err');
    }
  }

  // ---------------------------------------------------------------- detail
  function renderDetail() {
    var d = $('detail');
    d.innerHTML = '';
    var r = current;
    if (!r) { d.className = 'detail'; return; }
    d.className = 'detail show';

    d.appendChild(el('h3', null, r.filename));
    var m = el('div', 'meta');
    [r.file_type, fmt(r.size), r.text ? r.text.split(/\s+/).length + ' words' : null, date(r.uploaded_at)]
      .forEach(function (x) { if (x) m.appendChild(el('span', null, x)); });
    d.appendChild(m);

    d.appendChild(classificationBlock(r));
    if (r.status === 'failed') {
      d.appendChild(el('div', 'msg show err', r.error || 'The document could not be read.'));
    } else {
      d.appendChild(fieldsBlock(r));
      d.appendChild(summaryBlock(r));
      var det = el('details', 'raw');
      det.appendChild(el('summary', null, 'Extracted text'));
      det.appendChild(el('pre', null, r.text));
      d.appendChild(det);
    }
    d.appendChild(actions(r));
  }

  function classificationBlock(r) {
    var box = el('section', 'card-sec');
    box.appendChild(el('div', 'eyebrow', 'DOCUMENT TYPE'));
    var c = r.classification;
    var line = el('div', 'cls');
    if (c) {
      line.appendChild(el('strong', 'cls-type', c.label));
      if (c.type !== 'other') {
        line.appendChild(el('span', 'conf', Math.round(c.confidence * 100) + '% confidence'));
      }
      line.appendChild(el('span', 'method', c.method === 'llm' ? 'AI model' : 'Rule-based'));
    } else {
      line.appendChild(el('span', null, 'Not classified'));
    }
    box.appendChild(line);
    if (c && c.message) box.appendChild(el('p', 'hint', c.message));
    return box;
  }

  function fieldsBlock(r) {
    var box = el('section', 'card-sec');
    box.appendChild(el('div', 'eyebrow', 'EXTRACTED INFORMATION'));
    if (!r.fields.length) {
      box.appendChild(el('p', 'hint', 'No fields are extracted for this document type.'));
      return box;
    }
    var problems = r.fields.filter(function (f) { return f.state === 'missing' || f.state === 'unclear'; }).length;
    box.appendChild(el('p', 'hint', problems
      ? problems + ' field(s) need your attention. Missing fields are left empty — we never fill them in for you.'
      : 'Check that everything was read correctly.'));

    var grid = el('div', 'fgrid');
    var inputs = {};
    r.fields.forEach(function (f) {
      var row = el('label', 'fld ' + f.state);
      var top = el('span', 'fld-top');
      top.appendChild(el('span', 'fld-name', human(f.name)));
      top.appendChild(el('span', 'tag ' + STATE_TAGS[f.state], STATE_LABELS[f.state]));
      row.appendChild(top);
      var inp = el('input', 'f');
      inp.value = f.value || '';
      inp.placeholder = f.state === 'missing' ? 'Not found in the document' : '';
      inp.dataset.orig = f.value || '';
      inputs[f.name] = inp;
      row.appendChild(inp);
      grid.appendChild(row);
    });
    box.appendChild(grid);

    var save = button('Save corrections', 'btn sm', async function () {
      var changed = {};
      Object.keys(inputs).forEach(function (k) {
        if (inputs[k].value.trim() !== inputs[k].dataset.orig) changed[k] = inputs[k].value.trim();
      });
      if (!Object.keys(changed).length) { msg('No changes to save.', 'info'); return; }
      var res = await api('/api/documents/' + r.id + '/fields', {
        method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ fields: changed })
      });
      if (!res.ok) { msg(res.data.error || 'Could not save.', 'err'); return; }
      msg('Corrections saved.', 'ok');
      current = res.data;
      renderDetail();
    });
    var bar = el('div', 'acts');
    bar.appendChild(save);
    box.appendChild(bar);
    return box;
  }

  function summaryBlock(r) {
    var box = el('section', 'card-sec');
    box.appendChild(el('div', 'eyebrow', 'SUMMARY'));
    if (r.summary && r.summary.bullets.length) {
      var ul = el('ul', 'sum');
      r.summary.bullets.forEach(function (b) { ul.appendChild(el('li', null, b)); });
      box.appendChild(ul);
      box.appendChild(el('p', 'hint', 'Based only on this document’s text (' + (r.summary.method === 'llm' ? 'AI model' : 'key sentences') + ').'));
    } else {
      box.appendChild(el('p', 'hint', 'Get the key requirements, deadlines and required documents in a few bullet points.'));
    }
    var bar = el('div', 'acts');
    bar.appendChild(button(r.summary ? 'Summarize again' : 'Summarize', 'btn sec sm', async function (e) {
      e.target.disabled = true;
      var res = await api('/api/documents/' + r.id + '/summary', { method: 'POST' });
      e.target.disabled = false;
      if (!res.ok) { msg(res.data.error || 'Could not summarize.', 'err'); return; }
      current.summary = res.data;
      renderDetail();
    }));
    box.appendChild(bar);
    return box;
  }

  function actions(r) {
    var a = el('div', 'acts');
    var open = el('a', 'btn sec sm', 'Open original');
    open.href = r.file_url;
    open.target = '_blank';
    open.rel = 'noopener';
    a.appendChild(open);

    if (r.status !== 'failed') {
      if (r.reviewed) {
        a.appendChild(el('span', 'tag ok', 'Reviewed ' + date(r.reviewed_at)));
      } else {
        a.appendChild(button('Mark as reviewed', 'btn sm', async function () {
          var res = await api('/api/documents/' + r.id + '/review', { method: 'POST' });
          if (!res.ok) { msg(res.data.error || 'Could not update.', 'err'); return; }
          msg('Marked as reviewed.', 'ok');
          await refresh();
        }));
      }
    }

    a.appendChild(button('Delete', 'btn sec sm danger', async function () {
      if (!window.confirm('Delete “' + r.filename + '”? This cannot be undone.')) return;
      var res = await api('/api/documents/' + r.id, { method: 'DELETE' });
      if (!res.ok) { msg(res.data.error || 'Could not delete.', 'err'); return; }
      msg('Deleted “' + r.filename + '”.', 'ok');
      sel = null; current = null;
      renderDetail();
      await fetchDocs();
    }));
    return a;
  }

  // ---------------------------------------------------------------- wiring
  $('pick').onclick = function () { $('file').click(); };
  $('file').onchange = function (e) { handle(e.target.files[0]); e.target.value = ''; };
  $('q').oninput = function () {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(fetchDocs, 250);
  };

  var dz = $('drop');
  ['dragenter', 'dragover'].forEach(function (n) {
    dz.addEventListener(n, function (e) { e.preventDefault(); dz.classList.add('over'); });
  });
  ['dragleave', 'drop'].forEach(function (n) {
    dz.addEventListener(n, function (e) { e.preventDefault(); dz.classList.remove('over'); });
  });
  dz.addEventListener('drop', function (e) { handle(e.dataTransfer.files[0]); });

  fetchDocs();
})();
