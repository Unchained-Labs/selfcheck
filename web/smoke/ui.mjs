/**
 * Browser smoke test for the parts of the UI that are easy to break and hard
 * to typecheck: what the copy buttons actually put on the clipboard, and
 * whether jumping to a finding lands on it.
 *
 *   scripts/smoke-ui.sh          (starts nothing — point it at a running server)
 *
 * It picks the first tracked review that has open notes, and skips cleanly if
 * there is none, so it is safe to run against any selfcheck instance.
 */
import puppeteer from 'puppeteer-core'

const BASE = process.env.SELFCHECK_URL ?? 'http://127.0.0.1:7777'
const CHROME = process.env.CHROME_PATH ?? '/usr/bin/google-chrome'
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

const failures = []
const check = (cond, what) => {
  console.log(`  ${cond ? '✓' : '✗'} ${what}`)
  if (!cond) failures.push(what)
}

async function pickReview() {
  const res = await fetch(`${BASE}/api/reviews`)
  if (!res.ok) throw new Error(`GET /api/reviews -> ${res.status}`)
  const { reviews } = await res.json()
  return reviews.find((r) => (r.counts?.open ?? 0) > 0) ?? null
}

const review = await pickReview().catch((e) => {
  console.error(`cannot reach selfcheck at ${BASE}: ${e.message}`)
  process.exit(2)
})

if (!review) {
  console.log('no tracked review has open notes — nothing to smoke test, skipping')
  process.exit(0)
}
console.log(`using ${review.namespace}/${review.project} #${review.number}\n`)

const browser = await puppeteer.launch({
  executablePath: CHROME,
  headless: 'new',
  protocolTimeout: 30000,
  defaultViewport: { width: 1500, height: 950 },
  args: ['--no-sandbox', '--disable-gpu', '--hide-scrollbars'],
})

try {
  const page = await browser.newPage()
  page.on('pageerror', (e) => check(false, `no page errors (got: ${e.message})`))

  // Intercept the clipboard so we can assert on the payload itself.
  await page.evaluateOnNewDocument(() => {
    window.__copied = []
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText: (t) => { window.__copied.push(t); return Promise.resolve() } },
    })
  })

  await page.goto(`${BASE}/#/r/${review.id}/notes`, { waitUntil: 'networkidle2' })
  await page.waitForSelector('.note', { timeout: 20000 })
  await sleep(600)

  const lastCopy = () => page.evaluate(() => window.__copied.at(-1) ?? '')

  await page.evaluate(() => document.querySelector('.note .note-foot .copy-btn').click())
  await sleep(400)
  const one = await lastCopy()
  check(one.trim().length > 0, 'copying a single note produces text')
  check(/^`.+`/.test(one), 'a note copied from the Notes tab leads with its location')
  check(/\*\*\w+ — \w+\*\*/.test(one), 'the copied note carries severity and category')
  check(
    /Copied/.test(await page.evaluate(() =>
      document.querySelector('.note .note-foot .copy-btn').textContent)),
    'the copy button confirms on the button itself',
  )

  await page.evaluate(() =>
    document.querySelectorAll('.notes-toolbar .copy-btn')[0].click())
  await sleep(400)
  const all = await lastCopy()
  check(all.includes('- **'), 'copy-all produces a bulleted list of findings')
  check(all.length > one.length, 'copy-all is larger than a single note')

  const jumpable = await page.evaluate(() => !!document.querySelector('.note .loc-link'))
  if (jumpable) {
    await page.evaluate(() => document.querySelector('.note .loc-link').click())
    await sleep(2000)
    check(
      await page.evaluate(() => location.hash.endsWith('/diff')),
      'clicking a note location switches to the diff',
    )
    check(
      await page.evaluate(() => !!document.querySelector('.dtable')),
      'the diff renders after jumping to a finding',
    )
  }

  await page.keyboard.press('?')
  await sleep(400)
  check(
    await page.evaluate(() => !!document.querySelector('.modal.shortcuts')),
    '? opens the keyboard shortcuts',
  )
  await page.keyboard.press('Escape')
  await sleep(300)
  check(
    await page.evaluate(() => !document.querySelector('.modal.shortcuts')),
    'Escape closes the shortcuts',
  )
} finally {
  await browser.close()
}

console.log(failures.length ? `\n${failures.length} check(s) failed` : '\nall checks passed')
process.exit(failures.length ? 1 : 0)
