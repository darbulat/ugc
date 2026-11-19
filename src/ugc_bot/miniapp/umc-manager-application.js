(function () {
  'use strict';
  var bridge = window.__umcAppBridge;
  var entry = document.getElementById('link-manager-application');
  if (!bridge || !entry) return;
  var screen = document.createElement('section');
  screen.id = 'screen-manager-application';
  screen.className = 'screen';
  screen.dataset.umcSection = 'lilac';
  var heading = element('h1', 'Анкета менеджера');
  var content = element('div');
  var status = element('p', '', 'error');
  status.setAttribute('role', 'alert');
  var back = button('К выбору роли', function () {
    bridge.showScreen('screen-role-choice');
  }, 'btn btn-secondary');
  back.dataset.umcBack = '';
  screen.append(heading, content, status, back);
  document.getElementById('umc-app').appendChild(screen);
  var context = null;
  var version = 0;
  var data = null;
  var busy = false;
  var path = '/manager/application';

  function element(tag, text, className) {
    var node = document.createElement(tag);
    if (text) node.textContent = text;
    if (className) node.className = className;
    return node;
  }
  function button(text, action, className) {
    var node = element('button', text, className || 'btn');
    node.type = 'button';
    node.addEventListener('click', action);
    return node;
  }
  function sync() {
    screen.setAttribute('aria-busy', String(busy));
    content.querySelectorAll('button, input, textarea, select').forEach(function (control) {
      control.disabled = busy;
    });
    if (window.UMCShell) window.UMCShell.syncControls();
  }
  function clear() {
    if (context) context.dispose();
    context = null;
    version++;
    data = null;
    busy = false;
    content.replaceChildren();
    status.textContent = '';
    sync();
  }
  function current(requestVersion) {
    if (requestVersion !== version || !context) return false;
    if (context.isCurrent()) return true;
    clear();
    status.textContent = 'Сессия изменилась. Откройте анкету заново.';
    return false;
  }
  function request(endpoint, body, done) {
    if (busy || !context || !current(version)) return;
    var requestVersion = version;
    busy = true;
    status.textContent = '';
    sync();
    context.request(path + endpoint, body || {}).then(function (result) {
      if (current(requestVersion)) done(result);
    }).catch(function (error) {
      if (!current(requestVersion)) return;
      if (error.status === 401 || error.status === 403) {
        clear();
        status.textContent = 'Откройте мини-приложение заново.';
      } else {
        status.textContent = error.status === 422 ? error.message : 'Не удалось сохранить ответ. Попробуйте ещё раз.';
      }
    }).finally(function () {
      if (requestVersion !== version) return;
      busy = false;
      sync();
    });
  }
  function received(result) {
    data = result;
    render();
  }
  function render(selected) {
    content.replaceChildren();
    window.scrollTo(0, 0);
    var editable = ['draft', 'clarify', 'declined'].indexOf(data.state) >= 0;
    if (!editable) {
      content.appendChild(element('h2', data.state === 'approved' ? 'Заявка одобрена' : 'Заявка получена'));
      content.appendChild(element('p', data.state === 'approved' ? 'Вам доступен кабинет менеджера.' : 'Ответы сохранены. Мы рассмотрим вашу заявку.', 'hint'));
      if (data.state === 'approved') {
        window._me.is_manager = true;
        document.getElementById('btn-manager-role').style.display = '';
        entry.style.display = 'none';
      }
      verification();
      content.appendChild(button('Проверить статус', function () { request('/view', {}, received); }, 'btn btn-secondary'));
      sync();
      return;
    }
    var field = data.fields.find(function (item) { return item.name === (selected || data.next_field); }) || data.fields[0];
    if (!field) return;
    var index = data.fields.indexOf(field);
    var progress = element('p', 'Вопрос ' + (index + 1) + ' из ' + data.fields.length + '. Ответы сохраняются автоматически.', 'manager-progress');
    content.appendChild(progress);
    if (index === 0) content.appendChild(element('p', data.intro, 'hint'));
    if (data.state === 'clarify' || data.state === 'declined') {
      content.appendChild(element('p', 'Обновите ответы и отправьте заявку повторно.', 'hint'));
    }
    var form = element('form');
    form.id = 'form-manager-application';
    var label = element('label', field.prompt, 'manager-question');
    label.htmlFor = 'manager-answer';
    form.appendChild(label);
    var input;
    if (field.choices.length) {
      input = element('select');
      var placeholder = element('option', 'Выберите вариант');
      placeholder.value = '';
      input.appendChild(placeholder);
      field.choices.forEach(function (choice) {
        var option = element('option', choice);
        option.value = choice;
        input.appendChild(option);
      });
    } else {
      input = element(['case', 'shortfall_plan'].indexOf(field.name) >= 0 ? 'textarea' : 'input');
      input.maxLength = field.max_length;
      input.minLength = field.min_length;
      if (input.tagName === 'TEXTAREA') input.rows = 6;
      if (field.name === 'phone') {
        input.type = 'tel';
        input.autocomplete = 'tel';
        input.pattern = '\\+?[0-9]{7,15}';
        input.placeholder = '+79991234567';
      }
      if (field.name === 'instagram') {
        input.autocapitalize = 'none';
        input.spellcheck = false;
      }
    }
    input.id = 'manager-answer';
    input.name = field.name;
    input.required = true;
    input.value = data.answers[field.name] || '';
    form.appendChild(input);
    var city = element('div');
    form.appendChild(city);
    var submit = element('button', field.name === 'location' ? 'Найти город' : index === data.fields.length - 1 ? 'Отправить заявку' : 'Сохранить и продолжить', 'btn');
    submit.type = 'submit';
    submit.dataset.umcPrimary = '20';
    form.appendChild(submit);
    form.addEventListener('submit', function (event) {
      event.preventDefault();
      if (field.name !== 'location') {
        request('/answer', { field: field.name, value: input.value }, received);
        return;
      }
      var query = input.value;
      city.replaceChildren();
      request('/city', { value: query }, function (location) {
        if (input.value !== query) return;
        city.appendChild(element('p', [location.city, location.region, location.country].filter(Boolean).join(', ')));
        city.appendChild(button('Да, выбрать город', function () {
          if (input.value === query) request('/answer', { field: 'location', value: query }, received);
        }));
      });
    });
    input.addEventListener('input', function () { city.replaceChildren(); });
    content.appendChild(form);
    if (index > 0) content.appendChild(button('Предыдущий вопрос', function () { render(data.fields[index - 1].name); }, 'btn btn-secondary'));
    sync();
  }
  function verification() {
    if (data.instagram_verified) {
      content.appendChild(element('p', 'Instagram подтверждён.', 'hint'));
    } else if (data.instagram_code && data.instagram_direct_url) {
      content.appendChild(element('h2', 'Подтвердите Instagram'));
      content.appendChild(element('p', 'Отправьте этот код в Direct UMC с аккаунта, указанного в анкете. Код действует 24 часа.', 'hint'));
      var code = element('input', '', 'manager-code');
      code.id = 'manager-instagram-code';
      code.readOnly = true;
      code.value = data.instagram_code;
      code.setAttribute('aria-label', 'Код подтверждения Instagram');
      content.appendChild(code);
      var copyStatus = element('p', '', 'hint');
      copyStatus.setAttribute('role', 'status');
      content.appendChild(button('Скопировать код', function () {
        var requestVersion = version;
        var value = code.value;
        if (!current(requestVersion)) return;
        function manual() {
          if (!current(requestVersion)) return;
          code.select();
          copyStatus.textContent = 'Код выделен. Скопируйте его вручную.';
        }
        if (!navigator.clipboard) return manual();
        navigator.clipboard.writeText(value).then(function () {
          if (current(requestVersion)) copyStatus.textContent = 'Код скопирован.';
        }).catch(manual);
      }, 'btn btn-secondary'));
      content.appendChild(copyStatus);
      var direct = element('a', 'Открыть Direct', 'btn');
      direct.href = data.instagram_direct_url;
      direct.target = '_blank';
      direct.rel = 'noopener noreferrer';
      content.appendChild(direct);
    } else if (!data.instagram_verified && data.state !== 'approved') {
      content.appendChild(element('p', 'Проверка Instagram временно недоступна. Ответы сохранены; проверьте статус позже.', 'hint'));
    }
  }
  entry.addEventListener('click', function () {
    clear();
    bridge.showScreen(screen.id);
    context = bridge.createRequestContext();
    content.appendChild(element('p', 'Загружаем анкету…', 'hint'));
    request('/view', {}, received);
  });
  document.addEventListener('umc:screen-change', function (event) {
    if (event.detail.screen !== screen.id) clear();
  });
  document.addEventListener('umc:app-ready', clear);
  document.addEventListener('visibilitychange', function () { if (context) current(version); });
  window.addEventListener('focus', function () { if (context) current(version); });
})();
