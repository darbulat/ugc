(function () {
  'use strict';

  var copy = {
    ru: {
      title: 'Моя база креаторов', blocked: 'Бот недоступен', card: 'Креатор',
      search: 'Имя, ник или город', noMatches: 'Креаторы по этому запросу не найдены.',
      loading: 'Загружаем…', empty: 'База пока пуста. Поделитесь личной ссылкой из партнёрской программы. Здесь появятся креаторы, которые заполнят анкету по вашей ссылке.',
      emptyBlocked: 'Среди ваших креаторов нет тех, у кого бот недоступен.',
      error: 'Не удалось загрузить данные. Вернитесь назад и попробуйте ещё раз.',
      missing: 'Эта карточка больше недоступна.', verified: 'Instagram подтверждён',
      prev: '← Назад', next: 'Далее →', home: 'К кабинету менеджера', back: 'К списку'
    },
    en: {
      title: 'My creators', blocked: 'Bot unavailable', card: 'Creator',
      search: 'Name, handle or city', noMatches: 'No creators match your search.',
      loading: 'Loading…', empty: 'Share your personal link from the partner program. Creators who complete their profile through your link will appear here.',
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
  var queueCopy = {
    ru: ['Подтверждение Instagram', 'Все', 'Подтверждены', 'Не подтверждены', 'Нужно связаться', 'Instagram не подтверждён', 'Написать в Telegram', 'Нет контакта в Telegram', 'Написал', 'Напомнить завтра', 'Связаться после', 'В этой группе пока никого нет.', 'Не удалось сохранить напоминание. Попробуйте ещё раз.'],
    en: ['Instagram verification', 'All', 'Verified', 'Unverified', 'To contact', 'Instagram not verified', 'Message on Telegram', 'No Telegram contact', 'Contacted', 'Remind me tomorrow', 'Contact after', 'No creators in this group.', 'Could not save the reminder. Try again.'],
    kk: ['Instagram растауы', 'Барлығы', 'Расталған', 'Расталмаған', 'Байланысу керек', 'Instagram расталмаған', 'Telegram-да жазу', 'Telegram байланысы жоқ', 'Хабарластым', 'Ертең еске салу', 'Кейін хабарласу:', 'Бұл топта әзірге ешкім жоқ.', 'Еске салу сақталмады. Қайта көріңіз.'],
    be: ['Пацвярджэнне Instagram', 'Усе', 'Пацверджаныя', 'Непацверджаныя', 'Трэба звязацца', 'Instagram не пацверджаны', 'Напісаць у Telegram', 'Няма кантакту ў Telegram', 'Напісаў', 'Нагадаць заўтра', 'Звязацца пасля', 'У гэтай групе пакуль нікога няма.', 'Не ўдалося захаваць напамін. Паспрабуйце яшчэ раз.'],
    uz: ['Instagram tasdig‘i', 'Barchasi', 'Tasdiqlangan', 'Tasdiqlanmagan', 'Bog‘lanish kerak', 'Instagram tasdiqlanmagan', 'Telegramda yozish', 'Telegram kontakti yo‘q', 'Yozdim', 'Ertaga eslatish', 'Bog‘lanish vaqti:', 'Bu guruhda hali hech kim yo‘q.', 'Eslatma saqlanmadi. Qayta urinib ko‘ring.']
  };
  var queueKeys = ['filter', 'all', 'verifiedFilter', 'unverified', 'due', 'notVerified',
    'write', 'noContact', 'contacted', 'tomorrow', 'scheduled', 'emptyFilter', 'saveError'];
  Object.keys(queueCopy).forEach(function (locale) {
    queueKeys.forEach(function (key, index) {
      copy[locale][key] = queueCopy[locale][index];
    });
  });
  var listScreen = 'screen-invited-creators';
  var cardScreen = 'screen-invited-creator-card';
  var path = '/manager/invited-creators';
  var context = null;
  var page = 0;
  var requestVersion = 0;
  var searchTimer;

  function byId(id) { return document.getElementById(id); }
  var searchInput = byId('invited-search');
  var instagramFilter = 'all';
  var instagramFilters = element('div', '', 'umc-directory-actions');
  instagramFilters.hidden = true;
  instagramFilters.setAttribute('role', 'group');
  var instagramButtons = ['all', 'verified', 'unverified'].map(function (filter) {
    var button = element('button', '', 'btn btn-secondary');
    button.type = 'button';
    button.dataset.instagramFilter = filter;
    instagramFilters.appendChild(button);
    return button;
  });
  var followups = element('button', '', 'btn btn-secondary');
  followups.type = 'button';
  followups.hidden = true;
  byId('invited-search-form').after(followups, instagramFilters);
  function words() { return copy[(window._me || {}).locale] || copy.ru; }
  function setText(id, text) { byId(id).textContent = text; }

  function localize() {
    var lang = words();
    setText('btn-invited-creators', lang.title);
    setText('invited-creators-title', lang.title);
    setText('invited-search-label', lang.search);
    setText('invited-bot-label', lang.blocked);
    instagramFilters.setAttribute('aria-label', lang.filter);
    instagramButtons.forEach(function (button) {
      var filter = button.dataset.instagramFilter;
      button.textContent = filter === 'verified' ? lang.verifiedFilter : lang[filter];
    });
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
    followups.hidden = true;
    instagramFilters.hidden = true;
  }

  function showContact(parent, creator, lang) {
    if (/^https:\/\/t\.me\/[A-Za-z0-9_]{5,32}$/.test(creator.telegram_url || '')) {
      var link = element('a', lang.write, 'btn btn-secondary');
      link.href = creator.telegram_url;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      parent.appendChild(link);
    } else if (creator.telegram_url === null) {
      parent.appendChild(element('p', lang.noContact, 'umc-directory-detail'));
    }
  }

  function showFollowupActions(row, creator, lang, version) {
    if (creator.instagram_verified !== false) return;
    if (creator.remind_at && !creator.followup_due) {
      var date = new Intl.DateTimeFormat((window._me || {}).locale || 'ru', {
        dateStyle: 'medium', timeStyle: 'short'
      }).format(new Date(creator.remind_at));
      row.appendChild(element('p', lang.scheduled + ' ' + date, 'umc-directory-detail'));
    }
    var actions = element('div', '', 'umc-directory-actions');
    var feedback = element('p', '', 'umc-directory-detail error');
    feedback.setAttribute('role', 'alert');
    ['contacted', 'tomorrow'].forEach(function (action) {
      var button = element('button', lang[action], 'btn btn-secondary');
      button.type = 'button';
      button.addEventListener('click', function () {
        if (!activeRequest(version, listScreen)) return;
        actions.querySelectorAll('button').forEach(function (control) {
          control.disabled = true;
        });
        feedback.textContent = '';
        context.request(path + '/' + encodeURIComponent(creator.creator_id) + '/followup', {
          action: action
        }).then(function () {
          if (!activeRequest(version, listScreen)) return;
          if (instagramFilter === 'due') page = 0;
          showList();
        }).catch(function () {
          if (!activeRequest(version, listScreen)) return;
          feedback.textContent = lang.saveError;
          actions.querySelectorAll('button').forEach(function (control) {
            control.disabled = false;
          });
        });
      });
      actions.appendChild(button);
    });
    row.append(actions, feedback);
  }

  function selectInstagram(filter) {
    instagramFilter = filter;
    instagramButtons.forEach(function (button) {
      button.setAttribute('aria-pressed', String(button.dataset.instagramFilter === filter));
    });
    followups.setAttribute('aria-pressed', String(filter === 'due'));
  }

  function showList() {
    clearTimeout(searchTimer);
    var lang = words();
    var version = ++requestVersion;
    var list = byId('invited-creators-list');
    var filtered = byId('invited-bot-filter').checked;
    var query = searchInput.value.trim();
    var instagram = instagramFilter;
    list.replaceChildren();
    byId('invited-prev').hidden = true;
    byId('invited-next').hidden = true;
    setText('invited-creators-status', lang.loading);
    if (!byId(listScreen).classList.contains('active')) window.__umcAppBridge.showScreen(listScreen);
    var params = { bot_unavailable: filtered, page: page };
    if (query) params.q = query;
    if (instagram !== 'all') params.instagram = instagram;
    context.request(path, params).then(function (data) {
      if (!activeRequest(version, listScreen)) return;
      followups.hidden = !Number.isInteger(data.followup_count);
      instagramFilters.hidden = followups.hidden;
      if (!followups.hidden) followups.textContent = lang.due + ': ' + data.followup_count;
      var emptyMessage = query ? lang.noMatches : instagram !== 'all' ?
        lang.emptyFilter : filtered ? lang.emptyBlocked : lang.empty;
      setText('invited-creators-status', data.creators.length ? '' : emptyMessage);
      data.creators.forEach(function (creator) {
        var label = [creator.name || lang.card, creator.city];
        if (creator.status === 'bot_blocked') label.push(lang.blocked);
        var button = element('button', label.filter(Boolean).join(' · '), 'btn btn-secondary');
        button.type = 'button';
        button.addEventListener('click', function () { showCard(creator.creator_id); });
        var row = element('li', '');
        row.appendChild(button);
        if (typeof creator.instagram_verified === 'boolean') {
          row.appendChild(element('p', creator.instagram_verified ? lang.verified : lang.notVerified, 'umc-directory-detail'));
        }
        showContact(row, creator, lang);
        showFollowupActions(row, creator, lang, version);
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
      details.appendChild(element('p', creator.instagram_verified ? lang.verified : lang.notVerified));
      showContact(details, creator, lang);
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

  function openDirectory() {
    if (!(window._me || {}).is_manager) return;
    clear();
    context = window.__umcAppBridge.createRequestContext();
    if (!context.isCurrent()) return;
    page = 0;
    searchInput.value = '';
    byId('invited-bot-filter').checked = false;
    selectInstagram('all');
    showList();
  }

  byId('btn-invited-creators').addEventListener('click', openDirectory);
  document.addEventListener('umc:app-ready', function () {
    var params = new URLSearchParams(location.search);
    if (params.get('view') === 'manager' && params.get('section') === 'creators' &&
        byId('screen-manager-orders').classList.contains('active')) {
      openDirectory();
    }
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
  instagramButtons.forEach(function (button) {
    button.addEventListener('click', function () {
      if (!context) return;
      selectInstagram(button.dataset.instagramFilter);
      page = 0;
      showList();
    });
  });
  followups.addEventListener('click', function () {
    if (!context) return;
    selectInstagram(instagramFilter === 'due' ? 'all' : 'due');
    searchInput.value = '';
    byId('invited-bot-filter').checked = false;
    page = 0;
    showList();
  });
  document.addEventListener('visibilitychange', function () {
    if (!document.hidden && context && byId(listScreen).classList.contains('active')) showList();
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
    if (screen === listScreen && !context) openDirectory();
    if (context && screen !== listScreen && screen !== cardScreen) clear();
  });
}());
