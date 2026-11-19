# RawiBumi

RawiBumi is a free, self-hostable, browser-based tool to design and simulate grid-connected rooftop PV: site, roof
geometry, module layout, stringing and inverters, weather, an hourly yearly simulation with near shading, results and a
report. *Bahasa Indonesia: [Beranda](Home-ID).*

## Start here
- [Installation](Installation): run RawiBumi on your own computer.
- [Using RawiBumi](Using-RawiBumi): the ten steps from site to report. The full manual is built into the app at `/manual/`.
- [Weather files](Weather-files): which formats are read, and their time conventions.
- [How RawiBumi works](How-RawiBumi-works): the calculation chain step by step, methods, libraries, validation, what works and what does not, quirks.
- [Engine methods and limits](Engine-methods-and-limits): what the simulation does, how it was checked, and what it does not claim.
- [Architecture](Architecture): how the code is organised.
- [Contributing](Contributing): tests, rules, and how to propose a change.

## Status
Beta: usable end to end, from an empty project to a report; the interface is still being reworked (see the README's
"Known work in progress"). The engine passed an independent audit; results agree with PVsyst within a
fraction of a percent on two real shaded projects. RawiBumi has not yet been compared with measured plant data.

## Licence
Copyright © 2026 Sulthon. GNU Affero General Public License v3.0; see `LICENSE` in the repository.
