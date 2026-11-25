'use strict';

// Links shared before the language home was introduced pointed to chapters at /#….
function openBookmarkedChapter() {
  const bookmark = document.getElementById(window.location.hash.slice(1));
  if (!bookmark || !bookmark.hasAttribute('data-chapter-link')) return;
  const destination = new URL(bookmark.href);
  destination.search = window.location.search;
  window.location.replace(destination.href);
}

openBookmarkedChapter();
window.addEventListener('hashchange', openBookmarkedChapter);
