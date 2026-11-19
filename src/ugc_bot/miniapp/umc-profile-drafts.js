/* Device-local, account/role-scoped profile drafts. Never submits a profile. */
(function () {
  'use strict';
  var bridge = window.__umcAppBridge;
  if (!bridge || !bridge.profileForms) return;
  var copy = {
    ru: ['Есть незавершённая анкета на этом устройстве.', 'Продолжить заполнение', 'Начать заново', 'Черновик сохранён на этом устройстве.', 'Не удалось сохранить черновик на устройстве. Не закрывайте анкету до сохранения профиля.', 'Черновик изменился в другом окне. Откройте анкету заново.', 'Откройте Mini App заново, чтобы продолжить.', 'Продолжить анкету креатора', 'Продолжить анкету заказчика', 'Есть несохранённые изменения профиля. «Начать заново» вернёт сохранённые данные.'],
    en: ['There is an unfinished profile on this device.', 'Continue filling', 'Start over', 'Draft saved on this device.', 'Could not save the draft on this device. Keep the form open until you save your profile.', 'The draft changed in another window. Reopen the form.', 'Reopen the Mini App to continue.', 'Continue creator profile', 'Continue advertiser profile', 'There are unsaved profile edits. Start over returns to your saved profile.'],
    kk: ['Осы құрылғыда аяқталмаған сауалнама бар.', 'Толтыруды жалғастыру', 'Қайта бастау', 'Жоба осы құрылғыда сақталды.', 'Жоба құрылғыда сақталмады. Профильді сақтағанша сауалнаманы жаппаңыз.', 'Жоба басқа терезеде өзгерді. Сауалнаманы қайта ашыңыз.', 'Жалғастыру үшін Mini App-ты қайта ашыңыз.', 'Креатор сауалнамасын жалғастыру', 'Жарнама беруші сауалнамасын жалғастыру', 'Профильдің сақталмаған өзгерістері бар. Қайта бастау сақталған деректерді қайтарады.'],
    be: ['На гэтай прыладзе ёсць незавершаная анкета.', 'Працягнуць запаўненне', 'Пачаць нанова', 'Чарнавік захаваны на гэтай прыладзе.', 'Не ўдалося захаваць чарнавік на прыладзе. Не закрывайце анкету да захавання профілю.', 'Чарнавік змяніўся ў іншым акне. Адкрыйце анкету нанова.', 'Адкрыйце Mini App нанова, каб працягнуць.', 'Працягнуць анкету крэатара', 'Працягнуць анкету рэкламадаўца', 'Ёсць незахаваныя змены профілю. Пачаць нанова верне захаваныя даныя.'],
    uz: ['Bu qurilmada tugallanmagan anketa bor.', 'To‘ldirishni davom ettirish', 'Qaytadan boshlash', 'Qoralama shu qurilmada saqlandi.', 'Qoralama qurilmada saqlanmadi. Profilni saqlamaguncha anketani yopmang.', 'Qoralama boshqa oynada o‘zgardi. Anketani qayta oching.', 'Davom etish uchun Mini Appni qayta oching.', 'Kreator anketasini davom ettirish', 'Reklamachi anketasini davom ettirish', 'Profilda saqlanmagan o‘zgarishlar bor. Qaytadan boshlash saqlangan ma’lumotlarni qaytaradi.']
  };
  var fields = {
    advertiser: ['adv-name', 'adv-phone', 'adv-brand', 'adv-site', 'adv-city', 'adv-activity'],
    blogger: ['blg-name', 'blg-instagram', 'blg-birth-day', 'blg-birth-month', 'blg-birth-year', 'blg-topics', 'blg-city', 'blg-region', 'blg-country', 'blg-lat', 'blg-lon', 'blg-city-search', 'blg-audience-geo', 'blg-age-min', 'blg-age-max', 'blg-audience-gender', 'blg-price', 'blg-barter', 'blg-work-format', 'blg-blogger-gender']
  };
  var controllers = {}, account = null;
  function words() { return copy[(window._me || {}).locale] || copy.ru; }
  function uuid() { return Array.from(crypto.getRandomValues(new Uint8Array(16))).map(function (v) { return v.toString(16).padStart(2, '0'); }).join(''); }
  function identity() { var me = window._me || {}; return bridge.profileForms.isVerified() && me.user_id ? (window.__miniapp_platform || 'telegram') + ':' + me.user_id : null; }
  function mode(role) { return (window._me || {})['has_' + role + '_profile'] ? 'edit' : 'register'; }
  function prefix(role, kind) { return 'umc:profile-draft:v1:' + identity() + ':' + role + ':' + (kind || mode(role)) + ':'; }
  function sync() {
    Object.keys(controllers).forEach(function (role) { var c = controllers[role]; c.panel.hidden = !c.status.textContent && c.resume.hidden && c.restart.hidden; });
    if (window.UMCShell) window.UMCShell.syncControls();
  }
  function current(c) { return c.context && c.context.isCurrent() && c.identity === identity(); }
  function visible(c) { return c.screen.classList.contains('active'); }
  function invalidate(c) {
    if (c.context) c.context.dispose();
    c.context = null; c.form.hidden = false; c.form.reset();
    bridge.profileForms.clear(c.role);
    c.resume.hidden = true; c.restart.hidden = true; c.status.textContent = words()[6]; sync();
  }
  function values(c) {
    var result = {};
    fields[c.role].forEach(function (id) { result[id] = document.getElementById(id).value; });
    if (c.role === 'blogger' && bridge.profileForms.cityPending()) {
      ['blg-city', 'blg-region', 'blg-country', 'blg-lat', 'blg-lon'].forEach(function (id) { result[id] = ''; });
    }
    return result;
  }
  function latest(c) {
    var best = null;
    for (var i = 0; i < localStorage.length; i++) {
      var key = localStorage.key(i);
      if (!key || key.indexOf(c.prefix) !== 0 || !/^[a-f0-9]{32}$/.test(key.slice(c.prefix.length))) continue;
      var raw = localStorage.getItem(key), data;
      if (!raw || raw.length > 32768) continue;
      try { data = JSON.parse(raw); } catch (_) { continue; }
      if (!data || data.schema !== 1 || data.identity !== c.identity || data.role !== c.role || data.mode !== c.mode || data.epoch !== c.epoch || data.id !== key.slice(c.prefix.length) || !Number.isFinite(data.time) || !data.values || Array.isArray(data.values)) continue;
      if (!fields[c.role].some(function (id) { return typeof data.values[id] === 'string'; }) || !fields[c.role].every(function (id) { return data.values[id] === undefined || (typeof data.values[id] === 'string' && data.values[id].length <= 4000); })) continue;
      if (!best || data.time > best.data.time || (data.time === best.data.time && data.id > best.data.id)) best = {key: key, data: data};
    }
    return best;
  }
  function epochCurrent(c) {
    try {
      if ((localStorage.getItem(c.prefix + 'epoch') || '') === c.epoch) return true;
      c.status.textContent = words()[5]; c.resume.hidden = true; sync(); return false;
    } catch (_) { return true; } // Storage failure must not prevent registration.
  }
  function save(c) {
    if (!visible(c) || c.form.hidden || c.busy) return;
    if (!current(c)) { invalidate(c); return; }
    if (!epochCurrent(c)) return;
    var saved = values(c), serialized = JSON.stringify(saved);
    if (serialized === c.lastValues) return;
    try {
      if (typeof c.epoch !== 'string' || (localStorage.getItem(c.prefix + 'epoch') || '') !== c.epoch) throw new Error('storage_unavailable');
      if (fields[c.role].some(function (field) { return saved[field].length > 4000; })) throw new Error('field_too_large');
      var id = uuid(), key = c.prefix + id;
      var time = Number.isFinite(performance.timeOrigin) ? performance.timeOrigin + performance.now() : Date.now();
      var raw = JSON.stringify({schema: 1, identity: c.identity, role: c.role, mode: c.mode, epoch: c.epoch, id: id, time: time, values: saved});
      if (raw.length > 32768) throw new Error('draft_too_large');
      localStorage.setItem(key, raw);
      if (c.ownKey && c.ownKey !== key) localStorage.removeItem(c.ownKey);
      c.ownKey = key; c.lastValues = serialized;
      c.status.textContent = words()[3]; c.restart.hidden = false;
    } catch (_) { c.status.textContent = words()[4]; }
    sync();
  }
  function clearPrefix(prefix) {
    var keys = [];
    for (var i = 0; i < localStorage.length; i++) { var key = localStorage.key(i); if (key && key.indexOf(prefix) === 0) keys.push(key); }
    keys.forEach(function (key) { localStorage.removeItem(key); });
    var epoch = uuid(); localStorage.setItem(prefix + 'epoch', epoch); return epoch;
  }
  function erase(c, all) {
    try {
      if (all) c.epoch = clearPrefix(c.prefix);
      else if (c.submittedKey) localStorage.removeItem(c.submittedKey);
      return true;
    } catch (_) { c.status.textContent = words()[4]; return false; }
  }
  function enter(c) {
    if (c.busy) return;
    if (c.context) c.context.dispose();
    c.context = bridge.createRequestContext(); c.identity = identity(); c.mode = mode(c.role); c.prefix = prefix(c.role);
    if (!c.identity || !current(c)) { invalidate(c); return; }
    c.form.hidden = false; c.resume.hidden = true; c.restart.hidden = true; c.status.textContent = '';
    c.ownKey = null; c.lastValues = JSON.stringify(values(c));
    c.resume.textContent = words()[1]; c.restart.textContent = words()[2];
    try {
      c.epoch = localStorage.getItem(c.prefix + 'epoch') || '';
      var entry = latest(c);
      if (entry) {
        c.form.hidden = true; c.resume.hidden = false; c.restart.hidden = false;
        c.status.textContent = words()[c.mode === 'edit' ? 9 : 0];
      }
    } catch (_) { c.status.textContent = words()[4]; }
    sync();
  }
  function resume(c) {
    if (!current(c)) { invalidate(c); return; }
    try {
      c.epoch = localStorage.getItem(c.prefix + 'epoch') || '';
      var entry = latest(c);
      if (!entry) { enter(c); return; }
      bridge.profileForms.prepare(c.role);
      var saved = entry.data.values;
      fields[c.role].forEach(function (id) {
        if (typeof saved[id] !== 'string') return;
        var el = document.getElementById(id);
        if (el.tagName !== 'SELECT' || Array.from(el.options).some(function (option) { return option.value === saved[id]; })) el.value = saved[id];
      });
      if (c.role === 'blogger') {
        var city = document.getElementById('blg-city'), lat = document.getElementById('blg-lat'), lon = document.getElementById('blg-lon');
        var canonical = (window._me || {}).blogger_profile || {};
        var validPoint = lat.value.trim() && lon.value.trim() && Number.isFinite(Number(lat.value)) && Math.abs(Number(lat.value)) <= 90 && Number.isFinite(Number(lon.value)) && Math.abs(Number(lon.value)) <= 180;
        if (!validPoint && !(c.mode === 'edit' && city.value === canonical.city)) {
          ['blg-city', 'blg-region', 'blg-country', 'blg-lat', 'blg-lon'].forEach(function (id) { document.getElementById(id).value = ''; });
        }
      }
      c.ownKey = entry.key; c.lastValues = JSON.stringify(values(c));
      c.form.hidden = false; c.resume.hidden = true; c.restart.hidden = false; c.status.textContent = words()[3]; sync();
    } catch (_) { c.status.textContent = words()[4]; }
  }
  Object.keys(fields).forEach(function (role) {
    var form = document.getElementById('form-' + role), panel = document.createElement('div');
    panel.className = 'umc-profile-draft'; panel.dataset.profileDraft = role;
    var status = document.createElement('p'), resumeButton = document.createElement('button'), restart = document.createElement('button');
    status.className = 'hint'; status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite');
    resumeButton.type = restart.type = 'button'; resumeButton.hidden = restart.hidden = true;
    resumeButton.className = 'btn'; resumeButton.dataset.umcPrimary = '30'; restart.className = 'btn btn-secondary';
    panel.append(status, resumeButton, restart); form.before(panel);
    var c = controllers[role] = {role: role, panel: panel, screen: form.closest('.screen'), form: form, status: status, resume: resumeButton, restart: restart, context: null, busy: false};
    form.addEventListener('input', function () { save(c); });
    form.addEventListener('change', function () { save(c); });
    resumeButton.addEventListener('click', function () { resume(c); });
    restart.addEventListener('click', function () {
      if (!current(c)) { invalidate(c); return; }
      if (c.busy || !erase(c, true)) return;
      bridge.profileForms.prepare(c.role);
      enter(c);
    });
  });
  var shortcuts = document.createElement('div'); shortcuts.className = 'umc-profile-draft-shortcuts';
  document.getElementById('screen-role-choice').append(shortcuts);
  function updateShortcuts() {
    shortcuts.replaceChildren();
    if (!identity()) return;
    Object.keys(controllers).forEach(function (role) {
      var lookup = {identity: identity(), role: role, mode: mode(role), prefix: prefix(role)};
      try {
        lookup.epoch = localStorage.getItem(lookup.prefix + 'epoch') || '';
        if (!latest(lookup)) return;
      } catch (_) { return; }
      var button = document.createElement('button'), context = bridge.createRequestContext();
      button.type = 'button'; button.className = 'btn btn-secondary'; button.textContent = words()[role === 'blogger' ? 7 : 8];
      button.addEventListener('click', function () { if (context.isCurrent()) { bridge.profileForms.prepare(role); bridge.showScreen('screen-register-' + role); } });
      shortcuts.append(button);
    });
  }
  function ready() {
    var next = identity();
    if (next !== account) {
      Object.keys(controllers).forEach(function (role) { var c = controllers[role]; if (c.context) c.context.dispose(); c.context = null; c.form.hidden = false; if (next) bridge.profileForms.prepare(role); else bridge.profileForms.clear(role); c.status.textContent = ''; c.resume.hidden = c.restart.hidden = true; });
      account = next;
    }
    // The server may have accepted registration before the WebView closed.
    // A stored profile supersedes its old registration draft, never consent.
    if (next) Object.keys(controllers).forEach(function (role) {
      if (mode(role) !== 'edit') return;
      try {
        var old = prefix(role, 'register');
        if (Object.keys(localStorage).some(function (key) { return key.indexOf(old) === 0 && /^[a-f0-9]{32}$/.test(key.slice(old.length)); })) clearPrefix(old);
      } catch (_) { /* Forms stay usable when storage is unavailable. */ }
    });
    updateShortcuts();
    sync();
  }
  document.addEventListener('umc:app-ready', ready);
  document.addEventListener('umc:screen-change', function (event) {
    Object.keys(controllers).forEach(function (role) { var c = controllers[role]; if (event.detail.screen === c.screen.id) enter(c); });
    if (event.detail.screen === 'screen-role-choice') updateShortcuts();
  });
  function verifyVisible() {
    if (document.hidden) return;
    Object.keys(controllers).forEach(function (role) { var c = controllers[role]; if (visible(c) && c.context && !current(c)) invalidate(c); });
    updateShortcuts();
  }
  window.addEventListener('focus', verifyVisible);
  window.addEventListener('pageshow', verifyVisible);
  document.addEventListener('visibilitychange', verifyVisible);
  window.addEventListener('storage', function (event) {
    Object.keys(controllers).forEach(function (role) { var c = controllers[role]; if (c.context && event.key === c.prefix + 'epoch') epochCurrent(c); });
    updateShortcuts();
  });
  window.UMCProfileDrafts = {
    begin: function (role) {
      var c = controllers[role];
      if (!current(c)) { invalidate(c); return false; }
      if (!epochCurrent(c) || c.form.hidden || c.busy) return false;
      save(c); c.submittedKey = c.ownKey; c.busy = true;
      c.disabled = Array.from(c.form.elements).map(function (el) { var old = el.disabled; el.disabled = true; return [el, old]; });
      c.resume.disabled = c.restart.disabled = true; sync(); return true;
    },
    saved: function (role) {
      var c = controllers[role];
      if (!current(c)) return;
      var registered = c.mode === 'register';
      if (erase(c, registered)) { c.ownKey = null; c.status.textContent = ''; c.restart.hidden = true; }
      if (registered) {
        // Acceptance precedes /me refresh. Further typing after a failed
        // refresh is an edit, so the next login must not discard it.
        c.mode = 'edit'; c.prefix = prefix(role, 'edit');
        try { c.epoch = localStorage.getItem(c.prefix + 'epoch') || ''; }
        catch (_) { c.epoch = null; }
      }
    },
    finish: function (role) {
      var c = controllers[role];
      (c.disabled || []).forEach(function (entry) { entry[0].disabled = entry[1]; });
      c.disabled = null; c.busy = false; c.resume.disabled = c.restart.disabled = false;
      if (c.context && !current(c)) invalidate(c);
      sync();
    }
  };
  if (window.__umcAppReady) ready();
})();
