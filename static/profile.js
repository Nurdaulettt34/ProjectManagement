(function () {
  var $ = function (id) { return document.getElementById(id); };

  function show(el, text, kind) {
    el.textContent = text;
    el.className = 'msg show ' + kind;
  }

  async function api(url, options) {
    options = options || {};
    options.headers = Object.assign({ 'Accept': 'application/json' }, options.headers || {});
    var res = await fetch(url, options);
    if (res.status === 401) { window.location.href = '/login'; throw new Error('Not authenticated'); }
    var data = await res.json().catch(function () { return {}; });
    return { ok: res.ok, status: res.status, data: data };
  }

  function json(method, body) {
    return { method: method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) };
  }

  function statusTag(d) {
    if (d.status === 'failed') return ['bad', 'Unreadable'];
    if (d.reviewed) return ['ok', 'Reviewed'];
    return ['warn', 'Needs review'];
  }

  async function load() {
    var r = await api('/api/profile');
    if (!r.ok) return;
    var s = r.data.stats;
    $('s-total').textContent = s.total;
    $('s-needs').textContent = s.needs_review;
    $('s-reviewed').textContent = s.reviewed;
    $('s-failed').textContent = s.failed;

    var box = $('recent');
    box.innerHTML = '';
    if (!r.data.recent_documents.length) {
      var e = document.createElement('div');
      e.className = 'empty';
      e.textContent = 'No documents yet.';
      box.appendChild(e);
      return;
    }
    r.data.recent_documents.forEach(function (d) {
      var a = document.createElement('a');
      a.className = 'recent-row';
      a.href = '/app';
      var n = document.createElement('span');
      n.className = 'n';
      n.textContent = d.filename;
      var t = document.createElement('span');
      t.className = 'muted';
      t.textContent = d.doc_type_label || '—';
      var st = statusTag(d);
      var tag = document.createElement('span');
      tag.className = 'tag ' + st[0];
      tag.textContent = st[1];
      a.appendChild(n); a.appendChild(t); a.appendChild(tag);
      box.appendChild(a);
    });
  }

  $('name-form').addEventListener('submit', async function (e) {
    e.preventDefault();
    var name = $('full_name').value.trim();
    var r = await api('/api/profile', json('PATCH', { full_name: name }));
    if (!r.ok) { show($('name-msg'), r.data.error || 'Could not save.', 'err'); return; }
    show($('name-msg'), 'Saved.', 'ok');
    $('p-name').textContent = r.data.user.full_name;
    $('p-avatar').textContent = r.data.user.full_name.charAt(0).toUpperCase();
    var hn = document.querySelector('.who-name');
    if (hn) hn.textContent = r.data.user.full_name;
  });

  $('pw-form').addEventListener('submit', async function (e) {
    e.preventDefault();
    var cur = $('current_password').value, nw = $('new_password').value;
    if (nw.length < 8) { show($('pw-msg'), 'Password must be at least 8 characters long.', 'err'); return; }
    if (nw !== $('new_password2').value) { show($('pw-msg'), 'New passwords do not match.', 'err'); return; }
    var r = await api('/api/profile/password', json('POST', { current_password: cur, new_password: nw }));
    if (!r.ok) { show($('pw-msg'), r.data.error || 'Could not change the password.', 'err'); return; }
    show($('pw-msg'), 'Password changed.', 'ok');
    e.target.reset();
  });

  load();
})();
