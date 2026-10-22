/** Presentation folds for work-card fields. */
/**
 * Render one ISO-8601 instant as local wall time plus a coarse age.
 * @param value - instant from the contract, or null when the card carries none.
 * @param now - reference instant, injectable for tests.
 * @returns display text, or an em dash when the card has no timestamp.
 */
export function formatRecordedAt(value, now = Date.now()) {
    if (value === null)
        return '—';
    const parsed = Date.parse(value);
    if (Number.isNaN(parsed))
        return value;
    const date = new Date(parsed);
    const pad = (n) => String(n).padStart(2, '0');
    const stamp = `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
    return `${stamp} (${formatAge(parsed, now)})`;
}
/**
 * Render the age of one instant relative to now.
 * @param then - instant in milliseconds.
 * @param now - reference instant in milliseconds.
 * @returns a compact human age such as `just now`, `12m ago`, or `3d ago`.
 */
export function formatAge(then, now = Date.now()) {
    const seconds = Math.max(0, Math.round((now - then) / 1000));
    if (seconds < 60)
        return 'just now';
    const minutes = Math.round(seconds / 60);
    if (minutes < 60)
        return `${minutes}m ago`;
    const hours = Math.round(minutes / 60);
    if (hours < 24)
        return `${hours}h ago`;
    return `${Math.round(hours / 24)}d ago`;
}
/**
 * Clamp one summary for a single row.
 * @param summary - card summary, or null when none was generated.
 * @param limit - maximum characters kept.
 * @returns the trimmed summary, an explicit placeholder, or a truncated form.
 */
export function formatSummary(summary, limit = 160) {
    if (summary === null)
        return '(no summary)';
    const text = summary.replace(/\s+/gu, ' ').trim();
    if (text === '')
        return '(no summary)';
    return text.length <= limit ? text : `${text.slice(0, limit - 1)}…`;
}
//# sourceMappingURL=format.js.map