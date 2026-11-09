/** The right-Sidebar tab type that hosts the PM workbench next to the conversation. */
import type { TranslateNS } from '@deepseek-ai/dsh-client-locale/client';
import type { SidebarRightTabDefinition } from '@deepseek-ai/dsh-client-ui-sidebar-right/client';
/** This implementation's identity in the tab system, and the key its body registers under. */
export declare const PM_RIGHT_ID = "@deepseek-ai/dsh-client-ui-pm";
/** Page-type discriminator used by `sidebarRight.openTab('pm')`. */
export declare const PM_RIGHT_KIND = "pm";
/**
 * The PM tab type's registry definition: a page type (it recognizes no resource
 * address) whose guide entry is the discoverable way to open it.
 * @param t - namespace-bound translate, read fresh on every title call.
 * @returns the definition to register.
 */
export declare function pmRightTab(t: TranslateNS<'pm'>): SidebarRightTabDefinition;
//# sourceMappingURL=pmRightTab.d.ts.map