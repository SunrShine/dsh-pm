/**
 * One shared read of the Host work-card endpoint.
 *
 * The Sidebar summary and the main panel show the same payload, so both read
 * this store instead of issuing their own request. The store is a plain
 * `getSnapshot`/`subscribe` pair because that is the shape React's
 * `useSyncExternalStore` needs; nothing else owns it.
 */
import type { PmUiCards } from './types.ts';
/** Lifecycle of the most recent read. */
export type PmCardsStatus = 'idle' | 'loading' | 'ready' | 'error';
/** Snapshot the components render. */
export interface PmCardsState {
    readonly status: PmCardsStatus;
    readonly data: PmUiCards | null;
    readonly error: string | null;
    readonly loadedAt: number | null;
}
/** Read the current snapshot. */
export declare function getPmCardsState(): PmCardsState;
/**
 * Subscribe to state changes.
 * @param listener - invalidation callback.
 * @returns the unsubscriber.
 */
export declare function subscribePmCards(listener: () => void): () => void;
/** Options of {@link refreshPmCards}. */
export interface RefreshPmCardsOptions {
    /** Ask the Host to rescan the library instead of serving its cached payload. */
    readonly fresh?: boolean;
}
/**
 * Refresh the shared read, sharing one request across concurrent callers.
 * @param options - fresh request policy; the initial mount uses the Host cache.
 * @returns completion after the snapshot is published.
 */
export declare function refreshPmCards(options?: RefreshPmCardsOptions): Promise<void>;
/**
 * Bind the shared store to a component.
 * @returns the current snapshot, re-read on every publish.
 */
export declare function usePmCards(): PmCardsState;
//# sourceMappingURL=pm-store.d.ts.map