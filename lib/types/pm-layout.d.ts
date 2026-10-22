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
export declare const PACKAGED_APP_DIR: string;
/** Where a packaged installation keeps its own configuration. */
export declare const USER_CONFIG_PATH: string;
/** Everything the resolution may ask about the machine. */
export interface PmLayoutInput {
    readonly env: Readonly<Record<string, string | undefined>>;
    readonly cwd: string;
    readonly home: string;
    /** A regular file exists at this path. */
    readonly isFile: (path: string) => boolean;
    /** A directory exists at this path. */
    readonly isDir: (path: string) => boolean;
    /** The absolute path of an executable on `PATH`, when one exists. */
    readonly onPath: (name: string) => string | undefined;
}
/** The resolved layout, with one note per decision for diagnostics. */
export interface PmLayout {
    /** The `pm` launcher every command runs. */
    readonly pmBin: string;
    /** Working directory the launcher is invoked from. */
    readonly pmCwd: string;
    /** Configuration file named by default (`DSH_UI_PM_CONFIG` still overrides). */
    readonly pmConfig: string;
    /** Workbench directory used by default (`DSH_UI_PM_APP_DIR` still overrides). */
    readonly appDir: string;
    /** One line per decision. */
    readonly notes: readonly string[];
}
/**
 * Resolve the layout from machine facts.
 * @param input - environment, directories, and the two existence predicates.
 * @returns the launcher, working directory, configuration, workbench, and notes.
 */
export declare function resolvePmLayout(input: PmLayoutInput): PmLayout;
/** A regular file exists at this path. */
export declare function isFileAt(path: string): boolean;
/** A directory exists at this path. */
export declare function isDirAt(path: string): boolean;
/**
 * The absolute path of an executable on `PATH`.
 * @param name - executable name, without directories.
 * @returns the first match, or undefined when `PATH` holds none.
 */
export declare function executableOnPath(name: string): string | undefined;
/** Resolve the layout against this process. */
export declare function resolveProcessPmLayout(): PmLayout;
//# sourceMappingURL=pm-layout.d.ts.map