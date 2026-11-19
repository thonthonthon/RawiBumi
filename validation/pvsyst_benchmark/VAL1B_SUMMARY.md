# VAL1b checkpoint

| Case | Annual grid-energy deviation | Worst monthly deviation | Runtime | Energy verdict |
|---|---:|---:|---:|---|
| P2 Standard | −0.0568% | −0.1242% | 15m58s | PASS |
| P2 High sensitivity | −0.0568% | −0.1242% | 16m30s | PASS |
| P3 Standard | +0.1823% | +0.4140% | 3h20m58s | PASS |
| P3 High sensitivity | +0.1840% | +0.4165% | 3h48m49s | PASS |

Each original cold annual run completed within its approved cap, without retry. Standard remains the headline. P3 High changes the annual comparison by +0.00173 percentage points. Reference data, snapshots and verified packages are retained privately; committed fixtures and tests are synthetic.

P2 and P3 are accepted pending independent review. P2 plant IAM passes. Its horizon component remains outside tolerance but is partly attributed and immaterial under the approved diagnostic: horizon estimate +0.00303%, joint diffuse effect +0.04504%. The superseded absolute-sum diagnostic, 0.08705%, is retained as over-conservative and failed.

**P3 stage attribution is complete under the approved diagnostic policy.** Plant IAM passes (−0.2159% annual, 0.6224% hourly nRMSE). DC wiring loss retains its −1.5794% deviation against a ±1.5% stage limit, classified as "partly attributed (wiring/scalar ordering convention), immaterial": its labelled imposed-reference diagnostic changes annual grid energy by −0.03035%, below 0.05%. Every row and raw reference value is retained; one inadmissible low-light interval has the approved native zero-output certificate. The prior stopped diagnostic remains archived. No diagnostic changes a headline result.

The mandatory P3 inverter attribution measured output above the unchanged anchor envelope equivalent to **0.4770% of upstream DC energy**. This is a converter-stage attribution, including effects subject to clipping, rather than a net-export correction. Opposing stage biases can coexist with a close grid-energy result. No model was fitted or changed to improve agreement.

Single-orientation IAM factors retain interpolation-convention residuals. Ambiguous intermediate factors and unproved ground-optics bases remain unavailable rather than being reported as agreement; source operating DC and native available DC are distinct boundaries. Both P3 presets used the recorded serial memory fallback and required no shadow-union precision fallback. Pool eligibility and memory estimation at this scale remain a separate performance finding. Input conventions and approved geometry exceptions remain documented privately. These benchmarks do not establish production readiness.
