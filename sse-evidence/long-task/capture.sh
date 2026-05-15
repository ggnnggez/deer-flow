#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"

curl 'http://localhost:2026/api/langgraph/threads/1aa43d59-cfdb-4cd9-a88a-3585086bd6fb/runs/stream' \
  -N \
  -sS \
  -D "$SCRIPT_DIR/headers.txt" \
  -o "$SCRIPT_DIR/raw.sse" \
  -w 'http_code=%{http_code}
size_download=%{size_download}
time_total=%{time_total}
speed_download=%{speed_download}
' \
  -H 'sec-ch-ua-platform: "Windows"' \
  -H 'x-csrf-token: jNL45K3vaUzv3yJqrJWsRRWPRKH7bFoUZ_ibbryclZtg6-UlUCECk-XcqICTc1JjfqJ5rKD-0MN4cBBvZE-4bw' \
  -H 'Cookie: access_token=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI0ZGFlYWEzMS03YWM2LTRlYjUtYmRmNi04MDI5YWJjNTFmYWIiLCJleHAiOjE3NzkzNTc0MzIsImlhdCI6MTc3ODc1MjYzMiwidmVyIjowfQ.duXGQgEoek1UV-QvtTLMCYGGeAUjJFCsRd0tkzlNgL8; csrf_token=jNL45K3vaUzv3yJqrJWsRRWPRKH7bFoUZ_ibbryclZtg6-UlUCECk-XcqICTc1JjfqJ5rKD-0MN4cBBvZE-4bw' \
  -H 'Referer: http://localhost:2026/workspace/chats/1aa43d59-cfdb-4cd9-a88a-3585086bd6fb' \
  -H 'User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36' \
  -H 'sec-ch-ua: "Chromium";v="148", "Google Chrome";v="148", "Not/A)Brand";v="99"' \
  -H 'content-type: application/json' \
  -H 'sec-ch-ua-mobile: ?0' \
  --data-raw '{"input":{"messages":[{"type":"human","content":[{"type":"text","text":"把 p0 p1 p2 中的所有bug，都写一份根因分析报告，且报告中附上修复方案"}],"additional_kwargs":{}}]},"config":{"recursion_limit":1000},"context":{"model_name":"kimi-k2.6","mode":"pro","reasoning_effort":"medium","thinking_enabled":true,"is_plan_mode":true,"subagent_enabled":false,"thread_id":"1aa43d59-cfdb-4cd9-a88a-3585086bd6fb"},"stream_mode":["messages-tuple","values","updates","custom","events"],"stream_subgraphs":true,"stream_resumable":true,"assistant_id":"lead_agent","on_disconnect":"continue"}' \
  | tee "$SCRIPT_DIR/curl-metrics.txt"
