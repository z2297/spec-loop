# Review Communication — source-specific handling and phrasing

Load this when you are about to reply to a reviewer: the response depends on who the reviewer is and where the thread lives.

## From a human partner

Trusted — implement after understanding. Still ask if the scope is unclear. Skip straight to action or a technical acknowledgment; no performative agreement.

## From an external reviewer (human or agent)

Run the skeptical check before implementing:

1. Is it technically correct for THIS codebase?
2. Does it break existing functionality?
3. Is there a reason for the current implementation (legacy, compatibility, a prior decision)?
4. Does it work on all supported platforms/versions?
5. Does the reviewer have the full context?

If the suggestion seems wrong, push back with technical reasoning. If you cannot easily verify it, say so and name what you would need: "I can't verify this without [X]. Should I investigate, ask, or proceed?" If it conflicts with a prior architectural decision, stop and discuss before implementing.

> **Inside a spec-loop run:** the "stop and discuss" and "ask the human" moments here are human gates governed by `spec-loop:escalation-gate` — classify the point through the gate (PROCEED + log, or surface at the wave boundary) rather than messaging the human directly. `spec-loop:verification-before-completion` is never overridden.

## Acknowledging correct feedback

State the fix, not the feeling: "Fixed — [what changed]", "[specific issue]. Fixed in [location]", or just fix it and let the diff speak. Skip gratitude and skip agreement adjectives; the code shows you heard the feedback, and "you're absolutely right" adds nothing a reviewer can act on.

## Correcting your own pushback

If you pushed back and turned out to be wrong, say so factually and move on: "You were right — I checked [X] and it does [Y]. Implementing now." or "Verified; you're correct. My initial understanding was wrong because [reason]. Fixing." No long apology, no defense of why you pushed back, no over-explaining.

## GitHub in-thread replies

When replying to an inline review comment on GitHub, reply **in the comment thread**, not as a top-level PR comment:

```bash
gh api repos/{owner}/{repo}/pulls/{pr}/comments/{id}/replies \
  -f body="Fixed in <sha>. <what changed>"
```

`{id}` is the review comment's id. A top-level comment loses the thread context and forces reviewers to hunt for what you answered.
