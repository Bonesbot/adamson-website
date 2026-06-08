// Thousands-separator formatting for the Find My Dream Home wishlist form.
// Served as a static public asset (not processed by Astro, no inline JS
// attributes) so it can't be stripped by the build or Netlify's form processor.
// Budget shows "$2,000,000"; Property Size shows "2,500". On focus the field
// reverts to raw digits for easy editing; the Netlify function strips the
// $ and commas server-side, so the stored value is a clean number.
(function () {
  function fmt(el, prefix) {
    var raw = String(el.value).replace(/[^0-9.]/g, '');
    if (!raw) { el.value = ''; return; }
    var n = parseFloat(raw);
    if (isNaN(n)) { el.value = ''; return; }
    el.value = prefix + Math.round(n).toLocaleString('en-US');
  }
  function attach() {
    document.querySelectorAll('[data-format="currency"]').forEach(function (el) {
      el.addEventListener('focus', function () { el.value = String(el.value).replace(/[^0-9.]/g, ''); });
      el.addEventListener('blur', function () { fmt(el, '$'); });
    });
    document.querySelectorAll('[data-format="number"]').forEach(function (el) {
      el.addEventListener('focus', function () { el.value = String(el.value).replace(/[^0-9.]/g, ''); });
      el.addEventListener('blur', function () { fmt(el, ''); });
    });
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', attach);
  } else {
    attach();
  }
})();
