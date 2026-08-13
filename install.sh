#!/bin/sh
# Install the Riftbound rules-report skill.
#
#   curl -fsSL https://raw.githubusercontent.com/gear-null/riftbound-oracle/main/install.sh | sh
#
# Or, if you would rather read it first (you should):
#   curl -fsSL .../install.sh -o install.sh && less install.sh && sh install.sh
#
# Options:
#   --dir <path>     where to install (default: .claude/skills)
#   --version <tag>  a specific release (default: latest)
#   --force          overwrite an existing install
#   --no-verify      skip the selftest (not recommended)
#
# POSIX sh on purpose: this has to run under dash, busybox and macOS's old bash.

set -eu

REPO="gear-null/riftbound-oracle"
SKILL="rules-report"
DIR="${RIFTBOUND_SKILL_DIR:-.claude/skills}"
VERSION="latest"
FORCE=0
VERIFY=1

say()  { printf '%s\n' "$*"; }
warn() { printf '\033[33m%s\033[0m\n' "$*" >&2; }
die()  { printf '\033[31merror: %s\033[0m\n' "$*" >&2; exit 1; }

while [ $# -gt 0 ]; do
  case "$1" in
    --dir)        DIR="${2:?--dir needs a path}"; shift 2 ;;
    --version)    VERSION="${2:?--version needs a tag}"; shift 2 ;;
    --force)      FORCE=1; shift ;;
    --no-verify)  VERIFY=0; shift ;;
    -h|--help)    sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *)            die "unknown option: $1 (try --help)" ;;
  esac
done

need() { command -v "$1" >/dev/null 2>&1 || die "$1 is required but not installed"; }
need curl
need unzip

# --- Python floor -----------------------------------------------------------
# The skill is pure Python and needs 3.9+. Checking now beats a TypeError from
# inside the selftest, which is what a too-old interpreter used to produce.
PY=""
for candidate in python3 python; do
  if command -v "$candidate" >/dev/null 2>&1 &&
     "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,9) else 1)' 2>/dev/null; then
    PY="$candidate"; break
  fi
done
[ -n "$PY" ] || die "Python 3.9+ is required. Found: $(python3 --version 2>&1 || echo none)"

# --- Resolve the release ----------------------------------------------------
if [ "$VERSION" = "latest" ]; then
  say "Finding the latest release..."
  # Follow the redirect rather than parsing the API, so this needs no token and
  # no jq, and cannot be rate-limited into failing on a bad JSON parse.
  RESOLVED=$(curl -fsSLI -o /dev/null -w '%{url_effective}' \
    "https://github.com/$REPO/releases/latest" 2>/dev/null) \
    || die "could not reach GitHub"
  VERSION="${RESOLVED##*/}"
  case "$VERSION" in v*) ;; *) die "could not determine the latest version (got '$VERSION')" ;; esac
fi
say "Installing $SKILL $VERSION"

# Refuse before downloading 500KB we would only throw away.
TARGET="$DIR/$SKILL"
if [ -e "$TARGET" ] && [ "$FORCE" -ne 1 ]; then
  OLD=$([ -f "$TARGET/SKILL-VERSION.json" ] &&
        sed -n 's/.*"version"[^"]*"\([^"]*\)".*/\1/p' "$TARGET/SKILL-VERSION.json" || echo "unknown")
  die "$TARGET already exists (version $OLD). Re-run with --force to replace it."
fi

ASSET="riftbound-rules-report-$VERSION.zip"
BASE="https://github.com/$REPO/releases/download/$VERSION"

# --- Download and verify ----------------------------------------------------
TMP=$(mktemp -d)
# shellcheck disable=SC2064  # expand TMP now, not at trap time
trap "rm -rf '$TMP'" EXIT INT TERM

curl -fsSL "$BASE/$ASSET" -o "$TMP/$ASSET" || die "download failed: $BASE/$ASSET"

if curl -fsSL "$BASE/$ASSET.sha256" -o "$TMP/$ASSET.sha256" 2>/dev/null; then
  EXPECTED=$(cut -d' ' -f1 < "$TMP/$ASSET.sha256")
  if command -v shasum >/dev/null 2>&1; then
    ACTUAL=$(shasum -a 256 "$TMP/$ASSET" | cut -d' ' -f1)
  elif command -v sha256sum >/dev/null 2>&1; then
    ACTUAL=$(sha256sum "$TMP/$ASSET" | cut -d' ' -f1)
  else
    ACTUAL=""
    warn "no sha256 tool found — skipping checksum verification"
  fi
  if [ -n "$ACTUAL" ]; then
    [ "$ACTUAL" = "$EXPECTED" ] || die "checksum mismatch
  expected $EXPECTED
  got      $ACTUAL
Refusing to install. Report this at https://github.com/$REPO/issues"
    say "Checksum verified."
  fi
else
  warn "no published checksum for $VERSION — proceeding unverified"
fi

# --- Install ----------------------------------------------------------------
mkdir -p "$DIR"
rm -rf "$TARGET"
unzip -q "$TMP/$ASSET" -d "$DIR" || die "unzip failed"
[ -d "$TARGET" ] || die "archive did not contain $SKILL/"

# --- Prove it works ---------------------------------------------------------
if [ "$VERIFY" -eq 1 ]; then
  say "Verifying..."
  if ! (cd "$TARGET/lib" && "$PY" rules_cli.py selftest >"$TMP/selftest.log" 2>&1); then
    tail -20 "$TMP/selftest.log" >&2
    die "the selftest did not pass — this install is not trustworthy"
  fi
  say "$(tail -1 "$TMP/selftest.log")"
fi

say ""
say "Installed to $TARGET"
say ""
case "$DIR" in
  *.claude/skills*)
    say "Claude Code will pick it up automatically. Ask a rules question:"
    say "  \"Does a countered Flow spell still get banished?\"" ;;
  *)
    say "Point your agent at $TARGET/SKILL.md and give it shell access to $TARGET/lib." ;;
esac
say ""
say "Other agents: this is a plain folder of Python and data. Move it wherever your"
say "agent takes skills, or re-run with --dir <path>."
