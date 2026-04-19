from __future__ import annotations

import json
import sys


def main() -> int:
    payload = json.load(sys.stdin)
    envelope = payload.get("envelope", {})
    selected = payload.get("selectedModel") or {}
    json.dump(
        {
            "status": "ok",
            "bridge": payload.get("bridge"),
            "mode": payload.get("mode"),
            "executionKey": envelope.get("executionKey"),
            "symbioteId": envelope.get("symbioteId"),
            "role": envelope.get("role"),
            "taskId": (envelope.get("task") or {}).get("taskId"),
            "selectedModelId": selected.get("modelId"),
            "selectedProvider": selected.get("provider"),
        },
        sys.stdout,
        sort_keys=True,
    )
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
