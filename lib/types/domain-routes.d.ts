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
/** Identity prefixes a path parameter may carry, one per domain. */
export type IdPrefix = 'inbox' | 'task' | 'proposal' | 'memory';
/** Identity shape per domain, checked before any argv is built. */
export declare const ID_PATTERNS: Readonly<Record<IdPrefix, RegExp>>;
/** One query parameter a read route forwards as a flag. */
export interface QueryFieldSpec {
    /** Query parameter name as the URL spells it. */
    readonly name: string;
    /** Flag to emit. @default `--${name}` */
    readonly flag?: string;
    /** Binding key a `{placeholder}` refers to. @default the parameter name */
    readonly as?: string;
    readonly required?: boolean;
    /** Presence flag: the parameter carries no value. */
    readonly boolean?: boolean;
}
/** One body value a write route forwards as a flag. */
export interface BodyFieldSpec {
    /** Binding key a `{placeholder}` refers to. */
    readonly name: string;
    /**
     * Flag this field is sent as, when it is sent as one.
     *
     * Omitted for a value the command takes positionally: the argv template
     * carries it as a bare placeholder, and claiming a flag for it would describe
     * an argument the command never accepts.
     */
    readonly flag?: string;
    readonly kind: 'string' | 'int' | 'boolean' | 'repeat' | 'json-repeat' | 'enum';
    readonly required?: boolean;
    /**
     * Whether an empty string is a value rather than an omission.
     *
     * Most fields treat empty as "not sent", but a command that reads an empty
     * argument as a real instruction (clearing a section, say) needs the empty
     * string to travel as one.
     */
    readonly allowEmpty?: boolean;
    /** Allowed values for `enum`. */
    readonly values?: readonly string[];
    /**
     * Why this field is kept but no longer recommended.
     *
     * A caller reads it when choosing between two ways to name the same thing; the
     * command still accepts the field, so the route keeps forwarding it.
     */
    readonly deprecated?: string;
    /**
     * A substring this value must not contain, refused before the command runs.
     *
     * The command documents the same rule, but checking it here answers `400` with
     * the command's own code instead of spending a subprocess on a known-bad body.
     */
    readonly forbid?: {
        readonly text: string;
        readonly code: string;
        readonly message: string;
    };
}
/** One branch of an action-dispatching route. */
export interface ActionSpec {
    readonly argv: readonly string[];
    readonly body?: readonly BodyFieldSpec[];
    /** Field names this action requires, shared or domain. */
    readonly required?: readonly string[];
    /**
     * Field names of which exactly one must be given.
     *
     * Two ways to name the same thing are not merged silently: a caller that sends
     * both gets a refusal instead of whichever one the code happens to read.
     */
    readonly exactlyOne?: readonly string[];
    /** Flags the command accepts that this action deliberately never sends. */
    readonly notForwarded?: readonly {
        readonly flag: string;
        readonly reason: string;
    }[];
}
/** How a route treats the compare-and-set revision field. */
export type RevisionRule = 'required' | 'optional' | 'none';
/** One endpoint: a path pattern, a pm argv template, and the bindings that fill it. */
export interface RouteSpec {
    readonly method: 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE';
    /** Path pattern; `:name` segments become bindings. */
    readonly path: string;
    /** pm argv template; ignored when {@link actions} is present. */
    readonly argv?: readonly string[];
    /** Path parameters that must carry a domain identity. */
    readonly ids?: Readonly<Record<string, IdPrefix>>;
    /**
     * Path parameters that must match a shape pm would accept.
     *
     * A project key is not an identity prefix, but it is still a value that must
     * not reach the command malformed; the message names the expected shape.
     */
    readonly patterns?: Readonly<Record<string, RegExp>>;
    /**
     * Flags the command accepts that this route deliberately never sends.
     *
     * A gap has to be stated: the flag guard reports an undeclared flag, so a
     * route that means to omit one says so and gives the reason, and the
     * capability report carries it to the caller that would otherwise guess.
     */
    readonly notForwarded?: readonly {
        readonly flag: string;
        readonly reason: string;
    }[];
    /**
     * What to tell a caller who sends a field this route does not accept.
     *
     * A refusal is only useful if it says what to do instead, for the fields a
     * caller most plausibly reaches for (an idempotency key where the command
     * guards duplicates another way, say).
     */
    readonly unknownFieldHints?: Readonly<Record<string, string>>;
    /**
     * Differences from the command a caller should know, that no field expresses.
     *
     * The contract states them so the divergence between what the CLI defaults and
     * what this route demands is visible rather than folklore (an audit field the
     * command defaults is the usual case).
     */
    readonly notes?: readonly string[];
    /**
     * Status to answer for a specific pm error code, overriding the exit-code rule.
     *
     * The command's code says more than its exit status: a missing reason and a
     * state that forbids the write are both exit 2, yet one is the caller's mistake
     * (400) and the other is a well-formed request answered `422`.
     */
    readonly failureStatuses?: Readonly<Record<string, number>>;
    readonly query?: readonly QueryFieldSpec[];
    readonly body?: readonly BodyFieldSpec[];
    /** Additional required field names, shared or domain. */
    readonly required?: readonly string[];
    /** Field names of which exactly one must be given (see {@link ActionSpec.exactlyOne}). */
    readonly exactlyOne?: readonly string[];
    /**
     * Lift the command's own `data` object into the reply's `data`.
     *
     * A command that already answers an envelope would otherwise arrive nested as
     * `data.data`; the route whose contract documents the inner shape says so here
     * and answers what it promised. @default false
     */
    readonly flattenData?: boolean;
    /** Dispatch on one body field instead of one fixed argv. */
    readonly actions?: {
        readonly field: string;
        readonly cases: Readonly<Record<string, ActionSpec>>;
    };
    /** Writes answer with the write envelope and drop the card cache. */
    readonly write?: boolean;
    /** Compare-and-set rule for a write. @default 'required' */
    readonly revision?: RevisionRule;
    /**
     * Shared write fields this command actually accepts.
     *
     * Every write defaults to {@link SHARED_WRITE_FIELDS}, which is only safe
     * because the commands agree on them; a command that takes none of the audit
     * flags states that here rather than having the executor pass a flag its
     * parser would reject. @default SHARED_WRITE_FIELDS
     */
    readonly shared?: readonly BodyFieldSpec[];
}
/** Fields every mutating route accepts; `expectedRevision` is added per {@link RevisionRule}. */
export declare const SHARED_WRITE_FIELDS: readonly BodyFieldSpec[];
/**
 * Endpoints §6 names but pm's CLI does not implement yet. They are reported by
 * /ui-pm/capabilities and deliberately absent from {@link DOMAIN_ROUTES}: a
 * route is added here only when the command it would run exists - or, for a route
 * that ships ahead of its command, when the flag guard's pending list names it.
 */
export declare const UNSUPPORTED_ENDPOINTS: readonly {
    readonly method: string;
    readonly path: string;
    readonly reason: string;
}[];
/**
 * Flags every command accepts but this service deliberately never forwards.
 *
 * They are properties of the Host invocation, not of a request: a caller that
 * could name the configuration file or the DSH home could point the launcher at
 * another library or another instance, and `--yes` exists only for invocations
 * that never named a configuration file at all.
 */
export declare const HOST_OWNED_FLAGS: readonly {
    readonly flag: string;
    readonly reason: string;
}[];
/**
 * Flags the executor itself may put on a command line, whatever a route declares.
 *
 * The explicit allowlist the alignment check subtracts before calling a flag
 * undeclared: the configuration file is named by the host, JSON is always asked
 * for, and `--yes` exists only for invocations that named no configuration at
 * all. Each one carries its reason in {@link HOST_OWNED_FLAGS}.
 */
export declare const EXECUTOR_FLAGS: readonly string[];
/** One command the CLI offers that this service deliberately does not wrap. */
export interface UnexposedCommand {
    /** The command words, e.g. ['task', 'criteria', 'init-ids']. */
    readonly cliPath: readonly string[];
    /** Why a workbench route is not the right shape for it. */
    readonly reason: string;
}
/**
 * Commands the CLI offers that this service deliberately does not expose.
 *
 * The closure check reads the launcher's own command tree and requires every
 * command to be routed, covered by a fixed route, or named here with a reason -
 * so a command added to the CLI tomorrow cannot quietly have no answer.
 */
export declare const UNEXPOSED_COMMANDS: readonly UnexposedCommand[];
/**
 * Commands the fixed routes already run.
 *
 * The work-card payload and the quick note are fixed paths in ./index.ts rather
 * than table entries, so the closure check has to count them as covered.
 */
export declare const FIXED_ROUTE_COMMANDS: readonly UnexposedCommand[];
/** The command surface, one entry per endpoint. */
export declare const DOMAIN_ROUTES: readonly RouteSpec[];
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
export declare function cliPathOf(argv: readonly string[]): readonly string[];
/** The `--flag` literals one argv template carries, in first-seen order. */
export declare function argvFlagsOf(argv: readonly string[]): readonly string[];
/** Absolute pathname of the capability report. */
export declare const CAPABILITIES_ROUTE = "/ui-pm/capabilities";
/** One binding value a placeholder may resolve to. */
export type BindingValue = string | number | boolean | readonly string[] | undefined;
/** One refused request: the status and body to answer with. */
export interface Refusal {
    readonly status: number;
    readonly body: Record<string, unknown>;
}
/**
 * Whether one value carries a domain identity.
 * @param prefix - domain the value belongs to.
 * @param value - candidate identity.
 * @returns true when the value is `<prefix>-<ULID>`.
 */
export declare function isIdentity(prefix: IdPrefix, value: string): boolean;
/** One path match: the spec, its path bindings, and the methods that path serves. */
export interface RouteMatch {
    readonly spec: RouteSpec;
    readonly params: Readonly<Record<string, string>>;
}
/** Methods one path serves, for a 405 answer. */
export interface MethodOnly {
    readonly methods: readonly string[];
}
/**
 * Match one request path against the table.
 * @param pathname - request pathname, already normalized by the URL parser.
 * @param method - request method, or undefined to ask only which methods the path serves.
 * @returns the matching spec with its bindings, the methods when only the method is wrong, or undefined.
 */
export declare function matchRoute(pathname: string, method?: string): RouteMatch | MethodOnly | undefined;
/**
 * Prefixes every registered route hangs under, so registration follows the table.
 * @returns the distinct `/ui-pm/<domain>` prefixes, sorted.
 */
export declare function routePrefixes(): readonly string[];
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
export declare function buildArgv(argv: readonly string[], bindings: Readonly<Record<string, BindingValue>>, config: string): readonly string[];
/** Query-derived bindings, or the refusal that stops the request. */
export type BindingRead = {
    readonly bindings: Readonly<Record<string, BindingValue>>;
} | Refusal;
/**
 * Read one route's query parameters into bindings.
 * @param spec - matched route.
 * @param params - path bindings.
 * @param query - request search parameters.
 * @returns the bindings, or the refusal to answer with.
 */
export declare function readQuery(spec: RouteSpec, params: Readonly<Record<string, string>>, query: URLSearchParams): BindingRead;
/** One write route's request, validated and ready to become argv. */
export interface WriteRequest {
    readonly argv: readonly string[];
    readonly bindings: Readonly<Record<string, BindingValue>>;
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
export declare function readWrite(spec: RouteSpec, params: Readonly<Record<string, string>>, query: URLSearchParams, body: Record<string, unknown>): WriteRequest | Refusal;
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
export declare function commandFailure(code: number, stdout: string, stderr: string, failureStatuses?: Readonly<Record<string, number>>): Refusal;
/** Parse one JSON object, or undefined when the text is not one. */
export declare function parseObject(text: string): Record<string, unknown> | undefined;
/** First non-empty line of one message, bounded for a response body. */
export declare function firstLine(text: string): string;
/**
 * Shape one successful write reply.
 *
 * Only fields pm actually reported are carried: a payload that later gains a
 * field reaches the workbench unchanged, and a missing one is omitted rather
 * than invented.
 * @param parsed - the object pm printed.
 * @returns the reply body.
 */
export declare function successEnvelope(parsed: Record<string, unknown>, flattenData?: boolean): Record<string, unknown>;
/**
 * Shape one successful read reply, applying a caller's row limit.
 * @param parsed - the object pm printed.
 * @param limit - maximum rows to return, or undefined for all of them.
 * @returns the reply body.
 */
export declare function listBody(parsed: Record<string, unknown>, limit: number | undefined, flattenData?: boolean): Record<string, unknown>;
/**
 * The capability report: what this service serves, and what pm cannot do yet.
 * @param pmVersion - version string pm reported, or null when it did not answer.
 * @param config - configuration file every invocation names.
 * @param layout - where the launcher, configuration, and workbench were found,
 *   so a deployment can be diagnosed from the service itself.
 * @returns the report body.
 */
export declare function capabilities(pmVersion: string | null, config: string, layout?: Record<string, unknown>): Record<string, unknown>;
/** One read route's request, validated and ready to become argv. */
export interface ReadRequest {
    readonly argv: readonly string[];
    readonly bindings: Readonly<Record<string, BindingValue>>;
}
/**
 * Validate one read request and produce its argv template and bindings.
 * @param spec - matched route.
 * @param params - path bindings.
 * @param query - request search parameters.
 * @returns the argv template with its bindings, or the refusal to answer with.
 */
export declare function readRead(spec: RouteSpec, params: Readonly<Record<string, string>>, query: URLSearchParams): ReadRequest | Refusal;
/**
 * Read one caller's row limit.
 * @param query - request search parameters.
 * @returns the limit, undefined when none was asked for, or the refusal to answer with.
 */
export declare function readLimit(query: URLSearchParams): {
    readonly limit?: number;
} | Refusal;
//# sourceMappingURL=domain-routes.d.ts.map