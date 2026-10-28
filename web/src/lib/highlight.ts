/** Syntax highlighting for the diff, via Shiki.
 *
 * Diff viewers usually tokenize one line at a time, which gets multi-line
 * strings, template literals and block comments wrong. selfcheck highlights the
 * whole file once (fetched from the read-only checkout) and then indexes the
 * result by line number, so a hunk in the middle of a docstring still renders
 * correctly. When the checkout is unavailable it degrades to per-line
 * tokenizing rather than dropping colour entirely.
 */
import type { BundledLanguage, BundledTheme, Highlighter, ThemedToken } from 'shiki'

export type Line = ThemedToken[]

const THEMES: Record<'light' | 'dark', BundledTheme> = {
  // Vitesse: low-contrast, teal-and-sage, and quiet next to the app palette.
  light: 'vitesse-light',
  dark: 'vitesse-dark',
}

const EXT_TO_LANG: Record<string, BundledLanguage> = {
  ts: 'typescript', tsx: 'tsx', mts: 'typescript', cts: 'typescript',
  js: 'javascript', jsx: 'jsx', mjs: 'javascript', cjs: 'javascript',
  py: 'python', pyi: 'python', rb: 'ruby', go: 'go', rs: 'rust',
  java: 'java', kt: 'kotlin', kts: 'kotlin', scala: 'scala', swift: 'swift',
  c: 'c', h: 'c', cc: 'cpp', cpp: 'cpp', cxx: 'cpp', hpp: 'cpp', hh: 'cpp',
  cs: 'csharp', php: 'php', pl: 'perl', lua: 'lua', r: 'r', jl: 'julia',
  sh: 'shell', bash: 'shell', zsh: 'shell', fish: 'fish', ps1: 'powershell',
  sql: 'sql', graphql: 'graphql', gql: 'graphql', proto: 'proto',
  html: 'html', htm: 'html', xml: 'xml', svg: 'xml', vue: 'vue', svelte: 'svelte',
  css: 'css', scss: 'scss', sass: 'sass', less: 'less',
  json: 'json', jsonc: 'jsonc', json5: 'json5', yaml: 'yaml', yml: 'yaml',
  toml: 'toml', ini: 'ini', cfg: 'ini', conf: 'ini', env: 'dotenv',
  md: 'markdown', mdx: 'mdx', rst: 'rst', tex: 'latex',
  dockerfile: 'docker', makefile: 'make', mk: 'make', cmake: 'cmake',
  tf: 'terraform', hcl: 'hcl', nix: 'nix', zig: 'zig', dart: 'dart',
  ex: 'elixir', exs: 'elixir', erl: 'erlang', hs: 'haskell', clj: 'clojure',
  vim: 'viml', diff: 'diff', patch: 'diff', gradle: 'groovy', groovy: 'groovy',
}

const FILENAME_TO_LANG: Record<string, BundledLanguage> = {
  dockerfile: 'docker', makefile: 'make', 'cmakelists.txt': 'cmake',
  gemfile: 'ruby', rakefile: 'ruby', 'go.mod': 'go',
}

export function langFor(path: string): BundledLanguage | null {
  const base = path.split('/').pop()?.toLowerCase() ?? ''
  if (FILENAME_TO_LANG[base]) return FILENAME_TO_LANG[base]
  const ext = base.includes('.') ? base.split('.').pop()! : base
  return EXT_TO_LANG[ext] ?? null
}

let highlighterPromise: Promise<Highlighter> | null = null
const loadedLangs = new Set<string>()

async function getHighlighter(): Promise<Highlighter> {
  if (!highlighterPromise) {
    highlighterPromise = import('shiki').then((shiki) =>
      shiki.createHighlighter({ themes: [THEMES.light, THEMES.dark], langs: [] }),
    )
  }
  return highlighterPromise
}

async function ensureLang(hl: Highlighter, lang: BundledLanguage): Promise<boolean> {
  if (loadedLangs.has(lang)) return true
  try {
    await hl.loadLanguage(lang)
    loadedLangs.add(lang)
    return true
  } catch {
    return false
  }
}

/** Tokenize a whole file. Returns one token array per 1-indexed line. */
export async function highlightFile(
  code: string,
  path: string,
  mode: 'light' | 'dark',
): Promise<Line[] | null> {
  const lang = langFor(path)
  if (!lang) return null
  // Very large files are not worth the main-thread time.
  if (code.length > 1_500_000) return null
  const hl = await getHighlighter()
  if (!(await ensureLang(hl, lang))) return null
  try {
    return hl.codeToTokens(code, { lang, theme: THEMES[mode] }).tokens
  } catch {
    return null
  }
}

/** Fallback: tokenize a handful of standalone lines. */
export async function highlightLines(
  lines: string[],
  path: string,
  mode: 'light' | 'dark',
): Promise<Line[] | null> {
  const lang = langFor(path)
  if (!lang) return null
  const hl = await getHighlighter()
  if (!(await ensureLang(hl, lang))) return null
  try {
    return lines.map((l) => hl.codeToTokens(l, { lang, theme: THEMES[mode] }).tokens[0] ?? [])
  } catch {
    return null
  }
}
