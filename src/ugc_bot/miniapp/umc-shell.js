/* UMC shell: presentation and host capabilities only. Authentication and business actions stay in the page. */
(function () {
  'use strict';
  var root = document.documentElement;
  var media = window.matchMedia('(prefers-color-scheme: dark)');
  var platform = window.__miniapp_platform || 'telegram';
  var currentMain = null;
  var currentBack = null;
  var mainSignature = '';
  var adapter = null;
  var queued = false;
  var lastScreen = null;
  var lastFeedback = '';

  function call(object, method, args) {
    try {
      if (object && typeof object[method] === 'function') {
        object[method].apply(object, args || []);
        return true;
      }
    } catch (_) { /* An unsupported host capability must keep the browser control usable. */ }
    return false;
  }
  function css(name) { return getComputedStyle(root).getPropertyValue(name).trim(); }
  function supports(object, methods) {
    return !!object && methods.every(function (name) { return typeof object[name] === 'function'; });
  }
  function telegramAdapter(host) {
    return {
      name: 'telegram', host: host,
      main: supports(host.MainButton, ['setParams', 'onClick', 'show', 'hide']) ? host.MainButton : null,
      back: supports(host.BackButton, ['onClick', 'show', 'hide']) ? host.BackButton : null,
      theme: function () {
        call(host, 'setBackgroundColor', [css('--bg')]);
        if (typeof host.isVersionAtLeast === 'function' && host.isVersionAtLeast('6.9')) call(host, 'setHeaderColor', [css('--umc-section')]);
        if (typeof host.isVersionAtLeast === 'function' && host.isVersionAtLeast('7.10')) call(host, 'setBottomBarColor', [css('--bg')]);
      }
    };
  }
  // MAX is deliberately a separate adapter: no Telegram version API or object aliasing.
  function maxAdapter(host) {
    return {
      name: 'max', host: host,
      main: supports(host.MainButton, ['setParams', 'onClick', 'show', 'hide']) ? host.MainButton : null,
      back: supports(host.BackButton, ['onClick', 'show', 'hide']) ? host.BackButton : null,
      theme: function () { call(host, 'setHeaderColor', [css('--umc-section')]); call(host, 'setBackgroundColor', [css('--bg')]); }
    };
  }
  function visible(element) {
    if (!element || element.hidden || element.style.display === 'none') return false;
    var node = element;
    while (node && node.nodeType === 1) {
      var style = getComputedStyle(node);
      var nativeHidden = node === element && (node.classList.contains('umc-native-action') || node.classList.contains('umc-native-back'));
      if ((!nativeHidden && style.display === 'none') || style.visibility === 'hidden') return false;
      node = node.parentElement;
    }
    return true;
  }
  function restore(element, className) {
    if (!element) return;
    element.classList.remove(className);
  }
  function activate(element) {
    if (!element || element.disabled || !visible(element)) return;
    if (element.tagName === 'BUTTON' && element.type === 'submit' && element.form) {
      if (typeof element.form.requestSubmit === 'function') element.form.requestSubmit(element);
      else element.click();
    } else element.click();
  }
  function feedback(type) {
    if (!adapter) return;
    var haptic = adapter.host.HapticFeedback;
    if (type === 'selection') call(haptic, 'selectionChanged');
    else if (type === 'light') call(haptic, 'impactOccurred', ['light']);
    else call(haptic, 'notificationOccurred', [type]);
  }
  function updateViewport() {
    var host = adapter && adapter.host;
    var viewport = window.visualViewport;
    var height = (viewport && viewport.height) || window.innerHeight;
    var stable = (host && host.viewportStableHeight) || window.innerHeight;
    root.style.setProperty('--umc-viewport-height', Math.round(height) + 'px');
    root.style.setProperty('--umc-stable-height', Math.round(stable) + 'px');
    ['top', 'bottom', 'left', 'right'].forEach(function (side) {
      var safe = host && host.safeAreaInset && Number(host.safeAreaInset[side]);
      var content = host && host.contentSafeAreaInset && Number(host.contentSafeAreaInset[side]);
      root.style.setProperty('--umc-safe-' + side, Math.max(0, safe || 0, content || 0) + 'px');
    });
    root.dataset.keyboard = stable - height > 120 ? 'open' : 'closed';
  }
  function applyTheme() {
    var scheme = adapter && adapter.host.colorScheme;
    root.dataset.theme = scheme === 'dark' || scheme === 'light' ? scheme : (media.matches ? 'dark' : 'light');
    if (adapter) adapter.theme();
    mainSignature = '';
    schedule();
  }
  function syncControls(screen) {
    if (!adapter) return;
    var candidates = screen ? Array.from(screen.querySelectorAll('[data-umc-primary]')).filter(visible) : [];
    candidates.sort(function (a, b) { return Number(b.dataset.umcPrimary) - Number(a.dataset.umcPrimary); });
    var next = candidates[0] || null;
    // A navigation button leading to an already open panel is no longer the screen's main action.
    if (next && next.id === 'btn-show-create-order' && visible(document.getElementById('block-orders-list'))) next = null;
    if (currentMain !== next) { restore(currentMain, 'umc-native-action'); currentMain = next; mainSignature = ''; }
    if (adapter.main && currentMain) {
      var params = { text: currentMain.textContent.trim(), color: css('--ink'), text_color: css('--on-ink'), is_active: !currentMain.disabled, is_visible: true };
      var signature = JSON.stringify(params);
      if (signature !== mainSignature) {
        if (call(adapter.main, 'setParams', [params]) && call(adapter.main, 'show')) {
          currentMain.classList.add('umc-native-action');
          if (currentMain.disabled) call(adapter.main, 'showProgress', [true]);
          else call(adapter.main, 'hideProgress');
          mainSignature = signature;
        } else {
          restore(currentMain, 'umc-native-action');
          adapter.main = null;
        }
      }
    } else if (adapter.main) { call(adapter.main, 'hide'); mainSignature = ''; }
    var nextBack = screen && Array.from(screen.querySelectorAll('[data-umc-back]')).find(visible);
    if (currentBack !== nextBack) { restore(currentBack, 'umc-native-back'); currentBack = nextBack || null; }
    if (adapter.back) {
      if (currentBack && call(adapter.back, 'show')) {
        if (!currentBack.classList.contains('umc-native-back')) currentBack.classList.add('umc-native-back');
      }
      else { restore(currentBack, 'umc-native-back'); call(adapter.back, 'hide'); }
    }
  }
  function enhance() {
    queued = false;
    var screen = document.querySelector('.screen.active');
    var id = screen && screen.id;
    var name = screen && screen.dataset.umcSection;
    var section = ['lavender', 'peach', 'lilac', 'mint'].indexOf(name) !== -1 ? '--' + name : '--lavender';
    var color = css(section);
    if (root.style.getPropertyValue('--umc-section') !== color) {
      root.style.setProperty('--umc-section', color);
      if (adapter) adapter.theme();
    }
    if (id !== lastScreen) {
      if (lastScreen && screen) {
        window.scrollTo(0, 0);
        var heading = screen.querySelector('h1');
        if (heading) { heading.tabIndex = -1; heading.focus({ preventScroll: true }); }
      }
      lastScreen = id;
    }
    document.querySelectorAll('[data-umc-primary]').forEach(function (button) {
      var busy = button.disabled && (button.type === 'submit' || button.id.indexOf('agreement') !== -1);
      var value = busy ? 'true' : 'false';
      if (button.getAttribute('aria-busy') !== value) button.setAttribute('aria-busy', value);
      if (button.form && button.form.getAttribute('aria-busy') !== value) button.form.setAttribute('aria-busy', value);
    });
    document.querySelectorAll('li[style*="cursor: pointer"]').forEach(function (item) {
      if (item.dataset.umcKeyboard) return;
      item.tabIndex = 0;
      item.setAttribute('role', 'button');
      item.dataset.umcKeyboard = 'true';
      item.addEventListener('keydown', function (event) {
        if (event.target === item && (event.key === 'Enter' || event.key === ' ')) { event.preventDefault(); item.click(); }
      });
    });
    var loading = document.getElementById('screen-loading');
    if (loading) {
      var failed = loading.dataset.failed === 'true' || /No initData|Ошибка:|Error:/i.test(loading.textContent);
      loading.setAttribute('aria-busy', failed ? 'false' : 'true');
    }
    document.querySelectorAll('.error, .success').forEach(function (element) {
      if (!element.hasAttribute('role')) element.setAttribute('role', element.classList.contains('error') ? 'alert' : 'status');
    });
    if (screen) {
      var status = Array.from(screen.querySelectorAll('.error, .success')).filter(function (el) { return visible(el) && el.textContent.trim(); }).pop();
      var statusKey = status ? status.id + ':' + status.textContent : '';
      if (statusKey && statusKey !== lastFeedback) feedback(status.classList.contains('error') ? 'error' : 'success');
      lastFeedback = statusKey;
    }
    syncControls(screen);
  }
  function schedule() { if (!queued) { queued = true; window.requestAnimationFrame(enhance); } }
  function connect() {
    var host = platform === 'max' ? window.WebApp : window.Telegram && window.Telegram.WebApp;
    if (host) {
      adapter = platform === 'max' ? maxAdapter(host) : telegramAdapter(host);
      root.dataset.host = adapter.name;
      if (adapter.main && !call(adapter.main, 'onClick', [function () { syncControls(document.querySelector('.screen.active')); activate(currentMain); }])) adapter.main = null;
      if (adapter.back && !call(adapter.back, 'onClick', [function () { syncControls(document.querySelector('.screen.active')); activate(currentBack); }])) adapter.back = null;
      ['themeChanged', 'viewportChanged', 'safeAreaChanged', 'contentSafeAreaChanged'].forEach(function (event) {
        call(host, 'onEvent', [event, event === 'themeChanged' ? applyTheme : updateViewport]);
      });
    } else root.dataset.host = 'browser';
    updateViewport();
    applyTheme();
  }
  window.UMCShell = {
    syncControls: function () { syncControls(document.querySelector('.screen.active')); },
    currencyLabel: function (symbol, locale) { return /^(₽|RUB|руб\.)$/i.test(symbol) ? (locale === 'ru' ? 'руб.' : 'RUB') : symbol; },
    formatPrice: function (price, symbol, locale) {
      var value = price;
      if (price !== null && price !== '' && Number.isFinite(Number(price)) && Math.abs(Number(price)) <= Number.MAX_SAFE_INTEGER) {
        try { value = new Intl.NumberFormat(locale || 'ru', { maximumFractionDigits: 20 }).format(Number(price)); } catch (_) { /* Keep the API value if locale formatting is unavailable. */ }
      }
      return value + '\u00a0' + window.UMCShell.currencyLabel(symbol, locale);
    }
  };
  new MutationObserver(schedule).observe(document.getElementById('umc-app'), { attributes: true, attributeFilter: ['class', 'style', 'disabled'], childList: true, subtree: true, characterData: true });
  document.addEventListener('invalid', function (event) { event.target.setAttribute('aria-invalid', 'true'); }, true);
  document.addEventListener('input', function (event) {
    if (event.target.validity && event.target.validity.valid) event.target.removeAttribute('aria-invalid');
  });
  document.addEventListener('click', function (event) {
    var button = event.target.closest('button, .btn');
    if (button && !button.disabled) feedback(button.hasAttribute('data-role') ? 'selection' : 'light');
    var link = event.target.closest('a[href]');
    if (!link || event.defaultPrevented || !adapter || !/^https?:$/i.test(link.protocol)) return;
    var telegramLink = /(^|\.)t\.me$/i.test(link.hostname);
    var method = adapter.name === 'telegram' && telegramLink ? 'openTelegramLink' : 'openLink';
    if (call(adapter.host, method, [link.href])) event.preventDefault();
  });
  window.addEventListener('resize', updateViewport);
  if (window.visualViewport) window.visualViewport.addEventListener('resize', updateViewport);
  if (typeof media.addEventListener === 'function') media.addEventListener('change', applyTheme);
  Promise.resolve(window.__webAppReady).then(connect);
  schedule();
})();

/* Creator socials use the page's existing signed request helper and navigation. */
(function () {
  'use strict';
  var bridge = window.__umcSocialBridge;
  var screen = document.getElementById('screen-social-accounts');
  if (!bridge || !screen) return;
  var copies = {
    ru: {
      other: 'Другая площадка', platformName: 'Название площадки',
      title: 'Соцсети', intro: 'Дополните профиль креатора ссылками на ваши соцсети.',
      gate: 'Сначала подтвердите Instagram. После проверки можно добавить остальные соцсети.', verify: 'Подтвердить Instagram',
      verified: 'Подтверждено', unverified: 'Указано автором, не верифицировано', followers: 'Подписчики', unknown: 'Нет данных',
      url: 'Ссылка на профиль или канал',
      add: 'Добавить', edit: 'Изменить', remove: 'Удалить ссылку', save: 'Сохранить ссылку', cancel: 'Отменить',
      optional: 'Можно пропустить и добавить ссылку позже. Дополнительные ссылки не проходят проверку владения.',
      loading: 'Загружаем соцсети…', saving: 'Сохраняем ссылку…', removing: 'Удаляем ссылку…',
      empty: 'Соцсети пока не добавлены.',
      reload: 'Обновить список', back: 'Назад', saved: 'Ссылка сохранена.', removed: 'Ссылка удалена.', absent: 'Ссылка уже отсутствует.',
      loadError: 'Не удалось загрузить соцсети.', saveError: 'Не удалось сохранить ссылку.', removeError: 'Не удалось удалить ссылку.',
      authorityError: 'Доступ к соцсетям изменился. Обновите список, чтобы продолжить.'
    },
    en: {
      other: 'Other platform', platformName: 'Platform name',
      title: 'Social accounts', intro: 'Add your social links to your creator profile.',
      gate: 'Verify Instagram first. Other social accounts become available after verification.', verify: 'Verify Instagram',
      verified: 'Verified', unverified: 'Provided by creator, unverified', followers: 'Followers', unknown: 'No data',
      url: 'Profile or channel URL',
      add: 'Add', edit: 'Edit', remove: 'Remove link', save: 'Save link', cancel: 'Cancel',
      optional: 'You can skip and add a link later. Ownership of supplemental links is not verified.',
      loading: 'Loading social accounts…', saving: 'Saving link…', removing: 'Removing link…',
      empty: 'No social accounts added yet.',
      reload: 'Reload accounts', back: 'Back', saved: 'Link saved.', removed: 'Link removed.', absent: 'The link is already absent.',
      loadError: 'Could not load social accounts.', saveError: 'Could not save the link.', removeError: 'Could not remove the link.',
      authorityError: 'Access to social accounts has changed. Reload accounts to continue.'
    },
    kk: {
      other: 'Басқа платформа', platformName: 'Платформа атауы',
      title: 'Әлеуметтік желілер', intro: 'Креатор профиліне әлеуметтік желілеріңіздің сілтемелерін қосыңыз.',
      gate: 'Алдымен Instagram аккаунтын растаңыз. Содан кейін басқа әлеуметтік желілерді қосуға болады.', verify: 'Instagram аккаунтын растау',
      verified: 'Расталған', unverified: 'Автор көрсеткен, расталмаған', followers: 'Жазылушылар', unknown: 'Деректер жоқ',
      url: 'Профиль не арна сілтемесі',
      add: 'Қосу', edit: 'Өзгерту', remove: 'Сілтемені жою', save: 'Сілтемені сақтау', cancel: 'Бас тарту',
      optional: 'Қазір өткізіп, сілтемені кейін қосуға болады. Қосымша сілтемелерге иелік ету расталмайды.',
      loading: 'Әлеуметтік желілер жүктелуде…', saving: 'Сілтеме сақталуда…', removing: 'Сілтеме жойылуда…',
      empty: 'Әлеуметтік желілер әлі қосылмаған.',
      reload: 'Тізімді жаңарту', back: 'Артқа', saved: 'Сілтеме сақталды.', removed: 'Сілтеме жойылды.', absent: 'Сілтеме жоқ.',
      loadError: 'Әлеуметтік желілерді жүктеу мүмкін болмады.', saveError: 'Сілтемені сақтау мүмкін болмады.', removeError: 'Сілтемені жою мүмкін болмады.',
      authorityError: 'Әлеуметтік желілерге қолжетімділік өзгерді. Жалғастыру үшін тізімді жаңартыңыз.'
    },
    be: {
      other: 'Іншая пляцоўка', platformName: 'Назва пляцоўкі',
      title: 'Сацыяльныя сеткі', intro: 'Дадайце спасылкі на сацыяльныя сеткі ў профіль крэатара.',
      gate: 'Спачатку пацвердзіце Instagram. Пасля праверкі можна дадаць іншыя сацыяльныя сеткі.', verify: 'Пацвердзіць Instagram',
      verified: 'Пацверджана', unverified: 'Указана аўтарам, не праверана', followers: 'Падпісчыкі', unknown: 'Няма даных',
      url: 'Спасылка на профіль ці канал',
      add: 'Дадаць', edit: 'Змяніць', remove: 'Выдаліць спасылку', save: 'Захаваць спасылку', cancel: 'Адмяніць',
      optional: 'Можна прапусціць і дадаць спасылку пазней. Валоданне дадатковымі спасылкамі не правяраецца.',
      loading: 'Загружаем сацыяльныя сеткі…', saving: 'Захоўваем спасылку…', removing: 'Выдаляем спасылку…',
      empty: 'Сацыяльныя сеткі пакуль не дададзены.',
      reload: 'Абнавіць спіс', back: 'Назад', saved: 'Спасылка захавана.', removed: 'Спасылка выдалена.', absent: 'Спасылка ўжо адсутнічае.',
      loadError: 'Не атрымалася загрузіць сацыяльныя сеткі.', saveError: 'Не атрымалася захаваць спасылку.', removeError: 'Не атрымалася выдаліць спасылку.',
      authorityError: 'Доступ да сацыяльных сетак змяніўся. Абнавіце спіс, каб працягнуць.'
    },
    uz: {
      other: 'Boshqa platforma', platformName: 'Platforma nomi',
      title: 'Ijtimoiy tarmoqlar', intro: 'Kreator profilingizga ijtimoiy tarmoq havolalarini qo‘shing.',
      gate: 'Avval Instagram akkauntingizni tasdiqlang. Shundan so‘ng boshqa tarmoqlarni qo‘shish mumkin.', verify: 'Instagramni tasdiqlash',
      verified: 'Tasdiqlangan', unverified: 'Muallif ko‘rsatgan, tasdiqlanmagan', followers: 'Obunachilar', unknown: 'Ma’lumot yo‘q',
      url: 'Profil yoki kanal havolasi',
      add: 'Qo‘shish', edit: 'O‘zgartirish', remove: 'Havolani o‘chirish', save: 'Havolani saqlash', cancel: 'Bekor qilish',
      optional: 'Hozir o‘tkazib, havolani keyin qo‘shish mumkin. Qo‘shimcha havolalarga egalik tasdiqlanmaydi.',
      loading: 'Ijtimoiy tarmoqlar yuklanmoqda…', saving: 'Havola saqlanmoqda…', removing: 'Havola o‘chirilmoqda…',
      empty: 'Hali ijtimoiy tarmoqlar qo‘shilmagan.',
      reload: 'Ro‘yxatni yangilash', back: 'Orqaga', saved: 'Havola saqlandi.', removed: 'Havola o‘chirildi.', absent: 'Havola allaqachon yo‘q.',
      loadError: 'Ijtimoiy tarmoqlarni yuklab bo‘lmadi.', saveError: 'Havolani saqlab bo‘lmadi.', removeError: 'Havolani o‘chirib bo‘lmadi.',
      authorityError: 'Ijtimoiy tarmoqlarga kirish o‘zgardi. Davom etish uchun ro‘yxatni yangilang.'
    }
  };
  var names = { instagram: 'Instagram', tiktok: 'TikTok', youtube: 'YouTube', telegram: 'Telegram', vk: 'VK', dzen: 'Дзен', rutube: 'Rutube' };
  var samples = { tiktok: 'https://www.tiktok.com/@username', youtube: 'https://www.youtube.com/@channel', telegram: 'https://t.me/channel', vk: 'https://vk.com/username', dzen: 'https://dzen.ru/channel_name', rutube: 'https://rutube.ru/channel/123456/', other: 'https://example.com/profile' };
  var hosts = { instagram: ['instagram.com', 'www.instagram.com'], tiktok: ['tiktok.com', 'www.tiktok.com', 'm.tiktok.com'], youtube: ['youtube.com', 'www.youtube.com', 'm.youtube.com'], telegram: ['t.me', 'telegram.me', 'www.t.me'], vk: ['vk.com', 'www.vk.com', 'm.vk.com'], dzen: ['dzen.ru', 'www.dzen.ru'], rutube: ['rutube.ru', 'www.rutube.ru'] };
  var promptCopy = {
    ru: ['Добавьте другие соцсети', 'Сохраните ссылки на площадки, где вы ведёте свои аккаунты. Это можно сделать позже в профиле.', 'Добавить ссылки', 'Позже', 'Подписчики (необязательно)', 'Со слов креатора'],
    en: ['Add other social accounts', 'Save links to your accounts. You can also add them later in your profile.', 'Add links', 'Later', 'Followers (optional)', 'Reported by creator'],
    kk: ['Басқа әлеуметтік желілерді қосыңыз', 'Аккаунт сілтемелерін сақтаңыз. Оларды профильге кейін де қосуға болады.', 'Сілтемелерді қосу', 'Кейін', 'Жазылушылар саны (міндетті емес)', 'Креатор көрсеткен'],
    be: ['Дадайце іншыя сацсеткі', 'Захавайце спасылкі на свае акаўнты. Іх можна дадаць і пазней у профілі.', 'Дадаць спасылкі', 'Пазней', 'Падпісчыкі (неабавязкова)', 'Са слоў крэатара'],
    uz: ['Boshqa ijtimoiy tarmoqlarni qo‘shing', 'Akkaunt havolalarini saqlang. Ularni keyinroq profilingizda ham qo‘shishingiz mumkin.', 'Havolalarni qo‘shish', 'Keyinroq', 'Obunachilar (ixtiyoriy)', 'Ijodkor ko‘rsatgan']
  };
  var state = { loaded: false, accounts: [], next: null, showPrompt: false, busy: false, active: null, account: null, offered: false, returnScreen: 'screen-blogger-dashboard' };
  function byId(id) { return document.getElementById(id); }
  function locale() { var requested = window._me && window._me.locale; return copies[requested] ? requested : 'ru'; }
  function copy() { return copies[locale()] || copies.ru; }
  function node(tag, text, className) {
    var element = document.createElement(tag);
    if (text !== undefined) element.textContent = text;
    if (className) element.className = className;
    return element;
  }
  function verified() { return state.loaded && state.next !== 'instagram' && state.accounts.some(function (account) { return account.platform === 'instagram' && account.verified === true; }); }
  function localize() {
    var c = copy();
    var ids = { 'social-accounts-title': c.title, 'social-accounts-intro': c.intro, 'social-accounts-gate-text': c.gate, 'btn-social-verify-instagram': c.verify, 'social-accounts-empty': c.empty, 'lbl-social-account-url': c.url, 'lbl-social-platform-name': c.platformName, 'btn-social-save': c.save, 'btn-social-reload': c.reload, 'btn-social-back': c.back, 'social-account-editor-hint': c.optional, 'btn-blogger-social-accounts': c.title, 'btn-edit-profile-socials': c.title };
    Object.keys(ids).forEach(function (id) { byId(id).textContent = ids[id]; });
    ['social-prompt-title', 'social-prompt-text', 'btn-social-prompt-add', 'btn-social-prompt-later', 'lbl-social-followers'].forEach(function (id, i) {
      byId(id).textContent = promptCopy[locale()][i];
    });
  }
  function platformLabel(network) { return network === 'other' ? copy().other : names[network]; }
  function setPlatformName(network, name) {
    var field = byId('social-platform-name');
    var other = network === 'other';
    byId('social-platform-name-field').hidden = !other;
    field.disabled = !other;
    field.required = other;
    field.value = name || '';
  }
  function busy(value, message) {
    state.busy = value;
    screen.setAttribute('aria-busy', value ? 'true' : 'false');
    screen.querySelectorAll('button, input, select').forEach(function (element) { element.disabled = value || (element.id === 'social-platform-name' && state.active !== 'other'); });
    byId('social-accounts-state').textContent = value ? message : '';
    window.UMCShell.syncControls();
  }
  function authorityLost(exception) {
    return exception && (
      (exception.status === 401 && exception.message === 'financial_session_invalid') ||
      (exception.status === 404 && exception.message === 'existing_financial_account_required') ||
      (exception.status === 403 && (exception.message === 'financial_principal_changed' || exception.message === 'social_account_unavailable'))
    );
  }
  function discardEditor() {
    state.loaded = false;
    state.accounts = [];
    state.next = null;
    state.showPrompt = false;
    state.active = null;
    state.account = null;
    byId('social-accounts-list').replaceChildren();
    var form = byId('form-social-account');
    form.hidden = true;
    delete form.dataset.network;
    setPlatformName(null);
    byId('social-account-url').value = '';
    byId('social-account-url').placeholder = '';
    byId('social-account-url').removeAttribute('aria-invalid');
    byId('social-followers').value = '';
    byId('social-account-editor-title').textContent = '';
    byId('social-accounts-add-options').replaceChildren();
    ['social-accounts-add-options', 'social-accounts-gate', 'social-accounts-empty'].forEach(function (id) { byId(id).hidden = true; });
    clearMessages();
    window.UMCShell.syncControls();
  }
  function error(message, exception) {
    if (authorityLost(exception)) { discardEditor(); message = copy().authorityError; }
    byId('social-accounts-error').textContent = message;
  }
  function clearMessages() { byId('social-accounts-error').textContent = ''; byId('social-accounts-success').textContent = ''; }
  function safeLink(account) {
    try {
      var url = new URL(account.url);
      return url.protocol === 'https:' && !url.username && !url.password && !url.port && (account.platform === 'other' ? url.hostname.includes('.') : (hosts[account.platform] || []).indexOf(url.hostname) !== -1) ? url.href : null;
    } catch (_) { return null; }
  }
  function date(value) {
    var parsed = new Date(value);
    if (!value || isNaN(parsed.getTime())) return null;
    try { return new Intl.DateTimeFormat(locale(), { day: 'numeric', month: 'short', year: 'numeric' }).format(parsed); } catch (_) { return parsed.toISOString().slice(0, 10); }
  }
  function action(text, handler, dataName, value) {
    var button = node('button', text, 'btn btn-secondary');
    button.type = 'button';
    if (dataName) button.dataset[dataName] = value;
    button.addEventListener('click', handler);
    return button;
  }
  function editor(network, account) {
    if (!verified() || !samples[network]) return;
    state.active = network;
    state.account = account || null;
    var form = byId('form-social-account');
    form.hidden = false;
    byId('social-accounts-add-options').hidden = true;
    form.dataset.network = network;
    byId('social-account-editor-title').textContent = (account ? copy().edit : copy().add) + ' ' + platformLabel(network);
    setPlatformName(network, account && account.handle);
    byId('social-account-url').value = account ? account.url : '';
    byId('social-account-url').placeholder = samples[network];
    byId('social-account-url').removeAttribute('aria-invalid');
    byId('social-followers').value = account && account.metrics_source === 'creator_self_reported' && Number.isSafeInteger(account.followers_count) ? String(account.followers_count) : '';
    byId('btn-social-skip').textContent = copy().cancel;
    byId(network === 'other' ? 'social-platform-name' : 'social-account-url').focus();
    window.UMCShell.syncControls();
  }
  function render() {
    var c = copy();
    localize();
    var list = byId('social-accounts-list');
    list.replaceChildren();
    state.accounts.forEach(function (account) {
      var item = node('li', undefined, 'umc-social-account');
      item.dataset.socialNetwork = account.platform;
      item.appendChild(node('h2', account.platform === 'other' ? account.handle || c.other : platformLabel(account.platform) || account.platform));
      item.appendChild(node('span', account.verified === true ? c.verified : c.unverified, 'umc-social-badge' + (account.verified === true ? ' is-verified' : '')));
      var url = safeLink(account);
      var link = node(url ? 'a' : 'p', account.platform === 'other' ? account.url : account.handle || account.url || '');
      if (url) { link.href = url; link.target = '_blank'; link.rel = 'noopener noreferrer'; }
      item.appendChild(link);
      var observed = date(account.metrics_fetched_at);
      var count = Number.isSafeInteger(account.followers_count) && account.followers_count >= 0 && account.metrics_source && observed ? account.followers_count : null;
      item.appendChild(node('p', c.followers + ': ' + (count === null ? c.unknown : new Intl.NumberFormat(locale()).format(count))));
      if (count !== null) {
        var source = account.metrics_source === 'creator_self_reported' ? promptCopy[locale()][5] : account.metrics_source;
        item.appendChild(node('p', source + ' · ' + observed));
      }
      if (account.platform !== 'instagram' && verified() && samples[account.platform]) {
        var controls = node('div', undefined, 'umc-social-actions');
        controls.appendChild(action(c.edit, function () { clearMessages(); editor(account.platform, account); }, 'socialEdit', account.platform));
        controls.appendChild(action(c.remove, function () { remove(account); }, 'socialRemove', account.platform));
        item.appendChild(controls);
      }
      list.appendChild(item);
    });
    byId('social-accounts-empty').hidden = state.accounts.length > 0;
    byId('social-accounts-gate').hidden = verified();
    byId('form-social-account').hidden = true;
    state.active = null;
    setPlatformName(null);
    var options = byId('social-accounts-add-options');
    options.hidden = false;
    options.replaceChildren();
    if (verified()) {
      ['vk', 'youtube', 'tiktok', 'telegram', 'dzen', 'rutube', 'other'].forEach(function (network) {
        if (!state.accounts.some(function (account) { return account.platform === network; })) {
          options.appendChild(action(network === 'other' ? c.other : c.add + ' ' + platformLabel(network), function () {
            clearMessages();
            editor(network);
          }, 'socialAdd', network));
        }
      });
    }
  }
  function load(message) {
    if (state.busy) return Promise.resolve();
    state.loaded = false;
    busy(true, copy().loading);
    byId('social-accounts-error').textContent = '';
    return bridge.request('/social/accounts', {}).then(function (data) {
      if (!data || !Array.isArray(data.accounts) || (data.next_platform !== null && !names[data.next_platform])) throw new Error(copy().loadError);
      state.accounts = data.accounts;
      state.loaded = true;
      state.next = data.next_platform;
      state.showPrompt = data.show_prompt === true;
      render();
      if (message) byId('social-accounts-success').textContent = message;
    }).catch(function (exception) {
      // A failed gate lookup cannot expose supplemental input controls.
      state.loaded = false;
      byId('form-social-account').hidden = true;
      byId('social-accounts-gate').hidden = true;
      byId('social-accounts-add-options').hidden = true;
      screen.querySelectorAll('.umc-social-actions').forEach(function (controls) { controls.hidden = true; });
      error(copy().loadError, exception);
    }).then(function () { busy(false); });
  }
  function open() {
    if (state.busy) return;
    var current = document.querySelector('.screen.active');
    if (current && current !== screen && current.id !== 'screen-social-prompt') state.returnScreen = current.id;
    localize(); clearMessages();
    bridge.showScreen(screen.id);
    load();
  }
  function remove(account) {
    if (state.busy || !verified() || account.platform === 'instagram') return;
    clearMessages(); busy(true, copy().removing);
    bridge.request('/social/accounts/remove', { account_id: account.account_id }).then(function (data) {
      busy(false);
      return load(data.removed === true ? copy().removed : copy().absent);
    }).catch(function (exception) { busy(false); error(copy().removeError, exception); });
  }
  byId('btn-blogger-social-accounts').addEventListener('click', open);
  byId('btn-edit-profile-socials').addEventListener('click', open);
  byId('btn-social-reload').addEventListener('click', function () { load(); });
  byId('btn-social-back').addEventListener('click', function () { bridge.showScreen(state.returnScreen); });
  byId('btn-social-verify-instagram').addEventListener('click', function () {
    bridge.showScreen('screen-blogger-dashboard');
    byId('btn-blogger-confirm-instagram').click();
  });
  byId('btn-social-prompt-add').addEventListener('click', open);
  byId('btn-social-prompt-later').addEventListener('click', function () {
    var button = this;
    button.disabled = true;
    byId('social-prompt-error').textContent = '';
    bridge.request('/social/prompt/dismiss', {}).then(function () {
      bridge.showScreen('screen-blogger-dashboard');
    }).catch(function () {
      byId('social-prompt-error').textContent = copy().loadError;
    }).finally(function () { button.disabled = false; });
  });
  byId('btn-social-skip').addEventListener('click', function () {
    if (!state.busy) {
      clearMessages();
      render();
      window.UMCShell.syncControls();
    }
  });
  byId('social-account-url').addEventListener('input', function () {
    if (state.account && this.value.trim() !== state.account.url) {
      byId('social-followers').value = '';
      state.account = null;
    }
  });
  byId('form-social-account').addEventListener('submit', function (event) {
    event.preventDefault();
    if (state.busy || !verified() || !samples[state.active]) return;
    var network = state.active;
    var followers = byId('social-followers').value;
    var payload = {
      network: network,
      url: byId('social-account-url').value.trim(),
      reported_followers: followers === '' ? null : Number(followers)
    };
    if (network === 'other') payload.platform_name = byId('social-platform-name').value.trim();
    clearMessages(); busy(true, copy().saving);
    bridge.request('/social/accounts/save', payload).then(function () {
      busy(false);
      return load(copy().saved);
    }).catch(function (exception) { busy(false); error(copy().saveError, exception); });
  });
  function context() {
    localize();
    var me = window._me;
    byId('btn-edit-profile-socials').style.display = me && me.has_blogger_profile ? '' : 'none';
    if (!me || !me.has_blogger_profile || !me.blogger_profile || !me.blogger_profile.confirmed || state.offered) return;
    state.offered = true;
    // Fetch after canonical confirmation; the server decides whether a prompt remains.
    load().then(function () {
      var current = document.querySelector('.screen.active');
      if (!verified() || !current || current.id !== 'screen-blogger-dashboard') return;
      state.returnScreen = current.id;
      if (new URLSearchParams(location.search).get('view') === 'socials') {
        bridge.showScreen(screen.id);
      } else if (state.showPrompt) {
        byId('social-prompt-error').textContent = '';
        bridge.showScreen('screen-social-prompt');
      }
    });
  }
  document.addEventListener('umc:creator-state', context);
  context();
})();
