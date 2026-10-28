# Wakeups

A wakeup checks a repository on a schedule and reviews new pull requests as
they appear. Create one from **Wakeups**, from the alarm icon next to any
repository in the sidebar, or by pasting a repository URL into the add bar.

| setting | |
| --- | --- |
| **How often** | hourly, every 6 or 12 hours, daily or weekly |
| **At** | a time of day, in the server's timezone, for daily and weekly |
| **Depth / engine** | its own, or the defaults |
| **Only into branch** / **Only by authors** | filters |
| **Include drafts** | off by default |
| **Re-review on push** | also review tracked PRs whose head moved, at the wakeup's cadence |
| **At most N per check** | the rest wait for the next check, oldest first |

It is careful about spending:

- PRs already open when the wakeup is created are left alone unless you tick
  *also review the ones already open*.
- Runs queue behind the concurrency limit (2 at once by default).
- [Spend caps](configuration.md#spend-caps) pause automatic reviews.

**Open PRs** shows, for every open pull request, what the next check would do
and why it would skip the rest. **Check now** runs one immediately. Listing a
repository's pull requests is a `GET`, like everything else selfcheck sends.
A wakeup missed while selfcheck was not running fires as soon as it starts.
