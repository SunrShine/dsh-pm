<h1 align="center">dsh-pm</h1>

<div align="center">

**English** · [简体中文](README.zh-CN.md)

</div>

<p align="center"><b>Turn DSH (DeepSeek Harness) workspace and session state into an org-mode work library of projects / tasks / quick notes / proposals / memory — with Org as the single source of truth</b></p>

<p align="center"><b>Sessions expire. Org files do not.</b></p>

<div align="center">

[Usage](USAGE.md) · [Screenshots](docs/screenshots.md) · [skill](skill/pm/SKILL.md) · [Changelog](CHANGELOG.md) · [MIT](LICENSE)

</div>

<p align="center">
  <img src="https://img.shields.io/badge/license-MIT-blue?style=flat-square" alt="License: MIT">
  <img src="https://img.shields.io/badge/python-3.11%2B-blue?style=flat-square" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/org--mode-6f42c1?style=flat-square" alt="Org-mode">
  <img src="https://img.shields.io/badge/runtime__status-unknown-lightgrey?style=flat-square" alt="runtime_status: unknown">
</p>

The problem it solves: session records are scattered across several DSH data roots — sessions have **no tags and no tidy history**, so "what did I actually do" can only be answered by titles or hand-written notes (and the title is often just half a sentence such as "You are working in the …"), and finished work is easy to lose.
dsh-pm treats sessions strictly as **read-only input** and distils them into "work cards", while the things **a human actually maintains** — tasks, acceptance criteria, evidence, decisions — live in your own Org files: readable, diffable, durable, with no database or cloud service involved.

## Features

- **Org is the single source of truth.** Projects / tasks / quick notes / proposals / memory are all `.org` text: readable, diffable, durable, and free of databases or cloud services.
- **Sessions are read-only input.** Work cards are derived from the DSH projection; the tool never pretends to know "the facts"; the run status is always `unknown` — what we read is a **snapshot** DSH wrote down, and the snapshot carries no "is it still running right now" signal, so we do not guess.
- **Checkable acceptance criteria + evidence.** Create criteria with `pm task create --criterion`; attach evidence with `pm task evidence add --kind/--result` (write `info` when you do not know — never guess `pass`); **only a human writes `DONE`**.
- **AI can propose, never approve.** `pm proposal create` only writes a proposal; a human runs `pm proposal approve` to create real tasks.
- **Three skills teach your agent**: `pm` / `pm-evidence` / `pm-planning` — installed into DSH with a single `pm skill install`.
- **A built-in web workbench** (vanilla JS/CSS, no build step): work cards / inbox / task board (drag and drop + subtask DAG) / proposals / memory / project brief; **or just use the CLI + MCP**.
- **One-command plugin install**: `dsh plugin add github:SunrShine/dsh-pm` (with a profile: `dsh plugin --profile <profile> add github:SunrShine/dsh-pm`).

- This README is **self-contained**: with nothing but this repository you can install it, run it and understand it.
- The internal design / convention / acceptance / memo records are **not published with the repository**, so this README never links to them; where they are mentioned, they are called "internal records (not published)" together with the command and the date.
- The skills shipped to agents: [skill/pm/SKILL.md](skill/pm/SKILL.md); the details of each skill live next to it under `references/` (loaded on demand instead of bloating the main file).

> Status: **v0.3 series** (latest release **v0.3.1**, 2026-10-22); the repository is **public** at [github.com/SunrShine/dsh-pm](https://github.com/SunrShine/dsh-pm).
> Anything unfinished is listed under [roadmap / not done](#roadmap--not-done) at the end — never written up as done.

## UI

The screenshots come from a **self-built demo library (pure fake data)** (**dark mode**: `localStorage["pm-theme"]="dark"` + `prefers-color-scheme: dark`): the library only contains the two example projects `demo-app` / `demo-lib` and entries such as "Example task: …", and
**no real project name, real path or real session ID** (verifiable: grepping the page text for a real project key / home path / `session-<uuid>` yields 0 hits).
To reproduce:

```bash
pm init --root ~/dsh-pm-demo --no-git          # create the skeleton (then delete the project dirs discovered from your real environment)
printf 'library = "~/dsh-pm-demo"\n' > ~/dsh-pm-demo/pm.toml
pm project create demo-app --config ~/dsh-pm-demo/pm.toml --title "Demo project"
pm project create demo-lib --config ~/dsh-pm-demo/pm.toml --title "Demo library"
# Generate the rest of the sample data with pm task create/transition, pm capture, pm memory add, pm proposal create;
# when starting a throwaway instance point these env vars at the fake library: DSH_UI_PM_PM_BIN=…/bin/pm  DSH_UI_PM_CONFIG=~/dsh-pm-demo/pm.toml
```

Once installed into DSH, the workbench gets its data and routes from DSH under `/ui-pm/*`. Here is one representative image (the workbench):

![Workbench: capture box + pinned quick notes + pending proposals](assets/screenshots/workbench.png)

**More screenshots live in [docs/screenshots.md](docs/screenshots.md)** (7 in total: sidebar entry / workbench / project brief / task board DAG / inbox / task history / review).

The workbench is a bundled static frontend (`frontend_impl/`: vanilla JS/CSS, no build step). Its layout (in words):

- **Left sidebar**: project tree (projects with a directory in the library ∪ projects that only appeared inside DSH) and the session list, collapsible; the selected project drives the middle pane.
- **Middle pane**: workbench (work cards + the "quick note" card on top + the pending-proposals banner) / project board (5 columns, horizontally scrollable, cards can be dragged to a status column) / tasks, review and memory pages; a task card expands to show its subtasks and DAG.
- **Right pane**: the detail panel, width-draggable; inbox detail shows the original text (read-only), addenda, revisions (old values kept), history and pin state; task detail holds acceptance-criteria ticking, execution config and handoff.
- **Inbox**: the quick-note list with triage actions (archive / snooze / merge / dismiss / save as note); rows show addendum/revision counts and pin state.

No amount of prose replaces a real image (the ones above are actual captures); **the ASCII architecture diagram is in [Architecture](#architecture)**.

## Quick start

**Which half works standalone**: `bin/pm` (CLI + MCP) and the three skills (`skill/`) **need no DSH host** — if all you want is "give my agent its own org memory library", this layer is enough;
the **plugin half** (web workbench / `/ui-pm/*` routes / `lib/`) needs a **DSH host** — see **Requirements** below for the minimum version — and the `@deepseek-ai/dsh-*` packages in `package.json` `devDependencies` are only needed when developing that half.
**Requirements for the plugin half**: DSH ≥ **`0.2.1-alpha.1`** (this repository is developed and verified against that version; older versions are untested and may fail to load). The CLI and the three skills do not need DSH.

For a task-oriented walkthrough see **[USAGE.md](USAGE.md)** (up and running in 30 seconds → teach your agent → a day's workflow → with DSH → multiple libraries/instances → FAQ → command cheat sheet).

### A. Python backend (CLI / MCP)

**No installation needed inside this repository**: `bin/pm` puts `src/` on `PYTHONPATH` and runs directly; **zero third-party dependencies** (Python standard library only).

```sh
git clone https://github.com/SunrShine/dsh-pm && cd dsh-pm

./bin/pm --help                                            # all commands
./bin/pm scan                                              # read-only: current DSH projects / work cards
./bin/pm init   --root ~/my-work-memory --project demo01   # create the library skeleton (human files are only created when missing)
./bin/pm project list --json                               # projects in the library (with a directory ∪ seen only in DSH)
./bin/pm mcp                                               # run as an MCP server (stdio) for DSH
./bin/test                                                 # run the tests (see "Development and verification")
```

You can also install it from GitHub with `pipx` (**PyPI is not published yet; it is planned**):

```sh
pipx install git+https://github.com/SunrShine/dsh-pm
```

`scan` / `ui-cards` read your local DSH data roots (default `~/.dsh`, override with `--instance` / `--dsh-home`);
by default a write command only trusts the library named by an explicit `--config`, otherwise it demands `--yes`, which prevents accidental writes to your real library (see item 7 of the [honesty contract](#honesty-contract)).

**Config lookup order** (first match wins): `--config` > `DSH_UI_PM_CONFIG` > `PM_CONFIG` > `./pm.toml` > `~/.dsh-pm/pm.toml` > built-in default.
Finding none of them **does not fail**: the built-in defaults are used to auto-discover data roots (`pm scan` will honestly report "no data roots").

### B. As a DSH plugin (web workbench)

Installation goes through **GitHub** (package name `dsh-pm`):

```sh
dsh plugin add github:SunrShine/dsh-pm
# with an explicit profile:
# dsh plugin --profile <profile> add github:SunrShine/dsh-pm
```

> ⚠️ **The npm package with the same name, `dsh-pm`, is not this project** (the name is taken by someone else).
> So **do not** use a bare `dsh plugin add dsh-pm` — that installs their package. This project only offers the GitHub install path.

**Two things to watch when opening the workbench** (we hit both while taking screenshots; neither is related to dsh-pm):

1. **You must open the URL that carries a token.** When DSH starts it prints a line
   ```text
   dsh web: http://127.0.0.1:<port>/?token=<token>
   ```
   and normally opens it in your browser — just use that address. If the browser did not open (SSH / headless / `--no-open`), pull the line out of the log:

   ```sh
   dsh web --no-open > /tmp/dsh-web.log 2>&1 &     # or your usual startup, as long as the log is kept
   grep -o "http://127.0.0.1:[0-9]*/?token=[^ ]*" /tmp/dsh-web.log | tail -1
   ```

   Opening `http://127.0.0.1:<port>/` without the token is rejected:
   `dsh web authentication required; reopen the URL printed by dsh web.` (HTTP 401).
   The token is regenerated on every start, so fetch it again after each restart.

2. **If this instance has no model key configured yet, the first open shows DSH's own model-configuration modal** (titled "Add an API key to get started"):
   it asks for a model API key and is **unrelated to dsh-pm**; click **"Configure later"** to dismiss it and the workbench appears.

- Compatibility: **no `@deepseek-ai/dsh*` version dependency is declared in the package** (no peer version constraint, so DSH's compatibility check cannot block it); verified against **DSH `0.2.1-alpha.x`** (`0.2.1-alpha.1` in practice).
- Behaviour details once installed (route prefix `/ui-pm/*`, the frontend shipped inside the package, `DSH_UI_PM_APP_DIR` to relocate it) are in the source; end-to-end install re-verification is still in progress — see [roadmap / not done](#roadmap--not-done).

## Core concepts

| Concept | What it is | Where it lives | State machine / rules |
|---|---|---|---|
| **Project** | A unit that can be composed of several DSH workspaces | `projects/proj-<key>/project.org` (human) | Identity is `:ID:`; the brief has six sections: goal / scope / non-goals / acceptance criteria / milestones / risks |
| **Task** | A concrete piece of work with acceptance criteria | `projects/proj-<key>/tasks.org` | `TODO → NEXT → DOING → REVIEW → DONE`; `DONE` **only a human writes**, AI stops at `REVIEW` |
| **Quick note (inbox)** | Jot one line down first, triage later | `inbox-human-<period>.org` / `inbox-ai-<period>.org` (human weekly / AI monthly); `inbox.org` is a generated view | `CAPTURED → TRIAGE → TASK_PROPOSED → TASK_CREATED`; archive/snooze/merge/dismiss/save-as-note; **archiving is time rotation, not file movement** (the status stays in the entry's own period file); **the original text is read-only**, addenda are appended and revisions keep the old value |
| **Proposal** | An AI plan waiting for human approval | `proposals.org` | `PENDING → APPROVED / REJECTED`; **an unapproved proposal never creates a real task** |
| **Memory** | Facts / decisions / gotchas an AI may use as context | `memory/{facts,decisions,gotchas}.org` + `memory-candidates.org` | `CANDIDATE → VERIFIED` (**only a human** can verify) → `DEPRECATED` (history kept) |
| **Work card** | A read-only snapshot of one DSH session | Not persisted (output of `pm scan` / `ui-cards`) | Says what the cache recorded, never that a session is running (see the [honesty contract](#honesty-contract)) |

> **Memory is flat by decision (2026-10-18).** Memories are separated only by **status** (`CANDIDATE → VERIFIED → DEPRECATED`)
> and **type** (fact / decision / gotcha), all maintained by hand; the `L1/L2/L3` layer field is a **reserved capability**
> — present in the code, not shown in the UI, not used day to day ([`内部记录（未随仓库发布）)).
> So don't delete it as dead code, and don't wire it into the UI or the injection path without a new decision.

> **The inbox is split by origin and rotates by time (2026-10-22).** The sources of truth are
> `inbox-human-<period>.org` (human writes, default **weekly**, e.g. `inbox-human-2026-W43.org`) and
> `inbox-ai-<period>.org` (AI / MCP writes, default **monthly**, e.g. `inbox-ai-2026-10.org`).
> `inbox.org` is an **auto-generated summary view (read-only)**: the current human + AI files inlined, older periods listed as links only;
> `pm inbox render` writes it and `pm inbox render --check` verifies it (a stale view exits 1).
> **Archiving is time rotation, not file movement**: a processed entry keeps its status (`ARCHIVED` / `TASK_CREATED` / …) in the period file where it was written,
> so "what happened in week 43" stays in `inbox-human-2026-W43.org`.
> An old library keeps its single `inbox.org`; `pm inbox migrate` (`--dry-run` by default, `--write` backs the file up first) splits it by origin and period.
> The rotation granularity is `[inbox] human_mode` / `ai_mode` in `pm.toml`: the code default is `single` (an old library keeps working unchanged), and the real library used for verification is configured as `weekly` / `monthly`.
> Audit trail and CAS are untouched by the split: an entry is still addressed by `:ID:`, and the write lands in whichever file currently holds it.

Every **write** goes through the same path (`entities.apply_change`): check the revision first (CAS, so nobody else's edit is overwritten),
replace the whole file atomically, record an audit entry on the item, and write only once when the same submission is repeated; a revision mismatch returns `exit 3` and writes not a single byte.

### Project statistics shared across multiple DSH instances (legacy)

> **This is a legacy feature**, kept for "several DSH instances running on one machine" (for example a stable and a preview install).
> If you run a single DSH, skip this section.

Multiple DSH instances keep their data separately: each has its own workspace list and its own session numbering, so the same number can mean two different things in two instances. dsh-pm therefore identifies a session by **instance id + session id**
(the `id` of `[[instance]]` in the config is that instance id). That way sessions from several instances can be counted into one project without being mixed up.

```toml
[[instance]]
id   = "default"    # instance id: only together with the session id does it identify a session uniquely
path = "~/.dsh"
role = "work"       # purely a usage label (work = daily, explore = exploration); it does not affect the statistics

[[instance]]
id   = "preview"    # e.g. the data directory of another DSH version (or a preview build)
path = "~/.dsh-preview"
role = "explore"
```

- `pm scan --instance preview`: look at that one instance only, without mixing in sessions from others.
- `pm skill install`: by default installs **all** skills shipped with the tool, and only into **the instance currently running** —
  skills are read per instance, so installing into another instance is invisible to this session; add `--all-instances` to install into every configured instance.
  Use `--skill <name>` for just one; use `pm skill path` to list the names and source directories first. Re-running is **idempotent** (already-installed ones are left untouched).

## Commands and interfaces

### CLI (measured from `./bin/pm --help`, 2026-10-23)

20 top-level commands: `scan`, `ui-cards`, `api`, `init`, `render`, `summary`, `log`, `capture`,
`inbox`, `task`, `proposal`, `memory`, `project`, `workspace`, `index`, `recall`, `hook`, `prompt`, `mcp`, `skill`.

| Command | Common subcommands | What it does |
|---|---|---|
| `pm scan` | `--all --limit 0`, `--instance`, `--json` | Read-only look at DSH: cards / to-dos / how fresh the cached records are |
| `pm ui-cards` | `--project`, `--limit`, `--dsh-home` | The fixed JSON shape the plugin consumes (`schemaVersion=ui-cards-v1`) |
| `pm api` | `--query` | The unified envelope (pm-api-v2) read entry point |
| `pm init` / `pm render` | `--root`, `--write`, `--dry-run` | Create the library skeleton / generate `generated/**` (dry-run by default) |
| `pm summary` | `queue`, `set` | Work-card summaries (a human summary wins; AI never overwrites it) |
| `pm log` | `--session`, `--project --missing` | Read session logs and distil material (print only) |
| `pm capture` | `--project`, `--json`, `--dry-run` | Append a quick note; **routed by origin**: CLI (human) → `inbox-human-<period>.org`, MCP/AI → `inbox-ai-<period>.org` |
| `pm inbox files` | `--json` | List the inbox source files (human / AI rotation files, plus a legacy single `inbox.org` if the library has not been migrated) |
| `pm inbox render` | `--check`, `--json` | Generate the read-only `inbox.org` summary view; `--check` only verifies it (stale → exit 1, nothing written) |
| `pm inbox migrate` | `--write`, `--json` | Split an old single `inbox.org` by origin/period (**dry-run by default**; `--write` backs up the old file first, then regenerates the view) |
| `pm inbox` (triage) | `list` (`--status`, `--origin human\|ai`) `/ archive/snooze/merge/note/dismiss/set-status/annotate/edit/history/pin/unpin` | Inbox: triage + append addenda + explicit revision (old value kept) + history + pinning; every action addresses the entry by `:ID:` and writes into the file that currently holds it |
| `pm index` / `pm recall` | `--rebuild`, `--dry-run` / `--query`, `--scope`, `--type`, `--limit` | Memory content index (derived, `<library>/.local/index.sqlite`) / recall with the default scope (VERIFIED only) |
| `pm hook` / `pm prompt` | `session-start`, `recall`, `install` / `get`, `list`, `set`, `exports` | DSH hook injection (read-only, budgeted, off with one switch) / per-project initial prompt data (CAS + audit) |
| `pm task` | `list/show/create/transition/check/evidence/criteria/init-ids/dag/import-team/execution-config/link-session/unlink-session/handoff` | Tasks, acceptance-criteria ticking + stable criterion IDs, evidence, DAG, AI execution config and handoff (**no dispatch**) |
| `pm proposal` | `list/show/create/approve/reject/revise` | Proposals: only approval creates tasks; revising keeps the id and re-anchors the source revision |
| `pm memory` | `candidates/list/context/add/verify/deprecate/discard` — plus the **reserved** layer commands `scene/extract/condense/distill/stale` | Candidate → human verification → context bundle (VERIFIED only); the reserved five belong to the L1–L3 layer capability (see the note under Core concepts) |
| `pm project` | `list/create/context/brief get/brief set` | Unified project list, scaffold a directory, project brief (read / explicitly rewrite one section) |
| `pm workspace` | `list/context` | Workspaces of a project; memory + sessions (observation) of a workspace |
| `pm mcp` / `pm skill` | `path`, `install` (`--skill NAME`, `--all`, `--all-instances`) | MCP server (stdio) / list or install the skills shipped with the tool |

### HTTP routes (provided by the plugin host)

The route list is defined by the plugin's route table (`domain-routes.ts`); the endpoints the web frontend actually calls are below
(check method: the call sites in `frontend_impl/app.js`. As of 2026-10-12: **34 domain routes + `cards`/`capture`/`capabilities`,
plus 4 `UNSUPPORTED_ENDPOINTS`**; source: internal frontend review records, not published with the repository):

| Domain | Endpoints |
|---|---|
| Cards / host | `GET /ui-pm/cards`, `GET /ui-pm/capabilities`, `GET /ui-pm/events`, `POST /ui-pm/capture` |
| Inbox | `GET /ui-pm/inbox`, `GET /ui-pm/inbox/:id`, `POST /ui-pm/inbox/:id/{archive,snooze,merge,note,dismiss,annotate,edit,pin,unpin}` |
| Tasks | `GET /ui-pm/tasks`, `GET /ui-pm/tasks/:id`, `GET\|POST /ui-pm/tasks/:id/execution-config`, `POST /ui-pm/tasks/:id/{link-session,unlink-session}`, `GET /ui-pm/tasks/:id/handoff` |
| Proposals | `GET /ui-pm/proposals`, `GET /ui-pm/proposals/:id`, `POST /ui-pm/proposals/:id/{approve,reject,revise}` |
| Projects / workspaces | `GET\|POST /ui-pm/projects`, `GET /ui-pm/projects/:id/context`, `GET\|POST /ui-pm/projects/:key/brief`, `GET /ui-pm/workspaces`, `GET /ui-pm/workspaces/context` |
| Memory | `GET /ui-pm/memory`, `POST /ui-pm/memory/:id/deprecate`, `POST /ui-pm/memory-candidates/:id/{verify,merge,discard}` |
| **Not implemented (explicitly rejected)** | `POST /ui-pm/tasks/:id/dispatch`, `submit-review`, `accept`, `return` (4 entries in `UNSUPPORTED_ENDPOINTS` with reasons; see [roadmap](#roadmap--not-done)) |

Write endpoints require the revision you saw (`expectedRevision`; the brief uses `expectedDigest`)
and return the same five fields `entityId / revision / source / observedAt / auditEventId`;
a revision mismatch → `409` (`exit 3` in the CLI).

### MCP tools (`pm mcp`, stdio)

11 tools (measured from `TOOLS` in `src/pm/mcp.py`, 2026-10-23):
`projects`, `cards`, `card`, `summary_queue`, `session_log`, `set_summary`, `capture`,
`pm_recall`, `task_add`, `proposal_draft`, `render`.

- `task_add` can only create `TODO`/`NEXT`: writing `DONE`/`CANCELLED` is explicitly rejected (`DONE_REQUIRES_HUMAN`).
- `proposal_draft` **only creates a proposal, never a real task** (stated in the tool description).
- `capture` also returns those five fields and records an audit entry; because it runs as MCP (`source=mcp`) it appends to the **AI** inbox file (`inbox-ai-<period>.org`), never to the human one.

## Honesty contract

This is where the project spends most of its effort: **rather write "I do not know" than make something up**.

1. **The run status is always `unknown`**. What we read is only a read-only snapshot written by DSH, and it carries no live signal for "is this session still running right now"; therefore no UI or field may claim a session is "running"; `runtime_status` is always output as `unknown`.
2. **Observation ≠ run status.** A card's `observation` only describes "what the cache recorded and how fresh it is": `BUSY / STALE_BUSY / RECENT / IDLE / CLOSED / ARCHIVED / EMPTY`.
3. **`CLOSED` ≠ `DONE`**; `goal.phase = complete` in the cache only displays as "finished", which is not acceptance.
4. **Missing data is written as missing**: no summary reads "not established", no workspace reads "not connected"; an empty object never poses as a healthy state, and an empty library or empty payload is a legal output.
5. **`DONE` is written by humans only.** An AI submission can only reach `REVIEW`; `DONE` is terminal and the entry layer rejects AI (`task_add` over MCP included).
6. **Unapproved proposals create no tasks.** `proposal create` only writes `proposals.org` (marking the source inbox `TASK_PROPOSED`); `approve` creates the real task and marks the inbox `TASK_CREATED`.
7. **Write gate and report-only deletion**: without an explicit `--config`, a write command must carry `--yes`; `pm render` is dry-run by default and only `--write` persists; files under `generated/` that are no longer part of this plan are marked `orphan` and **only reported, never deleted** (auto-deleting when a data source is temporarily unavailable would destroy rebuildability). **Conversation bodies are not printed by default**: text coming from prompts requires an explicit `--show-prompt`.
8. **Fake-green protection** (guarding not the features but "verification itself lying"):
   - `scripts/verify-dsh-plugin.sh` fingerprints `inbox.org`, `overrides.org` and `projects/**` (file set + per-file sha256) at the start and end of acceptance; any change/addition/deletion FAILs; `--self-test-human-guard` proves on a temporary copy that this line **really does FAIL**.
     **Known gap**: the fingerprint still names the single `inbox.org`, so after the multi-file split the human truth in `inbox-human-*.org` is **not** covered by it yet (see [roadmap](#roadmap--not-done)); do not read a PASS as "the human inbox was not touched".
   - Harness injection (stubbing the frontend) must have hard-assertion anchors; silent no-ops are forbidden, and the guard itself ships negative self-tests (born from a real fake-green incident).
   - A broken domain module (ImportError/SyntaxError) must not stop the whole CLI; the other domains still register.
9. **Read-only originals + append-only addenda + explicit revision**: a captured quick note is never rewritten in place; addenda are appended to the body (with actor/time/rev); when a rewrite is genuinely needed it goes through `pm inbox edit --reason`, and **the old value stays verbatim in the entry**.
10. **The project brief has exactly one write entry point**: `pm project brief set`, using a **whole-file sha256 CAS**, replacing only the section you name, and completing the `:LOGBOOK:` audit and `:PM_BRIEF_UPDATED:` in the same atomic write; `--actor` is mandatory and no automated flow or import may call it.

## Architecture

```
        DSH data roots (~/.dsh*/storages: workspace.json + session cache)
                     │  read-only (no bodies exported, no credentials read)
                     ▼
   src/pm/sources/ ──► scan.py (group/filter/sort) ──► model.py (Agent/Project/Todo/Goal + observation)
                     │                                        │
                     │                                        ▼
                     │                              render/ (console/table/org/write plan)
                     │                                        │
                     │                                        ▼
                     │                        generated/** + library-root index.org (rewritten wholesale; contents carry no current time)
                     │
                     ▼
   ┌──────────────────────── work-memory library (Org is the single source of truth) ────────┐
   │ inbox-human-*.org + inbox-ai-*.org (+ generated inbox.org) │ projects/proj-*/{project,tasks,memory}.org │
   │ proposals.org │ memory/*.org │
   └────────────────────────────────────────┬────────────────────────────────────────────────┘
                                            │  entities.apply_change (revision check + atomic write + audit + dedup)
                                            ▼
        pm CLI (16 top-level commands) ◄──────► pm MCP server (10 tools, stdio)
                    │                              │
                    └───────► pm ui-cards (stable JSON) ◄───────┘
                                     │
                                     ▼
             DSH plugin (host half + browser half; /ui-pm/* routes + capabilities)
                                     │
                                     ▼
                       frontend_impl/ static workbench (no build, vanilla JS/CSS)
```

## Repository layout

```
bin/pm                      zero-install launcher (sets PYTHONPATH itself)
bin/test                    test entry point (unittest, zero third-party dependencies)
config/pm.toml              data roots, library path, merge rules, noise filtering
src/pm/
  model.py                  Agent / Project / Todo / Goal + the observation state machine
  scan.py                   grouping, filtering, sorting
  sources/                  read-only layer over ~/.dsh*/storages
  entities.py               the common implementation of every write (revision check + atomic write + audit + dedup)
  inbox.py / inbox_ops.py   inbox parsing and actions (triage / addendum / revision / pin), across all inbox files
  inbox_files.py            inbox file layout: per-origin/per-period naming, aggregation, the generated view, migration
  tasks.py                  task model (state machine / acceptance criteria / DAG / import-team)
  proposals.py              proposal model (create / approve / reject / revise)
  memory.py                 memory candidate → VERIFIED → context bundle
  projects.py               project list / scaffold a directory / brief (read + rewrite one section)
  execution.py              execution config / session linking / handoff (describes readiness only, never dispatches)
  ui_cards.py               the JSON shape the plugin consumes
  mcp.py                    MCP server (stdio, 10 tools)
  render/                   org / table / console / write plan
  scaffold.py               human-file templates
skill/pm/SKILL.md           the skill for agents
frontend_impl/              web workbench (vanilla JS/CSS, no build step)
scripts/                    acceptance and verification scripts (verify-*.sh / *.py; read-only, re-runnable)
tests/                      unit and integration tests + self-built DSH fixtures
```

> The work-memory library is **not shipped with the repository** either: create your own with `pm init --root <your dir>` (human files are only created when missing).

> The internal design / convention / acceptance / memo records are **not published with the public repository**, so this README does not reference them.

## Development and verification

### Unit / integration tests

```sh
./bin/test                     # everything (unittest, standard library)
```

**Measured on this machine on 2026-10-14**: `Ran 814 tests` → `OK`. (The number moves with commits.)

### Independent acceptance (plugin + per-module conventions)

```sh
./scripts/verify-dsh-plugin.sh                 # strict mode: read-only, re-runnable, no browser and no service by default
./scripts/verify-dsh-plugin.sh --with-host     # additionally start an isolated instance to check the plugin's /ui-pm/cards
./scripts/verify-dsh-plugin.sh --self-test-human-guard   # prove on a temporary copy that the "human files" fingerprint line FAILs
./scripts/verify-dsh-plugin.sh --interim       # while assembly is incomplete: missing pieces are SKIPs
```

**Measured on this machine on 2026-10-14 (strict)**: `PASS=314 FAIL=0 SKIP=0 WARN=12` (default) — the counts move with every fix, so always re-run and quote the date.
The remaining WARN is a human-confirmation item: grepping `lib/client.js` proves the code was compiled in, not that a real click in a browser works.

Internal acceptance records (**not published**) once recorded an early round of `PASS=61 FAIL=0 WARN=3` (63 with host) when `./bin/test` had 510 tests.
Whenever you quote a number, bring its date and your own re-run.

### Verification that needs a real browser

The following scripts dispatch real events over CDP (headless Chrome); without a browser in the environment they are not reached:

| Script | What it verifies |
|---|---|
| `scripts/verify_dag_cdp.mjs` | Real SVG rendering of the project task DAG + lazy loading of expanded state + centred scrolling |
| `scripts/verify_frontend_finish.py` | Frontend finishing acceptance (brief editing / proposal revision / what is shown after approval) |
| `scripts/verify_board_series.py` | Board column merging, 5-column rendering, substatus chips |
| `scripts/verify_inbox_cards.py` | Inbox cards (addendum counts / pinning / opening the detail) |

The other `scripts/verify_*.py` either read code only or verify against a temporary library; no browser is needed (the scripts are read-only and write temporaries under `mktemp -d`).

### Contributing

- Open an issue describing the change first; **the tests must be green** and fake greens are not allowed (see item 8 of the honesty contract).
- Human files must be written through `entities.apply_change` (CAS + audit); do not hand-write around it.
- New JSON fields are treated as append-only; update `schemaVersion` and the internal record alongside.

## Roadmap / not done

**Explicitly planned or in progress, and not usable today**:

| Item | Status | Notes |
|---|---|---|
| UI screenshots | **Done (demo library)** | Captured from a self-built demo library `~/dsh-pm-demo` (pure fake data; no real project names/paths/session ids); reproduce with the commands in [UI](#ui) |
| One static check in the acceptance script mis-firing | **Being fixed** | The single FAIL in the gate is the check itself being too rigid (anchor matching), not a functional defect |
| Human-file fingerprint vs. the multi-file inbox | **Planned** | `scripts/verify-dsh-plugin.sh` (C15) still fingerprints only `inbox.org`; the human inbox truth is now `inbox-human-*.org` / `inbox-ai-*.org`, which the fingerprint does not watch yet |
| DSH dispatch (who executes a task; including dedup and retry) | **Not implemented** | `POST /ui-pm/tasks/:id/dispatch` sits in `UNSUPPORTED_ENDPOINTS`; execution config only has "not ready" (`NOT_READY`) / "ready for handoff" (`HANDOFF_READY`) and never pretends to have dispatched |
| Dedicated `submit-review` / `accept` / `return` commands | **Not implemented** | `pm task transition` + `actor=human` is the equivalent today |
| Task change history (reading the `:LOGBOOK:` trail) + a detail view | **Done** | `pm task show --json` returns `history` / `historyCount` / `historyTruncated`, and the task detail pane renders it (newest first; missing fields read "not recorded") |
| Task evidence (screenshots / links) and stable IDs for acceptance criteria | **Done** | `pm task evidence add/list` (kind / result, `info` when unknown) and `pm task criteria init-ids` (backfills `c-xxxx` IDs) |
| AI self-assessment + an aggregated event timeline | **Planned** | Still internal-design-only |
| Frontend JS module split (phase 2) + tests no longer reading source text | **In progress** | That static check currently reports the FAIL |
| Replacing drag/scroll with a third-party library | **Under evaluation** | Drag-and-drop and horizontal scrolling are home-grown (and usable); whether to switch is being evaluated |
| End-to-end re-verification of plugin installation | **In progress** | Installation goes through GitHub (above); a clean-profile re-verification is unfinished |
| `pipx` / PyPI publishing | **Planned** | `pipx install git+https://github.com/SunrShine/dsh-pm` is the target form; PyPI is not published |
| `pm.el` (an Emacs org-agenda / capture entry point) | **Available** (repo root `pm.el`) | Left sidebar entry, agenda files, `C-c a P`, and a multi-file-aware org-capture template (writes the current `inbox-human-*.org` with `:ID:`); also `pm-capture-inbox` / `pm-inbox-render` / `pm-inbox-open-current` (see `emacs/README.md`) |
| Contributor agreement, CI workflow | **To be added** | The licence is settled as MIT (below) |
| Compatibility range with other DSH versions | **TODO** | So far only verified against `0.2.1-alpha.x` |

## License and third parties

- **Licence: MIT** — see the `LICENSE` file at the repository root (generated together with the release artefacts).
- **Third-party dependencies**: the Python side has **zero third-party dependencies** (standard library); the frontend is vanilla JS/CSS with no npm dependencies and no build step; drag and scroll are home-grown.
- **Data**: DSH data roots are read read-only; conversation bodies are never read or exported, credentials are not read, and DSH keeps ownership of command approval.
  **This repository ships no library or note data**: you create the work-memory with `pm init --root <your dir>`;
  every library path in this README is a placeholder (`<your data root>` / `~/my-work-memory`) and no concrete data is shown.

## Compatibility with DSH

**No `@deepseek-ai/dsh*` version dependency is declared in the package** (no peer version constraint, so DSH's compatibility check cannot block it); **verified against DSH `0.2.1-alpha.x`**:
measured on `0.2.1-alpha.1` (preview data root), `session_projcache` version 7.
The field list and the known pitfalls are written into the test data in `tests/fixtures.py` (including bad-data examples), so you can compare directly.
