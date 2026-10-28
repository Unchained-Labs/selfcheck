# The dashboard

**Home** answers *how is this going?* for the date range you pick (7 days to
all time), and every number opens the reviews behind it.

- **Since you were last here** — new pull requests (and how many a wakeup
  brought), reviews that finished, new blockers and majors, failed runs.
- **Headline numbers** — reviews run, findings raised, PRs tracked, findings
  per review, median review time, success rate, noise and spend, each with its
  change against the previous period of the same length.
- **Activity** — a year of days, by reviews, findings or PRs added, with
  streaks. Click a day for its reviews.
- **Reviews per day** stacked by engine, and **cumulative** totals.
- **Severity**, **category**, and **what happened** to the findings.
- **Performance** by engine, depth or trigger: success rate, median and p90
  time, findings and serious findings per review, noise and average cost.
- **Developers** you review — PRs, findings and serious findings per PR, how
  often *needs work*, lines changed — and **who gets the reviews**: assignees
  and requested reviewers.
- **When you review** — weekday by hour.

## Noise

*Noise* is the share of the findings you made a call on that you
**dismissed** as not real. It is the closest thing selfcheck has to a false
positive rate, per engine and per depth, and it is what
[learning](reviewing.md#learning-from-your-decisions) drives down.
