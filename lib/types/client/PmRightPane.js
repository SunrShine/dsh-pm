import { jsx as _jsx } from "react/jsx-runtime";
import { PmPanel } from "./PmPanel.js";
/**
 * Render the workbench in the right sidebar. The embedded page and its
 * `pm-open-session` bridge are exactly the main panel's, so a card press while
 * the chat stays open navigates the main column instead of replacing this tab.
 * @param props - framework-bound tab identity and the injected Session opener.
 * @returns the workbench frame.
 */
export function PmRightPane({ openSession, runPrompt, sessionId }) {
    return _jsx(PmPanel, { openSession: openSession, runPrompt: runPrompt, sessionId: sessionId });
}
//# sourceMappingURL=PmRightPane.js.map