// One-time rename of browser storage keys: the app used to be called "Nastusha".
// Runs as the first import of main.tsx, before any module reads localStorage
// (the API client loads the saved session at import time), so nobody is logged
// out and no filter, sort or synchronization baseline is lost.

const OLD_PREFIX = "nastusha.";
const NEW_PREFIX = "minidrive.";

try {
  const oldKeys: string[] = [];
  for (let i = 0; i < localStorage.length; i++) {
    const key = localStorage.key(i);
    if (key?.startsWith(OLD_PREFIX)) oldKeys.push(key);
  }
  for (const oldKey of oldKeys) {
    const newKey = NEW_PREFIX + oldKey.slice(OLD_PREFIX.length);
    const value = localStorage.getItem(oldKey);
    if (value !== null && localStorage.getItem(newKey) === null) localStorage.setItem(newKey, value);
    localStorage.removeItem(oldKey);
  }
} catch {
  /* storage unavailable (private mode): nothing to migrate */
}

export {};
