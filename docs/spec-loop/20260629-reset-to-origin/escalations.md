# Escalations — 20260629-reset-to-origin

## [intake] Iron Council objects: "stash the commits" cannot preserve local commits   (status: OPEN)
- Trigger: council-objection
- Council verdict: OBJECT (2/5 object, both SAFETY — guardian + skeptic; architect & historian also flagged this as a concern)
- Objecting members:
  - guardian (SAFETY) — `git stash` saves only working-tree/index changes, NOT commits; `git reset --hard origin/<default>` orphans local commits (reflog-only, GC-able). The stated intent to preserve them is not met.
  - skeptic (SAFETY) — "reset all local commits, preferring to stash them" is category-confused; the mechanism to preserve commits is a backup branch/tag, not stash.
- The decision: How should existing **local commits** be preserved before the hard reset?
- Options:
  1. Backup ref + stash — (RECOMMENDED DEFAULT) before resetting, create a durable backup branch/tag of HEAD (recoverable via normal git), AND `git stash push -u` the uncommitted working tree, both with a meaningful timestamped message. Honors "preserve, don't destroy."
  2. Stash only (literal) — stash uncommitted changes only; local commits are discarded (recoverable only via `git reflog` for ~90 days). Matches the literal wording but loses committed work.
  3. Backup ref only — create the backup branch/tag for commits; refuse to run when the working tree is dirty (no stash). Simplest, but blocks on uncommitted changes.
- If unanswered: block the run (intake council-objection).
- Answer: <pending>

## [intake] Iron Council objects: ambiguous target / blast radius of the reset   (status: OPEN)
- Trigger: council-objection
- Council verdict: OBJECT (SAFETY — skeptic; guardian concurred on edge handling)
- Objecting members:
  - skeptic (SAFETY) — "align with origin's main/master" has two divergent readings: (A) hard-reset the CURRENT branch to origin/main vs (B) switch to the default branch and align it. On THIS repo the current branch `alpha` is 31 commits ahead of origin/main (verified) but in sync with origin/alpha; reading (A) would destroy 31 already-published commits.
- The decision: Which branch should the command reset, and to what?
- Options:
  1. Switch to default branch — (RECOMMENDED DEFAULT) checkout the default branch (main/master) and hard-reset IT to origin/<default>; leave the branch you were on (and its commits) untouched. Never destroys the feature branch you're sitting on.
  2. Reset current branch to origin/<default> — hard-reset whatever branch you're on onto origin/main (the literal "reset all local commits" reading). On `alpha` today this moves 31 commits to the backup ref from Q1.
  3. Reset current branch to its OWN upstream — align the current branch to origin/<current-branch> (e.g. origin/alpha), not main. Common "discard my local changes, match the remote" intent, but does not target main/master as the request says.
- If unanswered: block the run (intake council-objection).
- Answer: <pending>
