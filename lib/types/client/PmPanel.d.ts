/**
 * PM workbench panel body.
 *
 * The panel is a host, not a view: the workbench itself is a static page served
 * by this plugin's node half, so the browser half only embeds it and bridges
 * the one interaction the page cannot perform for itself — opening a Session.
 * That bridge reuses the same Host probe and fallbacks every other card path
 * uses, so an archived or foreign Session is still explained rather than
 * silently ignored.
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
}
/** One accepted `pm-open-session` bridge request. */
export interface PmBridgeRequest {
    /** Session the workbench asked to open. */
    readonly sessionId: string;
    /** work-memory instance that recorded the card. */
    readonly instance: string;
}
/**
 * Read one workbench bridge message.
 * @param data - the message payload as received.
 * @returns the request, or null when the message is not one this panel serves.
 */
export declare function bridgeRequest(data: unknown): PmBridgeRequest | null;
/**
 * Document-relative URL of the hosted workbench.
 * @param base - document base URI to resolve against.
 * @returns the workbench URL, so a mounted base path keeps working.
 */
export declare function workbenchUrl(base?: string): string;
/**
 * Render the embedded PM workbench and bridge its Session requests.
 * @param props.openSession - injected Session navigation.
 * @returns the panel body.
 */
export declare function PmPanel({ openSession }: PmPanelInjected): import("react").JSX.Element;
//# sourceMappingURL=PmPanel.d.ts.map