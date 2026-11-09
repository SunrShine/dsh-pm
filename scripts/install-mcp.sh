#!/bin/sh
# 把 pm 的 MCP server 注册进 DSH profile（幂等，自动备份，自验证）。
#
#   scripts/install-mcp.sh [profile-patch-file]
#
# ⚠ 一定要用 insert 形式：裸的 "- id/name" 行是**覆盖已有条目**，
#   对不存在的 id 只会打一行 stderr 警告然后什么都不做：
#       patch: entry "mcp-pm" not found
set -eu

PATCH="${1:-$HOME/.dsh-preview/profiles/web/cordis.patch.yml}"
HERE=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
SNIPPET="$HERE/config/dsh-mcp.patch.yml"

if [ ! -f "$PATCH" ]; then
  echo "找不到 profile patch 文件: $PATCH" >&2
  echo "（用第一个参数指定，例如 ~/.dsh/profiles/web/cordis.patch.yml）" >&2
  exit 2
fi
if grep -q 'id: mcp-pm' "$PATCH"; then
  echo "已经注册过（找到 id: mcp-pm），未改动"
else
  BACKUP="$PATCH.bak-$(date +%Y%m%d-%H%M%S)"
  cp "$PATCH" "$BACKUP"
  printf '\n' >> "$PATCH"
  cat "$SNIPPET" >> "$PATCH"
  echo "已追加到 $PATCH"
  echo "备份: $BACKUP"
fi

# 自验证：dump 组合后的配置，确认 mcp-pm 真的进去了、且没有 not found 警告
DSH_CHECKOUT=${DSH_CHECKOUT:-<dsh-checkout>}
if [ -f "$DSH_CHECKOUT/apps/cli/src/bin.ts" ] && command -v node >/dev/null 2>&1; then
  echo "验证中（dump 组合配置）..."
  OUT=$(cd "$DSH_CHECKOUT" && DSH_HOME="${DSH_HOME:-$HOME/.dsh-preview}" \
        node --import tsx/esm apps/cli/src/bin.ts --profile web --dump-config 2>/dev/null \
        | grep -c 'mcp-pm' || true)
  ERR=$(cd "$DSH_CHECKOUT" && DSH_HOME="${DSH_HOME:-$HOME/.dsh-preview}" \
        node --import tsx/esm apps/cli/src/bin.ts --profile web --dump-config 2>&1 >/dev/null \
        | grep 'mcp-pm' || true)
  if [ "${OUT:-0}" -gt 0 ] && [ -z "$ERR" ]; then
    echo "✅ 验证通过：mcp-pm 已进入组合配置，无 not found 警告"
  else
    echo "⚠ 验证未通过：dump 命中 $OUT 次；stderr: $ERR" >&2
    echo "  （出现 not found = 没包在 insert: 里）" >&2
    exit 1
  fi
fi

echo "改完 profile 需要 DSH 重载（重启或 HMR）后生效。"
