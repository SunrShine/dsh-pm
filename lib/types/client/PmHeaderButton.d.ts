import type { PmKey } from './locales.ts';
/** Props the slot supplies through its injected face and locale binding. */
export interface PmHeaderButtonProps {
    /** Open the PM tab, or collapse it when it is already the active tab. */
    readonly toggle: () => void;
    /** Auto-open the PM tab once for this Session; the host keeps the per-page set. */
    readonly autoOpen: (sessionId: string) => void;
    /** Session whose header this action belongs to (session-scoped slot prop). */
    readonly sessionId?: string;
    /** Namespace-bound translate (pm). */
    readonly t: (key: PmKey) => string;
}
/**
 * Render the PM header affordance and trigger the one-time auto-open when this
 * Session's header mounts (the header only exists for the foreground Session).
 * @param props - injected toggle/auto-open, the Session id, and translator.
 * @returns a compact icon+label button.
 */
export declare function PmHeaderButton({ toggle, autoOpen, sessionId, t }: PmHeaderButtonProps): import("react").JSX.Element;
//# sourceMappingURL=PmHeaderButton.d.ts.map