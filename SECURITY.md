# Security policy

## What counts

selfcheck makes one promise above all others: **it never writes to GitHub or
GitLab, and the review engine cannot write to the code it reads.** The most
important reports are ways around that, for example:

- an HTTP request to a forge with a verb other than `GET`/`HEAD`;
- a `git` command outside the allowlist in `api/selfcheck/workspace.py`, or a
  push that reaches a remote;
- a review engine (CLI or API) writing to the checkout or the filesystem, or
  reaching the network beyond its model provider;
- an API-engine file tool reading outside the checkout (path traversal,
  symlinks);
- a forge token or API key ending up in a log, a URL, the database, the
  browser, or an engine's environment;
- a write to a local repository reviewed as a local branch.

selfcheck has no authentication and is meant to listen on loopback only.
Exposing it on a network is outside the supported setup, but tell us if a
default makes that easy to do by accident.

## Reporting

Please report privately through
[a GitHub security advisory](https://github.com/Unchained-Labs/selfcheck/security/advisories/new),
not a public issue. Include what you did, what happened, and the version
(`GET /api/status` or the release tag). You will get an answer within a few
days, and credit in the release notes if you want it.

## Supported versions

Fixes land on the latest release; there are no long-term branches.
