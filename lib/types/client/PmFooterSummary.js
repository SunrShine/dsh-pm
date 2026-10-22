import { jsx as _jsx } from "react/jsx-runtime";
/**
 * One-line work-card summary in the Sidebar foot.
 *
 * This is the always-mounted surface: it tells the user whether the Host
 * endpoint answered and how many cards need attention, and it is what made the
 * first end-to-end proof of this plugin visible before the panel existed.
 */
import { useEffect } from 'react';
import { refreshPmCards, usePmCards } from "./pm-store.js";
/** Count the cards the panel lists. */
function attentionCount(data) {
    if (data === null)
        return 0;
    return data.cards.filter(card => card.needs_attention).length;
}
/**
 * Render the live work-card status line.
 * @returns a single line: loading, unavailable, or the needs-attention count.
 */
export function PmFooterSummary() {
    const state = usePmCards();
    useEffect(() => { void refreshPmCards(); }, []);
    const text = state.status === 'ready'
        ? `PM needs attention: ${String(attentionCount(state.data))}`
        : state.status === 'error' ? 'PM: unavailable' : 'PM: …';
    return (_jsx("div", { "data-pm-footer-summary": "", title: state.error ?? state.data?.library ?? 'Work-memory work cards', style: {
            padding: '4px 8px',
            fontSize: '12px',
            lineHeight: '1.4',
            color: state.status === 'error' ? '#d98b8b' : '#7c8bff',
            whiteSpace: 'nowrap',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
        }, children: text }));
}
//# sourceMappingURL=PmFooterSummary.js.map