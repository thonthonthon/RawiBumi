# Engine methods and limits

## What the evidence supports
- The standard hourly path implements its cited methods correctly (independent engine audit, 2026).
- Against PVsyst 8.x on two real shaded projects, annual grid energy agrees within −0.06 % and −0.30 %, and the worst
  month within −0.12 % and −0.46 %. PVsyst is a benchmark, not the truth: agreement shows the same conventions, not
  field accuracy.
- The module model reproduces datasheet STC power within ±0.7 % on 63 real PAN files (median +0.03 %).
- The energy ledger reconciles in every interval of every run, or the run fails.
- Two identical runs give identical numbers; only per-run identifiers differ in the saved package.

## What it does not claim
1. Accuracy against measured plants: no field data has been used yet.
2. That the PVsyst agreement holds generally: two projects, one climate, crystalline modules, hourly data.
3. Mixed-orientation results against an external reference (none exists).
4. Electrical mismatch under uneven shading on the standard path.
5. Inverter thermal behaviour, or operation outside the MPPT window as a physical prediction (such strings block the run).
6. Far-horizon shading (there is no horizon-profile input yet).
7. Sub-hourly simulation, reactive power, power factor or kVA limits.
8. That the default losses describe a real site: they are recommended starting values to review.
9. Daylight-saving time zones.

## Safety rules in the design checks
A string whose cold open-circuit voltage exceeds the inverter's maximum DC voltage blocks the run, as does a string
whose operating voltage leaves the MPPT window. These are design rules, not modelled losses.

## LID defaults

New projects use recommended_defaults.v2: an explicit LID override applies to every circuit; otherwise each circuit uses its module file's finite LID fraction in [0, 1). Missing or invalid values fall back to generic starting values: 0.5 % for TOPCon, HJT, heterojunction or IBC technology; 1.5 % for other crystalline silicon and unknown technology; 0 % for thin film. These are starting values, not measurements: check the datasheet. Clear the input to restore automatic LID. Each run records the per-circuit value and source. Earlier v1 projects retain LID 0 % unless overridden; “Use the current defaults” switches to v2 in one undoable save, preserving overrides. Saved results stay unchanged.
