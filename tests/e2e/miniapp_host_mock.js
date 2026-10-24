(() => {
  const platform = __PLATFORM__;
  const native = __NATIVE__;
  const events = {};
  const calls = [];
  const wa = {
    initData: __INIT_DATA__, colorScheme: 'light',
    viewportStableHeight: 800, contentSafeAreaInset: {top: 12, bottom: 20},
    ready() {}, expand() {}, onEvent(name, fn) { events[name] = fn; },
    setBackgroundColor(color) { calls.push(['background', color]); },
    setHeaderColor(color) { calls.push(['header', color]); },
    setBottomBarColor(color) { calls.push(['bottom', color]); },
    openLink(url) { calls.push(['link', url]); },
    openTelegramLink(url) { calls.push(['telegram-link', url]); },
    close() { calls.push(['close']); }
  };
  if (platform === 'telegram') wa.isVersionAtLeast = () => true;
  if (native) {
    wa.MainButton = {params: {}, visible: false,
      setParams(params) { Object.assign(this.params, params); },
      onClick(fn) { this.click = fn; },
      show() { this.visible = true; }, hide() { this.visible = false; },
      showProgress() { this.busy = true; }, hideProgress() { this.busy = false; }
    };
    wa.BackButton = {visible: false,
      onClick(fn) { this.click = fn; },
      show() { this.visible = true; }, hide() { this.visible = false; }
    };
  }
  window.__host = {wa, events, calls};
  if (platform === 'max') window.WebApp = wa;
  else window.Telegram = {WebApp: wa};
}
)();
