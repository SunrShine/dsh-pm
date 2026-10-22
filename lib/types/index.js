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
import { execFile } from 'node:child_process';
import { readFile } from 'node:fs/promises';
import { join } from 'node:path';
import { CAPABILITIES_ROUTE, buildArgv, capabilities, commandFailure, firstLine, listBody, matchRoute, parseObject, readLimit, readRead, readWrite, routePrefixes, successEnvelope, } from "./domain-routes.js";
import { resolveProcessPmLayout } from "./pm-layout.js";
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
export const PM_BIN = LAYOUT.pmBin;
/** Working directory the launcher is invoked from. */
export const PM_CWD = LAYOUT.pmCwd;
/** Configuration file the work-memory commands run with. */
export const DEFAULT_PM_CONFIG = LAYOUT.pmConfig;
/** Default directory of the static workbench the panel embeds. */
export const DEFAULT_APP_DIR = LAYOUT.appDir;
/** How each of the four was found, for diagnostics. */
export const PM_LAYOUT_NOTES = LAYOUT.notes;
/** Absolute pathname of the read-only work-card endpoint. */
export const CARDS_ROUTE = '/ui-pm/cards';
/** Absolute pathname prefix of the hosted workbench. */
export const APP_ROUTE = '/ui-pm/app';
/** Absolute pathname of the quick-note endpoint. */
export const CAPTURE_ROUTE = '/ui-pm/capture';
/** Longest quick note the capture endpoint accepts, in characters. */
export const MAX_CAPTURE_CHARS = 8000;
/** Child-process deadline for a library scan; the scan is the slow part. */
const SCAN_TIMEOUT_MS = 120_000;
/** Child-process deadline for one domain command or inbox append. */
const CAPTURE_TIMEOUT_MS = 60_000;
/** Upper bound on captured stdout: the full card list for a large library. */
const MAX_BUFFER_BYTES = 32 * 1024 * 1024;
/** Upper bound on one request body. */
const MAX_BODY_BYTES = 64 * 1024;
/** How long one payload is served before another `pm ui-cards` run is allowed. */
export const CACHE_TTL_MS = 45_000;
/** Content type per served extension; an extension absent here is not served. */
const APP_TYPES = {
    html: 'text/html; charset=utf-8',
    css: 'text/css; charset=utf-8',
    js: 'text/javascript; charset=utf-8',
    map: 'application/json; charset=utf-8',
    svg: 'image/svg+xml',
    png: 'image/png',
    woff2: 'font/woff2',
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
export function appContentType(name) {
    return APP_TYPES[name.slice(name.lastIndexOf('.') + 1)];
}
/**
 * Directory the static route reads.
 *
 * The build-time client environment types `process.env` with only
 * `DSH_CLIENT_*` keys; these host-only deploy paths are read through one
 * documented widening instead of a name that would lie about being a client
 * build input.
 */
export const APP_DIR = process.env['DSH_UI_PM_APP_DIR']
    ?? DEFAULT_APP_DIR;
/**
 * Configuration file every invocation names explicitly, overridable per host.
 *
 * Naming the file is what makes a write a declared act: `pm` refuses a write
 * that never said which library it belongs to, and this plugin always means the
 * library its own configuration selects. Pointing the override at a temporary
 * `pm.toml` is also how a real end-to-end write is verified without touching
 * the library the user works in.
 */
export const PM_CONFIG = process.env['DSH_UI_PM_CONFIG']
    ?? DEFAULT_PM_CONFIG;
/** Arguments every `pm` invocation carries ahead of its subcommand. */
function globalArgs() {
    return ['--config', PM_CONFIG];
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
export function captureArgs(text) {
    return [...globalArgs(), 'capture', text, '--json'];
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
        execFile(PM_BIN, [...args], 
        // The launcher is a POSIX sh script that execs `python3`; the Host process
        // environment (verified to carry the user's full PATH) is inherited as-is.
        { cwd: PM_CWD, timeout, maxBuffer: MAX_BUFFER_BYTES, encoding: 'utf8' }, (error, stdout, stderr) => {
            const code = error === null ? 0 : (typeof error.code === 'number' ? error.code : 1);
            resolve({ code, stdout, stderr });
        });
    });
}
/** Run one `pm` subcommand and parse its stdout as JSON, rejecting on any failure. */
async function runJson(args, timeout, label) {
    const result = await runCommand(args, timeout);
    if (result.code !== 0) {
        throw new Error(result.stderr.trim() === '' ? label + ' exited with code ' + String(result.code) : result.stderr.trim());
    }
    const parsed = parseObject(result.stdout);
    if (parsed === undefined)
        throw new Error(label + ' returned invalid JSON');
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
export function readUiCards(options = {}) {
    if (options.fresh !== true && cached !== undefined && Date.now() - cached.at < CACHE_TTL_MS) {
        return Promise.resolve(cached.payload);
    }
    pending ??= runJson([...globalArgs(), 'ui-cards'], SCAN_TIMEOUT_MS, 'pm ui-cards')
        .then((payload) => {
        cached = { at: Date.now(), payload };
        return payload;
    })
        .finally(() => { pending = undefined; });
    return pending;
}
/**
 * Append one quick note to the work-memory inbox.
 * @param text - note text, already validated by the endpoint.
 * @returns the parsed `pm capture --json` result.
 * @throws when the launcher fails, times out, or prints something that is not JSON.
 */
export function runCapture(text) {
    return runJson(captureArgs(text), CAPTURE_TIMEOUT_MS, 'pm capture');
}
/** Write one JSON response and end it. */
function sendJson(res, status, body) {
    res.writeHead(status, {
        'content-type': 'application/json; charset=utf-8',
        'cache-control': 'no-store',
    });
    res.end(JSON.stringify(body));
}
/** Write one text response and end it; `HEAD` sends the headers alone. */
function sendText(res, status, contentType, body, head) {
    res.writeHead(status, {
        'content-type': contentType,
        'content-length': String(Buffer.byteLength(body)),
        'cache-control': 'no-store',
        'x-content-type-options': 'nosniff',
    });
    res.end(head ? undefined : body);
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
        const buffer = typeof chunk === 'string' ? Buffer.from(chunk) : chunk;
        size += buffer.byteLength;
        if (size > MAX_BODY_BYTES)
            throw new Error('request body is larger than 64 KiB');
        chunks.push(buffer);
    }
    return Buffer.concat(chunks).toString('utf8');
}
/**
 * Answer one read of the work-card endpoint. Only GET is served; a failed read
 * is reported as a structured 502 so the browser half can show the reason
 * instead of an empty list.
 */
async function cardsHandler(req, res) {
    if (req.method !== 'GET' && req.method !== 'HEAD') {
        res.writeHead(405, { allow: 'GET, HEAD' });
        res.end();
        return;
    }
    try {
        // The panel's Refresh presses `?refresh=1`; every ordinary mount reuses the
        // cached payload rather than rescanning the library.
        const fresh = new URL(req.url ?? '/', 'http://x').searchParams.has('refresh');
        const data = await readUiCards(fresh ? { fresh: true } : {});
        sendJson(res, 200, { ok: true, data });
    }
    catch (error) {
        sendJson(res, 502, { ok: false, error: { code: 'COMMAND_FAILED', message: summarise(error) } });
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
export function resolveAppFile(pathname) {
    const prefix = APP_ROUTE + '/';
    if (!pathname.startsWith(prefix))
        return { kind: 'missing' };
    let decoded;
    try {
        decoded = decodeURIComponent(pathname.slice(prefix.length));
    }
    catch {
        return { kind: 'escape' };
    }
    if (decoded === '')
        return { kind: 'file', name: 'index.html' };
    if (decoded.includes('..') || decoded.includes('/') || decoded.includes('\\') || decoded.startsWith('.')) {
        return { kind: 'escape' };
    }
    // A single segment with a served extension; anything else simply names nothing.
    return APP_FILE_NAME.test(decoded) ? { kind: 'file', name: decoded } : { kind: 'missing' };
}
/** Serve one file of the embedded workbench. */
async function appHandler(req, res) {
    const method = req.method ?? 'GET';
    if (method !== 'GET' && method !== 'HEAD') {
        res.writeHead(405, { allow: 'GET, HEAD' });
        res.end();
        return;
    }
    const head = method === 'HEAD';
    const url = new URL(req.url ?? '/', 'http://x');
    if (url.pathname === APP_ROUTE) {
        // The workbench's own relative references resolve against a directory.
        res.writeHead(308, { location: APP_ROUTE + '/' + url.search });
        res.end();
        return;
    }
    const resolved = resolveAppFile(url.pathname);
    if (resolved.kind === 'escape') {
        sendText(res, 400, 'text/plain; charset=utf-8', 'Bad request: path escapes the workbench directory\n', head);
        return;
    }
    if (resolved.kind === 'missing') {
        sendText(res, 404, 'text/plain; charset=utf-8', 'Not found\n', head);
        return;
    }
    try {
        // Read as bytes: icons and fonts are not text, and sendText measures bytes.
        const body = await readFile(join(APP_DIR, resolved.name));
        sendText(res, 200, appContentType(resolved.name) ?? 'application/octet-stream', body.toString('utf8'), head);
    }
    catch (error) {
        if (error.code === 'ENOENT') {
            sendText(res, 404, 'text/plain; charset=utf-8', 'Not found: ' + resolved.name + ' is missing from ' + APP_DIR + '\n', head);
            return;
        }
        sendText(res, 500, 'text/plain; charset=utf-8', 'The workbench could not be read\n', head);
    }
}
/**
 * Answer one quick-note append: the note goes to the work-memory inbox through
 * `pm capture`, and the card cache is dropped so the very next read reports it.
 */
async function captureHandler(req, res) {
    if ((req.method ?? '') !== 'POST') {
        res.writeHead(405, { allow: 'POST' });
        res.end();
        return;
    }
    let body;
    try {
        body = await readBody(req);
    }
    catch (error) {
        sendJson(res, 413, { ok: false, error: { code: 'BODY_TOO_LARGE', message: summarise(error) } });
        return;
    }
    const parsed = body.trim() === '' ? {} : parseObject(body);
    if (parsed === undefined) {
        sendJson(res, 400, { ok: false, error: { code: 'INVALID_BODY', message: 'body must be JSON of the form {"text": "…"}' } });
        return;
    }
    const text = parsed.text;
    if (typeof text !== 'string' || text.trim() === '') {
        sendJson(res, 400, { ok: false, error: { code: 'INVALID_BODY', message: 'text must be a non-empty string' } });
        return;
    }
    const note = text.trim();
    if (note.length > MAX_CAPTURE_CHARS) {
        sendJson(res, 400, {
            ok: false,
            error: { code: 'INVALID_BODY', message: 'text must be at most ' + String(MAX_CAPTURE_CHARS) + ' characters' },
        });
        return;
    }
    try {
        const result = await runCapture(note);
        cached = undefined;
        sendJson(res, 200, { ok: true, result });
    }
    catch (error) {
        sendJson(res, 502, { ok: false, error: { code: 'COMMAND_FAILED', message: summarise(error) } });
    }
}
/**
 * Execute one table entry: validate, build argv, run, map the exit code, and
 * shape the reply. Every domain endpoint goes through this one path, so the
 * rules — identity checks, the shared write body, the 3/2/other mapping, the
 * envelope, and the card-cache drop after a write — exist once.
 */
async function domainHandler(req, res) {
    const method = req.method ?? 'GET';
    const url = new URL(req.url ?? '/', 'http://x');
    const matched = matchRoute(url.pathname, method);
    if (matched === undefined) {
        sendJson(res, 404, { ok: false, error: { code: 'NOT_FOUND', message: 'no endpoint at ' + url.pathname } });
        return;
    }
    if ('methods' in matched) {
        res.writeHead(405, { allow: matched.methods.join(', ') });
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
        }
        catch (error) {
            sendJson(res, 413, { ok: false, error: { code: 'BODY_TOO_LARGE', message: summarise(error) } });
            return;
        }
        const parsedBody = text.trim() === '' ? {} : parseObject(text);
        if (parsedBody === undefined) {
            sendJson(res, 400, { ok: false, error: { code: 'INVALID_BODY', message: 'body must be a JSON object' } });
            return;
        }
        body = parsedBody;
    }
    const limit = readLimit(url.searchParams);
    if ('status' in limit) {
        sendJson(res, limit.status, limit.body);
        return;
    }
    const request = write
        ? readWrite(spec, matched.params, url.searchParams, body)
        : readRead(spec, matched.params, url.searchParams);
    if ('status' in request) {
        sendJson(res, request.status, request.body);
        return;
    }
    const argv = buildArgv(request.argv, request.bindings, PM_CONFIG);
    const result = await runCommand(argv, CAPTURE_TIMEOUT_MS);
    if (result.code !== 0) {
        const failure = commandFailure(result.code, result.stdout, result.stderr, spec.failureStatuses);
        sendJson(res, failure.status, failure.body);
        return;
    }
    const parsed = parseObject(result.stdout);
    if (parsed === undefined) {
        sendJson(res, 502, { ok: false, error: { code: 'BAD_OUTPUT', message: 'pm printed no JSON object' } });
        return;
    }
    // The card payload carries the inbox, so a write invalidates the cached read.
    if (write)
        cached = undefined;
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
    if ((req.method ?? '') !== 'GET' && (req.method ?? '') !== 'HEAD') {
        res.writeHead(405, { allow: 'GET, HEAD' });
        res.end();
        return;
    }
    if (pmVersion === undefined) {
        const result = await runCommand(['--version'], CAPTURE_TIMEOUT_MS);
        pmVersion = result.code === 0 && result.stdout.trim() !== '' ? result.stdout.trim() : null;
    }
    sendJson(res, 200, capabilities(pmVersion, PM_CONFIG, {
        pmBin: PM_BIN,
        pmCwd: PM_CWD,
        pmConfig: PM_CONFIG,
        appDir: APP_DIR,
        notes: PM_LAYOUT_NOTES,
    }));
}
/**
 * Mount the work-card, workbench, quick-note, capability, and domain routes.
 * The domain prefixes come from the route table, so registering a domain and
 * adding an endpoint are the same edit.
 * @param ctx - host context the profile mounted this plugin into.
 */
export function apply(ctx) {
    // Say once where the four values came from: a wrong library or a missing
    // workbench is then diagnosable from the log without guessing.
    ctx.logger.info('[ui-pm] %s', PM_LAYOUT_NOTES.join('; '));
    ctx.inject(['webServer'], (webCtx) => {
        webCtx.effect(() => webCtx.webServer.register({ kind: 'exact', path: CARDS_ROUTE, handler: cardsHandler }), 'ui-pm: work-card route');
        webCtx.effect(() => webCtx.webServer.register({ kind: 'prefix', path: APP_ROUTE, handler: appHandler }), 'ui-pm: workbench route');
        webCtx.effect(() => webCtx.webServer.register({ kind: 'exact', path: CAPTURE_ROUTE, handler: captureHandler }), 'ui-pm: quick-note route');
        for (const prefix of routePrefixes()) {
            if (prefix === CAPABILITIES_ROUTE)
                continue;
            webCtx.effect(() => webCtx.webServer.register({ kind: 'prefix', path: prefix, handler: domainHandler }), 'ui-pm: ' + prefix + ' routes');
        }
        webCtx.effect(() => webCtx.webServer.register({ kind: 'exact', path: CAPABILITIES_ROUTE, handler: capabilitiesHandler }), 'ui-pm: capability route');
    });
}
//# sourceMappingURL=index.js.map