#!/bin/bash
# 브라우저(헤드리스 Edge) 검사 실행: bash tests/browser/run.sh [app_check|bis_check]   (기본: 둘 다)
# 결과: "PASS: n  FAIL: m" (실패하면 FAIL 줄과 got/want 가 같이 나온다). Windows + Edge 전제, node 불필요.
EDGE="/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"
HERE="$(cd "$(dirname "$0")" && pwd)"
for name in ${1:-app_check bis_check}; do
  echo "== $name"
  timeout 60 "$EDGE" --headless=new --disable-gpu --allow-file-access-from-files --virtual-time-budget=4000 \
    --dump-dom "file:///$(cygpath -m "$HERE/$name.html")" 2>/dev/null | python -c "
import sys, re, html, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
d = sys.stdin.buffer.read().decode('utf-8', 'replace')
m = re.search(r'<pre id=\"out\">(.*?)</pre>', d, re.S)
L = (html.unescape(m.group(1)) if m else 'NO OUTPUT').splitlines()
print('\n'.join(l for l in L if l.startswith('FAIL') or l.startswith('   ') or 'ERROR' in l or l.startswith('NO OUT'))[:3000])
print('PASS:', sum(1 for l in L if l.startswith('PASS')), ' FAIL:', sum(1 for l in L if l.startswith('FAIL')))"
done
