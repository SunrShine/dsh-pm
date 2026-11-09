/** Right-Sidebar body: the same PM workbench, hosted next to the chat. */
import type { InjectFace, PropsLocale, PropsRuntime } from '@deepseek-ai/dsh-client-ui-slots';
import type { PmPanelInjected } from './PmPanel.tsx';
/** Composed props of the right-Sidebar PM tab body. */
export type PmRightPaneProps = PropsRuntime<'sidebar.right.pane.tab'> & PropsLocale<'pm'> & InjectFace<PmPanelInjected>;
/**
 * Render the workbench in the right sidebar. The embedded page and its
 * `pm-open-session` bridge are exactly the main panel's, so a card press while
 * the chat stays open navigates the main column instead of replacing this tab.
 * @param props - framework-bound tab identity and the injected Session opener.
 * @returns the workbench frame.
 */
export declare function PmRightPane({ openSession, runPrompt, sessionId }: PmRightPaneProps): import("react").JSX.Element;
//# sourceMappingURL=PmRightPane.d.ts.map