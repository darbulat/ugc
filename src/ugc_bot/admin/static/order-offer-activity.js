(() => {
  const panel = document.getElementById('order-offer-activity');
  const status = document.getElementById('order-offer-refresh-status');
  if (!panel || !status) return;

  const interval = 20_000;
  let previousHtml;

  function setStatus(message) {
    if (status.textContent !== message) status.textContent = message;
  }

  async function refresh() {
    if (document.hidden && previousHtml !== undefined) {
      window.setTimeout(refresh, interval);
      return;
    }
    try {
      const response = await fetch(panel.dataset.url, {
        cache: 'no-store',
        credentials: 'same-origin',
      });
      if (response.status === 401) {
        setStatus('Войдите в админку заново, чтобы обновить данные.');
        return;
      }
      if (response.status === 404) {
        setStatus('Заказ больше недоступен.');
        return;
      }
      if (!response.ok) throw new Error('Offer activity request failed');

      const html = await response.text();
      if (html !== previousHtml) {
        const wasOpen = panel.querySelector('[data-order-declines]')?.open;
        const active = document.activeElement;
        const focusedId = panel.contains(active) ? active.id : null;
        panel.innerHTML = html;
        previousHtml = html;
        const sent = panel.querySelector('[data-transferred-count]');
        const counter = document.getElementById('order-transferred-counter');
        if (sent && counter) counter.textContent = 'Передано заказчице: ' + sent.querySelector('.creator-transfer-count').textContent;
        const declines = panel.querySelector('[data-order-declines]');
        if (declines && wasOpen !== undefined) declines.open = wasOpen;
        if (focusedId) document.getElementById(focusedId)?.focus({preventScroll: true});
      }

      setStatus('Обновляется автоматически');
    } catch {
      setStatus('Не удалось обновить данные. Повторим попытку.');
    }
    window.setTimeout(refresh, interval);
  }

  panel.addEventListener('submit', (event) => {
    if (!event.target.matches('[data-creator-transfer-form]')) return;
    const button = event.target.querySelector('button');
    if (button.disabled) { event.preventDefault(); return; }
    button.disabled = true;
    button.textContent = 'Отправляем…';
  });
  refresh();
})();
