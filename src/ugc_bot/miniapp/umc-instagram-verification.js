/* Verification feedback reads server state; code issuance and bot messages stay unchanged. */
(function () {
  'use strict';
  var bridge = window.__umcAppBridge, screen = document.getElementById('screen-instagram-verification');
  if (!bridge || !screen) return;
  var copies = {
    ru: {waiting: 'Ожидаем подтверждения в Instagram…', confirmed: 'Instagram подтверждён', ready: 'Профиль креатора готов. Теперь вы можете получать предложения.', agreement: 'Для завершения регистрации подтвердите условия в личном кабинете.', check: 'Проверить статус', cabinet: 'В личный кабинет', error: 'Не удалось обновить статус. Попробуем ещё раз или нажмите «Проверить статус».', expired: 'Срок действия кода истёк. Вернитесь в кабинет, чтобы получить новый код.', session: 'Откройте Mini App заново, чтобы проверить свой профиль.'},
    en: {waiting: 'Waiting for Instagram confirmation…', confirmed: 'Instagram verified', ready: 'Your creator profile is ready. You can now receive offers.', agreement: 'Accept the terms in your account to complete registration.', check: 'Check status', cabinet: 'Go to my account', error: 'Could not refresh the status. We will retry, or you can select “Check status”.', expired: 'The code has expired. Return to your account to get a new code.', session: 'Reopen the Mini App to check your profile.'},
    kk: {waiting: 'Instagram растауын күтіп жатырмыз…', confirmed: 'Instagram расталды', ready: 'Креатор профилі дайын. Енді ұсыныстар ала аласыз.', agreement: 'Тіркелуді аяқтау үшін жеке кабинетте шарттарды қабылдаңыз.', check: 'Күйді тексеру', cabinet: 'Жеке кабинетке', error: 'Күйді жаңарту мүмкін болмады. Қайта тексереміз немесе «Күйді тексеру» түймесін басыңыз.', expired: 'Кодтың мерзімі аяқталды. Жаңа код алу үшін кабинетке оралыңыз.', session: 'Профильді тексеру үшін Mini App-ты қайта ашыңыз.'},
    be: {waiting: 'Чакаем пацвярджэння Instagram…', confirmed: 'Instagram пацверджаны', ready: 'Профіль крэатара гатовы. Цяпер вы можаце атрымліваць прапановы.', agreement: 'Для завяршэння рэгістрацыі прыміце ўмовы ў асабістым кабінеце.', check: 'Праверыць статус', cabinet: 'У асабісты кабінет', error: 'Не ўдалося абнавіць статус. Паўторым праверку або націсніце «Праверыць статус».', expired: 'Тэрмін дзеяння кода скончыўся. Вярніцеся ў кабінет па новы код.', session: 'Адкрыйце Mini App нанова, каб праверыць профіль.'},
    uz: {waiting: 'Instagram tasdiqlanishini kutyapmiz…', confirmed: 'Instagram tasdiqlandi', ready: 'Kreator profili tayyor. Endi takliflarni olishingiz mumkin.', agreement: 'Ro‘yxatdan o‘tishni yakunlash uchun shaxsiy kabinetda shartlarni qabul qiling.', check: 'Holatni tekshirish', cabinet: 'Shaxsiy kabinetga', error: 'Holat yangilanmadi. Qayta tekshiramiz yoki “Holatni tekshirish” tugmasini bosing.', expired: 'Kod muddati tugadi. Yangi kod olish uchun kabinetga qayting.', session: 'Profilni tekshirish uchun Mini Appni qayta oching.'}
  };
  function words() { return copies[(window._me || {}).locale] || copies.ru; }
  function accountLabel(value) {
    var match = value.match(/^(?:https?:\/\/(?:www\.)?instagram\.com\/|@)([a-z0-9_.]{1,30})\/?(?:\?.*)?$/i);
    return match ? '@' + match[1] : value;
  }
  function node(tag, id, className) { var el = document.createElement(tag); el.id = id; if (className) el.className = className; return el; }
  var result = node('div', 'instagram-verification-result', 'instagram-verification-feedback');
  result.hidden = true; result.setAttribute('role', 'status'); result.setAttribute('aria-live', 'polite');
  var title = node('strong', 'instagram-verification-success-title');
  var account = node('p', 'instagram-verification-account');
  var detail = node('p', 'instagram-verification-detail');
  var done = node('button', 'btn-instagram-verification-done', 'btn');
  done.type = 'button'; done.dataset.umcPrimary = '20';
  result.append(title, account, detail, done); screen.insertBefore(result, screen.querySelector('#instagram-verification-instruction'));
  var status = node('p', 'instagram-verification-status', 'hint');
  status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite');
  var check = node('button', 'btn-instagram-verification-check', 'btn btn-secondary'); check.type = 'button';
  var back = document.getElementById('btn-instagram-verification-back');
  screen.insertBefore(status, back); screen.insertBefore(check, back);
  var pending = ['instagram-verification-instruction', 'instagram-code-hint', 'instagram-verification-code', 'btn-instagram-copy', 'instagram-copy-status', 'btn-instagram-open'].map(function (id) { return document.getElementById(id); }).filter(Boolean);
  var bound = null, generation = 0, timer = null, request = null, expires = 0, complete = false, refreshWanted = false;
  function visible() { return screen.classList.contains('active') && !document.hidden; }
  function clearTimer() { if (timer !== null) clearTimeout(timer); timer = null; }
  function sync() { if (window.UMCShell) window.UMCShell.syncControls(); }
  function clearCode() { if (bridge.setInstagramCode) bridge.setInstagramCode(''); }
  function end() {
    generation++; clearTimer(); if (bound) bound.dispose(); bound = null; refreshWanted = false;
    if (request) { clearTimeout(request.timeout); if (request.controller) request.controller.abort(); request = null; }
    complete = false; result.hidden = true; check.disabled = false; clearCode(); sync();
  }
  function invalid() { end(); pending.forEach(function (el) { el.hidden = true; }); status.hidden = false; status.textContent = words().session; check.hidden = true; }
  function current(context, version) { return bound === context && generation === version && context.isCurrent() && screen.classList.contains('active'); }
  function schedule() {
    clearTimer(); if (!bound || !visible() || complete || Date.now() >= expires) return;
    timer = setTimeout(refresh, 5000);
  }
  function refresh() {
    if (!bound || !visible()) return;
    if (!bound.isCurrent()) { invalid(); return; }
    if (request) { refreshWanted = true; return; }
    clearTimer(); check.disabled = true;
    var context = bound, version = generation;
    var active = {controller: typeof AbortController === 'function' ? new AbortController() : null, timeout: null};
    request = active;
    if (active.controller) active.timeout = setTimeout(function () { active.controller.abort(); }, 15000);
    context.request('/blogger/instagram-verification/status', {}, {signal: active.controller ? active.controller.signal : undefined}).then(function (data) {
      if (!current(context, version)) { if (bound === context) invalid(); return; }
      var me = window._me;
      if (!me || !me.blogger_profile || data.user_id !== me.user_id || typeof data.confirmed !== 'boolean' || typeof data.agreement_confirmed !== 'boolean' || typeof data.instagram_url !== 'string' || !data.instagram_url) { invalid(); return; }
      me.blogger_profile.confirmed = data.confirmed;
      me.blogger_profile.agreement_confirmed = data.agreement_confirmed;
      me.blogger_profile.instagram_url = data.instagram_url;
      complete = data.confirmed;
      result.hidden = !complete; status.hidden = complete; check.hidden = complete;
      if (complete) {
        title.textContent = '✅ ' + words().confirmed;
        account.textContent = accountLabel(data.instagram_url);
        detail.textContent = data.agreement_confirmed ? words().ready : words().agreement;
        done.textContent = words().cabinet;
        pending.forEach(function (el) { el.hidden = true; }); clearCode();
      } else {
        status.textContent = Date.now() >= expires ? words().expired : words().waiting;
        if (Date.now() >= expires) { pending.forEach(function (el) { el.hidden = true; }); clearCode(); }
      }
      sync();
    }).catch(function (error) {
      if (!current(context, version)) { if (bound === context) invalid(); return; }
      if ([400, 401, 403].includes(error.status) || (error.status === 404 && error.message !== 'Not Found')) { invalid(); return; }
      if (!document.hidden) {
        complete = false; result.hidden = true; status.hidden = false; check.hidden = false;
        status.textContent = Date.now() >= expires ? words().expired : words().error;
        if (Date.now() >= expires) { pending.forEach(function (el) { el.hidden = true; }); clearCode(); }
      }
    }).finally(function () {
      clearTimeout(active.timeout);
      if (request !== active) return;
      request = null; check.disabled = false;
      if (!current(context, version)) return;
      if (refreshWanted && visible()) { refreshWanted = false; refresh(); } else schedule();
    });
  }
  function resume() {
    if (!bound) return;
    if (!bound.isCurrent()) { invalid(); return; }
    if (visible()) refresh(); else { clearTimer(); if (request && request.controller) request.controller.abort(); }
  }
  check.addEventListener('click', refresh);
  done.addEventListener('click', function () {
    if (!bound || !bound.isCurrent()) { invalid(); return; }
    bridge.showScreen('screen-blogger-dashboard');
  });
  document.addEventListener('umc:screen-change', function (event) { if (event.detail.screen !== screen.id && bound) end(); });
  document.addEventListener('visibilitychange', resume); window.addEventListener('focus', resume);
  window.addEventListener('pagehide', function () { clearTimer(); if (request && request.controller) request.controller.abort(); });
  window.addEventListener('pageshow', resume);
  window.UMCInstagramVerification = {begin: function (data) {
    // The start handler has already set the new code. Preserve it across cleanup.
    var code = document.getElementById('instagram-verification-code').value;
    end(); if (bridge.setInstagramCode) bridge.setInstagramCode(code);
    bound = bridge.createRequestContext();
    expires = Date.parse(data.expires_at) || Date.now() + 15 * 60 * 1000;
    status.hidden = false; status.textContent = words().waiting;
    check.hidden = false; check.textContent = words().check; done.textContent = words().cabinet;
    pending.forEach(function (el) { el.hidden = !code; });
    refresh();
  }};
})();
