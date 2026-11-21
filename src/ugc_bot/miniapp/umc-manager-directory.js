(function () {
  'use strict';

  var copy = {
    ru: {
      title: 'Моя база креаторов', blocked: 'Бот недоступен', card: 'Креатор',
      search: 'Имя, ник или город', noMatches: 'Креаторы по этому запросу не найдены.',
      all: 'Любой статус Instagram', referral: 'К личной ссылке', reset: 'Сбросить поиск и фильтры',
      loading: 'Загружаем…', empty: 'База пока пуста. Поделитесь личной ссылкой из партнёрской программы. Здесь появятся креаторы, которые заполнят анкету по вашей ссылке.',
      emptyBlocked: 'Среди ваших креаторов нет тех, у кого бот недоступен.',
      error: 'Не удалось загрузить данные. Вернитесь назад и попробуйте ещё раз.',
      missing: 'Эта карточка больше недоступна.', verified: 'Instagram подтверждён',
      prev: '← Назад', next: 'Далее →', home: 'К кабинету менеджера', back: 'К списку'
    },
    en: {
      title: 'My creators', blocked: 'Bot unavailable', card: 'Creator',
      search: 'Name, handle or city', noMatches: 'No creators match your search.',
      all: 'Any Instagram status', referral: 'Go to personal link', reset: 'Clear search and filters',
      loading: 'Loading…', empty: 'Share your personal link from the partner program. Creators who complete their profile through your link will appear here.',
      emptyBlocked: 'None of your creators have an unavailable bot.',
      error: 'Could not load data. Go back and try again.',
      missing: 'This profile is no longer available.', verified: 'Instagram verified',
      prev: '← Previous', next: 'Next →', home: 'Back to manager dashboard', back: 'Back to list'
    },
    kk: {
      title: 'Шақырылған креаторлар', blocked: 'Бот қолжетімсіз', card: 'Креатор',
      search: 'Аты, никнеймі немесе қаласы', noMatches: 'Сұрауыңыз бойынша креаторлар табылмады.',
      all: 'Instagram-ның кез келген күйі', referral: 'Жеке сілтемеге өту', reset: 'Іздеу мен сүзгілерді тазарту',
      loading: 'Жүктелуде…', empty: 'Шақырылған креаторлар әзірге жоқ.',
      emptyBlocked: 'Боты қолжетімсіз креаторлар жоқ.',
      error: 'Деректер жүктелмеді. Артқа оралып, қайта көріңіз.',
      missing: 'Бұл профиль енді қолжетімсіз.', verified: 'Instagram расталды',
      prev: '← Артқа', next: 'Келесі →', home: 'Менеджер кабинетіне', back: 'Тізімге'
    },
    be: {
      title: 'Запрошаныя крэатары', blocked: 'Бот недаступны', card: 'Крэатар',
      search: 'Імя, нік або горад', noMatches: 'Па вашым запыце крэатараў не знойдзена.',
      all: 'Любы статус Instagram', referral: 'Да асабістай спасылкі', reset: 'Скінуць пошук і фільтры',
      loading: 'Загрузка…', empty: 'У вас пакуль няма запрошаных крэатараў.',
      emptyBlocked: 'Сярод вашых крэатараў няма тых, у каго бот недаступны.',
      error: 'Не ўдалося загрузіць даныя. Вярніцеся і паспрабуйце яшчэ раз.',
      missing: 'Гэты профіль больш недаступны.', verified: 'Instagram пацверджаны',
      prev: '← Назад', next: 'Далей →', home: 'У кабінет менеджара', back: 'Да спіса'
    },
    uz: {
      title: 'Taklif qilingan ijodkorlar', blocked: 'Bot ishlamayapti', card: 'Ijodkor',
      search: 'Ism, nik yoki shahar', noMatches: 'So‘rovingizga mos ijodkorlar topilmadi.',
      all: 'Instagram holati: barchasi', referral: 'Shaxsiy havolaga o‘tish', reset: 'Qidiruv va filtrlarni tozalash',
      loading: 'Yuklanmoqda…', empty: 'Hozircha taklif qilingan ijodkorlar yo‘q.',
      emptyBlocked: 'Boti ishlamayotgan ijodkorlar yo‘q.',
      error: 'Ma’lumotlar yuklanmadi. Orqaga qaytib, yana urinib ko‘ring.',
      missing: 'Bu profil endi mavjud emas.', verified: 'Instagram tasdiqlangan',
      prev: '← Orqaga', next: 'Keyingi →', home: 'Menejer kabinetiga', back: 'Ro‘yxatga'
    }
  };
  var queueCopy = {
    ru: ['Подтверждение Instagram', 'Нужно связаться', 'Instagram не подтверждён', 'Написать в Telegram', 'Нет контакта в Telegram', 'Написал', 'Напомнить завтра', 'Связаться после', 'В этой группе пока никого нет.', 'Не удалось сохранить напоминание. Попробуйте ещё раз.'],
    en: ['Instagram verification', 'To contact', 'Instagram not verified', 'Message on Telegram', 'No Telegram contact', 'Contacted', 'Remind me tomorrow', 'Contact after', 'No creators in this group.', 'Could not save the reminder. Try again.'],
    kk: ['Instagram растауы', 'Байланысу керек', 'Instagram расталмаған', 'Telegram-да жазу', 'Telegram байланысы жоқ', 'Хабарластым', 'Ертең еске салу', 'Кейін хабарласу:', 'Бұл топта әзірге ешкім жоқ.', 'Еске салу сақталмады. Қайта көріңіз.'],
    be: ['Пацвярджэнне Instagram', 'Трэба звязацца', 'Instagram не пацверджаны', 'Напісаць у Telegram', 'Няма кантакту ў Telegram', 'Напісаў', 'Нагадаць заўтра', 'Звязацца пасля', 'У гэтай групе пакуль нікога няма.', 'Не ўдалося захаваць напамін. Паспрабуйце яшчэ раз.'],
    uz: ['Instagram tasdig‘i', 'Bog‘lanish kerak', 'Instagram tasdiqlanmagan', 'Telegramda yozish', 'Telegram kontakti yo‘q', 'Yozdim', 'Ertaga eslatish', 'Bog‘lanish vaqti:', 'Bu guruhda hali hech kim yo‘q.', 'Eslatma saqlanmadi. Qayta urinib ko‘ring.']
  };
  var queueKeys = ['filter', 'due', 'notVerified',
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
  prepareLayout();
  var toolbar = byId('invited-directory-toolbar');
  var searchInput = byId('invited-search');
  var botFilter = byId('invited-bot-filter');
  var instagramSelect = byId('invited-instagram-filter');
  var followups = byId('invited-followups');
  var referral = byId('invited-referral');
  var reset = byId('invited-reset');
  var instagramFilter = 'all';
  function words() { return copy[(window._me || {}).locale] || copy.ru; }
  function setText(id, text) { byId(id).textContent = text; }

  function prepareLayout() {
    // A rolling release can serve the template and this module from different replicas.
    byId(listScreen).classList.add('umc-directory');
    byId(cardScreen).classList.add('umc-directory');
    byId('invited-creator-details').classList.add('umc-directory-card');

    var form = byId('invited-search-form');
    var filters = element('div', '', 'umc-directory-toolbar');
    filters.id = 'invited-directory-toolbar';
    filters.innerHTML = `
      <select id="invited-instagram-filter" hidden>
        <option value="all"></option>
        <option value="verified"></option>
        <option value="unverified"></option>
      </select>
      <div class="umc-directory-filters">
        <button type="button" class="btn btn-secondary" id="invited-followups" aria-pressed="false" hidden></button>
      </div>`;
    form.before(filters);
    filters.prepend(form);
    filters.querySelector('.umc-directory-filters').prepend(byId('invited-bot-filter').closest('label'));

    var status = byId('invited-creators-status');
    var message = element('div', '', 'umc-directory-message');
    message.innerHTML = `
      <button type="button" class="btn" id="invited-referral" hidden></button>
      <button type="button" class="btn btn-secondary" id="invited-reset" hidden></button>`;
    status.before(message);
    message.prepend(status);
    var notice = element('p', '', 'success umc-directory-detail');
    notice.id = 'invited-followup-notice';
    notice.setAttribute('role', 'status');
    message.after(notice);
  }

  function localize() {
    var lang = words();
    setText('btn-invited-creators', lang.title);
    setText('invited-creators-title', lang.title);
    setText('invited-search-label', lang.search);
    setText('invited-bot-label', lang.blocked);
    instagramSelect.setAttribute('aria-label', lang.filter);
    instagramSelect.options[0].textContent = lang.all;
    instagramSelect.options[1].textContent = lang.verified;
    instagramSelect.options[2].textContent = lang.notVerified;
    referral.textContent = lang.referral;
    reset.textContent = lang.reset;
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
    setText('invited-followup-notice', '');
    setText('invited-creator-title', words().card);
    setText('invited-creator-status', '');
    setText('invited-creators-status', '');
    byId('invited-prev').hidden = true;
    byId('invited-next').hidden = true;
    followups.hidden = true;
    instagramSelect.hidden = true;
  }

  function showContact(parent, creator, lang) {
    if (/^https:\/\/t\.me\/[A-Za-z0-9_]{5,32}$/.test(creator.telegram_url || '')) {
      var link = element('a', lang.write, 'btn umc-directory-contact');
      link.href = creator.telegram_url;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      parent.appendChild(link);
    } else if (creator.telegram_url === null) {
      parent.appendChild(element('p', lang.noContact, 'umc-directory-detail'));
    }
  }

  function showStatuses(parent, creator, lang) {
    var statuses = element('div', '', 'umc-directory-statuses');
    if (typeof creator.instagram_verified === 'boolean') {
      var status = element('span', creator.instagram_verified ? lang.verified : lang.notVerified);
      if (creator.instagram_verified) status.className = 'umc-directory-verified';
      statuses.appendChild(status);
    }
    if (creator.status === 'bot_blocked') statuses.appendChild(element('span', lang.blocked));
    if (statuses.childElementCount) parent.appendChild(statuses);
  }

  function scheduledText(value, lang) {
    var date = new Intl.DateTimeFormat((window._me || {}).locale || 'ru', {
      dateStyle: 'medium', timeStyle: 'short'
    }).format(new Date(value));
    return lang.scheduled + ' ' + date;
  }

  function showFollowupActions(parent, creator, lang, version, screen) {
    if (creator.instagram_verified !== false) return;
    var followup = element('div', '', 'umc-directory-followup');
    var schedule = element('p', '', 'umc-directory-detail');
    schedule.setAttribute('aria-live', 'polite');
    if (creator.remind_at && !creator.followup_due) {
      schedule.textContent = scheduledText(creator.remind_at, lang);
    } else if (creator.followup_due) {
      schedule.textContent = lang.due;
    }
    var actions = element('div', '', 'umc-directory-actions');
    var feedback = element('p', '', 'umc-directory-detail error');
    feedback.setAttribute('role', 'alert');
    function disableActions(disabled) {
      actions.querySelectorAll('button').forEach(function (control) {
        control.disabled = disabled;
      });
    }
    ['contacted', 'tomorrow'].forEach(function (action) {
      var button = element('button', lang[action], 'btn btn-secondary');
      button.type = 'button';
      button.addEventListener('click', function () {
        if (!activeRequest(version, screen)) return;
        var saveContext = context;
        disableActions(true);
        feedback.textContent = '';
        saveContext.request(path + '/' + encodeURIComponent(creator.creator_id) + '/followup', {
          action: action
        }).then(function (result) {
          if (context !== saveContext || !saveContext.isCurrent()) return;
          if (screen === cardScreen && activeRequest(version, cardScreen)) {
            schedule.textContent = scheduledText(result.remind_at, lang);
            disableActions(false);
            return;
          }
          // The manager may have returned to the list before the save completed.
          if (!byId(listScreen).classList.contains('active')) return;
          if (instagramFilter === 'due') {
            page = 0;
            showList(scheduledText(result.remind_at, lang));
          } else {
            showList();
          }
        }).catch(function (error) {
          if (error.status === 404 && context === saveContext && saveContext.isCurrent()) {
            if (screen === cardScreen && activeRequest(version, cardScreen)) showCard(creator.creator_id);
            else if (byId(listScreen).classList.contains('active')) showList();
            return;
          }
          if (!activeRequest(version, screen)) return;
          feedback.textContent = lang.saveError;
          disableActions(false);
        });
      });
      actions.appendChild(button);
    });
    followup.append(schedule, actions, feedback);
    parent.appendChild(followup);
  }

  function selectInstagram(filter) {
    instagramFilter = filter;
    instagramSelect.value = filter === 'due' ? 'all' : filter;
    followups.setAttribute('aria-pressed', String(filter === 'due'));
  }

  function resetFilters() {
    page = 0;
    searchInput.value = '';
    botFilter.checked = false;
    selectInstagram('all');
  }

  function showList(notice) {
    clearTimeout(searchTimer);
    var lang = words();
    var version = ++requestVersion;
    var list = byId('invited-creators-list');
    var filtered = botFilter.checked;
    var query = searchInput.value.trim();
    var instagram = instagramFilter;
    list.replaceChildren();
    byId('invited-prev').hidden = true;
    byId('invited-next').hidden = true;
    toolbar.hidden = false;
    referral.hidden = reset.hidden = true;
    setText('invited-followup-notice', notice || '');
    setText('invited-creators-status', lang.loading);
    if (!byId(listScreen).classList.contains('active')) window.__umcAppBridge.showScreen(listScreen);
    var params = { bot_unavailable: filtered, page: page };
    if (query) params.q = query;
    if (instagram !== 'all') params.instagram = instagram;
    context.request(path, params).then(function (data) {
      if (!activeRequest(version, listScreen)) return;
      followups.hidden = !Number.isInteger(data.followup_count);
      instagramSelect.hidden = followups.hidden;
      if (!followups.hidden) followups.textContent = lang.due + ': ' + data.followup_count;
      var hasFilters = Boolean(query || instagram !== 'all' || filtered);
      var noResults = !data.creators.length;
      var emptyDirectory = noResults && !hasFilters && page === 0;
      toolbar.hidden = emptyDirectory;
      referral.hidden = !emptyDirectory;
      reset.hidden = !noResults || !hasFilters;
      var emptyMessage = lang.emptyFilter;
      if (query) emptyMessage = lang.noMatches;
      else if (emptyDirectory) emptyMessage = lang.empty;
      else if (filtered && instagram === 'all') emptyMessage = lang.emptyBlocked;
      setText('invited-creators-status', noResults ? emptyMessage : '');
      data.creators.forEach(function (creator) {
        var button = element('button', creator.name || lang.card, 'umc-directory-name');
        button.type = 'button';
        button.addEventListener('click', function () { showCard(creator.creator_id); });
        var row = element('li', '', 'umc-directory-card');
        row.appendChild(button);
        if (creator.city) row.appendChild(element('p', creator.city, 'umc-directory-city'));
        showStatuses(row, creator, lang);
        showContact(row, creator, lang);
        showFollowupActions(row, creator, lang, version, listScreen);
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
      setText('invited-creator-status', '');
      if (creator.city) details.appendChild(element('p', creator.city, 'umc-directory-city'));
      showStatuses(details, creator, lang);
      showContact(details, creator, lang);
      showFollowupActions(details, creator, lang, version, cardScreen);
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
    resetFilters();
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
  botFilter.addEventListener('change', function () {
    if (!context) return;
    page = 0;
    showList();
  });
  instagramSelect.addEventListener('change', function () {
    if (!context) return;
    selectInstagram(instagramSelect.value);
    page = 0;
    showList();
  });
  followups.addEventListener('click', function () {
    if (!context) return;
    selectInstagram(instagramFilter === 'due' ? 'all' : 'due');
    page = 0;
    showList();
  });
  reset.addEventListener('click', function () {
    if (!context) return;
    resetFilters();
    showList();
    searchInput.focus();
  });
  referral.addEventListener('click', function () {
    var dashboard = byId('screen-manager-orders');
    window.__umcAppBridge.showScreen(dashboard.id);
    var partner = dashboard.querySelector('[data-partner-home]');
    if (!partner) return;
    // Let the shell reset scroll and focus for the dashboard first.
    requestAnimationFrame(function () {
      requestAnimationFrame(function () {
        if (!dashboard.classList.contains('active')) return;
        partner.tabIndex = -1;
        partner.focus();
        partner.scrollIntoView({ block: 'start' });
      });
    });
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
