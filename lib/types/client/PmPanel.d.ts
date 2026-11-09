/**
 * PM workbench panel body.
 *
 * The panel is a host, not a view: the workbench itself is a static page served
 * by this plugin's node half, so the browser half only embeds it and bridges
 * the interactions the page cannot perform for itself — opening a Session and,
 * for Phase 2, enqueueing the summary prompt into that Session so the
 * conversation summarizes itself. Navigation reuses the shared Host probe and
 * fallbacks; a refused prompt is reported rather than silently ignored.
 */
/** Injected share of the panel: Session navigation for one bridge request. */
export interface PmPanelInjected {
    /**
     * Open the Session one workbench card names.
     * @param sessionId - Session id from the workbench.
     * @param instance - work-memory instance that recorded the card.
     * @returns a notice to show, or null when navigation succeeded.
     */
    readonly openSession: (sessionId: string, instance: string) => Promise<string | null>;
    /**
     * Send the summary prompt into the Session itself (Phase 2: the conversation
     * writes its own one-line summary).
     * @param sessionId - Session id from the workbench.
     * @param prompt - prompt text to enqueue.
     * @returns a notice to show, or null when the prompt was accepted.
     */
    readonly runPrompt: (sessionId: string, prompt: string, open?: boolean) => Promise<string | null>;
}
/** One accepted `pm-open-session` bridge request. */
export interface PmBridgeRequest {
    /** Session the workbench asked to open. */
    readonly sessionId: string;
    /** work-memory instance that recorded the card. */
    readonly instance: string;
}
/** One accepted `pm-run-prompt` bridge request. */
export interface PmPromptRequest {
    /** Session the workbench asked to summarize. */
    readonly sessionId: string;
    /** Prompt text the Session should receive. */
    readonly prompt: string;
    /** Whether the host should bring the Session to the main column; batch sends keep it false. */
    readonly open: boolean;
}
/**
 * Read one prompt bridge message.
 * @param data - the message payload as received.
 * @returns the request, or null when the message is not one this panel serves.
 */
export declare function promptRequest(data: unknown): PmPromptRequest | null;
/**
 * Read one workbench bridge message.
 * @param data - the message payload as received.
 * @returns the request, or null when the message is not one this panel serves.
 */
export declare function bridgeRequest(data: unknown): PmBridgeRequest | null;
/**
 * Document-relative URL of the hosted workbench.
 * @param base - document base URI to resolve against.
 * @param sessionId - foreground Session, passed through so the page can filter
 *   the AI-handoff session list by the Session project.
 * @returns the workbench URL, so a mounted base path keeps working.
 */
export declare function workbenchUrl(base?: string, sessionId?: string): string;
/**
 * Render the embedded PM workbench and bridge its Session requests.
 * @param props.openSession - injected Session navigation.
 * @param props.runPrompt - injected prompt enqueue for "let the conversation summarize itself".
 * @param props.sessionId - foreground Session when hosted in the right Sidebar.
 * @returns the panel body.
 */
export declare function PmPanel({ openSession, runPrompt, sessionId }: PmPanelInjected & {
    readonly sessionId?: string;
}): import("react").JSX.Element;
//# sourceMappingURL=PmPanel.d.ts.map