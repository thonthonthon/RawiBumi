"""Executable region/sub-string electrical parameterization for Phase 6.6."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from functools import lru_cache
import hashlib
import json
import math
from typing import Any, Mapping

import pvlib

from components.pan.pvsyst_sdm import (
    REQUIRED_PVSYST_PARAMETERS,
    calculate_pvsyst_diode_parameters,
)

from .contract import (
    ElectricalShadingContractError,
    assert_electrical_parameterization_evidence,
    assert_module_topology_definition,
)


REGION_PARAMETERIZATION_MODEL_ID = (
    "rawibumi.region.pvsyst_singlediode_linear_reverse.v0.1"
)

REGION_PARAMETERIZATION_MODEL_VERSION = "0.1"


class ElectricalParameterizationError(ValueError):
    """Raised when executable detailed electrical parameterization is ambiguous."""


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _finite(value: Any, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ElectricalParameterizationError(
            f"{label} must be numeric"
        )

    number = float(value)

    if not math.isfinite(number):
        raise ElectricalParameterizationError(
            f"{label} must be finite"
        )

    return number


def compute_parameterization_payload_sha256(
    definition: Mapping[str, Any],
) -> str:
    body = deepcopy(dict(definition))
    body.pop(
        "parameterization_payload_sha256",
        None,
    )
    return _canonical_sha256(body)


def finalize_parameterization_payload(
    definition: Mapping[str, Any],
) -> dict[str, Any]:
    out = deepcopy(dict(definition))
    out["parameterization_payload_sha256"] = (
        compute_parameterization_payload_sha256(
            out
        )
    )
    return out


def assert_electrical_parameterization_definition(
    definition: Mapping[str, Any],
    topology_definition: Mapping[str, Any],
) -> None:
    """Fail closed unless an executable parameter payload is exact and bound."""

    try:
        assert_module_topology_definition(
            topology_definition
        )
    except ElectricalShadingContractError as exc:
        raise ElectricalParameterizationError(
            str(exc)
        ) from exc

    required_strings = (
        "parameterization_id",
        "revision_id",
        "module_definition_revision_id",
        "module_topology_revision_id",
        "model_id",
        "model_version",
    )

    if (
        definition.get("schema_name")
        != "ElectricalParameterizationDefinition"
    ):
        raise ElectricalParameterizationError(
            "schema_name must be "
            "'ElectricalParameterizationDefinition'"
        )

    if definition.get("schema_version") != "0.1":
        raise ElectricalParameterizationError(
            "parameterization schema_version must be '0.1'"
        )

    if definition.get("contract_version") != "0.1":
        raise ElectricalParameterizationError(
            "parameterization contract_version must be '0.1'"
        )

    if (
        definition.get("parameterization_scope")
        != "region_substring"
    ):
        raise ElectricalParameterizationError(
            "Phase-6.6 executable parameterization "
            "requires region_substring scope"
        )

    for field in required_strings:
        value = definition.get(field)
        if not isinstance(value, str) or not value:
            raise ElectricalParameterizationError(
                f"{field} must be explicit"
            )

    if (
        definition["module_topology_revision_id"]
        != topology_definition.get("revision_id")
    ):
        raise ElectricalParameterizationError(
            "parameterization is bound to a different "
            "topology revision"
        )

    if (
        definition["module_definition_revision_id"]
        != topology_definition.get(
            "module_definition_revision_id"
        )
    ):
        raise ElectricalParameterizationError(
            "parameterization is bound to a different "
            "module revision"
        )

    source_ids = definition.get("source_ids")

    if (
        not isinstance(source_ids, list)
        or not source_ids
        or len(set(source_ids)) != len(source_ids)
        or any(
            not isinstance(item, str)
            or not item
            for item in source_ids
        )
    ):
        raise ElectricalParameterizationError(
            "parameterization requires unique explicit source_ids"
        )

    expected_hash = (
        compute_parameterization_payload_sha256(
            definition
        )
    )

    if (
        definition.get(
            "parameterization_payload_sha256"
        )
        != expected_hash
    ):
        raise ElectricalParameterizationError(
            "parameterization payload hash mismatch"
        )

    topology_regions = {
        str(region["region_id"]): region
        for region
        in topology_definition["physical_regions"]
    }

    entries = definition.get(
        "region_parameterizations"
    )

    if not isinstance(entries, list) or not entries:
        raise ElectricalParameterizationError(
            "region_parameterizations must be non-empty"
        )

    indexed: dict[str, Mapping[str, Any]] = {}

    for entry in entries:
        if not isinstance(entry, Mapping):
            raise ElectricalParameterizationError(
                "region parameterization must be an object"
            )

        region_id = str(
            entry.get("region_id") or ""
        )

        if not region_id:
            raise ElectricalParameterizationError(
                "region parameterization requires region_id"
            )

        if region_id in indexed:
            raise ElectricalParameterizationError(
                f"duplicate region parameterization: "
                f"{region_id}"
            )

        if region_id not in topology_regions:
            raise ElectricalParameterizationError(
                f"parameterization references unknown "
                f"region {region_id}"
            )

        if (
            entry.get("model_type")
            != "pvsyst_singlediode_linear_reverse"
        ):
            raise ElectricalParameterizationError(
                f"region {region_id} uses unsupported "
                "parameterization model"
            )

        params = entry.get("parameter_set")

        if not isinstance(params, Mapping):
            raise ElectricalParameterizationError(
                f"region {region_id} parameter_set "
                "must be an object"
            )

        missing = sorted(
            REQUIRED_PVSYST_PARAMETERS
            - set(params)
        )

        if missing:
            raise ElectricalParameterizationError(
                f"region {region_id} missing PVsyst "
                "parameters: "
                + ", ".join(missing)
            )

        cells_in_series = params.get(
            "cells_in_series"
        )

        if (
            isinstance(cells_in_series, bool)
            or not isinstance(
                cells_in_series,
                int,
            )
            or cells_in_series < 1
        ):
            raise ElectricalParameterizationError(
                f"region {region_id} cells_in_series "
                "must be a positive integer"
            )

        equivalent_count = int(
            topology_regions[
                region_id
            ][
                "equivalent_element_count"
            ]
        )

        if cells_in_series != equivalent_count:
            raise ElectricalParameterizationError(
                f"region {region_id} cells_in_series "
                "must match explicit "
                "equivalent_element_count"
            )

        for field in (
            "photocurrent_ref_a",
            "saturation_current_ref_a",
            "r_shunt_ref_ohm",
            "r_shunt_0_ohm",
            "energy_bandgap_ref_ev",
            "reference_irradiance_w_m2",
        ):
            if _finite(
                params.get(field),
                label=f"{region_id}.{field}",
            ) <= 0:
                raise ElectricalParameterizationError(
                    f"{region_id}.{field} "
                    "must be positive"
                )

        if _finite(
            params.get("r_series_ohm"),
            label=f"{region_id}.r_series_ohm",
        ) < 0:
            raise ElectricalParameterizationError(
                f"{region_id}.r_series_ohm "
                "must be non-negative"
            )

        reverse = entry.get("reverse_bias")

        if not isinstance(reverse, Mapping):
            raise ElectricalParameterizationError(
                f"region {region_id} reverse_bias "
                "must be explicit"
            )

        if (
            reverse.get("model_type")
            != "linear_resistance_from_isc"
        ):
            raise ElectricalParameterizationError(
                f"region {region_id} uses unsupported "
                "reverse-bias model"
            )

        resistance = _finite(
            reverse.get("resistance_ohm"),
            label=(
                f"{region_id}."
                "reverse_bias.resistance_ohm"
            ),
        )

        if resistance <= 0:
            raise ElectricalParameterizationError(
                f"region {region_id} reverse resistance "
                "must be positive"
            )

        minimum_voltage = _finite(
            reverse.get(
                "minimum_supported_voltage_v"
            ),
            label=(
                f"{region_id}."
                "minimum_supported_voltage_v"
            ),
        )

        if minimum_voltage > 0:
            raise ElectricalParameterizationError(
                f"region {region_id} minimum supported "
                "reverse voltage must be <= 0"
            )

        current_max = _finite(
            entry.get("current_domain_max_a"),
            label=(
                f"{region_id}."
                "current_domain_max_a"
            ),
        )

        if current_max <= 0:
            raise ElectricalParameterizationError(
                f"region {region_id} current domain "
                "must be positive"
            )

        indexed[region_id] = entry

    if set(indexed) != set(topology_regions):
        missing = sorted(
            set(topology_regions) - set(indexed)
        )
        extra = sorted(
            set(indexed) - set(topology_regions)
        )

        raise ElectricalParameterizationError(
            "parameterization region set must exactly "
            "match topology regions; "
            f"missing={missing}, extra={extra}"
        )


def assert_parameterization_evidence_binding(
    definition: Mapping[str, Any],
    evidence: Mapping[str, Any],
) -> None:
    """Prove that capability evidence validates this exact executable payload."""

    try:
        assert_electrical_parameterization_evidence(
            evidence,
            expected_scope="region_substring",
        )
    except ElectricalShadingContractError as exc:
        raise ElectricalParameterizationError(
            str(exc)
        ) from exc

    comparisons = (
        (
            "parameterization_id",
            "parameterization_id",
        ),
        (
            "module_definition_revision_id",
            "module_definition_revision_id",
        ),
        (
            "module_topology_revision_id",
            "module_topology_revision_id",
        ),
        (
            "model_id",
            "model_id",
        ),
        (
            "model_version",
            "model_version",
        ),
        (
            "parameterization_payload_sha256",
            "parameterization_payload_sha256",
        ),
    )

    for definition_field, evidence_field in comparisons:
        if (
            definition.get(definition_field)
            != evidence.get(evidence_field)
        ):
            raise ElectricalParameterizationError(
                "parameterization evidence does not "
                f"match payload field "
                f"{definition_field}"
            )


@dataclass(frozen=True)
class PVSystRegionElectricalState:
    """One explicitly parameterized region at one irradiance/temperature state."""

    region_id: str
    source_local_region_id: str
    source_substring_id: str

    effective_irradiance_w_m2: float
    cell_temperature_c: float

    isc_a: float
    voc_v: float

    current_ceiling_a: float

    reverse_resistance_ohm: float
    minimum_supported_voltage_v: float

    diode_parameters: tuple[float, ...] | None

    solver: str = "lambertw"

    model_id: str = REGION_PARAMETERIZATION_MODEL_ID

    def voltage_at_current(
        self,
        current_a: float,
    ) -> float:

        current = _finite(
            current_a,
            label=f"{self.region_id}.current_a",
        )

        if current < 0:
            raise ElectricalParameterizationError(
                "region current must be non-negative"
            )

        if (
            current
            > self.current_ceiling_a + 1e-10
        ):
            raise ElectricalParameterizationError(
                f"region {self.region_id} current "
                "exceeds explicit parameterization domain"
            )

        if self.isc_a <= 1e-12:
            voltage = (
                -self.reverse_resistance_ohm
                * current
            )

        elif current <= self.isc_a:
            if self.diode_parameters is None:
                raise ElectricalParameterizationError(
                    "active region has no diode parameters"
                )

            voltage = float(
                pvlib.pvsystem.v_from_i(
                    current,
                    *self.diode_parameters,
                    method=self.solver,
                )
            )

            if abs(voltage) < 1e-10:
                voltage = 0.0

        else:
            voltage = (
                -self.reverse_resistance_ohm
                * (
                    current
                    - self.isc_a
                )
            )

        if (
            voltage
            < self.minimum_supported_voltage_v
            - 1e-9
        ):
            raise ElectricalParameterizationError(
                f"region {self.region_id} requires "
                f"{voltage:.6g} V reverse bias, below "
                "its validated/supported domain "
                f"{self.minimum_supported_voltage_v:.6g} V"
            )

        return float(voltage)

    def current_at_voltage(
        self,
        voltage_v: float,
    ) -> float:
        """Direct I(V) evaluation from the explicit region model."""

        voltage = _finite(
            voltage_v,
            label=f"{self.region_id}.voltage_v",
        )

        if (
            voltage
            < self.minimum_supported_voltage_v
            - 1e-9
        ):
            raise ElectricalParameterizationError(
                f"region {self.region_id} "
                f"requires {voltage:.6g} V, "
                "below supported reverse-voltage "
                "domain "
                f"{self.minimum_supported_voltage_v:.6g} V"
            )

        if (
            voltage
            > self.voc_v
            + 1e-10
        ):
            return 0.0

        if (
            voltage >= 0.0
            and self.isc_a > 1e-12
        ):
            if self.diode_parameters is None:
                raise ElectricalParameterizationError(
                    "active region has no diode parameters"
                )

            current = float(
                pvlib.pvsystem.i_from_v(
                    voltage,
                    *self.diode_parameters,
                    method=self.solver,
                )
            )

            if (
                current < 0.0
                and abs(current) <= 1e-10
            ):
                current = 0.0

            if current < -1e-10:
                raise ElectricalParameterizationError(
                    f"region {self.region_id} "
                    "I(V) returned negative "
                    "delivery current"
                )

        else:
            # Explicit reverse branch:
            #
            # V = -R * (I - Isc)
            #
            # therefore:
            #
            # I = Isc - V/R
            current = (
                self.isc_a
                - voltage
                / self.reverse_resistance_ohm
            )

        if (
            current
            > self.current_ceiling_a
            + 1e-9
        ):
            raise ElectricalParameterizationError(
                f"region {self.region_id} "
                f"voltage {voltage:.6g} V "
                f"requires {current:.6g} A "
                "above supported current "
                f"domain {self.current_ceiling_a:.6g} A"
            )

        return float(
            max(
                0.0,
                current,
            )
        )


def build_pvsyst_region_electrical_states(
    topology_definition: Mapping[str, Any],
    electrical_region_map: Mapping[str, Any],
    local_irradiance_state: Mapping[str, Any],
    parameterization_definition: Mapping[str, Any],
    parameterization_evidence: Mapping[str, Any],
    *,
    solver: str = "lambertw",
    active_irradiance_threshold_w_m2: float = 1e-9,
    authorization_witness=None,
) -> dict[str, PVSystRegionElectricalState]:
    """Evaluate explicit per-region models at Phase-6.3 local irradiance."""

    from engine.simulation.detailed_inputs import validate_regional_transport
    if (authorization_witness is not None or parameterization_evidence.get("schema_version") == "0.2"
            or "evidence_class" in parameterization_evidence):
        validate_regional_transport(authorization_witness, topology_definition,
                                   parameterization_definition, parameterization_evidence)

    assert_electrical_parameterization_definition(
        parameterization_definition,
        topology_definition,
    )

    if parameterization_evidence.get("schema_version") == "0.2":
        from engine.simulation.detailed_inputs import _assert_numerical_parameterization_binding
        _assert_numerical_parameterization_binding(parameterization_definition, parameterization_evidence)
    else:
        assert_parameterization_evidence_binding(
            parameterization_definition, parameterization_evidence)

    return _build_region_states_from_checked_inputs(
        topology_definition, electrical_region_map, local_irradiance_state,
        parameterization_definition, solver=solver,
        active_irradiance_threshold_w_m2=active_irradiance_threshold_w_m2,
    )


def _build_region_states_from_checked_inputs(
    topology_definition: Mapping[str, Any],
    electrical_region_map: Mapping[str, Any],
    local_irradiance_state: Mapping[str, Any],
    parameterization_definition: Mapping[str, Any],
    *, solver: str = "lambertw",
    active_irradiance_threshold_w_m2: float = 1e-9,
) -> dict[str, PVSystRegionElectricalState]:
    """Shared numerical construction; caller must validate selected assets first."""
    map_id = str(
        electrical_region_map.get(
            "electrical_region_map_id"
        )
        or ""
    )

    map_hash = str(
        electrical_region_map.get(
            "mapping_payload_sha256"
        )
        or ""
    )

    if not map_id or not map_hash:
        raise ElectricalParameterizationError(
            "electrical region map identity is required"
        )

    if (
        local_irradiance_state.get(
            "source_electrical_region_map_id"
        )
        != map_id
    ):
        raise ElectricalParameterizationError(
            "local irradiance state is bound "
            "to another region map"
        )

    if (
        local_irradiance_state.get(
            "source_electrical_region_map_hash"
        )
        != map_hash
    ):
        raise ElectricalParameterizationError(
            "local irradiance region-map hash mismatch"
        )

    if (
        electrical_region_map.get(
            "source_module_topology_revision_id"
        )
        != topology_definition.get("revision_id")
    ):
        raise ElectricalParameterizationError(
            "region map/topology revision mismatch"
        )

    temperature = _finite(
        local_irradiance_state.get(
            "module_temperature_c"
        ),
        label="module_temperature_c",
    )

    threshold = _finite(
        active_irradiance_threshold_w_m2,
        label=(
            "active_irradiance_threshold_w_m2"
        ),
    )

    if threshold < 0:
        raise ElectricalParameterizationError(
            "active irradiance threshold must "
            "be non-negative"
        )

    map_by_local_id = {
        str(item["region_id"]): item
        for item
        in electrical_region_map.get("regions") or []
    }

    local_by_id = {
        str(item["region_id"]): item
        for item
        in local_irradiance_state.get("regions") or []
    }

    if set(map_by_local_id) != set(local_by_id):
        raise ElectricalParameterizationError(
            "local irradiance regions must exactly "
            "match ElectricalRegionMap"
        )

    source_to_local: dict[str, str] = {}

    for local_id, mapped in map_by_local_id.items():
        source_id = str(
            mapped.get(
                "source_topology_region_id"
            )
            or ""
        )

        if not source_id:
            raise ElectricalParameterizationError(
                "mapped region requires "
                "source_topology_region_id"
            )

        if source_id in source_to_local:
            raise ElectricalParameterizationError(
                "topology region appears more than once "
                "in ElectricalRegionMap"
            )

        source_to_local[source_id] = local_id

    parameter_entries = {
        str(entry["region_id"]): entry
        for entry
        in parameterization_definition[
            "region_parameterizations"
        ]
    }

    topology_regions = {
        str(region["region_id"]): region
        for region
        in topology_definition[
            "physical_regions"
        ]
    }

    if set(source_to_local) != set(topology_regions):
        raise ElectricalParameterizationError(
            "ElectricalRegionMap does not cover "
            "the exact topology region set"
        )

    states: dict[
        str,
        PVSystRegionElectricalState,
    ] = {}

    for region_id in sorted(
        topology_regions
    ):
        local_id = source_to_local[
            region_id
        ]

        mapped = map_by_local_id[
            local_id
        ]

        local = local_by_id[
            local_id
        ]

        topology_region = topology_regions[
            region_id
        ]

        entry = parameter_entries[
            region_id
        ]

        source_substring_id = str(
            topology_region[
                "electrical_substring_id"
            ]
        )

        if (
            str(
                mapped.get(
                    "source_electrical_substring_id"
                )
            )
            != source_substring_id
        ):
            raise ElectricalParameterizationError(
                f"region {region_id} substring "
                "identity mismatch"
            )

        effective = _finite(
            local.get(
                "effective_irradiance_w_m2"
            ),
            label=(
                f"{region_id}."
                "effective_irradiance_w_m2"
            ),
        )

        if effective < 0:
            raise ElectricalParameterizationError(
                f"region {region_id} effective "
                "irradiance must be non-negative"
            )

        params = dict(
            entry["parameter_set"]
        )

        diode_parameters = None

        isc = 0.0
        voc = 0.0

        if effective > threshold:
            raw = calculate_pvsyst_diode_parameters(
                effective_irradiance_w_m2=(
                    effective
                ),
                cell_temperature_c=temperature,
                parameter_set=params,
            )

            diode_parameters = tuple(
                float(value)
                for value in raw
            )

            solved = (
                pvlib.pvsystem.singlediode(
                    *diode_parameters,
                    method=solver,
                )
            )

            isc = float(
                solved["i_sc"]
            )

            voc = float(
                solved["v_oc"]
            )

            if (
                not math.isfinite(isc)
                or not math.isfinite(voc)
                or isc < 0
                or voc < 0
            ):
                raise ElectricalParameterizationError(
                    f"region {region_id} PVsyst model "
                    "returned invalid Isc/Voc"
                )

        declared_current_ceiling = _finite(
            entry[
                "current_domain_max_a"
            ],
            label=(
                f"{region_id}."
                "current_domain_max_a"
            ),
        )

        if (
            declared_current_ceiling
            + 1e-9
            < isc
        ):
            raise ElectricalParameterizationError(
                f"region {region_id} explicit current "
                "domain is below modeled Isc"
            )

        reverse = entry[
            "reverse_bias"
        ]

        reverse_resistance = _finite(
            reverse[
                "resistance_ohm"
            ],
            label=(
                f"{region_id}."
                "reverse_resistance_ohm"
            ),
        )

        minimum_supported_voltage = _finite(
            reverse[
                "minimum_supported_voltage_v"
            ],
            label=(
                f"{region_id}."
                "minimum_supported_voltage_v"
            ),
        )

        # Reverse model:
        #
        # V = -R * (I - Isc)
        #
        # therefore:
        #
        # I(Vmin) = Isc + |Vmin| / R
        #
        # The executable current domain is the
        # intersection of BOTH explicitly declared
        # limits:
        #
        #   I <= current_domain_max_a
        #   V >= minimum_supported_voltage_v
        #
        # This prevents numerical bracketing from
        # probing outside validated reverse-bias
        # support.
        reverse_supported_current_ceiling = (
            isc
            + max(
                0.0,
                -minimum_supported_voltage,
            )
            / reverse_resistance
        )

        current_ceiling = min(
            declared_current_ceiling,
            reverse_supported_current_ceiling,
        )

        if (
            current_ceiling
            + 1e-9
            < isc
        ):
            raise ElectricalParameterizationError(
                f"region {region_id} reverse-voltage "
                "domain does not include modeled Isc"
            )

        states[
            region_id
        ] = PVSystRegionElectricalState(
            region_id=region_id,
            source_local_region_id=(
                local_id
            ),
            source_substring_id=(
                source_substring_id
            ),
            effective_irradiance_w_m2=(
                effective
            ),
            cell_temperature_c=(
                temperature
            ),
            isc_a=isc,
            voc_v=voc,
            current_ceiling_a=(
                current_ceiling
            ),
            reverse_resistance_ohm=(
                reverse_resistance
            ),
            minimum_supported_voltage_v=(
                minimum_supported_voltage
            ),
            diode_parameters=(
                diode_parameters
            ),
            solver=solver,
        )

    return states


# B2 policy identity includes all secondary tolerances and optimizer precision.
# This result is numerical evidence only, never an execution permission.
_NUMERICAL_ACCEPTANCE_POLICY = (
    "rawibumi.level2.uniform_iv_equal_series", "1.0.0",
    "rb08b2.secondary.1", 1e-4, 1e-6, 1e-6, 1e-5, 0.005, 1e-5,
    "golden_section.1", 1e-10, 256, 1e-8,
)


def _require_acceptance(condition: bool, message: str) -> None:
    if not condition:
        raise ElectricalParameterizationError(message)


def _assert_numerical_candidate_assets(module, topology, definition, evidence, sources):
    from pathlib import Path
    from jsonschema import Draft202012Validator
    from components.topology_library import (
        assert_library_source_bindings, canonical_topology_asset_sha256,
    )
    from .contract import (
        assert_numerical_assumption_evidence_structure,
        resolve_region_geometry_execution_readiness,
    )
    root = Path(__file__).resolve().parents[2]
    for value, path in (
        (module, "components/schema/module-definition.schema.json"),
        (topology, "components/schema/module-topology-definition.schema.json"),
        (definition, "shading/electrical/electrical-parameterization-definition.schema.json"),
    ):
        Draft202012Validator(json.loads((root / path).read_text())).validate(value)
    assert_numerical_assumption_evidence_structure(evidence)
    assert_electrical_parameterization_definition(definition, topology)
    _require_acceptance(evidence["parameterization_scope"] == "region_substring",
                        "unsupported numerical assumption scope")
    declaration = evidence["assumption_declaration"]
    expected_metadata = {key: declaration[key] for key in (
        "assumption_id", "assumption_revision_id", "evidence_class")}
    for label, asset in (("topology", topology), ("parameterization", definition)):
        _require_acceptance((asset.get("metadata") or {}).get("numerical_assumption") == expected_metadata,
                            f"{label}.metadata.numerical_assumption exact linkage mismatch")
        assert_library_source_bindings(asset, sources, label=label)
    _require_acceptance(topology["verification_state"] == "unverified" and
                        topology["topology_provenance"] == "inferred",
                        "numerical topology must remain inferred/unverified")
    comparisons = (
        (declaration["module_source"]["component_id"], module["module_definition_id"], "module identity"),
        (declaration["module_source"]["revision_id"], module["revision_id"], "module revision"),
        (module["revision_id"], topology["module_definition_revision_id"], "topology module revision"),
        (module["revision_id"], definition["module_definition_revision_id"], "parameterization module revision"),
        (declaration["topology"]["topology_id"], topology["module_topology_id"], "topology identity"),
        (declaration["topology"]["topology_revision_id"], topology["revision_id"], "topology revision"),
        (declaration["topology"]["topology_sha256"], canonical_topology_asset_sha256(topology), "topology digest"),
        (declaration["parameterization"]["parameterization_id"], definition["parameterization_id"], "parameterization identity"),
        (declaration["parameterization"]["parameterization_revision_id"], definition["revision_id"], "parameterization revision"),
        (declaration["parameterization"]["parameterization_sha256"], compute_parameterization_payload_sha256(definition), "parameterization digest"),
        (evidence["model_id"], definition["model_id"], "model identity"),
        (evidence["model_version"], definition["model_version"], "model version"),
    )
    for supplied, actual, label in comparisons:
        _require_acceptance(supplied == actual, f"selected {label} mismatch")
    _require_acceptance(resolve_region_geometry_execution_readiness(
        topology, topology_structurally_valid=True), "region geometry unsupported")
    regions = topology["physical_regions"]
    substrings = topology["electrical_substrings"]
    _require_acceptance(len(regions) == len(substrings) == 3,
                        "equal-series policy requires three regions and three substrings")
    for substring in substrings:
        branches = substring["parallel_branches"]
        _require_acceptance(len(branches) == 1 and len(branches[0]["series_region_ids"]) == 1,
                            "equal-series policy requires one equivalent region/branch per substring")
    area = 0.0
    fractions = []
    for region in regions:
        polygon = region["polygon_normalized"]
        area += abs(sum(polygon[i][0] * polygon[(i+1) % len(polygon)][1] -
                        polygon[(i+1) % len(polygon)][0] * polygon[i][1]
                        for i in range(len(polygon)))) / 2
        if region.get("active_area_fraction") is not None:
            fractions.append(region["active_area_fraction"])
    _require_acceptance(abs(area - 1.0) <= 1e-9, "region polygons must cover one module")
    if len(fractions) == 3:
        _require_acceptance(abs(sum(fractions) - 1.0) <= 1e-9,
                            "region active area fractions must sum to one")
    for device in topology["bypass_devices"]:
        model = device["forward_voltage_model"]
        if model.get("source_ids"):
            assert_library_source_bindings(model, sources, label="bypass model")
    quality = evidence.get("module_quality_declaration")
    if quality is not None:
        assert_library_source_bindings(quality, sources, label="module quality declaration")
        _require_acceptance(set(quality["source_ids"]).issubset(evidence["source_ids"]),
                            "quality source IDs must belong to evidence")


def _acceptance_states(topology, definition, evidence, irradiances, temperature, solver):
    """Build actual regional states and the production adapter without a permit."""
    from .module_series_adapter import _build_series_model_from_checked_states
    _require_acceptance(_finite(temperature, label="temperature") > -273.15,
                        "temperature must be above absolute zero")
    for value in irradiances.values():
        _require_acceptance(_finite(value, label="irradiance") >= 0,
                            "irradiance must be non-negative")
    region_map = dict(
        electrical_region_map_id="b2-acceptance-map",
        source_module_instance_id="b2-acceptance-module",
        source_module_topology_revision_id=topology["revision_id"],
        regions=[dict(region_id=r["region_id"], source_topology_region_id=r["region_id"],
                      source_electrical_substring_id=r["electrical_substring_id"])
                 for r in topology["physical_regions"]],
    )
    region_map["mapping_payload_sha256"] = _canonical_sha256(region_map)
    local = dict(source_electrical_region_map_id=region_map["electrical_region_map_id"],
                 source_electrical_region_map_hash=region_map["mapping_payload_sha256"],
                 module_temperature_c=temperature,
                 regions=[dict(region_id=key, effective_irradiance_w_m2=value)
                          for key, value in sorted(irradiances.items())])
    states = _build_region_states_from_checked_inputs(
        topology, region_map, local, definition, solver=solver)
    adapter = _build_series_model_from_checked_states(
        topology, region_map, local, definition, evidence, states, region_solver=solver)
    return states, adapter


def _check_numerical_conservation(topology, states, adapter, current):
    """Independently reconcile actual branch, substring and adapter results."""
    from .substring_reference import evaluate_protected_substring_at_current
    current_error = voltage_error = power_error = 0.0
    voltage_sum = signed_power = 0.0
    solved_states = []
    for substring in sorted(topology["electrical_substrings"], key=lambda x: x["series_order"]):
        solved = evaluate_protected_substring_at_current(
            topology, substring["substring_id"], states, current_a=current)
        solved_states.append(solved)
        terminal = _finite(solved["terminal_voltage_v"], label="substring terminal voltage")
        bypass = _finite(solved["bypass_current_a"], label="bypass current")
        _require_acceptance(bypass >= 0 and solved["bypass_clamp_voltage_v"] <= 0,
                            "invalid bypass polarity/current")
        pv_current = sum(_finite(b["current_a"], label="PV branch current")
                         for b in solved["terminal_branch_states"])
        current_error = max(current_error, abs(pv_current + bypass - current))
        branches = {b["branch_id"]: b for b in substring["parallel_branches"]}
        region_power = 0.0
        for branch in solved["terminal_branch_states"]:
            branch_current = _finite(branch["current_a"], label="branch current")
            ids = branches[branch["branch_id"]]["series_region_ids"]
            region_voltages = [_finite(states[key].voltage_at_current(branch_current),
                                       label="series region voltage") for key in ids]
            branch_voltage = _finite(branch["voltage_v"], label="branch voltage")
            region_sum = sum(region_voltages)
            voltage_error = max(voltage_error, abs(region_sum - branch_voltage),
                                abs(branch_voltage - terminal))
            # I(V) provides an independent check of delivered series current.
            for key, voltage in zip(ids, region_voltages):
                current_error = max(current_error, abs(_finite(states[key].current_at_voltage(voltage),
                                                               label="region I(V) current") - branch_current))
            region_power += region_sum * branch_current
        diode_dissipation = -terminal * bypass
        _require_acceptance(diode_dissipation >= -1e-10, "bypass device creates positive power")
        net_power = region_power - diode_dissipation
        power_error = max(power_error, abs(net_power - terminal * current))
        signed_power += net_power
        voltage_sum += terminal
    actual = adapter.voltage_at_current(current)
    terminal_voltage = _finite(actual["terminal_voltage_v"], label="module terminal voltage")
    voltage_error = max(voltage_error, abs(terminal_voltage - voltage_sum))
    power_error = max(power_error, abs(terminal_voltage * current - signed_power))
    _require_acceptance(current_error <= 1e-6, f"G2 series-current residual {current_error:.17g} A exceeds 1e-6")
    _require_acceptance(voltage_error <= 1e-6, f"G3 series-voltage residual {voltage_error:.17g} V exceeds 1e-6")
    _require_acceptance(power_error <= 1e-5, f"G4 Kirchhoff power residual {power_error:.17g} W exceeds 1e-5")
    return dict(current_residual_a=current_error, voltage_residual_v=voltage_error,
                power_residual_w=power_error), solved_states


def _resolve_uniform_mpp_for_temperature_gate(adapter, isc, *, bracket_scale=1e-10):
    """Continuous diagnostic MPP; leaves production sampled-MPPT unchanged."""
    lo, hi = 0.0, float(isc)
    _require_acceptance(math.isfinite(hi) and hi > 0, "G8 MPP requires finite positive Isc")
    tolerance = bracket_scale * max(1.0, isc)
    evaluations = 0

    def point(current):
        nonlocal evaluations
        evaluations += 1
        _require_acceptance(evaluations <= 256, "G8 MPP evaluation cap exceeded")
        state = adapter.voltage_at_current(current)
        _require_acceptance(not any(s["bypass_active"] for s in state["protected_substrings"]),
                            "G8 uniform generating branch has active bypass")
        voltage = _finite(state["terminal_voltage_v"], label="G8 MPP voltage")
        power = current * voltage
        _require_acceptance(math.isfinite(power), "G8 nonfinite MPP power")
        return voltage, power

    left_endpoint = point(lo)[1]
    right_endpoint = point(hi)[1]
    ratio = (math.sqrt(5.0) - 1.0) / 2.0
    left, right = hi - ratio * (hi-lo), lo + ratio * (hi-lo)
    pl, pr = point(left)[1], point(right)[1]
    while hi - lo > tolerance:
        if pl < pr:
            lo, left, pl = left, right, pr
            right = lo + ratio * (hi-lo)
            pr = point(right)[1]
        else:
            hi, right, pr = right, left, pl
            left = hi - ratio * (hi-lo)
            pl = point(left)[1]
    imp = (lo + hi) / 2.0
    vmp, pmp = point(imp)
    _require_acceptance(0 < imp < isc and pmp > max(left_endpoint, right_endpoint),
                        "G8 boundary or unresolved flat MPP")
    return dict(i_mp=imp, v_mp=vmp, p_mp=pmp, bracket_width_a=hi-lo,
                evaluations=evaluations)


def _check_acceptance_domain(states):
    """Probe explicit endpoints and ensure unsupported extrapolation raises."""
    for state in states.values():
        for current in (0.0, state.isc_a, state.current_ceiling_a):
            _finite(state.voltage_at_current(current), label="G9 domain endpoint voltage")
        for invalid in (-1.0, state.current_ceiling_a + 1e-5, float("nan")):
            try:
                state.voltage_at_current(invalid)
            except ElectricalParameterizationError:
                pass
            else:
                raise ElectricalParameterizationError("G9 unsupported current extrapolation accepted")
        try:
            state.current_at_voltage(state.minimum_supported_voltage_v - 1e-5)
        except ElectricalParameterizationError:
            pass
        else:
            raise ElectricalParameterizationError("G9 unsupported reverse-voltage extrapolation accepted")


def _check_acceptance_bypass(topology, definition, evidence, solver):
    from .substring_reference import evaluate_protected_substring_at_current
    diagnostics = []
    region_ids = sorted(r["region_id"] for r in topology["physical_regions"])
    for substring in sorted(topology["electrical_substrings"], key=lambda s: s["series_order"]):
        shaded_id = substring["parallel_branches"][0]["series_region_ids"][0]
        found = None
        for fraction in (0.5, 0.1, 0.01):
            irradiances = {key: 1000.0 for key in region_ids}
            irradiances[shaded_id] *= fraction
            states, adapter = _acceptance_states(topology, definition, evidence, irradiances, 25.0, solver)
            at_zero = evaluate_protected_substring_at_current(
                topology, substring["substring_id"], states, current_a=0.0)
            transition = at_zero["pv_current_at_bypass_clamp_a"]
            clamp = at_zero["bypass_clamp_voltage_v"]
            delta = max(2e-8, 1e-6 * transition)
            if not 0 < transition - delta < transition + delta < adapter.current_domain_ceiling_a:
                continue
            for _ in range(20):
                points = []
                for current in (transition-delta, transition, transition+delta):
                    conservation, solved = _check_numerical_conservation(topology, states, adapter, current)
                    target = next(s for s in solved if s["substring_id"] == substring["substring_id"])
                    points.append((target, conservation))
                flags = [p[0]["bypass_active"] for p in points]
                if flags == [False, False, True]:
                    before, at, after = [p[0] for p in points]
                    _require_acceptance(abs(after["terminal_voltage_v"] - clamp) <= 1e-10,
                                        "G6 active bypass does not equal actual model clamp")
                    _require_acceptance(abs(at["terminal_voltage_v"] - clamp) <= 1e-6,
                                        "G7 transition is not at actual model clamp")
                    raw_before = before["unbypassed_voltage_v"]
                    raw_at = at["unbypassed_voltage_v"]
                    _require_acceptance(raw_before is not None and raw_at is not None,
                                        "G7 transition unbypassed solution unavailable")
                    _require_acceptance(abs(before["terminal_voltage_v"] - after["terminal_voltage_v"])
                                        <= abs(raw_before - raw_at) + 1e-6,
                                        "G7 bypass transition voltage discontinuity")
                    # Retain and exercise the actual linear reverse branch.
                    reverse_current = states[shaded_id].isc_a + min(
                        (states[shaded_id].current_ceiling_a - states[shaded_id].isc_a)/2, delta)
                    if states[shaded_id].minimum_supported_voltage_v < 0:
                        _require_acceptance(states[shaded_id].voltage_at_current(reverse_current) < 0,
                                            "G6 reverse-bias negative voltage lost")
                    found = dict(substring_id=substring["substring_id"], shaded_fraction=fraction,
                                 transition_current_a=transition, clamp_voltage_v=clamp,
                                 bracket_delta_a=delta, states=flags,
                                 conservation=[p[1] for p in points])
                    break
                delta *= 2
                if not 0 < transition-delta < transition+delta < adapter.current_domain_ceiling_a:
                    break
            if found is not None:
                break
        _require_acceptance(found is not None,
                            f"G7 no resolvable supported bypass transition for {substring['substring_id']}")
        diagnostics.append(found)
    return diagnostics


def _evaluate_numerical_candidate_physics(module, topology, definition, evidence, solver):
    from engine.module.pvsyst import extract_validated_pvsyst_parameter_set
    from .contract import numerical_assumption_object_sha256
    from .module_iv import _solve_module_isc

    _require_acceptance(solver in {"lambertw", "brentq"}, "unsupported acceptance solver")
    source_models = [m for m in module["electrical_models"] if m["model_type"] == "pvsyst_singlediode"]
    _require_acceptance(len(source_models) == 1, "ambiguous whole-module PVsyst source model")
    params = extract_validated_pvsyst_parameter_set(module)
    for key in REQUIRED_PVSYST_PARAMETERS:
        _finite(params[key], label=f"whole-module.{key}")
    positive = REQUIRED_PVSYST_PARAMETERS - {
        "alpha_sc_a_per_c", "mu_gamma", "reference_cell_temperature_c", "r_series_ohm", "r_shunt_exp"}
    for key in positive:
        _require_acceptance(params[key] > 0, f"whole-module.{key} must be positive")
    _require_acceptance(params["r_series_ohm"] >= 0 and params["r_shunt_exp"] >= 0,
                        "invalid whole-module resistance/exponent")
    _require_acceptance(params["reference_cell_temperature_c"] > -273.15,
                        "invalid source reference temperature")
    _require_acceptance(type(params["cells_in_series"]) is int and params["cells_in_series"] % 3 == 0,
                        "source series-cell semantics incompatible with three equal regions")
    source_validation_id = (source_models[0].get("validation") or {}).get("validation_record_id")
    declaration = evidence["assumption_declaration"]
    if source_validation_id:
        _require_acceptance(source_validation_id not in {
            declaration["assumption_id"], declaration["assumption_revision_id"]},
            "assumption identity collides with source validation identity")
    region_ids = sorted(r["region_id"] for r in topology["physical_regions"])

    def whole(g, temperature):
        diode = tuple(float(v) for v in calculate_pvsyst_diode_parameters(
            effective_irradiance_w_m2=g, cell_temperature_c=temperature, parameter_set=params))
        _require_acceptance(all(math.isfinite(v) for v in diode), "G9 nonfinite source diode parameters")
        solved = pvlib.pvsystem.singlediode(*diode, method=solver)
        points = {key: float(solved[key]) for key in ("i_sc", "v_oc", "i_mp", "v_mp", "p_mp")}
        _require_acceptance(all(math.isfinite(v) and v > 0 for v in points.values()),
                            "G9 invalid/nonconvergent whole-module solution")
        return diode, points

    def uniform(g, temperature):
        return _acceptance_states(topology, definition, evidence,
                                  {key: float(g) for key in region_ids}, float(temperature), solver)

    def regional_points(states, adapter):
        isc = _solve_module_isc(topology, states, current_ceiling_a=adapter.current_domain_ceiling_a,
                                voltage_tolerance_v=1e-10, current_tolerance_a=1e-10,
                                max_iterations=200)
        coarse = _resolve_uniform_mpp_for_temperature_gate(adapter, isc)
        tight = _resolve_uniform_mpp_for_temperature_gate(adapter, isc, bracket_scale=1e-11)
        stability = {key: abs(coarse[key] - tight[key]) for key in ("i_mp", "v_mp", "p_mp")}
        _require_acceptance(all(value <= 1e-8 for value in stability.values()),
                            f"G8 MPP precision failure: {stability}; required <=1e-8 A/V/W")
        voc = _finite(adapter.voltage_at_current(0.0)["terminal_voltage_v"], label="regional Voc")
        points = dict(i_sc=isc, v_oc=voc, **{key: tight[key] for key in ("i_mp", "v_mp", "p_mp")})
        return points, dict(coarse=coarse, tight=tight, stability=stability)

    record = dict(policy_id=_NUMERICAL_ACCEPTANCE_POLICY[0], policy_version=_NUMERICAL_ACCEPTANCE_POLICY[1],
                  assumption_digest_sha256=declaration["digest_sha256"], model_family="pvsyst_sdm",
                  voltage_tolerance_v=0.0001, cases=[])
    conservation_results = []
    characteristic_results = []
    for g, temperature in ((1000, 25), (800, 45), (400, 15)):
        diode, whole_points = whole(g, temperature)
        states, adapter = uniform(g, temperature)
        _check_acceptance_domain(states)
        samples = []
        for fraction in (0.10, 0.30, 0.50, 0.70, 0.90):
            current = fraction * whole_points["i_sc"]
            module_voltage = _finite(float(pvlib.pvsystem.v_from_i(current, *diode, method=solver)),
                                     label="whole-module fixed-current voltage")
            assembled = _finite(adapter.voltage_at_current(current)["terminal_voltage_v"],
                                label="assembled fixed-current voltage")
            checks, substring_states = _check_numerical_conservation(topology, states, adapter, current)
            _require_acceptance(not any(s["bypass_active"] for s in substring_states),
                                "G5 uniform fixed-current state has active bypass")
            conservation_results.append(checks)
            samples.append(dict(current_a=current, module_voltage_v=module_voltage,
                                assembled_voltage_v=assembled, residual_v=assembled-module_voltage))
        record["cases"].append(dict(irradiance_w_m2=g, cell_temperature_c=temperature, samples=samples))
        # G1 is evaluated before semantic equality checks so incorrect resistance
        # transformations are diagnosed against real numerical residuals.
    maximum = max(abs(sample["residual_v"]) for case in record["cases"] for sample in case["samples"])
    record.update(max_abs_residual_v=maximum, passed=maximum <= 1e-4)
    record["digest_sha256"] = numerical_assumption_object_sha256(record)
    if not record["passed"]:
        return dict(accepted=False, failures=[f"G1 maximum fixed-current voltage residual {maximum:.17g} V exceeds 1e-4"],
                    consistency_record=record, conservation=conservation_results)

    divided = {"cells_in_series", "r_series_ohm", "r_shunt_ref_ohm", "r_shunt_0_ohm"}
    for entry in definition["region_parameterizations"]:
        region_params = entry["parameter_set"]
        for key in REQUIRED_PVSYST_PARAMETERS:
            expected = params[key] / 3 if key in divided else params[key]
            _require_acceptance(math.isclose(region_params[key], expected, rel_tol=1e-12, abs_tol=0.0),
                                f"equal-series parameter semantics mismatch: {entry['region_id']}.{key}")

    # Characteristic agreement is secondary, with the approved relative/floor
    # tolerance. Continuous MPP prevents sampled-curve jitter in the thermal gate.
    for g, temperature in ((1000, 25), (800, 45), (400, 15)):
        _, whole_points = whole(g, temperature)
        states, adapter = uniform(g, temperature)
        points, precision = regional_points(states, adapter)
        for key in whole_points:
            error = abs(points[key] - whole_points[key])
            _require_acceptance(error <= max(0.005 * abs(whole_points[key]), 1e-5),
                                f"characteristic {key} residual {error:.17g} outside tolerance")
        characteristic_results.append(dict(irradiance_w_m2=g, cell_temperature_c=temperature,
                                           whole=whole_points, regional=points, precision=precision))

    bypass_results = _check_acceptance_bypass(topology, definition, evidence, solver)
    _, reference_points = whole(1000, 25)
    reference_current = 0.5 * reference_points["i_sc"]
    thermal_points = {}
    thermal_precision = []
    for temperature in (24, 25, 26):
        diode, whole_points = whole(1000, temperature)
        states, adapter = uniform(1000, temperature)
        regional, precision = regional_points(states, adapter)
        _require_acceptance(reference_current < min(whole_points["i_sc"], regional["i_sc"]),
                            "G8 common fixed current outside generating temperature domain")
        whole_points["fixed_current_voltage_v"] = float(pvlib.pvsystem.v_from_i(reference_current, *diode, method=solver))
        regional["fixed_current_voltage_v"] = adapter.voltage_at_current(reference_current)["terminal_voltage_v"]
        _check_numerical_conservation(topology, states, adapter, reference_current)
        thermal_points[temperature] = (whole_points, regional)
        thermal_precision.append(precision)
    temperature_responses = {}
    for key in thermal_points[24][0]:
        source_response = (thermal_points[26][0][key] - thermal_points[24][0][key]) / 2.0
        region_response = (thermal_points[26][1][key] - thermal_points[24][1][key]) / 2.0
        error = abs(source_response - region_response)
        tolerance = max(0.005 * abs(source_response), 1e-5)
        _require_acceptance(math.isfinite(error) and error <= tolerance,
                            f"G8 temperature response {key} error {error:.17g} exceeds {tolerance:.17g}")
        _require_acceptance(abs(source_response) <= 1e-5 or source_response * region_response >= 0,
                            f"G8 temperature response direction reversed for {key}")
        temperature_responses[key] = dict(whole=source_response, regional=region_response,
                                         absolute_error=error, tolerance=tolerance)
    dark_states, _ = uniform(0, 25)
    _check_acceptance_domain(dark_states)
    return dict(accepted=True, failures=[], consistency_record=record, conservation=conservation_results,
                characteristic_points=characteristic_results, bypass=bypass_results,
                temperature_responses=temperature_responses, temperature_precision=thermal_precision)


# Keep at most 64 small immutable inputs/results (under 4 MiB of input bytes).
# A cache stores computed evidence, not permissions. Independent verification
# can request use_cache=False; B3 must reconstruct inputs from its own witness.
@lru_cache(maxsize=64)
def _cached_numerical_candidate(payload_bytes: bytes, solver: str, implementation_identity: tuple):
    payload = json.loads(payload_bytes)
    result = _evaluate_numerical_candidate_physics(
        payload["module"], payload["topology"], payload["definition"], payload["evidence"], solver)
    return json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def evaluate_numerical_assumption_acceptance(
    module: Mapping[str, Any], topology: Mapping[str, Any], definition: Mapping[str, Any],
    evidence: Mapping[str, Any], sources: Mapping[str, Mapping[str, Any]],
    *, solver: str = "lambertw", source_bytes: Mapping[str, bytes] | None = None,
    use_cache: bool = True,
) -> dict[str, Any]:
    """Evaluate a selected candidate from an authenticated registry, without a permit.

    The caller owns registry authentication/selection. This function checks full
    contents, exact revisions, source relationships and real numerical physics.
    accepted means scientific-input acceptance only; execution_allowed is false.
    Submitted records must equal the deterministic recomputation, including PASS.
    """
    from components.topology_library import assert_numerical_assumption_source_bindings
    from .module_iv import MODULE_NONUNIFORM_IV_SOLVER_ID, MODULE_NONUNIFORM_IV_SOLVER_VERSION
    try:
        # Freeze caller-owned mutable data before hashing, lookup or evaluation.
        payload = deepcopy(dict(module=module, topology=topology, definition=definition,
                                evidence=evidence, sources=sources))
        _assert_numerical_candidate_assets(**payload)
        provenance = assert_numerical_assumption_source_bindings(
            payload["module"], payload["evidence"], payload["sources"], source_bytes=source_bytes)
        from engine.module.pvsyst import extract_validated_pvsyst_parameter_set
        source_params = extract_validated_pvsyst_parameter_set(payload["module"])
        for key in REQUIRED_PVSYST_PARAMETERS:
            _finite(source_params[key], label=f"whole-module.{key}")
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=False, allow_nan=False).encode()
        identity = (_NUMERICAL_ACCEPTANCE_POLICY, solver, pvlib.__version__,
                    MODULE_NONUNIFORM_IV_SOLVER_ID, MODULE_NONUNIFORM_IV_SOLVER_VERSION,
                    "rb08b2.acceptance.1")
        if use_cache and len(encoded) <= 65536:
            result = json.loads(_cached_numerical_candidate(encoded, solver, identity))
        else:
            # Same serialization path prevents cached/uncached numeric differences.
            decoded = json.loads(encoded)
            result = _evaluate_numerical_candidate_physics(
                decoded["module"], decoded["topology"], decoded["definition"], decoded["evidence"], solver)
        result["source_provenance"] = provenance
        result["input_fingerprint_sha256"] = _canonical_sha256(dict(
            payload=payload, implementation_identity=identity))
        computed = result.get("consistency_record")
        if computed is not None and payload["evidence"]["consistency_record"] != computed:
            result["accepted"] = False
            result["failures"].append("submitted consistency_record does not equal real-kernel recomputation")
        result["execution_allowed"] = False
        result["evidence_class"] = "NUMERICAL_ASSUMPTION"
        return deepcopy(result)
    except Exception as exc:
        # Schema, kernel/domain and convergence failures all reject a candidate.
        # No exception becomes an availability fallback or a manufacturer claim.
        return dict(accepted=False, execution_allowed=False, evidence_class="NUMERICAL_ASSUMPTION",
                    failures=[f"{type(exc).__name__}: {exc}"])


def validate_numerical_assumption_acceptance(*args, **kwargs) -> dict[str, Any]:
    """Raise a non-fallback scientific integrity error on candidate rejection."""
    from .contract import NumericalAssumptionInputError
    result = evaluate_numerical_assumption_acceptance(*args, **kwargs)
    if not result["accepted"]:
        raise NumericalAssumptionInputError("; ".join(result["failures"]))
    return result
