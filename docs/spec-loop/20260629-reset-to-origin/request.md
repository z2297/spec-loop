# Request (verbatim)

> Add a new slash command that resets the local terminal to align with origin's main/master. This should reset all local commits, preffering to stash them with a meaningful message. This should be confirmed by the user when ran

## Controller restatement

Add one new slash command to the `spec-loop` plugin (a markdown command file under
`plugins/spec-loop/commands/`) that brings the local checkout into alignment with
origin's default branch (main or master). Local work must be **preserved, not destroyed**,
before the reset (the request says "preferring to stash them"), and the destructive action
must be **explicitly confirmed by the user** at run time.

## Run metadata
- run-id: `20260629-reset-to-origin`
- base_ref: `alpha`
- base_sha: `e590fc80dc14182fe8a5cdc3e7648cf0cebf48d4`
- flags: `--max-parallel 5` (default), `--risk-floor 1` (default)
