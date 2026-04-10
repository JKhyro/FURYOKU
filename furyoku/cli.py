from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import sys
from pathlib import Path
from typing import Sequence

from .character_profiles import (
    CharacterProfileSelection,
    build_character_orchestration_envelope,
    load_character_profile,
    select_character_profile_models,
)
from .model_registry import load_model_registry
from .model_router import ModelScore, RouterError, TaskProfile, load_routing_score_policy, select_model
from .model_decisions import ModelDecisionReport, evaluate_model_decisions, load_decision_suite
from .outcome_feedback import (
    VALID_OUTCOME_VERDICTS,
    append_decision_outcome,
    create_decision_outcome_record,
    load_feedback_adjustment_policy,
    load_decision_outcomes,
)
from .provider_health import ProviderHealthCheckRequest, ProviderHealthCheckResult, check_provider_health_many
from .provider_adapters import ProviderExecutionRequest, ProviderExecutionResult
from .runtime import (
    CharacterRoleExecutionResult,
    DecisionSituationExecutionResult,
    RoutedExecutionResult,
    execute_character_role,
    execute_decision_situation,
    route_and_execute,
)
from .task_profiles import load_task_profile


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "feedback":
        record = create_decision_outcome_record(
            args.report,
            verdict=args.verdict,
            score=args.score,
            reason=args.reason,
            tags=args.tag,
            override_model_id=args.override_model_id or "",
        )
        append_decision_outcome(args.feedback_log, record)
        _write_json(record.to_dict())
        return 0

    models = load_model_registry(args.registry)

    if args.command == "select":
        task = _task_from_args(args, parser)
        readiness = _readiness_from_args(args, models)
        feedback, feedback_policy = _feedback_from_args(args, parser)
        routing_policy = _routing_policy_from_args(args)
        selection, report = _select_with_optional_feedback(
            models,
            task,
            feedback,
            feedback_policy=feedback_policy,
            readiness=readiness,
            routing_policy=routing_policy,
        )
        _write_json(_single_selection_to_dict(selection, report=report, readiness=readiness))
        return 0

    if args.command == "run":
        if args.decision_suite:
            if not args.situation_id:
                parser.error("--situation-id is required when --decision-suite is provided")
            readiness = _readiness_from_args(args, models)
            feedback, feedback_policy = _feedback_from_args(args, parser)
            routing_policy = _routing_policy_from_args(args)
            result = execute_decision_situation(
                models,
                load_decision_suite(args.decision_suite),
                args.situation_id,
                ProviderExecutionRequest(args.prompt, timeout_seconds=args.timeout_seconds),
                readiness=readiness,
                feedback=feedback,
                feedback_policy=feedback_policy,
                routing_policy=routing_policy,
            )
            _write_json(_decision_execution_result_to_dict(result, readiness=readiness), output_path=args.output)
            return 0 if result.ok else 2

        task = _task_from_args(args, parser)
        readiness = _readiness_from_args(args, models)
        feedback, feedback_policy = _feedback_from_args(args, parser)
        routing_policy = _routing_policy_from_args(args)
        result = route_and_execute(
            models,
            task,
            ProviderExecutionRequest(args.prompt, timeout_seconds=args.timeout_seconds),
            readiness=readiness,
            feedback=feedback,
            feedback_policy=feedback_policy,
            routing_policy=routing_policy,
        )
        _write_json(_routed_result_to_dict(result, readiness=readiness), output_path=args.output)
        return 0 if result.ok else 2

    if args.command == "health":
        results = check_provider_health_many(
            models,
            ProviderHealthCheckRequest(
                probe=args.probe,
                probe_prompt=args.probe_prompt,
                timeout_seconds=args.timeout_seconds,
            ),
        )
        _write_json({"ok": all(result.ready for result in results), "providers": [_health_to_dict(result) for result in results]})
        return 0 if all(result.ready for result in results) else 2

    if args.command == "decide":
        if args.decision_suite and args.task_profile:
            parser.error("--decision-suite cannot be combined with --task-profile")
        decision_input = load_decision_suite(args.decision_suite) if args.decision_suite else tuple(
            load_task_profile(path) for path in args.task_profile
        )
        readiness = _readiness_from_args(args, models)
        feedback, feedback_policy = _feedback_from_args(args, parser)
        routing_policy = _routing_policy_from_args(args)
        report = evaluate_model_decisions(
            models,
            decision_input or None,
            readiness=readiness,
            feedback=feedback,
            feedback_policy=feedback_policy,
            routing_policy=routing_policy,
        )
        _write_json(_decision_report_to_dict(report, readiness=readiness), output_path=args.output)
        return 0 if not report.blocked_tasks else 2

    if args.command == "character-select":
        profile = load_character_profile(args.character_profile)
        readiness = _readiness_from_args(args, models)
        selection = select_character_profile_models(
            models,
            profile,
            allow_reuse=not args.no_reuse,
            readiness=readiness,
        )
        _write_json(_character_profile_selection_to_dict(selection), output_path=args.output)
        return 0

    if args.command == "character-run":
        profile = load_character_profile(args.character_profile)
        readiness = _readiness_from_args(args, models)
        result = execute_character_role(
            models,
            profile,
            ProviderExecutionRequest(args.prompt, timeout_seconds=args.timeout_seconds),
            role_id=args.role_id,
            allow_reuse=not args.no_reuse,
            readiness=readiness,
        )
        _write_json(_character_role_result_to_dict(result), output_path=args.output)
        return 0 if result.ok else 2

    parser.error(f"unsupported command {args.command}")
    return 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="FURYOKU multi-model router/runtime CLI.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    select_parser = subparsers.add_parser("select", help="Select the best eligible model for a task.")
    _add_common_task_args(select_parser)
    _add_health_decision_args(select_parser, "Run provider readiness checks before selecting a model.")
    _add_routing_policy_arg(select_parser)
    select_parser.add_argument(
        "--feedback-log",
        type=Path,
        help="Optional JSONL outcome feedback log used to adjust eligible model rankings.",
    )
    _add_feedback_policy_arg(select_parser)
    run_parser = subparsers.add_parser("run", help="Select and execute the best eligible model for a task.")
    _add_common_task_args(run_parser)
    run_parser.add_argument(
        "--decision-suite",
        type=Path,
        help="Run a named situation from a reusable FURYOKU decision suite.",
    )
    run_parser.add_argument(
        "--situation-id",
        help="Situation/task id inside --decision-suite to execute.",
    )
    run_parser.add_argument("--prompt", required=True, help="Prompt text passed to the selected model.")
    run_parser.add_argument("--timeout-seconds", type=float, default=60.0, help="Execution timeout in seconds.")
    run_parser.add_argument("--output", type=Path, help="Optional path to persist the JSON execution report.")
    run_parser.add_argument(
        "--check-health",
        action="store_true",
        help="Run provider readiness checks before direct or decision-suite execution.",
    )
    run_parser.add_argument("--health-probe", action="store_true", help="Run lightweight provider probes with --check-health.")
    run_parser.add_argument("--health-probe-prompt", default="", help="Prompt text used when --health-probe is set.")
    run_parser.add_argument("--health-timeout-seconds", type=float, default=5.0, help="Health probe timeout in seconds.")
    run_parser.add_argument(
        "--feedback-log",
        type=Path,
        help="Optional JSONL outcome feedback log used to adjust decision-suite execution selection.",
    )
    _add_feedback_policy_arg(run_parser)
    _add_routing_policy_arg(run_parser)
    health_parser = subparsers.add_parser("health", help="Check provider endpoint readiness for a registry.")
    health_parser.add_argument("--registry", required=True, type=Path, help="Path to a FURYOKU model registry JSON file.")
    health_parser.add_argument("--probe", action="store_true", help="Run a lightweight probe instead of only checking configuration.")
    health_parser.add_argument("--probe-prompt", default="", help="Prompt text used when --probe is set.")
    health_parser.add_argument("--timeout-seconds", type=float, default=5.0, help="Health probe timeout in seconds.")
    decide_parser = subparsers.add_parser(
        "decide",
        help="Evaluate local, CLI, and API models across multiple decision situations.",
    )
    decide_parser.add_argument("--registry", required=True, type=Path, help="Path to a FURYOKU model registry JSON file.")
    decide_parser.add_argument(
        "--decision-suite",
        type=Path,
        help="Path to a reusable FURYOKU decision suite JSON file.",
    )
    decide_parser.add_argument(
        "--task-profile",
        action="append",
        default=[],
        type=Path,
        help="Optional task profile to include. Repeat for multiple situations. Defaults to built-in scenarios.",
    )
    decide_parser.add_argument(
        "--check-health",
        action="store_true",
        help="Run provider readiness checks before deciding, and demote not-ready endpoints.",
    )
    decide_parser.add_argument("--health-probe", action="store_true", help="Run lightweight provider probes with --check-health.")
    decide_parser.add_argument("--health-probe-prompt", default="", help="Prompt text used when --health-probe is set.")
    decide_parser.add_argument("--health-timeout-seconds", type=float, default=5.0, help="Health probe timeout in seconds.")
    decide_parser.add_argument(
        "--feedback-log",
        type=Path,
        help="Optional JSONL outcome feedback log used to adjust eligible model rankings.",
    )
    _add_feedback_policy_arg(decide_parser)
    _add_routing_policy_arg(decide_parser)
    decide_parser.add_argument("--output", type=Path, help="Optional path to persist the JSON decision report.")
    feedback_parser = subparsers.add_parser(
        "feedback",
        help="Append an outcome feedback record linked to a persisted decision or execution report.",
    )
    feedback_parser.add_argument("--report", required=True, type=Path, help="Path to a persisted FURYOKU report JSON file.")
    feedback_parser.add_argument(
        "--feedback-log",
        required=True,
        type=Path,
        help="JSONL file where feedback records should be appended.",
    )
    feedback_parser.add_argument(
        "--verdict",
        required=True,
        choices=VALID_OUTCOME_VERDICTS,
        help="Outcome verdict for the selected decision/execution.",
    )
    feedback_parser.add_argument("--score", type=float, default=None, help="Optional normalized quality score from 0.0 to 1.0.")
    feedback_parser.add_argument("--reason", default="", help="Short reason or operator note for this outcome.")
    feedback_parser.add_argument("--tag", action="append", default=[], help="Optional feedback tag. Repeat for multiple tags.")
    feedback_parser.add_argument("--override-model-id", help="Model id that should have been used when verdict is manual_override.")
    character_parser = subparsers.add_parser(
        "character-select",
        help="Select concrete model endpoints for every role in a CHARACTER profile.",
    )
    character_parser.add_argument("--registry", required=True, type=Path, help="Path to a FURYOKU model registry JSON file.")
    character_parser.add_argument(
        "--character-profile",
        required=True,
        type=Path,
        help="Path to a FURYOKU CHARACTER composition profile JSON file.",
    )
    character_parser.add_argument(
        "--no-reuse",
        action="store_true",
        help="Require each CHARACTER role to use a distinct registered model.",
    )
    character_parser.add_argument("--output", type=Path, help="Optional path to persist the JSON CHARACTER envelope.")
    _add_health_decision_args(character_parser, "Run provider readiness checks before assigning CHARACTER roles.")
    character_run_parser = subparsers.add_parser(
        "character-run",
        help="Select CHARACTER role assignments and execute one role.",
    )
    character_run_parser.add_argument("--registry", required=True, type=Path, help="Path to a FURYOKU model registry JSON file.")
    character_run_parser.add_argument(
        "--character-profile",
        required=True,
        type=Path,
        help="Path to a FURYOKU CHARACTER composition profile JSON file.",
    )
    character_run_parser.add_argument("--prompt", required=True, help="Prompt text passed to the selected CHARACTER role model.")
    character_run_parser.add_argument(
        "--role-id",
        help="CHARACTER role id to execute. Defaults to the profile's effective primary role.",
    )
    character_run_parser.add_argument("--timeout-seconds", type=float, default=60.0, help="Execution timeout in seconds.")
    character_run_parser.add_argument(
        "--no-reuse",
        action="store_true",
        help="Require each CHARACTER role to use a distinct registered model.",
    )
    character_run_parser.add_argument("--output", type=Path, help="Optional path to persist the JSON CHARACTER execution report.")
    _add_health_decision_args(character_run_parser, "Run provider readiness checks before assigning and executing a CHARACTER role.")
    return parser


def _add_health_decision_args(parser: argparse.ArgumentParser, help_text: str) -> None:
    parser.add_argument("--check-health", action="store_true", help=help_text)
    parser.add_argument("--health-probe", action="store_true", help="Run lightweight provider probes with --check-health.")
    parser.add_argument("--health-probe-prompt", default="", help="Prompt text used when --health-probe is set.")
    parser.add_argument("--health-timeout-seconds", type=float, default=5.0, help="Health probe timeout in seconds.")


def _add_feedback_policy_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--feedback-policy",
        type=Path,
        help="Optional JSON feedback adjustment policy used with --feedback-log.",
    )


def _add_routing_policy_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--routing-policy",
        type=Path,
        help="Optional JSON routing score policy profile for baseline model selection.",
    )


def _add_common_task_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--registry", required=True, type=Path, help="Path to a FURYOKU model registry JSON file.")
    parser.add_argument("--task-profile", type=Path, help="Path to a reusable FURYOKU task profile JSON file.")
    parser.add_argument("--task-id", help="Task identifier for routing evidence.")
    parser.add_argument(
        "--capability",
        action="append",
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


def _task_from_args(args: argparse.Namespace, parser: argparse.ArgumentParser) -> TaskProfile:
    if args.task_profile:
        profile = load_task_profile(args.task_profile)
        if not args.capability and not args.task_id:
            return profile
        return TaskProfile(
            task_id=args.task_id or profile.task_id,
            description=args.description or profile.description,
            required_capabilities=_parse_capabilities(args.capability) if args.capability else profile.required_capabilities,
            min_context_tokens=args.min_context_tokens or profile.min_context_tokens,
            privacy_requirement=args.privacy if args.privacy != "allow_remote" else profile.privacy_requirement,
            max_input_cost_per_1k=args.max_input_cost_per_1k
            if args.max_input_cost_per_1k is not None
            else profile.max_input_cost_per_1k,
            max_output_cost_per_1k=args.max_output_cost_per_1k
            if args.max_output_cost_per_1k is not None
            else profile.max_output_cost_per_1k,
            require_tools=args.require_tools or profile.require_tools,
            require_json=args.require_json or profile.require_json,
            preferred_providers=tuple(args.preferred_provider) or profile.preferred_providers,
        )

    if not args.task_id:
        parser.error("--task-id is required unless --task-profile is provided")
    if not args.capability:
        parser.error("--capability is required unless --task-profile is provided")
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


def _select_with_optional_feedback(
    models,
    task: TaskProfile,
    feedback,
    *,
    feedback_policy=None,
    readiness=None,
    routing_policy=None,
):
    if feedback is None and readiness is None and routing_policy is None:
        return select_model(models, task), None
    report = evaluate_model_decisions(
        models,
        [task],
        readiness=readiness,
        feedback=feedback,
        feedback_policy=feedback_policy,
        routing_policy=routing_policy,
    )
    selection = report.selected_for(task.task_id)
    if selection is None:
        decision = report.situations[task.task_id]
        blocker_summary = "; ".join(
            f"{model_id}: {', '.join(blockers)}"
            for model_id, blockers in decision.blockers.items()
        )
        raise RouterError(f"No eligible model for task '{task.task_id}'. {blocker_summary}")
    return selection, report


def _feedback_from_args(args: argparse.Namespace, parser: argparse.ArgumentParser):
    feedback_log = getattr(args, "feedback_log", None)
    feedback_policy_path = getattr(args, "feedback_policy", None)
    if not feedback_log:
        if feedback_policy_path:
            parser.error("--feedback-policy requires --feedback-log")
        return None, None
    return (
        load_decision_outcomes(feedback_log),
        load_feedback_adjustment_policy(feedback_policy_path) if feedback_policy_path else None,
    )


def _routing_policy_from_args(args: argparse.Namespace):
    routing_policy_path = getattr(args, "routing_policy", None)
    if not routing_policy_path:
        return None
    return load_routing_score_policy(routing_policy_path)


def _readiness_from_args(args: argparse.Namespace, models):
    if not getattr(args, "check_health", False):
        return None
    return check_provider_health_many(
        models,
        ProviderHealthCheckRequest(
            probe=args.health_probe,
            probe_prompt=args.health_probe_prompt,
            timeout_seconds=args.health_timeout_seconds,
        ),
    )


def _score_to_dict(selection: ModelScore) -> dict:
    return {
        "modelId": selection.model.model_id,
        "provider": selection.model.provider,
        "score": selection.score,
        "eligible": selection.eligible,
        "reasons": list(selection.reasons),
        "blockers": list(selection.blockers),
    }


def _single_selection_to_dict(
    selection: ModelScore,
    *,
    report: ModelDecisionReport | None = None,
    readiness=None,
) -> dict:
    payload = _score_to_dict(selection)
    if report is not None:
        _add_optional_feedback_metadata(payload, report)
        _add_routing_policy_metadata(payload, report)
    if readiness is not None:
        payload["readiness"] = [_health_to_dict(result) for result in readiness]
    return payload


def _routed_result_to_dict(result: RoutedExecutionResult, *, readiness=None) -> dict:
    payload = {
        "ok": result.ok,
        "selection": _score_to_dict(result.selection),
        "execution": _execution_to_dict(result.execution),
    }
    if result.report is not None:
        _add_optional_feedback_metadata(payload, result.report)
        _add_routing_policy_metadata(payload, result.report)
    if readiness is not None:
        payload["readiness"] = [_health_to_dict(result) for result in readiness]
    return payload


def _decision_execution_result_to_dict(result: DecisionSituationExecutionResult, *, readiness=None) -> dict:
    payload = {
        "ok": result.ok,
        "situationId": result.situation_id,
        "selectedModel": _score_to_dict(result.selection) if result.selection else None,
        "decision": result.decision.to_dict(),
        "execution": _execution_to_dict(result.execution) if result.execution else None,
        "aggregate": result.report.aggregate.to_dict(),
        "feedbackAdjustments": _feedback_adjustments_to_dict(result.report),
    }
    _add_feedback_policy_metadata(payload, result.report)
    _add_routing_policy_metadata(payload, result.report)
    if readiness is not None:
        payload["readiness"] = [_health_to_dict(result) for result in readiness]
    return payload


def _decision_report_to_dict(report: ModelDecisionReport, *, readiness=None) -> dict:
    payload = {
        "ok": not report.blocked_tasks,
        "blockedTasks": list(report.blocked_tasks),
        "decisions": [
            {
                "taskId": decision.task.task_id,
                "description": decision.task.description,
                "weight": decision.weight,
                "minimumScore": decision.minimum_score,
                "selectedModel": _score_to_dict(decision.selected) if decision.selected else None,
                "rankedModels": [_score_to_dict(score) for score in decision.ranked],
            }
            for decision in report.decisions
        ],
        "summaries": [
            {
                "modelId": summary.model_id,
                "provider": summary.provider,
                "selectedCount": summary.selected_count,
                "eligibleCount": summary.eligible_count,
                "averageScore": summary.average_score,
                "blockedCount": summary.blocked_count,
                "selectedWeight": summary.selected_weight,
                "eligibleWeight": summary.eligible_weight,
                "weightedAverageScore": summary.weighted_average_score,
            }
            for summary in report.summaries
        ],
        "aggregate": report.aggregate.to_dict(),
        "feedbackAdjustments": _feedback_adjustments_to_dict(report),
    }
    _add_feedback_policy_metadata(payload, report)
    _add_routing_policy_metadata(payload, report)
    if readiness is not None:
        payload["readiness"] = [_health_to_dict(result) for result in readiness]
    return payload


def _character_role_result_to_dict(result: CharacterRoleExecutionResult) -> dict:
    return {
        "ok": result.ok,
        "characterId": result.character_id,
        "executedRoleId": result.role_id,
        "selectedModel": _score_to_dict(result.selection),
        "execution": _execution_to_dict(result.execution),
        "roleAssignments": _character_profile_selection_to_dict(result.character_selection),
    }


def _execution_to_dict(execution: ProviderExecutionResult) -> dict:
    return {
        "modelId": execution.model_id,
        "provider": execution.provider,
        "status": execution.status,
        "responseText": execution.response_text,
        "elapsedMs": execution.elapsed_ms,
        "exitCode": execution.exit_code,
        "stderr": execution.stderr,
        "error": execution.error,
        "timedOut": execution.timed_out,
    }


def _character_profile_selection_to_dict(selection: CharacterProfileSelection) -> dict:
    return build_character_orchestration_envelope(selection).to_dict()


def _feedback_adjustments_to_dict(report: ModelDecisionReport) -> dict:
    return {
        model_id: summary.to_dict()
        for model_id, summary in report.feedback_adjustments.items()
    }


def _add_optional_feedback_metadata(payload: dict, report: ModelDecisionReport) -> None:
    if report.feedback_adjustments or report.feedback_policy_metadata is not None:
        payload["feedbackAdjustments"] = _feedback_adjustments_to_dict(report)
        _add_feedback_policy_metadata(payload, report)


def _add_feedback_policy_metadata(payload: dict, report: ModelDecisionReport) -> None:
    if report.feedback_policy_metadata is not None:
        payload["feedbackPolicy"] = report.feedback_policy_metadata.to_dict()


def _add_routing_policy_metadata(payload: dict, report: ModelDecisionReport) -> None:
    if report.routing_policy_metadata is not None:
        payload["routingPolicy"] = report.routing_policy_metadata.to_dict()


def _health_to_dict(result: ProviderHealthCheckResult) -> dict:
    payload = {
        "modelId": result.model_id,
        "provider": result.provider,
        "status": result.status,
        "ready": result.ready,
        "reason": result.reason,
        "command": result.command,
        "resolvedCommand": result.resolved_command,
    }
    if result.execution is not None:
        payload["execution"] = {
            "status": result.execution.status,
            "elapsedMs": result.execution.elapsed_ms,
            "exitCode": result.execution.exit_code,
            "stderr": result.execution.stderr,
            "error": result.execution.error,
            "timedOut": result.execution.timed_out,
        }
    return payload


def _write_json(payload: dict, *, output_path: Path | None = None) -> None:
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        persisted_payload = {
            "reportMetadata": {
                "schemaVersion": 1,
                "generatedAt": datetime.now(timezone.utc).isoformat(),
            },
            **payload,
        }
        with output_path.open("w", encoding="utf-8") as handle:
            json.dump(persisted_payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
    json.dump(payload, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    raise SystemExit(main())
