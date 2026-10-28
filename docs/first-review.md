# Your first review

1. Open [http://127.0.0.1:7777](http://127.0.0.1:7777).
2. Paste a link into the bar at the top of **Home** — or press ++a++ anywhere:
    - `https://github.com/owner/repo/pull/12`
    - `https://gitlab.com/group/project/-/merge_requests/34` or `gl:group/project!34`
    - a local repository: `~/src/app@feature` (see [Local branches](local-branches.md))
3. Leave *review right away* on and pick a depth, or keep the default.

The run bar shows each step — metadata, diff, read-only checkout, reading —
and the files the engine opens as it goes. When it finishes:

- **Summary** has the verdict, the summary, risks, test gaps, questions for
  the author and a checklist. The *Shaped by* line says what the review was
  told beyond the diff (repo rules, past dismissals).
- **Files** is the diff with every finding inline on its line. ++n++ / ++p++
  walk the findings.
- **Notes** lists them all, filterable by severity.

Resolve, dismiss or mark findings *won't fix*; edit them; add your own by
clicking a line number. **Copy** gives you markdown to paste into the real
review — selfcheck never posts anything.

Press ++question++ for every shortcut.
