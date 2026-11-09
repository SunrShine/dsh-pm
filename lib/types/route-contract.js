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
import { createHash } from 'node:crypto';
import { DOMAIN_ROUTES, EXECUTOR_FLAGS, FIXED_ROUTE_COMMANDS, HOST_OWNED_FLAGS, SHARED_WRITE_FIELDS, UNEXPOSED_COMMANDS, UNSUPPORTED_ENDPOINTS, argvFlagsOf, cliPathOf, } from "./domain-routes.js";
/** Project one body field, omitting what it does not declare. */
function bodyField(field) {
    return {
        name: field.name,
        ...(field.flag === undefined ? {} : { flag: field.flag }),
        kind: field.kind,
        required: field.required === true,
        ...(field.values === undefined ? {} : { values: [...field.values] }),
        ...(field.allowEmpty === true ? { allowEmpty: true } : {}),
        ...(field.deprecated === undefined ? {} : { deprecated: field.deprecated }),
        ...(field.forbid === undefined ? {} : { forbid: { ...field.forbid } }),
    };
}
/** Project one query field, omitting what it does not declare. */
function queryField(field) {
    return {
        name: field.name,
        ...(field.flag === undefined ? {} : { flag: field.flag }),
        kind: field.required === true ? 'required-query' : 'query',
        required: field.required === true,
        ...(field.boolean === true ? { boolean: true } : {}),
    };
}
/**
 * Project the route table into the contract document.
 * @returns the contract, in table order so a reordering is visible.
 */
export function routeContract() {
    return {
        contractVersion: 1,
        generatedFrom: 'src/domain-routes.ts',
        executorFlags: [...EXECUTOR_FLAGS],
        defaultSharedFields: SHARED_WRITE_FIELDS.map(bodyField),
        hostOwnedFlags: HOST_OWNED_FLAGS.map(entry => ({ flag: entry.flag, reason: entry.reason })),
        unsupported: UNSUPPORTED_ENDPOINTS.map(entry => ({
            method: entry.method,
            path: entry.path,
            reason: entry.reason,
        })),
        unexposedCommands: UNEXPOSED_COMMANDS.map(entry => ({
            cliPath: [...entry.cliPath],
            reason: entry.reason,
        })),
        fixedRouteCommands: FIXED_ROUTE_COMMANDS.map(entry => ({
            cliPath: [...entry.cliPath],
            reason: entry.reason,
        })),
        routes: DOMAIN_ROUTES.map((spec) => {
            const commands = spec.actions === undefined
                ? [{
                        cliPath: cliPathOf(spec.argv ?? []),
                        argvFlags: argvFlagsOf(spec.argv ?? []),
                    }]
                : Object.entries(spec.actions.cases).map(([action, one]) => ({
                    cliPath: cliPathOf(one.argv),
                    argvFlags: argvFlagsOf(one.argv),
                    action,
                    ...(one.body === undefined ? {} : { body: one.body.map(bodyField) }),
                    ...(one.exactlyOne === undefined ? {} : { exactlyOne: [...one.exactlyOne] }),
                    ...(one.required === undefined ? {} : { required: [...one.required] }),
                    ...(one.notForwarded === undefined
                        ? {}
                        : { notForwarded: one.notForwarded.map(entry => ({ flag: entry.flag, reason: entry.reason })) }),
                }));
            const patterns = spec.patterns === undefined
                ? {}
                : Object.fromEntries(Object.entries(spec.patterns).map(([name, pattern]) => [name, pattern.source]));
            return {
                method: spec.method,
                path: spec.path,
                write: spec.write === true,
                revision: spec.revision ?? 'required',
                ...(spec.ids === undefined ? {} : { ids: { ...spec.ids } }),
                ...(Object.keys(patterns).length === 0 ? {} : { patterns }),
                query: (spec.query ?? []).map(queryField),
                body: (spec.body ?? []).map(bodyField),
                ...(spec.required === undefined ? {} : { required: [...spec.required] }),
                commands,
                ...(spec.shared === undefined ? {} : { shared: spec.shared.map(bodyField) }),
                ...(spec.notForwarded === undefined
                    ? {}
                    : { notForwarded: spec.notForwarded.map(entry => ({ flag: entry.flag, reason: entry.reason })) }),
                ...(spec.unknownFieldHints === undefined ? {} : { unknownFieldHints: { ...spec.unknownFieldHints } }),
                ...(spec.notes === undefined ? {} : { notes: [...spec.notes] }),
                ...(spec.failureStatuses === undefined ? {} : { failureStatuses: { ...spec.failureStatuses } }),
                ...(spec.flattenData === true ? { flattenData: true } : {}),
            };
        }),
    };
}
/**
 * Render the contract exactly as it is committed.
 * @param contract - the projected contract.
 * @returns stable JSON text with a trailing newline.
 */
export function renderContract(contract) {
    return JSON.stringify(contract, null, 2) + '\n';
}
/**
 * The digest of a rendered contract, for an external verification record.
 * @param text - rendered contract text.
 * @returns the sha256 hex digest.
 */
export function contractDigest(text) {
    return createHash('sha256').update(text).digest('hex');
}
//# sourceMappingURL=route-contract.js.map