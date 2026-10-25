/* Actual signed collaboration commands. Server capabilities own permissions. */
(function () {
  'use strict';
  var bridge = window.__umcAppBridge;
  var screen = document.getElementById('screen-collaboration');
  if (!bridge || !screen) return;
  var actions = ['start', 'claim', 'agree', 'dispute', 'extend_due', 'request_confirmation', 'resolve_success', 'resolve_failure'];
  var copy = {
    ru: { title: 'Сотрудничество', states: ['Назначено', 'В работе', 'Заявлен успех', 'Есть возражение', 'Успех подтверждён', 'Срок подтверждения истёк', 'Удержание завершено'], action: ['Начать работу', 'Заявить об успехе', 'Согласиться с успехом', 'Не согласиться', 'Перенести срок', 'Запросить подтверждение'], due: 'Согласованный срок', first: 'Первое заявление об успехе: до срока + 14 суток', objection: 'Возражение: до первого заявления + 72 часа', final: 'Успех подтверждён', hold: 'Окончание удержания: успех + 14 суток', proof: 'Доказательство', terms: 'Согласованные условия', reason: 'Причина', evidence: 'Ссылка на материал или описание доказательства', newDue: 'Новый согласованный срок', newTerms: 'Новые согласованные условия', confirm: 'Проверьте решение перед отправкой.', submit: 'Подтвердить решение', cancel: 'Отмена', reload: 'Обновить статус', back: 'Назад', loading: 'Загружаем сотрудничество…', sending: 'Отправляем решение…', required: 'Заполните обязательное поле.', invalid: 'Ссылка на сотрудничество некорректна.', unavailable: 'Сотрудничество временно недоступно. Попробуйте обновить позже.', forbidden: 'У вас нет доступа к этому сотрудничеству.', missing: 'Сотрудничество не найдено.', session: 'Откройте приложение заново, чтобы продолжить.', failed: 'Не удалось загрузить статус. Попробуйте обновить.', conflict: 'Решение не принято. Проверьте обновлённые данные перед повтором.', uncertain: 'Не удалось подтвердить результат отправки. Проверьте обновлённый статус.', saved: 'Статус обновлён.', readonly: 'Доступен просмотр статуса.', history: 'История назначения. Изменения недоступны.', noticeFailed: 'Доставка уведомления не подтверждена. Автоматическое подтверждение приостановлено.', noticePending: 'Доставка уведомления ещё не подтверждена.' },
    en: { title: 'Collaboration', states: ['Assigned', 'In progress', 'Success claimed', 'Disputed', 'Success confirmed', 'Confirmation expired', 'Hold completed'], action: ['Start work', 'Claim success', 'Agree with success', 'Dispute success', 'Extend due date', 'Request confirmation'], due: 'Agreed due date', first: 'First success claim: due date + 14 days', objection: 'Objection: first claim + 72 hours', final: 'Success confirmed', hold: 'Hold ends: confirmation + 14 days', proof: 'Evidence', terms: 'Agreed terms', reason: 'Reason', evidence: 'Content link or description of evidence', newDue: 'New agreed due date', newTerms: 'New agreed terms', confirm: 'Review this decision before sending.', submit: 'Confirm decision', cancel: 'Cancel', reload: 'Refresh status', back: 'Back', loading: 'Loading collaboration…', sending: 'Sending decision…', required: 'Complete this required field.', invalid: 'This collaboration link is invalid.', unavailable: 'Collaboration is temporarily unavailable. Try refreshing later.', forbidden: 'You do not have access to this collaboration.', missing: 'Collaboration not found.', session: 'Reopen the app to continue.', failed: 'Could not load the status. Try refreshing.', conflict: 'The decision was not accepted. Review the refreshed details before trying again.', uncertain: 'The send result could not be confirmed. Review the refreshed status.', saved: 'Status updated.', readonly: 'Status is available to view.', history: 'Historical assignment. Changes are unavailable.', noticeFailed: 'Notice delivery is unconfirmed. Automatic confirmation is paused.', noticePending: 'Notice delivery has not yet been confirmed.' },
    kk: { title: 'Ынтымақтастық', states: ['Тағайындалды', 'Орындалуда', 'Сәтті аяқталу мәлімделді', 'Қарсылық бар', 'Сәтті аяқталуы расталды', 'Растау мерзімі өтті', 'Ұстап тұру аяқталды'], action: ['Жұмысты бастау', 'Сәтті аяқталуын мәлімдеу', 'Сәтті аяқталуымен келісу', 'Келіспеу', 'Мерзімді ұзарту', 'Растауды сұрау'], due: 'Келісілген мерзім', first: 'Алғашқы мәлімдеме: мерзімнен кейін 14 тәулік', objection: 'Қарсылық: алғашқы мәлімдемеден кейін 72 сағат', final: 'Сәтті аяқталуы расталды', hold: 'Ұстап тұру: растаудан кейін 14 тәулік', proof: 'Дәлел', terms: 'Келісілген шарттар', reason: 'Себебі', evidence: 'Материал сілтемесі немесе дәлел сипаттамасы', newDue: 'Жаңа келісілген мерзім', newTerms: 'Жаңа келісілген шарттар', confirm: 'Жібермес бұрын шешімді тексеріңіз.', submit: 'Шешімді растау', cancel: 'Бас тарту', reload: 'Мәртебені жаңарту', back: 'Артқа', loading: 'Ынтымақтастық жүктелуде…', sending: 'Шешім жіберілуде…', required: 'Міндетті өрісті толтырыңыз.', invalid: 'Ынтымақтастық сілтемесі жарамсыз.', unavailable: 'Ынтымақтастық уақытша қолжетімсіз. Кейін жаңартыңыз.', forbidden: 'Бұл ынтымақтастыққа рұқсатыңыз жоқ.', missing: 'Ынтымақтастық табылмады.', session: 'Жалғастыру үшін қолданбаны қайта ашыңыз.', failed: 'Мәртебе жүктелмеді. Жаңартып көріңіз.', conflict: 'Шешім қабылданбады. Қайта жібермес бұрын жаңартылған деректерді тексеріңіз.', uncertain: 'Жіберу нәтижесі расталмады. Жаңартылған мәртебені тексеріңіз.', saved: 'Мәртебе жаңартылды.', readonly: 'Мәртебені көруге болады.', history: 'Бұрынғы тағайындау. Өзгерту қолжетімсіз.', noticeFailed: 'Хабарландыру жеткізілгені расталмады. Автоматты растау тоқтатылды.', noticePending: 'Хабарландыру жеткізілгені әлі расталмады.' },
    be: { title: 'Супрацоўніцтва', states: ['Прызначана', 'У працы', 'Заяўлены поспех', 'Ёсць пярэчанне', 'Поспех пацверджаны', 'Тэрмін пацверджання мінуў', 'Утрыманне завершана'], action: ['Пачаць працу', 'Заявіць аб поспеху', 'Пагадзіцца з поспехам', 'Не пагадзіцца', 'Перанесці тэрмін', 'Запытаць пацверджанне'], due: 'Узгоднены тэрмін', first: 'Першая заява: тэрмін + 14 сутак', objection: 'Пярэчанне: першая заява + 72 гадзіны', final: 'Поспех пацверджаны', hold: 'Канец утрымання: пацверджанне + 14 сутак', proof: 'Доказ', terms: 'Узгодненыя ўмовы', reason: 'Прычына', evidence: 'Спасылка на матэрыял або апісанне доказу', newDue: 'Новы ўзгоднены тэрмін', newTerms: 'Новыя ўзгодненыя ўмовы', confirm: 'Праверце рашэнне перад адпраўкай.', submit: 'Пацвердзіць рашэнне', cancel: 'Адмена', reload: 'Абнавіць статус', back: 'Назад', loading: 'Загружаем супрацоўніцтва…', sending: 'Адпраўляем рашэнне…', required: 'Запоўніце абавязковае поле.', invalid: 'Спасылка на супрацоўніцтва няправільная.', unavailable: 'Супрацоўніцтва часова недаступнае. Абнавіце пазней.', forbidden: 'У вас няма доступу да гэтага супрацоўніцтва.', missing: 'Супрацоўніцтва не знойдзена.', session: 'Адкрыйце праграму нанова.', failed: 'Не ўдалося загрузіць статус. Абнавіце яго.', conflict: 'Рашэнне не прынята. Праверце абноўленыя даныя перад паўторам.', uncertain: 'Вынік адпраўкі не пацверджаны. Праверце абноўлены статус.', saved: 'Статус абноўлены.', readonly: 'Статус даступны для прагляду.', history: 'Гісторыя прызначэння. Змены недаступныя.', noticeFailed: 'Дастаўка паведамлення не пацверджана. Аўтаматычнае пацверджанне прыпынена.', noticePending: 'Дастаўка паведамлення яшчэ не пацверджана.' },
    uz: { title: 'Hamkorlik', states: ['Tayinlandi', 'Jarayonda', 'Muvaffaqiyat bildirildi', 'E’tiroz bor', 'Muvaffaqiyat tasdiqlandi', 'Tasdiqlash muddati tugadi', 'Ushlab turish tugadi'], action: ['Ishni boshlash', 'Muvaffaqiyatni bildirish', 'Muvaffaqiyatga rozilik', 'E’tiroz bildirish', 'Muddatni uzaytirish', 'Tasdiqlashni so‘rash'], due: 'Kelishilgan muddat', first: 'Birinchi bildirish: muddat + 14 kun', objection: 'E’tiroz: birinchi bildirish + 72 soat', final: 'Muvaffaqiyat tasdiqlandi', hold: 'Ushlab turish tugashi: tasdiq + 14 kun', proof: 'Dalil', terms: 'Kelishilgan shartlar', reason: 'Sabab', evidence: 'Material havolasi yoki dalil tavsifi', newDue: 'Yangi kelishilgan muddat', newTerms: 'Yangi kelishilgan shartlar', confirm: 'Yuborishdan oldin qarorni tekshiring.', submit: 'Qarorni tasdiqlash', cancel: 'Bekor qilish', reload: 'Holatni yangilash', back: 'Orqaga', loading: 'Hamkorlik yuklanmoqda…', sending: 'Qaror yuborilmoqda…', required: 'Majburiy maydonni to‘ldiring.', invalid: 'Hamkorlik havolasi noto‘g‘ri.', unavailable: 'Hamkorlik vaqtincha mavjud emas. Keyinroq yangilang.', forbidden: 'Bu hamkorlikka kirish huquqingiz yo‘q.', missing: 'Hamkorlik topilmadi.', session: 'Davom etish uchun ilovani qayta oching.', failed: 'Holat yuklanmadi. Yangilab ko‘ring.', conflict: 'Qaror qabul qilinmadi. Qayta yuborishdan oldin yangilangan ma’lumotlarni tekshiring.', uncertain: 'Yuborish natijasi tasdiqlanmadi. Yangilangan holatni tekshiring.', saved: 'Holat yangilandi.', readonly: 'Holatni ko‘rish mumkin.', history: 'Oldingi tayinlash. O‘zgartirish mumkin emas.', noticeFailed: 'Xabar yetkazilgani tasdiqlanmadi. Avtomatik tasdiqlash to‘xtatildi.', noticePending: 'Xabar yetkazilgani hali tasdiqlanmadi.' }
  };
  var resolutionCopy={ru:['Подтвердить успех по спору','Отклонить успех по спору','Успех отклонён'],en:['Resolve dispute as successful','Reject success claim','Success rejected'],kk:['Дауды сәтті деп шешу','Сәттілікті қабылдамау','Сәттілік қабылданбады'],be:['Пацвердзіць поспех у спрэчцы','Адхіліць поспех у спрэчцы','Поспех адхілены'],uz:['Nizoni muvaffaqiyatli hal qilish','Muvaffaqiyatni rad etish','Muvaffaqiyat rad etildi']};
  Object.keys(copy).forEach(function(locale){copy[locale].action.push(resolutionCopy[locale][0],resolutionCopy[locale][1]);copy[locale].states.push(resolutionCopy[locale][2]);});
  var states = ['assigned', 'in_progress', 'success_claimed', 'disputed', 'success_final', 'unconfirmed_expired', 'available', 'rejected'];
  var state = { admin: false, data: null, busy: false, selected: null, assignment: null, returnScreen: 'screen-role-choice', opened: false };
  function id(name) { return document.getElementById(name); }
  function words() { return copy[(window._me || {}).locale] || copy.ru; }
  function sync() { if (window.UMCShell) window.UMCShell.syncControls(); }
  function text(name, value) { id(name).textContent = value || ''; }
  function localize() {
    var c = words();
    text('collaboration-title', c.title); text('btn-collaboration-reload', c.reload); text('btn-collaboration-back', c.back);
    text('btn-collaboration-submit', c.submit); text('btn-collaboration-cancel', c.cancel); text('collaboration-confirm', c.confirm);
    [['evidence', c.evidence], ['reason', c.reason], ['due-at', c.newDue + ' (' + Intl.DateTimeFormat().resolvedOptions().timeZone + ')'], ['terms', c.newTerms]].forEach(function (field) { text('lbl-collaboration-' + field[0], field[1]); });
  }
  function busy(value, label) {
    state.busy = value;
    screen.setAttribute('aria-busy', String(value));
    id('form-collaboration-command').setAttribute('aria-busy', String(value));
    screen.querySelectorAll('button,input,textarea').forEach(function (element) { element.disabled = value; });
    text('collaboration-loading', label);
    id('btn-collaboration-submit').setAttribute('aria-busy', String(value));
    sync();
  }
  function resetForm() {
    state.selected = null;
    id('form-collaboration-command').hidden = true;
    id('collaboration-actions').hidden = false;
    id('form-collaboration-command').reset();
    screen.querySelectorAll('[aria-invalid]').forEach(function (field) { field.removeAttribute('aria-invalid'); });
    sync();
  }
  function safeProof(container, value) {
    container.replaceChildren();
    if (!value) return;
    try {
      var url = new URL(value);
      if ((url.protocol === 'https:' || url.protocol === 'http:') && !url.username && !url.password) {
        var a = document.createElement('a'); a.href = url.href; a.textContent = value; a.target = '_blank'; a.rel = 'noopener noreferrer'; container.appendChild(a); return;
      }
    } catch (_) { /* Non-URL evidence remains literal text. */ }
    container.textContent = value;
  }
  function timeRow(label, value, key) {
    if (!value || isNaN(new Date(value).getTime())) return;
    var dt = document.createElement('dt'); dt.textContent = label;
    var dd = document.createElement('dd'); var time = document.createElement('time'); time.dateTime = value; time.dataset.collaborationTime = key;
    var date = new Date(value); var offset = -date.getTimezoneOffset();
    var pad = function (n) { return String(n).padStart(2, '0'); };
    time.textContent = localInput(value).replace('T', ' ') + ' (UTC' + (offset < 0 ? '-' : '+') + pad(Math.floor(Math.abs(offset) / 60)) + ':' + pad(Math.abs(offset) % 60) + ')';
    dd.appendChild(time); id('collaboration-dates').append(dt, dd);
  }
  function render(data) {
    var c = words();
    var record = data && data.record; var work = record && record.collaboration;
    if (!work || work.assignment_id !== state.assignment || states.indexOf(work.state) < 0 || !Number.isInteger(record.version) || record.version < 1 || !Array.isArray(data.allowed_actions) || typeof data.is_current !== 'boolean') throw new Error('invalid_collaboration_response');
    state.data = data; resetForm();
    id('collaboration-details').hidden = false;
    id('collaboration-status').dataset.state = work.state;
    text('collaboration-status', c.states[states.indexOf(work.state)]);
    text('collaboration-id', work.assignment_id);
    text('collaboration-proof-title', c.proof); text('collaboration-terms-title', c.terms);
    id('collaboration-proof').hidden = !work.evidence;
    safeProof(id('collaboration-evidence-view'), work.evidence);
    text('collaboration-terms-view', record.terms_reference);
    id('collaboration-dates').replaceChildren();
    timeRow(c.due, work.due_at, 'due_at'); timeRow(c.first, data.first_claim_deadline, 'first_claim_deadline');
    timeRow(c.objection, data.objection_deadline, 'objection_deadline'); timeRow(c.final, work.success_final_at, 'success_final_at'); timeRow(c.hold, data.available_at, 'available_at');
    text('collaboration-dispute-reason', work.dispute_reason ? c.reason + ': ' + work.dispute_reason : '');
    text('collaboration-notice-state', work.state === 'success_claimed' ? (work.notice_failed_at ? c.noticeFailed : !work.notice_delivered_at ? c.noticePending : '') : '');
    var available = data.is_current ? data.allowed_actions.filter(function (action) { return actions.indexOf(action) >= 0; }) : [];
    var options = id('collaboration-actions'); options.replaceChildren();
    available.forEach(function (action) {
      var button = document.createElement('button'); button.type = 'button'; button.className = 'btn btn-secondary'; button.dataset.collaborationAction = action;
      button.textContent = c.action[actions.indexOf(action)]; button.addEventListener('click', function () { select(action); }); options.appendChild(button);
    });
    document.dispatchEvent(new CustomEvent('umc:collaboration-view',{detail:data}));
    text('collaboration-readonly', data.is_current ? c.readonly : c.history); id('collaboration-readonly').hidden = available.length > 0;
  }
  function failure(error) {
    var c = words();
    text('collaboration-error', error.status === 503 ? c.unavailable : error.status === 403 ? c.forbidden : error.status === 404 ? c.missing : error.status === 401 ? c.session : c.failed);
  }
  function load(message) {
    if (state.busy) return Promise.resolve();
    state.data = null; resetForm(); id('collaboration-actions').replaceChildren(); id('collaboration-details').hidden = true;
    text('collaboration-error', ''); text('collaboration-feedback', ''); busy(true, words().loading);
    return bridge.request(state.admin?'/collaborations/admin/'+state.assignment+'/view':'/collaborations/'+state.assignment+'/status').then(function (data) { render(data); if (message) text('collaboration-feedback', message); }).catch(failure).then(function () { busy(false); });
  }
  function localInput(value) {
    var d = new Date(value); var pad = function (n) { return String(n).padStart(2, '0'); };
    return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()) + 'T' + pad(d.getHours()) + ':' + pad(d.getMinutes());
  }
  function operationKey() {
    if (!window.crypto) return null;
    if (typeof crypto.randomUUID === 'function') return crypto.randomUUID();
    if (typeof crypto.getRandomValues !== 'function') return null;
    var bytes = new Uint8Array(16); crypto.getRandomValues(bytes);
    return Array.from(bytes).map(function (byte) { return byte.toString(16).padStart(2, '0'); }).join('');
  }
  function select(action) {
    if (state.busy || !state.data || state.data.allowed_actions.indexOf(action) < 0 || !state.data.is_current) return;
    resetForm(); state.selected = action; text('collaboration-error', ''); text('collaboration-feedback', '');
    var resolution=action==='resolve_success'||action==='resolve_failure';
    var fields = { evidence: action === 'claim'||resolution, reason: action === 'dispute' || action === 'extend_due'||resolution, 'due-at': action === 'extend_due', terms: action === 'extend_due' };
    Object.keys(fields).forEach(function (name) { id('collaboration-field-' + name).hidden = !fields[name]; id('collaboration-' + name).required = fields[name]; });
    text('collaboration-action-title', words().action[actions.indexOf(action)]);
    if (action === 'extend_due') id('collaboration-due-at').value = localInput(state.data.record.collaboration.due_at);
    id('collaboration-actions').hidden = true; id('form-collaboration-command').hidden = false; sync();
    var field = id('form-collaboration-command').querySelector('[required]'); if (field) field.focus();
  }
  id('form-collaboration-command').addEventListener('submit', function (event) {
    event.preventDefault(); if (state.busy || !state.data || !state.selected) return;
    var fields = Array.from(this.querySelectorAll('[required]'));
    var missing = fields.find(function (field) { return !field.value.trim(); });
    if (missing) { text('collaboration-error', words().required); missing.setAttribute('aria-invalid', 'true'); missing.focus(); return; }
    var key = operationKey();
    if (!key) { text('collaboration-error', words().session); return; }
    var payload = { action: state.selected, expected_version: state.data.record.version, operation_key: 'miniapp:' + state.selected + ':' + key };
    if (state.selected === 'claim'||state.selected==='resolve_success'||state.selected==='resolve_failure') payload.evidence = id('collaboration-evidence').value.trim();
    if (state.selected === 'dispute' || state.selected === 'extend_due'||state.selected==='resolve_success'||state.selected==='resolve_failure') payload.reason = id('collaboration-reason').value.trim();
    if (state.selected === 'extend_due') {
      var due = new Date(id('collaboration-due-at').value);
      if (isNaN(due.getTime())) { text('collaboration-error', words().required); return; }
      payload.due_at = due.toISOString(); payload.expected_due_version = state.data.record.collaboration.due_version; payload.terms_reference = id('collaboration-terms').value.trim();
    }
    text('collaboration-error', ''); text('collaboration-feedback', ''); busy(true, words().sending);
    bridge.request('/collaborations/' + state.assignment + '/command', payload).then(function (data) {
      render(data); busy(false);
      if (!data.is_current) return load(words().conflict);
      text('collaboration-feedback', words().saved);
    }).catch(function (error) {
      busy(false);
      if (error.status === 409 || !error.status) return load(error.status === 409 ? words().conflict : words().uncertain);
      state.data = null; resetForm(); id('collaboration-actions').replaceChildren(); failure(error);
    });
  });
  id('form-collaboration-command').addEventListener('input', function (event) {
    event.target.removeAttribute('aria-invalid');
    text('collaboration-error', '');
  });
  id('btn-collaboration-cancel').addEventListener('click', resetForm);
  id('btn-collaboration-reload').addEventListener('click', function () { if (state.assignment) load(); });
  id('btn-collaboration-back').addEventListener('click', function () {
    if (state.busy) return; if (state.selected) { resetForm(); return; }
    var url = new URL(location.href); url.searchParams.delete('assignment'); url.searchParams.delete('assignment_id'); history.replaceState(null, '', url.href);
    bridge.showScreen(state.returnScreen);
  });
  function openLink() {
    if (state.opened) return;
    var params = new URLSearchParams(location.search); var values = params.getAll('assignment').concat(params.getAll('assignment_id'));
    if (!values.length) return;
    state.opened = true; localize(); var current = document.querySelector('.screen.active'); if (current && current !== screen) state.returnScreen = current.id;
    bridge.showScreen(screen.id);
    var value = values[0].toLowerCase();
    if (values.length !== 1 || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(value) || /^0{8}-0{4}-0{4}-0{4}-0{12}$/.test(value)) { text('collaboration-error', words().invalid); id('btn-collaboration-reload').hidden = true; return; }
    state.assignment = value; load();
  }
  function open(assignment,admin) {
    state.admin=admin===true;
    var url = new URL(location.href); url.searchParams.delete('assignment_id'); url.searchParams.set('assignment', assignment); history.replaceState(null, '', url.href);
    state.opened = false; openLink();
  }
  window.UMCCollaboration={open:function(assignment){open(assignment,false);},openAdmin:function(assignment){open(assignment,true);}};
  document.addEventListener('umc:app-ready', openLink);
  if (window.__umcAppReady) openLink();
})();
