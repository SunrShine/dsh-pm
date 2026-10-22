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
import type { Context as ClientContext } from '@deepseek-ai/cordis';
/** Required services: the slot registry, Session/Workspace feeds, and Workspace navigation. */
export declare const inject: string[];
/**
 * Register the panel, its Sidebar row, and the Sidebar-foot count.
 * @param ctx - browser services used by these contributions.
 */
export declare function apply(ctx: ClientContext): void;
//# sourceMappingURL=index.d.ts.map