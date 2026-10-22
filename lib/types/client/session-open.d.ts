/**
 * Session navigation for one work card.
 *
 * A work-memory card names a Session that the running page may not have loaded.
 * Neither projection is an existence test: `sessions.list.ids` is the loaded
 * catalog window (older Sessions arrive by paging), and a Workspace's
 * `sessionIds` only accounts for Sessions the catalog already holds. So a card
 * outside the window is probed against the Host by retaining its exact
 * generation and awaiting the shared open attempt, and only a refused open is
 * reported as one — never as "another instance".
 */
import type { SessionListState } from '@deepseek-ai/dsh-api-session-controller/client';
import type { WorkspaceId, WorkspaceSnapshot } from '@deepseek-ai/dsh-api-workspace-controller/client';
import type { SessionId } from '@deepseek-ai/dsh-session/types';
/**
 * Where one Session id stands relative to what the page has already loaded.
 *
 * `not-loaded` claims nothing about existence: the Session may be older than
 * the loaded window, may live in another DSH instance, or may be gone.
 */
export type SessionLinkState = 'available' | 'loading' | 'archived' | 'not-loaded';
/**
 * Classify one Session id against the current projections.
 * @param id - Session a work card names.
 * @param sessions - current Session list projection.
 * @param workspaces - current Workspace and archive projection.
 * @returns whether the id is loaded, archived, still loading, or merely absent from the window.
 */
export declare function sessionLinkState(id: SessionId, sessions: SessionListState, workspaces: WorkspaceSnapshot): SessionLinkState;
/** What one click on a work card actually did. */
export type OpenSessionOutcome = {
    readonly kind: 'opened';
} | {
    readonly kind: 'loaded';
} | {
    readonly kind: 'workspace-opened';
} | {
    readonly kind: 'archived';
} | {
    readonly kind: 'loading';
} | {
    readonly kind: 'unknown';
    readonly detail: string;
} | {
    readonly kind: 'failed';
    readonly detail: string;
};
/** The navigation verbs this package uses, narrowed from the Workspace service. */
export interface SessionNavigation {
    /** Select a Session and show its Conversation. */
    readonly openSession: (sessionId: SessionId) => void;
    /** Connect a Workspace and open its Session. */
    readonly openWorkspace: (workspaceId: WorkspaceId) => Promise<void>;
}
/** Live feeds re-read after every await, so a settled navigation sees current state. */
export interface SessionFeeds {
    sessions(): SessionListState;
    workspaces(): WorkspaceSnapshot;
}
/**
 * Authoritative Host existence probe for one Session id.
 *
 * `sessions.retain` starts the shared initial `Session.open()`; awaiting that
 * reference's `ready` therefore settles exactly when the Host has produced the
 * Session, whatever the loaded window holds.
 */
export interface SessionProbe {
    /**
     * Ask the Host to open one Session.
     * @param sessionId - Session id from the work card.
     * @returns null when the Host opened it, otherwise the refusal message.
     */
    open(sessionId: string): Promise<string | null>;
}
/**
 * Open the Session one work card names.
 *
 * A loaded, unarchived Session opens directly. Anything else is first probed
 * against the Host, which is what lets an older Session outside the loaded
 * window open normally; only after the Host refuses is the Workspace that
 * accounts for the card tried, and only after that does the click report a
 * failure — with the refusal it actually received.
 * @param nav - Workspace navigation verbs.
 * @param feeds - current Session and Workspace projections.
 * @param probe - authoritative Host existence probe.
 * @param id - Session id from the work card, as the contract spells it.
 * @returns what happened, so the caller can either stay quiet or explain.
 */
export declare function openCardSession(nav: SessionNavigation, feeds: SessionFeeds, probe: SessionProbe, id: string): Promise<OpenSessionOutcome>;
/**
 * Explain one outcome in user-facing terms, stating only what is known.
 * @param outcome - result of {@link openCardSession}.
 * @param sessionId - the Session the click targeted.
 * @param instance - work-memory instance that recorded the card.
 * @returns the notice text, or null when navigation succeeded silently.
 */
export declare function openOutcomeNotice(outcome: OpenSessionOutcome, sessionId: string, instance: string): string | null;
//# sourceMappingURL=session-open.d.ts.map