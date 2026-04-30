// Sentral tema-handtering. Brukes baade fra Layout (innlogget) og Login.
// Settes ogsaa via inline-script i index.html for aa unngaa flash.

const STORAGE_KEY = 'theme';

export function getStoredTheme() {
  if (typeof window === 'undefined') return 'light';
  return localStorage.getItem(STORAGE_KEY) || 'light';
}

export function applyTheme(theme) {
  const root = document.documentElement;
  if (theme === 'dark') root.classList.add('dark');
  else root.classList.remove('dark');
  try { localStorage.setItem(STORAGE_KEY, theme); } catch (_) { /* ignore */ }
}

export function toggleTheme() {
  const next = getStoredTheme() === 'dark' ? 'light' : 'dark';
  applyTheme(next);
  return next;
}
