/* Exact RUB boundary. Monetary values never pass through a JavaScript number. */
(function () {
  'use strict';
  var maximum = '9223372036854775807';
  function canonical(value) {
    return typeof value === 'string' && /^(0|[1-9][0-9]*)$/.test(value) &&
      (value.length < maximum.length || (value.length === maximum.length && value <= maximum));
  }
  function available() { return typeof BigInt === 'function'; }
  function parse(value) {
    if (!available() || typeof value !== 'string' || !/^(0|[1-9][0-9]*)([.,][0-9]{1,2})?$/.test(value)) return null;
    var pieces = value.split(/[.,]/), minor = (pieces[0] + (pieces[1] || '').padEnd(2, '0')).replace(/^0+(?=[0-9])/, '');
    if (!canonical(minor) || minor === '0' || BigInt(minor) > BigInt(maximum)) return null;
    return minor;
  }
  function format(value) {
    if (!canonical(value)) return null;
    var padded = value.padStart(3, '0');
    return padded.slice(0, -2).replace(/\B(?=(\d{3})+(?!\d))/g, '\u00a0') + ',' + padded.slice(-2) + '\u00a0RUB';
  }
  window.UMCPayoutMoney = Object.freeze({parse:parse, format:format, available:available, canonical:canonical});
})();
