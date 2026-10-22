"""记忆内容索引（P0）：派生 SQLite FTS5 索引 + pm recall。

依据：内部记录/11 §4-A1 / §5-P0（推荐路径 A）、内部记录/13 §3.1（表结构）/ §7-A（落地顺序 A）。

硬约束（每条都配判据）：
1. **索引是派生物**：落 <库>/.local/index.sqlite，可删可重建，**永不回写 Org**；
2. **默认召回口径** = layer IN ('L1','L2') AND status='VERIFIED'；**L3 永不进召回**；
   候选 / 已废弃必须 --include-candidate / --include-deprecated 显式开；
3. **零新依赖**（stdlib sqlite3；不引入 jieba）；**FTS5 不可用 → 回退 LIKE 并在输出里明说降级**；
4. **命中必带 path:line + revision**；
5. **收录层级 L1 + L2**（M3 起）：L1 = memory/{facts,decisions,gotchas}.org + 候选中 layer=L1 的条目；
   L2 = memory/l2/<scope>/<scene>.org（一块一文件；只存标题+摘要）；**L3 永不进索引**；
6. **v2（unigram）起连续 CJK 按字拆开进 `search_*` 列**（查询侧同拆、短语匹配）⇒「词中匹配」也走 FTS；
   盘上 schema 旧（缺 `search_*` 或版本不符）⇒ **自动整份重建并说明原因**，绝不用旧口径静默作答。

去重口径：pm memory verify 会在 memory/<type>.org 写 VERIFIED 副本，候选文件里的同 :ID: 记录仍在
⇒ 同一 id 可能同时出现在两处；本模块**优先 canonical 文件（memory/*.org）**，候选副本丢弃，
避免同一事实命中两次。

测试/诊断开关：环境变量 PM_INDEX_FORCE_LIKE=1 强制走 LIKE 降级路径（生产路径只由 FTS5 编译情况决定）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
from pathlib import Path

from pm import memory
from pm.cli import _add_common_options
from pm.config import load as load_config
from pm.layout import Layout

INDEX_RELATIVE = ".local/index.sqlite"
#: 默认召回口径的 layer 白名单：L3 不在里面（内部记录/13 §3.1）。
RECALL_LAYERS = (memory.LAYER_L1, memory.LAYER_L2)
#: 要索引的层：L1（memory/*.org + 候选）与 L2（memory/l2/**/*.org，只存标题+摘要）。L3 不索引。
INDEXED_LAYERS = (memory.LAYER_L1, memory.LAYER_L2)
FORCE_LIKE_ENV = "PM_INDEX_FORCE_LIKE"
DEFAULT_LIMIT = 10
#: 索引 schema 版本。**不匹配就整份重建**（索引是派生物）：
#: v2 起 entries 增加 search_title/search_body（把连续 CJK 按字拆开后的检索文本，让「词中匹配」也走 FTS；display 的 title/body 不动）；
#: v3 起 **L2/L3 候选行也记 source_rev 锚点**（原先只给 scene 文件记账 ⇒ 生成出来的 L2/L3 候选
#: 永远被报「无锚点」，stale 漏判；改的是列语义，必须整份重建才生效）。
SCHEMA_VERSION = "3"

SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
  rowid      INTEGER PRIMARY KEY,
  id         TEXT,
  layer      TEXT NOT NULL,
  scope      TEXT NOT NULL,
  type       TEXT,
  status     TEXT NOT NULL,
  revision   INTEGER NOT NULL,
  path       TEXT NOT NULL,
  line       INTEGER NOT NULL,
  title      TEXT,
  body       TEXT,
  search_title TEXT,
  search_body  TEXT,
  sources    TEXT,
  source_rev TEXT,
  ts         TEXT,
  file       TEXT NOT NULL,
  file_sha   TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS entries_key ON entries(path, line, IFNULL(id, ''));
CREATE INDEX IF NOT EXISTS entries_layer ON entries(layer, status);
CREATE TABLE IF NOT EXISTS files (
  file    TEXT PRIMARY KEY,
  sha     TEXT NOT NULL,
  mtime   REAL NOT NULL,
  size    INTEGER NOT NULL,
  entries INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT NOT NULL);
"""

FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS entries_fts USING fts5(
  search_title, search_body, content='entries', content_rowid='rowid', tokenize='unicode61'
);
"""

#: 需要按字拆开的 CJK 区段：统一表意（含扩展 A）+ 兼容表意。
_CJK_RANGES = ((0x3400, 0x4DBF), (0x4E00, 0x9FFF), (0xF900, 0xFAFF))


def _is_cjk(ch: str) -> bool:
    code = ord(ch)
    return any(low <= code <= high for low, high in _CJK_RANGES)


#: 查询侧停用词（CJK 功能字/疑问词）：**只用于切分查询**，不进索引、不改 display 文本。
#: 目的：真实输入是整句（"看板卡片被裁的真机制是什么？"），疑问词若参与匹配会把整句变成必中短语。
QUERY_STOPWORD_CHARS = frozenset(
    "的地得是吗呢吧啊呀哪请了咋啥嘛呃为什么怎如何到底究竟帮我你他她它们一个下就也都很大太更要会能以应该"
)

def normalize_for_fts(text: str) -> str:
    """检索用规范化：**把连续 CJK 按字拆成独立 token**（其余字符原样）。

    为什么：unicode61 把连续中文当成**一个 token**（"记忆检索用" 是一个 token），于是
    "检索" 这种**词中**查询永远匹配不到 ⇒ 现在拆成 "记 忆 检 索 用"，查询侧也拆字后用短语
    匹配（"检 索"）⇒ 词中匹配走 FTS，不再退 LIKE 兜底。
    注意：display 用的 title/body 列**不动**（这里只给索引用的 search_* 列）。
    """
    out: list[str] = []
    for ch in str(text or ""):
        if _is_cjk(ch):
            out.append(" ")
            out.append(ch)
            out.append(" ")
        else:
            out.append(ch)
    return re.sub(r"\s+", " ", "".join(out)).strip()


#: 查询里当分隔符的标点/空白（保留 ASCII 字母数字与下划线，按整词前缀匹配）。
QUERY_SEPARATORS = frozenset(" \t\r\n？?！!。.，,、：:；;（）()「」『』【】[]{}'\"“”‘’…—-_/\\|~`*#@$%^&+=<>")


def query_runs(query: str) -> list[str]:
    """把查询切成**内容 run**（去掉停用词/标点后剩下的连续片段）。

    例：`看板卡片被裁的真机制是什么？` → `['看板卡片被裁', '真机制']`；`hooktok-abc123 是什么` → `['hooktok-abc123']`。
    为什么：索引侧已按字拆（unigram）—— 查询侧若把整句当一个 term，就会要求整句**逐字相邻**命中 ⇒
    疑问词/加粗标记一挡就整条丢掉（实测 `看板卡片被裁的真机制是什么？` → 0 字节）。
    """
    runs: list[str] = []
    current: list[str] = []
    seen: set[str] = set()

    def _flush() -> None:
        if not current:
            return
        token = "".join(current).strip()
        current.clear()
        if token and token.lower() not in seen:
            seen.add(token.lower())
            runs.append(token)

    for ch in str(query or ""):
        if _is_cjk(ch):
            if ch in QUERY_STOPWORD_CHARS:
                _flush()
            else:
                current.append(ch)
        elif ch in QUERY_SEPARATORS:
            # 标识符内的 - _ . : 不拆（hooktok-abc123 / memory-01M… 必须整体当一个 run）；
            # 只有「两侧不都是字母数字」时才当分隔符（"。" / "，" / "行尾的 ." 等）。
            prev = current[-1] if current else ""
            if ch in "-_.:" and prev and prev.isalnum():
                current.append(ch)
            else:
                _flush()
        else:
            current.append(ch)
    _flush()
    return runs

_FTS5_CACHE: bool | None = None


class IndexError_(Exception):
    """带错误码的索引层错误（CLI 统一翻成 JSON/文本 + 退出码）。"""

    def __init__(self, code: str, message: str, exit_code: int = 2):
        super().__init__(message)
        self.code = code
        self.message = message
        self.exit_code = exit_code


def fts5_available() -> bool:
    """FTS5 是否可用（带缓存）。PM_INDEX_FORCE_LIKE=1 时强制不可用 —— 只为测试/诊断降级路径。"""
    global _FTS5_CACHE
    if os.environ.get(FORCE_LIKE_ENV) == "1":
        return False
    if _FTS5_CACHE is None:
        try:
            con = sqlite3.connect(":memory:")
            try:
                con.execute("CREATE VIRTUAL TABLE _probe USING fts5(x)")
                _FTS5_CACHE = True
            finally:
                con.close()
        except sqlite3.Error:
            _FTS5_CACHE = False
    return bool(_FTS5_CACHE)


def index_path(library_root) -> Path:
    return Path(library_root) / INDEX_RELATIVE


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source_files(library_root) -> list[tuple[Path, str]]:
    """要索引的 L1 来源：canonical（memory/*.org）优先，其后候选文件。顺序固定 ⇒ 可复现。"""
    root = Path(library_root)
    out: list[tuple[Path, str]] = []
    for entry_type in memory.TYPES:
        path = memory.type_path(root, entry_type)  # memory/{facts,decisions,gotchas}.org（复数）
        if path.is_file():
            out.append((path, "memory"))
    candidates = root / memory.CANDIDATES_RELATIVE
    if candidates.is_file():
        out.append((candidates, "candidate"))
    # L2：一块一文件（路径即 id）—— 索引只存标题+摘要，正文按需读文件。
    l2_root = memory.l2_dir(root)
    if l2_root.is_dir():
        for path in sorted(l2_root.glob("*/*.org")):
            out.append((path, "scene"))
    return out


def _relpath(library_root, path: Path) -> str:
    try:
        return str(path.relative_to(Path(library_root)))
    except ValueError:
        return str(path)


def _split_title_body(text: str) -> tuple[str, str]:
    lines = (text or "").split("\n")
    title = lines[0].strip() if lines else ""
    body = "\n".join(lines[1:]).strip()
    return title, body


def _rows_for_file(library_root, path: Path, kind: str) -> list[dict]:
    """解析一个来源文件；候选文件只收 layer=L1（P0 口径），未知 layer 一律不收。"""
    text = ""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    rows: list[dict] = []
    for entry in memory.parse_entries_text(text):
        layer = entry.layer
        if kind == "candidate" and layer not in INDEXED_LAYERS:
            continue
        if kind == "memory":
            layer = memory.LAYER_L1
        if kind == "scene":
            layer = memory.LAYER_L2  # 目录即层级（路径即 id）；文件里的 :PM_LAYER: 只作说明
        if layer not in INDEXED_LAYERS:
            continue
        title, body = _split_title_body(entry.text)
        rows.append({
            "id": entry.id,
            "layer": layer,
            "scope": entry.scope,
            "type": entry.type,
            "status": entry.status,
            "revision": int(entry.revision),
            "path": _relpath(library_root, path),
            "line": int(entry.line),
            "title": title,
            "body": body,
            # 检索列：连续 CJK 按字拆开；display 的 title/body 不动（见 normalize_for_fts）。
            "search_title": normalize_for_fts(title),
            "search_body": normalize_for_fts(body),
            "sources": ",".join(entry.sources),
            # L2/L3 的 :PM_SOURCES: 是**版本锚点**（id@rev 或 path@hash）⇒ 进 source_rev，stale 判定只读它。
            # ★ 判据是「层级」而不是「文件种类」：生成出来的 **L2/L3 候选**同样带锚点，
            #   只给 scene 文件填会让候选永远被报成「无锚点」（实测踩过）。
            "source_rev": (" ".join(entry.sources) if layer != memory.LAYER_L1 else None),
            "ts": entry.created_at,
            "file": _relpath(library_root, path),
            "file_sha": "",
        })
    return rows


def collect_rows(library_root) -> tuple[list[dict], list[Path]]:
    """收集全部 L1 行（含跨文件去重），返回 (rows, 来源文件列表)。"""
    files = _source_files(library_root)
    canonical: dict[str, int] = {}
    rows: list[dict] = []
    for path, kind in files:
        file_rows = _rows_for_file(library_root, path, kind)
        if kind == "memory":
            for row in file_rows:
                if row["id"]:
                    canonical.setdefault(row["id"], len(rows) + file_rows.index(row))
        rows.extend(file_rows)
    # canonical 优先：同一 id 若在 memory/*.org 出现过，丢掉候选副本
    canonical_ids = {row["id"] for row in rows if row["file"].startswith(memory.MEMORY_DIRNAME + "/") and row["id"]}
    deduped = [row for row in rows if not (row["id"] and row["id"] in canonical_ids and not row["file"].startswith(memory.MEMORY_DIRNAME + "/"))]
    deduped.sort(key=lambda r: (r["file"], r["line"], r["id"] or ""))
    return deduped, [p for p, _ in files]


def _connect(db: Path) -> sqlite3.Connection:
    db.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(db))
    con.row_factory = sqlite3.Row
    return con


def _connect_ro(db: Path) -> sqlite3.Connection:
    """**严格只读**连接（`mode=ro` + `immutable=1` + `query_only`）。

    为什么必须这样开：只读环境（会话沙箱把库/仓库置为不可写）下，普通连接会尝试建
    `-journal`/`-wal`/`-shm` 或加写锁 ⇒ `attempt to write a readonly database`
    ⇒ hook 的 fail-safe 把它吞掉 ⇒ **静默零注入**（Lead 2026-10-18 本地复现 ✓）。
    `immutable=1` 明确告诉 SQLite 这个文件不会被改 ⇒ 不建 sidecar、不加锁。
    """
    con = sqlite3.connect("file:" + str(db) + "?mode=ro&immutable=1", uri=True)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA query_only = on")
    # 严格沙箱里 TMPDIR/临时区可能不可写：强制内存临时存储，免得查询本身因为要建临时文件而失败 ✗。
    try:
        con.execute("PRAGMA temp_store = MEMORY")
    except sqlite3.Error:
        pass
    return con


def probe_read_only(con: sqlite3.Connection) -> None:
    """只读预检：把"读 entries + 跑一次 FTS 查询"先试一遍。

    为什么要有它：只读打开成功 ≠ 查询能跑（FTS5 可能需要在临时区建结构；严格沙箱下会失败）。
    这里先探一次 ⇒ 失败就整体并入 org-scan 回退，而不是让异常冒到 hook 的 fail-safe 里变成静默零注入 ✗。
    """
    con.execute("SELECT COUNT(*) FROM entries").fetchone()
    has_fts = con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='entries_fts'"
    ).fetchone() is not None
    if has_fts:
        con.execute("SELECT rowid FROM entries_fts WHERE entries_fts MATCH ? LIMIT 1", ("probe",)).fetchall()


def _dir_writable(path: Path) -> bool:
    """该目录能不能写（不存在时看最近的存在祖先）。只读环境下返回 False。"""
    target = Path(path)
    while not target.exists() and target != target.parent:
        target = target.parent
    return os.access(str(target), os.W_OK)


def org_scan_hits(library_root, query: str, *, scope: str | None = None, type: str | None = None,
                  statuses: list[str] | None = None, limit: int = DEFAULT_LIMIT,
                  any_mode: bool = False) -> tuple[list[dict], str]:
    """**索引层直读回退（org-scan）**：索引打不开/库只读时，直接有界地读库里的 `*.org`。

    口径与 FTS 路**完全一致**：layer ∈ RECALL_LAYERS、status 白名单、scope/type 过滤、top-k 上限；
    只有**排序口径不同**（这里按"命中 run 数 desc, path, line"），因此调用方必须把 how/mode 标成 org-scan
    —— "可解释"比"看起来一样"重要（Lead 2026-10-18 裁定）。
    run 匹配用与查询侧同一套 `query_runs`（子串判定），AND 零命中时按既有阶梯放宽为任一命中。
    """
    rows, _files = collect_rows(library_root)
    runs = query_runs(query)
    wanted_statuses = list(statuses or [memory.STATUS_VERIFIED])

    def _accept(row: dict, need_all: bool) -> tuple[bool, int]:
        if row.get("layer") not in RECALL_LAYERS:
            return False, 0
        if row.get("status") not in wanted_statuses:
            return False, 0
        if scope and row.get("scope") != scope:
            return False, 0
        if type and row.get("type") != type:
            return False, 0
        hay = ((row.get("title") or "") + "\n" + (row.get("body") or "")).lower()
        matched = sum(1 for run in runs if run.lower() in hay)
        if need_all and len(runs) > 1 and matched < len(runs):
            return False, matched
        if matched == 0:
            return False, 0
        return True, matched

    def _collect(need_all: bool) -> list[tuple[int, dict]]:
        out = []
        for row in rows:
            ok, matched = _accept(row, need_all)
            if ok:
                out.append((matched, row))
        return out

    picked = _collect(need_all=not any_mode)
    used = "any" if any_mode else "and"
    if not picked and not any_mode and len(runs) > 1:
        picked = _collect(need_all=False)
        if picked:
            used = "any"
    picked.sort(key=lambda item: (-item[0], str(item[1].get("path")), int(item[1].get("line") or 0)))
    hits = []
    for _matched, row in picked[: max(0, int(limit))]:
        hits.append({
            "id": row.get("id"), "layer": row.get("layer"), "scope": row.get("scope"),
            "type": row.get("type"), "status": row.get("status"),
            "revision": int(row.get("revision") or 0), "path": row.get("path"),
            "line": int(row.get("line") or 0), "title": row.get("title"),
            "snippet": _snippet(row.get("title") or "", row.get("body") or "", query),
            "source": str(row.get("path")) + ":" + str(row.get("line")),
        })
    return hits, used


def _ensure_schema(con: sqlite3.Connection, use_fts: bool) -> None:
    con.executescript(SCHEMA)
    if use_fts:
        con.executescript(FTS_SCHEMA)


def _delete_file_rows(con: sqlite3.Connection, rel: str, use_fts: bool) -> None:
    if use_fts:
        con.execute(
            "INSERT INTO entries_fts(entries_fts, rowid, search_title, search_body) "
            "SELECT 'delete', rowid, search_title, search_body FROM entries WHERE file = ?",
            (rel,),
        )
    con.execute("DELETE FROM entries WHERE file = ?", (rel,))


def _insert_rows(con: sqlite3.Connection, rows: list[dict], use_fts: bool) -> None:
    for row in rows:
        con.execute(
            "INSERT INTO entries(id, layer, scope, type, status, revision, path, line, title, body, search_title, search_body, sources, source_rev, ts, file, file_sha) "
            "VALUES(:id, :layer, :scope, :type, :status, :revision, :path, :line, :title, :body, :search_title, :search_body, :sources, :source_rev, :ts, :file, :file_sha)",
            row,
        )
    if use_fts and rows:
        con.execute(
            "INSERT INTO entries_fts(rowid, search_title, search_body) SELECT rowid, search_title, search_body FROM entries WHERE file = ?",
            (rows[0]["file"],),
        )


def build(library_root, *, rebuild: bool = False, dry_run: bool = False) -> dict:
    """建/刷新索引。返回统计；dry_run 时一字节不写。"""
    root = Path(library_root)
    if not root.is_dir():
        raise IndexError_("LIBRARY_MISSING", "work-memory 库目录不存在: " + str(root), 2)
    use_fts = fts5_available()
    rows, files = collect_rows(root)
    by_file: dict[str, list[dict]] = {}
    for row in rows:
        by_file.setdefault(row["file"], []).append(row)

    stats = {
        "db": str(index_path(root)),
        "mode": "fts5" if use_fts else "like",
        "degraded": (not use_fts),
        "schemaVersion": SCHEMA_VERSION,
        "sqliteVersion": sqlite3.sqlite_version,
        "layers": list(INDEXED_LAYERS),
        "files": len(files),
        "filesChanged": [],
        "filesSkipped": [],
        "entries": len(rows),
        "rebuilt": bool(rebuild),
    }
    if dry_run:
        stats["dryRun"] = True
        return stats

    db = index_path(root)
    db_existed = db.is_file()
    con = _connect(db)
    try:
        # ★ schema 不匹配 ⇒ 整份重建，并在输出里写明**为什么**重建（绝不用旧口径静默作答）。
        if not rebuild and db_existed:
            stored_version, cols = None, set()
            try:
                row = con.execute("SELECT v FROM meta WHERE k = 'schema_version'").fetchone()
                stored_version = row[0] if row else None
                cols = {info[1] for info in con.execute("PRAGMA table_info(entries)")}
            except sqlite3.Error:
                pass
            if "search_title" not in cols or stored_version != SCHEMA_VERSION:
                rebuild = True
                stats["schemaRebuilt"] = (
                    "索引 schema 旧（磁盘 " + str(stored_version or "未知") + " → 现在 " + SCHEMA_VERSION
                    + "）：已整份重建（索引是派生物，可放心重建）"
                )
        if rebuild:
            con.executescript("DROP TABLE IF EXISTS entries_fts; DROP TABLE IF EXISTS entries; DROP TABLE IF EXISTS files; DROP TABLE IF EXISTS meta;")
        _ensure_schema(con, use_fts)
        known = {r["file"]: r for r in con.execute("SELECT * FROM files")}
        current = {rel for rel in by_file}
        for rel in sorted(set(known) - current):
            _delete_file_rows(con, rel, use_fts)
            con.execute("DELETE FROM files WHERE file = ?", (rel,))
        for path, _kind in [(p, k) for p, k in _source_files(root)]:
            rel = _relpath(root, path)
            sha = _sha256_file(path)
            stat = path.stat()
            previous = known.get(rel)
            if not rebuild and previous and previous["sha"] == sha and int(previous["size"]) == stat.st_size:
                stats["filesSkipped"].append(rel)
                continue
            file_rows = by_file.get(rel, [])
            for row in file_rows:
                row["file_sha"] = sha
            _delete_file_rows(con, rel, use_fts)
            _insert_rows(con, file_rows, use_fts)
            con.execute(
                "INSERT INTO files(file, sha, mtime, size, entries) VALUES(?,?,?,?,?) "
                "ON CONFLICT(file) DO UPDATE SET sha=excluded.sha, mtime=excluded.mtime, size=excluded.size, entries=excluded.entries",
                (rel, sha, stat.st_mtime, stat.st_size, len(file_rows)),
            )
            stats["filesChanged"].append(rel)
        con.execute("INSERT INTO meta(k, v) VALUES('schema_version', ?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (SCHEMA_VERSION,))
        con.execute("INSERT INTO meta(k, v) VALUES('mode', ?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (stats["mode"],))
        con.commit()
    finally:
        con.close()
    con2 = _connect(db)
    try:
        stats["entriesInDb"] = con2.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
    finally:
        con2.close()
    return stats


def _match_expr(query: str, *, any_mode: bool = False) -> str:
    """把用户查询翻成 FTS5 表达式：每个词做**前缀**匹配，词间 AND。

    为什么必须前缀：unicode61 把连续 CJK 当成**一个 token**（实测："检索" 匹配不到
    token "检索要带来源行号"，而 "检索"* 可以）。纯整词匹配会让中文查询几乎全空。
    """
    quoted = []
    for run in query_runs(query):
        # 内容 run：内部按**字**短语匹配（与索引侧 unigram 对称），run 之间按 AND/OR。
        #   单 token（拉丁词/单个汉字）→ 前缀匹配；多 token（中文）→ 短语匹配。
        toks = normalize_for_fts(run).split()
        if not toks:
            continue
        body = " ".join(tok.replace('"', '""') for tok in toks)
        quoted.append('"' + body + '"' + ("" if len(toks) > 1 else "*"))
    return (" OR " if any_mode else " AND ").join(quoted)


def _snippet(title: str, body: str, query: str, width: int = 100) -> str:
    hay = (title or "")
    text = hay + ("\n" + body if body else "")
    needle = ""
    for term in query_runs(query):
        if term.lower() in text.lower():
            needle = term
            break
    if not needle:
        return (text or "").replace("\n", " ")[:width]
    low = text.lower()
    pos = low.find(needle.lower())
    start = max(0, pos - width // 3)
    end = min(len(text), pos + len(needle) + width // 2)
    return ("…" if start else "") + text[start:end].replace("\n", " ") + ("…" if end < len(text) else "")


def recall(library_root, query: str, *, scope: str | None = None, type: str | None = None,
           limit: int = DEFAULT_LIMIT, include_candidate: bool = False,
           include_deprecated: bool = False, auto_build: bool = True,
           any_mode: bool = False) -> dict:
    """按默认口径检索。返回 {query, mode, degraded, note, count, hits[]}（hits 带 path:line+revision）。"""
    root = Path(library_root)
    q = str(query or "").strip()
    if not q:
        raise IndexError_("QUERY_REQUIRED", "recall 需要非空 --query", 2)
    db = index_path(root)
    built = False
    schema_note = None
    read_only_fallback = None
    if auto_build:
        # ★ 每次都按内容 sha 增量刷新（build 幂等、未变文件只 stat+sha 一次）：
        #   否则 verify/render 之后索引是旧的，recall 会给出**陈旧读数**（实测过的时序 bug）。
        #   ⚠️ 只读环境（会话沙箱）下 build 无处可写 ⇒ 走**镜像回退**，绝不静默零注入。
        if _dir_writable(root / ".local"):
            had_db = db.is_file()
            try:
                build_stats = build(root)
                built = not had_db and db.is_file()
                schema_note = build_stats.get("schemaRebuilt")
            except sqlite3.Error as exc:
                read_only_fallback = "build 失败（" + exc.__class__.__name__ + "）"
        else:
            read_only_fallback = "库/.local 不可写（只读环境）"
    statuses = [memory.STATUS_VERIFIED]
    if include_candidate:
        statuses.append(memory.STATUS_CANDIDATE)
    if include_deprecated:
        statuses.append(memory.STATUS_DEPRECATED)

    def _org_scan_result(reason: str) -> dict:
        """② 索引层直读回退：仍按同一口径过滤 + 同一 top-k，只在输出里如实标 org-scan。"""
        scanned, used_kind = org_scan_hits(
            root, q, scope=scope, type=type, statuses=statuses, limit=limit, any_mode=any_mode
        )
        scan_note = ("只读回退：" + reason + " → 已直读库里 *.org（org-scan：口径一致，排序按命中 run 数/路径/行）"
                     if scanned else
                     "只读回退：" + reason + " → 已直读库里 *.org（org-scan），本次 0 命中")
        return {
            "library": str(root), "query": q, "mode": "org-scan", "readOnlyFallback": reason,
            "match": used_kind, "degraded": True, "note": scan_note,
            "indexBuiltNow": False, "indexEntries": None,
            "layers": list(RECALL_LAYERS), "statuses": statuses, "limit": int(limit),
            "count": len(scanned), "hits": scanned,
        }

    # 没索引且没走回退 ⇒ 明确报 INDEX_MISSING（别让 _connect 建出一个空库再炸在 SELECT 上）。
    if read_only_fallback is None and not db.is_file():
        raise IndexError_("INDEX_MISSING", "还没建索引：先跑 pm index（或 pm index --rebuild）", 2)
    # ① **严格只读连接**（mode=ro&immutable=1 + query_only）：只读环境下也不建 journal/wal、不加写锁。
    con = None
    if read_only_fallback:
        if db.is_file():
            try:
                con = _connect_ro(db)
            except sqlite3.Error as exc:
                read_only_fallback += "；只读打开失败（" + exc.__class__.__name__ + "）"
        else:
            read_only_fallback += "；索引不存在"
        if con is None:
            return _org_scan_result(read_only_fallback)
        # 只读预检：任何"能打开但查不动"的情形也并入 org-scan（Lead 2026-10-18 的怀疑点 ✓）。
        try:
            probe_read_only(con)
        except (sqlite3.Error, OSError) as exc:
            con.close()
            return _org_scan_result(read_only_fallback + "；只读查询失败（" + exc.__class__.__name__ + "）")
    else:
        con = _connect(db)
    try:
        total = con.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
        if total == 0:
            # 绝不静默返回 count=0：空索引要么是库选错、要么盘上真没有可索引的 L1 条目。
            raise IndexError_(
                "INDEX_EMPTY",
                "库 " + str(root) + " 的索引是空的（memory/*.org 与 memory-candidates.org 里没有可索引的 L1 条目）。"
                "若这不是你要查的库，请用 --config 显式指向目标库（不要依赖默认配置）。",
                2,
            )
        use_fts = fts5_available()
        has_fts = con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='entries_fts'").fetchone() is not None
        where = ["layer IN (" + ",".join("?" for _ in RECALL_LAYERS) + ")", "status IN (" + ",".join("?" for _ in statuses) + ")"]
        params: list = list(RECALL_LAYERS) + statuses
        if scope:
            where.append("scope = ?")
            params.append(scope)
        if type:
            where.append("type = ?")
            params.append(type)
        mode = "fts5" if (use_fts and has_fts) else "like"
        note = None
        # 查询侧切分：去停用词/标点后取**内容 run**（与索引侧 unigram 对称）。
        # 纯停用词查询直接报错，绝不静默 0 命中（"是什么？" 这种）。
        runs = query_runs(q)
        if not runs:
            raise IndexError_(
                "QUERY_NO_TERMS",
                "查询里没有可检索的内容词（只有停用词/标点）：" + q + "—— 请给一个内容词，或一句包含内容词的话",
                2,
            )
        used = "any" if any_mode else "and"

        def _fts_rows(any_terms: bool) -> list:
            sql = ("SELECT e.*, bm25(entries_fts) AS score FROM entries_fts f JOIN entries e ON e.rowid = f.rowid "
                   "WHERE entries_fts MATCH ? AND " + " AND ".join(where) +
                   " ORDER BY score, e.path, e.line, IFNULL(e.id,'') LIMIT ?")
            return con.execute(sql, [_match_expr(q, any_mode=any_terms)] + params + [int(limit)]).fetchall()

        def _like_rows(any_terms: bool) -> list:
            like_where = list(where)
            like_params = list(params)
            if runs:
                glue = " OR " if any_terms else " AND "
                clause = glue.join("(IFNULL(e.title,'') LIKE ? OR IFNULL(e.body,'') LIKE ?)" for _ in runs)
                like_where.append("(" + clause + ")")
                for token in runs:
                    like_params.extend(["%" + token + "%", "%" + token + "%"])
            sql = ("SELECT e.*, 0.0 AS score FROM entries e WHERE " + " AND ".join(like_where) +
                   " ORDER BY e.path, e.line, IFNULL(e.id,'') LIMIT ?")
            return con.execute(sql, like_params + [int(limit)]).fetchall()

        def _attempt(engine_fts: bool, any_terms: bool) -> list:
            return _fts_rows(any_terms) if engine_fts else _like_rows(any_terms)

        # 匹配阶梯：① 默认（词间 AND）→ ② 多词时自动放宽为「任一命中」(match=any)
        #             → ③ FTS5 无命中就退 LIKE → ④ LIKE 也整句 AND 不中就再放宽。
        # 为什么要有 ②：真实消费者（前端搜索框 / hook 的整句 prompt）都是整句输入，
        # 词间 AND 会让"多一个对不上的词"整条丢掉（实测 "hooktok-abc123 是什么" → 0）。
        engine_fts = mode == "fts5"
        rows = _attempt(engine_fts, any_mode)
        if not rows and not any_mode and len(runs) > 1:
            rows = _attempt(engine_fts, True)
            if rows:
                used = "any"
                note = "词间 AND 零命中 → 已自动放宽为「任一词命中」（match=any）"
        if not rows and engine_fts:
            mode = "like"
            used = "any" if any_mode else "and"
            rows = _attempt(False, any_mode)
            if rows:
                note = "FTS5 无命中（unicode61 把连续中文当作一个整词）→ 已用 LIKE 子串匹配" + ("（任一命中）" if any_mode else "（词间 AND）")
            elif not any_mode and len(runs) > 1:
                rows = _attempt(False, True)
                if rows:
                    used = "any"
                    note = "FTS5 与 LIKE 都不能整句命中 → 已放宽为「任一词命中」（match=any）"
                if mode == "fts5":
                    mode = "like"
                    note = "FTS5 无命中（unicode61 把连续中文当作一个整词）→ 已用 LIKE 子串兜底，按 path:line 排序"
    finally:
        con.close()
    hits = []
    for row in rows:
        hits.append({
            "id": row["id"],
            "layer": row["layer"],
            "scope": row["scope"],
            "type": row["type"],
            "status": row["status"],
            "revision": int(row["revision"]),
            "path": row["path"],
            "line": int(row["line"]),
            "title": row["title"],
            "snippet": _snippet(row["title"], row["body"], q),
            "source": row["path"] + ":" + str(row["line"]),
        })
    # 归因要准：mode=like 有**两种**来路 —— ①FTS5 本来就不可用（真降级）②FTS5 可用但这词没命中（退 LIKE 兜底）。
    # 实测踩过：第二种情况报「FTS5 不可用」是假诊断（会让人去查环境）。
    if schema_note:
        note = (schema_note + "；" + note) if note else schema_note
    if note is None and mode == "like":
        if not use_fts:
            note = "FTS5 不可用 → 已降级为 SQLite LIKE 子串匹配（不是全文检索，中文分词/排序能力受限）"
        elif not has_fts:
            note = "索引是按 LIKE 建的（建索引时 FTS5 不可用）；本次查询走 SQLite LIKE（降级）"
        else:
            note = "FTS5 无命中 → 已尝试 LIKE 子串匹配；这条查询仍 0 命中"
    if read_only_fallback:
        # 绝不静默：把"为什么走了只读回退"写进 note 与结构化字段（hook 的 --json / trace 也会带出去）。
        fallback_note = "只读回退：" + read_only_fallback + " → 已用严格只读连接查索引（不建 journal/wal）"
        note = (fallback_note + "；" + note) if note else fallback_note
    return {
        "library": str(root),
        "query": q,
        "mode": mode,
        #: 只读回退原因（None = 正常可写路径）；只读环境下 hook 靠它出结果而不是静默零注入。
        "readOnlyFallback": read_only_fallback,
        #: 词间语义：and（默认）/ any（任一词命中）/ like（用的是 LIKE 引擎，AND/OR 见 note）
        "match": ("like" if mode == "like" else used),
        "degraded": mode == "like",
        "note": note,
        "indexBuiltNow": built,
        "indexEntries": int(total),
        "layers": list(RECALL_LAYERS),
        "statuses": statuses,
        "limit": int(limit),
        "count": len(hits),
        "hits": hits,
    }




def stale_check(library_root) -> dict:
    """纯计算：L2/L3 引用的 L1 revision 变了或没了 ⇒ 该条过期。**不改任何文件**（只刷新派生索引）。

    三分类（不把「不知道」混进「新鲜」）：
      - stale   ：有锚点且对不上（revision 变了 / 引用目标已不在 L1 索引里）；
      - unpinned：来源没写 `@rev`（或压根没写 :PM_SOURCES:）⇒ 无法判定，单独列出；
      - fresh   ：全部锚点都对上。
    """
    root = Path(library_root)
    build(root)  # 派生索引按需刷新（只写 .local/**，不碰 Org）
    con = _connect(index_path(root))
    try:
        current: dict[str, dict] = {}
        for row in con.execute(
            "SELECT id, revision, path, status FROM entries WHERE layer = ? AND id IS NOT NULL",
            (memory.LAYER_L1,),
        ):
            key = row["id"]
            previous = current.get(key)
            # 同 ID 可能在候选与正式区各一份：优先记正式区（memory/ 开头）那条的 revision。
            if previous is None or str(row["path"]).startswith(memory.MEMORY_DIRNAME + "/"):
                current[key] = {"revision": int(row["revision"]), "path": row["path"], "status": row["status"]}
        rows = [dict(row) for row in con.execute(
            "SELECT * FROM entries WHERE layer IN (?,?) ORDER BY path, line",
            (memory.LAYER_L2, memory.LAYER_L3),
        ).fetchall()]
        # ★ **L3 按设计不进索引**（连索引都不建）⇒ 生成命令产出的 L2/L3 候选必须**直接读 Org**，
        #   否则「L3 引用变了」永远判不出来（实测踩过：改了 L2 文件，L3 候选仍报 fresh）。
        seen_keys = {(str(row["path"]), int(row["line"])) for row in rows}
        candidates_path = root / memory.CANDIDATES_RELATIVE
        if candidates_path.is_file():
            try:
                candidate_text = candidates_path.read_text(encoding="utf-8")
            except OSError:
                candidate_text = ""
            for entry in memory.parse_entries_text(candidate_text):
                if entry.layer not in (memory.LAYER_L2, memory.LAYER_L3):
                    continue
                key = (memory.CANDIDATES_RELATIVE, int(entry.line))
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                rows.append({
                    "id": entry.id, "layer": entry.layer, "status": entry.status,
                    "revision": int(entry.revision), "path": memory.CANDIDATES_RELATIVE,
                    "line": int(entry.line), "source_rev": " ".join(entry.sources),
                })
        rows.sort(key=lambda row: (str(row["path"]), int(row["line"])))
        stale: list[dict] = []
        unpinned: list[dict] = []
        fresh = 0
        skipped_deprecated = 0
        file_hash_cache: dict[str, str | None] = {}

        def _file_hash(rel: str) -> str | None:
            if rel not in file_hash_cache:
                target = root / rel
                try:
                    file_hash_cache[rel] = _sha256_file(target)[:12] if target.is_file() else None
                except OSError:
                    file_hash_cache[rel] = None
            return file_hash_cache[rel]

        for row in rows:
            if str(row["status"]) == memory.STATUS_DEPRECATED:
                # 已作废的是历史，不再催你重新生成；但要如实计数（不静默丢）。
                skipped_deprecated += 1
                continue
            pins = memory.parse_source_refs(str(row["source_rev"] or "").split())
            item = {
                "id": row["id"],
                "layer": row["layer"],
                "status": row["status"],
                "revision": int(row["revision"]),
                "path": row["path"],
                "line": int(row["line"]),
                "source": str(row["path"]) + ":" + str(row["line"]),
                "sources": str(row["source_rev"] or ""),
            }
            if not pins:
                item["reason"] = "没有 :PM_SOURCES: 版本锚点（写成 id@revision 才能判新鲜）"
                unpinned.append(item)
                continue
            problems: list[str] = []
            for ref, pinned_rev, pinned_hash in pins:
                if "/" in ref:
                    # 文件锚点（L3 → L2 文件）：比内容 hash 前 12 位
                    actual = _file_hash(ref)
                    if actual is None:
                        problems.append(ref + " 文件不在了")
                    elif pinned_hash is None:
                        problems.append(ref + " 没有 hash 锚点（写成 path@hash）")
                    elif not (actual.startswith(pinned_hash) or pinned_hash.startswith(actual)):
                        problems.append(ref + " 内容变了（" + pinned_hash + " → " + actual + "）")
                    continue
                current_row = current.get(ref)
                if current_row is None:
                    problems.append(ref + " 已不在 L1 索引里（被删/被改名/层级变了）")
                elif pinned_rev is None:
                    problems.append(ref + " 没有版本锚点（写成 id@revision）")
                elif current_row["revision"] != pinned_rev:
                    problems.append(ref + " revision " + str(pinned_rev) + " → " + str(current_row["revision"]))
            if problems:
                item["problems"] = problems
                stale.append(item)
            else:
                fresh += 1
    finally:
        con.close()
    return {"library": str(root), "checked": len(rows), "stale": stale, "unpinned": unpinned,
            "fresh": fresh, "skippedDeprecated": skipped_deprecated}


def _fail(code: str, message: str, json_mode: bool) -> int:
    if json_mode:
        print(json.dumps({"ok": False, "error": {"code": code, "message": message}}, ensure_ascii=False, indent=2))
    else:
        print("pm: [" + code + "] " + message, file=sys.stderr)
    return 2


def _resolve_read_target(args):
    config_path = getattr(args, "config", None)
    if config_path is not None:
        path = Path(str(config_path)).expanduser()
        if not path.is_file():
            return None, ("CONFIG_NOT_FOUND", "指定的 --config 不存在: " + str(path) + "（未读取任何内容）", 2)
    try:
        config, _warnings = load_config(config_path)
    except Exception as exc:
        return None, ("CONFIG_ERROR", str(exc), 2)
    if config.library is None:
        return None, ("NO_LIBRARY", "未配置 work-memory 库（pm.toml 缺 library）", 2)
    layout = Layout(Path(config.library).expanduser())
    if not layout.root.is_dir():
        return None, ("LIBRARY_MISSING", "work-memory 库目录不存在: " + str(layout.root), 2)
    return layout, None


def command_index(args) -> int:
    json_mode = bool(getattr(args, "json", False))
    from pm.cli import resolve_write_target
    layout, error = resolve_write_target(args, json_mode)
    if error:
        code, message = error[0], error[1]  # 第三个是 error 自带的退出码，_fail 只有一个位置参数对
        return _fail(code, message, json_mode=json_mode)
    try:
        stats = build(layout.root, rebuild=bool(getattr(args, "rebuild", False)),
                      dry_run=bool(getattr(args, "dry_run", False)))
    except IndexError_ as exc:
        return _fail(exc.code, exc.message, json_mode)
    except sqlite3.Error as exc:
        # ③ CLI 面不许抛 traceback：只读/损坏等 sqlite 错误翻成**人话**（exit 2）。
        return _fail("DB_ERROR", "索引数据库不可用（" + exc.__class__.__name__ + "：" + str(exc) + "）；"
                                 "若库在只读位置，pm recall 会自动走 org-scan 回退；pm index 需要可写位置。",
                     json_mode)
    if json_mode:
        print(json.dumps({"ok": True, "data": stats}, ensure_ascii=False, indent=2))
        return 0
    print("索引: " + stats["db"])
    print("模式: " + stats["mode"] + ("（FTS5）" if stats["mode"] == "fts5" else "（降级：LIKE）"))
    print("层: " + ",".join(stats["layers"]) + " | 文件 " + str(stats["files"]) +
          " | 条目 " + str(stats["entries"]) + ("（库里 " + str(stats.get("entriesInDb")) + "）" if not stats.get("dryRun") else "（dry-run，未写）"))
    if stats["filesChanged"] or stats["filesSkipped"]:
        print("刷新: " + (",".join(stats["filesChanged"]) or "无") + " | 跳过(未变): " + (",".join(stats["filesSkipped"]) or "无"))
    if stats.get("schemaRebuilt"):
        print("重建说明: " + stats["schemaRebuilt"])
    if stats["degraded"]:
        print("降级说明: FTS5 不可用（sqlite " + stats["sqliteVersion"] + "）→ 索引按 LIKE 检索，排序/分词能力受限")
    return 0


def command_recall(args) -> int:
    json_mode = bool(getattr(args, "json", False))
    layout, error = _resolve_read_target(args)
    if error:
        code, message = error[0], error[1]
        return _fail(code, message, json_mode=json_mode)
    try:
        result = recall(layout.root, args.query, scope=getattr(args, "scope", None),
                        type=getattr(args, "type", None), limit=int(getattr(args, "limit", DEFAULT_LIMIT) or DEFAULT_LIMIT),
                        include_candidate=bool(getattr(args, "include_candidate", False)),
                        include_deprecated=bool(getattr(args, "include_deprecated", False)),
                        any_mode=bool(getattr(args, "any", False)))
    except IndexError_ as exc:
        return _fail(exc.code, exc.message, json_mode)
    except sqlite3.Error as exc:
        # ③ CLI 面不许抛 traceback（只读库/索引损坏等）。
        return _fail("DB_ERROR", "索引数据库不可用（" + exc.__class__.__name__ + "：" + str(exc) + "）"
                                 "—— 只读位置请用 pm recall（会自动 org-scan 回退），或把库放到可写位置后 pm index。",
                     json_mode)
    if json_mode:
        print(json.dumps({"ok": True, "data": result}, ensure_ascii=False, indent=2))
        return 0
    if result["note"]:
        print("⚠ " + result["note"])
    print("库: " + result["library"] + " | 索引条目 " + str(result["indexEntries"]) + " | 模式: " + result["mode"] + " | match=" + result["match"])
    print("查询: " + result["query"] + " | 命中 " + str(result["count"]) + " 条（layer=" + ",".join(result["layers"]) + "；status=" + ",".join(result["statuses"]) + "）")
    for hit in result["hits"]:
        print("  " + hit["source"] + "  rev " + str(hit["revision"]) + "  [" + hit["layer"] + "/" + hit["status"] + "/" + str(hit["scope"]) + "/" + str(hit["type"]) + "]")
        print("    " + (hit["title"] or "") + " — " + hit["snippet"])
    return 0


def register_cli(subparsers) -> None:
    index = subparsers.add_parser("index", help="建/刷新记忆内容索引（派生物：<库>/.local/index.sqlite）")
    index.add_argument("--rebuild", action="store_true", help="丢掉旧索引整份重建（默认增量刷新）")
    index.add_argument("--dry-run", dest="dry_run", action="store_true", help="只预演统计，一字节不写")
    index.add_argument("--yes", action="store_true", help="确认要写「默认配置指向的库」（未显式 --config 时必需）")
    index.add_argument("--json", action="store_true", help="输出 JSON")
    # as_defaults=True ⇒ SUPPRESS：子命令**不覆盖**父级解析到的 --config/--dsh-home
    # （否则 `pm --config X index` 会被子解析器的默认 None 冲掉 ⇒ 误判 NEEDS_YES / 读错库）
    _add_common_options(index, as_defaults=True)
    index.set_defaults(handler=command_index)

    recall_parser = subparsers.add_parser("recall", help="按默认口径检索记忆（L1/L2 + VERIFIED；L3 不进召回）")
    recall_parser.add_argument("--query", required=True, metavar="Q", help="查询词（可为中文短语）")
    recall_parser.add_argument("--scope", metavar="SCOPE", help="只看某个 scope（项目 key 或 global）")
    recall_parser.add_argument("--type", metavar="T", help="只看某类（fact / decision / gotcha）")
    recall_parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, metavar="N", help="最多返回几条（默认 10）")
    recall_parser.add_argument("--include-candidate", dest="include_candidate", action="store_true", help="把 CANDIDATE 也纳入（默认只 VERIFIED）")
    recall_parser.add_argument("--include-deprecated", dest="include_deprecated", action="store_true", help="把 DEPRECATED 也纳入（默认排除）")
    recall_parser.add_argument("--any", action="store_true", help="词间改为「任一命中」（默认 AND；多词 AND 零命中时会自动放宽并标 match=any）")
    recall_parser.add_argument("--json", action="store_true", help="输出 JSON")
    _add_common_options(recall_parser, as_defaults=True)  # 同上：父级 --config 必须活下来
    recall_parser.set_defaults(handler=command_recall)
