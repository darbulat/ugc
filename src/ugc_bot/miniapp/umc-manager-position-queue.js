(function () {
  'use strict';

  const panel = document.getElementById('mgr-position-queue');
  const toggle = document.getElementById('mgr-queue-toggle');
  if (!panel || !toggle) return;

  const filters = [...panel.querySelectorAll('[data-stage]')];
  const status = document.getElementById('mgr-queue-status');
  const positions = document.getElementById('mgr-queue-positions');
  let orderId;
  let context;
  let requestNumber = 0;
  let stage = 'all';

  function close() {
    requestNumber += 1;
    if (context) context.dispose();
    context = null;
    panel.hidden = true;
    toggle.setAttribute('aria-expanded', 'false');
    positions.replaceChildren();
    status.textContent = '';
  }

  async function load() {
    if (!context || !orderId) return;
    const current = context;
    const attempt = ++requestNumber;
    const isCurrent = () => attempt === requestNumber && current.isCurrent();
    filters.forEach(button => {
      button.setAttribute('aria-pressed', String(button.dataset.stage === stage));
    });
    positions.replaceChildren();
    status.textContent = 'Загружаем позиции…';
    try {
      const result = await current.request('/manager/orders/' + orderId + '/position-queue', {stage});
      if (!isCurrent()) return;
      for (const position of result.positions) {
        const row = document.createElement('li');
        row.textContent = '№' + position.ordinal + ' · ' + position.label
          + (position.needs_review ? ' · Требует проверки' : '');
        positions.appendChild(row);
      }
      status.textContent = !result.positions.length ? 'По этому фильтру позиций нет.'
        : result.positions.some(position => position.preview)
          ? 'Тестовый заказ. «Контакт получен» означает, что он появился в тестовой карточке.'
          : '';
    } catch (_) {
      if (isCurrent()) status.textContent = 'Не удалось открыть очередь. Попробуйте обновить.';
    }
  }

  document.addEventListener('umc:manager-order-opened', event => {
    close();
    orderId = event.detail.orderId;
    stage = 'all';
  });
  document.addEventListener('umc:screen-change', event => {
    if (event.detail.screen !== 'screen-manager-order-detail') close();
  });
  toggle.addEventListener('click', () => {
    if (!panel.hidden) { close(); return; }
    if (!orderId || !window.__umcAppBridge) return;
    context = window.__umcAppBridge.createRequestContext();
    toggle.setAttribute('aria-expanded', 'true');
    panel.hidden = false;
    load();
  });
  filters.forEach(button => button.addEventListener('click', () => {
    stage = button.dataset.stage;
    load();
  }));
  document.getElementById('mgr-queue-refresh').addEventListener('click', load);
})();
