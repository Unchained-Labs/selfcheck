import { useCallback, useEffect, useRef, useState } from 'react'
import { copyText } from '../lib/clipboard'
import { Icon } from './Icon'

type State = 'idle' | 'ok' | 'failed'

/** Copy-to-clipboard with the confirmation inline on the button itself.
 *  A global toast is the wrong feedback for this: when you copy note after
 *  note, you need to see which one you just took. */
export function CopyButton({
  text, label = 'Copy', title, className = 'btn ghost sm', compact = false,
}: {
  /** A function, so a large payload is only built when actually copied. */
  text: string | (() => string)
  label?: string
  title?: string
  className?: string
  compact?: boolean
}) {
  const [state, setState] = useState<State>('idle')
  const timer = useRef<number | undefined>(undefined)

  useEffect(() => () => window.clearTimeout(timer.current), [])

  const onClick = useCallback(async () => {
    const payload = typeof text === 'function' ? text() : text
    const result = await copyText(payload)
    setState(result === 'ok' ? 'ok' : 'failed')
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => setState('idle'), result === 'ok' ? 1600 : 3200)
  }, [text])

  const shown = state === 'ok' ? 'Copied' : state === 'failed' ? 'Press ⌘C' : label

  return (
    <button
      type="button"
      className={`${className} copy-btn ${state}`}
      onClick={onClick}
      title={state === 'failed'
        ? 'The browser blocked the clipboard — select the text and copy manually'
        : (title ?? label)}
      aria-live="polite"
    >
      <Icon name={state === 'ok' ? 'check' : state === 'failed' ? 'alert' : 'copy'} size={13} />
      {!compact && <span>{shown}</span>}
    </button>
  )
}
