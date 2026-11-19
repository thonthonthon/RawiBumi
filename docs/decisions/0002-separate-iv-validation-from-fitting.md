# Decision 0002 — Keep independent IV validation separate from model fitting

**Status:** Accepted for v0.1 implementation  
**Date:** 2026-09-22

## Decision

An IV reference dataset used to validate a PAN-derived module model shall not be used to
modify, refit, tune, or optimize that same model during the validation run.

## Reason

A model fitted to the same measurements used to score it does not provide independent
validation evidence. OpenSIMPV therefore keeps two future workflows conceptually separate:

```text
model creation / fitting
measurement -> fitted parameters

model validation
frozen parameters + separate measurement -> residuals
```

pvlib 0.15.2 provides `fit_pvsyst_iec61853_sandia_2025()`, which is useful for the former
workflow. The v0.1 `IVReferenceDataset` validator implements the latter.

## Consequences

- imported PAN parameters remain frozen during an IV-reference validation run;
- all model residuals are against the pre-existing parameter set;
- validation results carry provenance qualification;
- same-source and synthetic data may pass numerically but cannot set
  `independent_iv_validated`;
- a future IEC 61853 model-fitting workflow must create a new model revision before that model
  can be validated against separate data.
