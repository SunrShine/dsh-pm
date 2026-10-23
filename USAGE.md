# Usage

English · [简体中文](USAGE.zh-CN.md)

> This tutorial is organised by **what you want to do**. For install and the big picture see the [README](README.md); the authoritative definition of any command is always `pm <command> --help` (every command here was checked against the real `--help`).

## 0. Which half works standalone

| Part | Needs a DSH host? | Notes |
| --- | --- | --- |
| `bin/pm` (CLI + MCP) | **No** | Reads and writes the org work-memory library you point it at |
| The three skills (`skill/`) | **No** | Operating instructions for agents; install with `pm skill install` |
| The plugin half (web workbench / `/ui-pm/*` routes / `lib/`) | **Yes**, DSH `0.2.1-alpha.x` | The `@deepseek-ai/dsh-*` packages in `devDependencies` are only needed when developing the plugin half |

Only want the CLI / MCP? Clone the repo and run `./bin/pm` (or `pip install .`).

## 1. Up and running in 30 seconds (no DSH needed)

```bash
# 1) Create the library skeleton (add --no-git if you do not want git)
pm init --root ~/my-work-memory --no-git

# 2) Write the config file: tell pm where the library is
#    (pm init only creates the skeleton; it does not write pm.toml for you)
printf 'library = "~/my-work-memory"\n' > ~/my-work-memory/pm.toml

# 3) Capture a quick note (--config points explicitly at the target library)
pm capture --config ~/my-work-memory/pm.toml "let us get the CLI half running today" --project demo-app

# 4) See where it landed
pm inbox list --config ~/my-work-memory/pm.toml
```

- `library = "~/..."` supports `~` expansion; `pm init` creates `inbox.org` / `overrides.org` / `README.org` / `.gitignore`
  (that `inbox.org` is the skeleton file; with the multi-file inbox in §3.5 the notes themselves live in `inbox-human-*.org` / `inbox-ai-*.org`, and `inbox.org` becomes a generated view).
- **Write gate**: without an explicit `--config` (and without either environment variable) a write command must carry `--yes`; otherwise it is rejected with `NEEDS_YES` — this stops accidental writes to the default library. To rehearse only, add `--dry-run` (no `--yes` needed).

## 2. Teach your agent to use it

### 2.1 Install the skills

```bash
pm skill path --all                                 # where the three bundled skills live
pm skill install --skill pm-evidence --dsh-home ~/.dsh
pm skill install --all --dsh-home ~/.dsh            # install all three
```

- Installation creates a **symlink** at `<dsh-home>/skills/<name>`, so edits to the source take effect immediately.
- The three skills: `pm` (the main read/write playbook), `pm-evidence` (attach checkable evidence to acceptance criteria), `pm-planning` (turn a request into checkable tasks).

### 2.2 Wire it up as MCP (`pm mcp`, stdio)

`pm mcp` speaks JSON-RPC over stdio, so any MCP-capable client can use it. On the DSH side, copy `config/dsh-mcp.patch.yml` into the profile's `cordis.patch.yml` — it **must be wrapped in `insert:`** (a bare entry means "override", and if the id does not exist it silently does nothing):

```yaml
- insert:
    - id: mcp-pm
      name: '@deepseek-ai/dsh-mcp-client'
      config:
        serverName: pm
        transport: stdio
        command: <pm-root>/bin/pm
        args: ['mcp']
        cwd: <pm-root>
        env:
          PATH: <node-bin-dir>:/usr/local/bin:/usr/bin:/bin
```

- Consider adding `--config` to `args` so the MCP side and the instance side read the same library.
- The tool list and the honesty contract (`task_add` can only create TODO/NEXT; `proposal_draft` only drafts proposals, never tasks) are in the README's "MCP tools" section.

## 3. A day's workflow

In one sentence: **AI produces candidates, humans decide; AI can submit at most to REVIEW, and only a human writes DONE.**

### 3.1 Quick note → proposal → human approves

```bash
# 1) Quick note (the original text is read-only and never rewritten in place)
pm capture --config ~/my-work-memory/pm.toml "the customer wants an entry point that exports a weekly report" --project demo-app

# 2) Take the :ID: from the inbox and ask the AI for a proposal
pm inbox list --config ~/my-work-memory/pm.toml
pm proposal create --config ~/my-work-memory/pm.toml \
  --source-inbox <inbox-id> \
  --change "Add: weekly-report export entry point" \
  --criterion "the export command produces a weekly report" \
  --project demo-app

# 3) A human approves (only approval creates real tasks; rejection changes nothing)
pm proposal approve <proposal-id> --config ~/my-work-memory/pm.toml \
  --project demo-app --expected-revision 1
```

### 3.2 Working a task: the state machine is strictly linear

```text
TODO → NEXT → DOING → REVIEW → DONE        NEXT/DOING ⇄ WAITING/BLOCKED
any unfinished → CANCELLED                  DONE / CANCELLED are terminal
```

```bash
# Start working (skipping levels is rejected: TODO → DOING is invalid, you must pass through NEXT)
pm task transition <task-id> --config ~/my-work-memory/pm.toml \
  --project demo-app --to NEXT --expected-revision 1
```

### 3.3 Attaching evidence (every acceptance criterion has a stable ID)

```bash
# See the criteria and their stable IDs (c-xxxx); this is also where you get the revision
pm task show <task-id> --config ~/my-work-memory/pm.toml --project demo-app --json

# Tick one criterion
pm task check <task-id> --config ~/my-work-memory/pm.toml --project demo-app \
  --criterion-id c-65e1 --expected-revision 2

# Attach one piece of checkable evidence
pm task evidence add <task-id> --config ~/my-work-memory/pm.toml --project demo-app \
  --criterion-id c-65e1 --kind test --result pass \
  --ref "node --test tests/frontend" --expected-revision 3
```

- `--kind`: test / build / manual / artifact / review / other; `--result`: pass / fail / `info`.
- **If you do not know the outcome, write `info` — never guess `pass`**; `--ref` must not contain `|` (use `--note` instead).

### 3.4 AI submits for review, a human writes DONE

```bash
# AI/system can submit at most to REVIEW
pm task transition <task-id> --config ~/my-work-memory/pm.toml --project demo-app \
  --to REVIEW --expected-revision 4 --reason "evidence attached, awaiting human review"

# Human acceptance (DONE only accepts actor=human; AI writes are rejected with DONE_REQUIRES_HUMAN)
pm task transition <task-id> --config ~/my-work-memory/pm.toml --project demo-app \
  --to DONE --expected-revision 5 --actor human --reason "accepted by a human"
```

**Every write command is CAS**: fetch the `revision` with `task show`, then pass `--expected-revision`; a mismatch returns `exit 3` (409) and writes nothing.

### 3.5 The inbox is split into files (weekly human / monthly AI)

The inbox is no longer one file: the sources of truth are `inbox-human-<period>.org` (human writes, default **weekly**, e.g. `inbox-human-2026-W43.org`) and
`inbox-ai-<period>.org` (AI / MCP writes, default **monthly**, e.g. `inbox-ai-2026-10.org`); `inbox.org` is a **generated summary view (read-only)**.

```bash
# Turn rotation on. The code default is "single", so an old library keeps working unchanged.
cat >> ~/my-work-memory/pm.toml <<'EOF'

[inbox]
human_mode = "weekly"     # weekly | monthly | quarterly | yearly | single | per-entry
ai_mode    = "monthly"    # monthly | quarterly | yearly | single
EOF

pm capture --config ~/my-work-memory/pm.toml "…"             # CLI = human → inbox-human-2026-W43.org
# the same capture tool over MCP (source=mcp) writes the AI file: inbox-ai-2026-10.org

pm inbox files  --config ~/my-work-memory/pm.toml            # which source files exist (origin + name)
pm inbox list   --config ~/my-work-memory/pm.toml --origin ai
pm inbox render --config ~/my-work-memory/pm.toml            # rewrite the read-only inbox.org view
pm inbox render --config ~/my-work-memory/pm.toml --check    # stale view → exit 1, nothing written
```

- **Archiving is time rotation, not file movement**: `pm inbox archive` only writes the status; the entry stays in the period file it was written to, so "week 43" stays readable in `inbox-human-2026-W43.org`.
- **Do not hand-edit `inbox.org`** — the next `pm inbox render` overwrites it. Edit `inbox-human-<period>.org` instead (it carries a copy-paste entry template in its header).
- An old library that still has one mixed `inbox.org`: `pm inbox migrate` (dry-run by default) prints where every block would go;
  `pm inbox migrate --write` backs the old file up as `inbox.org.bak.<YYYYmmdd-HHMMSS>`, splits it by origin/period, then regenerates the view.
- Every action (`archive` / `annotate` / `edit` / `pin` / …) still addresses the entry by `:ID:` and writes into whichever file currently holds it.

## 4. Using it with DSH

```bash
dsh plugin add github:SunrShine/dsh-pm
```

- The plugin half requires **DSH ≥ `0.2.1-alpha.1`** (developed and verified against that version; older versions are untested and may fail to load). The CLI/MCP and the skills do not need DSH.
- Once installed, open it from the **"PM Workbench" entry in the DSH sidebar**; see the README's "UI" section for the tour and screenshots.
- To make the HTTP path and the `pm mcp` subprocess read the **same library**, set `DSH_UI_PM_CONFIG=<your pm.toml>` for the instance (next section).

## 5. Multiple libraries / multiple instances

**Config lookup order** (matches `pm --help`):

```text
--config  >  DSH_UI_PM_CONFIG  >  PM_CONFIG  >  ./pm.toml  >  ~/.dsh-pm/pm.toml  >  built-in default
```

- **Explicit sources must exist and parse**: one wrong character fails immediately (`CONFIG_NOT_FOUND` / `CONFIG_INVALID`), and it **never silently falls back to the default library**.
- `DSH_UI_PM_CONFIG` is **instance-scoped**: the plugin side and the `pm mcp` side both honour it, so when both variables are set they read the same library instead of diverging.
- To isolate a throwaway instance use `--dsh-home` (or `PM_DSH_HOME`) as a single-instance override; use `pm skill install --all-instances` to act on every data root.
- `pm.toml` holds two kinds of things: `library` (the library root) and one or more `[[instance]]` tables (`id` / `path` / `role`), plus view settings `active_days` / `active_hours` / `row_limit` / `exclude_paths` and the inbox rotation `[inbox] human_mode` / `ai_mode` (`single` = one `inbox.org`).
- The write gate is independent of env vars: even with both variables set, write commands **still** need `--yes` (unless you point at the library explicitly with `--config`).

## 6. FAQ

| Symptom | Cause and fix |
| --- | --- |
| `pm: [NO_LIBRARY]` | `pm.toml` has no `library`; add the library root |
| `pm: [CONFIG_NOT_FOUND]` / `[CONFIG_INVALID]` | The explicit config path does not exist or the TOML is broken. It will **not** fall back to the default library (by design) |
| `pm: [NEEDS_YES]` | A write command with neither an explicit `--config` nor `--yes`; add `--yes` or point at the library |
| `[LEGACY_UNTRACKED]` | An old inbox entry without a `:ID:` (identity is `:ID:` only; old entries are flagged rather than guessed at — after a split they stay in the human file until you give them an ID) |
| My edit to `inbox.org` vanished | `inbox.org` is a **generated view**: the next `pm inbox render` overwrites it. Edit the period file (`pm inbox files` lists them), then re-render |
| `pm inbox render --check` exits 1 | The view is older than the source files: run `pm inbox render` (no `--write` needed; `--check` never writes) |
| `[DONE_REQUIRES_HUMAN]` | AI/system tried to write `DONE`; use `--to REVIEW` and let a human accept |
| `[INVALID_TRANSITION]` | Level skipping (e.g. TODO → REVIEW); follow the arrows in 3.2 |
| `exit 3` (409) | The `revision` is not the latest; run `task show` again and retry |
| "needs attention" is empty | Those cards only appear on an **explicit signal** (controlled session / obvious anomaly); an empty library or empty payload is a legal output, not a bug |
| Why is the session status always `unknown`? | Because the panel reads a **read-only snapshot**: the snapshot carries no "is it still running right now" signal, so nobody can know; the run status is always written as `unknown` and only observed history is shown |
| Why can't AI write DONE? | DONE is the only proof that "a human accepted it" (see the README's honesty contract) |
| No conversation text in the output | Prompt text is not printed by default; add `--show-prompt` to see it |

## 7. One-page command cheat sheet

| Goal | Command |
| --- | --- |
| Capture a note | `pm capture --config ~/my-work-memory/pm.toml "…"` |
| List the inbox | `pm inbox list --config ~/my-work-memory/pm.toml` |
| List the inbox source files | `pm inbox files --config ~/my-work-memory/pm.toml` |
| Only AI (or human) entries | `pm inbox list --config ~/my-work-memory/pm.toml --origin ai` |
| Regenerate the `inbox.org` view | `pm inbox render --config ~/my-work-memory/pm.toml` (verify only: `--check`) |
| Split an old single-file inbox | `pm inbox migrate --config ~/my-work-memory/pm.toml` then `--write` |
| Pin an entry | `pm inbox pin <inbox-id> --config ~/my-work-memory/pm.toml --expected-revision 1` |
| Create a project | `pm project create demo-app --config ~/my-work-memory/pm.toml --title "Demo project"` |
| List projects | `pm project list --config ~/my-work-memory/pm.toml --json` |
| List tasks | `pm task list --config ~/my-work-memory/pm.toml --project demo-app --json` |
| Create a task | `pm task create --config ~/my-work-memory/pm.toml --project demo-app --title "…" --criterion "…"` |
| Show one task | `pm task show <task-id> --config ~/my-work-memory/pm.toml --project demo-app --json` |
| Backfill criterion IDs | `pm task criteria init-ids <task-id> --config ~/my-work-memory/pm.toml --project demo-app --expected-revision 1` |
| Tick a criterion | `pm task check <task-id> --config ~/my-work-memory/pm.toml --project demo-app --criterion-id c-65e1 --expected-revision 2` |
| Attach evidence | `pm task evidence add <task-id> --config ~/my-work-memory/pm.toml --project demo-app --criterion-id c-65e1 --kind test --result pass --ref "…" --expected-revision 3` |
| List evidence | `pm task evidence list <task-id> --config ~/my-work-memory/pm.toml --project demo-app` |
| Change status | `pm task transition <task-id> --config ~/my-work-memory/pm.toml --project demo-app --to NEXT --expected-revision 2` |
| Draft a proposal | `pm proposal create --config ~/my-work-memory/pm.toml --source-inbox <inbox-id> --change "Add: …" --project demo-app` |
| Approve a proposal | `pm proposal approve <proposal-id> --config ~/my-work-memory/pm.toml --project demo-app --expected-revision 1` |
| Memory candidates | `pm memory candidates --config ~/my-work-memory/pm.toml --status CANDIDATE` |
| Add a memory | `pm memory add --config ~/my-work-memory/pm.toml --text "…" --scope demo-app --type decision --topic "config precedence" --sources "commit abc1234"` |
| Verify / supersede / discard | `pm memory verify <memory-id> --config ~/my-work-memory/pm.toml --expected-revision 1` ・ `pm memory deprecate <memory-id> --config ~/my-work-memory/pm.toml --reason "superseded by a new decision" --superseded-by <memory-id>` ・ `pm memory discard <memory-id> --config ~/my-work-memory/pm.toml --reason "false positive"` |
| List workspaces | `pm workspace list --config ~/my-work-memory/pm.toml --json` |
| Scan DSH data roots | `pm scan --config ~/my-work-memory/pm.toml --days 14` |
| Card view | `pm ui-cards --config ~/my-work-memory/pm.toml --limit 20` |
| Render generated/ | `pm render --config ~/my-work-memory/pm.toml --write` |
| Summary queue | `pm summary queue --config ~/my-work-memory/pm.toml` |
| Start MCP | `pm mcp --config ~/my-work-memory/pm.toml` |
| Skill path / install | `pm skill path --all` ・ `pm skill install --all --dsh-home ~/.dsh` |

> Fallback: add `--help` to any command (e.g. `pm task evidence add --help`) to see the options that really exist right now.
