/* Only allowlisted, nonsensitive recovery intent may survive a page. */
(function () {
  'use strict';
  var uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
  function validId(value) { return typeof value === 'string' && uuid.test(value) && value !== '00000000-0000-0000-0000-000000000000'; }
  function key(partition) {
    if (!partition || Object.keys(partition).length !== 2 || !Object.prototype.hasOwnProperty.call(partition,'actor_id') || !Object.prototype.hasOwnProperty.call(partition,'platform') || !validId(partition.actor_id) || ['telegram','max'].indexOf(partition.platform) < 0) return null;
    return 'umc:payout:v1:' + partition.platform + ':' + partition.actor_id;
  }
  function normalize(value) {
    if (!value || typeof value !== 'object' || Array.isArray(value) || value.version !== 1 || !validId(value.operation_key)) return null;
    var names = ['version','action','operation_key'];
    if (value.action === 'RequestPayout') names = names.concat(['requisites_id','amount_minor','currency']);
    else if (value.action === 'StorePayoutRequisites') names = names.concat(['requirements_id','document_id','document_hash']);
    else return null;
    if (Object.keys(value).length !== names.length || Object.keys(value).some(function (name) { return names.indexOf(name) < 0; })) return null;
    if (value.action === 'RequestPayout' && (!validId(value.requisites_id) || !window.UMCPayoutMoney.canonical(value.amount_minor) || value.amount_minor === '0' || value.currency !== 'RUB')) return null;
    if (value.action === 'StorePayoutRequisites' && (!validId(value.requirements_id) || !validId(value.document_id) || typeof value.document_hash !== 'string' || !/^[0-9a-f]{64}$/.test(value.document_hash))) return null;
    var result = {}; names.forEach(function (name) { result[name] = value[name]; });
    return Object.freeze(result);
  }
  function read(partition) {
    var name = key(partition); if (!name) return {status:'blocked', record:null};
    try {
      var raw = localStorage.getItem(name);
      if (raw === null) return {status:'empty', record:null};
      var value = normalize(JSON.parse(raw));
      return value ? {status:'pending', record:value} : {status:'blocked', record:null};
    } catch (_) { return {status:'blocked', record:null}; }
  }
  function equal(a, b) { var one = normalize(a), two = normalize(b); return !!one && !!two && JSON.stringify(one) === JSON.stringify(two); }
  function write(partition, record) {
    var value = normalize(record), current = read(partition), name = key(partition);
    if (!value || !name || current.status === 'blocked' || (current.record && !equal(current.record,value))) return false;
    try { localStorage.setItem(name, JSON.stringify(value)); return equal(read(partition).record,value); } catch (_) { return false; }
  }
  function clear(partition, expected) {
    var name = key(partition); if (!name || !equal(read(partition).record,expected)) return false;
    try { localStorage.removeItem(name); return read(partition).status === 'empty'; } catch (_) { return false; }
  }
  function available() { try { return !!window.crypto && (typeof window.crypto.randomUUID === 'function' || typeof window.crypto.getRandomValues === 'function'); } catch (_) { return false; } }
  function newKey() {
    try {
      var crypto = window.crypto;
      if (crypto && typeof crypto.randomUUID === 'function') { var id = crypto.randomUUID(); return validId(id) ? id : null; }
      if (!crypto || typeof crypto.getRandomValues !== 'function') return null;
      var bytes = new Uint8Array(16); crypto.getRandomValues(bytes); bytes[6] = (bytes[6] & 15) | 64; bytes[8] = (bytes[8] & 63) | 128;
      var hex = Array.from(bytes, function (b) { return b.toString(16).padStart(2,'0'); }).join('');
      return hex.slice(0,8)+'-'+hex.slice(8,12)+'-'+hex.slice(12,16)+'-'+hex.slice(16,20)+'-'+hex.slice(20);
    } catch (_) { return null; }
  }
  window.UMCPayoutState = Object.freeze({key:key, read:read, write:write, clear:clear, newKey:newKey, available:available, equal:equal, validId:validId});
})();
