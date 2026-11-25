'use strict';
const switcher = document.querySelector('[data-lang-switch]');
if (switcher) {
  const alternate = switcher.getAttribute('href');
  function keepSection() {
    switcher.setAttribute('href', alternate + window.location.hash);
  }
  keepSection();
  window.addEventListener('hashchange', keepSection);
}
