"""Named simulation-model contracts used by the Phase-1 resolver.

This registry describes model-selection contracts only. Numerical execution belongs to later
engine phases. A model is listed here only when its required canonical inputs and intended
execution behavior are sufficiently defined to make deterministic selection meaningful.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelDescriptor:
    model_id: str
    component_type: str
    model_family: str
    fidelity_rank: int
    source_model_type: str | None
    implementation_status: str
    description: str

    def as_dict(self) -> dict[str, object]:
        return {
            "model_id": self.model_id,
            "component_type": self.component_type,
            "model_family": self.model_family,
            "fidelity_rank": self.fidelity_rank,
            "source_model_type": self.source_model_type,
            "implementation_status": self.implementation_status,
            "description": self.description,
        }


MODULE_PVSYST_SDM = ModelDescriptor(
    model_id="module.pvsyst_singlediode.v6",
    component_type="module",
    model_family="single_diode",
    fidelity_rank=300,
    source_model_type="pvsyst_singlediode",
    implementation_status="validated_contract",
    description=(
        "PVsyst-v6 compatible single-diode model using the validated canonical parameter set."
    ),
)

MODULE_STC_TEMPCO = ModelDescriptor(
    model_id="module.stc_tempco_linear.v0.1",
    component_type="module",
    model_family="stc_temperature_coefficient",
    fidelity_rank=100,
    source_model_type=None,
    implementation_status="resolution_contract",
    description=(
        "Basic module fallback using STC electrical points and explicit temperature "
        "coefficients. It does not claim full IV-curve fidelity."
    ),
)

INVERTER_VOLTAGE_CURVES = ModelDescriptor(
    model_id="inverter.voltage_dependent_efficiency.v0.1",
    component_type="inverter",
    model_family="efficiency_curve",
    fidelity_rank=300,
    source_model_type="voltage_dependent_curves",
    implementation_status="validated_contract",
    description=(
        "Inverter conversion model using DC-voltage-specific Pin/Pout efficiency curves."
    ),
)

INVERTER_VOLTAGE_CURVES_BOUNDED = ModelDescriptor(
    model_id="inverter.voltage_dependent_efficiency.v0.2",
    component_type="inverter",
    model_family="efficiency_curve",
    fidelity_rank=300,
    source_model_type="voltage_dependent_curves",
    implementation_status="validated_contract",
    description="Voltage-dependent conversion with adjacent-envelope-clamped quadratic interpolation.",
)

INVERTER_ONE_DIMENSIONAL_CURVE = ModelDescriptor(
    model_id="inverter.one_dimensional_efficiency.v0.1",
    component_type="inverter",
    model_family="efficiency_curve",
    fidelity_rank=200,
    source_model_type="one_dimensional_curve",
    implementation_status="resolution_contract",
    description="Inverter conversion model using a single load-dependent efficiency curve.",
)

INVERTER_CONSTANT = ModelDescriptor(
    model_id="inverter.constant_efficiency.v0.1",
    component_type="inverter",
    model_family="constant_efficiency",
    fidelity_rank=100,
    source_model_type="constant",
    implementation_status="resolution_contract",
    description="Basic inverter conversion using an explicit constant efficiency.",
)


MODULE_MODELS = {
    descriptor.model_id: descriptor
    for descriptor in (
        MODULE_PVSYST_SDM,
        MODULE_STC_TEMPCO,
    )
}

INVERTER_MODELS = {
    descriptor.model_id: descriptor
    for descriptor in (
        INVERTER_VOLTAGE_CURVES,
        INVERTER_VOLTAGE_CURVES_BOUNDED,
        INVERTER_ONE_DIMENSIONAL_CURVE,
        INVERTER_CONSTANT,
    )
}
