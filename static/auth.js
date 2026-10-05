// Login, registration and email confirmation. The server validates everything
// again — these checks only give faster feedback.
var EMAIL_RE = /^[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}$/;

function isUniversityEmail(email, domain) {
  var host = (email.split('@').pop() || '').toLowerCase();
  return host === domain || host.slice(-(domain.length + 1)) === '.' + domain;
}

function makeMsg(el) {
  return function (text, kind) {
    el.textContent = text;
    el.className = 'msg show ' + kind;
  };
}

async function postJSON(url, payload) {
  var res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
    body: JSON.stringify(payload)
  });
  var data = await res.json().catch(function () { return {}; });
  return { ok: res.ok, status: res.status, data: data };
}

function goVerify(email) {
  window.location.href = '/verify?email=' + encodeURIComponent(email);
}

function initAuthForm(formId, endpoint, opts) {
  opts = opts || {};
  var form = document.getElementById(formId);
  var showMsg = makeMsg(document.getElementById('msg'));
  var domain = form.dataset.studentDomain || 'sdu.edu.kz';

  function val(id) {
    var el = document.getElementById(id);
    return el ? el.value : '';
  }

  function currentRole() {
    var r = form.querySelector('input[name="role"]:checked');
    return r ? r.value : '';
  }

  // Registration: the email label and hint depend on the chosen role.
  if (opts.register) {
    var label = document.getElementById('email-label');
    var hint = document.getElementById('email-hint');
    var emailInput = document.getElementById('email');
    var syncRole = function () {
      if (currentRole() === 'student') {
        label.textContent = 'University email';
        hint.textContent = 'Students sign up with their SDU email (…@' + domain + ').';
        emailInput.placeholder = 'name@stu.' + domain;
      } else {
        label.textContent = 'Email';
        hint.textContent = 'Applicants can use any personal email.';
        emailInput.placeholder = 'you@example.com';
      }
    };
    form.querySelectorAll('input[name="role"]').forEach(function (r) { r.addEventListener('change', syncRole); });
    syncRole();
  }

  form.addEventListener('submit', async function (e) {
    e.preventDefault();
    var payload = { email: val('email').trim(), password: val('password') };

    if (opts.register) {
      payload.full_name = val('full_name').trim();
      payload.role = currentRole();

      var empty = [];
      if (!payload.full_name) empty.push('full name');
      if (!payload.email) empty.push('email');
      if (!payload.password) empty.push('password');
      if (!payload.role) empty.push('role');
      if (empty.length) { showMsg('Required fields cannot be empty: ' + empty.join(', ') + '.', 'err'); return; }
      if (!EMAIL_RE.test(payload.email)) { showMsg('Please enter a valid email address.', 'err'); return; }
      if (payload.role === 'student' && !isUniversityEmail(payload.email, domain)) {
        showMsg('Students must register with their SDU university email (ending in @' + domain + '). Applicants can use any email.', 'err');
        return;
      }
      if (payload.password.length < 8) { showMsg('Password must be at least 8 characters long.', 'err'); return; }
      if (payload.password !== val('confirm')) { showMsg('Passwords do not match.', 'err'); return; }
    }

    var submitBtn = form.querySelector('button[type="submit"]');
    submitBtn.disabled = true;
    try {
      var r = await postJSON(endpoint, payload);
      if (r.ok && opts.register) { goVerify(r.data.email || payload.email); return; }
      if (r.ok) { window.location.href = '/app'; return; }
      if (r.data.verification_required) { goVerify(r.data.email || payload.email); return; }
      showMsg(r.data.error || 'Something went wrong. Try again.', 'err');
      submitBtn.disabled = false;
    } catch (err) {
      showMsg('Could not reach the server. Check your connection and try again.', 'err');
      submitBtn.disabled = false;
    }
  });
}

function initVerifyForm() {
  var form = document.getElementById('verify-form');
  var showMsg = makeMsg(document.getElementById('msg'));
  var codeInput = document.getElementById('code');
  var emailInput = document.getElementById('email');
  var resendBtn = document.getElementById('resend-btn');
  var timer = null;

  function countdown(seconds) {
    clearInterval(timer);
    var left = seconds;
    resendBtn.disabled = true;
    var tick = function () {
      if (left <= 0) {
        clearInterval(timer);
        resendBtn.disabled = false;
        resendBtn.textContent = 'Send a new code';
        return;
      }
      resendBtn.textContent = 'Send a new code (' + left + ' s)';
      left -= 1;
    };
    tick();
    timer = setInterval(tick, 1000);
  }

  codeInput.addEventListener('input', function () {
    codeInput.value = codeInput.value.replace(/\D/g, '').slice(0, 6);
    if (codeInput.value.length === 6) form.requestSubmit();
  });

  form.addEventListener('submit', async function (e) {
    e.preventDefault();
    var email = emailInput.value.trim();
    var code = codeInput.value.trim();
    if (!email) { showMsg('Enter your email.', 'err'); return; }
    if (!/^\d{6}$/.test(code)) { showMsg('Enter the 6-digit code from the email.', 'err'); return; }

    var btn = form.querySelector('button[type="submit"]');
    btn.disabled = true;
    try {
      var r = await postJSON('/api/verify-email', { email: email, code: code });
      if (r.ok) {
        showMsg(r.data.message || 'Email confirmed.', 'ok');
        window.location.href = r.data.next || '/welcome';
        return;
      }
      if (r.status === 409) { window.location.href = '/login'; return; }
      showMsg(r.data.error || 'Could not confirm the code.', 'err');
      codeInput.value = '';
      codeInput.focus();
    } catch (err) {
      showMsg('Could not reach the server. Try again.', 'err');
    }
    btn.disabled = false;
  });

  resendBtn.addEventListener('click', async function () {
    var email = emailInput.value.trim();
    if (!email) { showMsg('Enter your email first.', 'err'); return; }
    resendBtn.disabled = true;
    try {
      var r = await postJSON('/api/resend-code', { email: email });
      if (r.ok) showMsg('A new code has been sent. Check your inbox.', 'info');
      else showMsg(r.data.error || 'Could not send a new code.', 'err');
      countdown(r.data.retry_after || 0);
    } catch (err) {
      showMsg('Could not reach the server. Try again.', 'err');
      resendBtn.disabled = false;
    }
  });

  // A code was just sent by the registration request: start with the cooldown.
  if (emailInput.value) countdown(parseInt(form.dataset.resend, 10) || 0);
  codeInput.focus();
}
