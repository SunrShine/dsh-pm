/** Wire contract of `pm ui-cards` (frozen by task-1) as the panel consumes it. */
/**
 * Work-card observation values the panel renders.
 *
 * The vocabulary is pm's `CacheObservation`; `ARCHIVED` comes from the DSH
 * registry's archived-Session set rather than from the card's own activity.
 */
export type PmObservation = 'STALE_BUSY' | 'BUSY' | 'RECENT' | 'IDLE' | 'EMPTY' | 'CLOSED' | 'ARCHIVED' | 'DONE' | 'REVIEW' | 'BLOCKED' | 'UNKNOWN';
/** How a card's one-line summary was produced. */
export type PmSummarySource = 'human' | 'ai' | 'not_generated';
/** One project aggregate row. */
export interface PmProjectRow {
    readonly key: string;
    readonly title: string;
    readonly paths: readonly string[];
    readonly cards: number;
    readonly missing_summary: number;
    readonly open_todos: number;
    readonly total_todos: number;
    readonly last_recorded: string | null;
    /** Cards in this project whose `needs_attention` is true. */
    readonly attention: number;
    /** Cards in this project whose observation is `STALE_BUSY`. */
    readonly stale_busy: number;
}
/** One work card. */
export interface PmCardRow {
    readonly session_id: string;
    readonly instance: string;
    readonly project: string;
    readonly observation: PmObservation;
    readonly observation_label: string;
    readonly summary: string | null;
    readonly summary_source: PmSummarySource;
    readonly turns: number;
    readonly steps: number;
    readonly recorded_at: string | null;
    readonly cwd: string;
    readonly open_todos: number;
    readonly total_todos: number;
    /** `STALE_BUSY`, or any open todo. */
    readonly needs_attention: boolean;
    readonly card_file: string;
}
/** One quick-note entry from the work-memory inbox. */
export interface PmInboxEntry {
    /** Note text as recorded. */
    readonly text: string;
    /** Source line in the inbox file. */
    readonly line: number;
}
/**
 * The work-memory inbox (quick notes), or absent when the library has none.
 * Added after the first contract revision: a payload without it is valid.
 */
export interface PmInbox {
    /** Absolute path of the inbox file. */
    readonly path: string;
    /** Number of entries. */
    readonly count: number;
    readonly entries: readonly PmInboxEntry[];
}
/** The complete `pm ui-cards` payload. */
export interface PmUiCards {
    readonly generated_at: string;
    readonly library: string;
    readonly instances: readonly string[];
    readonly runtime_status: string;
    readonly projects: readonly PmProjectRow[];
    readonly cards: readonly PmCardRow[];
    /** Quick notes; null or absent when the library reports no inbox. */
    readonly inbox?: PmInbox | null;
}
//# sourceMappingURL=types.d.ts.map