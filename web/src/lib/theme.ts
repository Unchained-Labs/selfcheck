/** Theme preference: follow the OS, or pin light / dark. */

export type ThemePref = 'system' | 'light' | 'dark'
export type Theme = 'light' | 'dark'

const KEY = 'selfcheck.theme'
const media = () => window.matchMedia('(prefers-color-scheme: light)')

export function loadPref(): ThemePref {
  try {
    const v = localStorage.getItem(KEY)
    return v === 'light' || v === 'dark' ? v : 'system'
  } catch {
    return 'system'
  }
}

export function savePref(pref: ThemePref) {
  try {
    if (pref === 'system') localStorage.removeItem(KEY)
    else localStorage.setItem(KEY, pref)
  } catch { /* private mode: the choice lasts for this tab */ }
}

export function resolve(pref: ThemePref): Theme {
  if (pref !== 'system') return pref
  return media().matches ? 'light' : 'dark'
}

export function apply(theme: Theme) {
  document.documentElement.dataset.theme = theme
}

export function onSystemChange(fn: () => void): () => void {
  const m = media()
  m.addEventListener('change', fn)
  return () => m.removeEventListener('change', fn)
}
