(function () {
  'use strict';

  function instagramUrl(value) {
    var input = value.trim();
    var match = /^@?([a-z0-9_.]{1,30})$/i.exec(input) ||
      /^(?:https?:\/\/)?(?:www\.)?instagram\.com\/([a-z0-9_.]{1,30})\/?(?:[?#].*)?$/i.exec(input);
    if (!match || match[1] === '.' || match[1] === '..') return '';
    return 'https://instagram.com/' + match[1];
  }

  function bindCity(request, text) {
    var byId = function (id) { return document.getElementById(id); };
    var city = byId('blg-city');
    var region = byId('blg-region');
    var country = byId('blg-country');
    var latitude = byId('blg-lat');
    var longitude = byId('blg-lon');
    var search = byId('blg-city-search');
    var searchButton = byId('btn-blogger-city-search');
    var confirm = byId('btn-blogger-city-confirm');
    var toggle = byId('btn-blogger-city-map');
    var block = byId('block-blogger-city-map');
    var hint = byId('blg-city-map-hint');
    var error = byId('blg-error');
    var map;
    var marker;
    var candidate;
    var generation = 0;
    var pending = false;

    function begin() {
      pending = true;
      confirm.disabled = true;
      return ++generation;
    }

    function finish(id) {
      if (id !== generation) return;
      pending = false;
      confirm.disabled = false;
      if (error.textContent === text('loading')) error.textContent = '';
    }

    function reset() {
      candidate = null;
      confirm.hidden = true;
      finish(++generation);
      [region, country, latitude, longitude, search].forEach(function (field) {
        field.value = '';
      });
      if (marker) {
        map.removeLayer(marker);
        marker = null;
      }
      hint.textContent = text('ph_blg_city_map_hint');
      showMap(false);
    }

    function suggest(data, lat, lon) {
      if (!data.city || !Number.isFinite(lat) || !Number.isFinite(lon)) {
        throw new Error('city_missing');
      }
      candidate = {lat: lat, lon: lon, region: data.region, country: data.country};
      city.value = data.city;
      confirm.hidden = false;
      hint.textContent = text('city_selected') + data.city;
      if (map) {
        map.setView([lat, lon], 12);
        if (marker) marker.setLatLng([lat, lon]);
        else marker = window.L.marker([lat, lon]).addTo(map);
      }
    }

    function lookup(path, input, id, failure) {
      request(path, input).then(function (data) {
        if (id !== generation) return;
        var point = path === '/geocode/reverse' ? input : data;
        suggest(data, point.lat, point.lon);
      }).catch(function () {
        if (id === generation) hint.textContent = text(failure);
      }).finally(function () { finish(id); });
    }

    function showMap(show) {
      block.style.display = show ? 'block' : 'none';
      toggle.setAttribute('aria-expanded', String(show));
      if (!show) return;
      if (!map && window.L) {
        map = window.L.map('blogger-city-map').setView([55.7558, 37.6173], 5);
        window.L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
          attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
        }).addTo(map);
        map.on('click', function (event) {
          lookup('/geocode/reverse', {lat: event.latlng.lat, lon: event.latlng.lng}, begin(), 'city_error');
        });
      } else if (map && map.invalidateSize) {
        map.invalidateSize();
      }
    }

    toggle.addEventListener('click', function () {
      var opening = block.style.display === 'none';
      showMap(opening);
      if (!opening || city.value || pending || !navigator.geolocation) return;
      var id = begin();
      navigator.geolocation.getCurrentPosition(function (position) {
        if (id !== generation) return;
        lookup('/geocode/reverse', {
          lat: position.coords.latitude, lon: position.coords.longitude
        }, id, 'city_error');
      }, function () { finish(id); }, {
        enableHighAccuracy: false, timeout: 5000, maximumAge: 60000
      });
    });

    searchButton.addEventListener('click', function () {
      var query = search.value.trim();
      if (!query) {
        hint.textContent = text('city_enter');
        return;
      }
      showMap(true);
      lookup('/geocode/forward', {city: query}, begin(), 'city_not_found');
    });

    search.addEventListener('keydown', function (event) {
      if (event.key !== 'Enter') return;
      event.preventDefault();
      searchButton.click();
    });

    confirm.addEventListener('click', function () {
      if (!candidate || pending) return;
      region.value = candidate.region || '';
      country.value = candidate.country || '';
      latitude.value = String(candidate.lat);
      longitude.value = String(candidate.lon);
      candidate = null;
      confirm.hidden = true;
      if (error.textContent === text('city_confirm_required')) error.textContent = '';
      showMap(false);
      toggle.focus();
      city.closest('form').dispatchEvent(new Event('change', {bubbles: true}));
    });

    return {
      reset: reset,
      get pending() { return pending; },
      get needsConfirmation() { return !!candidate; }
    };
  }

  function bindVerificationCopy(text) {
    var code = document.getElementById('instagram-verification-code');
    var button = document.getElementById('btn-instagram-copy');
    var status = document.getElementById('instagram-copy-status');
    var generation = 0;

    button.addEventListener('click', async function () {
      var value = code.value;
      if (!value) return;
      var current = generation;
      button.disabled = true;
      status.textContent = '';
      var copied = false;
      try {
        if (navigator.clipboard && navigator.clipboard.writeText) {
          await navigator.clipboard.writeText(value);
          copied = true;
        }
      } catch (_) {
        // Some messenger webviews deny the Clipboard API.
      }
      if (current !== generation) return;
      if (!copied) {
        code.focus();
        code.select();
        code.setSelectionRange(0, value.length);
        try { copied = document.execCommand('copy'); } catch (_) {}
      }
      status.textContent = text(copied ? 'instagram_code_copied' : 'instagram_code_manual');
      button.disabled = false;
    });

    return function setCode(value) {
      generation += 1;
      code.value = value || '';
      button.disabled = !code.value;
      status.textContent = '';
    };
  }

  window.UMCCreatorForm = {
    instagramUrl: instagramUrl,
    bindCity: bindCity,
    bindVerificationCopy: bindVerificationCopy
  };
})();
