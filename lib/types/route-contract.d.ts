/**
 * The route contract as data another tool can read.
 *
 * `src/domain-routes.ts` is the single source of truth for the HTTP surface and
 * for the pm command each endpoint runs. This module projects that table into a
 * stable JSON document so the alignment between table and CLI can be checked by
 * something that does not read TypeScript: the committed
 * `route-contract.json` is compared with a fresh projection in the test suite,
 * and `scripts/route-contract.ts --check` reports the same staleness outside it.
 *
 * Regenerating is a deliberate act: change the table, run the script, commit both
 * the table and the document. A table edit without the document fails the gate,
 * and so does a document edit without the table.
 * @module @deepseek-ai/dsh-client-ui-pm
 */
import type { IdPrefix, RevisionRule } from './domain-routes.ts';
/** One body or query field as a consumer sees it. */
export interface ContractField {
    readonly name: string;
    /** The flag this field is sent as, when it is sent as one (a positional has none). */
    readonly flag?: string;
    readonly kind: string;
    readonly required: boolean;
    /** Allowed values of an `enum` field. */
    readonly values?: readonly string[];
    /** Whether an empty string is a value rather than an omission. */
    readonly allowEmpty?: boolean;
    /** Why this field is kept but no longer recommended. */
    readonly deprecated?: string;
    /** A substring the value must not contain, with the code the refusal answers. */
    readonly forbid?: {
        readonly text: string;
        readonly code: string;
        readonly message: string;
    };
    /** A presence flag: the parameter carries no value. */
    readonly boolean?: boolean;
}
/** One pm command a route runs, with the flags its argv template names. */
export interface ContractCommand {
    /** The command words, e.g. ['task', 'execution-config', 'set']. */
    readonly cliPath: readonly string[];
    /** Every `--flag` the template carries. */
    readonly argvFlags: readonly string[];
    /** The `action` value that selects this command, when the route dispatches. */
    readonly action?: string;
    /** Fields this specific command adds, for a dispatching route. */
    readonly body?: readonly ContractField[];
    /** Fields of which exactly one must be given, for a dispatching route. */
    readonly exactlyOne?: readonly string[];
    /** Field names this action requires beyond the ones marked in its body. */
    readonly required?: readonly string[];
    /** Flags this command accepts that the action deliberately never sends. */
    readonly notForwarded?: readonly {
        readonly flag: string;
        readonly reason: string;
    }[];
}
/** One endpoint. */
export interface ContractRoute {
    readonly method: string;
    readonly path: string;
    readonly write: boolean;
    /** How the command treats the compare-and-set revision. */
    readonly revision: RevisionRule;
    /** Path parameters that must carry a domain identity. */
    readonly ids?: Readonly<Record<string, IdPrefix>>;
    /** Path parameters that must match a shape, as source text. */
    readonly patterns?: Readonly<Record<string, string>>;
    readonly query: readonly ContractField[];
    readonly body: readonly ContractField[];
    /** Field names the route requires beyond the ones marked in `body` (shared included). */
    readonly required?: readonly string[];
    readonly commands: readonly ContractCommand[];
    /** The route answers the command's own `data` object rather than nesting it. */
    readonly flattenData?: boolean;
    /** Shared write fields this route accepts instead of {@link RouteContract.defaultSharedFields}. */
    readonly shared?: readonly ContractField[];
    /** Flags the command accepts that this route deliberately never sends. */
    readonly notForwarded?: readonly {
        readonly flag: string;
        readonly reason: string;
    }[];
    /** What to tell a caller who sends a field this route does not accept. */
    readonly unknownFieldHints?: Readonly<Record<string, string>>;
    /** Differences from the command a caller should know, that no field expresses. */
    readonly notes?: readonly string[];
    /** Status to answer for a specific pm error code, overriding the exit-code rule. */
    readonly failureStatuses?: Readonly<Record<string, number>>;
}
/** The whole contract. */
export interface RouteContract {
    readonly contractVersion: number;
    readonly generatedFrom: string;
    /** Flags the executor may add itself, whatever a route declares. */
    readonly executorFlags: readonly string[];
    /** The shared write fields a route accepts unless it declares its own. */
    readonly defaultSharedFields: readonly ContractField[];
    /** Flags every command accepts that this service never forwards, with reasons. */
    readonly hostOwnedFlags: readonly {
        readonly flag: string;
        readonly reason: string;
    }[];
    /** Endpoints with no route, with reasons. */
    readonly unsupported: readonly {
        readonly method: string;
        readonly path: string;
        readonly reason: string;
    }[];
    /** Commands the CLI offers that this service deliberately does not wrap, with reasons. */
    readonly unexposedCommands: readonly {
        readonly cliPath: readonly string[];
        readonly reason: string;
    }[];
    /** Commands the fixed routes already run (not table entries). */
    readonly fixedRouteCommands: readonly {
        readonly cliPath: readonly string[];
        readonly reason: string;
    }[];
    readonly routes: readonly ContractRoute[];
}
/**
 * Project the route table into the contract document.
 * @returns the contract, in table order so a reordering is visible.
 */
export declare function routeContract(): RouteContract;
/**
 * Render the contract exactly as it is committed.
 * @param contract - the projected contract.
 * @returns stable JSON text with a trailing newline.
 */
export declare function renderContract(contract: RouteContract): string;
/**
 * The digest of a rendered contract, for an external verification record.
 * @param text - rendered contract text.
 * @returns the sha256 hex digest.
 */
export declare function contractDigest(text: string): string;
//# sourceMappingURL=route-contract.d.ts.map