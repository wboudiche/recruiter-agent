#!/usr/bin/env bash
set -euo pipefail
URL="${API_URL:-http://localhost:8000}"
echo "Generating types from ${URL}/openapi.json"
npx openapi-typescript "${URL}/openapi.json" -o src/lib/api-types.ts
