import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
/** Session-header PM toggle: one click opens the PM workbench in the right sidebar. */
import { useEffect } from 'react';
import { PmPanelIcon } from "./PmPanelIcon.js";
const buttonStyle = {
    display: 'inline-flex',
    alignItems: 'center',
    gap: '6px',
    padding: '4px 8px',
    border: '0',
    borderRadius: '6px',
    background: 'transparent',
    color: 'inherit',
    cursor: 'pointer',
    font: 'inherit',
};
/**
 * Render the PM header affordance and trigger the one-time auto-open when this
 * Session's header mounts (the header only exists for the foreground Session).
 * @param props - injected toggle/auto-open, the Session id, and translator.
 * @returns a compact icon+label button.
 */
export function PmHeaderButton({ toggle, autoOpen, sessionId, t }) {
    useEffect(() => {
        if (sessionId !== undefined && sessionId !== '')
            autoOpen(sessionId);
    }, [autoOpen, sessionId]);
    const label = t('right.title');
    return (_jsxs("button", { type: "button", "data-pm-header-toggle": "", style: buttonStyle, onClick: toggle, title: label, "aria-label": label, children: [_jsx(PmPanelIcon, { size: 16 }), _jsx("span", { children: label })] }));
}
//# sourceMappingURL=PmHeaderButton.js.map