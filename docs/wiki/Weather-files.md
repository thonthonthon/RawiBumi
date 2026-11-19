# Weather files

| Format | Read | Notes |
|---|---|---|
| Built-in provider | Yes | A year of ERA5-based hourly data for the site. |
| TMY3 (`.csv`) | Yes | Typical-year files (for example a Meteonorm TMY3 export). |
| EPW | Yes | EnergyPlus weather. A truncated location header is refused with a reason. |
| PVsyst Standard CSV | Yes | The format the PVsyst benchmark used end to end. |
| Meteonorm `.dat` with headers | Yes | Time reference −30 minutes only; other references are refused with a reason. |
| RawiBumi CSV | Yes | Missing values (`nan`, empty) go to the quality check; infinite values and repeated timestamps are refused. |
| PVsyst `.MET` | No | Export "PVsyst Standard" CSV from PVsyst instead. |
| Meteonorm `.dat` without headers, or the Meteonorm "PVsyst" `.dat` layout | No | Export TMY3 from Meteonorm instead. |

Every import shows the period, step, time zone, distance from the site and a quality check before it is kept. Only the
PVsyst CSV route has been checked end to end against an external reference; the other importers are covered by unit tests.
