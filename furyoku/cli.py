from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from .model_registry import load_model_registry
from .model_router import ModelScore, TaskProfile, select_model
from .provider_adapters import ProviderExecutionRequest
from .runtime import RoutedExecutionResult, route_and_execute


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    models = load_model_registry(args.registry)
    task = _task_from_args(args)

    if args.command == "select":
        selection = select_model(models, task)
        _write_json(_score_to_dict(selection))
        return 0

    if args.command == "run":
        result = route_and_execute(
            models,
            task,
            ProviderExecutionRequest(args.prompt, timeout_seconds=args.timeout_seconds),
        )
        _write_json(_routed_result_to_dict(result))
        return 0 if result.ok else 2

    parser.error(f"unsupported command {args.command}")
    return 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="FURYOKU multi-model router/runtime CLI.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    _add_common_task_args(subparsers.add_parser("select", help="Select the best eligible model for a task."))
    run_parser = subparsers.add_parser("run", help="Select and execute the best eligible model for a task.")
    _add_common_task_args(run_parser)
    run_parser.add_argument("--prompt", required=True, help="Prompt text passed to the selected model.")
    run_parser.add_argument("--timeout-seconds", type=float, default=60.0, help="Execution timeout in seconds.")
    return parser


def _add_common_task_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--registry", required=True, type=Path, help="Path to a FURYOKU model registry JSON file.")
    parser.add_argument("--task-id", required=True, help="Task identifier for routing evidence.")
    parser.add_argument(
        "--capability",
        action="append",
        required=True,
        default=[],
        metavar="NAME=SCORE",
        help="Required capability score from 0.0 to 1.0. Repeat for multiple capabilities.",
    )
    parser.add_argument("--description", default="", help="Optional task description.")
    parser.add_argument("--min-context-tokens", type=int, default=0, help="Minimum required context window.")
    parser.add_argument(
        "--privacy",
        default="allow_remote",
        choices=("allow_remote", "prefer_local", "local_only"),
        help="Privacy requirement for model selection.",
    )
    parser.add_argument("--require-tools", action="store_true", help="Require tool-capable endpoints.")
    parser.add_argument("--require-json", action="store_true", help="Require structured JSON-capable endpoints.")
    parser.add_argument(
        "--preferred-provider",
        action="append",
        default=[],
        help="Preferred provider id. Repeat for multiple providers.",
    )
    parser.add_argument("--max-input-cost-per-1k", type=float, default=None, help="Maximum input cost per 1k tokens.")
    parser.add_argument("--max-output-cost-per-1k", type=float, default=None, help="Maximum output cost per 1k tokens.")


def _task_from_args(args: argparse.Namespace) -> TaskProfile:
    return TaskProfile(
        task_id=args.task_id,
        description=args.description,
        required_capabilities=_parse_capabilities(args.capability),
        min_context_tokens=args.min_context_tokens,
        privacy_requirement=args.privacy,
        max_input_cost_per_1k=args.max_input_cost_per_1k,
        max_output_cost_per_1k=args.max_output_cost_per_1k,
        require_tools=args.require_tools,
        require_json=args.require_json,
        preferred_providers=tuple(args.preferred_provider),
    )


def _parse_capabilities(raw_values: Sequence[str]) -> dict[str, float]:
    capabilities: dict[str, float] = {}
    for raw_value in raw_values:
        if "=" not in raw_value:
            raise argparse.ArgumentTypeError(f"capability must use NAME=SCORE syntax: {raw_value}")
        name, raw_score = raw_value.split("=", 1)
        name = name.strip()
        if not name:
            raise argparse.ArgumentTypeError("capability name must be non-empty")
        try:
            score = float(raw_score)
        except ValueError as exc:
            raise argparse.ArgumentTypeError(f"capability score must be numeric: {raw_value}") from exc
        if score < 0.0 or score > 1.0:
            raise argparse.ArgumentTypeError(f"capability score must be between 0.0 and 1.0: {raw_value}")
        capabilities[name] = score
    return capabilities


def _score_to_dict(selection: ModelScore) -> dict:
    return {
        "modelId": selection.model.model_id,
        "provider": selection.model.provider,
        "score": selection.score,
        "eligible": selection.eligible,
        "reasons": list(selection.reasons),
        "blockers": list(selection.blockers),
    }


def _routed_result_to_dict(result: RoutedExecutionResult) -> dict:
    execution = result.execution
    return {
        "ok": result.ok,
        "selection": _score_to_dict(result.selection),
        "execution": {
            "modelId": execution.model_id,
            "provider": execution.provider,
            "status": execution.status,
            "responseText": execution.response_text,
            "elapsedMs": execution.elapsed_ms,
            "exitCode": execution.exit_code,
            "stderr": execution.stderr,
            "error": execution.error,
            "timedOut": execution.timed_out,
        },
    }


def _write_json(payload: dict) -> None:
    json.dump(payload, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    raise SystemExit(main())
