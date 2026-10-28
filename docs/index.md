---
hide:
  - navigation
  - toc
---

<div class="sc-hero" markdown>

<h1>self<span>check</span></h1>

A local, read-only review workbench for pull requests, merge requests and local
branches — reviewed by the coding agent you already have.

[Get started](getting-started.md){ .md-button .md-button--primary }
[See it in action](media.md){ .md-button }

</div>

<video class="sc-video" src="assets/media/selfcheck-promo.mp4" poster="assets/brand/og-card.png" controls muted playsinline></video>

<div class="sc-grid" markdown>

<div class="sc-card" markdown>**:material-shield-check-outline: Never writes to a forge**
<p>GET-only HTTP, a git allowlist, a chmod read-only checkout. Notes stay on your machine until you copy them.</p></div>

<div class="sc-card" markdown>**:material-robot-outline: Any engine**
<p>Claude Code, Codex, Cursor Agent, the Anthropic API, or any OpenAI-compatible endpoint — Ollama included.</p></div>

<div class="sc-card" markdown>**:material-alarm: Wakeups**
<p>Point it at a repository and a time. New pull requests are reviewed before you get to them.</p></div>

<div class="sc-card" markdown>**:material-source-branch: Before you push**
<p>Review a local branch like a PR. Your working copy is read, never written.</p></div>

<div class="sc-card" markdown>**:material-account-voice: Ask and compare**
<p>Question any finding against the code. Get a second opinion from another engine and see where they agree.</p></div>

<div class="sc-card" markdown>**:material-chart-box-outline: A dashboard that answers**
<p>Activity, findings, engine performance and the developers you review — every number opens the PRs behind it.</p></div>

</div>

```bash
docker run --rm -p 127.0.0.1:7777:7777 -v ./data:/app/data ghcr.io/unchained-labs/selfcheck:latest
```
