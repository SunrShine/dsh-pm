/**
 * Browser half of the work-memory (PM) panel.
 *
 * The main column hosts the static PM workbench (served by the node half at
 * /ui-pm/app/) and bridges the Session requests it posts back, the Sidebar
 * panel row opens that panel, and the Sidebar foot carries an always-visible
 * needs-attention count read from the same payload the workbench fetches. Every
 * navigation outcome is explained in the panel — a card whose Session belongs to
 * another DSH instance must say so rather than look like a dead click.
 */
import { PmFooterSummary } from "./PmFooterSummary.js";
import { PmPanel } from "./PmPanel.js";
import { PmPanelIcon } from "./PmPanelIcon.js";
import { openCardSession, openOutcomeNotice } from "./session-open.js";
/** Main-panel key this package owns. */
const PANEL_ID = 'pm';
/** Required services: the slot registry, Session/Workspace feeds, and Workspace navigation. */
export const inject = ['slots', 'sessions', 'workspaces', 'uiWorkspace'];
/**
 * Register the panel, its Sidebar row, and the Sidebar-foot count.
 * @param ctx - browser services used by these contributions.
 */
export function apply(ctx) {
    const nav = {
        openSession: (sessionId) => { ctx.uiWorkspace.openSession(sessionId); },
        openWorkspace: (workspaceId) => ctx.uiWorkspace.openWorkspace(workspaceId),
    };
    const feeds = {
        sessions: () => ctx.sessions.list.getSnapshot(),
        workspaces: () => ctx.workspaces.list.getSnapshot(),
    };
    // The loaded catalog window is not an existence test, so a card outside it is
    // probed by retaining the exact Session generation and reading the lifecycle
    // the shared Host open attempt settled into. `ready` alone cannot answer the
    // question: `Session.open()` records a remote refusal in the snapshot instead
    // of rejecting. The probe reference is released immediately after; the
    // navigation that follows keeps its own.
    const probe = {
        open: async (sessionId) => {
            let reference;
            try {
                reference = ctx.sessions.retain(sessionId, { source: 'controllerOperation' });
            }
            catch (error) {
                return error instanceof Error ? error.message : String(error);
            }
            try {
                await reference.ready;
                const snapshot = reference.binding.session.getSnapshot();
                if (snapshot.openState === 'open')
                    return null;
                const refusal = snapshot.openError;
                return refusal === null
                    ? `the Session could not be opened (state: ${snapshot.openState})`
                    : `${refusal.code}: ${refusal.message}`;
            }
            catch (error) {
                return error instanceof Error ? error.message : String(error);
            }
            finally {
                reference.release();
            }
        },
    };
    // The workbench cannot open a Session itself, so it posts one bridge message
    // per press and this seat answers with the same probe and fallbacks the card
    // rows used: loaded, late-loadable, archived, foreign, or a stated failure.
    ctx.slots.inject('main', () => ctx.slots.register({
        name: 'main',
        key: PANEL_ID,
        inject: () => ({
            openSession: async (sessionId, instance) => openOutcomeNotice(await openCardSession(nav, feeds, probe, sessionId), sessionId, instance),
        }),
    }, PmPanel));
    ctx.slots.inject('sidebar.panellist', () => ctx.slots.register({
        name: 'sidebar.panellist',
        id: PANEL_ID,
        order: 10,
        // The workbench's own title uses the same name, so the sidebar entry and the
        // page it opens read as one product.
        label: 'PM 工作台',
    }, PmPanelIcon));
    ctx.slots.inject('sidebar.footer.action', () => ctx.slots.register({
        name: 'sidebar.footer.action',
        id: 'pm-panel',
        order: 20,
    }, PmFooterSummary));
}
//# sourceMappingURL=index.js.map