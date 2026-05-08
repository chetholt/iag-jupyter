#!/usr/bin/env bash
# fd_report.sh - Report top 10 processes by open file descriptor count using /proc
# Compatible with bash 3 / POSIX sh (no associative arrays, no mapfile)

SEPARATOR="----------------------------------------------------------------------"
DIVIDER="  ......................................................................"

fd_type_distribution() {
  local pid=$1
  ls -la "/proc/$pid/fd/" 2>/dev/null \
    | awk 'NR>1 && $NF ~ /->/ {
        target = $NF
        if (target ~ /socket:/)         type = "socket"
        else if (target ~ /pipe:/)      type = "pipe"
        else if (target ~ /anon_inode/) type = "anon_inode"
        else if (target ~ /^\/dev\//)  type = "device"
        else if (target ~ /^\//)        type = "file"
        else                            type = "other"
        count[type]++
      }
      END {
        for (t in count) printf "      %-14s %d\n", t":", count[t]
      }' \
    | sort -k2 -rn
}

cmdline_for() {
  local pid=$1
  local raw
  raw=$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null)
  if [ ${#raw} -gt 80 ]; then
    echo "${raw:0:77}..."
  else
    echo "$raw"
  fi
}

# ── Collect FD counts into a flat file ──────────────────────────────────────
tmpfile=$(mktemp)
trap 'rm -f "$tmpfile"' EXIT

for proc_dir in /proc/[0-9]*/fd; do
  [ -d "$proc_dir" ] || continue
  pid=$(echo "$proc_dir" | sed 's|/proc/||; s|/fd||')
  count=$(ls "$proc_dir" 2>/dev/null | wc -l | tr -d ' ')
  echo "$count $pid"
done > "$tmpfile"

# ── Print report ─────────────────────────────────────────────────────────────
echo ""
echo "  FD REPORT — $(date)"
echo ""
echo "$SEPARATOR"
printf "  %-8s %-10s %s\n" "PID" "FD COUNT" "PROCESS NAME"
echo "$SEPARATOR"

rank=1
while read -r count pid; do
  name=$(cat "/proc/$pid/comm" 2>/dev/null || echo "unknown")
  exe=$(readlink "/proc/$pid/exe" 2>/dev/null || echo "n/a")
  cmdline=$(cmdline_for "$pid")

  printf "  %-8s %-10s %s\n" "$pid" "$count" "$name"
  printf "    %-12s %s\n" "exe:"     "$exe"
  printf "    %-12s %s\n" "cmdline:" "$cmdline"
  echo "    fd types:"
  fd_type_distribution "$pid"

  rank=$(( rank + 1 ))
  [ $rank -le 10 ] && echo "$DIVIDER"
done < <(sort -rn "$tmpfile" | head -10)

echo "$SEPARATOR"
echo ""
