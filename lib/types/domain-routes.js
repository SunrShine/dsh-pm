/**
 * The domain command surface as data.
 *
 * pm's domain commands share one shape: a subcommand, flags, an optional
 * identity positional, compare-and-set write flags, and one exit-code
 * vocabulary. This module states that mapping as a table — path pattern, argv
 * template, and the bindings that may fill each placeholder — so a new pm
 * command is one entry here rather than another handler, and the HTTP layer
 * stays a single executor.
 */
/** ULID body: Crockford base32, 26 characters. */
const ULID = '[0-9A-HJKMNP-TV-Z]{26}';
/** Identity shape per domain, checked before any argv is built. */
export const ID_PATTERNS = {
    inbox: new RegExp('^inbox-' + ULID + '$', 'u'),
    task: new RegExp('^task-' + ULID + '$', 'u'),
    proposal: new RegExp('^proposal-' + ULID + '$', 'u'),
    memory: new RegExp('^memory-' + ULID + '$', 'u'),
};
/** Fields every mutating route accepts; `expectedRevision` is added per {@link RevisionRule}. */
export const SHARED_WRITE_FIELDS = [
    { name: 'actor', flag: '--actor', kind: 'enum', values: ['human', 'ai', 'system'] },
    { name: 'reason', flag: '--reason', kind: 'string' },
    { name: 'idempotencyKey', flag: '--idempotency-key', kind: 'string' },
    { name: 'dryRun', flag: '--dry-run', kind: 'boolean' },
];
/** The revision field a write route adds when it accepts one. */
const REVISION_FIELD = { name: 'expectedRevision', flag: '--expected-revision', kind: 'int' };
/**
 * Endpoints §6 names but pm's CLI does not implement yet. They are reported by
 * /ui-pm/capabilities and deliberately absent from {@link DOMAIN_ROUTES}: a
 * route is added here only when the command it would run exists - or, for a route
 * that ships ahead of its command, when the flag guard's pending list names it.
 */
export const UNSUPPORTED_ENDPOINTS = [
    {
        method: 'POST', path: '/ui-pm/tasks/:id/submit-review',
        reason: 'pm task submit-review is not part of the CLI yet (P3 acceptance flow)',
    },
    {
        method: 'POST', path: '/ui-pm/tasks/:id/accept',
        reason: 'pm task accept is not part of the CLI yet (P3 acceptance flow)',
    },
    {
        method: 'POST', path: '/ui-pm/tasks/:id/return',
        reason: 'pm task return is not part of the CLI yet (P3 acceptance flow)',
    },
    {
        method: 'POST', path: '/ui-pm/tasks/:id/dispatch',
        reason: 'this service never dispatches work: execution-config plus handoff is the whole contract, and no endpoint may claim a run started',
    },
];
/**
 * Flags every command accepts but this service deliberately never forwards.
 *
 * They are properties of the Host invocation, not of a request: a caller that
 * could name the configuration file or the DSH home could point the launcher at
 * another library or another instance, and `--yes` exists only for invocations
 * that never named a configuration file at all.
 */
export const HOST_OWNED_FLAGS = [
    { flag: '--config', reason: 'the host names one configuration file; a request must not repoint the launcher' },
    { flag: '--dsh-home', reason: 'the running profile owns the DSH home; a request must not target another instance' },
    { flag: '--yes', reason: 'only needed when no configuration file is named, which this service always does' },
    { flag: '--json', reason: 'every invocation already asks for JSON' },
    { flag: '--help', reason: 'not a request parameter' },
];
/**
 * Flags the executor itself may put on a command line, whatever a route declares.
 *
 * The explicit allowlist the alignment check subtracts before calling a flag
 * undeclared: the configuration file is named by the host, JSON is always asked
 * for, and `--yes` exists only for invocations that named no configuration at
 * all. Each one carries its reason in {@link HOST_OWNED_FLAGS}.
 */
export const EXECUTOR_FLAGS = ['--config', '--json', '--yes'];
/**
 * Commands the CLI offers that this service deliberately does not expose.
 *
 * The closure check reads the launcher's own command tree and requires every
 * command to be routed, covered by a fixed route, or named here with a reason -
 * so a command added to the CLI tomorrow cannot quietly have no answer.
 */
export const UNEXPOSED_COMMANDS = [
    {
        cliPath: ['api'],
        reason: 'the pm-api-v2 envelope query entry: a tooling interface, not something the workbench renders',
    },
    {
        cliPath: ['init'],
        reason: 'library scaffolding: it creates the work-memory skeleton, which an HTTP caller must not do',
    },
    { cliPath: ['log'], reason: 'session-log extraction for a person or agent; it only prints' },
    {
        cliPath: ['mcp'],
        reason: 'the MCP server DSH launches through its own client row; this plugin talks to pm over HTTP instead',
    },
    {
        cliPath: ['render'],
        reason: 'writes generated/ for human maintenance; the workbench reads the live projection instead',
    },
    { cliPath: ['scan'], reason: 'the read-only scan whose projection the work-card route already serves' },
    {
        cliPath: ['index'],
        reason: 'the derived content index (内部记录/11 §A1): maintenance a person or a hook runs, not a workbench action; recall reads what it built',
    },
    { cliPath: ['skill'], reason: 'skill installation and path maintenance, run by a person or by pm skill install' },
    { cliPath: ['summary', 'queue'], reason: 'the summary work queue, read by a person or agent rather than rendered' },
    {
        cliPath: ['summary', 'set'],
        reason: 'writing a work-card summary: an editorial act the workbench does not perform',
    },
    {
        cliPath: ['task', 'criteria', 'init-ids'],
        reason: 'planning maintenance: it stamps stable criterion ids onto an existing task',
    },
    {
        cliPath: ['task', 'init-ids'],
        reason: 'the same planning maintenance at the task level: it stamps stable criterion ids',
    },
    {
        cliPath: ['task', 'evidence', 'rm'],
        reason: 'removing evidence is destructive, and the approved scope is CLI-only (2026-10-16 ruling): exposing it needs a proposal, then a human approval, then a card - until then the omission is deliberate',
    },
    {
        cliPath: ['task', 'dag', 'set'],
        reason: 'dependency-graph maintenance, arranged by a person or agent rather than a workbench view',
    },
    {
        cliPath: ['task', 'import-team'],
        reason: 'imports an outside team plan: a planning act, not a workbench action',
    },
    {
        cliPath: ['task', 'evidence', 'list'],
        reason: 'reading evidence stays on task show --json (2026-10-13 ruling); only the evidence write is routed',
    },
    {
        cliPath: ['memory', 'stale'],
        reason: 'read-only, but nothing consumes it: the memory page stages (内部记录/12: P2 browsing/search, P3 history) have no staleness view, so the 2026-10-16 ruling keeps this unexposed - open the route together with the UI change that shows stale L2/L3',
    },
    {
        cliPath: ['memory', 'scene', 'show'],
        reason: 'the same ruling as memory stale: no memory-page stage shows scenes yet, and opening a read with no consumer fixes a shape before the view exists - open it with the scene view',
    },
    {
        cliPath: ['memory', 'scene', 'list'],
        reason: 'the list half of the same pending scene view: unexposed until the memory page lists scenes, then opened with it',
    },
    {
        cliPath: ['memory', 'condense'],
        reason: 'derives an L2 candidate by running an external LLM (--llm, --allow-network): a generation job a person starts, not an HTTP action, and its output is a candidate the page reviews later',
    },
    {
        cliPath: ['memory', 'extract'],
        reason: 'same family: it turns a session into L1 candidates with an external LLM, which is a planning/maintenance run rather than a workbench read or write',
    },
    {
        cliPath: ['memory', 'distill'],
        reason: 'same family: it distills L2 into an L3 candidate with an external LLM; exposing an LLM run needs a product decision and its own card',
    },
    {
        cliPath: ['memory', 'scene', 'set'],
        reason: 'writing a scene is an editorial act (CAS + audit), like removing evidence: exposing it needs a proposal, then a card',
    },
    {
        cliPath: ['hook', 'session-start'],
        reason: 'the SessionStart hook the DSH hooks bridge runs with the session context on stdin; its caller is that bridge, not an HTTP request',
    },
    {
        cliPath: ['hook', 'recall'],
        reason: 'the UserPromptSubmit hook the same bridge runs per prompt; the workbench reads recall itself through GET /ui-pm/recall',
    },
    {
        cliPath: ['hook', 'install'],
        reason: 'it prints a profile fragment for a person to copy; installation guidance is not a workbench action',
    },
];
/**
 * Commands the fixed routes already run.
 *
 * The work-card payload and the quick note are fixed paths in ./index.ts rather
 * than table entries, so the closure check has to count them as covered.
 */
export const FIXED_ROUTE_COMMANDS = [
    { cliPath: ['ui-cards'], reason: 'served by the fixed work-card route, which is not a table entry' },
    { cliPath: ['capture'], reason: 'served by the fixed quick-note route, which is not a table entry' },
];
/** The command surface, one entry per endpoint. */
export const DOMAIN_ROUTES = [
    // ---- inbox ---------------------------------------------------------
    {
        method: 'GET', path: '/ui-pm/inbox',
        argv: ['inbox', 'list', '--status', '{status}', '--json'],
        query: [{ name: 'status' }],
    },
    {
        method: 'POST', path: '/ui-pm/inbox/:id/archive', write: true,
        argv: ['inbox', 'archive', '{id}', '--json'],
        ids: { id: 'inbox' },
    },
    {
        method: 'POST', path: '/ui-pm/inbox/:id/snooze', write: true,
        argv: ['inbox', 'snooze', '{id}', '--until', '{until}', '--json'],
        ids: { id: 'inbox' },
        body: [{ name: 'until', flag: '--until', kind: 'string', required: true }],
    },
    {
        method: 'POST', path: '/ui-pm/inbox/:id/merge', write: true,
        argv: ['inbox', 'merge', '{id}', '--into', '{into}', '--json'],
        ids: { id: 'inbox' },
        body: [{ name: 'into', flag: '--into', kind: 'string', required: true }],
    },
    {
        method: 'POST', path: '/ui-pm/inbox/:id/note', write: true,
        argv: ['inbox', 'note', '{id}', '--project', '{project}', '--json'],
        ids: { id: 'inbox' },
        body: [{ name: 'project', flag: '--project', kind: 'string' }],
    },
    {
        method: 'POST', path: '/ui-pm/inbox/:id/dismiss', write: true,
        argv: ['inbox', 'dismiss', '{id}', '--json'],
        ids: { id: 'inbox' },
        required: ['reason'],
    },
    {
        method: 'GET', path: '/ui-pm/inbox/:id',
        argv: ['inbox', 'history', '{id}', '--json'],
        ids: { id: 'inbox' },
    },
    {
        method: 'POST', path: '/ui-pm/inbox/:id/annotate', write: true,
        argv: ['inbox', 'annotate', '{id}', '--text', '{text}', '--json'],
        ids: { id: 'inbox' },
        // Appending to an entry needs no reason; the original headline stays put.
        body: [{ name: 'text', flag: '--text', kind: 'string', required: true }],
    },
    {
        method: 'POST', path: '/ui-pm/inbox/:id/pin', write: true,
        argv: ['inbox', 'pin', '{id}', '--json'],
        ids: { id: 'inbox' },
    },
    {
        method: 'POST', path: '/ui-pm/inbox/:id/unpin', write: true,
        argv: ['inbox', 'unpin', '{id}', '--json'],
        ids: { id: 'inbox' },
    },
    {
        method: 'POST', path: '/ui-pm/inbox/:id/edit', write: true,
        argv: ['inbox', 'edit', '{id}', '--text', '{text}', '--json'],
        ids: { id: 'inbox' },
        body: [{ name: 'text', flag: '--text', kind: 'string', required: true }],
        // Rewriting the captured headline is an explicit act: it must say why.
        required: ['reason'],
    },
    {
        method: 'POST', path: '/ui-pm/inbox/:id/set-status', write: true,
        argv: ['inbox', 'set-status', '{id}', '--status', '{status}', '--json'],
        ids: { id: 'inbox' },
        body: [{ name: 'status', flag: '--status', kind: 'string', required: true }],
    },
    // ---- workspaces and projects ---------------------------------------
    {
        method: 'GET', path: '/ui-pm/workspaces',
        argv: ['workspace', 'list', '--project', '{project}', '--json'],
        query: [{ name: 'project', required: true }],
    },
    {
        method: 'GET', path: '/ui-pm/workspaces/context',
        argv: ['workspace', 'context', '{path}', '--no-global', '{noGlobal}', '--json'],
        query: [
            { name: 'path', required: true },
            // Read the project's own memories alone, the same switch memory context has.
            { name: 'no-global', flag: '--no-global', as: 'noGlobal', boolean: true },
        ],
    },
    {
        method: 'GET', path: '/ui-pm/projects',
        argv: ['project', 'list', '--in-library-only', '{inLibraryOnly}', '--json'],
        query: [{ name: 'in-library-only', flag: '--in-library-only', as: 'inLibraryOnly', boolean: true }],
    },
    {
        method: 'POST', path: '/ui-pm/projects', write: true, revision: 'none',
        // pm project create takes --title/--path/--workspace and --dry-run only: a
        // created project has no revision to compare and its parser rejects the
        // audit flags, so this route accepts exactly what the command does.
        shared: [{ name: 'dryRun', flag: '--dry-run', kind: 'boolean' }],
        argv: ['project', 'create', '{key}', '--title', '{title}', '--path', '{path}',
            '--workspace', '{workspace}', '--json'],
        body: [
            // KEY is a positional argument, so it carries no flag.
            { name: 'key', kind: 'string', required: true },
            { name: 'title', flag: '--title', kind: 'string' },
            { name: 'path', flag: '--path', kind: 'repeat' },
            { name: 'workspace', flag: '--workspace', kind: 'repeat' },
        ],
    },
    {
        method: 'GET', path: '/ui-pm/projects/:key/brief',
        // A project directory without project.org is a real answer, not a missing
        // one: pm exits 0 with brief:null and reason:NO_PROJECT_ORG, and that passes
        // through untouched.
        argv: ['project', 'brief', 'get', '{key}', '--json'],
        patterns: { key: /^[A-Za-z0-9._-]+$/u },
    },
    {
        method: 'POST', path: '/ui-pm/projects/:key/brief', write: true, revision: 'none',
        // This command compares a whole-file digest instead of a revision, needs an
        // explicit actor, and takes no idempotency key.
        shared: [
            { name: 'reason', flag: '--reason', kind: 'string' },
            { name: 'dryRun', flag: '--dry-run', kind: 'boolean' },
        ],
        notForwarded: [{
                flag: '--text-file',
                reason: 'a request must not read an arbitrary host file into the library; the caller sends the text itself',
            }],
        unknownFieldHints: {
            idempotencyKey: 'this command has no idempotency key: it guards duplicates with the digest compare-and-set, '
                + 'so re-sending the same text changes nothing (changed:false) and a file that moved on answers 409',
            expectedRevision: 'this command compares the whole-file digest, not a revision: send the expectedDigest the read returned',
        },
        argv: ['project', 'brief', 'set', '{key}', '--section', '{section}', '--text', '{text}',
            '--actor', '{actor}', '--expect-digest', '{expectedDigest}', '--json'],
        patterns: { key: /^[A-Za-z0-9._-]+$/u },
        body: [
            {
                name: 'section', flag: '--section', kind: 'enum', required: true,
                values: ['goal', 'scope', 'nonGoal', 'acceptance', 'milestones', 'risks'],
            },
            // An empty text is how a section is cleared, so empty is a value here.
            { name: 'text', flag: '--text', kind: 'string', required: true, allowEmpty: true },
            { name: 'expectedDigest', flag: '--expect-digest', kind: 'string', required: true },
            {
                name: 'actor', flag: '--actor', kind: 'enum', required: true,
                values: ['human', 'ai', 'system'],
            },
        ],
    },
    {
        method: 'GET', path: '/ui-pm/projects/:id/context',
        argv: ['project', 'context', '{id}', '--no-global', '{noGlobal}', '--json'],
        query: [{ name: 'no-global', flag: '--no-global', as: 'noGlobal', boolean: true }],
    },
    // ---- tasks ---------------------------------------------------------
    {
        method: 'GET', path: '/ui-pm/tasks',
        argv: ['task', 'list', '--project', '{project}', '--status', '{status}', '--json'],
        query: [{ name: 'project', required: true }, { name: 'status' }],
    },
    {
        method: 'GET', path: '/ui-pm/tasks/:id',
        argv: ['task', 'show', '--project', '{project}', '{id}', '--json'],
        ids: { id: 'task' },
        query: [{ name: 'project', required: true }],
    },
    {
        method: 'POST', path: '/ui-pm/tasks', write: true, revision: 'none',
        argv: ['task', 'create', '--project', '{project}', '--title', '{title}',
            '--goal', '{goal}', '--non-goal', '{nonGoal}', '--criterion', '{criterion}',
            '--from-inbox', '{fromInbox}', '--ai', '{ai}', '--assignee', '{assignee}',
            '--id', '{id}', '--json'],
        body: [
            { name: 'project', flag: '--project', kind: 'string', required: true },
            { name: 'title', flag: '--title', kind: 'string', required: true },
            { name: 'goal', flag: '--goal', kind: 'string' },
            { name: 'nonGoal', flag: '--non-goal', kind: 'string' },
            { name: 'criterion', flag: '--criterion', kind: 'repeat' },
            { name: 'fromInbox', flag: '--from-inbox', kind: 'string' },
            { name: 'ai', flag: '--ai', kind: 'boolean' },
            { name: 'assignee', flag: '--assignee', kind: 'string' },
            { name: 'id', flag: '--id', kind: 'string' },
        ],
    },
    {
        method: 'PATCH', path: '/ui-pm/tasks/:id', write: true,
        ids: { id: 'task' },
        actions: {
            field: 'action',
            cases: {
                transition: {
                    argv: ['task', 'transition', '{id}', '--project', '{project}', '--to', '{to}', '--json'],
                    body: [
                        { name: 'project', flag: '--project', kind: 'string', required: true },
                        { name: 'to', flag: '--to', kind: 'string', required: true },
                    ],
                },
                check: {
                    argv: ['task', 'check', '{id}', '--project', '{project}', '--criterion-id', '{criterionId}',
                        '--index', '{index}', '--uncheck', '{uncheck}', '--json'],
                    exactlyOne: ['criterionId', 'index'],
                    notForwarded: [{
                            flag: '--criterion',
                            reason: 'the deprecated number-or-text selector: this service names a criterion by its stable id, so a reordered file cannot retarget a check',
                        }],
                    body: [
                        { name: 'project', flag: '--project', kind: 'string', required: true },
                        { name: 'criterionId', flag: '--criterion-id', kind: 'string' },
                        {
                            name: 'index', flag: '--index', kind: 'int',
                            deprecated: 'prefer criterionId: a stable per-criterion id; a file index shifts when criteria are reordered',
                        },
                        { name: 'uncheck', flag: '--uncheck', kind: 'boolean' },
                    ],
                },
            },
        },
    },
    {
        method: 'POST', path: '/ui-pm/tasks/:id/evidence', write: true,
        ids: { id: 'task' },
        // The command is a task-level compare-and-set write, so the revision travels
        // in the body like every other write here.
        required: ['actor'],
        argv: ['task', 'evidence', 'add', '{id}', '--project', '{project}', '--criterion-id', '{criterionId}',
            '--kind', '{kind}', '--result', '{result}', '--ref', '{ref}', '--note', '{note}', '--json'],
        body: [
            { name: 'project', flag: '--project', kind: 'string', required: true },
            { name: 'criterionId', flag: '--criterion-id', kind: 'string', required: true },
            {
                name: 'kind', flag: '--kind', kind: 'enum', required: true,
                values: ['test', 'build', 'manual', 'artifact', 'review', 'other'],
            },
            { name: 'result', flag: '--result', kind: 'enum', required: true, values: ['pass', 'fail', 'info'] },
            {
                name: 'ref', flag: '--ref', kind: 'string', required: true,
                forbid: {
                    text: '|',
                    code: 'INVALID_EVIDENCE_REF',
                    message: 'ref must not contain |; put the longer text in note',
                },
            },
            { name: 'note', flag: '--note', kind: 'string' },
        ],
        unknownFieldHints: {
            index: 'this command names a criterion by its stable id: send criterionId',
            criterion: 'this command names a criterion by its stable id: send criterionId',
        },
        notes: [
            'pm defaults --actor to human; this route requires actor, because an HTTP caller has no terminal context and a wrong audit attribution is worse than a refusal',
        ],
    },
    {
        // 内部记录/25 §6: the initial system prompt a project keeps as a human file.
        // A project that has not recorded one answers `exists:false, revision:0` -
        // "not written yet" is the normal first state, not an error.
        method: 'GET', path: '/ui-pm/prompt',
        // 内部记录/25 §6 documents the six fields directly under `data`; the command already
        // answers that envelope, so the route hands it on instead of nesting it.
        flattenData: true,
        argv: ['prompt', 'get', '--scope', '{scope}', '--render', '{render}', '--json'],
        // `--render` expands the referenced documents for the page's preview; absent
        // leaves it out, so a plain read returns the stored blocks only. The command
        // defaults the scope to global; this route insists on naming the project.
        query: [{ name: 'scope', required: true }, { name: 'render', boolean: true }],
        // Interface pending `pm prompt` (in flight): the executor carries arguments
        // only (no stdin channel), so blocks must travel as repeated --block-json
        // elements - the same shape proposals already use for --change.
        notes: [
            'reads projects/proj-<key>/prompt.org through pm prompt get; a missing file is exists:false with revision 0, never a 404',
            'the answer is {scope, exists, revision, updatedAt, savedBy, blocks[{name, text, include}]}: no injection-side field rides along, and a hand-written file with no :PM_REVISION: reports revision 0',
            '--render adds a render object beside the payload inside the envelope: the assembled text plus one entry per block with its expression, resolved path, line and byte counts, and the truncation flag (内部记录/25 §4)',
        ],
    },
    {
        // The list half (2026-10-19 ruling): pm prompt list answers its own envelope, so the
        // route lifts it and hands `data` on verbatim. Every item path is relative to the
        // library root (verified: projects/proj-demo01/prompt.org), so no absolute host path
        // leaves the service. Read-only: no revision, no shared body, nothing written.
        method: 'GET', path: '/ui-pm/prompts', flattenData: true,
        argv: ['prompt', 'list', '--json'],
        notes: [
            'the answer is pm prompt list with the command data lifted: {onlySaved, count, items[{scope, revision, updatedAt, savedBy, blockCount, path}]}, and every path is relative to the library root',
            'read-only: it never writes and compares no revision; a project that has recorded nothing simply is not in items',
            'the singular route stays singular: omitting scope on GET /ui-pm/prompt must never answer a list - a page cannot guess a return type from a missing parameter; if a list mode is ever wanted it needs an explicit discriminator in the payload (e.g. shape:list) rather than an implied one',
        ],
    },
    {
        // 内部记录/25 §5.1/§6: the exported-prompt records are derived data in
        // .local/prompt-exports.json, never in projects/**; the browser downloads the file
        // and the service only records what was exported. Interface provisional until
        // `pm prompt exports` lands (task-267): argv as proposed, aligned by the guard.
        method: 'GET', path: '/ui-pm/prompt-exports', flattenData: true,
        failureStatuses: { PROMPT_EXPORTS_CORRUPT: 500 },
        argv: ['prompt', 'exports', 'list', '--scope', '{scope}', '--q', '{q}', '--json'],
        query: [{ name: 'scope' }, { name: 'q' }],
        notes: [
            'answers the command data lifted: {records[{id, project, path, name, fmt, bytes, blocks, savedAt, snapshot}]}; scope and q are both optional and only what the caller sends is forwarded',
            'read-only over a derived store: the records live in .local/prompt-exports.json, never in projects/**',
            'a corrupt derived store answers 500 (PROMPT_EXPORTS_CORRUPT): that is server state, not the caller request, so it is not dressed up as a 422',
            'interface provisional: `pm prompt exports` is live; the flag guard keeps this surface aligned with its parser',
        ],
    },
    {
        method: 'POST', path: '/ui-pm/prompt-exports', write: true, revision: 'none', shared: [], flattenData: true,
        failureStatuses: { PROMPT_EXPORT_BAD_PAYLOAD: 400, PROMPT_EXPORTS_CORRUPT: 500 },
        argv: ['prompt', 'exports', 'add', '--scope', '{scope}', '--path', '{path}', '--name', '{name}',
            '--fmt', '{fmt}', '--text', '{text}', '--snapshot', '{snapshot}',
            '--blocks-json', '{blocksData}', '--idempotency-key', '{idempotencyKey}', '--json'],
        body: [
            { name: 'scope', flag: '--scope', kind: 'string', required: true },
            { name: 'path', flag: '--path', kind: 'string', required: true },
            { name: 'name', flag: '--name', kind: 'string', required: true },
            { name: 'fmt', flag: '--fmt', kind: 'enum', required: true, values: ['md', 'txt', 'org'] },
            { name: 'text', flag: '--text', kind: 'string' },
            { name: 'snapshot', flag: '--snapshot', kind: 'string' },
            { name: 'blocksData', flag: '--blocks-json', kind: 'string' },
            { name: 'idempotencyKey', flag: '--idempotency-key', kind: 'string' },
        ],
        notForwarded: [
            {
                flag: '--payload-file',
                reason: 'the route maps the POST body onto the field flags directly; the payload file form reads a host path, which an HTTP request must not name',
            },
            {
                flag: '--payload-b64',
                reason: 'the route forwards the body field by field rather than re-encoding it as base64; the payload form exists for a caller that already holds one JSON blob',
            },
            {
                flag: '--text-file',
                reason: 'the exported text travels as the request body; reading it back from a host path is a terminal convenience, not something a request may choose',
            },
        ],
        notes: [
            'writes one derived record and nothing else: the exported file is the browser user choice, and the service never claims it wrote that path',
            'idempotencyKey rides straight through: replaying the same export does not append a second record',
            'PROMPT_EXPORT_BAD_PAYLOAD answers 400 (invalid JSON reached the command); PROMPT_EXPORT_BAD_FMT is unreachable here because the route checks fmt against its enum first, so a bad format is 400 INVALID_BODY',
            'the body maps 1:1 onto the command flags (scope, path, name, fmt, text, snapshot, blocks-json, idempotency-key); the payload/base64/file forms are declared omissions',
        ],
    },
    {
        method: 'DELETE', path: '/ui-pm/prompt-exports/:id', write: true, revision: 'none', shared: [], flattenData: true,
        failureStatuses: { PROMPT_EXPORT_NOT_FOUND: 404, PROMPT_EXPORTS_CORRUPT: 500 },
        // The record id shape belongs to pm; the route only refuses values that could not
        // be one id (slashes, dot segments) before any command runs.
        patterns: { id: /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/ },
        // The command takes the id as a flag, so the path segment becomes --id <value>.
        argv: ['prompt', 'exports', 'delete', '--id', '{id}', '--json'],
        notes: [
            'deletes one derived record only: the exported file and prompt.org stay untouched',
            'a missing record answers 404 (PROMPT_EXPORT_NOT_FOUND) rather than a generic 422; the record store is derived, so the exported file may still exist',
            'answers the command data lifted: {deleted: 1}',
            'interface provisional: `pm prompt exports delete` is live; the flag guard keeps this surface aligned with its parser',
        ],
    },
    {
        method: 'PUT', path: '/ui-pm/prompt', write: true, flattenData: true,
        // The 2026-10-18 red line (内部记录/25 §7): an existing prompt.org is a human
        // file, so this route never rewrites one silently. expectedRevision is
        // required - 0 means create-only - and pm's compare-and-set answers a stale or
        // unexpected revision with exit 3, mapped to 409 carrying error.currentRevision.
        // Ruling (a) gave every content block its own :ID: drawer, which is how the page
        // matches blocks on the way back.
        argv: ['prompt', 'set', '--scope', '{scope}', '--block-json', '{blocks}', '--json'],
        // The writer is required: without --actor pm records the write as ai, and an
        // existing prompt.org then refuses every later save with AI_CANNOT_EDIT - the
        // page would be unable to edit its own file a second time. The page sends human.
        required: ['actor'],
        body: [
            { name: 'scope', flag: '--scope', kind: 'string', required: true },
            { name: 'blocks', flag: '--block-json', kind: 'json-repeat', required: true },
        ],
        // The command takes {human, ai} for actor, not the shared three: a caller that
        // sent `system` would be forwarded a value the parser rejects.
        shared: [
            { name: 'actor', flag: '--actor', kind: 'enum', values: ['human', 'ai'] },
            { name: 'reason', flag: '--reason', kind: 'string' },
            { name: 'idempotencyKey', flag: '--idempotency-key', kind: 'string' },
            { name: 'dryRun', flag: '--dry-run', kind: 'boolean' },
        ],
        failureStatuses: { RESERVED_BLOCK_NAME: 400 },
        notForwarded: [
            {
                flag: '--blocks-json',
                reason: 'the route sends the repeatable --block-json so argv order encodes block order; the whole-array form exists for a caller that already built one JSON value',
            },
            {
                flag: '--file',
                reason: 'reading an org file (or stdin) is the terminal path: a request must not name an arbitrary host path, and the executor has no stdin channel',
            },
        ],
        notes: [
            'never rewrites an existing prompt.org: expectedRevision is required, 0 means create-only, and a conflict is pm exit 3 -> 409 whose payload carries error.currentRevision',
            'blocks travel as repeated --block-json elements in array order (pm also accepts --file/- and a whole-array --blocks-json, which a route cannot use), so pm assembles the org file and gives each block its :ID: drawer - this half never builds org text',
            'refusals the caller can meet: RESERVED_BLOCK_NAME (block name prompt-meta is reserved) -> 400; AI_CANNOT_EDIT (an existing prompt.org edited as actor=ai) -> 422; BLOCK_DELETE_UNSUPPORTED (the request drops a block) -> 422',
            'an idempotencyKey belongs to one intended change: replaying it answers as a replay - 200 with changed:0 and the revision where it was - and a key that was already used on that file (even by an earlier attempt) answers the next call the same way, so a page must mint a fresh key per save',
            'a successful save advances the file revision and the block revisions together; a live acceptance reads create revision 1, a stale revision 409 with error.currentRevision, an edit at revision 2, a keyed save at revision 3 and its replay unchanged at 3, and a reserved block name refused as 400',
            'the payload is the command data lifted to one level (flattenData): {scope, file, revision, changed, idempotent, dryRun} for a write and the six documented fields for the read, never data.data',
            'pm answers exit 2 REVISION_REQUIRED without a revision, which this route never provokes: the field is required, so body validation refuses first',
            'actor is required and accepts only {human, ai}, deliberately with no default: a route that filled in human would let automation be recorded as a person editing a human file, which is the red line bypassed (fail-open); refusing a body without it is fail-closed. The command recording its own default as ai points the same way, and the page sends human explicitly',
            'note 2026-10-18 (mechanism explained, appended): the one file-revision stall observed (run C) is a pre-fix shape - the client key went straight to the meta write, so a leftover replay record for that key skipped the meta bump while the block write with its derived key still landed.',
            'that stall needs a stale leftover key, so this revision does not reproduce it and that is expected: the same key answers a replay (nothing written, changed:0), a fresh key changes content and the revision advances by one; pm pins the half-write with tests/test_prompt.py::test_same_key_different_content_never_half_writes (reverting the derived meta key turns that test red). The two raw logs match too: run C shows changed:1 with idempotent:true while the revision stayed 1, run I uses a per-run key, reads changed:0 and then revision 2.',
        ],
    },
    {
        method: 'GET', path: '/ui-pm/tasks/:id/execution-config',
        argv: ['task', 'execution-config', 'get', '{id}', '--json'],
        ids: { id: 'task' },
    },
    {
        method: 'POST', path: '/ui-pm/tasks/:id/execution-config', write: true,
        argv: ['task', 'execution-config', 'set', '{id}', '--workspace', '{workspace}',
            '--instance', '{instance}', '--project', '{project}', '--memory', '{memory}',
            '--session', '{session}', '--note', '{note}', '--json'],
        ids: { id: 'task' },
        body: [
            { name: 'workspace', flag: '--workspace', kind: 'string', required: true },
            { name: 'instance', flag: '--instance', kind: 'string' },
            { name: 'project', flag: '--project', kind: 'string' },
            { name: 'memory', flag: '--memory', kind: 'repeat' },
            { name: 'session', flag: '--session', kind: 'string' },
            { name: 'note', flag: '--note', kind: 'string' },
        ],
    },
    {
        method: 'POST', path: '/ui-pm/tasks/:id/link-session', write: true,
        argv: ['task', 'link-session', '{id}', '--session', '{session}',
            '--instance', '{instance}', '--json'],
        ids: { id: 'task' },
        body: [
            { name: 'session', flag: '--session', kind: 'string', required: true },
            { name: 'instance', flag: '--instance', kind: 'string' },
        ],
    },
    {
        method: 'POST', path: '/ui-pm/tasks/:id/unlink-session', write: true,
        argv: ['task', 'unlink-session', '{id}', '--json'],
        ids: { id: 'task' },
        required: ['reason'],
    },
    {
        method: 'GET', path: '/ui-pm/tasks/:id/handoff',
        argv: ['task', 'handoff', '{id}', '--json'],
        ids: { id: 'task' },
    },
    // ---- proposals -----------------------------------------------------
    {
        method: 'GET', path: '/ui-pm/proposals',
        argv: ['proposal', 'list', '--status', '{status}', '--json'],
        query: [{ name: 'status' }],
    },
    {
        method: 'GET', path: '/ui-pm/proposals/:id',
        argv: ['proposal', 'show', '{id}', '--json'],
        ids: { id: 'proposal' },
    },
    {
        method: 'POST', path: '/ui-pm/proposals', write: true, revision: 'optional',
        argv: ['proposal', 'create', '--source-inbox', '{sourceInbox}', '--change', '{change}',
            '--criterion', '{criterion}', '--risk', '{risk}', '--action', '{action}', '--title', '{title}',
            '--project', '{project}', '--plan-revision', '{planRevision}', '--created-by', '{createdBy}',
            '--allow-duplicate', '{allowDuplicate}', '--json'],
        body: [
            { name: 'sourceInbox', flag: '--source-inbox', kind: 'string', required: true },
            { name: 'change', flag: '--change', kind: 'repeat' },
            { name: 'criterion', flag: '--criterion', kind: 'repeat' },
            { name: 'risk', flag: '--risk', kind: 'repeat' },
            { name: 'action', flag: '--action', kind: 'repeat' },
            { name: 'title', flag: '--title', kind: 'string' },
            { name: 'project', flag: '--project', kind: 'string' },
            { name: 'planRevision', flag: '--plan-revision', kind: 'int' },
            { name: 'createdBy', flag: '--created-by', kind: 'string' },
            // Creating a second proposal for an inbox entry is the caller's call.
            { name: 'allowDuplicate', flag: '--allow-duplicate', kind: 'boolean' },
        ],
    },
    {
        method: 'POST', path: '/ui-pm/proposals/:id/revise', write: true,
        argv: ['proposal', 'revise', '{id}', '--title', '{title}', '--change', '{changes}',
            '--change-op', '{changeOp}', '--change-title', '{changeTitle}', '--criterion', '{criterion}',
            '--risk', '{risks}', '--action', '{actions}', '--json'],
        ids: { id: 'proposal' },
        body: [
            { name: 'title', flag: '--title', kind: 'string' },
            // A plan change is structured; the command renders it.
            { name: 'changes', flag: '--change', kind: 'json-repeat' },
            { name: 'changeOp', flag: '--change-op', kind: 'repeat' },
            { name: 'changeTitle', flag: '--change-title', kind: 'repeat' },
            { name: 'criterion', flag: '--criterion', kind: 'repeat' },
            { name: 'risks', flag: '--risk', kind: 'repeat' },
            { name: 'actions', flag: '--action', kind: 'repeat' },
        ],
    },
    {
        method: 'POST', path: '/ui-pm/proposals/:id/approve', write: true,
        argv: ['proposal', 'approve', '{id}', '--project', '{project}',
            '--allow-stale', '{allowStale}', '--json'],
        ids: { id: 'proposal' },
        body: [
            { name: 'project', flag: '--project', kind: 'string' },
            // Approving a plan whose source inbox moved on is the caller's decision;
            // the flag is forwarded, never set for them.
            { name: 'allowStale', flag: '--allow-stale', kind: 'boolean' },
        ],
    },
    {
        method: 'POST', path: '/ui-pm/proposals/:id/reject', write: true,
        argv: ['proposal', 'reject', '{id}', '--json'],
        ids: { id: 'proposal' },
        required: ['reason'],
    },
    // ---- memory --------------------------------------------------------
    {
        method: 'GET', path: '/ui-pm/memory',
        argv: ['memory', 'list', '--type', '{type}', '--scope', '{scope}', '--status', '{status}', '--json'],
        // `--status` is how the memory page browses DEPRECATED history (内部记录/12 P3);
        // it landed with the P0/P1 memory work and the guard caught it the same day.
        query: [{ name: 'type' }, { name: 'scope' }, { name: 'status' }],
    },
    {
        method: 'GET', path: '/ui-pm/memory/candidates',
        argv: ['memory', 'candidates', '--status', '{status}', '--json'],
        query: [{ name: 'status' }],
    },
    {
        method: 'GET', path: '/ui-pm/memory/context',
        argv: ['memory', 'context', '--scope', '{scope}', '--task', '{task}',
            '--no-global', '{noGlobal}', '--allow-cross-scope', '{allowCrossScope}', '--json'],
        query: [
            { name: 'scope', required: true },
            { name: 'task' },
            { name: 'no-global', flag: '--no-global', as: 'noGlobal', boolean: true },
            // §P4 wants a cross-project read to be an explicit authorization.
            { name: 'allow-cross-scope', flag: '--allow-cross-scope', as: 'allowCrossScope', boolean: true },
        ],
    },
    {
        // §P1 of 内部记录/11: recall reads the derived content index. Read-only: it
        // forwards the query and never writes, so no revision and no shared body.
        method: 'GET', path: '/ui-pm/recall',
        argv: ['recall', '--query', '{q}', '--scope', '{scope}', '--type', '{type}',
            '--limit', '{limit}', '--any', '{any}', '--json'],
        query: [
            { name: 'q', required: true }, { name: 'scope' }, { name: 'type' }, { name: 'limit' },
            // Explicit OR between words. Absent keeps the command's default (AND, with
            // pm's own widening on zero hits), so the old read is unchanged.
            { name: 'any', boolean: true },
        ],
        // The command can widen a search; the P1 read does not, and says so rather
        // than letting the guard pass silently.
        notForwarded: [
            {
                flag: '--include-candidate',
                reason: 'outside the P1 read (q/scope/type/limit): widening a search to unconfirmed candidates is a product decision, so the omission is declared until a filter asks for it',
            },
            {
                flag: '--include-deprecated',
                reason: 'outside the P1 read (q/scope/type/limit): a default search returns live memories, and a history filter can expose this later',
            },
        ],
    },
    {
        method: 'POST', path: '/ui-pm/memory-candidates', write: true, revision: 'none',
        argv: ['memory', 'add', '--text', '{text}', '--scope', '{scope}', '--type', '{type}',
            '--sources', '{sources}', '--topic', '{topic}', '--task-id', '{taskId}',
            '--created-by', '{createdBy}', '--supersedes', '{supersedes}', '--json'],
        body: [
            { name: 'text', flag: '--text', kind: 'string', required: true },
            { name: 'scope', flag: '--scope', kind: 'string', required: true },
            { name: 'type', flag: '--type', kind: 'enum', required: true, values: ['fact', 'decision', 'gotcha'] },
            { name: 'sources', flag: '--sources', kind: 'repeat' },
            { name: 'topic', flag: '--topic', kind: 'string' },
            { name: 'taskId', flag: '--task-id', kind: 'string' },
            { name: 'createdBy', flag: '--created-by', kind: 'string' },
            { name: 'supersedes', flag: '--supersedes', kind: 'string' },
        ],
    },
    {
        method: 'POST', path: '/ui-pm/memory-candidates/:id/verify', write: true,
        argv: ['memory', 'verify', '{id}', '--sources', '{sources}', '--supersedes', '{supersedes}',
            '--conflict-with', '{conflictWith}', '--json'],
        ids: { id: 'memory' },
        body: [
            { name: 'sources', flag: '--sources', kind: 'repeat' },
            { name: 'supersedes', flag: '--supersedes', kind: 'string' },
            { name: 'conflictWith', flag: '--conflict-with', kind: 'string' },
        ],
    },
    {
        method: 'POST', path: '/ui-pm/memory/:id/discard', write: true,
        ids: { id: 'memory' },
        // Only a candidate can be discarded, and the command insists on a reason.
        required: ['reason'],
        argv: ['memory', 'discard', '{id}', '--json'],
        // Both refusals are exit 2; the code says which one it is. A VERIFIED memory
        // is not the caller's typo, so it answers 422 and points at deprecate.
        failureStatuses: { REASON_REQUIRED: 400, NOT_A_CANDIDATE: 422 },
        notes: [
            'error mapping: NOT_A_CANDIDATE -> 422 (a VERIFIED memory is deprecated, not discarded), REVISION_CONFLICT -> 409',
            'REASON_REQUIRED -> 400 stays from the command contract, but this route normally never sees it: the body is validated first, so a missing reason answers 400 INVALID_REQUEST and an empty one answers 400 INVALID_BODY, and the command is not run at all',
            'discarding an already DEPRECATED candidate is idempotent: it answers 200 with changed:false and discarded:false',
        ],
    },
    {
        method: 'POST', path: '/ui-pm/memory/:id/deprecate', write: true,
        argv: ['memory', 'deprecate', '{id}', '--superseded-by', '{supersededBy}', '--json'],
        ids: { id: 'memory' },
        body: [{ name: 'supersededBy', flag: '--superseded-by', kind: 'string' }],
        required: ['reason'],
    },
];
/**
 * The pm command path one argv template runs.
 *
 * The leading tokens that are neither a flag nor a placeholder. For a
 * multi-word command this is the whole path (`task execution-config set`),
 * never `argv[1]` alone: the parent parser accepts no options, so comparing
 * against it would be an empty comparison that always passes.
 * @param argv - template from the route table.
 * @returns the command words, outermost first.
 */
export function cliPathOf(argv) {
    const path = [];
    for (const element of argv) {
        if (element.startsWith('--') || element.startsWith('{'))
            break;
        path.push(element);
    }
    return path;
}
/** The `--flag` literals one argv template carries, in first-seen order. */
export function argvFlagsOf(argv) {
    const flags = [];
    for (const element of argv) {
        if (!element.startsWith('--') || flags.includes(element))
            continue;
        flags.push(element);
    }
    return flags;
}
/** Absolute pathname of the capability report. */
export const CAPABILITIES_ROUTE = '/ui-pm/capabilities';
/** Refuse one request with a structured error. */
function refuse(status, code, message) {
    return { status, body: { ok: false, error: { code, message } } };
}
/**
 * Whether one value carries a domain identity.
 * @param prefix - domain the value belongs to.
 * @param value - candidate identity.
 * @returns true when the value is `<prefix>-<ULID>`.
 */
export function isIdentity(prefix, value) {
    return ID_PATTERNS[prefix].test(value);
}
/** The segments of one path pattern, with `:name` markers preserved. */
function segmentsOf(path) {
    return path.split('/').filter(segment => segment !== '');
}
/**
 * Match one request path against the table.
 * @param pathname - request pathname, already normalized by the URL parser.
 * @param method - request method, or undefined to ask only which methods the path serves.
 * @returns the matching spec with its bindings, the methods when only the method is wrong, or undefined.
 */
export function matchRoute(pathname, method) {
    const requested = pathname.split('/').filter(segment => segment !== '');
    const candidates = [];
    for (const spec of DOMAIN_ROUTES) {
        const pattern = segmentsOf(spec.path);
        if (pattern.length !== requested.length)
            continue;
        const params = {};
        let matched = true;
        for (let index = 0; index < pattern.length; index += 1) {
            const expected = pattern[index] ?? '';
            const actual = requested[index] ?? '';
            if (expected.startsWith(':')) {
                if (actual === '') {
                    matched = false;
                    break;
                }
                try {
                    params[expected.slice(1)] = decodeURIComponent(actual);
                }
                catch {
                    params[expected.slice(1)] = actual;
                }
                continue;
            }
            if (expected !== actual) {
                matched = false;
                break;
            }
        }
        if (matched)
            candidates.push({ spec, params });
    }
    if (candidates.length === 0)
        return undefined;
    if (method !== undefined) {
        const hit = candidates.find(candidate => candidate.spec.method === method);
        if (hit !== undefined)
            return hit;
    }
    return { methods: [...new Set(candidates.map(candidate => candidate.spec.method))].sort() };
}
/**
 * Prefixes every registered route hangs under, so registration follows the table.
 * @returns the distinct `/ui-pm/<domain>` prefixes, sorted.
 */
export function routePrefixes() {
    const prefixes = new Set();
    for (const spec of DOMAIN_ROUTES) {
        const segments = segmentsOf(spec.path);
        prefixes.add('/' + (segments.slice(0, 2).join('/')));
    }
    prefixes.add(CAPABILITIES_ROUTE);
    return [...prefixes].sort();
}
/**
 * Expand one argv template against its bindings.
 *
 * Reading the template: a `{name}` element is replaced by its value; when the
 * value is an array, the flag immediately before it repeats once per element;
 * when the value is a boolean, `true` leaves the flag alone and `false` drops
 * it; an absent or empty value drops both the flag and the placeholder. Every
 * element stays a separate argv entry, so nothing a caller sends can become
 * shell syntax.
 * @param argv - template from the route table.
 * @param bindings - resolved values by placeholder name.
 * @param config - configuration file every invocation names.
 * @returns the launcher arguments.
 */
export function buildArgv(argv, bindings, config) {
    const out = ['--config', config];
    for (let index = 0; index < argv.length; index += 1) {
        const element = argv[index] ?? '';
        const placeholder = /^\{(\w+)\}$/u.exec(element);
        if (placeholder === null) {
            out.push(element);
            continue;
        }
        const value = bindings[placeholder[1] ?? ''];
        const previous = argv[index - 1] ?? '';
        const flagBefore = previous.startsWith('--');
        if (value === undefined || value === false) {
            if (flagBefore)
                out.pop();
            continue;
        }
        if (value === true)
            continue;
        // An empty string is a value when the route declared it as one (clearing a
        // section, for instance); the flag it belongs to has already been pushed.
        if (value === '') {
            out.push('');
            continue;
        }
        if (Array.isArray(value)) {
            if (flagBefore)
                out.pop();
            for (const item of value) {
                if (flagBefore)
                    out.push(previous);
                out.push(String(item));
            }
            continue;
        }
        out.push(String(value));
    }
    return out;
}
/**
 * Read one route's query parameters into bindings.
 * @param spec - matched route.
 * @param params - path bindings.
 * @param query - request search parameters.
 * @returns the bindings, or the refusal to answer with.
 */
export function readQuery(spec, params, query) {
    const bindings = { ...params };
    // `limit` is the executor's own row cap, and only a read has rows to cap.
    const accepted = new Set((spec.query ?? []).map(field => field.name));
    if (spec.write !== true)
        accepted.add('limit');
    const unknownParams = [...query.keys()].filter(name => !accepted.has(name));
    if (unknownParams.length > 0) {
        return {
            status: 400,
            body: {
                ok: false,
                error: {
                    code: 'UNKNOWN_PARAMS',
                    message: 'this endpoint does not take ' + unknownParams.join(', ')
                        + '; it reads: ' + ([...accepted].sort().join(', ') || '(no query parameters)'),
                },
                unknownParams,
            },
        };
    }
    for (const field of spec.query ?? []) {
        const key = field.as ?? field.name;
        const raw = query.get(field.name);
        if (field.boolean === true) {
            bindings[key] = raw !== null && raw !== 'false' && raw !== '0';
            continue;
        }
        if (raw === null || raw === '') {
            if (field.required === true) {
                return refuse(400, 'INVALID_QUERY', 'query parameter ' + field.name + ' is required');
            }
            continue;
        }
        bindings[key] = raw;
    }
    return { bindings };
}
/** Coerce one body value to the shape its field declares. */
function fieldValue(field, value) {
    if (value === undefined)
        return undefined;
    switch (field.kind) {
        case 'boolean':
            return typeof value === 'boolean'
                ? value
                : refuse(400, 'INVALID_BODY', field.name + ' must be a boolean');
        case 'int':
            return typeof value === 'number' && Number.isInteger(value)
                ? value
                : refuse(400, 'INVALID_BODY', field.name + ' must be an integer');
        case 'repeat':
            if (!Array.isArray(value) || value.some(item => typeof item !== 'string' || item.trim() === '')) {
                return refuse(400, 'INVALID_BODY', field.name + ' must be an array of non-empty strings');
            }
            return value;
        case 'json-repeat': {
            // A structured entry travels as its own JSON text, which is how the
            // command takes a plan change; a plain string is passed through, so the
            // command's own "新增：标题" shorthand stays usable.
            if (!Array.isArray(value) || value.length === 0) {
                return refuse(400, 'INVALID_BODY', field.name + ' must be a non-empty array (an empty one cannot clear a plan)');
            }
            const rendered = [];
            for (const item of value) {
                if (typeof item === 'string') {
                    if (item.trim() === '')
                        return refuse(400, 'INVALID_BODY', field.name + ' entries must not be empty');
                    rendered.push(item);
                    continue;
                }
                if (typeof item === 'object' && item !== null && !Array.isArray(item)) {
                    rendered.push(JSON.stringify(item));
                    continue;
                }
                return refuse(400, 'INVALID_BODY', field.name + ' entries must be a string or an object');
            }
            return rendered;
        }
        case 'enum':
            if (typeof value !== 'string' || !(field.values ?? []).includes(value)) {
                return refuse(400, 'INVALID_BODY', field.name + ' must be one of ' + (field.values ?? []).join(', '));
            }
            return value;
        default:
            if (typeof value !== 'string') {
                return refuse(400, 'INVALID_BODY', field.name + ' must be a string');
            }
            if (field.allowEmpty === true)
                return value;
            if (value.trim() === '') {
                return refuse(400, 'INVALID_BODY', field.name + ' must be a non-empty string');
            }
            if (field.forbid !== undefined && value.includes(field.forbid.text)) {
                return refuse(400, field.forbid.code, field.forbid.message);
            }
            return value.trim();
    }
}
/**
 * Validate one write request and produce its argv template and bindings.
 *
 * The shared compare-and-set fields and the route's own fields share one
 * validator, so an endpoint never re-states what a write body looks like.
 * @param spec - matched route.
 * @param params - path bindings.
 * @param query - request search parameters.
 * @param body - parsed request body.
 * @returns the argv template with its bindings, or the refusal to answer with.
 */
export function readWrite(spec, params, query, body) {
    const queryRead = readQuery(spec, params, query);
    if ('status' in queryRead)
        return queryRead;
    const bindings = { ...queryRead.bindings };
    for (const [name, value] of Object.entries(params)) {
        const prefix = spec.ids?.[name];
        if (prefix !== undefined && !isIdentity(prefix, value)) {
            return refuse(400, 'INVALID_ID', name + ' must be ' + prefix + '- followed by a 26-character ULID');
        }
        const pattern = spec.patterns?.[name];
        if (pattern !== undefined && !pattern.test(value)) {
            return refuse(400, 'INVALID_PARAM', name + ' must match ' + pattern.source);
        }
    }
    let template = spec.argv;
    let fields = [...(spec.body ?? [])];
    let required = [...(spec.required ?? [])];
    let exclusive = spec.exactlyOne;
    if (spec.actions !== undefined) {
        const actionName = body[spec.actions.field];
        if (typeof actionName !== 'string' || spec.actions.cases[actionName] === undefined) {
            return refuse(400, 'UNKNOWN_ACTION', spec.actions.field + ' must be one of ' + Object.keys(spec.actions.cases).join(', '));
        }
        const action = spec.actions.cases[actionName];
        template = action.argv;
        fields = [...(action.body ?? [])];
        required = [...required, ...(action.required ?? [])];
        exclusive = action.exactlyOne ?? exclusive;
    }
    // A field's own declaration is what makes it mandatory; the route's list is
    // for shared fields it needs to insist on.
    for (const field of fields) {
        if (field.required === true)
            required.push(field.name);
    }
    const revision = spec.revision ?? 'required';
    if (revision === 'required')
        required.push(REVISION_FIELD.name);
    if (revision !== 'none')
        fields.push(REVISION_FIELD);
    const writableShared = spec.shared ?? SHARED_WRITE_FIELDS;
    const acceptedFields = new Set(fields.map(field => field.name));
    for (const field of writableShared)
        acceptedFields.add(field.name);
    if (spec.actions !== undefined)
        acceptedFields.add(spec.actions.field);
    // Silently dropping a field would let a caller believe a filter or an
    // idempotency key was in effect: say which fields this endpoint does not take.
    const unknownFields = Object.keys(body).filter(name => !acceptedFields.has(name));
    if (unknownFields.length > 0) {
        const hints = unknownFields
            .map(name => spec.unknownFieldHints?.[name]
            ?? (name === REVISION_FIELD.name && revision === 'none'
                ? 'this endpoint has no revision to compare, so it takes no expectedRevision'
                : undefined))
            .filter((hint) => hint !== undefined);
        // Naming what the route does take is what lets a caller fix the request
        // without guessing.
        const accepted = [...acceptedFields].join(', ');
        return {
            status: 400,
            body: {
                ok: false,
                error: {
                    code: 'UNKNOWN_FIELDS',
                    message: 'this route does not accept ' + unknownFields.join(', ')
                        + '; it takes: ' + accepted
                        + (hints.length === 0 ? '' : '; ' + hints.join('; ')),
                },
                unknownFields,
            },
        };
    }
    for (const name of required) {
        if (body[name] === undefined)
            return refuse(400, 'INVALID_REQUEST', name + ' is required');
    }
    // Two names for one thing are never merged silently.
    if (exclusive !== undefined) {
        const given = exclusive.filter(name => body[name] !== undefined);
        if (given.length !== 1) {
            return refuse(400, 'INVALID_REQUEST', 'exactly one of ' + exclusive.join(', ')
                + ' must be given (' + (given.length === 0 ? 'none was' : 'both were') + '), not both');
        }
    }
    for (const field of [...fields, ...(spec.shared ?? SHARED_WRITE_FIELDS)]) {
        const value = fieldValue(field, body[field.name]);
        if (value !== undefined && isRefusal(value))
            return value;
        if (value !== undefined)
            bindings[field.name] = value;
    }
    if (template === undefined)
        return refuse(500, 'ROUTE_MISCONFIGURED', spec.path + ' declares neither argv nor actions');
    const missing = templateMissing(template, bindings);
    if (missing !== undefined)
        return refuse(400, 'INVALID_REQUEST', missing + ' is required');
    // Shared compare-and-set flags are appended here rather than repeated in every
    // table entry: a template names the domain's own flags and identity, and the
    // executor adds the ones every write shares.
    const named = new Set(template.flatMap((element) => {
        const placeholder = /^\{(\w+)\}$/u.exec(element);
        return placeholder === null ? [] : [placeholder[1] ?? ''];
    }));
    const sharedFields = spec.shared ?? SHARED_WRITE_FIELDS;
    const shared = revision === 'none' ? sharedFields : [REVISION_FIELD, ...sharedFields];
    const argv = [...template];
    for (const field of shared) {
        if (named.has(field.name))
            continue;
        if (bindings[field.name] === undefined)
            continue;
        // A shared field always travels as a flag; one without a flag cannot be sent.
        if (field.flag === undefined)
            continue;
        argv.push(field.flag, '{' + field.name + '}');
    }
    return { argv, bindings };
}
/** Whether one validated value is a refusal rather than a binding. */
function isRefusal(value) {
    return typeof value === 'object' && value !== null && 'status' in value && 'body' in value;
}
/** The first placeholder one template needs but no binding supplies. */
function templateMissing(template, bindings) {
    for (const element of template) {
        const placeholder = /^\{(\w+)\}$/u.exec(element);
        if (placeholder === null)
            continue;
        const name = placeholder[1] ?? '';
        const value = bindings[name];
        if (value === undefined || value === '' || value === false)
            continue;
        if (Array.isArray(value) && value.length === 0)
            return name;
    }
    return undefined;
}
/**
 * Map a refused pm invocation onto HTTP.
 *
 * pm reports a compare-and-set conflict with exit code 3 and prints the
 * conflict object on stdout, which becomes a 409 passed through unchanged.
 * Exit code 2 is a well-formed request pm refused on its own terms and becomes
 * 422. Anything else means the command itself failed.
 * @param code - process exit code.
 * @param stdout - captured stdout.
 * @param stderr - captured stderr.
 * @returns the status and body to send.
 */
export function commandFailure(code, stdout, stderr, failureStatuses) {
    const parsed = parseObject(stdout);
    const message = firstLine(stderr);
    if (parsed !== undefined && failureStatuses !== undefined) {
        const reported = parsed.error;
        const reportedCode = typeof reported === 'object' && reported !== null
            ? reported.code
            : undefined;
        if (typeof reportedCode === 'string' && failureStatuses[reportedCode] !== undefined) {
            return { status: failureStatuses[reportedCode] ?? 502, body: parsed };
        }
    }
    if (code === 3)
        return { status: 409, body: parsed ?? { ok: false, error: { code: 'COMMAND_CONFLICT', message } } };
    if (code === 2)
        return { status: 422, body: parsed ?? { ok: false, error: { code: 'COMMAND_REFUSED', message } } };
    return { status: 502, body: parsed ?? { ok: false, error: { code: 'COMMAND_FAILED', message } } };
}
/** Parse one JSON object, or undefined when the text is not one. */
export function parseObject(text) {
    try {
        const value = JSON.parse(text);
        return typeof value === 'object' && value !== null && !Array.isArray(value)
            ? value
            : undefined;
    }
    catch {
        return undefined;
    }
}
/** First non-empty line of one message, bounded for a response body. */
export function firstLine(text) {
    const line = (text.split('\n')[0] ?? '').trim();
    return line.length <= 400 ? line : line.slice(0, 399) + '…';
}
/** Envelope keys lifted to the top level when pm reported them. */
const ENVELOPE_KEYS = ['entityId', 'revision', 'source', 'observedAt', 'auditEventId'];
/**
 * Shape one successful write reply.
 *
 * Only fields pm actually reported are carried: a payload that later gains a
 * field reaches the workbench unchanged, and a missing one is omitted rather
 * than invented.
 * @param parsed - the object pm printed.
 * @returns the reply body.
 */
export function successEnvelope(parsed, flattenData = false) {
    const lifted = new Set([...ENVELOPE_KEYS, 'ok', 'inboxId']);
    const inner = parsed.data;
    const flat = flattenData && typeof inner === 'object' && inner !== null
        ? inner
        : undefined;
    const data = flat === undefined ? {} : { ...flat };
    if (flat === undefined) {
        for (const [key, value] of Object.entries(parsed)) {
            if (!lifted.has(key))
                data[key] = value;
        }
    }
    const body = { ok: true };
    const entityId = parsed.entityId ?? parsed.inboxId;
    if (entityId !== undefined)
        body.entityId = entityId;
    for (const key of ENVELOPE_KEYS) {
        if (key !== 'entityId' && parsed[key] !== undefined)
            body[key] = parsed[key];
    }
    body.data = data;
    return body;
}
/**
 * Shape one successful read reply, applying a caller's row limit.
 * @param parsed - the object pm printed.
 * @param limit - maximum rows to return, or undefined for all of them.
 * @returns the reply body.
 */
export function listBody(parsed, limit, flattenData = false) {
    const inner = parsed.data;
    const data = flattenData && typeof inner === 'object' && inner !== null
        ? { ...inner }
        : { ...parsed };
    delete data.ok;
    if (limit !== undefined) {
        // pm's list payloads name their rows differently per domain; trim whichever
        // array the payload carries rather than insisting on one spelling.
        for (const key of ['entries', 'tasks', 'proposals', 'groups', 'workspaces', 'memories', 'sessions', 'projects']) {
            const rows = data[key];
            if (Array.isArray(rows))
                data[key] = rows.slice(0, limit);
        }
    }
    return { ok: true, data };
}
/**
 * The capability report: what this service serves, and what pm cannot do yet.
 * @param pmVersion - version string pm reported, or null when it did not answer.
 * @param config - configuration file every invocation names.
 * @param layout - where the launcher, configuration, and workbench were found,
 *   so a deployment can be diagnosed from the service itself.
 * @returns the report body.
 */
export function capabilities(pmVersion, config, layout) {
    return {
        ok: true,
        data: {
            pmVersion,
            config,
            endpoints: DOMAIN_ROUTES.map((spec) => {
                const endpoint = {
                    method: spec.method,
                    path: spec.path,
                    write: spec.write === true,
                };
                if (spec.notForwarded !== undefined)
                    endpoint.notForwarded = spec.notForwarded;
                return endpoint;
            }),
            hostOwnedFlags: HOST_OWNED_FLAGS,
            unavailable: UNSUPPORTED_ENDPOINTS,
            ...(layout === undefined ? {} : { layout }),
        },
    };
}
/**
 * Validate one read request and produce its argv template and bindings.
 * @param spec - matched route.
 * @param params - path bindings.
 * @param query - request search parameters.
 * @returns the argv template with its bindings, or the refusal to answer with.
 */
export function readRead(spec, params, query) {
    for (const [name, value] of Object.entries(params)) {
        const prefix = spec.ids?.[name];
        if (prefix !== undefined && !isIdentity(prefix, value)) {
            return refuse(400, 'INVALID_ID', name + ' must be ' + prefix + '- followed by a 26-character ULID');
        }
        const pattern = spec.patterns?.[name];
        if (pattern !== undefined && !pattern.test(value)) {
            return refuse(400, 'INVALID_PARAM', name + ' must match ' + pattern.source);
        }
    }
    if (spec.argv === undefined)
        return refuse(500, 'ROUTE_MISCONFIGURED', spec.path + ' declares no argv');
    const read = readQuery(spec, params, query);
    if ('status' in read)
        return read;
    return { argv: spec.argv, bindings: read.bindings };
}
/**
 * Read one caller's row limit.
 * @param query - request search parameters.
 * @returns the limit, undefined when none was asked for, or the refusal to answer with.
 */
export function readLimit(query) {
    const raw = query.get('limit');
    if (raw === null)
        return {};
    const parsed = Number(raw);
    if (!Number.isInteger(parsed) || parsed < 1) {
        return refuse(400, 'INVALID_LIMIT', 'limit must be a positive integer');
    }
    return { limit: parsed };
}
//# sourceMappingURL=domain-routes.js.map