import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
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
import { useEffect, useRef, useState } from 'react';
/** Message type the workbench posts to its host. */
const OPEN_SESSION = 'pm-open-session';
/** Message type that enqueues a prompt into the named Session. */
const RUN_PROMPT = 'pm-run-prompt';
/** Message type the host answers a prompt request with. */
const PROMPT_RESULT = 'pm-run-prompt-result';
/** Instance label used when the workbench omits the field. */
const UNKNOWN_INSTANCE = 'unknown';
/**
 * Read one prompt bridge message.
 * @param data - the message payload as received.
 * @returns the request, or null when the message is not one this panel serves.
 */
export function promptRequest(data) {
    if (typeof data !== 'object' || data === null)
        return null;
    const message = data;
    if (message.type !== RUN_PROMPT)
        return null;
    if (typeof message.sessionId !== 'string' || message.sessionId === '')
        return null;
    if (typeof message.prompt !== 'string' || message.prompt.trim() === '')
        return null;
    const messageOpen = data.open;
    return { sessionId: message.sessionId, prompt: message.prompt, open: messageOpen !== false };
}
/**
 * Read one workbench bridge message.
 * @param data - the message payload as received.
 * @returns the request, or null when the message is not one this panel serves.
 */
export function bridgeRequest(data) {
    if (typeof data !== 'object' || data === null)
        return null;
    const message = data;
    if (message.type !== OPEN_SESSION)
        return null;
    if (typeof message.sessionId !== 'string' || message.sessionId === '')
        return null;
    return {
        sessionId: message.sessionId,
        instance: typeof message.instance === 'string' && message.instance !== '' ? message.instance : UNKNOWN_INSTANCE,
    };
}
/** Base used when there is no document to resolve against (server render, tests). */
const NO_DOCUMENT_BASE = 'http://localhost/';
/**
 * Document-relative URL of the hosted workbench.
 * @param base - document base URI to resolve against.
 * @returns the workbench URL, so a mounted base path keeps working.
 */
export function workbenchUrl(base) {
    const resolved = base ?? (typeof document === 'undefined' ? NO_DOCUMENT_BASE : document.baseURI);
    return new URL('ui-pm/app/', resolved).href;
}
/** Panel shell: the workbench fills it, with a floor so the frame cannot collapse. */
const shell = {
    display: 'flex', flexDirection: 'column', gap: '8px',
    height: '100%', minHeight: '560px', padding: '8px',
};
const noticeStyle = { fontSize: '12px', color: '#d9c48b', margin: 0 };
const frameStyle = {
    flex: '1 1 auto', width: '100%', minHeight: '520px',
    border: '0', borderRadius: '8px', background: 'transparent',
};
/**
 * Render the embedded PM workbench and bridge its Session requests.
 * @param props.openSession - injected Session navigation.
 * @param props.runPrompt - injected prompt enqueue for "let the conversation summarize itself".
 * @returns the panel body.
 */
export function PmPanel({ openSession, runPrompt }) {
    const frame = useRef(null);
    const [notice, setNotice] = useState(null);
    const [busy, setBusy] = useState(false);
    useEffect(() => {
        const listener = (event) => {
            // Only the frame this panel mounted may steer the panel.
            if (event.source !== frame.current?.contentWindow)
                return;
            const prompt = promptRequest(event.data);
            if (prompt !== null) {
                setBusy(true);
                setNotice(null);
                void runPrompt(prompt.sessionId, prompt.prompt, prompt.open)
                    .then((outcome) => {
                    setNotice(outcome);
                    // The workbench shows its own status; a failed enqueue must not look sent.
                    frame.current?.contentWindow?.postMessage({ type: PROMPT_RESULT, sessionId: prompt.sessionId, error: outcome }, '*');
                })
                    .finally(() => { setBusy(false); });
                return;
            }
            const request = bridgeRequest(event.data);
            if (request === null)
                return;
            setBusy(true);
            setNotice(null);
            void openSession(request.sessionId, request.instance)
                .then((outcome) => { setNotice(outcome); })
                .finally(() => { setBusy(false); });
        };
        window.addEventListener('message', listener);
        return () => { window.removeEventListener('message', listener); };
    }, [openSession]);
    return (_jsxs("div", { style: shell, "data-pm-panel": "", "data-pm-view": "workbench", children: [(notice !== null || busy) && (_jsx("p", { style: noticeStyle, role: "status", "data-pm-notice": "", children: busy ? 'Opening the Session…' : notice })), _jsx("iframe", { ref: frame, "data-pm-frame": "", title: "PM workbench", src: workbenchUrl(), sandbox: "allow-scripts allow-same-origin allow-forms allow-modals", style: frameStyle })] }));
}
//# sourceMappingURL=PmPanel.js.map