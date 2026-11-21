(() => {
  const panel = document.getElementById('order-offer-activity');
  const status = document.getElementById('order-offer-refresh-status');
  if (!panel || !status) return;
  const interval = 20_000;
  let previousHtml;
  let sending = false;

  function setStatus(message) {
    if (status.textContent !== message) status.textContent = message;
  }

  function filterRows(key) {
    const workspace = panel.querySelector('[data-creator-workspace]');
    if (!workspace) return;
    const selected = key || workspace.querySelector('[aria-pressed="true"]')?.dataset.creatorFilter || 'all';
    const query = (workspace.querySelector('[data-creator-search]')?.value || '').trim().toLocaleLowerCase('ru');
    workspace.querySelectorAll('[data-creator-filter]').forEach(button => {
      button.setAttribute('aria-pressed', String(button.dataset.creatorFilter === selected));
      button.hidden = button.dataset.creatorFilter !== 'all' && button.dataset.creatorFilter !== selected && Number(button.dataset.creatorFilterCount) === 0;
    });
    let visible = 0;
    workspace.querySelectorAll('[data-creator-row]').forEach(row => {
      row.hidden = (selected !== 'all' && row.dataset.creatorGroup !== selected) ||
        !row.dataset.creatorSearchText.toLocaleLowerCase('ru').includes(query);
      if (!row.hidden) visible += 1;
    });
    workspace.querySelector('[data-creator-empty]').hidden = visible > 0;
  }

  function updateCounter() {
    const source = panel.querySelector('[data-transferred-count]');
    const counter = document.getElementById('order-transferred-counter');
    if (!counter) return;
    if (!source) { counter.hidden = true; return; }
    const count = Number(source.dataset.transferredCount);
    const needed = Number(source.dataset.transferNeeded);
    if (!Number.isFinite(count) || !Number.isFinite(needed)) return;
    const value = document.getElementById('order-transferred-value');
    const extra = document.getElementById('order-transferred-extra');
    const manual = document.getElementById('order-transferred-manual');
    const manualCount = Number(source.dataset.manualTransferredCount || 0);
    const over = Math.max(count - needed, 0);
    if (value.textContent !== String(count)) value.textContent = count;
    value.classList.toggle('order-detail__transfer-over', over > 0);
    extra.hidden = over === 0;
    extra.textContent = over ? `+${over} сверх плана` : '';
    if (manual) {
      manual.hidden = !Number.isFinite(manualCount) || manualCount <= 0;
      manual.textContent = manual.hidden ? '' : `${manualCount} вручную`;
    }
    counter.hidden = false;
  }

  async function refresh() {
    if (sending || (document.hidden && previousHtml !== undefined)) {
      window.setTimeout(refresh, interval);
      return;
    }
    try {
      const response = await fetch(panel.dataset.url, {cache: 'no-store', credentials: 'same-origin'});
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
        const filter = panel.querySelector('[data-creator-filter][aria-pressed="true"]')?.dataset.creatorFilter;
        const search = panel.querySelector('[data-creator-search]');
        const query = search?.value || '';
        const focusedSearch = search && document.activeElement === search;
        const selection = focusedSearch ? [search.selectionStart, search.selectionEnd] : null;
        const expanded = new Set(Array.from(panel.querySelectorAll('[data-creator-detail][open]'), item => item.dataset.creatorDetail));
        const scroller = panel.querySelector('.order-creators__scroll');
        const scrollPosition = [scroller?.scrollTop || 0, scroller?.scrollLeft || 0];
        panel.innerHTML = html;
        previousHtml = html;
        const nextSearch = panel.querySelector('[data-creator-search]');
        if (nextSearch) nextSearch.value = query;
        panel.querySelectorAll('[data-creator-detail]').forEach(item => { item.open = expanded.has(item.dataset.creatorDetail); });
        filterRows(filter);
        updateCounter();
        const nextScroller = panel.querySelector('.order-creators__scroll');
        if (nextScroller) [nextScroller.scrollTop, nextScroller.scrollLeft] = scrollPosition;
        if (focusedSearch && nextSearch) {
          nextSearch.focus({preventScroll: true});
          // Search inputs do not support selection ranges in all browsers.
          try { nextSearch.setSelectionRange(...selection); } catch {}
        }
      }
      setStatus('Обновляется автоматически');
    } catch {
      setStatus('Не удалось обновить данные. Повторим попытку.');
    } finally {
      panel.setAttribute('aria-busy', 'false');
    }
    window.setTimeout(refresh, interval);
  }

  panel.addEventListener('click', event => {
    const button = event.target.closest('[data-creator-filter]');
    if (button) filterRows(button.dataset.creatorFilter);
  });
  panel.addEventListener('input', event => {
    if (event.target.matches('[data-creator-search]')) filterRows();
  });
  panel.addEventListener('submit', event => {
    if (!event.target.matches('[data-creator-transfer-form]')) return;
    const button = event.target.querySelector('button');
    if (button.disabled) { event.preventDefault(); return; }
    sending = true;
    button.disabled = true;
    button.textContent = 'Отправляем…';
  });
  refresh();
})();
