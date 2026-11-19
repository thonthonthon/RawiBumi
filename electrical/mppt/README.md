# MPPT assignment and aggregation


Phase 3.5 introduces explicit string-to-MPPT assignment and analytical parallel aggregation.


Model:


```text
mppt.identical_parallel_mpp.v0.1
```


## Assignment authority


The electrical design is authoritative. Runtime simulation does **not** silently auto-assign
strings.


A deterministic helper is provided:


```text
balanced_string_assignment(...)
```


but it is a suggestion/fixture utility only. The Phase-3 PVsyst reference uses this helper to
create a reproducible RawiBumi analytical assignment because the PVsyst reports expose total
string count but not individual string-to-MPPT wiring.


That RawiBumi assignment is not claimed to reproduce PVsyst's internal wiring.


## Parallel aggregation


For strings that share one electrical MPP voltage:


```text
Vmp_MPPT = common Vmp_string
Voc_MPPT = common Voc_string


Imp_MPPT = sum(Imp_string)
Isc_MPPT = sum(Isc_string)
Pmp_MPPT = sum(Pmp_string)
```


The engine requires identical active state and common Vmp/Voc within explicit numerical
tolerance. If that condition is not met, aggregation stops with an error rather than
pretending that the sum of individual string MPPs is the true common MPPT operating point.


Future mismatch/shading work will require full string IV curves and common-voltage
optimization.


## Constraint flags


Phase 3.5 evaluates but does not enforce or clip against:


- MPPT minimum operating voltage;
- MPPT maximum operating voltage;
- MPPT operating current limit, when independently verified.


Constraint findings are flags only. Actual inverter operating-point limiting and clipping
belong to Phase 3.6.


An unknown current limit remains explicitly unknown. It is not treated as unlimited and is
not inferred from PV-array sizing fields.


## Huawei reference boundary


The current Huawei OND establishes:


```text
NbMPPT   = 10
NbInputs = 20
MPPT voltage = 200..1000 V
```


It does not establish a verified physical input count per MPPT or verified per-MPPT
operating-current limit in the canonical component record.


RawiBumi therefore does not infer:


```text
20 / 10 = 2 inputs per MPPT
```


as a hardware constraint.


The Phase-3 balanced benchmark counts happen to contain at most two strings per tracker, but
that distribution is an analytical fixture, not evidence for the inverter's connector
topology.


Independent MPPT powers may be summed. The engine deliberately does not invent one common
inverter DC voltage by averaging independent MPPT voltages.
### Separable execution (S16)

The API supplies optional canonical compatibility keys to automatic assignment and
rebalance. Each tracker receives one key; verified input capacities, inverter ownership
and the rule against moving unselected strings still apply. Homogeneous automation keeps
its existing distribution. Grouped allocation refuses atomically if usable tracker
capacity is insufficient. Manual assignment remains editable and simulation reports a
plain refusal for heterogeneous strings on one MPPT. The existing analytical MPPT
aggregation and inverter numerics are unchanged. Per-inverter pooled-bank conversion
uses `power_weighted_voltage_efficiency_at_total_inverter_dc_power`; no common DC voltage
is synthesized across trackers or inverters.
