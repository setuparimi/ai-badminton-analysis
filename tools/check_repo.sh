#!/usr/bin/env bash
# Scans what git would publish for secrets, personal data, videos and big files. Exits 1 if it finds anything.
#   bash tools/check_repo.sh
#   PII_TERMS='\bjane\b|\bsmith\b|myemployer' bash tools/check_repo.sh      # add your own words (a regex)
# Run it before every push. It cannot see faces: look at every image yourself (they are listed at the end).
set -uo pipefail
cd "$(dirname "$0")/.."
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || { echo "Not a git repository yet (run: git init)."; exit 1; }
TMP=$(mktemp)
trap 'rm -f "$TMP"' EXIT
FILES=$( { git ls-files; git ls-files --others --exclude-standard; } | sort -u )
bad=0
note() { echo "FOUND: $1"; bad=1; }

# 1. file types that must never be published
while IFS= read -r f; do
  case "$f" in
    *.mp4|*.mov|*.mkv|*.avi|*.m4v|*.webm|*.npz|*.pt|*.pth|*.onnx|*.log|.env|.env.*|*.pem|*.key) note "forbidden file type: $f" ;;
  esac
done <<< "$FILES"

# 2. big files
while IFS= read -r f; do
  [ -f "$f" ] || continue
  size=$(wc -c < "$f")
  [ "$size" -gt 3000000 ] && note "file over 3 MB: $f ($((size / 1000000)) MB)"
done <<< "$FILES"

# 3. text patterns (secrets, home paths, emails, your own words)
pat_secret='gh[pousr]_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----|(password|passwd|secret|api[_-]?key|token)[[:space:]]*[:=][[:space:]]*["'"'"']?[A-Za-z0-9/+_.-]{12,}'
pat_path='/Users/[A-Za-z0-9._-]+|/home/[A-Za-z0-9._-]+|[A-Za-z]:\\Users\\'
pat_email='[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}'
while IFS= read -r f; do
  [ -f "$f" ] || continue
  [ "$f" = "tools/check_repo.sh" ] && continue
  grep -Iq . "$f" 2>/dev/null || continue            # skip binary files (images)
  if grep -InE "$pat_secret" "$f" >"$TMP" 2>/dev/null; then note "possible secret in $f:"; sed 's/^/    /' "$TMP" | cut -c1-120; fi
  if grep -InE "$pat_path" "$f" >"$TMP" 2>/dev/null; then note "home path in $f:"; sed 's/^/    /' "$TMP" | cut -c1-120; fi
  if grep -InE "$pat_email" "$f" 2>/dev/null | grep -vE 'noreply@anthropic\.com|users\.noreply\.github\.com' >"$TMP" && [ -s "$TMP" ]; then note "email address in $f:"; sed 's/^/    /' "$TMP" | cut -c1-120; fi
  if [ -n "${PII_TERMS:-}" ] && grep -InEi "$PII_TERMS" "$f" >"$TMP" 2>/dev/null; then note "personal term in $f:"; sed 's/^/    /' "$TMP" | cut -c1-120; fi
done <<< "$FILES"

# 4. git history (author names and emails that would become public)
if git rev-parse HEAD >/dev/null 2>&1; then
  echo "Commit authors that would be public:"; git log --format='    %an <%ae>' | sort -u
fi

# 5. images: a person must look at each one
echo; echo "Images that would be published (look at every one for faces, names and plates):"
echo "$FILES" | grep -iE '\.(png|jpe?g|gif|webp|svg)$' | sed 's/^/    /'

echo
if [ "$bad" -eq 0 ]; then echo "check_repo: no secrets, home paths, emails, videos or big files found."; else echo "check_repo: FIX THE ITEMS ABOVE BEFORE PUSHING."; fi
exit "$bad"
