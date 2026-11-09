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
/**
 * Classify one Session id against the current projections.
 * @param id - Session a work card names.
 * @param sessions - current Session list projection.
 * @param workspaces - current Workspace and archive projection.
 * @returns whether the id is loaded, archived, still loading, or merely absent from the window.
 */
export function sessionLinkState(id, sessions, workspaces) {
    if (sessions.phase === 'pending' || workspaces.phase === 'pending')
        return 'loading';
    // The registry-global archive set is authoritative, unlike a Workspace's sessionIds.
    if (workspaces.archivedSessionIds.includes(id))
        return 'archived';
    if (sessions.ids.includes(id))
        return 'available';
    return 'not-loaded';
}
/** Message of an unknown throw. */
function messageOf(error) {
    return error instanceof Error ? error.message : String(error);
}
/** The Workspace that accounts for one Session, when one does. */
function owningWorkspace(feeds, id) {
    const owner = feeds.workspaces().items.find(item => item.sessionIds.includes(id));
    return owner === undefined ? undefined : { workspaceId: owner.workspaceId, title: owner.title };
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
export async function openCardSession(nav, feeds, probe, id) {
    const target = id;
    const state = sessionLinkState(target, feeds.sessions(), feeds.workspaces());
    if (state === 'loading')
        return { kind: 'loading' };
    if (state === 'archived')
        return { kind: 'archived' };
    if (state === 'available') {
        nav.openSession(target);
        return { kind: 'opened' };
    }
    const refusal = await probe.open(id);
    if (refusal === null) {
        nav.openSession(target);
        return { kind: 'loaded' };
    }
    const owner = owningWorkspace(feeds, target);
    if (owner !== undefined) {
        try {
            await nav.openWorkspace(owner.workspaceId);
        }
        catch (error) {
            return { kind: 'failed', detail: `connecting Workspace "${owner.title}" failed: ${messageOf(error)}` };
        }
        const after = sessionLinkState(target, feeds.sessions(), feeds.workspaces());
        if (after === 'available') {
            nav.openSession(target);
            return { kind: 'workspace-opened' };
        }
        if (after === 'archived')
            return { kind: 'archived' };
    }
    return { kind: 'unknown', detail: refusal };
}
/**
 * Explain one outcome in user-facing terms, stating only what is known.
 * @param outcome - result of {@link openCardSession}.
 * @param sessionId - the Session the click targeted.
 * @param instance - work-memory instance that recorded the card.
 * @returns the notice text, or null when navigation succeeded silently.
 */
export function openOutcomeNotice(outcome, sessionId, instance) {
    switch (outcome.kind) {
        case 'opened':
        case 'loaded':
        case 'workspace-opened':
            return null;
        case 'loading':
            return 'The Session list is still loading; try again in a moment.';
        case 'archived':
            return `Session ${sessionId} is archived; unarchive it in the Sidebar to open it.`;
        case 'failed':
            return outcome.detail;
        case 'unknown':
            return `Session ${sessionId} is not in the loaded Session list and the Host could not open it (${outcome.detail}). `
                + `It may be a Session of another DSH instance — this card was recorded by "${instance}" — or it may no longer exist. `
                + 'Open the DSH instance that recorded the card, or check the Session id.';
    }
}
//# sourceMappingURL=session-open.js.map