/** Desktop notifications, entirely in the browser: selfcheck's server never
 *  sends anything anywhere. The page watches the review list it already
 *  polls and raises a notification when a review it has seen start finishes. */

import type { Review } from './types'

export type NotifyLevel = 'off' | 'serious' | 'all'
const KEY = 'selfcheck.notify'

export function loadLevel(): NotifyLevel {
  try {
    const v = localStorage.getItem(KEY)
    return v === 'serious' || v === 'all' ? v : 'off'
  } catch {
    return 'off'
  }
}

export function saveLevel(level: NotifyLevel) {
  try { localStorage.setItem(KEY, level) } catch { /* private mode */ }
}

export const supported = () => typeof window !== 'undefined' && 'Notification' in window

export async function requestPermission(): Promise<NotificationPermission> {
  if (!supported()) return 'denied'
  if (Notification.permission !== 'default') return Notification.permission
  return Notification.requestPermission()
}

/** Run ids seen in a non-final state, so only runs that finish while this
 *  page is open notify — never a backlog on first load. */
const watching = new Set<string>()
const notified = new Set<string>()

export function checkForNotifications(
  reviews: Review[], level: NotifyLevel, open: (reviewId: string) => void,
) {
  if (level === 'off' || !supported() || Notification.permission !== 'granted') {
    for (const r of reviews) if (r.latest_run && isActive(r.latest_run.status)) watching.add(r.latest_run.id)
    return
  }
  for (const r of reviews) {
    const run = r.latest_run
    if (!run) continue
    if (isActive(run.status)) { watching.add(run.id); continue }
    if (!watching.has(run.id) || notified.has(run.id)) continue
    watching.delete(run.id)
    notified.add(run.id)

    const blockers = r.counts?.blocker ?? 0
    const majors = r.counts?.major ?? 0
    const serious = blockers + majors > 0
    if (run.status === 'failed') {
      show(r, `Review failed: ${r.project} #${r.number}`, run.error?.slice(0, 140) || 'The run did not finish.', open)
    } else if (run.status === 'done' && (level === 'all' || serious)) {
      const findings = serious
        ? `${blockers ? `${blockers} blocker${blockers === 1 ? '' : 's'}` : ''}${blockers && majors ? ', ' : ''}${majors ? `${majors} major` : ''}`
        : `${r.counts?.open ?? 0} open findings`
      show(r, `${serious ? '⚠ ' : ''}${r.project} #${r.number}: ${findings}`, r.title, open)
    }
  }
}

function isActive(status: string) {
  return ['queued', 'preparing', 'analyzing'].includes(status)
}

function show(r: Review, title: string, body: string, open: (id: string) => void) {
  const n = new Notification(title, { body, tag: `selfcheck-${r.id}` })
  n.onclick = () => {
    window.focus()
    open(r.id)
    n.close()
  }
}

export function testNotification() {
  if (supported() && Notification.permission === 'granted') {
    new Notification('selfcheck notifications are on', { body: 'You will hear about reviews as they finish.' })
  }
}
