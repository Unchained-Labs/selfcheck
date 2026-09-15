/** A deliberately small markdown renderer.
 *
 * Note bodies come from Claude, and Claude is summarising a diff written by
 * someone else — so this escapes everything first and only then re-introduces
 * the handful of constructs that actually show up in review prose. No raw HTML
 * passes through, which is the whole point of not pulling in a full parser.
 */

const ESCAPES: Record<string, string> = {
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
}

const SENTINEL = ''

function esc(s: string): string {
  return s.replace(/[&<>"']/g, (c) => ESCAPES[c])
}

function inline(s: string): string {
  // Strip any pre-existing sentinel so input cannot forge a placeholder.
  let out = esc(s.split(SENTINEL).join(''))

  // Code spans first, so their contents are not touched by the other rules.
  const spans: string[] = []
  out = out.replace(/`([^`]+)`/g, (_m, code: string) => {
    spans.push(`<code>${code}</code>`)
    return `${SENTINEL}${spans.length - 1}${SENTINEL}`
  })

  out = out
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/(^|\W)_([^_]+)_(?=\W|$)/g, '$1<em>$2</em>')
    .replace(/\*([^*]+)\*/g, '<em>$1</em>')
    .replace(
      /\[([^\]]+)\]\((https?:[^)\s]+)\)/g,
      '<a href="$2" target="_blank" rel="noreferrer noopener">$1</a>',
    )
    .replace(
      /(^|\s)(https?:\/\/[^\s<]+)/g,
      '$1<a href="$2" target="_blank" rel="noreferrer noopener">$2</a>',
    )

  const placeholder = new RegExp(`${SENTINEL}(\\d+)${SENTINEL}`, 'g')
  return out.replace(placeholder, (_m, i: string) => spans[Number(i)] ?? '')
}

export function renderMarkdown(src: string): string {
  const lines = (src ?? '').replace(/\r\n/g, '\n').split('\n')
  const out: string[] = []
  let i = 0
  let list: 'ul' | 'ol' | null = null

  const closeList = () => {
    if (list) {
      out.push(`</${list}>`)
      list = null
    }
  }

  while (i < lines.length) {
    const line = lines[i]

    const fence = /^\s*```(\w*)\s*$/.exec(line)
    if (fence) {
      closeList()
      const buf: string[] = []
      i++
      while (i < lines.length && !/^\s*```\s*$/.test(lines[i])) buf.push(lines[i++])
      i++
      out.push(`<pre><code>${esc(buf.join('\n'))}</code></pre>`)
      continue
    }

    if (!line.trim()) {
      closeList()
      i++
      continue
    }

    const heading = /^(#{1,6})\s+(.*)$/.exec(line)
    if (heading) {
      closeList()
      const level = Math.min(6, heading[1].length + 2)
      out.push(`<h${level}>${inline(heading[2])}</h${level}>`)
      i++
      continue
    }

    const ul = /^\s*[-*+]\s+(.*)$/.exec(line)
    const ol = /^\s*\d+[.)]\s+(.*)$/.exec(line)
    if (ul || ol) {
      const want = ul ? 'ul' : 'ol'
      if (list !== want) {
        closeList()
        out.push(`<${want}>`)
        list = want
      }
      out.push(`<li>${inline((ul ?? ol)![1])}</li>`)
      i++
      continue
    }

    closeList()
    const para: string[] = []
    while (
      i < lines.length &&
      lines[i].trim() &&
      !/^\s*(```|[-*+]\s|\d+[.)]\s|#{1,6}\s)/.test(lines[i])
    ) {
      para.push(lines[i++])
    }
    out.push(`<p>${inline(para.join(' '))}</p>`)
  }

  closeList()
  return out.join('')
}
