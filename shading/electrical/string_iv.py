"""Phase-6.7 general non-identical series-string IV assembly."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from typing import Any, Callable, Mapping

from .contract import (
    ElectricalShadingContractError,
    assert_electrical_iv_curve,
)


GENERAL_SERIES_STRING_IV_SOLVER_ID = (
    "rawibumi.phase67.general_series_string_iv.v0.1"
)

GENERAL_SERIES_STRING_IV_SOLVER_VERSION = "0.1"


class GeneralSeriesStringIVError(ValueError):
    """Raised when a general series string cannot be solved safely."""


@dataclass(frozen=True)
class SeriesModuleOperatingModel:
    """Runtime V(I) authority for one module in a series string.

    The object is intentionally an execution object, not a canonical
    persistence object. Its scientific identity is carried separately by
    scientific_input_sha256.

    voltage_at_current(current_a) must return:
        {
            "terminal_voltage_v": float,
            "protected_substrings": [
                {
                    "substring_id": str,
                    "terminal_voltage_v": float,
                    "bypass_active": bool,
                    "bypass_current_a": float
                },
                ...
            ]
        }

    Negative module terminal voltage is explicitly permitted. This is
    required for physically coherent mismatched series strings where a weak
    or bypassed module can be driven beyond its standalone Isc while the
    complete string remains in positive-power generation.
    """

    module_instance_id: str
    current_domain_ceiling_a: float
    scientific_input_sha256: str
    model_id: str
    model_version: str
    voltage_at_current: Callable[
        [float],
        Mapping[str, Any],
    ]


@dataclass(frozen=True)
class GeneralSeriesStringIVResult:
    curve: dict[str, Any]
    state: dict[str, Any]


def _canonical_sha256(
    value: Any,
) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")

    return hashlib.sha256(
        encoded
    ).hexdigest()


def _finite(
    value: Any,
    *,
    label: str,
) -> float:
    try:
        number = float(value)
    except (
        TypeError,
        ValueError,
    ) as exc:
        raise GeneralSeriesStringIVError(
            f"{label} must be finite"
        ) from exc

    if not math.isfinite(number):
        raise GeneralSeriesStringIVError(
            f"{label} must be finite"
        )

    return number


def _assert_sha256(
    value: Any,
    *,
    label: str,
) -> str:
    text = str(
        value or ""
    )

    if (
        len(text) != 64
        or any(
            char
            not in "0123456789abcdef"
            for char in text
        )
    ):
        raise GeneralSeriesStringIVError(
            f"{label} must be a lowercase SHA-256"
        )

    return text


def _validate_string_circuit(
    string_circuit: Mapping[str, Any],
) -> tuple[
    str,
    str,
    tuple[str, ...],
]:
    string_id = str(
        string_circuit.get(
            "string_id"
        )
        or ""
    )

    if not string_id:
        raise GeneralSeriesStringIVError(
            "StringCircuit.string_id "
            "must be non-empty"
        )

    project_revision_id = str(
        string_circuit.get(
            "project_revision_id"
        )
        or ""
    )

    if not project_revision_id:
        raise GeneralSeriesStringIVError(
            "StringCircuit.project_revision_id "
            "must be non-empty"
        )

    module_ids = tuple(
        str(value)
        for value
        in (
            string_circuit.get(
                "module_instance_ids"
            )
            or []
        )
    )

    if not module_ids:
        raise GeneralSeriesStringIVError(
            "StringCircuit.module_instance_ids "
            "must not be empty"
        )

    if len(module_ids) != len(
        set(module_ids)
    ):
        raise GeneralSeriesStringIVError(
            "StringCircuit.module_instance_ids "
            "must be unique"
        )

    polarity = string_circuit.get(
        "polarity"
    )

    if polarity != "normal":
        raise GeneralSeriesStringIVError(
            "Phase-6.7 general series solver "
            "requires polarity='normal'"
        )

    if (
        string_circuit.get(
            "enabled"
        )
        is not True
    ):
        raise GeneralSeriesStringIVError(
            "Phase-6.7 general series solver "
            "requires an enabled StringCircuit"
        )

    return (
        string_id,
        project_revision_id,
        module_ids,
    )


def _validate_module_models(
    module_ids: tuple[str, ...],
    module_models: Mapping[
        str,
        SeriesModuleOperatingModel,
    ],
) -> list[
    SeriesModuleOperatingModel
]:
    expected = set(
        module_ids
    )

    actual = {
        str(value)
        for value
        in module_models
    }

    if actual != expected:
        missing = sorted(
            expected - actual
        )

        extra = sorted(
            actual - expected
        )

        raise GeneralSeriesStringIVError(
            "module operating-model coverage "
            "must exactly match StringCircuit; "
            f"missing={missing}, extra={extra}"
        )

    ordered = []

    for module_id in module_ids:
        model = module_models[
            module_id
        ]

        if not isinstance(
            model,
            SeriesModuleOperatingModel,
        ):
            raise GeneralSeriesStringIVError(
                f"module {module_id} does not "
                "provide a SeriesModuleOperatingModel"
            )

        if (
            model.module_instance_id
            != module_id
        ):
            raise GeneralSeriesStringIVError(
                "module operating-model identity "
                f"mismatch for {module_id}"
            )

        ceiling = _finite(
            model.current_domain_ceiling_a,
            label=(
                f"{module_id}."
                "current_domain_ceiling_a"
            ),
        )

        if ceiling <= 0:
            raise GeneralSeriesStringIVError(
                f"module {module_id} current "
                "domain must be positive"
            )

        _assert_sha256(
            model.scientific_input_sha256,
            label=(
                f"{module_id}."
                "scientific_input_sha256"
            ),
        )

        if not model.model_id:
            raise GeneralSeriesStringIVError(
                f"module {module_id} "
                "model_id must be non-empty"
            )

        if not model.model_version:
            raise GeneralSeriesStringIVError(
                f"module {module_id} "
                "model_version must be non-empty"
            )

        if not callable(
            model.voltage_at_current
        ):
            raise GeneralSeriesStringIVError(
                f"module {module_id} "
                "requires voltage_at_current"
            )

        ordered.append(
            model
        )

    return ordered


def _normalize_protected_substrings(
    value: Any,
    *,
    module_id: str,
) -> list[dict[str, Any]]:
    if value is None:
        return []

    if not isinstance(
        value,
        (list, tuple),
    ):
        raise GeneralSeriesStringIVError(
            f"module {module_id} "
            "protected_substrings must be an array"
        )

    normalized = []

    seen = set()

    for raw in value:
        if not isinstance(
            raw,
            Mapping,
        ):
            raise GeneralSeriesStringIVError(
                f"module {module_id} "
                "protected substring must be an object"
            )

        substring_id = str(
            raw.get(
                "substring_id"
            )
            or ""
        )

        if not substring_id:
            raise GeneralSeriesStringIVError(
                f"module {module_id} protected "
                "substring_id must be non-empty"
            )

        if substring_id in seen:
            raise GeneralSeriesStringIVError(
                f"module {module_id} protected "
                "substring IDs must be unique"
            )

        seen.add(
            substring_id
        )

        voltage = _finite(
            raw.get(
                "terminal_voltage_v"
            ),
            label=(
                f"{module_id}."
                f"{substring_id}."
                "terminal_voltage_v"
            ),
        )

        bypass_current = _finite(
            raw.get(
                "bypass_current_a"
            ),
            label=(
                f"{module_id}."
                f"{substring_id}."
                "bypass_current_a"
            ),
        )

        if bypass_current < 0:
            raise GeneralSeriesStringIVError(
                f"module {module_id} "
                "bypass current cannot be negative"
            )

        bypass_active = raw.get(
            "bypass_active"
        )

        if not isinstance(
            bypass_active,
            bool,
        ):
            raise GeneralSeriesStringIVError(
                f"module {module_id} "
                "bypass_active must be boolean"
            )

        normalized.append(
            {
                "substring_id": (
                    substring_id
                ),
                "terminal_voltage_v": (
                    voltage
                ),
                "bypass_active": (
                    bypass_active
                ),
                "bypass_current_a": (
                    bypass_current
                ),
            }
        )

    return normalized


def _evaluate_module(
    model: SeriesModuleOperatingModel,
    current_a: float,
    *,
    current_tolerance_a: float,
) -> dict[str, Any]:
    current = _finite(
        current_a,
        label="module current_a",
    )

    if current < 0:
        raise GeneralSeriesStringIVError(
            "series current cannot be negative"
        )

    if (
        current
        > model.current_domain_ceiling_a
        + current_tolerance_a
    ):
        raise GeneralSeriesStringIVError(
            f"module {model.module_instance_id} "
            f"requested current {current} A "
            "exceeds supported current domain "
            f"{model.current_domain_ceiling_a} A"
        )

    try:
        raw = model.voltage_at_current(
            current
        )
    except Exception as exc:
        raise GeneralSeriesStringIVError(
            f"module {model.module_instance_id} "
            f"failed at {current} A: {exc}"
        ) from exc

    if not isinstance(
        raw,
        Mapping,
    ):
        raise GeneralSeriesStringIVError(
            f"module {model.module_instance_id} "
            "operating model returned "
            "a non-object state"
        )

    voltage = _finite(
        raw.get(
            "terminal_voltage_v"
        ),
        label=(
            f"{model.module_instance_id}."
            "terminal_voltage_v"
        ),
    )

    substrings = (
        _normalize_protected_substrings(
            raw.get(
                "protected_substrings",
                [],
            ),
            module_id=(
                model.module_instance_id
            ),
        )
    )

    return {
        "terminal_voltage_v": (
            voltage
        ),
        "protected_substrings": (
            substrings
        ),
    }


def _string_state_at_current(
    ordered_models: list[
        SeriesModuleOperatingModel
    ],
    current_a: float,
    *,
    current_tolerance_a: float,
) -> tuple[
    float,
    list[dict[str, Any]],
]:
    current = _finite(
        current_a,
        label="string current_a",
    )

    total_voltage = 0.0

    modules = []

    for series_order, model in enumerate(
        ordered_models
    ):
        solved = _evaluate_module(
            model,
            current,
            current_tolerance_a=(
                current_tolerance_a
            ),
        )

        voltage = float(
            solved[
                "terminal_voltage_v"
            ]
        )

        total_voltage += voltage

        modules.append(
            {
                "series_order": (
                    series_order
                ),
                "module_instance_id": (
                    model.module_instance_id
                ),
                "terminal_voltage_v": (
                    voltage
                ),
                "module_power_w": float(
                    voltage
                    * current
                ),
                "protected_substrings": (
                    solved[
                        "protected_substrings"
                    ]
                ),
            }
        )

    return (
        float(total_voltage),
        modules,
    )


def _solve_string_isc(
    ordered_models: list[
        SeriesModuleOperatingModel
    ],
    *,
    current_ceiling_a: float,
    voltage_tolerance_v: float,
    current_tolerance_a: float,
    max_iterations: int,
) -> float:
    v_zero, _ = (
        _string_state_at_current(
            ordered_models,
            0.0,
            current_tolerance_a=(
                current_tolerance_a
            ),
        )
    )

    if v_zero < -voltage_tolerance_v:
        raise GeneralSeriesStringIVError(
            "string open-circuit voltage "
            "cannot be negative"
        )

    if abs(
        v_zero
    ) <= voltage_tolerance_v:
        raise GeneralSeriesStringIVError(
            "zero-generation string requires "
            "a dedicated dark-state representation"
        )

    v_high, _ = (
        _string_state_at_current(
            ordered_models,
            current_ceiling_a,
            current_tolerance_a=(
                current_tolerance_a
            ),
        )
    )

    if (
        v_high
        > voltage_tolerance_v
    ):
        raise GeneralSeriesStringIVError(
            "module current domains are too "
            "short to reach string Isc"
        )

    lo = 0.0
    hi = float(
        current_ceiling_a
    )

    for _ in range(
        max_iterations
    ):
        mid = 0.5 * (
            lo + hi
        )

        voltage, _ = (
            _string_state_at_current(
                ordered_models,
                mid,
                current_tolerance_a=(
                    current_tolerance_a
                ),
            )
        )

        if (
            abs(
                voltage
            )
            <= voltage_tolerance_v
            or (
                hi - lo
                <= current_tolerance_a
            )
        ):
            return float(
                mid
            )

        if voltage > 0:
            lo = mid
        else:
            hi = mid

    return float(
        0.5
        * (
            lo + hi
        )
    )


def _local_mpp_candidates(
    points: list[
        dict[str, float]
    ],
    global_index: int,
) -> list[
    dict[str, float]
]:
    candidates = []

    for index in range(
        1,
        len(points) - 1,
    ):
        previous_power = points[
            index - 1
        ][
            "power_w"
        ]

        power = points[
            index
        ][
            "power_w"
        ]

        next_power = points[
            index + 1
        ][
            "power_w"
        ]

        if (
            power >= previous_power
            and power >= next_power
            and (
                power > previous_power
                or power > next_power
            )
        ):
            candidates.append(
                {
                    "voltage_v": float(
                        points[
                            index
                        ][
                            "voltage_v"
                        ]
                    ),
                    "current_a": float(
                        points[
                            index
                        ][
                            "current_a"
                        ]
                    ),
                    "power_w": float(
                        power
                    ),
                }
            )

    global_point = {
        "voltage_v": float(
            points[
                global_index
            ][
                "voltage_v"
            ]
        ),
        "current_a": float(
            points[
                global_index
            ][
                "current_a"
            ]
        ),
        "power_w": float(
            points[
                global_index
            ][
                "power_w"
            ]
        ),
    }

    if not any(
        abs(
            item[
                "voltage_v"
            ]
            - global_point[
                "voltage_v"
            ]
        ) <= 1e-12
        and abs(
            item[
                "power_w"
            ]
            - global_point[
                "power_w"
            ]
        ) <= 1e-12
        for item
        in candidates
    ):
        candidates.append(
            global_point
        )

    candidates.sort(
        key=lambda item: (
            item[
                "voltage_v"
            ],
            item[
                "current_a"
            ],
        )
    )

    return candidates


def assemble_general_series_string_iv(
    string_circuit: Mapping[str, Any],
    module_models: Mapping[
        str,
        SeriesModuleOperatingModel,
    ],
    *,
    sample_count: int = 201,
    voltage_tolerance_v: float = 1e-9,
    current_tolerance_a: float = 1e-9,
    max_iterations: int = 200,
) -> GeneralSeriesStringIVResult:
    """Assemble one general non-identical series string.

    The common series current is authoritative.

    Individual modules may contribute negative terminal voltage at a valid
    string operating current. This is required for bypassed or otherwise
    current-limited modules inside a still-generating string.
    """

    (
        string_id,
        project_revision_id,
        module_ids,
    ) = _validate_string_circuit(
        string_circuit
    )

    ordered_models = (
        _validate_module_models(
            module_ids,
            module_models,
        )
    )

    if (
        isinstance(
            sample_count,
            bool,
        )
        or not isinstance(
            sample_count,
            int,
        )
        or sample_count < 25
    ):
        raise GeneralSeriesStringIVError(
            "sample_count must be "
            "an integer >= 25"
        )

    if voltage_tolerance_v <= 0:
        raise GeneralSeriesStringIVError(
            "voltage_tolerance_v "
            "must be positive"
        )

    if current_tolerance_a <= 0:
        raise GeneralSeriesStringIVError(
            "current_tolerance_a "
            "must be positive"
        )

    if max_iterations < 1:
        raise GeneralSeriesStringIVError(
            "max_iterations must be >= 1"
        )

    current_ceiling = min(
        float(
            model.current_domain_ceiling_a
        )
        for model
        in ordered_models
    )

    isc = _solve_string_isc(
        ordered_models,
        current_ceiling_a=(
            current_ceiling
        ),
        voltage_tolerance_v=(
            voltage_tolerance_v
        ),
        current_tolerance_a=(
            current_tolerance_a
        ),
        max_iterations=(
            max_iterations
        ),
    )

    voc, _ = (
        _string_state_at_current(
            ordered_models,
            0.0,
            current_tolerance_a=(
                current_tolerance_a
            ),
        )
    )

    if voc <= 0:
        raise GeneralSeriesStringIVError(
            "string Voc must be positive"
        )

    current_samples = []

    for index in range(
        sample_count
    ):
        fraction = (
            index
            / (
                sample_count - 1
            )
        )

        current = (
            isc
            * fraction
        )

        voltage, modules = (
            _string_state_at_current(
                ordered_models,
                current,
                current_tolerance_a=(
                    current_tolerance_a
                ),
            )
        )

        if (
            index
            == sample_count - 1
        ):
            voltage = 0.0

        elif (
            voltage < 0
            and abs(
                voltage
            )
            <= 10
            * voltage_tolerance_v
        ):
            voltage = 0.0

        if (
            voltage
            < -10
            * voltage_tolerance_v
        ):
            raise GeneralSeriesStringIVError(
                "sampled current below string Isc "
                "produced negative string voltage"
            )

        voltage = max(
            0.0,
            float(
                voltage
            ),
        )

        current_samples.append(
            {
                "current_a": float(
                    current
                ),
                "string_voltage_v": (
                    voltage
                ),
                "string_power_w": float(
                    voltage
                    * current
                ),
                "modules": (
                    modules
                ),
            }
        )

    points = [
        {
            "voltage_v": float(
                sample[
                    "string_voltage_v"
                ]
            ),
            "current_a": float(
                sample[
                    "current_a"
                ]
            ),
            "power_w": float(
                sample[
                    "string_power_w"
                ]
            ),
        }
        for sample
        in reversed(
            current_samples
        )
    ]

    points.sort(
        key=lambda item: (
            item[
                "voltage_v"
            ],
            -item[
                "current_a"
            ],
        )
    )

    previous_voltage = None

    for point in points:
        voltage = point[
            "voltage_v"
        ]

        if (
            previous_voltage
            is not None
            and voltage
            <= previous_voltage
        ):
            raise GeneralSeriesStringIVError(
                "sampled string V(I) does not "
                "map to a strictly increasing "
                "ElectricalIVCurve voltage grid; "
                "adaptive representation is required"
            )

        previous_voltage = (
            voltage
        )

    global_index = max(
        range(
            len(points)
        ),
        key=lambda index: (
            points[
                index
            ][
                "power_w"
            ]
        ),
    )

    global_mpp = {
        "voltage_v": float(
            points[
                global_index
            ][
                "voltage_v"
            ]
        ),
        "current_a": float(
            points[
                global_index
            ][
                "current_a"
            ]
        ),
        "power_w": float(
            points[
                global_index
            ][
                "power_w"
            ]
        ),
    }

    local_candidates = (
        _local_mpp_candidates(
            points,
            global_index,
        )
    )

    source_string_payload = {
        "string_id": (
            string_id
        ),
        "project_revision_id": (
            project_revision_id
        ),
        "module_instance_ids": (
            list(
                module_ids
            )
        ),
        "polarity": (
            string_circuit.get(
                "polarity"
            )
        ),
        "enabled": (
            string_circuit.get(
                "enabled"
            )
        ),
        "target_mppt_instance_id": (
            string_circuit.get(
                "target_mppt_instance_id"
            )
        ),
    }

    source_string_hash = (
        _canonical_sha256(
            source_string_payload
        )
    )

    module_sources = [
        {
            "series_order": (
                index
            ),
            "module_instance_id": (
                model.module_instance_id
            ),
            "current_domain_ceiling_a": float(
                model.current_domain_ceiling_a
            ),
            "scientific_input_sha256": (
                model.scientific_input_sha256
            ),
            "model_id": (
                model.model_id
            ),
            "model_version": (
                model.model_version
            ),
        }
        for index, model
        in enumerate(
            ordered_models
        )
    ]

    scientific_input = {
        "source_string_payload_sha256": (
            source_string_hash
        ),
        "source_string_id": (
            string_id
        ),
        "source_project_revision_id": (
            project_revision_id
        ),
        "source_module_instance_ids": (
            list(
                module_ids
            )
        ),
        "module_sources": (
            module_sources
        ),
        "series_rule": (
            "common_current_sum_module_voltage"
        ),
    }

    scientific_input_sha = (
        _canonical_sha256(
            scientific_input
        )
    )

    physical_payload = {
        "isc_a": float(
            isc
        ),
        "voc_v": float(
            voc
        ),
        "points": (
            points
        ),
        "global_mpp": (
            global_mpp
        ),
        "local_mpp_candidates": (
            local_candidates
        ),
    }

    physical_hash = (
        _canonical_sha256(
            physical_payload
        )
    )

    execution_payload = {
        "solver_id": (
            GENERAL_SERIES_STRING_IV_SOLVER_ID
        ),
        "solver_version": (
            GENERAL_SERIES_STRING_IV_SOLVER_VERSION
        ),
        "sample_count": (
            sample_count
        ),
        "voltage_tolerance_v": (
            voltage_tolerance_v
        ),
        "current_tolerance_a": (
            current_tolerance_a
        ),
        "max_iterations": (
            max_iterations
        ),
    }

    execution_hash = (
        _canonical_sha256(
            execution_payload
        )
    )

    curve_id = (
        "iv:string:"
        + physical_hash[:20]
    )

    curve = {
        "schema_name": (
            "ElectricalIVCurve"
        ),
        "schema_version": "0.1",
        "contract_version": "0.1",
        "curve_id": (
            curve_id
        ),
        "curve_scope": "string",
        "representation": (
            "sampled_voltage_grid"
        ),
        "sample_order": (
            "ascending_voltage"
        ),
        "sign_convention": (
            "pv_delivery_current_positive_power_equals_v_times_i"
        ),
        "source_string_id": (
            string_id
        ),
        "points": (
            points
        ),
        "isc_a": float(
            isc
        ),
        "voc_v": float(
            voc
        ),
        "mpp_semantics": {
            "declaration_authority": (
                "solver_declared"
            ),
            "sample_verification_scope": (
                "represented_samples_only"
            ),
            "voltage_tolerance_v": float(
                voltage_tolerance_v
            ),
            "power_tolerance_w": (
                1e-8
            ),
            "continuous_curve_guarantee": (
                "none"
            ),
            "continuous_curve_guarantee_basis": (
                None
            ),
        },
        "global_mpp": (
            global_mpp
        ),
        "local_mpp_candidates": (
            local_candidates
        ),
        "scientific_model_manifest": {
            "model_id": (
                GENERAL_SERIES_STRING_IV_SOLVER_ID
            ),
            "model_version": (
                GENERAL_SERIES_STRING_IV_SOLVER_VERSION
            ),
            "parameterization_id": (
                None
            ),
            "topology_revision_id": (
                None
            ),
            "bypass_model_ids": [],
            "notes": (
                "General non-identical series "
                "aggregation. Common current is "
                "explicit; module terminal voltage "
                "may be negative."
            ),
        },
        "execution_manifest": {
            "solver_id": (
                GENERAL_SERIES_STRING_IV_SOLVER_ID
            ),
            "solver_version": (
                GENERAL_SERIES_STRING_IV_SOLVER_VERSION
            ),
            "voltage_grid_strategy": (
                "uniform_string_current_then_"
                "ascending_voltage_projection"
            ),
            "point_count": (
                len(
                    points
                )
            ),
            "cache_mode": "none",
            "parallelization": "none",
        },
        "scientific_input_sha256": (
            scientific_input_sha
        ),
        "physical_result_sha256": (
            physical_hash
        ),
        "execution_payload_sha256": (
            execution_hash
        ),
        "quality_flags": [
            "common_series_current_explicit",
            (
                "negative_module_terminal_voltage_"
                "permitted"
            ),
            "represented_sample_mpp_only",
        ],
    }

    try:
        assert_electrical_iv_curve(
            curve
        )
    except ElectricalShadingContractError as exc:
        raise GeneralSeriesStringIVError(
            "assembled string ElectricalIVCurve "
            f"failed canonical validation: {exc}"
        ) from exc

    state_payload = {
        "schema_name": (
            "StringSeriesIVState"
        ),
        "schema_version": "0.1",
        "contract_version": "0.1",
        "state_id": (
            "string-series-state:"
            + scientific_input_sha[:12]
            + ":"
            + physical_hash[:12]
        ),
        "source_string_id": (
            string_id
        ),
        "source_project_revision_id": (
            project_revision_id
        ),
        "source_string_payload_sha256": (
            source_string_hash
        ),
        "source_module_instance_ids": (
            list(
                module_ids
            )
        ),
        "module_sources": (
            module_sources
        ),
        "string_curve_id": (
            curve_id
        ),
        "isc_a": float(
            isc
        ),
        "voc_v": float(
            voc
        ),
        "current_samples": (
            current_samples
        ),
        "scientific_input_sha256": (
            scientific_input_sha
        ),
    }

    state_hash = (
        _canonical_sha256(
            state_payload
        )
    )

    state = dict(
        state_payload
    )

    state[
        "state_payload_sha256"
    ] = state_hash

    return GeneralSeriesStringIVResult(
        curve=curve,
        state=state,
    )
