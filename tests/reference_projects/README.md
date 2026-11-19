# Reference project boundary


This directory is reserved for redistributable RawiBumi reference-project inputs.


Phase 3.0 freezes the unshaded external benchmark contract in:


```text
tests/benchmarks/phase3_unshaded.yaml
```


The current Meteonorm 8.2 DAT files and PVsyst V8.1.6 reports are user-supplied external
references whose redistribution status is not established, so their raw files are **not**
committed here.


The benchmark contract stores only source-identifying metadata, hashes where available,
extracted engineering targets, and validation invariants.


If a future reference source is confirmed redistributable, a minimized or full fixture may
be added here with provenance and license information.