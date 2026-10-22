/** Presentation folds for work-card fields. */
/**
 * Render one ISO-8601 instant as local wall time plus a coarse age.
 * @param value - instant from the contract, or null when the card carries none.
 * @param now - reference instant, injectable for tests.
 * @returns display text, or an em dash when the card has no timestamp.
 */
export declare function formatRecordedAt(value: string | null, now?: number): string;
/**
 * Render the age of one instant relative to now.
 * @param then - instant in milliseconds.
 * @param now - reference instant in milliseconds.
 * @returns a compact human age such as `just now`, `12m ago`, or `3d ago`.
 */
export declare function formatAge(then: number, now?: number): string;
/**
 * Clamp one summary for a single row.
 * @param summary - card summary, or null when none was generated.
 * @param limit - maximum characters kept.
 * @returns the trimmed summary, an explicit placeholder, or a truncated form.
 */
export declare function formatSummary(summary: string | null, limit?: number): string;
//# sourceMappingURL=format.d.ts.map