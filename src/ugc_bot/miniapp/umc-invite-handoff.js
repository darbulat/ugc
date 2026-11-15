(function () {
  'use strict';

  let panel;
  let context;
  let revision = 0;

  function button(label, action) {
    const element = document.createElement('button');
    element.type = 'button';
    element.className = 'btn btn-secondary';
    element.textContent = label;
    element.addEventListener('click', action);
    return element;
  }

  function clear() {
    revision += 1;
    if (context) context.dispose();
    context = null;
    if (panel) panel.remove();
    panel = null;
  }

  async function render(event) {
    clear();
    if ((window.__miniapp_platform || 'telegram') !== 'telegram') return;
    const order = event.detail && event.detail.order_id;
    const parent = document.getElementById('selection-positions');
    if (!order || !parent || !window.__umcAppBridge) return;
    const guard = revision;
    context = window.__umcAppBridge.createRequestContext();
    const requestContext = context;
    const path = '/financial/orders/' + order + '/invite-handoff';
    const current = () => revision === guard && requestContext.isCurrent();
    const request = (action, invitation) => requestContext.request(path, {action, invitation});
    let data;
    try {
      data = await request('view');
    } catch (_) {
      return;
    }
    if (!current()) return;
    panel = document.createElement('section');
    panel.className = 'umc-selection-position';
    parent.before(panel);
    const message = document.createElement('p');
    message.setAttribute('role', 'status');
    const share = button('', async () => {
      share.disabled = true;
      try {
        const changed = await request(data.enabled ? 'hide' : 'share');
        if (current()) {
          data = changed;
          updateShare();
        }
      } catch (_) {
        if (current()) message.textContent = 'Не удалось сохранить настройку.';
      } finally {
        share.disabled = false;
      }
    });

    function updateShare() {
      share.textContent = data.enabled ? 'Скрыть мой Telegram' : 'Разрешить передачу моего Telegram';
      message.textContent = data.enabled
        ? 'Подтвердившие участие креаторы увидят ' + data.telegram + '.'
        : data.telegram ? 'Ваш Telegram скрыт.' : 'Добавьте @username в Telegram, чтобы открыть контакт креаторам.';
    }

    share.hidden = !data.telegram;
    const open = document.createElement('a');
    open.className = 'btn btn-secondary';
    open.textContent = 'Итоги заказа в Telegram';
    open.href = data.open_url;
    open.rel = 'noopener noreferrer';
    panel.append(share, message, open);
    updateShare();
    for (const item of data.staff || []) {
      const row = document.createElement('div');
      const contact = document.createElement('p');
      contact.style.whiteSpace = 'pre-line';
      const confirmed = document.createElement('p');
      confirmed.textContent = item.accepted_at ? 'Получение подтверждено' : '';
      const ack = button('Подтвердить получение контакта', async () => {
        ack.disabled = true;
        try {
          await request('ack', item.id);
          if (current()) {
            item.accepted_at = true;
            ack.hidden = true;
            confirmed.textContent = 'Получение подтверждено';
          }
        } catch (_) {
          if (current()) {
            ack.disabled = false;
            message.textContent = 'Не удалось подтвердить получение.';
          }
        }
      });
      ack.hidden = true;
      const show = button('Контакт №' + item.ordinal, async () => {
        try {
          const result = await request('open', item.id);
          if (current()) {
            contact.textContent = result.contact;
            ack.hidden = Boolean(item.accepted_at);
          }
        } catch (_) {
          if (current()) contact.textContent = 'Контакт сейчас недоступен.';
        }
      });
      row.append(show, contact, ack, confirmed);
      panel.appendChild(row);
    }
  }

  document.addEventListener('umc:selection-view', render);
  document.addEventListener('umc:screen-change', (event) => {
    if (!event.detail || event.detail.screen !== 'screen-selection') clear();
  });
  document.addEventListener('umc:app-ready', clear);
})();
