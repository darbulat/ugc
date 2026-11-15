(function () {
  'use strict';

  var copy = {
    ru: {
      title: 'Приглашённые креаторы', blocked: 'Бот недоступен', card: 'Креатор',
      search: 'Имя, ник или город', noMatches: 'Креаторы по этому запросу не найдены.',
      loading: 'Загружаем…', empty: 'У вас пока нет приглашённых креаторов.',
      emptyBlocked: 'Среди ваших креаторов нет тех, у кого бот недоступен.',
      error: 'Не удалось загрузить данные. Вернитесь назад и попробуйте ещё раз.',
      missing: 'Эта карточка больше недоступна.', verified: 'Instagram подтверждён',
      prev: '← Назад', next: 'Далее →', home: 'К кабинету менеджера', back: 'К списку'
    },
    en: {
      title: 'Invited creators', blocked: 'Bot unavailable', card: 'Creator',
      search: 'Name, handle or city', noMatches: 'No creators match your search.',
      loading: 'Loading…', empty: 'You have no invited creators yet.',
      emptyBlocked: 'None of your creators have an unavailable bot.',
      error: 'Could not load data. Go back and try again.',
      missing: 'This profile is no longer available.', verified: 'Instagram verified',
      prev: '← Previous', next: 'Next →', home: 'Back to manager dashboard', back: 'Back to list'
    },
    kk: {
      title: 'Шақырылған креаторлар', blocked: 'Бот қолжетімсіз', card: 'Креатор',
      search: 'Аты, никнеймі немесе қаласы', noMatches: 'Сұрауыңыз бойынша креаторлар табылмады.',
      loading: 'Жүктелуде…', empty: 'Шақырылған креаторлар әзірге жоқ.',
      emptyBlocked: 'Боты қолжетімсіз креаторлар жоқ.',
      error: 'Деректер жүктелмеді. Артқа оралып, қайта көріңіз.',
      missing: 'Бұл профиль енді қолжетімсіз.', verified: 'Instagram расталды',
      prev: '← Артқа', next: 'Келесі →', home: 'Менеджер кабинетіне', back: 'Тізімге'
    },
    be: {
      title: 'Запрошаныя крэатары', blocked: 'Бот недаступны', card: 'Крэатар',
      search: 'Імя, нік або горад', noMatches: 'Па вашым запыце крэатараў не знойдзена.',
      loading: 'Загрузка…', empty: 'У вас пакуль няма запрошаных крэатараў.',
      emptyBlocked: 'Сярод вашых крэатараў няма тых, у каго бот недаступны.',
      error: 'Не ўдалося загрузіць даныя. Вярніцеся і паспрабуйце яшчэ раз.',
      missing: 'Гэты профіль больш недаступны.', verified: 'Instagram пацверджаны',
      prev: '← Назад', next: 'Далей →', home: 'У кабінет менеджара', back: 'Да спіса'
    },
    uz: {
      title: 'Taklif qilingan ijodkorlar', blocked: 'Bot ishlamayapti', card: 'Ijodkor',
      search: 'Ism, nik yoki shahar', noMatches: 'So‘rovingizga mos ijodkorlar topilmadi.',
      loading: 'Yuklanmoqda…', empty: 'Hozircha taklif qilingan ijodkorlar yo‘q.',
      emptyBlocked: 'Boti ishlamayotgan ijodkorlar yo‘q.',
      error: 'Ma’lumotlar yuklanmadi. Orqaga qaytib, yana urinib ko‘ring.',
      missing: 'Bu profil endi mavjud emas.', verified: 'Instagram tasdiqlangan',
      prev: '← Orqaga', next: 'Keyingi →', home: 'Menejer kabinetiga', back: 'Ro‘yxatga'
    }
  };
  var listScreen = 'screen-invited-creators';
  var cardScreen = 'screen-invited-creator-card';
  var path = '/manager/invited-creators';
  var context = null;
  var page = 0;
  var requestVersion = 0;
  var searchTimer;

  function byId(id) { return document.getElementById(id); }
  var searchInput = byId('invited-search');
  function words() { return copy[(window._me || {}).locale] || copy.ru; }
  function setText(id, text) { byId(id).textContent = text; }

  function localize() {
    var lang = words();
    setText('btn-invited-creators', lang.title);
    setText('invited-creators-title', lang.title);
    setText('invited-search-label', lang.search);
    setText('invited-bot-label', lang.blocked);
    setText('invited-prev', lang.prev);
    setText('invited-next', lang.next);
    setText('invited-back', lang.home);
    setText('invited-card-back', lang.back);
  }

  function element(tag, text, className) {
    var result = document.createElement(tag);
    result.textContent = text;
    if (className) result.className = className;
    return result;
  }

  function activeRequest(version, screen) {
    if (!context || requestVersion !== version || !byId(screen).classList.contains('active')) {
      return false;
    }
    if (context.isCurrent()) return true;
    clear();
    return false;
  }

  function clear() {
    clearTimeout(searchTimer);
    if (context) context.dispose();
    context = null;
    requestVersion++;
    byId('invited-creators-list').replaceChildren();
    byId('invited-creator-details').replaceChildren();
    setText('invited-creator-title', words().card);
    setText('invited-creator-status', '');
    setText('invited-creators-status', '');
    byId('invited-prev').hidden = true;
    byId('invited-next').hidden = true;
  }

  function showList() {
    clearTimeout(searchTimer);
    var lang = words();
    var version = ++requestVersion;
    var list = byId('invited-creators-list');
    var filtered = byId('invited-bot-filter').checked;
    var query = searchInput.value.trim();
    list.replaceChildren();
    byId('invited-prev').hidden = true;
    byId('invited-next').hidden = true;
    setText('invited-creators-status', lang.loading);
    if (!byId(listScreen).classList.contains('active')) window.__umcAppBridge.showScreen(listScreen);
    var params = { bot_unavailable: filtered, page: page };
    if (query) params.q = query;
    context.request(path, params).then(function (data) {
      if (!activeRequest(version, listScreen)) return;
      var emptyMessage = query ? lang.noMatches : filtered ? lang.emptyBlocked : lang.empty;
      setText('invited-creators-status', data.creators.length ? '' : emptyMessage);
      data.creators.forEach(function (creator) {
        var label = [creator.name || lang.card, creator.city];
        if (creator.status === 'bot_blocked') label.push(lang.blocked);
        var button = element('button', label.filter(Boolean).join(' · '), 'btn btn-secondary');
        button.type = 'button';
        button.addEventListener('click', function () { showCard(creator.creator_id); });
        var row = element('li', '');
        row.appendChild(button);
        list.appendChild(row);
      });
      byId('invited-prev').hidden = page === 0;
      byId('invited-next').hidden = !data.has_more;
    }).catch(function () {
      if (!activeRequest(version, listScreen)) return;
      setText('invited-creators-status', lang.error);
      byId('invited-prev').hidden = page === 0;
    });
  }

  function showCard(creatorId) {
    clearTimeout(searchTimer);
    var lang = words();
    var version = ++requestVersion;
    var details = byId('invited-creator-details');
    details.replaceChildren();
    setText('invited-creator-title', lang.card);
    setText('invited-creator-status', lang.loading);
    window.__umcAppBridge.showScreen(cardScreen);
    context.request(path + '/' + encodeURIComponent(creatorId), {}).then(function (creator) {
      if (!activeRequest(version, cardScreen)) return;
      setText('invited-creator-title', creator.name || lang.card);
      setText('invited-creator-status', creator.status === 'bot_blocked' ? lang.blocked : '');
      if (creator.city) details.appendChild(element('p', creator.city));
      if (creator.instagram_verified) details.appendChild(element('p', lang.verified));
      creator.links.forEach(function (link) {
        if (!link.url.startsWith('https://')) return;
        var anchor = element('a', link.label, 'btn btn-secondary');
        anchor.href = link.url;
        anchor.target = '_blank';
        anchor.rel = 'noopener noreferrer';
        details.appendChild(anchor);
      });
    }).catch(function (error) {
      if (!activeRequest(version, cardScreen)) return;
      setText('invited-creator-status', error.status === 404 ? lang.missing : lang.error);
    });
  }

  byId('btn-invited-creators').addEventListener('click', function () {
    if (!(window._me || {}).is_manager) return;
    clear();
    context = window.__umcAppBridge.createRequestContext();
    page = 0;
    searchInput.value = '';
    byId('invited-bot-filter').checked = false;
    showList();
  });
  searchInput.addEventListener('input', function (event) {
    if (!context || event.isComposing) return;
    clearTimeout(searchTimer);
    requestVersion++;
    page = 0;
    byId('invited-prev').hidden = true;
    byId('invited-next').hidden = true;
    searchTimer = setTimeout(showList, 250);
  });
  byId('invited-search-form').addEventListener('submit', function (event) {
    event.preventDefault();
    if (!context) return;
    page = 0;
    showList();
  });
  byId('invited-bot-filter').addEventListener('change', function () {
    if (!context) return;
    page = 0;
    showList();
  });
  byId('invited-prev').addEventListener('click', function () {
    if (!context) return;
    page = Math.max(0, page - 1);
    showList();
  });
  byId('invited-next').addEventListener('click', function () {
    if (!context) return;
    page += 1;
    showList();
  });
  byId('invited-card-back').addEventListener('click', function () {
    if (context) showList();
    else window.__umcAppBridge.showScreen('screen-manager-orders');
  });
  byId('invited-back').addEventListener('click', function () {
    window.__umcAppBridge.showScreen('screen-manager-orders');
  });
  document.addEventListener('umc:screen-change', function (event) {
    var screen = event.detail.screen;
    if (screen === 'screen-manager-orders') localize();
    if (context && screen !== listScreen && screen !== cardScreen) clear();
  });
}());
