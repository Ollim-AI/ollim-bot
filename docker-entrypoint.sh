#!/bin/sh
# Pull the Ollama model if ANTHROPIC_BASE_URL points to an Ollama server.
# Runs before the main command so the model is ready when the bot starts.

if [ -n "$ANTHROPIC_BASE_URL" ] && [ -n "$ANTHROPIC_MODEL" ]; then
    echo "checking model $ANTHROPIC_MODEL at $ANTHROPIC_BASE_URL..."
    # Check if model exists (Ollama returns 200 with model info)
    if ! python -c "
import urllib.request, json, sys
try:
    req = urllib.request.Request('${ANTHROPIC_BASE_URL}/api/show',
        data=json.dumps({'name': '${ANTHROPIC_MODEL}'}).encode(),
        headers={'Content-Type': 'application/json'})
    urllib.request.urlopen(req, timeout=5)
except Exception:
    sys.exit(1)
" 2>/dev/null; then
        echo "pulling model $ANTHROPIC_MODEL (this may take a few minutes)..."
        python -c "
import urllib.request, json, sys
req = urllib.request.Request('${ANTHROPIC_BASE_URL}/api/pull',
    data=json.dumps({'model': '${ANTHROPIC_MODEL}', 'stream': False}).encode(),
    headers={'Content-Type': 'application/json'})
try:
    resp = urllib.request.urlopen(req, timeout=600)
    data = json.loads(resp.read())
    print(f\"pulled: {data.get('status', 'done')}\")
except Exception as e:
    print(f'warning: model pull failed: {e}', file=sys.stderr)
"
    else
        echo "model $ANTHROPIC_MODEL ready"
    fi
fi

exec "$@"
