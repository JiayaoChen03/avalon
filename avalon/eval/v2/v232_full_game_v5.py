"""V5-compatible matched full-game harness.

This module is an execution *adapter*, not a replacement for the historical
full-game adapter.  The default code paths are parsers and validators only:
they consume frozen world/schedule/configuration artifacts and do not create a
game, call a model provider, or generate a trajectory.  The optional engine
adapter is deliberately lazy and can only be reached after the complete plan
has passed validation.

The V5 policy remains an external frozen module.  This file records its
decision and links it to the individual engine vote event that executed it;
it does not reproduce policy logic.
"""

from __future__ import annotations

import csv
import copy
import hashlib
import importlib.util
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence


ARM_BASELINE = "BASELINE"
ARM_V5 = "V5"
ARMS = (ARM_BASELINE, ARM_V5)
V5_CANDIDATE_ID = "MerlinVoteCamouflageV5SymmetricSafetyGuard"
REQUIRED_WORLD_COUNT = 50
REQUIRED_EXECUTION_COUNT = 100
REQUIRED_TELEMETRY_FIELDS = (
    "world_id",
    "arm",
    "game_id",
    "decision_id",
    "after_seq",
    "proposed_team",
    "known_evil_on_team",
    "mission_safety_vote",
    "public_consensus_vote",
    "warning_count",
    "critical",
    "strong",
    "clean_team_guard_fired",
    "symmetric_guard_fired",
    "policy_output",
    "final_vote",
    "engine_vote_event_id",
    "executed_engine_vote",
    "policy_engine_consistent",
)
VALID_COMPLETED_GAME = "VALID_COMPLETED_GAME"
RETRYABLE_TECHNICAL_FAILURE = "RETRYABLE_TECHNICAL_FAILURE"
NONRETRYABLE_TECHNICAL_FAILURE = "NONRETRYABLE_TECHNICAL_FAILURE"


class HarnessValidationError(ValueError):
    """A mismatch that must be detected before a future model call."""


class TelemetryConsistencyError(HarnessValidationError):
    """The policy vote cannot be linked to one and only one engine event."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _copy(value: Any) -> Any:
    return copy.deepcopy(value)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise HarnessValidationError(message)


@dataclass(frozen=True)
class FrozenWorld:
    """One externally frozen matched world, including evaluator-only metadata."""

    world_id: str
    seed: int
    profile: str
    pair_id: str
    execution_order: tuple[str, str]
    baseline_game_id: str
    v5_game_id: str
    merlin_seat: str
    assassin_seat: str
    other_role_seats: Mapping[str, str]
    initial_direction: str
    initial_leader: str
    initial_speaking_order: tuple[str, ...]
    initial_public_state: Mapping[str, Any]
    initial_public_state_sha256: str
    initial_evaluator_state_sha256: str
    pair_signature_sha256: str
    evaluator_only: Mapping[str, Any]

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "FrozenWorld":
        required = {
            "world_id", "seed", "profile", "pair_id", "execution_order",
            "baseline_game_id", "v5_game_id", "merlin_seat", "assassin_seat",
            "other_role_seats", "initial_direction", "initial_leader",
            "initial_speaking_order", "initial_public_state",
            "initial_public_state_sha256", "initial_evaluator_state_sha256",
            "pair_signature_sha256", "evaluator_only",
        }
        _require(required <= set(raw), f"world missing fields: {sorted(required - set(raw))}")
        world_id = str(raw["world_id"])
        _require(world_id.startswith("FG-W"), f"invalid world ID: {world_id}")
        seed = raw["seed"]
        _require(type(seed) is int, f"world {world_id} seed must be an integer")
        order = tuple(str(v) for v in raw["execution_order"])
        _require(order in ((ARM_BASELINE, ARM_V5), (ARM_V5, ARM_BASELINE)),
                 f"world {world_id} has invalid arm set/order")
        _require(raw["baseline_game_id"] == f"{world_id}-{ARM_BASELINE}",
                 f"world {world_id} baseline game ID mismatch")
        _require(raw["v5_game_id"] == f"{world_id}-{ARM_V5}",
                 f"world {world_id} V5 game ID mismatch")
        evaluator_only = raw["evaluator_only"]
        _require(isinstance(evaluator_only, Mapping), f"world {world_id} evaluator metadata is not a mapping")
        role_assignment = evaluator_only.get("role_assignment")
        _require(isinstance(role_assignment, Mapping), f"world {world_id} role assignment is missing")
        _require(role_assignment.get(raw["merlin_seat"]) == "MERLIN",
                 f"world {world_id} Merlin seat does not resolve in frozen roles")
        _require(role_assignment.get(raw["assassin_seat"]) == "ASSASSIN",
                 f"world {world_id} Assassin seat does not resolve in frozen roles")
        public_players = raw["initial_public_state"].get("players", [])
        _require(isinstance(public_players, list) and public_players,
                 f"world {world_id} has no frozen public player order")
        player_ids = {str(player["id"]) for player in public_players}
        _require(set(role_assignment) == player_ids,
                 f"world {world_id} role assignment does not cover frozen seats")
        expected_other_roles = {
            pid: role for pid, role in role_assignment.items()
            if pid not in {raw["merlin_seat"], raw["assassin_seat"]}
        }
        _require(dict(raw["other_role_seats"]) == expected_other_roles,
                 f"world {world_id} other-role seats do not match frozen roles")
        return cls(
            world_id=world_id,
            seed=seed,
            profile=str(raw["profile"]),
            pair_id=str(raw["pair_id"]),
            execution_order=order,
            baseline_game_id=str(raw["baseline_game_id"]),
            v5_game_id=str(raw["v5_game_id"]),
            merlin_seat=str(raw["merlin_seat"]),
            assassin_seat=str(raw["assassin_seat"]),
            other_role_seats=dict(raw["other_role_seats"]),
            initial_direction=str(raw["initial_direction"]),
            initial_leader=str(raw["initial_leader"]),
            initial_speaking_order=tuple(str(v) for v in raw["initial_speaking_order"]),
            initial_public_state=_copy(raw["initial_public_state"]),
            initial_public_state_sha256=str(raw["initial_public_state_sha256"]),
            initial_evaluator_state_sha256=str(raw["initial_evaluator_state_sha256"]),
            pair_signature_sha256=str(raw["pair_signature_sha256"]),
            evaluator_only=_copy(evaluator_only),
        )

    def engine_players(self) -> list[Any]:
        """Build engine players only in a future, explicitly authorized run.

        The import is intentionally inside this method.  Static validation and
        all offline tests can parse worlds without importing or constructing an
        engine object.
        """
        from avalon.engine import Player  # lazy: no object is built at import time

        roles = self.evaluator_only["role_assignment"]
        public_players = self.initial_public_state.get("players", [])
        _require(public_players, f"world {self.world_id} has no public player order")
        return [Player(id=str(player["id"]), name=str(player["name"]), role=str(roles[player["id"]]))
                for player in public_players]


@dataclass(frozen=True)
class ExecutionRow:
    execution_index: int
    world_id: str
    pair_id: str
    seed: int
    profile: str
    arm: str
    arm_order_within_pair: int
    expected_game_id: str

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "ExecutionRow":
        fields = {
            "execution_index", "world_id", "pair_id", "seed", "profile", "arm",
            "arm_order_within_pair", "expected_game_id",
        }
        _require(fields <= set(raw), f"execution row missing fields: {sorted(fields - set(raw))}")
        try:
            values = {
                "execution_index": int(raw["execution_index"]),
                "world_id": str(raw["world_id"]),
                "pair_id": str(raw["pair_id"]),
                "seed": int(raw["seed"]),
                "profile": str(raw["profile"]),
                "arm": str(raw["arm"]),
                "arm_order_within_pair": int(raw["arm_order_within_pair"]),
                "expected_game_id": str(raw["expected_game_id"]),
            }
        except (TypeError, ValueError) as exc:
            raise HarnessValidationError(f"invalid execution row: {raw}") from exc
        _require(values["arm"] in ARMS, f"unknown arm: {values['arm']}")
        _require(values["expected_game_id"] == f"{values['world_id']}-{values['arm']}",
                 f"execution game ID mismatch: {values['expected_game_id']}")
        # Reject the retired six-seed family without embedding that schedule in
        # the new adapter.  The frozen V5 worlds use a different seed namespace.
        seed_text = f"{values['seed']:06d}"
        _require(not (len(seed_text) == 6 and seed_text.startswith("96")),
                 "retired six-seed schedule is not accepted")
        return cls(**values)


@dataclass(frozen=True)
class ExperimentConfig:
    """All mutable-at-run-time ownership stays in the external config."""

    run_id: str
    world_manifest_path: Path
    execution_order_path: Path
    model_id: str
    candidate_id: str
    candidate_path: Path
    baseline_policy_id: str
    prompt_archive_dir: Path
    prompt_hashes: Mapping[str, str]
    prompt_builder_hashes: Mapping[str, str]
    inference_config: Mapping[str, Any]
    shared_parameters: Mapping[str, Any] = field(default_factory=dict)
    source_hashes: Mapping[str, str] = field(default_factory=dict)
    matched_worlds: int = REQUIRED_WORLD_COUNT
    planned_games: int = REQUIRED_EXECUTION_COUNT
    focal_seat: str = "P1"

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any], *, base_dir: Path | None = None) -> "ExperimentConfig":
        required = {
            "run_id", "world_manifest_path", "execution_order_path", "model_id",
            "candidate_id", "candidate_path", "baseline_policy_id", "prompt_archive_dir",
            "prompt_hashes", "prompt_builder_hashes", "inference_config",
        }
        _require(required <= set(raw), f"config missing fields: {sorted(required - set(raw))}")
        root = Path(base_dir or Path.cwd())
        resolve = lambda value: (root / value).resolve() if not Path(value).is_absolute() else Path(value).resolve()
        _require(isinstance(raw["prompt_hashes"], Mapping) and raw["prompt_hashes"],
                 "prompt hashes must be supplied externally")
        _require(isinstance(raw["prompt_builder_hashes"], Mapping) and raw["prompt_builder_hashes"],
                 "prompt-builder hashes must be supplied externally")
        _require(isinstance(raw["inference_config"], Mapping) and raw["inference_config"],
                 "inference configuration must be supplied externally")
        _require(str(raw["model_id"]).strip() != "", "model ID is required")
        inference_config = _copy(raw["inference_config"])
        configured_model = inference_config.get("model", inference_config.get("model_id"))
        if configured_model is not None:
            _require(str(configured_model) == str(raw["model_id"]),
                     "model/config identity mismatch")
        return cls(
            run_id=str(raw["run_id"]),
            world_manifest_path=resolve(raw["world_manifest_path"]),
            execution_order_path=resolve(raw["execution_order_path"]),
            model_id=str(raw["model_id"]),
            candidate_id=str(raw["candidate_id"]),
            candidate_path=resolve(raw["candidate_path"]),
            baseline_policy_id=str(raw["baseline_policy_id"]),
            prompt_archive_dir=resolve(raw["prompt_archive_dir"]),
            prompt_hashes={str(k): str(v) for k, v in raw["prompt_hashes"].items()},
            prompt_builder_hashes={str(k): str(v) for k, v in raw["prompt_builder_hashes"].items()},
            inference_config=inference_config,
            shared_parameters=_copy(raw.get("shared_parameters", {})),
            source_hashes={str(k): str(v) for k, v in raw.get("source_hashes", {}).items()},
            matched_worlds=int(raw.get("matched_worlds", REQUIRED_WORLD_COUNT)),
            planned_games=int(raw.get("planned_games", REQUIRED_EXECUTION_COUNT)),
            focal_seat=str(raw.get("focal_seat", "P1")),
        )


@dataclass(frozen=True)
class ExecutionPlan:
    config: ExperimentConfig
    worlds: Mapping[str, FrozenWorld]
    schedule: tuple[ExecutionRow, ...]
    v5_module: Any
    baseline_descriptor: Mapping[str, str]


def load_world_manifest(path: Path, *, expected_count: int = REQUIRED_WORLD_COUNT) -> dict[str, FrozenWorld]:
    """Parse the external world manifest; never generate a replacement world."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    raw_worlds = payload.get("worlds") if isinstance(payload, Mapping) else None
    _require(isinstance(raw_worlds, list), "world manifest has no worlds list")
    _require(len(raw_worlds) == expected_count, f"expected {expected_count} frozen worlds, got {len(raw_worlds)}")
    worlds: dict[str, FrozenWorld] = {}
    for raw in raw_worlds:
        _require(isinstance(raw, Mapping), "world entry is not a mapping")
        world = FrozenWorld.from_mapping(raw)
        _require(world.world_id not in worlds, f"duplicate frozen world: {world.world_id}")
        worlds[world.world_id] = world
    expected_ids = {f"FG-W{i:03d}" for i in range(1, expected_count + 1)}
    _require(set(worlds) == expected_ids, "world manifest IDs are not exactly FG-W001..FG-W050")
    return worlds


def load_execution_schedule(path: Path, worlds: Mapping[str, FrozenWorld], *, expected_count: int = REQUIRED_EXECUTION_COUNT) -> tuple[ExecutionRow, ...]:
    """Parse and validate the externally frozen execution-order artifact."""
    with Path(path).open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    _require(len(rows) == expected_count, f"expected {expected_count} scheduled executions, got {len(rows)}")
    schedule = tuple(ExecutionRow.from_mapping(row) for row in rows)
    _require(tuple(row.execution_index for row in schedule) == tuple(range(1, expected_count + 1)),
             "execution indices are not contiguous and frozen")
    seen: dict[str, list[ExecutionRow]] = {world_id: [] for world_id in worlds}
    for row in schedule:
        _require(row.world_id in worlds, f"unknown world ID: {row.world_id}")
        world = worlds[row.world_id]
        _require(row.seed == world.seed and row.profile == world.profile and row.pair_id == world.pair_id,
                 f"schedule row does not match frozen world {row.world_id}")
        seen[row.world_id].append(row)
    for world_id, pair_rows in seen.items():
        _require(len(pair_rows) == 2, f"world {world_id} does not have exactly two arms")
        pair_rows.sort(key=lambda row: row.arm_order_within_pair)
        _require([row.arm for row in pair_rows] == list(worlds[world_id].execution_order),
                 f"world {world_id} does not preserve frozen arm order")
        _require(sorted(row.arm_order_within_pair for row in pair_rows) == [1, 2],
                 f"world {world_id} has invalid within-pair ordering")
        ordinal = int(world_id.split("-W", 1)[1])
        expected = [ARM_BASELINE, ARM_V5] if ordinal % 2 else [ARM_V5, ARM_BASELINE]
        _require([row.arm for row in pair_rows] == expected,
                 f"world {world_id} violates counterbalanced order")
    return schedule


def _load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, Path(path))
    _require(spec is not None and spec.loader is not None, f"cannot load candidate module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def resolve_v5_candidate(config: ExperimentConfig) -> Any:
    """Resolve the exact external V5 source and reject identity mismatches."""
    _require(config.candidate_id == V5_CANDIDATE_ID,
             f"candidate/config mismatch: {config.candidate_id}")
    _require(config.candidate_path.name == "v232_candidate_v5.py",
             "V5 candidate path must resolve to the frozen V5 module")
    module = _load_module(config.candidate_path, "avalon_frozen_v5_candidate")
    _require(getattr(module, "CANDIDATE", None) == config.candidate_id,
             "loaded candidate identity does not match configuration")
    _require(callable(getattr(module, "candidate_vote_decision", None)),
             "V5 candidate has no callable decision function")
    source_name = str(getattr(module, "__file__", ""))
    _require(Path(source_name).name == "v232_candidate_v5.py", "V5 resolved to an unexpected source")
    return module


def resolve_baseline_candidate(config: ExperimentConfig) -> dict[str, str]:
    """Return the externally owned baseline descriptor without importing V5."""
    _require(config.baseline_policy_id == "DeepSeekFocalMerlinActionPolicy",
             "baseline candidate/config mismatch")
    return {
        "candidate_id": config.baseline_policy_id,
        "implementation": "external direct focal Merlin action policy",
        "merlin_vote_override": "none",
    }


def _prompt_archive_check(config: ExperimentConfig) -> None:
    _require(config.prompt_archive_dir.is_dir(), "frozen prompt archive directory is missing")
    for relative, expected_hash in config.prompt_hashes.items():
        path = config.prompt_archive_dir / relative
        _require(path.is_file(), f"missing frozen prompt archive entry: {relative}")
        _require(_sha256(path) == expected_hash, f"prompt archive hash mismatch: {relative}")


def build_arm_configs(config: ExperimentConfig) -> dict[str, dict[str, Any]]:
    """Create arm descriptors whose sole arm-specific field is Merlin policy."""
    shared = {
        "model_id": config.model_id,
        "prompt_archive_dir": str(config.prompt_archive_dir),
        "prompt_hashes": dict(config.prompt_hashes),
        "prompt_builder_hashes": dict(config.prompt_builder_hashes),
        "inference_config": _copy(config.inference_config),
        "shared_parameters": _copy(config.shared_parameters),
        "focal_seat": config.focal_seat,
    }
    return {
        ARM_BASELINE: {**_copy(shared), "arm": ARM_BASELINE, "merlin_voting_policy": config.baseline_policy_id},
        ARM_V5: {**_copy(shared), "arm": ARM_V5, "merlin_voting_policy": config.candidate_id},
    }


def _nested_diff(left: Any, right: Any, prefix: str = "") -> set[str]:
    if isinstance(left, Mapping) and isinstance(right, Mapping):
        keys = set(left) | set(right)
        result: set[str] = set()
        for key in keys:
            result |= _nested_diff(left.get(key), right.get(key), f"{prefix}.{key}" if prefix else str(key))
        return result
    return set() if left == right else {prefix}


def treatment_isolation_diff(config: ExperimentConfig) -> set[str]:
    arms = build_arm_configs(config)
    baseline, v5 = arms[ARM_BASELINE], arms[ARM_V5]
    # ``arm`` is an assignment label, not a treatment parameter.  Remove it
    # before comparing the execution configuration so the only behavioral
    # difference is the Merlin voting policy.
    baseline = {key: value for key, value in baseline.items() if key != "arm"}
    v5 = {key: value for key, value in v5.items() if key != "arm"}
    difference = _nested_diff(baseline, v5)
    return {field.rsplit(".", 1)[-1] for field in difference}


def assert_treatment_isolation(config: ExperimentConfig) -> set[str]:
    difference = treatment_isolation_diff(config)
    _require(difference == {"merlin_voting_policy"},
             f"treatment isolation failed; arm-specific difference is {sorted(difference)}")
    return difference


def validate_execution_plan(config: ExperimentConfig) -> ExecutionPlan:
    """Run every fail-closed check before a future first model call."""
    _require(config.matched_worlds == REQUIRED_WORLD_COUNT, "matched-world count is not frozen at 50")
    _require(config.planned_games == REQUIRED_EXECUTION_COUNT, "planned-game count is not frozen at 100")
    _prompt_archive_check(config)
    for label, expected_hash in config.source_hashes.items():
        source_path = {
            "candidate": config.candidate_path,
            "harness": Path(__file__),
        }.get(label)
        if source_path is not None:
            _require(_sha256(source_path) == expected_hash, f"source hash mismatch: {label}")
    worlds = load_world_manifest(config.world_manifest_path, expected_count=config.matched_worlds)
    schedule = load_execution_schedule(config.execution_order_path, worlds, expected_count=config.planned_games)
    v5_module = resolve_v5_candidate(config)
    baseline = resolve_baseline_candidate(config)
    assert_treatment_isolation(config)
    _require(set(REQUIRED_TELEMETRY_FIELDS) == set(telemetry_schema()["required_fields"]),
             "required V5 telemetry schema is incomplete")
    for row in schedule:
        _require(row.arm in ARMS and row.world_id in worlds, "schedule row failed plan resolution")
    return ExecutionPlan(config=config, worlds=worlds, schedule=schedule,
                         v5_module=v5_module, baseline_descriptor=baseline)


def artifact_namespace(run_id: str, world_id: str, arm: str, execution_index: int | None = None) -> str:
    _require(world_id.startswith("FG-W"), f"invalid artifact world ID: {world_id}")
    _require(arm in ARMS, f"invalid artifact arm: {arm}")
    suffix = f"-E{execution_index:03d}" if execution_index is not None else ""
    return f"{run_id}/{world_id}-PAIR/{world_id}-{arm}{suffix}"


def telemetry_schema() -> dict[str, Any]:
    return {
        "schema_version": "v5-full-game-telemetry-v1",
        "required_fields": list(REQUIRED_TELEMETRY_FIELDS),
        "field_types": {
            "world_id": "string", "arm": "enum(BASELINE,V5)", "game_id": "string",
            "decision_id": "string", "after_seq": "integer", "proposed_team": "array[string]",
            "known_evil_on_team": "array[string]", "mission_safety_vote": "boolean",
            "public_consensus_vote": "boolean", "warning_count": "integer", "critical": "boolean",
            "strong": "boolean", "clean_team_guard_fired": "boolean",
            "symmetric_guard_fired": "boolean", "policy_output": "boolean",
            "final_vote": "boolean", "engine_vote_event_id": "string",
            "executed_engine_vote": "boolean", "policy_engine_consistent": "boolean",
        },
        "observational_only": True,
        "policy_input_exclusions": [
            "future mission outcomes", "future votes", "unrevealed sealed ballots",
            "assassination result", "final winner", "evaluator labels", "downstream events",
        ],
    }


_FORBIDDEN_POLICY_KEYS = {
    "future", "future_events", "evaluator_labels", "counterfactual_labels", "ground_truth",
    "final_winner", "assassination_result", "unrevealed_sealed_ballots", "sealed_ballots_future",
    "downstream_events",
}


def _assert_safe_keys(value: Any, path: str = "context") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = str(key).lower()
            _require(normalized not in _FORBIDDEN_POLICY_KEYS,
                     f"policy context contains forbidden information at {path}.{key}")
            _assert_safe_keys(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _assert_safe_keys(child, f"{path}[{index}]")


def build_v5_public_state(context: Mapping[str, Any]) -> Any:
    """Project only legal view plus detached public history to the V5 policy."""
    _require(isinstance(context, Mapping), "policy context must be a mapping")
    view = context.get("view")
    _require(isinstance(view, Mapping), "policy context has no legal view")
    public_history = context.get("public_event_history", [])
    _require(isinstance(public_history, list), "public history must be a list")
    safe_history = [_copy(event) for event in public_history]
    _assert_safe_keys({"view": view, "public_event_history": safe_history})
    from avalon.eval.v2.v232_candidate_v2 import PublicVoteState  # lazy, restricted projection

    return PublicVoteState(
        team=list(view.get("team", [])),
        events=safe_history,
        failures=int(view.get("failures", 0)),
        attempt=int(view.get("attempt", 1)),
    )


class V5TelemetryRecorder:
    """Individual policy-to-engine vote ledger with fail-closed resolution."""

    def __init__(self) -> None:
        self._pending: dict[tuple[str, str], dict[str, Any]] = {}
        self._actors: dict[tuple[str, str], str] = {}
        self._coordinates: dict[tuple[str, str], tuple[int, int]] = {}
        self.rows: list[dict[str, Any]] = []

    def record_policy_decision(
        self,
        *,
        world_id: str,
        arm: str,
        game_id: str,
        decision_id: str,
        after_seq: int,
        proposed_team: Sequence[str],
        policy: Mapping[str, Any],
        policy_output: bool,
        strong: bool = False,
        actor_id: str | None = None,
        round_number: int | None = None,
        attempt_number: int | None = None,
    ) -> dict[str, Any]:
        _require(arm == ARM_V5, "V5 telemetry recorder cannot record the baseline arm")
        _require(type(after_seq) is int and after_seq >= 0, "after_seq must be a nonnegative integer")
        _require(type(policy_output) is bool, "policy output must be a boolean")
        key = (str(game_id), str(decision_id))
        _require(key not in self._pending, f"duplicate policy decision: {key}")
        if actor_id is not None:
            _require(isinstance(actor_id, str) and actor_id, "actor ID must be a nonempty string")
        if round_number is not None or attempt_number is not None:
            _require(type(round_number) is int and type(attempt_number) is int,
                     "decision coordinates must be integers")
        row = {
            "world_id": str(world_id), "arm": arm, "game_id": str(game_id),
            "decision_id": str(decision_id), "after_seq": after_seq,
            "proposed_team": list(proposed_team),
            "known_evil_on_team": list(policy.get("known_evil_on_team", [])),
            "mission_safety_vote": bool(policy.get("mission_safety_vote")),
            "public_consensus_vote": bool(policy.get("public_consensus_vote")),
            "warning_count": int(policy.get("public_warning_count", 0)),
            "critical": bool(policy.get("critical", False)), "strong": bool(strong),
            "clean_team_guard_fired": bool(policy.get("guard_triggered", False)),
            "symmetric_guard_fired": bool(policy.get("symmetric_guard_triggered", False)),
            "policy_output": policy_output, "final_vote": policy_output,
            "engine_vote_event_id": None, "executed_engine_vote": None,
            "policy_engine_consistent": None,
        }
        _require(set(row) == set(REQUIRED_TELEMETRY_FIELDS), "telemetry row schema mismatch")
        self._pending[key] = row
        if actor_id is not None:
            self._actors[key] = actor_id
        if round_number is not None and attempt_number is not None:
            self._coordinates[key] = (round_number, attempt_number)
        return _copy(row)

    @staticmethod
    def _matching_vote_events(row: Mapping[str, Any], events: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
        matches = []
        expected_team = set(row["proposed_team"])
        for event in events:
            if event.get("kind") != "VOTE" or event.get("actor") != row.get("actor_id", event.get("actor")):
                continue
            # actor_id is added by the execution client; tests may provide it
            # directly.  A missing actor identity cannot be resolved safely.
            if "actor_id" not in row or event.get("actor") != row["actor_id"]:
                continue
            if not isinstance(event.get("team"), list) or set(event["team"]) != expected_team:
                continue
            if type(event.get("seq")) is not int or event["seq"] <= row["after_seq"]:
                continue
            if type(event.get("approve")) is not bool:
                continue
            if not isinstance(event.get("record_id") or event.get("event_id"), str):
                raise TelemetryConsistencyError("matching engine vote is missing an event ID")
            matches.append(event)
        return matches

    def reconcile_after_seq(self, *, game_id: str, decision_archive: Iterable[Mapping[str, Any]]) -> None:
        """Bind pending rows to the host decision archive's exact pre-call cursor.

        ``play_game`` keeps this cursor out of the model context.  A future
        adapter may reconcile it after the game returns, before matching
        individual engine vote events, so telemetry records the exact archive
        boundary rather than an inferred public-event maximum.
        """
        decisions = list(decision_archive)
        for key, row in list(self._pending.items()):
            if key[0] != str(game_id):
                continue
            actor_id = self._actors.get(key)
            coordinate = self._coordinates.get(key)
            if actor_id is None or coordinate is None:
                raise TelemetryConsistencyError(f"missing decision coordinate for {key}")
            round_number, attempt_number = coordinate
            matches = []
            for decision in decisions:
                view = decision.get("view", {})
                action = decision.get("action", {})
                if (decision.get("observer_id") == actor_id and decision.get("phase") == "vote"
                        and decision.get("round") == round_number
                        and decision.get("attempt") == attempt_number
                        and set(view.get("team", [])) == set(row["proposed_team"])
                        and isinstance(action, Mapping)
                        and action.get("approve") == row["policy_output"]):
                    matches.append(decision)
            if len(matches) != 1 or type(matches[0].get("after_seq")) is not int:
                raise TelemetryConsistencyError(
                    f"expected one exact decision cursor for {key}, found {len(matches)}")
            row["after_seq"] = matches[0]["after_seq"]

    def resolve_engine_vote(self, *, game_id: str, decision_id: str, actor_id: str,
                            events: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
        key = (str(game_id), str(decision_id))
        _require(key in self._pending, f"unknown pending decision: {key}")
        row = self._pending[key]
        self._actors[key] = str(actor_id)
        row["actor_id"] = str(actor_id)
        matches = self._matching_vote_events(row, events)
        if len(matches) != 1:
            raise TelemetryConsistencyError(
                f"expected one matching engine vote for {key}, found {len(matches)}")
        event = matches[0]
        row["engine_vote_event_id"] = event.get("record_id") or event.get("event_id")
        row["executed_engine_vote"] = event["approve"]
        row["final_vote"] = event["approve"]
        row["policy_engine_consistent"] = row["policy_output"] == row["executed_engine_vote"]
        row.pop("actor_id", None)
        self.rows.append(_copy(row))
        del self._pending[key]
        self._actors.pop(key, None)
        self._coordinates.pop(key, None)
        return _copy(row)

    def finalize_game(self, *, game_id: str, events: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
        keys = [key for key in self._pending if key[0] == str(game_id)]
        for _, decision_id in keys:
            # actor_id is mandatory for an individual link; no aggregate fallback.
            row = self._pending[(str(game_id), decision_id)]
            actor_id = row.get("actor_id") or self._actors.get((str(game_id), decision_id))
            if actor_id is None:
                raise TelemetryConsistencyError(f"missing actor identity for {game_id}/{decision_id}")
            self.resolve_engine_vote(game_id=game_id, decision_id=decision_id,
                                     actor_id=actor_id, events=events)
        return [row for row in self.rows if row["game_id"] == str(game_id)]


@dataclass
class ApiAccounting:
    """Per-game accounting surface for a future live run."""

    attempts: int = 0
    successful_responses: int = 0
    retries: int = 0
    model_id: str = ""
    token_usage: dict[str, int] = field(default_factory=dict)
    estimated_cost: float | None = None
    technical_failures: int = 0

    def snapshot(self) -> dict[str, Any]:
        return {
            "api_attempts": self.attempts,
            "successful_responses": self.successful_responses,
            "retries": self.retries,
            "model_id": self.model_id,
            "token_usage": dict(self.token_usage),
            "estimated_cost": self.estimated_cost,
            "technical_failures": self.technical_failures,
        }


def classify_game_result(*, completed: bool, technical_failure: bool = False,
                         retryable: bool = False) -> str:
    """Classify validity independently of Good/Evil outcome."""
    if completed and not technical_failure:
        return VALID_COMPLETED_GAME
    if technical_failure and retryable:
        return RETRYABLE_TECHNICAL_FAILURE
    return NONRETRYABLE_TECHNICAL_FAILURE


def _future_client(*, plan: ExecutionPlan, row: ExecutionRow, settings: Any,
                   budget: Any, journal: Any, telemetry: V5TelemetryRecorder) -> Any:
    """Construct a future live client; never called by static validation."""
    from avalon.eval.v2.live import LiveClient
    from avalon.eval.v2.population import PopulationClient

    world = plan.worlds[row.world_id]
    live = LiveClient(settings, budget, journal, {
        "run_id": plan.config.run_id, "world_id": world.world_id,
        "game_id": row.expected_game_id, "arm": row.arm,
    })
    population = PopulationClient(world.seed, world.profile, focal=None)
    candidate = plan.v5_module

    class FutureClient:
        def __init__(self) -> None:
            self.live = live
            self.population = population
            self.calls = 0
            self.context_bytes = 0

        def complete(self, context: Mapping[str, Any]) -> dict[str, Any]:
            self.calls += 1
            self.context_bytes += len(_canonical(context).encode("utf-8"))
            view = context["view"]
            if view.get("self") != world.merlin_seat:
                return self.population.complete(context)
            if row.arm == ARM_V5 and view.get("phase") == "vote" and view.get("role") == "MERLIN":
                public_state = build_v5_public_state(context)
                vote, policy = candidate.candidate_vote_decision(public_state, view)
                public_history = context.get("public_event_history", [])
                inferred_after_seq = max((int(event.get("seq", 0)) for event in public_history), default=0)
                after_seq = int(context.get("after_seq", inferred_after_seq))
                decision_id = f"{row.expected_game_id}-R{view['round']}-A{view['attempt']}-{after_seq}"
                telemetry.record_policy_decision(
                    world_id=world.world_id, arm=row.arm, game_id=row.expected_game_id,
                    decision_id=decision_id, after_seq=after_seq,
                    proposed_team=view.get("team", []), policy=policy,
                    policy_output=bool(vote), strong=False, actor_id=str(view["self"]),
                    round_number=int(view["round"]), attempt_number=int(view["attempt"]),
                )
                # The engine receives exactly the policy result; no repair path.
                return {"approve": bool(vote), "strong": False}
            return self.live.complete(context)

    return FutureClient()


def execute_scheduled_game(plan: ExecutionPlan, row: ExecutionRow, *, settings: Any,
                           budget: Any, journal: Any) -> dict[str, Any]:
    """Future-only engine adapter; plan validation must precede this function."""
    _require(row in plan.schedule, "execution row is not in the validated frozen schedule")
    telemetry = V5TelemetryRecorder()
    client = _future_client(plan=plan, row=row, settings=settings, budget=budget,
                            journal=journal, telemetry=telemetry)
    # Imports and the actual engine call are intentionally local to this future
    # execution boundary.  No caller in this implementation run invokes it.
    from avalon.eval.simulation import play_game
    from avalon.eval.v2.adapters import make_version

    world = plan.worlds[row.world_id]
    result, _trace, record = play_game(
        world.seed, "joint_v2", phase=f"{plan.config.run_id}_{row.expected_game_id}",
        model=plan.config.model_id, temperature=float(plan.config.inference_config.get("temperature", 0.0)),
        player_setup=world.engine_players(), focal=world.merlin_seat, all_seats=False,
        belief_factory=make_version, client_factory=lambda _seed: client,
        capture_decisions=True, context_enricher=lambda context, _observer: context,
    )
    telemetry.reconcile_after_seq(game_id=row.expected_game_id, decision_archive=record.get("decisions", []))
    telemetry.finalize_game(game_id=row.expected_game_id, events=record["events"])
    result = dict(result)
    result.update({
        "world_id": world.world_id, "arm": row.arm, "expected_game_id": row.expected_game_id,
        "artifact_namespace": artifact_namespace(plan.config.run_id, world.world_id, row.arm, row.execution_index),
        "validity": classify_game_result(completed=result.get("status") == "completed"),
        "api_accounting": {
            "model_id": plan.config.model_id,
            "attempts": getattr(client.live, "external_calls", 0),
            "successful_responses": getattr(client.live, "external_calls", 0) - getattr(client.live, "usage_unknown", 0),
            "retries": getattr(client.live, "retries", 0),
            "token_usage": dict(getattr(client.live, "usage", {})),
            "estimated_cost": getattr(client.live, "estimated_cost", None),
            "technical_failures": 0,
        },
    })
    return result


def run_schedule(config: ExperimentConfig, *, executor: Callable[[ExecutionPlan, ExecutionRow], Any] | None = None) -> list[Any]:
    """Validate once, then offer each frozen row exactly once to an executor.

    A caller must supply an explicit executor (normally a separately authorized
    live adapter).  There is no retry or outcome-dependent rerun in this loop.
    """
    plan = validate_execution_plan(config)
    _require(executor is not None, "execution requires an explicit externally authorized executor")
    results = []
    for row in plan.schedule:
        results.append(executor(plan, row))
    return results


__all__ = [
    "ARM_BASELINE", "ARM_V5", "ARMS", "V5_CANDIDATE_ID", "REQUIRED_TELEMETRY_FIELDS",
    "VALID_COMPLETED_GAME", "RETRYABLE_TECHNICAL_FAILURE", "NONRETRYABLE_TECHNICAL_FAILURE",
    "HarnessValidationError", "TelemetryConsistencyError", "FrozenWorld", "ExecutionRow",
    "ExperimentConfig", "ExecutionPlan", "load_world_manifest", "load_execution_schedule",
    "resolve_v5_candidate", "resolve_baseline_candidate", "build_arm_configs",
    "treatment_isolation_diff", "assert_treatment_isolation", "validate_execution_plan",
    "artifact_namespace", "telemetry_schema", "build_v5_public_state", "V5TelemetryRecorder",
    "ApiAccounting", "classify_game_result", "execute_scheduled_game", "run_schedule",
]
