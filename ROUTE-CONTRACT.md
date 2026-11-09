# Route contract

The HTTP surface and the `pm` command behind each endpoint are one table, and that
table ships as data another tool can read: **`route-contract.json`**, projected from
`src/domain-routes.ts` by `src/route-contract.ts` and committed next to the source.

## What the document carries

| Field | Meaning |
|---|---|
| `contractVersion` | Bumped when the shape changes |
| `generatedFrom` | The source file this is a projection of |
| `executorFlags` | Flags the executor itself may add: `--config`, `--json`, `--yes` |
| `defaultSharedFields` | Shared write fields (`actor`, `reason`, `idempotencyKey`, `dryRun`) a route accepts unless it declares its own |
| `hostOwnedFlags[]` | Flags every command accepts that this service never forwards, each with its reason |
| `unsupported[]` | Endpoints with no route, each with its reason (`submit-review`, `accept`, `return`, `dispatch`) |
| `unexposedCommands[]` | Commands the launcher offers that this service deliberately does not wrap, each with its reason |
| `fixedRouteCommands[]` | Commands the fixed routes run (the work-card payload and the quick note), which are not table entries |
| `routes[]` | One entry per endpoint, in table order |

Per route there is also `notes[]`: a difference from the command that no field
expresses, so it is stated rather than folklore. The evidence write carries one -
`pm` defaults `--actor` to `human` while the route requires the field, because an HTTP
caller has no terminal context and a wrong audit attribution is worse than a refusal.

Per route: `method`, `path`, `write`, `revision` (`required` / `optional` / `none`),
`ids` (identity prefix per path parameter), `patterns` (path-parameter shapes as source
text), `query[]`, `body[]` (each `name` / `flag` / `kind` / `required` / `values` /
`allowEmpty`, `deprecated`, `forbid`), `required[]` (names the route insists on beyond the
fields marked in `body`, shared ones included), `commands[]` (`cliPath`, `argvFlags`, and
`action` plus `body`/`required` for a
dispatching route), `shared[]` when the route narrows the default set, `notForwarded[]`
with reasons, and `unknownFieldHints` when a plausible field is refused with advice.

`contractDigest(text)` (exported alongside the projection) is the sha256 of the rendered
document, so an external record can quote exactly which contract it verified.
## Regenerating and checking

```sh
pnpm --filter @deepseek-ai/dsh-client-ui-pm contract        # rewrite route-contract.json
pnpm --filter @deepseek-ai/dsh-client-ui-pm contract:check  # fail when it is stale
```

Changing the table without regenerating fails the suite:
`tests/route-contract.client.spec.ts` compares the committed bytes with a fresh
projection, and also asserts that the manifest ships and exports the document.

## Who reads it

| Consumer | Use |
|---|---|
| `tests/command-flags.client.spec.ts` | Aligns the table with the real CLI in both directions, per command |
| Browser/workbench code | `commands[].cliPath` and `body[]` build the call; `unknownFieldHints` says what to send instead of a refused field; `unsupported[]` says what does not exist |
| Packaging and verification | Ship it (see `files` and the `./route-contract.json` export), and quote `contractDigest` in an export or verification record |
| `README.md` | Stays the human-facing description; this file is the machine-facing one |

## The alignment rules (each one turns the suite red)

1. **A declared flag the CLI rejects** - the reverse check reads `pm <cliPath> --help` and
   fails on any declared flag the command does not accept.
2. **A flag the CLI accepts that the route never declares** - the forward check subtracts
   the declared set, `executorFlags`, `hostOwnedFlags`, and justified `notForwarded`
   entries; anything left is a gap.
3. **A single-word command path** - `task execution-config set` must be compared as a
   whole; asking `argv[1]` alone queries a parent parser that accepts no options, which
   is an empty comparison that always passes.
4. **A stale document** - table edits without regeneration (and document edits without
   the table) fail the byte comparison.
5. **An unjustified omission** - a `notForwarded` entry with an empty reason, or one
   naming a flag the command does not accept, fails.

Each rule was shown to fail before it was trusted: a fabricated route with no CLI
command, a declared `--no-such-flag`, and an emptied `notForwarded` reason each turned
the gate red; the outputs are recorded in the task that introduced this contract.

## Choosing a status per refusal (example)

A route may refine the exit-code rule with `failureStatuses`: the command's error code
says more than its exit status. `POST /ui-pm/memory/:id/discard` answers `400` for
`REASON_REQUIRED` (the caller omitted something) and `422` for `NOT_A_CANDIDATE` (a
VERIFIED memory is deprecated, not discarded), while `REVISION_CONFLICT` stays `409`
through the exit-code rule. Unlisted codes keep that rule, and the route states the
mapping in its `notes[]` as well.

A mapping describes the command, not necessarily what a caller can provoke. **This
route validates the body first**, so a missing `reason` answers `400 INVALID_REQUEST`
and an empty one answers `400 INVALID_BODY` without running the command; the command's
own `REASON_REQUIRED` is kept as defence in depth and is normally unreachable here. A
reader comparing the document with observed behaviour should trust the note: the
refusal a caller actually gets is the route's, and both are `400`.

## Choosing a locator (example)

`PATCH /ui-pm/tasks/:id` with `action: check` locates one acceptance criterion and
requires **exactly one** of `criterionId` (forwarded as `--criterion-id`, the stable id)
or `index` (`--index`, kept for compatibility and marked `deprecated`). Sending both,
or neither, is a `400`: two names for one thing are never merged silently. The
deprecated text selector is listed in that command's `notForwarded` with its reason, so
a reader can see that the omission is a decision rather than an oversight.

**Prefer `criterionId`**: a file index shifts when criteria are reordered, an id does not.

## Closure: every CLI command has an answer

`tests/cli-coverage.client.spec.ts` reads the launcher's own command tree and requires
every leaf to be one of:

1. a command some route runs (`routes[].commands[].cliPath`);
2. a command a fixed route runs (`fixedRouteCommands[]`);
3. a command listed as deliberately unexposed (`unexposedCommands[]`) with a reason.

Both directions fail the suite: an offered command with no answer is a gap, and a
listed omission that is routed again (or that the launcher no longer offers) is stale.
The check closes the third side of the triangle with the table-versus-CLI alignment
(both flag directions) and the skill-versus-CLI check: CLI, routes, and skills can no
longer grow apart without a test saying so.

### How the tree is read, and the bounds that keep it honest

- **Probe:** the guard runs `pm --config <pm.toml> <path> --help` for each command it
  visits, depth-first from the root. It asks with the resolved config so the launcher
  answers exactly as it does for the service.
- **Parse:** only the group on the line directly under `positional arguments:` counts as
  subcommands. The same help text lists option enum values (`{human,ai,system}`);
  reading those as commands would wreck the check from the other side.
- **Depth cap `DEPTH_LIMIT = 4`:** the deepest command today is three words
  (`task criteria init-ids`), so the cap sits one word deeper than reality. A path that
  actually *reaches* the cap is an alarm, not a leaf: it means a child could exist
  unenumerated. That alarm is **red** - confirming the cap once is cheaper than
  silently missing commands. Raise the constant when the launcher nests deeper.
- **Command floor `MIN_COMMAND_COUNT = 40`:** the tree has 58 leaves today. A help-
  layout change or a depth cut loses many entries at once, so a floor well under the
  current count catches that shape while leaving room for a handful of genuine
  removals. Going below 40 fails the run; if the CLI ever shrinks on purpose, lower the
  floor deliberately in that same change.
- **Audibility:** every run prints the enumerated count, the deepest path length, the
  floor, the cap, and how many paths were cut off at the cap. A green run that found
  fewer commands than before is the failure this is built to prevent.

## Not covered

- Command semantics beyond flags: what a command does, its payload shapes, and exit codes
  other than the `3 -> 409 / 2 -> 422 / other -> 502` mapping the executor applies.
- Whether `pm` is installed at all: the contract lists commands; resolution of the
  launcher lives in `src/pm-layout.ts` (`PM_LAYOUT_NOTES`, `capabilities.layout`).
