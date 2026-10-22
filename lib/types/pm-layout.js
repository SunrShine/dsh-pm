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
import { accessSync, constants, statSync } from 'node:fs';
import { homedir } from 'node:os';
import { basename, dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
/**
 * The workbench shipped inside this package, one level above src/ or lib/.
 * Both layouts resolve to the same directory, so the source tree and the built
 * package agree on where `app/` would be.
 */
export const PACKAGED_APP_DIR = fileURLToPath(new URL('../app/', import.meta.url));
/** Where a packaged installation keeps its own configuration. */
export const USER_CONFIG_PATH = join(homedir(), '.dsh-pm', 'pm.toml');
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
    const recorded = HOST_ENV['PWD'];
    return recorded !== undefined && recorded !== '' ? recorded : homedir();
}
/** First non-empty value among these variable names. */
function envValue(env, names) {
    for (const name of names) {
        const value = env[name];
        if (value !== undefined && value.trim() !== '')
            return value.trim();
    }
    return undefined;
}
/**
 * Directories that could hold a checkout of the pm tools, most explicit first.
 * @param input - the machine facts.
 * @param launcher - the launcher already discovered, if any.
 * @returns candidate repository roots.
 */
function repoCandidates(input, launcher) {
    const candidates = [];
    const explicit = envValue(input.env, ['DSH_UI_PM_PM_ROOT', 'PM_ROOT']);
    if (explicit !== undefined)
        candidates.push(explicit);
    // A launcher installed as <root>/bin/pm names its own repository.
    if (launcher !== undefined && basename(launcher) === 'pm' && basename(dirname(launcher)) === 'bin') {
        candidates.push(dirname(dirname(launcher)));
    }
    // The working directory and its ancestors, so a checkout started from inside
    // itself finds its own configuration.
    let current = input.cwd;
    for (let depth = 0; depth < 4; depth += 1) {
        candidates.push(current);
        const parent = dirname(current);
        if (parent === current)
            break;
        current = parent;
    }
    // Conventional developer checkouts, existence-guarded like every other step.
    candidates.push(join(input.home, 'projects', 'tools_dev', 'pm_tools'));
    candidates.push(join(input.home, 'pm_tools'));
    return candidates;
}
/**
 * Resolve the layout from machine facts.
 * @param input - environment, directories, and the two existence predicates.
 * @returns the launcher, working directory, configuration, workbench, and notes.
 */
export function resolvePmLayout(input) {
    const notes = [];
    const launcherChoice = envValue(input.env, ['DSH_UI_PM_PM_BIN', 'PM_BIN']);
    if (launcherChoice !== undefined)
        notes.push('pm launcher: DSH_UI_PM_PM_BIN/PM_BIN');
    const onPath = launcherChoice === undefined ? input.onPath('pm') : undefined;
    if (onPath !== undefined)
        notes.push('pm launcher: PATH');
    const discovered = launcherChoice ?? onPath;
    const repo = repoCandidates(input, discovered)
        .find(candidate => input.isFile(join(candidate, 'config', 'pm.toml')));
    if (repo !== undefined)
        notes.push('pm checkout: ' + repo);
    const repoBin = repo === undefined ? undefined : join(repo, 'bin', 'pm');
    const pmBin = discovered ?? (repoBin !== undefined && input.isFile(repoBin) ? repoBin : 'pm');
    if (discovered === undefined) {
        notes.push(repoBin !== undefined && input.isFile(repoBin)
            ? 'pm launcher: checkout'
            : 'pm launcher: bare name (PATH lookup at run time)');
    }
    const cwdConfig = join(input.cwd, 'pm.toml');
    const pmConfig = envValue(input.env, ['PM_CONFIG'])
        ?? (repo === undefined ? undefined : join(repo, 'config', 'pm.toml'))
        ?? (input.isFile(cwdConfig) ? cwdConfig : undefined)
        ?? USER_CONFIG_PATH;
    if (pmConfig === cwdConfig)
        notes.push('pm config: working directory');
    else if (pmConfig === USER_CONFIG_PATH)
        notes.push('pm config: ' + USER_CONFIG_PATH);
    else if (repo !== undefined && pmConfig === join(repo, 'config', 'pm.toml'))
        notes.push('pm config: checkout');
    else
        notes.push('pm config: PM_CONFIG');
    const pmCwd = envValue(input.env, ['DSH_UI_PM_PM_CWD', 'PM_CWD']) ?? repo ?? input.cwd;
    const repoApp = repo === undefined ? undefined : join(repo, 'frontend_impl');
    const packagedApp = input.isDir(PACKAGED_APP_DIR);
    const appDir = packagedApp
        ? PACKAGED_APP_DIR
        : repoApp !== undefined && input.isDir(repoApp) ? repoApp : PACKAGED_APP_DIR;
    if (packagedApp)
        notes.push('workbench: packaged app/');
    else if (repoApp !== undefined && input.isDir(repoApp))
        notes.push('workbench: checkout frontend_impl');
    else
        notes.push('workbench: packaged app/ (missing)');
    return { pmBin, pmCwd, pmConfig, appDir, notes };
}
/** A regular file exists at this path. */
export function isFileAt(path) {
    try {
        return statSync(path).isFile();
    }
    catch {
        return false;
    }
}
/** A directory exists at this path. */
export function isDirAt(path) {
    try {
        return statSync(path).isDirectory();
    }
    catch {
        return false;
    }
}
/**
 * The absolute path of an executable on `PATH`.
 * @param name - executable name, without directories.
 * @returns the first match, or undefined when `PATH` holds none.
 */
export function executableOnPath(name) {
    for (const directory of (HOST_ENV['PATH'] ?? '').split(':')) {
        if (directory === '')
            continue;
        const candidate = join(directory, name);
        try {
            accessSync(candidate, constants.X_OK);
            if (statSync(candidate).isFile())
                return candidate;
        }
        catch {
            // Not executable or not there: keep looking.
        }
    }
    return undefined;
}
/** Resolve the layout against this process. */
export function resolveProcessPmLayout() {
    return resolvePmLayout({
        env: HOST_ENV,
        cwd: hostCwd(),
        home: homedir(),
        isFile: isFileAt,
        isDir: isDirAt,
        onPath: executableOnPath,
    });
}
//# sourceMappingURL=pm-layout.js.map