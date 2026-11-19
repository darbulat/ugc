(() => {
  'use strict';
  const form = document.getElementById('invite-creator-form');
  const receipt = document.getElementById('invite-result');
  if (receipt) receipt.focus({preventScroll: true});
  const copy = document.getElementById('copy-invite-link');
  copy?.addEventListener('click', async () => {
    const link = document.getElementById('invite-link');
    const status = document.getElementById('invite-copy-status');
    try { await navigator.clipboard.writeText(link.value); status.textContent = 'Ссылка скопирована'; }
    catch { link.focus(); link.select(); status.textContent = 'Скопируйте выделенную ссылку'; }
  });
  if (!form) return;

  function highlight(node, value, query) {
    const words = query.trim().replace(/@/g, '').split(/\s+/).filter(Boolean);
    const lower = value.toLocaleLowerCase();
    let start = 0;
    while (start < value.length) {
      let found = -1, length = 0;
      for (const word of words) {
        const index = lower.indexOf(word.toLocaleLowerCase(), start);
        if (index !== -1 && (found === -1 || index < found)) { found = index; length = word.length; }
      }
      if (found === -1) { node.append(document.createTextNode(value.slice(start))); break; }
      node.append(document.createTextNode(value.slice(start, found)));
      const mark = document.createElement('mark'); mark.textContent = value.slice(found, found + length); node.append(mark);
      start = found + length;
    }
  }

  class PeoplePicker {
    constructor(root, onSelect) {
      this.root = root;
      this.kind = root.dataset.personPicker;
      this.input = root.querySelector('[role="combobox"]');
      this.hidden = root.querySelector('input[type="hidden"]');
      this.clear = root.querySelector('.invite-clear');
      this.popup = root.querySelector('.invite-popup');
      this.list = root.querySelector('[role="listbox"]');
      this.status = root.querySelector('.invite-search-status');
      this.detail = root.querySelector('[data-person-detail]');
      this.hint = root.dataset.emptyHint || '';
      this.manual = root.querySelector('.invite-manual');
      this.onSelect = onSelect;
      this.active = -1; this.rows = []; this.version = 0;
      this.input.addEventListener('input', () => {
        if (this.hidden) this.hidden.value = '';
        this.detail && (this.detail.textContent = this.hint);
        this.onSelect?.(null);
        this.clear.hidden = !this.input.value;
        this.schedule();
      });
      this.input.addEventListener('focus', () => {
        if (!this.hidden?.value && !this.input.readOnly && this.input.value.trim().length >= 2) this.schedule();
      });
      this.input.addEventListener('keydown', event => this.keydown(event));
      this.clear.addEventListener('click', () => { this.select(null); this.input.focus(); });
      this.manual?.addEventListener('click', () => {
        const value = this.input.value.trim();
        if (/^@?[\w.]{1,30}$/.test(value) || /^(https:\/\/)?(www\.)?instagram\.com\//i.test(value)) {
          document.getElementById('invite-instagram').value = value;
          document.getElementById('invite-instagram').dispatchEvent(new Event('input'));
        }
        this.close(); document.getElementById('invite-instagram').focus();
      });
      document.addEventListener('pointerdown', event => { if (!root.contains(event.target)) this.close(); });
      root.addEventListener('focusout', event => { if (!root.contains(event.relatedTarget)) this.close(); });
    }
    close() {
      this.version++; clearTimeout(this.timer); this.abort?.abort();
      this.popup.hidden = true; this.input.setAttribute('aria-expanded', 'false');
      this.input.removeAttribute('aria-activedescendant'); this.active = -1;
    }
    schedule() {
      this.close();
      const query = this.input.value.trim();
      if (query.length < 2 || this.input.readOnly) return;
      this.popup.hidden = false; this.input.setAttribute('aria-expanded', 'true');
      this.list.replaceChildren(); this.rows = [];
      this.status.textContent = 'Ищем…'; if (this.manual) this.manual.hidden = true;
      const version = this.version;
      this.timer = setTimeout(() => this.search(query, version), 180);
    }
    async search(query, version) {
      this.abort = new AbortController();
      const url = new URL(form.dataset.searchUrl);
      url.searchParams.set('kind', this.kind); url.searchParams.set('q', query);
      try {
        const response = await fetch(url, {signal: this.abort.signal, credentials: 'same-origin', headers: {'Accept': 'application/json'}});
        if (!response.ok) throw new Error('search');
        const data = await response.json();
        if (version !== this.version || query !== this.input.value.trim()) return;
        this.rows = data.results; this.list.replaceChildren(); this.active = -1;
        this.rows.forEach((person, index) => {
          const option = document.createElement('div');
          option.id = `${this.list.id}-${index}`; option.className = 'invite-search-option';
          option.setAttribute('role', 'option'); option.setAttribute('aria-selected', 'false');
          const avatar = document.createElement('span'); avatar.className = 'invite-avatar'; avatar.setAttribute('aria-hidden', 'true');
          avatar.textContent = person.name.replace(/^@/, '').split(/\s+/).slice(0, 2).map(word => word[0]).join('').toLocaleUpperCase();
          const text = document.createElement('span'); text.className = 'invite-option-copy';
          const name = document.createElement('span'); name.className = 'invite-option-name'; highlight(name, person.name, query);
          const detail = document.createElement('span'); detail.className = 'invite-option-detail'; highlight(detail, person.detail, query);
          text.append(name, detail); option.append(avatar, text);
          option.addEventListener('mousedown', event => event.preventDefault());
          option.addEventListener('click', () => this.select(person));
          this.list.append(option);
        });
        this.status.textContent = data.more ? 'Показаны первые 8. Уточните имя или ник.' : this.rows.length ? '' : 'Никого не нашли. Попробуйте другое имя или ник.';
        if (this.manual) this.manual.hidden = this.rows.length > 0;
      } catch (error) {
        if (error.name === 'AbortError' || version !== this.version) return;
        this.status.textContent = 'Поиск недоступен. Попробуйте ещё раз.';
        if (this.manual) this.manual.hidden = false;
      }
    }
    keydown(event) {
      if (event.key === 'Escape') { this.close(); return; }
      if (['ArrowDown', 'ArrowUp'].includes(event.key)) {
        event.preventDefault();
        if (this.popup.hidden) { this.schedule(); return; }
        if (!this.rows.length) return;
        this.active = this.active < 0 ? (event.key === 'ArrowDown' ? 0 : this.rows.length - 1) : (this.active + (event.key === 'ArrowDown' ? 1 : -1) + this.rows.length) % this.rows.length;
        [...this.list.children].forEach((option, index) => option.setAttribute('aria-selected', String(index === this.active)));
        const option = this.list.children[this.active];
        this.input.setAttribute('aria-activedescendant', option.id); option.scrollIntoView({block: 'nearest'});
      }
      if (event.key === 'Enter') {
        event.preventDefault();
        if (!this.popup.hidden && this.active >= 0) this.select(this.rows[this.active]);
      }
    }
    select(person, {locked = false, notify = true} = {}) {
      this.close();
      this.input.value = person?.name || '';
      if (this.hidden) this.hidden.value = person?.id || '';
      this.input.readOnly = locked; this.root.dataset.locked = String(locked);
      this.clear.hidden = !person || locked;
      if (this.detail) this.detail.textContent = person?.detail || this.hint;
      const label = this.root.querySelector('label');
      let badge = label.querySelector('.invite-lock');
      if (locked && !badge) { badge = document.createElement('span'); badge.className = 'invite-lock'; badge.textContent = 'Закреплён ранее'; label.append(badge); }
      if (!locked) badge?.remove();
      if (notify) this.onSelect?.(person);
    }
  }

  const instagram = document.getElementById('invite-instagram');
  const telegram = document.getElementById('invite-telegram');
  const consent = document.getElementById('invite-consent');
  const source = document.getElementById('invite-source');
  const customer = document.getElementById('invite-customer-action');
  const creator = document.getElementById('invite-creator-action');
  const profileStatus = document.getElementById('invite-profile-status');
  const labels = {
    ready: 'Профиль найден · бот доступен', external: 'Новый креатор · можно добавить по контактам',
    unverified: 'Анкета найдена · Instagram ещё не подтверждён', blocked: 'Профиль найден · бот заблокирован, контакт можно передать заказчику',
    unavailable: 'Профиль найден · приглашение доступно по ссылке'
  };
  let chosenReferrer = null;
  const referrerRoot = form.querySelector('[data-person-picker="referrer"]');
  const referrer = referrerRoot ? new PeoplePicker(referrerRoot, person => { chosenReferrer = person; }) : null;
  if (referrer && referrer.root.dataset.locked !== 'true' && referrer.hidden.value) {
    chosenReferrer = {id: referrer.hidden.value, name: referrer.input.value, detail: referrer.detail.textContent};
  }
  new PeoplePicker(form.querySelector('[data-person-picker="manager"]'));
  const creatorSearch = new PeoplePicker(form.querySelector('[data-person-picker="creator"]'), person => {
    if (!person) return;
    instagram.value = person.instagram ? `@${person.instagram}` : '';
    telegram.value = person.telegram ? `@${person.telegram}` : '';
    document.getElementById('invite-name').value = person.creator_name;
    identityChanged(true);
  });
  function updateConsent() {
    customer.disabled = !consent.checked;
    source.required = consent.checked;
    document.getElementById('invite-source-wrap').hidden = !consent.checked;
    creator.hidden = consent.checked || profileStatus.dataset.availability !== 'ready';
    document.getElementById('invite-action-hint').textContent = consent.checked ? 'Отправим имя, Instagram и Telegram креатора.' : 'Для отправки отметьте согласие креатора.';
  }
  const item = document.getElementById('invite-item');
  function updatePosition() {
    const ordinal = item.selectedOptions[0]?.dataset.ordinal;
    document.getElementById('invite-action-summary').textContent = ordinal ? `Карточка для заказчика · позиция №${ordinal}` : 'Карточка для заказчика';
  }
  updateConsent(); updatePosition();
  consent.addEventListener('change', updateConsent); item.addEventListener('change', updatePosition);
  let profileVersion = 0, profileAbort, profileTimer;
  function identityChanged(immediate = false) {
    clearTimeout(profileTimer); profileAbort?.abort(); profileVersion++;
    if (referrer?.root.dataset.locked === 'true') referrer.select(chosenReferrer, {notify: false});
    profileStatus.dataset.availability = ''; updateConsent();
    profileStatus.textContent = instagram.value.trim() ? 'Проверяем профиль…' : 'Новый автор? Просто заполните контакты выше.';
    if (instagram.value.trim()) profileTimer = setTimeout(checkProfile, immediate ? 0 : 350);
  }
  async function checkProfile() {
    clearTimeout(profileTimer); profileAbort?.abort(); profileAbort = new AbortController();
    const version = ++profileVersion;
    const url = new URL(form.dataset.profileUrl);
    url.searchParams.set('instagram', instagram.value); url.searchParams.set('telegram', telegram.value);
    try {
      const response = await fetch(url, {signal: profileAbort.signal, credentials: 'same-origin', headers: {'Accept': 'application/json'}});
      if (!response.ok) throw new Error('profile');
      const data = await response.json();
      if (version !== profileVersion) return;
      profileStatus.dataset.availability = data.availability; profileStatus.textContent = labels[data.availability];
      if (referrer) referrer.select(data.referrer || chosenReferrer, {locked: Boolean(data.referrer), notify: false});
      updateConsent();
    } catch (error) {
      if (error.name === 'AbortError' || version !== profileVersion) return;
      profileStatus.dataset.availability = 'error';
      profileStatus.textContent = 'Не удалось проверить профиль. Проверьте Instagram и Telegram и повторите.';
    }
  }
  instagram.addEventListener('input', () => identityChanged()); telegram.addEventListener('input', () => identityChanged());
  document.getElementById('invite-check-profile').addEventListener('click', event => { event.preventDefault(); identityChanged(true); });
  // Preserve native POST preview as a fallback when JavaScript is unavailable.
  let submitting = false;
  form.addEventListener('submit', event => {
    if (submitting) { event.preventDefault(); return; }
    if (!['send_customer', 'send'].includes(event.submitter?.value)) return;
    submitting = true; creatorSearch.close();
    form.setAttribute('aria-busy', 'true');
    const status = document.getElementById('invite-submit-status'); status.hidden = false;
    status.textContent = 'Отправляем в Telegram. Дождитесь результата…'; event.submitter.textContent = 'Отправляем…';
  });
})();
