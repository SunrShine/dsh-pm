/**
 * One shared read of the Host work-card endpoint.
 *
 * The Sidebar summary and the main panel show the same payload, so both read
 * this store instead of issuing their own request. The store is a plain
 * `getSnapshot`/`subscribe` pair because that is the shape React's
 * `useSyncExternalStore` needs; nothing else owns it.
 */
import { useSyncExternalStore } from 'react';
const INITIAL = { status: 'idle', data: null, error: null, loadedAt: null };
let state = INITIAL;
let inFlight;
const listeners = new Set();
/** Publish one state and notify every subscriber. */
function publish(next) {
    state = next;
    for (const listener of [...listeners])
        listener();
}
/** Read the current snapshot. */
export function getPmCardsState() {
    return state;
}
/**
 * Subscribe to state changes.
 * @param listener - invalidation callback.
 * @returns the unsubscriber.
 */
export function subscribePmCards(listener) {
    listeners.add(listener);
    return () => { listeners.delete(listener); };
}
/** Document-relative endpoint URL, so a mounted base path keeps working. */
function cardsUrl(fresh) {
    return new URL(fresh ? 'ui-pm/cards?refresh=1' : 'ui-pm/cards', document.baseURI).href;
}
/** One read of the endpoint, retaining the previous payload on failure. */
async function load(fresh) {
    if (state.data === null)
        publish({ status: 'loading', data: null, error: null, loadedAt: null });
    try {
        const response = await fetch(cardsUrl(fresh), { headers: { accept: 'application/json' } });
        // Without the Host half's route the SPA fallback answers with index.html and
        // a 200, which would otherwise surface as a JSON syntax error.
        const contentType = response.headers.get('content-type') ?? '';
        if (!contentType.includes('application/json')) {
            throw new Error('the Host half is not serving /ui-pm/cards yet — restart the dsh web process');
        }
        const body = await response.json();
        if (!response.ok || body.ok !== true || body.data === undefined) {
            throw new Error(body.error ?? `HTTP ${String(response.status)}`);
        }
        publish({ status: 'ready', data: body.data, error: null, loadedAt: Date.now() });
    }
    catch (error) {
        publish({
            status: 'error',
            data: state.data,
            error: error instanceof Error ? error.message : String(error),
            loadedAt: state.loadedAt,
        });
    }
}
/**
 * Refresh the shared read, sharing one request across concurrent callers.
 * @param options - fresh request policy; the initial mount uses the Host cache.
 * @returns completion after the snapshot is published.
 */
export function refreshPmCards(options = {}) {
    inFlight ??= load(options.fresh === true).finally(() => { inFlight = undefined; });
    return inFlight;
}
/**
 * Bind the shared store to a component.
 * @returns the current snapshot, re-read on every publish.
 */
export function usePmCards() {
    // The same snapshot answers a server render; the store is module state, not a DOM read.
    return useSyncExternalStore(subscribePmCards, getPmCardsState, getPmCardsState);
}
//# sourceMappingURL=pm-store.js.map