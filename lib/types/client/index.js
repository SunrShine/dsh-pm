/**
 * Browser half of the work-memory (PM) panel.
 *
 * The main column hosts the static PM workbench (served by the node half at
 * /ui-pm/app/) and bridges the Session requests it posts back, the Sidebar
 * panel row opens that panel, and the Sidebar foot carries an always-visible
 * needs-attention count read from the same payload the workbench fetches. Every
 * navigation outcome is explained in the panel — a card whose Session belongs to
 * another DSH instance must say so rather than look like a dead click.
 *
 * The same workbench is also a right-Sidebar tab type (`pmRightTab`): opening it
 * hosts the page next to the conversation, so the chat and the work-memory pages
 * run side by side. Its body reuses this panel's `pm-open-session` bridge, which
 * means a card press still navigates the main column instead of replacing the tab.
 */
import { PmFooterSummary } from "./PmFooterSummary.js";
import { PmPanel } from "./PmPanel.js";
import { PmPanelIcon } from "./PmPanelIcon.js";
import { PmHeaderButton } from "./PmHeaderButton.js";
import { PmRightPane } from "./PmRightPane.js";
import { en, zh } from "./locales.js";
import { PM_RIGHT_ID, PM_RIGHT_KIND, pmRightTab } from "./pmRightTab.js";
import { openCardSession, openOutcomeNotice } from "./session-open.js";
/** Main-panel key this package owns. */
const PANEL_ID = 'pm';
/** This package's locale namespace. */
const NS = 'pm';
/** Required services: slots, Session/Workspace feeds, Workspace navigation, copy, and the right-Sidebar registry. */
export const inject = ['slots', 'sessions', 'workspaces', 'uiWorkspace', 'locale', 'sidebarRightTabs', 'sidebarRight'];
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
    // The right-Sidebar tab shares this exact face so both hosts behave alike.
    // Phase 2: the workbench asks this host to enqueue the summary prompt into
    // the conversation itself. The Host probe is not reused here because a
    // refused prompt must report the prompt error, not "another instance".
    const runPrompt = async (sessionId, prompt, open = true) => {
        let reference;
        try {
            reference = ctx.sessions.retain(sessionId, { source: 'controllerOperation' });
        }
        catch (error) {
            return error instanceof Error ? error.message : String(error);
        }
        try {
            await reference.ready;
            const result = await reference.binding.session.prompt([{ type: 'text', text: prompt }], 'queue');
            if (!result.ok)
                return `${result.error.code}: ${result.error.message}`;
            if (open)
                ctx.uiWorkspace.openSession(sessionId);
            return null;
        }
        catch (error) {
            return error instanceof Error ? error.message : String(error);
        }
        finally {
            reference.release();
        }
    };
    const bridge = {
        openSession: async (sessionId, instance) => openOutcomeNotice(await openCardSession(nav, feeds, probe, sessionId), sessionId, instance),
        runPrompt,
    };
    ctx.effect(() => ctx.locale.register(NS, { zh, en }), 'ui-pm: dictionaries');
    const t = ctx.locale.bind(NS);
    ctx.slots.inject('main', () => ctx.slots.register({
        name: 'main',
        key: PANEL_ID,
        inject: () => bridge,
    }, PmPanel));
    // Right-Sidebar tab type: a page type with a guide entry, so the workbench can
    // be opened beside the conversation instead of replacing it.
    ctx.effect(() => ctx.sidebarRightTabs.register(pmRightTab(t)), 'ui-pm: right tab type');
    ctx.slots.inject('sidebar.right.pane.tab', () => ctx.slots.register({
        name: 'sidebar.right.pane.tab', key: PM_RIGHT_ID, locale: NS,
        inject: () => bridge,
    }, PmRightPane));
    // A + auto-open trigger: whenever the on-screen Session changes, open the PM
    // page once for that Session, so chat and the workbench are paired without a
    // manual click. keepMounted:false unloads the previous Session's iframe, so at
    // most one PM page context is alive at a time. The set is per page load: a tab
    // the user closed is not reopened when they switch back.
    // One auto-open per Session per page load. The trigger lives in
    // PmHeaderButton: the session-header action only renders for the foreground
    // Session, so its mount is the reliable "a Session became current" signal.
    const autoOpened = new Set();
    const autoOpen = (sessionId) => {
        if (autoOpened.has(sessionId))
            return;
        autoOpened.add(sessionId);
        ctx.sidebarRight.openTab(PM_RIGHT_KIND);
    };
    // Session-header toggle: one click puts the workbench in the right sidebar next
    // to the conversation; an already-active PM tab collapses the column.
    ctx.slots.inject('conversation.session.header.actions', () => ctx.slots.register({
        name: 'conversation.session.header.actions',
        id: 'pm-toggle',
        order: 30,
        locale: NS,
        inject: () => ({
            autoOpen,
            toggle: () => {
                const active = ctx.sidebarRight.active();
                if (ctx.sidebarRight.isExpanded() && active !== undefined && active.kind === PM_RIGHT_KIND) {
                    ctx.sidebarRight.toggleExpanded();
                    return;
                }
                ctx.sidebarRight.openTab(PM_RIGHT_KIND);
            },
            t,
        }),
    }, PmHeaderButton));
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