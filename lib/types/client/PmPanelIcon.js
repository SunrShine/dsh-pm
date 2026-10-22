import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
/** Decorative sidebar icon for the work-card panel row. */
/**
 * Render the panel glyph at the size the Sidebar requests; the Sidebar owns the
 * navigation label, so the glyph itself is decorative.
 * @param props.size - requested square edge in pixels.
 * @returns the card-stack glyph.
 */
export function PmPanelIcon({ size }) {
    return (_jsxs("svg", { width: size, height: size, viewBox: "0 0 16 16", fill: "none", "aria-hidden": "true", focusable: "false", children: [_jsx("rect", { x: "2", y: "2.5", width: "12", height: "3.6", rx: "1.1", stroke: "currentColor", strokeWidth: "1.3" }), _jsx("rect", { x: "2", y: "7.4", width: "12", height: "3.6", rx: "1.1", stroke: "currentColor", strokeWidth: "1.3" }), _jsx("path", { d: "M4.4 13.3h7.2", stroke: "currentColor", strokeWidth: "1.3", strokeLinecap: "round" })] }));
}
//# sourceMappingURL=PmPanelIcon.js.map