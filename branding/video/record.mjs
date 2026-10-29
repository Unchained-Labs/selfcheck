// Record selfcheck's featurettes from a real, seeded instance (see seed.py).
//
//   node branding/video/record.mjs [--base http://127.0.0.1:7778] [--out branding/video/out]
//
// Each scene drives the UI in headless Chrome with a visible cursor and a
// caption, and is screencast to WebM; build.sh turns them into MP4s and the
// promo. Long waits (a review running) are cut, not sped up: a scene records
// in segments and build.sh joins them. Needs Chrome and ffmpeg.

import { mkdirSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { createRequire } from 'node:module'

// puppeteer-core is a dev dependency of the web app; resolve it from there.
const require = createRequire(new URL('../../web/package.json', import.meta.url))
const puppeteer = require('puppeteer-core')

const arg = (name, fallback) => {
  const i = process.argv.indexOf(`--${name}`)
  return i > -1 ? process.argv[i + 1] : fallback
}
const BASE = arg('base', 'http://127.0.0.1:7778')
const OUT = resolve(arg('out', 'branding/video/out'))
const CHROME = process.env.CHROME_PATH ?? '/usr/bin/google-chrome'
const LIVE_PR = arg('live-pr', 'https://github.com/pallets/click/pull/3897')
const W = 1440
const H = 900
mkdirSync(OUT, { recursive: true })

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const api = async (path, init) => (await fetch(BASE + path, init)).json()

/* ── page helpers ─────────────────────────────────────────────────────── */

// A visible cursor and a caption bar, injected into every page load.
const OVERLAY = `
(() => {
  try {
    // Every scene starts dark; only the engines scene toggles the theme, in-page.
    localStorage.setItem('selfcheck.theme', 'dark')
    if (!localStorage.getItem('selfcheck.lastActive'))
      localStorage.setItem('selfcheck.lastActive', new Date(Date.now() - 20 * 3600e3).toISOString())
  } catch {}
  const install = () => {
    if (document.getElementById('__cursor')) return
    const style = document.createElement('style')
    style.textContent = \`
      #__cursor { position: fixed; z-index: 99999; width: 22px; height: 22px; margin: -3px 0 0 -3px;
        pointer-events: none; transition: transform .08s; filter: drop-shadow(0 2px 4px rgba(0,0,0,.5)); }
      #__cursor.down { transform: scale(.85); }
      #__ripple { position: fixed; z-index: 99998; width: 34px; height: 34px; margin: -17px 0 0 -17px; border-radius: 50%;
        border: 2px solid #f28c5c; pointer-events: none; opacity: 0; }
      #__ripple.on { animation: rip .45s ease-out; }
      @keyframes rip { from { opacity: .9; transform: scale(.4) } to { opacity: 0; transform: scale(1.4) } }
      #__caption { position: fixed; z-index: 99997; left: 50%; bottom: 28px; transform: translate(-50%, 12px);
        max-width: 980px; padding: 12px 22px; border-radius: 14px; font: 600 19px/1.35 Inter, system-ui, sans-serif;
        color: #fef5ee; background: rgba(22, 16, 13, .86); border: 1px solid rgba(242,140,92, .45);
        box-shadow: 0 12px 40px rgba(0,0,0,.45); opacity: 0; transition: opacity .35s, transform .35s; text-align: center; }
      #__caption.on { opacity: 1; transform: translate(-50%, 0); }
      #__caption b { color: #f28c5c; font-weight: 650; }\`
    document.head.appendChild(style)
    const c = document.createElement('div')
    c.id = '__cursor'
    c.innerHTML = '<svg viewBox="0 0 24 24" width="22" height="22"><path d="M4 2l15 10-7 1.5L8.5 21z" fill="#fff" stroke="#1b1410" stroke-width="1.4" stroke-linejoin="round"/></svg>'
    const r = document.createElement('div'); r.id = '__ripple'
    const cap = document.createElement('div'); cap.id = '__caption'
    document.body.append(c, r, cap)
    c.style.left = (window.__cx ?? 720) + 'px'; c.style.top = (window.__cy ?? 450) + 'px'
    addEventListener('mousemove', (e) => { c.style.left = e.clientX + 'px'; c.style.top = e.clientY + 'px'; window.__cx = e.clientX; window.__cy = e.clientY }, true)
    addEventListener('mousedown', (e) => { c.classList.add('down'); r.style.left = e.clientX + 'px'; r.style.top = e.clientY + 'px'; r.classList.remove('on'); void r.offsetWidth; r.classList.add('on') }, true)
    addEventListener('mouseup', () => c.classList.remove('down'), true)
    window.__caption = (html) => { cap.innerHTML = html; cap.classList.toggle('on', !!html) }
  }
  if (document.readyState === 'loading') addEventListener('DOMContentLoaded', install); else install()
})()`

async function caption(page, html) {
  await page.evaluate((h) => window.__caption?.(h), html)
}

async function moveTo(page, selector, { text, offsetY = 0 } = {}) {
  const handle = text
    ? await page.waitForFunction((sel, t) => [...document.querySelectorAll(sel)].find((e) => e.textContent.includes(t)), {}, selector, text)
    : await page.waitForSelector(selector, { visible: true })
  const el = handle.asElement ? handle.asElement() : handle
  await el.evaluate((e) => e.scrollIntoView({ block: 'center', behavior: 'instant' }))
  await sleep(150)
  const box = await el.boundingBox()
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2 + offsetY, { steps: 28 })
  return el
}

async function click(page, selector, opts) {
  const el = await moveTo(page, selector, opts)
  await sleep(220)
  await el.click()
  await sleep(400)
}

/** Smoothly scroll the main column to a position, or an element into view. */
async function scroll(page, target, ms = 1600) {
  await page.evaluate(async (target, ms) => {
    const sc = [...document.querySelectorAll('.scroller')].pop()
    if (!sc) return
    const from = sc.scrollTop
    const to = typeof target === 'number' ? target
      : (document.querySelector(target)?.getBoundingClientRect().top ?? 0) + from - 110
    const t0 = performance.now()
    await new Promise((done) => {
      const tick = (t) => {
        const k = Math.min(1, (t - t0) / ms)
        sc.scrollTop = from + (to - from) * (1 - Math.pow(1 - k, 3))
        k < 1 ? requestAnimationFrame(tick) : done()
      }
      requestAnimationFrame(tick)
    })
  }, target, ms)
}

async function go(page, hash) {
  await page.goto(`${BASE}/?v=${Date.now()}${hash}`, { waitUntil: 'networkidle2' })
  await sleep(900)
}

/* ── scenes ───────────────────────────────────────────────────────────── */

async function reviewId(project, number) {
  const { reviews } = await api('/api/reviews')
  return reviews.find((r) => r.project === project && (number === undefined || r.number === number))?.id
}

const SCENES = {
  async dashboard(page, rec) {
    await go(page, '#/')
    await rec.start()
    await caption(page, '<b>Home</b> — what was reviewed, what it found, and what changed since you were last here')
    await sleep(3200)
    await scroll(page, '.dash .dcard', 1800)
    await caption(page, 'A year of activity, reviews per day, and a running total')
    await sleep(2600)
    await scroll(page, '.dash-grid.three', 1800)
    await caption(page, 'What the findings are — every number opens the reviews behind it')
    await sleep(2400)
    await click(page, '.hbar-row.clickable')
    await caption(page, '<b>Reviews</b>, filtered: every pull request with an open blocker')
    await sleep(3200)
    await caption(page, '')
    await rec.stop()
  },

  async review(page, rec) {
    await go(page, '#/')
    await rec.start()
    await caption(page, 'Paste a pull request — or a local branch, to check it before you push')
    await moveTo(page, '.addbar-input input')
    await page.click('.addbar-input input')
    await page.keyboard.type(LIVE_PR, { delay: 28 })
    await sleep(500)
    await click(page, '.addbar .seg.xs button', { text: 'Light' })  // depth, not the theme switch
    await click(page, '.addbar-go')
    await caption(page, 'The engine reads a <b>read-only checkout</b>. Nothing is ever posted back.')
    await page.waitForSelector('.runbar', { visible: true, timeout: 30000 })
    await sleep(7000)
    await rec.stop()

    // The review takes a while; the video cuts to when it is done.
    const id = await reviewId('click', Number(LIVE_PR.split('/').pop()))
    for (let i = 0; i < 150; i++) {
      const { latest_run: run } = await api(`/api/reviews/${id}`)
      if (run && ['done', 'failed'].includes(run.status)) break
      await sleep(4000)
    }
    await go(page, `#/r/${id}`)
    await rec.start()
    await caption(page, 'A verdict, a summary, risks and questions for the author')
    await sleep(3000)
    await click(page, '.tab', { text: 'Files' })
    await sleep(800)
    await page.keyboard.press('n')
    await caption(page, 'Every finding sits on the line it is about — <b>n</b> / <b>p</b> walk them')
    await sleep(3800)
    await caption(page, '')
    await rec.stop()
  },

  async ask(page, rec) {
    const id = await reviewId('stats-lib')
    await go(page, `#/r/${id}/diff`)
    await rec.start()
    await caption(page, 'A <b>local branch</b>, reviewed like a pull request')
    await sleep(1200)
    await page.keyboard.press('n')
    await sleep(1600)
    await click(page, '.note .note-foot .btn', { text: 'Ask' })
    await caption(page, '<b>Ask</b> about any finding — the engine checks the code and cites the lines')
    await scroll(page, '.thread', 1400)
    await sleep(5200)
    await caption(page, '')
    await rec.stop()
  },

  async second(page, rec) {
    const id = await reviewId('stats-lib')
    await go(page, `#/r/${id}`)
    await rec.start()
    await caption(page, 'A <b>second opinion</b> from another engine, side by side')
    await moveTo(page, '.second-opinion .so-meter')
    await sleep(3200)
    await moveTo(page, '.second-opinion details summary')
    await caption(page, 'What both found, and what only one did — adopt it with a click')
    await sleep(3200)
    await caption(page, '')
    await rec.stop()
  },

  async wakeups(page, rec) {
    await go(page, '#/wakeups')
    await rec.start()
    await caption(page, '<b>Wakeups</b>: check a repository on a schedule and review new pull requests')
    await sleep(2600)
    await click(page, '.wake-actions .btn', { text: 'Open PR' })
    await caption(page, 'See what the next check will review, and why it skips the rest')
    await sleep(3600)
    await caption(page, '')
    await rec.stop()
  },

  async engines(page, rec) {
    await go(page, '#/')
    await rec.start()
    await caption(page, 'Claude Code, Codex, Cursor, the Anthropic API, or a <b>local model</b>')
    await click(page, '.engine-switch-btn')
    await sleep(2600)
    await page.keyboard.press('Escape')
    await click(page, '.nav-item', { text: 'Settings' })
    await caption(page, 'Switch engines, models and depth on the fly — no restart')
    await sleep(1800)
    await scroll(page, 380, 1600)
    await sleep(1400)
    await click(page, '.theme-row button', { text: 'Light' })
    await caption(page, 'Light, dark, or follow the system')
    await sleep(2400)
    await click(page, '.theme-row button', { text: 'Dark' })
    await caption(page, '')
    await sleep(600)
    await rec.stop()
  },
}

/* ── stills for the README and the docs (`--shots`) ─────────────────────── */

async function shots(browser) {
  const dir = resolve(arg('shots-out', 'docs'))
  const stats = await reviewId('stats-lib')
  const live = await reviewId('click', Number(LIVE_PR.split('/').pop()))
  const list = [
    ['screenshot-dashboard.png', '#/', 'dark', null],
    ['screenshot-review.png', `#/r/${stats}`, 'dark', null],
    ['screenshot-diff.png', `#/r/${live}/diff`, 'dark', 'n'],
    ['screenshot-light.png', `#/r/${stats}/diff`, 'light', 'n'],
  ]
  for (const [file, hash, theme, key] of list) {
    const page = await browser.newPage()
    await page.evaluateOnNewDocument(`try { localStorage.setItem('selfcheck.theme', '${theme}') } catch {}`)
    await page.setViewport({ width: W, height: H, deviceScaleFactor: 2 })
    await go(page, hash)
    if (key) { await page.keyboard.press(key); await sleep(1500) }
    await page.screenshot({ path: join(dir, file) })
    console.log(`  ${file}`)
    await page.close()
  }
}

/* ── run ─────────────────────────────────────────────────────────────── */

const only = process.argv.filter((a) => SCENES[a])
const browser = await puppeteer.launch({
  executablePath: CHROME,
  headless: true,
  defaultViewport: { width: W, height: H, deviceScaleFactor: 1 },
  args: [`--window-size=${W},${H}`, '--hide-scrollbars', '--force-color-profile=srgb'],
})
try {
  if (process.argv.includes('--shots')) {
    await shots(browser)
    process.exit(0)
  }
  for (const [name, scene] of Object.entries(SCENES)) {
    if (only.length && !only.includes(name)) continue
    const page = await browser.newPage()
    await page.evaluateOnNewDocument(OVERLAY)
    await page.mouse.move(W / 2, H / 2)
    let segment = 0
    let recorder = null
    const rec = {
      start: async () => {
        recorder = await page.screencast({ path: join(OUT, `${name}-${segment++}.webm`) })
        await sleep(300)
      },
      stop: async () => { await sleep(300); await recorder.stop(); recorder = null },
    }
    console.log(`recording ${name}`)
    try {
      await scene(page, rec)
    } finally {
      if (recorder) await recorder.stop()
      await page.close()
    }
  }
} finally {
  await browser.close()
}
console.log(`segments in ${OUT}`)
