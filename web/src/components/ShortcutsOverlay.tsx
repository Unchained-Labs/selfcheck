const GROUPS: { title: string; keys: [string, string][] }[] = [
  {
    title: 'Navigate',
    keys: [
      ['1 2 3', 'Summary / Files / Notes'],
      ['j k', 'Next / previous file'],
      ['n p', 'Next / previous finding'],
      ['Esc', 'Close this'],
    ],
  },
  {
    title: 'Diff',
    keys: [
      ['u', 'Split ↔ unified'],
      ['w', 'Ignore whitespace-only changes'],
      ['d', 'Word-level diff'],
      ['f', 'Only files with open notes'],
      ['v', 'Mark the current file viewed'],
    ],
  },
  {
    title: 'Act',
    keys: [
      ['a', 'New review: a PR, an MR or a local branch'],
      ['r', 'Review (or re-review) with this PR’s depth and engine'],
      ['s', 'Sync with the forge'],
      ['c', 'Copy every open note'],
      ['t', 'Toggle light / dark'],
      ['?', 'This list'],
    ],
  },
]

export function ShortcutsOverlay({ onClose }: { onClose: () => void }) {
  return (
    <div className="modal-bg" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal shortcuts" role="dialog" aria-label="Keyboard shortcuts">
        <h2>Keyboard shortcuts</h2>
        <div className="content">
          {GROUPS.map((g) => (
            <div key={g.title}>
              <h3>{g.title}</h3>
              <dl>
                {g.keys.map(([k, what]) => (
                  <div key={k} className="shortcut-row">
                    <dt>{k.split(' ').map((one) => <kbd key={one}>{one}</kbd>)}</dt>
                    <dd>{what}</dd>
                  </div>
                ))}
              </dl>
            </div>
          ))}
        </div>
        <div className="foot">
          <button className="btn" onClick={onClose}>Close</button>
        </div>
      </div>
    </div>
  )
}
