import { execFile } from "node:child_process";
import { readFile } from "node:fs/promises";
import { basename, dirname, join } from "node:path";
import { accessSync, constants, statSync } from "node:fs";
import { homedir } from "node:os";
import { fileURLToPath } from "node:url";
//#region lib/types/domain-routes.js
/** Identity shape per domain, checked before any argv is built. */
const ID_PATTERNS = {
	inbox: /* @__PURE__ */ new RegExp("^inbox-[0-9A-HJKMNP-TV-Z]{26}$", "u"),
	task: /* @__PURE__ */ new RegExp("^task-[0-9A-HJKMNP-TV-Z]{26}$", "u"),
	proposal: /* @__PURE__ */ new RegExp("^proposal-[0-9A-HJKMNP-TV-Z]{26}$", "u"),
	memory: /* @__PURE__ */ new RegExp("^memory-[0-9A-HJKMNP-TV-Z]{26}$", "u")
};
/** Fields every mutating route accepts; `expectedRevision` is added per {@link RevisionRule}. */
const SHARED_WRITE_FIELDS = [
	{
		name: "actor",
		flag: "--actor",
		kind: "enum",
		values: [
			"human",
			"ai",
			"system"
		]
	},
	{
		name: "reason",
		flag: "--reason",
		kind: "string"
	},
	{
		name: "idempotencyKey",
		flag: "--idempotency-key",
		kind: "string"
	},
	{
		name: "dryRun",
		flag: "--dry-run",
		kind: "boolean"
	}
];
/** The revision field a write route adds when it accepts one. */
const REVISION_FIELD = {
	name: "expectedRevision",
	flag: "--expected-revision",
	kind: "int"
};
/**
* Endpoints §6 names but pm's CLI does not implement yet. They are reported by
* /ui-pm/capabilities and deliberately absent from {@link DOMAIN_ROUTES}: a
* route is added here only when the command it would run exists - or, for a route
* that ships ahead of its command, when the flag guard's pending list names it.
*/
const UNSUPPORTED_ENDPOINTS = [
	{
		method: "POST",
		path: "/ui-pm/tasks/:id/submit-review",
		reason: "pm task submit-review is not part of the CLI yet (P3 acceptance flow)"
	},
	{
		method: "POST",
		path: "/ui-pm/tasks/:id/accept",
		reason: "pm task accept is not part of the CLI yet (P3 acceptance flow)"
	},
	{
		method: "POST",
		path: "/ui-pm/tasks/:id/return",
		reason: "pm task return is not part of the CLI yet (P3 acceptance flow)"
	},
	{
		method: "POST",
		path: "/ui-pm/tasks/:id/dispatch",
		reason: "this service never dispatches work: execution-config plus handoff is the whole contract, and no endpoint may claim a run started"
	}
];
/**
* Flags every command accepts but this service deliberately never forwards.
*
* They are properties of the Host invocation, not of a request: a caller that
* could name the configuration file or the DSH home could point the launcher at
* another library or another instance, and `--yes` exists only for invocations
* that never named a configuration file at all.
*/
const HOST_OWNED_FLAGS = [
	{
		flag: "--config",
		reason: "the host names one configuration file; a request must not repoint the launcher"
	},
	{
		flag: "--dsh-home",
		reason: "the running profile owns the DSH home; a request must not target another instance"
	},
	{
		flag: "--yes",
		reason: "only needed when no configuration file is named, which this service always does"
	},
	{
		flag: "--json",
		reason: "every invocation already asks for JSON"
	},
	{
		flag: "--help",
		reason: "not a request parameter"
	}
];
/** The command surface, one entry per endpoint. */
const DOMAIN_ROUTES = [
	{
		method: "GET",
		path: "/ui-pm/inbox",
		argv: [
			"inbox",
			"list",
			"--status",
			"{status}",
			"--json"
		],
		query: [{ name: "status" }]
	},
	{
		method: "POST",
		path: "/ui-pm/inbox/:id/archive",
		write: true,
		argv: [
			"inbox",
			"archive",
			"{id}",
			"--json"
		],
		ids: { id: "inbox" }
	},
	{
		method: "POST",
		path: "/ui-pm/inbox/:id/snooze",
		write: true,
		argv: [
			"inbox",
			"snooze",
			"{id}",
			"--until",
			"{until}",
			"--json"
		],
		ids: { id: "inbox" },
		body: [{
			name: "until",
			flag: "--until",
			kind: "string",
			required: true
		}]
	},
	{
		method: "POST",
		path: "/ui-pm/inbox/:id/merge",
		write: true,
		argv: [
			"inbox",
			"merge",
			"{id}",
			"--into",
			"{into}",
			"--json"
		],
		ids: { id: "inbox" },
		body: [{
			name: "into",
			flag: "--into",
			kind: "string",
			required: true
		}]
	},
	{
		method: "POST",
		path: "/ui-pm/inbox/:id/note",
		write: true,
		argv: [
			"inbox",
			"note",
			"{id}",
			"--project",
			"{project}",
			"--json"
		],
		ids: { id: "inbox" },
		body: [{
			name: "project",
			flag: "--project",
			kind: "string"
		}]
	},
	{
		method: "POST",
		path: "/ui-pm/inbox/:id/dismiss",
		write: true,
		argv: [
			"inbox",
			"dismiss",
			"{id}",
			"--json"
		],
		ids: { id: "inbox" },
		required: ["reason"]
	},
	{
		method: "GET",
		path: "/ui-pm/inbox/:id",
		argv: [
			"inbox",
			"history",
			"{id}",
			"--json"
		],
		ids: { id: "inbox" }
	},
	{
		method: "POST",
		path: "/ui-pm/inbox/:id/annotate",
		write: true,
		argv: [
			"inbox",
			"annotate",
			"{id}",
			"--text",
			"{text}",
			"--json"
		],
		ids: { id: "inbox" },
		body: [{
			name: "text",
			flag: "--text",
			kind: "string",
			required: true
		}]
	},
	{
		method: "POST",
		path: "/ui-pm/inbox/:id/pin",
		write: true,
		argv: [
			"inbox",
			"pin",
			"{id}",
			"--json"
		],
		ids: { id: "inbox" }
	},
	{
		method: "POST",
		path: "/ui-pm/inbox/:id/unpin",
		write: true,
		argv: [
			"inbox",
			"unpin",
			"{id}",
			"--json"
		],
		ids: { id: "inbox" }
	},
	{
		method: "POST",
		path: "/ui-pm/inbox/:id/edit",
		write: true,
		argv: [
			"inbox",
			"edit",
			"{id}",
			"--text",
			"{text}",
			"--json"
		],
		ids: { id: "inbox" },
		body: [{
			name: "text",
			flag: "--text",
			kind: "string",
			required: true
		}],
		required: ["reason"]
	},
	{
		method: "POST",
		path: "/ui-pm/inbox/:id/set-status",
		write: true,
		argv: [
			"inbox",
			"set-status",
			"{id}",
			"--status",
			"{status}",
			"--json"
		],
		ids: { id: "inbox" },
		body: [{
			name: "status",
			flag: "--status",
			kind: "string",
			required: true
		}]
	},
	{
		method: "GET",
		path: "/ui-pm/workspaces",
		argv: [
			"workspace",
			"list",
			"--project",
			"{project}",
			"--json"
		],
		query: [{
			name: "project",
			required: true
		}]
	},
	{
		method: "GET",
		path: "/ui-pm/workspaces/context",
		argv: [
			"workspace",
			"context",
			"{path}",
			"--no-global",
			"{noGlobal}",
			"--json"
		],
		query: [{
			name: "path",
			required: true
		}, {
			name: "no-global",
			flag: "--no-global",
			as: "noGlobal",
			boolean: true
		}]
	},
	{
		method: "GET",
		path: "/ui-pm/projects",
		argv: [
			"project",
			"list",
			"--in-library-only",
			"{inLibraryOnly}",
			"--json"
		],
		query: [{
			name: "in-library-only",
			flag: "--in-library-only",
			as: "inLibraryOnly",
			boolean: true
		}]
	},
	{
		method: "POST",
		path: "/ui-pm/projects",
		write: true,
		revision: "none",
		shared: [{
			name: "dryRun",
			flag: "--dry-run",
			kind: "boolean"
		}],
		argv: [
			"project",
			"create",
			"{key}",
			"--title",
			"{title}",
			"--path",
			"{path}",
			"--workspace",
			"{workspace}",
			"--json"
		],
		body: [
			{
				name: "key",
				kind: "string",
				required: true
			},
			{
				name: "title",
				flag: "--title",
				kind: "string"
			},
			{
				name: "path",
				flag: "--path",
				kind: "repeat"
			},
			{
				name: "workspace",
				flag: "--workspace",
				kind: "repeat"
			}
		]
	},
	{
		method: "GET",
		path: "/ui-pm/projects/:key/brief",
		argv: [
			"project",
			"brief",
			"get",
			"{key}",
			"--json"
		],
		patterns: { key: /^[A-Za-z0-9._-]+$/u }
	},
	{
		method: "POST",
		path: "/ui-pm/projects/:key/brief",
		write: true,
		revision: "none",
		shared: [{
			name: "reason",
			flag: "--reason",
			kind: "string"
		}, {
			name: "dryRun",
			flag: "--dry-run",
			kind: "boolean"
		}],
		notForwarded: [{
			flag: "--text-file",
			reason: "a request must not read an arbitrary host file into the library; the caller sends the text itself"
		}],
		unknownFieldHints: {
			idempotencyKey: "this command has no idempotency key: it guards duplicates with the digest compare-and-set, so re-sending the same text changes nothing (changed:false) and a file that moved on answers 409",
			expectedRevision: "this command compares the whole-file digest, not a revision: send the expectedDigest the read returned"
		},
		argv: [
			"project",
			"brief",
			"set",
			"{key}",
			"--section",
			"{section}",
			"--text",
			"{text}",
			"--actor",
			"{actor}",
			"--expect-digest",
			"{expectedDigest}",
			"--json"
		],
		patterns: { key: /^[A-Za-z0-9._-]+$/u },
		body: [
			{
				name: "section",
				flag: "--section",
				kind: "enum",
				required: true,
				values: [
					"goal",
					"scope",
					"nonGoal",
					"acceptance",
					"milestones",
					"risks"
				]
			},
			{
				name: "text",
				flag: "--text",
				kind: "string",
				required: true,
				allowEmpty: true
			},
			{
				name: "expectedDigest",
				flag: "--expect-digest",
				kind: "string",
				required: true
			},
			{
				name: "actor",
				flag: "--actor",
				kind: "enum",
				required: true,
				values: [
					"human",
					"ai",
					"system"
				]
			}
		]
	},
	{
		method: "GET",
		path: "/ui-pm/projects/:id/context",
		argv: [
			"project",
			"context",
			"{id}",
			"--no-global",
			"{noGlobal}",
			"--json"
		],
		query: [{
			name: "no-global",
			flag: "--no-global",
			as: "noGlobal",
			boolean: true
		}]
	},
	{
		method: "GET",
		path: "/ui-pm/tasks",
		argv: [
			"task",
			"list",
			"--project",
			"{project}",
			"--status",
			"{status}",
			"--json"
		],
		query: [{
			name: "project",
			required: true
		}, { name: "status" }]
	},
	{
		method: "GET",
		path: "/ui-pm/tasks/:id",
		argv: [
			"task",
			"show",
			"--project",
			"{project}",
			"{id}",
			"--json"
		],
		ids: { id: "task" },
		query: [{
			name: "project",
			required: true
		}]
	},
	{
		method: "POST",
		path: "/ui-pm/tasks",
		write: true,
		revision: "none",
		argv: [
			"task",
			"create",
			"--project",
			"{project}",
			"--title",
			"{title}",
			"--goal",
			"{goal}",
			"--non-goal",
			"{nonGoal}",
			"--criterion",
			"{criterion}",
			"--from-inbox",
			"{fromInbox}",
			"--ai",
			"{ai}",
			"--assignee",
			"{assignee}",
			"--id",
			"{id}",
			"--json"
		],
		body: [
			{
				name: "project",
				flag: "--project",
				kind: "string",
				required: true
			},
			{
				name: "title",
				flag: "--title",
				kind: "string",
				required: true
			},
			{
				name: "goal",
				flag: "--goal",
				kind: "string"
			},
			{
				name: "nonGoal",
				flag: "--non-goal",
				kind: "string"
			},
			{
				name: "criterion",
				flag: "--criterion",
				kind: "repeat"
			},
			{
				name: "fromInbox",
				flag: "--from-inbox",
				kind: "string"
			},
			{
				name: "ai",
				flag: "--ai",
				kind: "boolean"
			},
			{
				name: "assignee",
				flag: "--assignee",
				kind: "string"
			},
			{
				name: "id",
				flag: "--id",
				kind: "string"
			}
		]
	},
	{
		method: "PATCH",
		path: "/ui-pm/tasks/:id",
		write: true,
		ids: { id: "task" },
		actions: {
			field: "action",
			cases: {
				transition: {
					argv: [
						"task",
						"transition",
						"{id}",
						"--project",
						"{project}",
						"--to",
						"{to}",
						"--json"
					],
					body: [{
						name: "project",
						flag: "--project",
						kind: "string",
						required: true
					}, {
						name: "to",
						flag: "--to",
						kind: "string",
						required: true
					}]
				},
				check: {
					argv: [
						"task",
						"check",
						"{id}",
						"--project",
						"{project}",
						"--criterion-id",
						"{criterionId}",
						"--index",
						"{index}",
						"--uncheck",
						"{uncheck}",
						"--json"
					],
					exactlyOne: ["criterionId", "index"],
					notForwarded: [{
						flag: "--criterion",
						reason: "the deprecated number-or-text selector: this service names a criterion by its stable id, so a reordered file cannot retarget a check"
					}],
					body: [
						{
							name: "project",
							flag: "--project",
							kind: "string",
							required: true
						},
						{
							name: "criterionId",
							flag: "--criterion-id",
							kind: "string"
						},
						{
							name: "index",
							flag: "--index",
							kind: "int",
							deprecated: "prefer criterionId: a stable per-criterion id; a file index shifts when criteria are reordered"
						},
						{
							name: "uncheck",
							flag: "--uncheck",
							kind: "boolean"
						}
					]
				}
			}
		}
	},
	{
		method: "POST",
		path: "/ui-pm/tasks/:id/evidence",
		write: true,
		ids: { id: "task" },
		required: ["actor"],
		argv: [
			"task",
			"evidence",
			"add",
			"{id}",
			"--project",
			"{project}",
			"--criterion-id",
			"{criterionId}",
			"--kind",
			"{kind}",
			"--result",
			"{result}",
			"--ref",
			"{ref}",
			"--note",
			"{note}",
			"--json"
		],
		body: [
			{
				name: "project",
				flag: "--project",
				kind: "string",
				required: true
			},
			{
				name: "criterionId",
				flag: "--criterion-id",
				kind: "string",
				required: true
			},
			{
				name: "kind",
				flag: "--kind",
				kind: "enum",
				required: true,
				values: [
					"test",
					"build",
					"manual",
					"artifact",
					"review",
					"other"
				]
			},
			{
				name: "result",
				flag: "--result",
				kind: "enum",
				required: true,
				values: [
					"pass",
					"fail",
					"info"
				]
			},
			{
				name: "ref",
				flag: "--ref",
				kind: "string",
				required: true,
				forbid: {
					text: "|",
					code: "INVALID_EVIDENCE_REF",
					message: "ref must not contain |; put the longer text in note"
				}
			},
			{
				name: "note",
				flag: "--note",
				kind: "string"
			}
		],
		unknownFieldHints: {
			index: "this command names a criterion by its stable id: send criterionId",
			criterion: "this command names a criterion by its stable id: send criterionId"
		},
		notes: ["pm defaults --actor to human; this route requires actor, because an HTTP caller has no terminal context and a wrong audit attribution is worse than a refusal"]
	},
	{
		method: "GET",
		path: "/ui-pm/prompt",
		flattenData: true,
		argv: [
			"prompt",
			"get",
			"--scope",
			"{scope}",
			"--render",
			"{render}",
			"--json"
		],
		query: [{
			name: "scope",
			required: true
		}, {
			name: "render",
			boolean: true
		}],
		notes: [
			"reads projects/proj-<key>/prompt.org through pm prompt get; a missing file is exists:false with revision 0, never a 404",
			"the answer is {scope, exists, revision, updatedAt, savedBy, blocks[{name, text, include}]}: no injection-side field rides along, and a hand-written file with no :PM_REVISION: reports revision 0",
			"--render adds a render object beside the payload inside the envelope: the assembled text plus one entry per block with its expression, resolved path, line and byte counts, and the truncation flag (内部记录/25 §4)"
		]
	},
	{
		method: "GET",
		path: "/ui-pm/prompts",
		flattenData: true,
		argv: [
			"prompt",
			"list",
			"--json"
		],
		notes: [
			"the answer is pm prompt list with the command data lifted: {onlySaved, count, items[{scope, revision, updatedAt, savedBy, blockCount, path}]}, and every path is relative to the library root",
			"read-only: it never writes and compares no revision; a project that has recorded nothing simply is not in items",
			"the singular route stays singular: omitting scope on GET /ui-pm/prompt must never answer a list - a page cannot guess a return type from a missing parameter; if a list mode is ever wanted it needs an explicit discriminator in the payload (e.g. shape:list) rather than an implied one"
		]
	},
	{
		method: "GET",
		path: "/ui-pm/prompt-exports",
		flattenData: true,
		failureStatuses: { PROMPT_EXPORTS_CORRUPT: 500 },
		argv: [
			"prompt",
			"exports",
			"list",
			"--scope",
			"{scope}",
			"--q",
			"{q}",
			"--json"
		],
		query: [{ name: "scope" }, { name: "q" }],
		notes: [
			"answers the command data lifted: {records[{id, project, path, name, fmt, bytes, blocks, savedAt, snapshot}]}; scope and q are both optional and only what the caller sends is forwarded",
			"read-only over a derived store: the records live in .local/prompt-exports.json, never in projects/**",
			"a corrupt derived store answers 500 (PROMPT_EXPORTS_CORRUPT): that is server state, not the caller request, so it is not dressed up as a 422",
			"interface provisional: `pm prompt exports` is live; the flag guard keeps this surface aligned with its parser"
		]
	},
	{
		method: "POST",
		path: "/ui-pm/prompt-exports",
		write: true,
		revision: "none",
		shared: [],
		flattenData: true,
		failureStatuses: {
			PROMPT_EXPORT_BAD_PAYLOAD: 400,
			PROMPT_EXPORTS_CORRUPT: 500
		},
		argv: [
			"prompt",
			"exports",
			"add",
			"--scope",
			"{scope}",
			"--path",
			"{path}",
			"--name",
			"{name}",
			"--fmt",
			"{fmt}",
			"--text",
			"{text}",
			"--snapshot",
			"{snapshot}",
			"--blocks-json",
			"{blocksData}",
			"--idempotency-key",
			"{idempotencyKey}",
			"--json"
		],
		body: [
			{
				name: "scope",
				flag: "--scope",
				kind: "string",
				required: true
			},
			{
				name: "path",
				flag: "--path",
				kind: "string",
				required: true
			},
			{
				name: "name",
				flag: "--name",
				kind: "string",
				required: true
			},
			{
				name: "fmt",
				flag: "--fmt",
				kind: "enum",
				required: true,
				values: [
					"md",
					"txt",
					"org"
				]
			},
			{
				name: "text",
				flag: "--text",
				kind: "string"
			},
			{
				name: "snapshot",
				flag: "--snapshot",
				kind: "string"
			},
			{
				name: "blocksData",
				flag: "--blocks-json",
				kind: "string"
			},
			{
				name: "idempotencyKey",
				flag: "--idempotency-key",
				kind: "string"
			}
		],
		notForwarded: [
			{
				flag: "--payload-file",
				reason: "the route maps the POST body onto the field flags directly; the payload file form reads a host path, which an HTTP request must not name"
			},
			{
				flag: "--payload-b64",
				reason: "the route forwards the body field by field rather than re-encoding it as base64; the payload form exists for a caller that already holds one JSON blob"
			},
			{
				flag: "--text-file",
				reason: "the exported text travels as the request body; reading it back from a host path is a terminal convenience, not something a request may choose"
			}
		],
		notes: [
			"writes one derived record and nothing else: the exported file is the browser user choice, and the service never claims it wrote that path",
			"idempotencyKey rides straight through: replaying the same export does not append a second record",
			"PROMPT_EXPORT_BAD_PAYLOAD answers 400 (invalid JSON reached the command); PROMPT_EXPORT_BAD_FMT is unreachable here because the route checks fmt against its enum first, so a bad format is 400 INVALID_BODY",
			"the body maps 1:1 onto the command flags (scope, path, name, fmt, text, snapshot, blocks-json, idempotency-key); the payload/base64/file forms are declared omissions"
		]
	},
	{
		method: "DELETE",
		path: "/ui-pm/prompt-exports/:id",
		write: true,
		revision: "none",
		shared: [],
		flattenData: true,
		failureStatuses: {
			PROMPT_EXPORT_NOT_FOUND: 404,
			PROMPT_EXPORTS_CORRUPT: 500
		},
		patterns: { id: /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/ },
		argv: [
			"prompt",
			"exports",
			"delete",
			"--id",
			"{id}",
			"--json"
		],
		notes: [
			"deletes one derived record only: the exported file and prompt.org stay untouched",
			"a missing record answers 404 (PROMPT_EXPORT_NOT_FOUND) rather than a generic 422; the record store is derived, so the exported file may still exist",
			"answers the command data lifted: {deleted: 1}",
			"interface provisional: `pm prompt exports delete` is live; the flag guard keeps this surface aligned with its parser"
		]
	},
	{
		method: "PUT",
		path: "/ui-pm/prompt",
		write: true,
		flattenData: true,
		argv: [
			"prompt",
			"set",
			"--scope",
			"{scope}",
			"--block-json",
			"{blocks}",
			"--json"
		],
		required: ["actor"],
		body: [{
			name: "scope",
			flag: "--scope",
			kind: "string",
			required: true
		}, {
			name: "blocks",
			flag: "--block-json",
			kind: "json-repeat",
			required: true
		}],
		shared: [
			{
				name: "actor",
				flag: "--actor",
				kind: "enum",
				values: ["human", "ai"]
			},
			{
				name: "reason",
				flag: "--reason",
				kind: "string"
			},
			{
				name: "idempotencyKey",
				flag: "--idempotency-key",
				kind: "string"
			},
			{
				name: "dryRun",
				flag: "--dry-run",
				kind: "boolean"
			}
		],
		failureStatuses: { RESERVED_BLOCK_NAME: 400 },
		notForwarded: [{
			flag: "--blocks-json",
			reason: "the route sends the repeatable --block-json so argv order encodes block order; the whole-array form exists for a caller that already built one JSON value"
		}, {
			flag: "--file",
			reason: "reading an org file (or stdin) is the terminal path: a request must not name an arbitrary host path, and the executor has no stdin channel"
		}],
		notes: [
			"never rewrites an existing prompt.org: expectedRevision is required, 0 means create-only, and a conflict is pm exit 3 -> 409 whose payload carries error.currentRevision",
			"blocks travel as repeated --block-json elements in array order (pm also accepts --file/- and a whole-array --blocks-json, which a route cannot use), so pm assembles the org file and gives each block its :ID: drawer - this half never builds org text",
			"refusals the caller can meet: RESERVED_BLOCK_NAME (block name prompt-meta is reserved) -> 400; AI_CANNOT_EDIT (an existing prompt.org edited as actor=ai) -> 422; BLOCK_DELETE_UNSUPPORTED (the request drops a block) -> 422",
			"an idempotencyKey belongs to one intended change: replaying it answers as a replay - 200 with changed:0 and the revision where it was - and a key that was already used on that file (even by an earlier attempt) answers the next call the same way, so a page must mint a fresh key per save",
			"a successful save advances the file revision and the block revisions together; a live acceptance reads create revision 1, a stale revision 409 with error.currentRevision, an edit at revision 2, a keyed save at revision 3 and its replay unchanged at 3, and a reserved block name refused as 400",
			"the payload is the command data lifted to one level (flattenData): {scope, file, revision, changed, idempotent, dryRun} for a write and the six documented fields for the read, never data.data",
			"pm answers exit 2 REVISION_REQUIRED without a revision, which this route never provokes: the field is required, so body validation refuses first",
			"actor is required and accepts only {human, ai}, deliberately with no default: a route that filled in human would let automation be recorded as a person editing a human file, which is the red line bypassed (fail-open); refusing a body without it is fail-closed. The command recording its own default as ai points the same way, and the page sends human explicitly",
			"note 2026-10-18 (mechanism explained, appended): the one file-revision stall observed (run C) is a pre-fix shape - the client key went straight to the meta write, so a leftover replay record for that key skipped the meta bump while the block write with its derived key still landed.",
			"that stall needs a stale leftover key, so this revision does not reproduce it and that is expected: the same key answers a replay (nothing written, changed:0), a fresh key changes content and the revision advances by one; pm pins the half-write with tests/test_prompt.py::test_same_key_different_content_never_half_writes (reverting the derived meta key turns that test red). The two raw logs match too: run C shows changed:1 with idempotent:true while the revision stayed 1, run I uses a per-run key, reads changed:0 and then revision 2."
		]
	},
	{
		method: "GET",
		path: "/ui-pm/tasks/:id/execution-config",
		argv: [
			"task",
			"execution-config",
			"get",
			"{id}",
			"--json"
		],
		ids: { id: "task" }
	},
	{
		method: "POST",
		path: "/ui-pm/tasks/:id/execution-config",
		write: true,
		argv: [
			"task",
			"execution-config",
			"set",
			"{id}",
			"--workspace",
			"{workspace}",
			"--instance",
			"{instance}",
			"--project",
			"{project}",
			"--memory",
			"{memory}",
			"--session",
			"{session}",
			"--note",
			"{note}",
			"--json"
		],
		ids: { id: "task" },
		body: [
			{
				name: "workspace",
				flag: "--workspace",
				kind: "string",
				required: true
			},
			{
				name: "instance",
				flag: "--instance",
				kind: "string"
			},
			{
				name: "project",
				flag: "--project",
				kind: "string"
			},
			{
				name: "memory",
				flag: "--memory",
				kind: "repeat"
			},
			{
				name: "session",
				flag: "--session",
				kind: "string"
			},
			{
				name: "note",
				flag: "--note",
				kind: "string"
			}
		]
	},
	{
		method: "POST",
		path: "/ui-pm/tasks/:id/link-session",
		write: true,
		argv: [
			"task",
			"link-session",
			"{id}",
			"--session",
			"{session}",
			"--instance",
			"{instance}",
			"--json"
		],
		ids: { id: "task" },
		body: [{
			name: "session",
			flag: "--session",
			kind: "string",
			required: true
		}, {
			name: "instance",
			flag: "--instance",
			kind: "string"
		}]
	},
	{
		method: "POST",
		path: "/ui-pm/tasks/:id/unlink-session",
		write: true,
		argv: [
			"task",
			"unlink-session",
			"{id}",
			"--json"
		],
		ids: { id: "task" },
		required: ["reason"]
	},
	{
		method: "GET",
		path: "/ui-pm/tasks/:id/handoff",
		argv: [
			"task",
			"handoff",
			"{id}",
			"--json"
		],
		ids: { id: "task" }
	},
	{
		method: "GET",
		path: "/ui-pm/proposals",
		argv: [
			"proposal",
			"list",
			"--status",
			"{status}",
			"--json"
		],
		query: [{ name: "status" }]
	},
	{
		method: "GET",
		path: "/ui-pm/proposals/:id",
		argv: [
			"proposal",
			"show",
			"{id}",
			"--json"
		],
		ids: { id: "proposal" }
	},
	{
		method: "POST",
		path: "/ui-pm/proposals",
		write: true,
		revision: "optional",
		argv: [
			"proposal",
			"create",
			"--source-inbox",
			"{sourceInbox}",
			"--change",
			"{change}",
			"--criterion",
			"{criterion}",
			"--risk",
			"{risk}",
			"--action",
			"{action}",
			"--title",
			"{title}",
			"--project",
			"{project}",
			"--plan-revision",
			"{planRevision}",
			"--created-by",
			"{createdBy}",
			"--allow-duplicate",
			"{allowDuplicate}",
			"--json"
		],
		body: [
			{
				name: "sourceInbox",
				flag: "--source-inbox",
				kind: "string",
				required: true
			},
			{
				name: "change",
				flag: "--change",
				kind: "repeat"
			},
			{
				name: "criterion",
				flag: "--criterion",
				kind: "repeat"
			},
			{
				name: "risk",
				flag: "--risk",
				kind: "repeat"
			},
			{
				name: "action",
				flag: "--action",
				kind: "repeat"
			},
			{
				name: "title",
				flag: "--title",
				kind: "string"
			},
			{
				name: "project",
				flag: "--project",
				kind: "string"
			},
			{
				name: "planRevision",
				flag: "--plan-revision",
				kind: "int"
			},
			{
				name: "createdBy",
				flag: "--created-by",
				kind: "string"
			},
			{
				name: "allowDuplicate",
				flag: "--allow-duplicate",
				kind: "boolean"
			}
		]
	},
	{
		method: "POST",
		path: "/ui-pm/proposals/:id/revise",
		write: true,
		argv: [
			"proposal",
			"revise",
			"{id}",
			"--title",
			"{title}",
			"--change",
			"{changes}",
			"--change-op",
			"{changeOp}",
			"--change-title",
			"{changeTitle}",
			"--criterion",
			"{criterion}",
			"--risk",
			"{risks}",
			"--action",
			"{actions}",
			"--json"
		],
		ids: { id: "proposal" },
		body: [
			{
				name: "title",
				flag: "--title",
				kind: "string"
			},
			{
				name: "changes",
				flag: "--change",
				kind: "json-repeat"
			},
			{
				name: "changeOp",
				flag: "--change-op",
				kind: "repeat"
			},
			{
				name: "changeTitle",
				flag: "--change-title",
				kind: "repeat"
			},
			{
				name: "criterion",
				flag: "--criterion",
				kind: "repeat"
			},
			{
				name: "risks",
				flag: "--risk",
				kind: "repeat"
			},
			{
				name: "actions",
				flag: "--action",
				kind: "repeat"
			}
		]
	},
	{
		method: "POST",
		path: "/ui-pm/proposals/:id/approve",
		write: true,
		argv: [
			"proposal",
			"approve",
			"{id}",
			"--project",
			"{project}",
			"--allow-stale",
			"{allowStale}",
			"--json"
		],
		ids: { id: "proposal" },
		body: [{
			name: "project",
			flag: "--project",
			kind: "string"
		}, {
			name: "allowStale",
			flag: "--allow-stale",
			kind: "boolean"
		}]
	},
	{
		method: "POST",
		path: "/ui-pm/proposals/:id/reject",
		write: true,
		argv: [
			"proposal",
			"reject",
			"{id}",
			"--json"
		],
		ids: { id: "proposal" },
		required: ["reason"]
	},
	{
		method: "GET",
		path: "/ui-pm/memory",
		argv: [
			"memory",
			"list",
			"--type",
			"{type}",
			"--scope",
			"{scope}",
			"--status",
			"{status}",
			"--json"
		],
		query: [
			{ name: "type" },
			{ name: "scope" },
			{ name: "status" }
		]
	},
	{
		method: "GET",
		path: "/ui-pm/memory/candidates",
		argv: [
			"memory",
			"candidates",
			"--status",
			"{status}",
			"--json"
		],
		query: [{ name: "status" }]
	},
	{
		method: "GET",
		path: "/ui-pm/memory/context",
		argv: [
			"memory",
			"context",
			"--scope",
			"{scope}",
			"--task",
			"{task}",
			"--no-global",
			"{noGlobal}",
			"--allow-cross-scope",
			"{allowCrossScope}",
			"--json"
		],
		query: [
			{
				name: "scope",
				required: true
			},
			{ name: "task" },
			{
				name: "no-global",
				flag: "--no-global",
				as: "noGlobal",
				boolean: true
			},
			{
				name: "allow-cross-scope",
				flag: "--allow-cross-scope",
				as: "allowCrossScope",
				boolean: true
			}
		]
	},
	{
		method: "GET",
		path: "/ui-pm/recall",
		argv: [
			"recall",
			"--query",
			"{q}",
			"--scope",
			"{scope}",
			"--type",
			"{type}",
			"--limit",
			"{limit}",
			"--any",
			"{any}",
			"--json"
		],
		query: [
			{
				name: "q",
				required: true
			},
			{ name: "scope" },
			{ name: "type" },
			{ name: "limit" },
			{
				name: "any",
				boolean: true
			}
		],
		notForwarded: [{
			flag: "--include-candidate",
			reason: "outside the P1 read (q/scope/type/limit): widening a search to unconfirmed candidates is a product decision, so the omission is declared until a filter asks for it"
		}, {
			flag: "--include-deprecated",
			reason: "outside the P1 read (q/scope/type/limit): a default search returns live memories, and a history filter can expose this later"
		}]
	},
	{
		method: "POST",
		path: "/ui-pm/memory-candidates",
		write: true,
		revision: "none",
		argv: [
			"memory",
			"add",
			"--text",
			"{text}",
			"--scope",
			"{scope}",
			"--type",
			"{type}",
			"--sources",
			"{sources}",
			"--topic",
			"{topic}",
			"--task-id",
			"{taskId}",
			"--created-by",
			"{createdBy}",
			"--supersedes",
			"{supersedes}",
			"--json"
		],
		body: [
			{
				name: "text",
				flag: "--text",
				kind: "string",
				required: true
			},
			{
				name: "scope",
				flag: "--scope",
				kind: "string",
				required: true
			},
			{
				name: "type",
				flag: "--type",
				kind: "enum",
				required: true,
				values: [
					"fact",
					"decision",
					"gotcha"
				]
			},
			{
				name: "sources",
				flag: "--sources",
				kind: "repeat"
			},
			{
				name: "topic",
				flag: "--topic",
				kind: "string"
			},
			{
				name: "taskId",
				flag: "--task-id",
				kind: "string"
			},
			{
				name: "createdBy",
				flag: "--created-by",
				kind: "string"
			},
			{
				name: "supersedes",
				flag: "--supersedes",
				kind: "string"
			}
		]
	},
	{
		method: "POST",
		path: "/ui-pm/memory-candidates/:id/verify",
		write: true,
		argv: [
			"memory",
			"verify",
			"{id}",
			"--sources",
			"{sources}",
			"--supersedes",
			"{supersedes}",
			"--conflict-with",
			"{conflictWith}",
			"--json"
		],
		ids: { id: "memory" },
		body: [
			{
				name: "sources",
				flag: "--sources",
				kind: "repeat"
			},
			{
				name: "supersedes",
				flag: "--supersedes",
				kind: "string"
			},
			{
				name: "conflictWith",
				flag: "--conflict-with",
				kind: "string"
			}
		]
	},
	{
		method: "POST",
		path: "/ui-pm/memory/:id/discard",
		write: true,
		ids: { id: "memory" },
		required: ["reason"],
		argv: [
			"memory",
			"discard",
			"{id}",
			"--json"
		],
		failureStatuses: {
			REASON_REQUIRED: 400,
			NOT_A_CANDIDATE: 422
		},
		notes: [
			"error mapping: NOT_A_CANDIDATE -> 422 (a VERIFIED memory is deprecated, not discarded), REVISION_CONFLICT -> 409",
			"REASON_REQUIRED -> 400 stays from the command contract, but this route normally never sees it: the body is validated first, so a missing reason answers 400 INVALID_REQUEST and an empty one answers 400 INVALID_BODY, and the command is not run at all",
			"discarding an already DEPRECATED candidate is idempotent: it answers 200 with changed:false and discarded:false"
		]
	},
	{
		method: "POST",
		path: "/ui-pm/memory/:id/deprecate",
		write: true,
		argv: [
			"memory",
			"deprecate",
			"{id}",
			"--superseded-by",
			"{supersededBy}",
			"--json"
		],
		ids: { id: "memory" },
		body: [{
			name: "supersededBy",
			flag: "--superseded-by",
			kind: "string"
		}],
		required: ["reason"]
	}
];
/** Absolute pathname of the capability report. */
const CAPABILITIES_ROUTE = "/ui-pm/capabilities";
/** Refuse one request with a structured error. */
function refuse(status, code, message) {
	return {
		status,
		body: {
			ok: false,
			error: {
				code,
				message
			}
		}
	};
}
/**
* Whether one value carries a domain identity.
* @param prefix - domain the value belongs to.
* @param value - candidate identity.
* @returns true when the value is `<prefix>-<ULID>`.
*/
function isIdentity(prefix, value) {
	return ID_PATTERNS[prefix].test(value);
}
/** The segments of one path pattern, with `:name` markers preserved. */
function segmentsOf(path) {
	return path.split("/").filter((segment) => segment !== "");
}
/**
* Match one request path against the table.
* @param pathname - request pathname, already normalized by the URL parser.
* @param method - request method, or undefined to ask only which methods the path serves.
* @returns the matching spec with its bindings, the methods when only the method is wrong, or undefined.
*/
function matchRoute(pathname, method) {
	const requested = pathname.split("/").filter((segment) => segment !== "");
	const candidates = [];
	for (const spec of DOMAIN_ROUTES) {
		const pattern = segmentsOf(spec.path);
		if (pattern.length !== requested.length) continue;
		const params = {};
		let matched = true;
		for (let index = 0; index < pattern.length; index += 1) {
			const expected = pattern[index] ?? "";
			const actual = requested[index] ?? "";
			if (expected.startsWith(":")) {
				if (actual === "") {
					matched = false;
					break;
				}
				try {
					params[expected.slice(1)] = decodeURIComponent(actual);
				} catch {
					params[expected.slice(1)] = actual;
				}
				continue;
			}
			if (expected !== actual) {
				matched = false;
				break;
			}
		}
		if (matched) candidates.push({
			spec,
			params
		});
	}
	if (candidates.length === 0) return void 0;
	if (method !== void 0) {
		const hit = candidates.find((candidate) => candidate.spec.method === method);
		if (hit !== void 0) return hit;
	}
	return { methods: [...new Set(candidates.map((candidate) => candidate.spec.method))].sort() };
}
/**
* Prefixes every registered route hangs under, so registration follows the table.
* @returns the distinct `/ui-pm/<domain>` prefixes, sorted.
*/
function routePrefixes() {
	const prefixes = /* @__PURE__ */ new Set();
	for (const spec of DOMAIN_ROUTES) {
		const segments = segmentsOf(spec.path);
		prefixes.add("/" + segments.slice(0, 2).join("/"));
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
function buildArgv(argv, bindings, config) {
	const out = ["--config", config];
	for (let index = 0; index < argv.length; index += 1) {
		const element = argv[index] ?? "";
		const placeholder = /^\{(\w+)\}$/u.exec(element);
		if (placeholder === null) {
			out.push(element);
			continue;
		}
		const value = bindings[placeholder[1] ?? ""];
		const previous = argv[index - 1] ?? "";
		const flagBefore = previous.startsWith("--");
		if (value === void 0 || value === false) {
			if (flagBefore) out.pop();
			continue;
		}
		if (value === true) continue;
		if (value === "") {
			out.push("");
			continue;
		}
		if (Array.isArray(value)) {
			if (flagBefore) out.pop();
			for (const item of value) {
				if (flagBefore) out.push(previous);
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
function readQuery(spec, params, query) {
	const bindings = { ...params };
	const accepted = new Set((spec.query ?? []).map((field) => field.name));
	if (spec.write !== true) accepted.add("limit");
	const unknownParams = [...query.keys()].filter((name) => !accepted.has(name));
	if (unknownParams.length > 0) return {
		status: 400,
		body: {
			ok: false,
			error: {
				code: "UNKNOWN_PARAMS",
				message: "this endpoint does not take " + unknownParams.join(", ") + "; it reads: " + ([...accepted].sort().join(", ") || "(no query parameters)")
			},
			unknownParams
		}
	};
	for (const field of spec.query ?? []) {
		const key = field.as ?? field.name;
		const raw = query.get(field.name);
		if (field.boolean === true) {
			bindings[key] = raw !== null && raw !== "false" && raw !== "0";
			continue;
		}
		if (raw === null || raw === "") {
			if (field.required === true) return refuse(400, "INVALID_QUERY", "query parameter " + field.name + " is required");
			continue;
		}
		bindings[key] = raw;
	}
	return { bindings };
}
/** Coerce one body value to the shape its field declares. */
function fieldValue(field, value) {
	if (value === void 0) return void 0;
	switch (field.kind) {
		case "boolean": return typeof value === "boolean" ? value : refuse(400, "INVALID_BODY", field.name + " must be a boolean");
		case "int": return typeof value === "number" && Number.isInteger(value) ? value : refuse(400, "INVALID_BODY", field.name + " must be an integer");
		case "repeat":
			if (!Array.isArray(value) || value.some((item) => typeof item !== "string" || item.trim() === "")) return refuse(400, "INVALID_BODY", field.name + " must be an array of non-empty strings");
			return value;
		case "json-repeat": {
			if (!Array.isArray(value) || value.length === 0) return refuse(400, "INVALID_BODY", field.name + " must be a non-empty array (an empty one cannot clear a plan)");
			const rendered = [];
			for (const item of value) {
				if (typeof item === "string") {
					if (item.trim() === "") return refuse(400, "INVALID_BODY", field.name + " entries must not be empty");
					rendered.push(item);
					continue;
				}
				if (typeof item === "object" && item !== null && !Array.isArray(item)) {
					rendered.push(JSON.stringify(item));
					continue;
				}
				return refuse(400, "INVALID_BODY", field.name + " entries must be a string or an object");
			}
			return rendered;
		}
		case "enum":
			if (typeof value !== "string" || !(field.values ?? []).includes(value)) return refuse(400, "INVALID_BODY", field.name + " must be one of " + (field.values ?? []).join(", "));
			return value;
		default:
			if (typeof value !== "string") return refuse(400, "INVALID_BODY", field.name + " must be a string");
			if (field.allowEmpty === true) return value;
			if (value.trim() === "") return refuse(400, "INVALID_BODY", field.name + " must be a non-empty string");
			if (field.forbid !== void 0 && value.includes(field.forbid.text)) return refuse(400, field.forbid.code, field.forbid.message);
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
function readWrite(spec, params, query, body) {
	const queryRead = readQuery(spec, params, query);
	if ("status" in queryRead) return queryRead;
	const bindings = { ...queryRead.bindings };
	for (const [name, value] of Object.entries(params)) {
		const prefix = spec.ids?.[name];
		if (prefix !== void 0 && !isIdentity(prefix, value)) return refuse(400, "INVALID_ID", name + " must be " + prefix + "- followed by a 26-character ULID");
		const pattern = spec.patterns?.[name];
		if (pattern !== void 0 && !pattern.test(value)) return refuse(400, "INVALID_PARAM", name + " must match " + pattern.source);
	}
	let template = spec.argv;
	let fields = [...spec.body ?? []];
	let required = [...spec.required ?? []];
	let exclusive = spec.exactlyOne;
	if (spec.actions !== void 0) {
		const actionName = body[spec.actions.field];
		if (typeof actionName !== "string" || spec.actions.cases[actionName] === void 0) return refuse(400, "UNKNOWN_ACTION", spec.actions.field + " must be one of " + Object.keys(spec.actions.cases).join(", "));
		const action = spec.actions.cases[actionName];
		template = action.argv;
		fields = [...action.body ?? []];
		required = [...required, ...action.required ?? []];
		exclusive = action.exactlyOne ?? exclusive;
	}
	for (const field of fields) if (field.required === true) required.push(field.name);
	const revision = spec.revision ?? "required";
	if (revision === "required") required.push(REVISION_FIELD.name);
	if (revision !== "none") fields.push(REVISION_FIELD);
	const writableShared = spec.shared ?? SHARED_WRITE_FIELDS;
	const acceptedFields = new Set(fields.map((field) => field.name));
	for (const field of writableShared) acceptedFields.add(field.name);
	if (spec.actions !== void 0) acceptedFields.add(spec.actions.field);
	const unknownFields = Object.keys(body).filter((name) => !acceptedFields.has(name));
	if (unknownFields.length > 0) {
		const hints = unknownFields.map((name) => spec.unknownFieldHints?.[name] ?? (name === REVISION_FIELD.name && revision === "none" ? "this endpoint has no revision to compare, so it takes no expectedRevision" : void 0)).filter((hint) => hint !== void 0);
		const accepted = [...acceptedFields].join(", ");
		return {
			status: 400,
			body: {
				ok: false,
				error: {
					code: "UNKNOWN_FIELDS",
					message: "this route does not accept " + unknownFields.join(", ") + "; it takes: " + accepted + (hints.length === 0 ? "" : "; " + hints.join("; "))
				},
				unknownFields
			}
		};
	}
	for (const name of required) if (body[name] === void 0) return refuse(400, "INVALID_REQUEST", name + " is required");
	if (exclusive !== void 0) {
		const given = exclusive.filter((name) => body[name] !== void 0);
		if (given.length !== 1) return refuse(400, "INVALID_REQUEST", "exactly one of " + exclusive.join(", ") + " must be given (" + (given.length === 0 ? "none was" : "both were") + "), not both");
	}
	for (const field of [...fields, ...spec.shared ?? SHARED_WRITE_FIELDS]) {
		const value = fieldValue(field, body[field.name]);
		if (value !== void 0 && isRefusal(value)) return value;
		if (value !== void 0) bindings[field.name] = value;
	}
	if (template === void 0) return refuse(500, "ROUTE_MISCONFIGURED", spec.path + " declares neither argv nor actions");
	const missing = templateMissing(template, bindings);
	if (missing !== void 0) return refuse(400, "INVALID_REQUEST", missing + " is required");
	const named = new Set(template.flatMap((element) => {
		const placeholder = /^\{(\w+)\}$/u.exec(element);
		return placeholder === null ? [] : [placeholder[1] ?? ""];
	}));
	const sharedFields = spec.shared ?? SHARED_WRITE_FIELDS;
	const shared = revision === "none" ? sharedFields : [REVISION_FIELD, ...sharedFields];
	const argv = [...template];
	for (const field of shared) {
		if (named.has(field.name)) continue;
		if (bindings[field.name] === void 0) continue;
		if (field.flag === void 0) continue;
		argv.push(field.flag, "{" + field.name + "}");
	}
	return {
		argv,
		bindings
	};
}
/** Whether one validated value is a refusal rather than a binding. */
function isRefusal(value) {
	return typeof value === "object" && value !== null && "status" in value && "body" in value;
}
/** The first placeholder one template needs but no binding supplies. */
function templateMissing(template, bindings) {
	for (const element of template) {
		const placeholder = /^\{(\w+)\}$/u.exec(element);
		if (placeholder === null) continue;
		const name = placeholder[1] ?? "";
		const value = bindings[name];
		if (value === void 0 || value === "" || value === false) continue;
		if (Array.isArray(value) && value.length === 0) return name;
	}
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
function commandFailure(code, stdout, stderr, failureStatuses) {
	const parsed = parseObject(stdout);
	const message = firstLine(stderr);
	if (parsed !== void 0 && failureStatuses !== void 0) {
		const reported = parsed.error;
		const reportedCode = typeof reported === "object" && reported !== null ? reported.code : void 0;
		if (typeof reportedCode === "string" && failureStatuses[reportedCode] !== void 0) return {
			status: failureStatuses[reportedCode] ?? 502,
			body: parsed
		};
	}
	if (code === 3) return {
		status: 409,
		body: parsed ?? {
			ok: false,
			error: {
				code: "COMMAND_CONFLICT",
				message
			}
		}
	};
	if (code === 2) return {
		status: 422,
		body: parsed ?? {
			ok: false,
			error: {
				code: "COMMAND_REFUSED",
				message
			}
		}
	};
	return {
		status: 502,
		body: parsed ?? {
			ok: false,
			error: {
				code: "COMMAND_FAILED",
				message
			}
		}
	};
}
/** Parse one JSON object, or undefined when the text is not one. */
function parseObject(text) {
	try {
		const value = JSON.parse(text);
		return typeof value === "object" && value !== null && !Array.isArray(value) ? value : void 0;
	} catch {
		return;
	}
}
/** First non-empty line of one message, bounded for a response body. */
function firstLine(text) {
	const line = (text.split("\n")[0] ?? "").trim();
	return line.length <= 400 ? line : line.slice(0, 399) + "…";
}
/** Envelope keys lifted to the top level when pm reported them. */
const ENVELOPE_KEYS = [
	"entityId",
	"revision",
	"source",
	"observedAt",
	"auditEventId"
];
/**
* Shape one successful write reply.
*
* Only fields pm actually reported are carried: a payload that later gains a
* field reaches the workbench unchanged, and a missing one is omitted rather
* than invented.
* @param parsed - the object pm printed.
* @returns the reply body.
*/
function successEnvelope(parsed, flattenData = false) {
	const lifted = new Set([
		...ENVELOPE_KEYS,
		"ok",
		"inboxId"
	]);
	const inner = parsed.data;
	const flat = flattenData && typeof inner === "object" && inner !== null ? inner : void 0;
	const data = flat === void 0 ? {} : { ...flat };
	if (flat === void 0) {
		for (const [key, value] of Object.entries(parsed)) if (!lifted.has(key)) data[key] = value;
	}
	const body = { ok: true };
	const entityId = parsed.entityId ?? parsed.inboxId;
	if (entityId !== void 0) body.entityId = entityId;
	for (const key of ENVELOPE_KEYS) if (key !== "entityId" && parsed[key] !== void 0) body[key] = parsed[key];
	body.data = data;
	return body;
}
/**
* Shape one successful read reply, applying a caller's row limit.
* @param parsed - the object pm printed.
* @param limit - maximum rows to return, or undefined for all of them.
* @returns the reply body.
*/
function listBody(parsed, limit, flattenData = false) {
	const inner = parsed.data;
	const data = flattenData && typeof inner === "object" && inner !== null ? { ...inner } : { ...parsed };
	delete data.ok;
	if (limit !== void 0) for (const key of [
		"entries",
		"tasks",
		"proposals",
		"groups",
		"workspaces",
		"memories",
		"sessions",
		"projects"
	]) {
		const rows = data[key];
		if (Array.isArray(rows)) data[key] = rows.slice(0, limit);
	}
	return {
		ok: true,
		data
	};
}
/**
* The capability report: what this service serves, and what pm cannot do yet.
* @param pmVersion - version string pm reported, or null when it did not answer.
* @param config - configuration file every invocation names.
* @param layout - where the launcher, configuration, and workbench were found,
*   so a deployment can be diagnosed from the service itself.
* @returns the report body.
*/
function capabilities(pmVersion, config, layout) {
	return {
		ok: true,
		data: {
			pmVersion,
			config,
			endpoints: DOMAIN_ROUTES.map((spec) => {
				const endpoint = {
					method: spec.method,
					path: spec.path,
					write: spec.write === true
				};
				if (spec.notForwarded !== void 0) endpoint.notForwarded = spec.notForwarded;
				return endpoint;
			}),
			hostOwnedFlags: HOST_OWNED_FLAGS,
			unavailable: UNSUPPORTED_ENDPOINTS,
			...layout === void 0 ? {} : { layout }
		}
	};
}
/**
* Validate one read request and produce its argv template and bindings.
* @param spec - matched route.
* @param params - path bindings.
* @param query - request search parameters.
* @returns the argv template with its bindings, or the refusal to answer with.
*/
function readRead(spec, params, query) {
	for (const [name, value] of Object.entries(params)) {
		const prefix = spec.ids?.[name];
		if (prefix !== void 0 && !isIdentity(prefix, value)) return refuse(400, "INVALID_ID", name + " must be " + prefix + "- followed by a 26-character ULID");
		const pattern = spec.patterns?.[name];
		if (pattern !== void 0 && !pattern.test(value)) return refuse(400, "INVALID_PARAM", name + " must match " + pattern.source);
	}
	if (spec.argv === void 0) return refuse(500, "ROUTE_MISCONFIGURED", spec.path + " declares no argv");
	const read = readQuery(spec, params, query);
	if ("status" in read) return read;
	return {
		argv: spec.argv,
		bindings: read.bindings
	};
}
/**
* Read one caller's row limit.
* @param query - request search parameters.
* @returns the limit, undefined when none was asked for, or the refusal to answer with.
*/
function readLimit(query) {
	const raw = query.get("limit");
	if (raw === null) return {};
	const parsed = Number(raw);
	if (!Number.isInteger(parsed) || parsed < 1) return refuse(400, "INVALID_LIMIT", "limit must be a positive integer");
	return { limit: parsed };
}
//#endregion
//#region lib/types/pm-layout.js
/**
* Where `pm` and its configuration live, resolved at runtime.
*
* A published package must not carry the machine path it was built on: `pm`
* may come from pipx, from a package manager, or from a checkout, and the
* library configuration may sit in the working directory or in the user's home.
* This module resolves the four values the host half needs, in this order:
*
* 1. an explicit choice: the `DSH_UI_PM_*` variables, then the backend's own
*    `PM_*` ones;
* 2. `pm` on `PATH`;
* 3. a developer checkout: the repository holding a discovered `<root>/bin/pm`,
*    the working directory and its ancestors, or the conventional checkouts
*    under the home directory;
* 4. the package's own `app/` and `~/.dsh-pm/pm.toml`.
*
* Every step is existence-guarded, so an installation that has none of them
* still starts, and the first command reports what to set instead of silently
* reading the wrong library.
* @module @deepseek-ai/dsh-client-ui-pm
*/
/**
* The workbench shipped inside this package, one level above src/ or lib/.
* Both layouts resolve to the same directory, so the source tree and the built
* package agree on where `app/` would be.
*/
const PACKAGED_APP_DIR = fileURLToPath(new URL("../app/", import.meta.url));
/** Where a packaged installation keeps its own configuration. */
const USER_CONFIG_PATH = join(homedir(), ".dsh-pm", "pm.toml");
/**
* The Host environment, read through one documented widening.
*
* The client build face types `process.env` with only its own `DSH_CLIENT_*`
* keys; this half runs in the Host process, where the environment and the
* working directory are real (see the same widening in ./index.ts).
*/
const HOST_ENV = process.env;
/**
* The Host's working directory.
*
* A shell records it in `PWD`; a service started without one falls back to the
* home directory, which only affects where a checkout is looked for and the
* launcher's working directory - every command names its configuration file
* explicitly, so the library is never chosen by the working directory.
*/
function hostCwd() {
	const recorded = HOST_ENV["PWD"];
	return recorded !== void 0 && recorded !== "" ? recorded : homedir();
}
/** First non-empty value among these variable names. */
function envValue(env, names) {
	for (const name of names) {
		const value = env[name];
		if (value !== void 0 && value.trim() !== "") return value.trim();
	}
}
/**
* Directories that could hold a checkout of the pm tools, most explicit first.
* @param input - the machine facts.
* @param launcher - the launcher already discovered, if any.
* @returns candidate repository roots.
*/
function repoCandidates(input, launcher) {
	const candidates = [];
	const explicit = envValue(input.env, ["DSH_UI_PM_PM_ROOT", "PM_ROOT"]);
	if (explicit !== void 0) candidates.push(explicit);
	if (launcher !== void 0 && basename(launcher) === "pm" && basename(dirname(launcher)) === "bin") candidates.push(dirname(dirname(launcher)));
	let current = input.cwd;
	for (let depth = 0; depth < 4; depth += 1) {
		candidates.push(current);
		const parent = dirname(current);
		if (parent === current) break;
		current = parent;
	}
	candidates.push(join(input.home, "projects", "tools_dev", "pm_tools"));
	candidates.push(join(input.home, "pm_tools"));
	return candidates;
}
/**
* Resolve the layout from machine facts.
* @param input - environment, directories, and the two existence predicates.
* @returns the launcher, working directory, configuration, workbench, and notes.
*/
function resolvePmLayout(input) {
	const notes = [];
	const launcherChoice = envValue(input.env, ["DSH_UI_PM_PM_BIN", "PM_BIN"]);
	if (launcherChoice !== void 0) notes.push("pm launcher: DSH_UI_PM_PM_BIN/PM_BIN");
	const onPath = launcherChoice === void 0 ? input.onPath("pm") : void 0;
	if (onPath !== void 0) notes.push("pm launcher: PATH");
	const discovered = launcherChoice ?? onPath;
	const repo = repoCandidates(input, discovered).find((candidate) => input.isFile(join(candidate, "config", "pm.toml")));
	if (repo !== void 0) notes.push("pm checkout: " + repo);
	const repoBin = repo === void 0 ? void 0 : join(repo, "bin", "pm");
	const pmBin = discovered ?? (repoBin !== void 0 && input.isFile(repoBin) ? repoBin : "pm");
	if (discovered === void 0) notes.push(repoBin !== void 0 && input.isFile(repoBin) ? "pm launcher: checkout" : "pm launcher: bare name (PATH lookup at run time)");
	const cwdConfig = join(input.cwd, "pm.toml");
	const pmConfig = envValue(input.env, ["PM_CONFIG"]) ?? (repo === void 0 ? void 0 : join(repo, "config", "pm.toml")) ?? (input.isFile(cwdConfig) ? cwdConfig : void 0) ?? USER_CONFIG_PATH;
	if (pmConfig === cwdConfig) notes.push("pm config: working directory");
	else if (pmConfig === USER_CONFIG_PATH) notes.push("pm config: " + USER_CONFIG_PATH);
	else if (repo !== void 0 && pmConfig === join(repo, "config", "pm.toml")) notes.push("pm config: checkout");
	else notes.push("pm config: PM_CONFIG");
	const pmCwd = envValue(input.env, ["DSH_UI_PM_PM_CWD", "PM_CWD"]) ?? repo ?? input.cwd;
	const repoApp = repo === void 0 ? void 0 : join(repo, "frontend_impl");
	const packagedApp = input.isDir(PACKAGED_APP_DIR);
	const appDir = packagedApp ? PACKAGED_APP_DIR : repoApp !== void 0 && input.isDir(repoApp) ? repoApp : PACKAGED_APP_DIR;
	if (packagedApp) notes.push("workbench: packaged app/");
	else if (repoApp !== void 0 && input.isDir(repoApp)) notes.push("workbench: checkout frontend_impl");
	else notes.push("workbench: packaged app/ (missing)");
	return {
		pmBin,
		pmCwd,
		pmConfig,
		appDir,
		notes
	};
}
/** A regular file exists at this path. */
function isFileAt(path) {
	try {
		return statSync(path).isFile();
	} catch {
		return false;
	}
}
/** A directory exists at this path. */
function isDirAt(path) {
	try {
		return statSync(path).isDirectory();
	} catch {
		return false;
	}
}
/**
* The absolute path of an executable on `PATH`.
* @param name - executable name, without directories.
* @returns the first match, or undefined when `PATH` holds none.
*/
function executableOnPath(name) {
	for (const directory of (HOST_ENV["PATH"] ?? "").split(":")) {
		if (directory === "") continue;
		const candidate = join(directory, name);
		try {
			accessSync(candidate, constants.X_OK);
			if (statSync(candidate).isFile()) return candidate;
		} catch {}
	}
}
/** Resolve the layout against this process. */
function resolveProcessPmLayout() {
	return resolvePmLayout({
		env: HOST_ENV,
		cwd: hostCwd(),
		home: homedir(),
		isFile: isFileAt,
		isDir: isDirAt,
		onPath: executableOnPath
	});
}
//#endregion
//#region lib/types/index.js
/**
* PM workbench plugin, node half.
*
* This half serves the browser face the frozen `pm ui-cards` payload, the
* static workbench the panel embeds, and the domain command surface the
* workbench acts through. The command surface is a table (./domain-routes.ts)
* executed by ONE runner, so a new pm command is a table entry rather than
* another handler. Every command is spawned with an argv array, so no request
* text ever reaches a shell, and every write names its configuration file so it
* cannot land in a library the caller never meant.
* @module @deepseek-ai/dsh-client-ui-pm
*/
/**
* Where `pm`, its configuration, and the workbench were found on this machine.
*
* Resolved at load time from the environment, `PATH`, a nearby checkout, and the
* package's own `app/` (./pm-layout.ts). Nothing machine-specific is baked into
* the built artifact; an installation that resolves none of them still starts
* and reports what to set when the first command runs.
*/
const LAYOUT = resolveProcessPmLayout();
/** The `pm` launcher every command runs. */
const PM_BIN = LAYOUT.pmBin;
/** Working directory the launcher is invoked from. */
const PM_CWD = LAYOUT.pmCwd;
/** Configuration file the work-memory commands run with. */
const DEFAULT_PM_CONFIG = LAYOUT.pmConfig;
/** Default directory of the static workbench the panel embeds. */
const DEFAULT_APP_DIR = LAYOUT.appDir;
/** How each of the four was found, for diagnostics. */
const PM_LAYOUT_NOTES = LAYOUT.notes;
/** Absolute pathname of the read-only work-card endpoint. */
const CARDS_ROUTE = "/ui-pm/cards";
/** Absolute pathname prefix of the hosted workbench. */
const APP_ROUTE = "/ui-pm/app";
/** Absolute pathname of the quick-note endpoint. */
const CAPTURE_ROUTE = "/ui-pm/capture";
/** Longest quick note the capture endpoint accepts, in characters. */
const MAX_CAPTURE_CHARS = 8e3;
/** Child-process deadline for a library scan; the scan is the slow part. */
const SCAN_TIMEOUT_MS = 12e4;
/** Child-process deadline for one domain command or inbox append. */
const CAPTURE_TIMEOUT_MS = 6e4;
/** Upper bound on captured stdout: the full card list for a large library. */
const MAX_BUFFER_BYTES = 32 * 1024 * 1024;
/** Upper bound on one request body. */
const MAX_BODY_BYTES = 64 * 1024;
/** How long one payload is served before another `pm ui-cards` run is allowed. */
const CACHE_TTL_MS = 45e3;
/** Content type per served extension; an extension absent here is not served. */
const APP_TYPES = {
	html: "text/html; charset=utf-8",
	css: "text/css; charset=utf-8",
	js: "text/javascript; charset=utf-8",
	map: "application/json; charset=utf-8",
	svg: "image/svg+xml",
	png: "image/png",
	woff2: "font/woff2"
};
/**
* One file name the static route may serve: a single segment with a served
* extension. The workbench is free to split its own modules, icons, and fonts
* without asking this plugin for a new line, while a separator, a parent
* segment, or an unserved extension still names nothing.
*/
const APP_FILE_NAME = /^[A-Za-z0-9._-]+\.(html|css|js|map|svg|png|woff2)$/u;
/**
* Content type of one served file name.
* @param name - whitelisted file name.
* @returns the content type, or undefined when the extension is not served.
*/
function appContentType(name) {
	return APP_TYPES[name.slice(name.lastIndexOf(".") + 1)];
}
/**
* Directory the static route reads.
*
* The build-time client environment types `process.env` with only
* `DSH_CLIENT_*` keys; these host-only deploy paths are read through one
* documented widening instead of a name that would lie about being a client
* build input.
*/
const APP_DIR = process.env["DSH_UI_PM_APP_DIR"] ?? DEFAULT_APP_DIR;
/**
* Configuration file every invocation names explicitly, overridable per host.
*
* Naming the file is what makes a write a declared act: `pm` refuses a write
* that never said which library it belongs to, and this plugin always means the
* library its own configuration selects. Pointing the override at a temporary
* `pm.toml` is also how a real end-to-end write is verified without touching
* the library the user works in.
*/
const PM_CONFIG = process.env["DSH_UI_PM_CONFIG"] ?? DEFAULT_PM_CONFIG;
/** Arguments every `pm` invocation carries ahead of its subcommand. */
function globalArgs() {
	return ["--config", PM_CONFIG];
}
/**
* argv one quick note is captured with.
*
* The note travels as a single element after the subcommand, so a shell never
* parses it and its punctuation cannot become syntax. Exported so the argv
* contract can be asserted without running — and therefore without writing.
* @param text - note text.
* @returns the launcher arguments, configuration override included.
*/
function captureArgs(text) {
	return [
		...globalArgs(),
		"capture",
		text,
		"--json"
	];
}
/**
* Run one `pm` subcommand with argv (never a shell) and report how it exited.
*
* Unlike {@link runJson} this never rejects: the domain endpoints must
* translate specific exit codes into specific HTTP statuses, so the code is
* data.
* @param args - launcher arguments, configuration file included.
* @param timeout - child-process deadline in milliseconds.
* @returns the exit code and both output streams.
*/
function runCommand(args, timeout) {
	return new Promise((resolve) => {
		execFile(PM_BIN, [...args], {
			cwd: PM_CWD,
			timeout,
			maxBuffer: MAX_BUFFER_BYTES,
			encoding: "utf8"
		}, (error, stdout, stderr) => {
			resolve({
				code: error === null ? 0 : typeof error.code === "number" ? error.code : 1,
				stdout,
				stderr
			});
		});
	});
}
/** Run one `pm` subcommand and parse its stdout as JSON, rejecting on any failure. */
async function runJson(args, timeout, label) {
	const result = await runCommand(args, timeout);
	if (result.code !== 0) throw new Error(result.stderr.trim() === "" ? label + " exited with code " + String(result.code) : result.stderr.trim());
	const parsed = parseObject(result.stdout);
	if (parsed === void 0) throw new Error(label + " returned invalid JSON");
	return parsed;
}
let pending;
let cached;
/**
* Read the current work-card payload.
*
* One read is shared by every concurrent caller, and a completed read is served
* for {@link CACHE_TTL_MS} so a page that is reloaded or a Sidebar that mounts
* again does not rescan the whole library. Only the read is cached; nothing is
* written anywhere.
* @param options - fresh request policy.
* @returns the parsed `pm ui-cards` JSON.
* @throws when the launcher fails, times out, or prints something that is not JSON.
*/
function readUiCards(options = {}) {
	if (options.fresh !== true && cached !== void 0 && Date.now() - cached.at < 45e3) return Promise.resolve(cached.payload);
	pending ??= runJson([...globalArgs(), "ui-cards"], SCAN_TIMEOUT_MS, "pm ui-cards").then((payload) => {
		cached = {
			at: Date.now(),
			payload
		};
		return payload;
	}).finally(() => {
		pending = void 0;
	});
	return pending;
}
/**
* Append one quick note to the work-memory inbox.
* @param text - note text, already validated by the endpoint.
* @returns the parsed `pm capture --json` result.
* @throws when the launcher fails, times out, or prints something that is not JSON.
*/
function runCapture(text) {
	return runJson(captureArgs(text), CAPTURE_TIMEOUT_MS, "pm capture");
}
/** Write one JSON response and end it. */
function sendJson(res, status, body) {
	res.writeHead(status, {
		"content-type": "application/json; charset=utf-8",
		"cache-control": "no-store"
	});
	res.end(JSON.stringify(body));
}
/** Write one text response and end it; `HEAD` sends the headers alone. */
function sendText(res, status, contentType, body, head) {
	res.writeHead(status, {
		"content-type": contentType,
		"content-length": String(Buffer.byteLength(body)),
		"cache-control": "no-store",
		"x-content-type-options": "nosniff"
	});
	res.end(head ? void 0 : body);
}
/** First line of one failure, bounded for a response body. */
function summarise(error) {
	return firstLine(error instanceof Error ? error.message : String(error));
}
/** Read one request body, refusing anything above {@link MAX_BODY_BYTES}. */
async function readBody(req) {
	const chunks = [];
	let size = 0;
	for await (const chunk of req) {
		const buffer = typeof chunk === "string" ? Buffer.from(chunk) : chunk;
		size += buffer.byteLength;
		if (size > MAX_BODY_BYTES) throw new Error("request body is larger than 64 KiB");
		chunks.push(buffer);
	}
	return Buffer.concat(chunks).toString("utf8");
}
/**
* Answer one read of the work-card endpoint. Only GET is served; a failed read
* is reported as a structured 502 so the browser half can show the reason
* instead of an empty list.
*/
async function cardsHandler(req, res) {
	if (req.method !== "GET" && req.method !== "HEAD") {
		res.writeHead(405, { allow: "GET, HEAD" });
		res.end();
		return;
	}
	try {
		sendJson(res, 200, {
			ok: true,
			data: await readUiCards(new URL(req.url ?? "/", "http://x").searchParams.has("refresh") ? { fresh: true } : {})
		});
	} catch (error) {
		sendJson(res, 502, {
			ok: false,
			error: {
				code: "COMMAND_FAILED",
				message: summarise(error)
			}
		});
	}
}
/**
* Resolve the path under {@link APP_ROUTE} to one whitelisted file.
*
* The name is decoded and then matched exactly, so `..`, a separator, a
* backslash, or a hidden name is refused as an escape rather than reported as
* absent: the route can only ever read files this directory holds.
* @param pathname - request pathname, already normalized by the URL parser.
* @returns the file to serve, or the refusal reason.
*/
function resolveAppFile(pathname) {
	if (!pathname.startsWith("/ui-pm/app/")) return { kind: "missing" };
	let decoded;
	try {
		decoded = decodeURIComponent(pathname.slice(11));
	} catch {
		return { kind: "escape" };
	}
	if (decoded === "") return {
		kind: "file",
		name: "index.html"
	};
	if (decoded.includes("..") || decoded.includes("/") || decoded.includes("\\") || decoded.startsWith(".")) return { kind: "escape" };
	return APP_FILE_NAME.test(decoded) ? {
		kind: "file",
		name: decoded
	} : { kind: "missing" };
}
/** Serve one file of the embedded workbench. */
async function appHandler(req, res) {
	const method = req.method ?? "GET";
	if (method !== "GET" && method !== "HEAD") {
		res.writeHead(405, { allow: "GET, HEAD" });
		res.end();
		return;
	}
	const head = method === "HEAD";
	const url = new URL(req.url ?? "/", "http://x");
	if (url.pathname === "/ui-pm/app") {
		res.writeHead(308, { location: "/ui-pm/app/" + url.search });
		res.end();
		return;
	}
	const resolved = resolveAppFile(url.pathname);
	if (resolved.kind === "escape") {
		sendText(res, 400, "text/plain; charset=utf-8", "Bad request: path escapes the workbench directory\n", head);
		return;
	}
	if (resolved.kind === "missing") {
		sendText(res, 404, "text/plain; charset=utf-8", "Not found\n", head);
		return;
	}
	try {
		const body = await readFile(join(APP_DIR, resolved.name));
		sendText(res, 200, appContentType(resolved.name) ?? "application/octet-stream", body.toString("utf8"), head);
	} catch (error) {
		if (error.code === "ENOENT") {
			sendText(res, 404, "text/plain; charset=utf-8", "Not found: " + resolved.name + " is missing from " + APP_DIR + "\n", head);
			return;
		}
		sendText(res, 500, "text/plain; charset=utf-8", "The workbench could not be read\n", head);
	}
}
/**
* Answer one quick-note append: the note goes to the work-memory inbox through
* `pm capture`, and the card cache is dropped so the very next read reports it.
*/
async function captureHandler(req, res) {
	if ((req.method ?? "") !== "POST") {
		res.writeHead(405, { allow: "POST" });
		res.end();
		return;
	}
	let body;
	try {
		body = await readBody(req);
	} catch (error) {
		sendJson(res, 413, {
			ok: false,
			error: {
				code: "BODY_TOO_LARGE",
				message: summarise(error)
			}
		});
		return;
	}
	const parsed = body.trim() === "" ? {} : parseObject(body);
	if (parsed === void 0) {
		sendJson(res, 400, {
			ok: false,
			error: {
				code: "INVALID_BODY",
				message: "body must be JSON of the form {\"text\": \"…\"}"
			}
		});
		return;
	}
	const text = parsed.text;
	if (typeof text !== "string" || text.trim() === "") {
		sendJson(res, 400, {
			ok: false,
			error: {
				code: "INVALID_BODY",
				message: "text must be a non-empty string"
			}
		});
		return;
	}
	const note = text.trim();
	if (note.length > 8e3) {
		sendJson(res, 400, {
			ok: false,
			error: {
				code: "INVALID_BODY",
				message: "text must be at most " + String(MAX_CAPTURE_CHARS) + " characters"
			}
		});
		return;
	}
	try {
		const result = await runCapture(note);
		cached = void 0;
		sendJson(res, 200, {
			ok: true,
			result
		});
	} catch (error) {
		sendJson(res, 502, {
			ok: false,
			error: {
				code: "COMMAND_FAILED",
				message: summarise(error)
			}
		});
	}
}
/**
* Execute one table entry: validate, build argv, run, map the exit code, and
* shape the reply. Every domain endpoint goes through this one path, so the
* rules — identity checks, the shared write body, the 3/2/other mapping, the
* envelope, and the card-cache drop after a write — exist once.
*/
async function domainHandler(req, res) {
	const method = req.method ?? "GET";
	const url = new URL(req.url ?? "/", "http://x");
	const matched = matchRoute(url.pathname, method);
	if (matched === void 0) {
		sendJson(res, 404, {
			ok: false,
			error: {
				code: "NOT_FOUND",
				message: "no endpoint at " + url.pathname
			}
		});
		return;
	}
	if ("methods" in matched) {
		res.writeHead(405, { allow: matched.methods.join(", ") });
		res.end();
		return;
	}
	const spec = matched.spec;
	const write = spec.write === true;
	let body = {};
	if (write) {
		let text;
		try {
			text = await readBody(req);
		} catch (error) {
			sendJson(res, 413, {
				ok: false,
				error: {
					code: "BODY_TOO_LARGE",
					message: summarise(error)
				}
			});
			return;
		}
		const parsedBody = text.trim() === "" ? {} : parseObject(text);
		if (parsedBody === void 0) {
			sendJson(res, 400, {
				ok: false,
				error: {
					code: "INVALID_BODY",
					message: "body must be a JSON object"
				}
			});
			return;
		}
		body = parsedBody;
	}
	const limit = readLimit(url.searchParams);
	if ("status" in limit) {
		sendJson(res, limit.status, limit.body);
		return;
	}
	const request = write ? readWrite(spec, matched.params, url.searchParams, body) : readRead(spec, matched.params, url.searchParams);
	if ("status" in request) {
		sendJson(res, request.status, request.body);
		return;
	}
	const result = await runCommand(buildArgv(request.argv, request.bindings, PM_CONFIG), CAPTURE_TIMEOUT_MS);
	if (result.code !== 0) {
		const failure = commandFailure(result.code, result.stdout, result.stderr, spec.failureStatuses);
		sendJson(res, failure.status, failure.body);
		return;
	}
	const parsed = parseObject(result.stdout);
	if (parsed === void 0) {
		sendJson(res, 502, {
			ok: false,
			error: {
				code: "BAD_OUTPUT",
				message: "pm printed no JSON object"
			}
		});
		return;
	}
	if (write) cached = void 0;
	const flatten = spec.flattenData === true;
	sendJson(res, 200, write ? successEnvelope(parsed, flatten) : listBody(parsed, limit.limit, flatten));
}
let pmVersion;
/**
* Report what this service serves and what pm cannot do yet. The version is
* read once and cached; a launcher that cannot answer leaves it null rather
* than inventing a version.
*/
async function capabilitiesHandler(req, res) {
	if ((req.method ?? "") !== "GET" && (req.method ?? "") !== "HEAD") {
		res.writeHead(405, { allow: "GET, HEAD" });
		res.end();
		return;
	}
	if (pmVersion === void 0) {
		const result = await runCommand(["--version"], CAPTURE_TIMEOUT_MS);
		pmVersion = result.code === 0 && result.stdout.trim() !== "" ? result.stdout.trim() : null;
	}
	sendJson(res, 200, capabilities(pmVersion, PM_CONFIG, {
		pmBin: PM_BIN,
		pmCwd: PM_CWD,
		pmConfig: PM_CONFIG,
		appDir: APP_DIR,
		notes: PM_LAYOUT_NOTES
	}));
}
/**
* Mount the work-card, workbench, quick-note, capability, and domain routes.
* The domain prefixes come from the route table, so registering a domain and
* adding an endpoint are the same edit.
* @param ctx - host context the profile mounted this plugin into.
*/
function apply(ctx) {
	ctx.logger.info("[ui-pm] %s", PM_LAYOUT_NOTES.join("; "));
	ctx.inject(["webServer"], (webCtx) => {
		webCtx.effect(() => webCtx.webServer.register({
			kind: "exact",
			path: CARDS_ROUTE,
			handler: cardsHandler
		}), "ui-pm: work-card route");
		webCtx.effect(() => webCtx.webServer.register({
			kind: "prefix",
			path: APP_ROUTE,
			handler: appHandler
		}), "ui-pm: workbench route");
		webCtx.effect(() => webCtx.webServer.register({
			kind: "exact",
			path: CAPTURE_ROUTE,
			handler: captureHandler
		}), "ui-pm: quick-note route");
		for (const prefix of routePrefixes()) {
			if (prefix === "/ui-pm/capabilities") continue;
			webCtx.effect(() => webCtx.webServer.register({
				kind: "prefix",
				path: prefix,
				handler: domainHandler
			}), "ui-pm: " + prefix + " routes");
		}
		webCtx.effect(() => webCtx.webServer.register({
			kind: "exact",
			path: CAPABILITIES_ROUTE,
			handler: capabilitiesHandler
		}), "ui-pm: capability route");
	});
}
//#endregion
export { APP_DIR, APP_ROUTE, CACHE_TTL_MS, CAPTURE_ROUTE, CARDS_ROUTE, DEFAULT_APP_DIR, DEFAULT_PM_CONFIG, MAX_CAPTURE_CHARS, PM_BIN, PM_CONFIG, PM_CWD, PM_LAYOUT_NOTES, appContentType, apply, captureArgs, readUiCards, resolveAppFile, runCapture };
