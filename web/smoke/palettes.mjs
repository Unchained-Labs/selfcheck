// Render the real app in candidate palettes by overriding the colour tokens.
import puppeteer from 'puppeteer-core'
const OUT = '/tmp/claude-1000/-home-wardn-dev-selfcheck/8e78142b-df46-43e2-8d30-9d20f4a9c67d/scratchpad/palettes'

const derived = `--accent-dim: color-mix(in oklch, var(--accent) 14%, transparent);
  --accent-ring: color-mix(in oklch, var(--accent) 38%, transparent);
  --heat-1: color-mix(in oklch, var(--accent) 28%, var(--heat-0));
  --heat-2: color-mix(in oklch, var(--accent) 52%, var(--heat-0));
  --heat-3: color-mix(in oklch, var(--accent) 76%, var(--heat-0));
  --heat-4: var(--accent);`

const P = {
  // Linear-style: one indigo-violet on near-black graphite (Radix iris + slate).
  indigo: {
    dark: { bg: '#0f1011', 'bg-raised': '#16171a', 'bg-elevated': '#1c1d21', 'bg-inset': '#0b0c0d', 'bg-hover': '#222328', 'bg-active': '#2a2b33',
      border: '#25262b', 'border-strong': '#34363d', fg: '#f7f8f8', 'fg-muted': '#b4b6be', 'fg-faint': '#8a8f98',
      accent: '#7170ff', 'accent-strong': '#5e6ad2', 'accent-2': '#828fff', 'accent-fg': '#ffffff', 'accent-text': '#9b9dff', 'on-color': '#0f1011', 'heat-0': '#1f2025' },
    light: { bg: '#f7f8f9', 'bg-raised': '#ffffff', 'bg-elevated': '#ffffff', 'bg-inset': '#f1f2f4', 'bg-hover': '#eceef1', 'bg-active': '#e4e6fb',
      border: '#e3e5e9', 'border-strong': '#d0d3da', fg: '#1b1c1f', 'fg-muted': '#5c606b', 'fg-faint': '#6b6f7a',
      accent: '#5e6ad2', 'accent-strong': '#4f58c0', 'accent-2': '#7170ff', 'accent-fg': '#ffffff', 'accent-text': '#4b55c4', 'on-color': '#ffffff', 'heat-0': '#eceef1' },
  },
  // Vercel / Geist: monochrome, a single blue for action.
  mono: {
    dark: { bg: '#0a0a0a', 'bg-raised': '#111111', 'bg-elevated': '#171717', 'bg-inset': '#070707', 'bg-hover': '#1f1f1f', 'bg-active': '#262626',
      border: '#232323', 'border-strong': '#333333', fg: '#ededed', 'fg-muted': '#a1a1a1', 'fg-faint': '#8b8b8b',
      accent: '#ededed', 'accent-strong': '#ffffff', 'accent-2': '#52a8ff', 'accent-fg': '#0a0a0a', 'accent-text': '#52a8ff', 'on-color': '#0a0a0a', 'heat-0': '#1c1c1c' },
    light: { bg: '#fafafa', 'bg-raised': '#ffffff', 'bg-elevated': '#ffffff', 'bg-inset': '#f4f4f4', 'bg-hover': '#efefef', 'bg-active': '#e8e8e8',
      border: '#eaeaea', 'border-strong': '#d4d4d4', fg: '#171717', 'fg-muted': '#4d4d4d', 'fg-faint': '#666666',
      accent: '#171717', 'accent-strong': '#000000', 'accent-2': '#0070f3', 'accent-fg': '#ffffff', 'accent-text': '#0068d6', 'on-color': '#ffffff', 'heat-0': '#ededed' },
    extra: `--heat-1: color-mix(in oklch, var(--accent-2) 28%, var(--heat-0)); --heat-2: color-mix(in oklch, var(--accent-2) 52%, var(--heat-0));
      --heat-3: color-mix(in oklch, var(--accent-2) 76%, var(--heat-0)); --heat-4: var(--accent-2);`,
  },
  // Catppuccin Mocha / Latte: mauve on soft purple-grey.
  mocha: {
    dark: { bg: '#1e1e2e', 'bg-raised': '#232334', 'bg-elevated': '#2a2b3c', 'bg-inset': '#181825', 'bg-hover': '#313244', 'bg-active': '#3a3b50',
      border: '#313244', 'border-strong': '#45475a', fg: '#cdd6f4', 'fg-muted': '#bac2de', 'fg-faint': '#9399b2',
      accent: '#cba6f7', 'accent-strong': '#b48ef0', 'accent-2': '#89b4fa', 'accent-fg': '#1e1e2e', 'accent-text': '#cba6f7', 'on-color': '#1e1e2e', 'heat-0': '#313244',
      'sev-blocker': '#f38ba8', 'sev-major': '#fab387', 'sev-minor': '#f9e2af', 'sev-praise': '#a6e3a1', 'sev-question': '#89dceb', ok: '#a6e3a1', bad: '#f38ba8', merged: '#b4befe' },
    light: { bg: '#eff1f5', 'bg-raised': '#f6f7fa', 'bg-elevated': '#ffffff', 'bg-inset': '#e6e9ef', 'bg-hover': '#e2e5ec', 'bg-active': '#dcd6f7',
      border: '#dce0e8', 'border-strong': '#ccd0da', fg: '#4c4f69', 'fg-muted': '#5c5f77', 'fg-faint': '#6c6f85',
      accent: '#8839ef', 'accent-strong': '#7528dd', 'accent-2': '#1e66f5', 'accent-fg': '#ffffff', 'accent-text': '#7a2fe0', 'on-color': '#ffffff', 'heat-0': '#e2e5ec',
      'sev-blocker': '#d20f39', 'sev-major': '#c14d08', 'sev-minor': '#9a6413', 'sev-praise': '#2f7f1f', 'sev-question': '#04799a', ok: '#2f7f1f', bad: '#d20f39', merged: '#7287fd' },
  },
  // Supabase-style: emerald on graphite.
  emerald: {
    dark: { bg: '#171717', 'bg-raised': '#1c1c1c', 'bg-elevated': '#232323', 'bg-inset': '#121212', 'bg-hover': '#2a2a2a', 'bg-active': '#1f3b2f',
      border: '#2a2a2a', 'border-strong': '#393939', fg: '#ededed', 'fg-muted': '#b4b4b4', 'fg-faint': '#8f8f8f',
      accent: '#3ecf8e', 'accent-strong': '#34b27b', 'accent-2': '#6ee7b7', 'accent-fg': '#0b1f16', 'accent-text': '#3ecf8e', 'on-color': '#171717', 'heat-0': '#262626' },
    light: { bg: '#fcfcfc', 'bg-raised': '#ffffff', 'bg-elevated': '#ffffff', 'bg-inset': '#f6f6f6', 'bg-hover': '#f0f0f0', 'bg-active': '#e3f5ec',
      border: '#e8e8e8', 'border-strong': '#d6d6d6', fg: '#1c1c1c', 'fg-muted': '#525252', 'fg-faint': '#6b6b6b',
      accent: '#1f9d63', 'accent-strong': '#178553', 'accent-2': '#3ecf8e', 'accent-fg': '#ffffff', 'accent-text': '#15784b', 'on-color': '#ffffff', 'heat-0': '#efefef' },
  },
}

const block = (vals, extra) => Object.entries(vals).map(([k, v]) => `--${k}: ${v};`).join('\n  ') + '\n  ' + derived + (extra ?? '')
const css = (p) => `:root:not([data-theme='light']) { ${block(p.dark, p.extra)} }
:root[data-theme='light'] { ${block(p.light, p.extra)} }`

const b = await puppeteer.launch({ executablePath: '/usr/bin/google-chrome', headless: true })
const reviews = (await (await fetch('http://127.0.0.1:7777/api/reviews')).json()).reviews
const r = reviews.find((x) => x.project === 'click') ?? reviews[0]
for (const [name, p] of Object.entries(P)) {
  for (const theme of ['dark', 'light']) {
    const page = await b.newPage()
    await page.setViewport({ width: 1440, height: 900 })
    await page.emulateMediaFeatures([{ name: 'prefers-color-scheme', value: theme }])
    for (const [view, h] of [['home', '#/'], ['review', `#/r/${r.id}/diff`]]) {
      await page.goto('http://127.0.0.1:7777/' + h, { waitUntil: 'networkidle0' })
      await page.reload({ waitUntil: 'networkidle0' })
      await page.addStyleTag({ content: css(p) })
      await new Promise((s) => setTimeout(s, 1500))
      await page.screenshot({ path: `${OUT}/${name}-${theme}-${view}.png` })
    }
    await page.close()
  }
  console.log(name)
}
await b.close()
