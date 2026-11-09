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
import type { Context } from '@deepseek-ai/cordis';
/** The `pm` launcher every command runs. */
export declare const PM_BIN: string;
/** Working directory the launcher is invoked from. */
export declare const PM_CWD: string;
/** Configuration file the work-memory commands run with. */
export declare const DEFAULT_PM_CONFIG: string;
/** Default directory of the static workbench the panel embeds. */
export declare const DEFAULT_APP_DIR: string;
/** How each of the four was found, for diagnostics. */
export declare const PM_LAYOUT_NOTES: readonly string[];
/** Absolute pathname of the read-only work-card endpoint. */
export declare const CARDS_ROUTE = "/ui-pm/cards";
/** Absolute pathname prefix of the hosted workbench. */
export declare const APP_ROUTE = "/ui-pm/app";
/** Absolute pathname of the quick-note endpoint. */
export declare const CAPTURE_ROUTE = "/ui-pm/capture";
/** Longest quick note the capture endpoint accepts, in characters. */
export declare const MAX_CAPTURE_CHARS = 8000;
/** How long one payload is served before another `pm ui-cards` run is allowed. */
export declare const CACHE_TTL_MS = 45000;
/**
 * Content type of one served file name.
 * @param name - whitelisted file name.
 * @returns the content type, or undefined when the extension is not served.
 */
export declare function appContentType(name: string): string | undefined;
/**
 * Directory the static route reads.
 *
 * The build-time client environment types `process.env` with only
 * `DSH_CLIENT_*` keys; these host-only deploy paths are read through one
 * documented widening instead of a name that would lie about being a client
 * build input.
 */
export declare const APP_DIR: string;
/**
 * Configuration file every invocation names explicitly, overridable per host.
 *
 * Naming the file is what makes a write a declared act: `pm` refuses a write
 * that never said which library it belongs to, and this plugin always means the
 * library its own configuration selects. Pointing the override at a temporary
 * `pm.toml` is also how a real end-to-end write is verified without touching
 * the library the user works in.
 */
export declare const PM_CONFIG: string;
/**
 * argv one quick note is captured with.
 *
 * The note travels as a single element after the subcommand, so a shell never
 * parses it and its punctuation cannot become syntax. Exported so the argv
 * contract can be asserted without running — and therefore without writing.
 * @param text - note text.
 * @returns the launcher arguments, configuration override included.
 */
export declare function captureArgs(text: string): readonly string[];
/** One finished `pm` invocation: how it exited and what it printed. */
export interface CommandResult {
    /** Process exit code; a spawn failure that produced none is reported as 1. */
    readonly code: number;
    readonly stdout: string;
    readonly stderr: string;
}
/** Options of {@link readUiCards}. */
export interface ReadUiCardsOptions {
    /** Bypass the TTL cache: the caller asked for the current library state. */
    readonly fresh?: boolean;
}
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
export declare function readUiCards(options?: ReadUiCardsOptions): Promise<unknown>;
/**
 * Append one quick note to the work-memory inbox.
 * @param text - note text, already validated by the endpoint.
 * @returns the parsed `pm capture --json` result.
 * @throws when the launcher fails, times out, or prints something that is not JSON.
 */
export declare function runCapture(text: string): Promise<unknown>;
/** Which whitelisted file one request path names, or why it names none. */
type AppFileResolution = {
    readonly kind: 'file';
    readonly name: string;
} | {
    readonly kind: 'escape';
} | {
    readonly kind: 'missing';
};
/**
 * Resolve the path under {@link APP_ROUTE} to one whitelisted file.
 *
 * The name is decoded and then matched exactly, so `..`, a separator, a
 * backslash, or a hidden name is refused as an escape rather than reported as
 * absent: the route can only ever read files this directory holds.
 * @param pathname - request pathname, already normalized by the URL parser.
 * @returns the file to serve, or the refusal reason.
 */
export declare function resolveAppFile(pathname: string): AppFileResolution;
/**
 * Mount the work-card, workbench, quick-note, capability, and domain routes.
 * The domain prefixes come from the route table, so registering a domain and
 * adding an endpoint are the same edit.
 * @param ctx - host context the profile mounted this plugin into.
 */
export declare function apply(ctx: Context): void;
export {};
//# sourceMappingURL=index.d.ts.map