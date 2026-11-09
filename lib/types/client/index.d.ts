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
import type { Context as ClientContext } from '@deepseek-ai/cordis';
import { type PmKey } from './locales.ts';
declare module '@deepseek-ai/dsh-client-ui-slots' {
    interface LocaleNamespaceMap {
        /** Right-Sidebar PM tab and guide copy. */
        pm: PmKey;
    }
}
/** Required services: slots, Session/Workspace feeds, Workspace navigation, copy, and the right-Sidebar registry. */
export declare const inject: string[];
/**
 * Register the panel, its Sidebar row, and the Sidebar-foot count.
 * @param ctx - browser services used by these contributions.
 */
export declare function apply(ctx: ClientContext): void;
//# sourceMappingURL=index.d.ts.map