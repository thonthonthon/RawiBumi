# PV string electrical aggregation

Phase 3.5 implements analytical series aggregation for the current unshaded,
electrically identical module scope.

Model:

```text
string.identical_series_mpp.v0.1
```

For `N` identical modules in series:

```text
Voc_string = N × Voc_module
Vmp_string = N × Vmp_module

Isc_string = Isc_module
Imp_string = Imp_module

Pmp_string = N × Pmp_module
```

The engine verifies `Pmp = Vmp × Imp` and preserves active/inactive state.

This model is deliberately narrow. It is valid for the Phase-3 unshaded reference where
every module in a string has the same irradiance, temperature, IAM treatment, and electrical
model state.

It is **not** used as an approximation for non-identical modules. Shaded modules, different
orientations, unequal string lengths, bypass-diode states, or other mismatch cases require
future full IV aggregation.

The electrical design remains the source of string identity and module membership; the
runtime aggregation does not auto-create design topology.
