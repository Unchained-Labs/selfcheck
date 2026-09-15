/** Copying text out is the whole point of selfcheck — it never posts anything
 *  itself — so this path has to work everywhere rather than only on the happy
 *  modern-browser-with-focus case. */

export type CopyResult = 'ok' | 'failed'

async function viaAsyncApi(text: string): Promise<boolean> {
  if (!navigator.clipboard?.writeText) return false
  try {
    // Requires a secure context, the document focused, and permission. Any of
    // those can be missing, so this is an attempt, not a guarantee.
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    return false
  }
}

function viaTextarea(text: string): boolean {
  const el = document.createElement('textarea')
  el.value = text
  // Keep it out of view without using display:none, which makes it unselectable.
  el.setAttribute('readonly', '')
  el.style.cssText = 'position:fixed;top:0;left:-9999px;opacity:0;'
  document.body.appendChild(el)

  const selection = document.getSelection()
  const previous = selection && selection.rangeCount > 0 ? selection.getRangeAt(0) : null

  try {
    el.select()
    el.setSelectionRange(0, el.value.length)
    const ok = document.execCommand('copy')
    return ok
  } catch {
    return false
  } finally {
    document.body.removeChild(el)
    if (previous && selection) {
      selection.removeAllRanges()
      selection.addRange(previous)
    }
  }
}

export async function copyText(text: string): Promise<CopyResult> {
  if (!text) return 'failed'
  if (await viaAsyncApi(text)) return 'ok'
  return viaTextarea(text) ? 'ok' : 'failed'
}
