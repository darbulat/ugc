'use strict';

const platform = document.getElementById('people-platform');
const minimum = document.getElementById('platform-followers-min');
const unknown = document.getElementById('platform-followers-unknown');

function syncAudienceFilters() {
  const hasPlatform = Boolean(platform.value);
  unknown.disabled = !hasPlatform;
  minimum.disabled = !hasPlatform || unknown.checked;
  minimum.placeholder = hasPlatform ? 'Например, 1000' : 'Выберите площадку';
}

platform.addEventListener('change', syncAudienceFilters);
unknown.addEventListener('change', syncAudienceFilters);
syncAudienceFilters();
