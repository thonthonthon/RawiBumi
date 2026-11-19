# TMY3 adapter


TMY3 import uses pvlib's documented parser and then performs an explicit RawiBumi
normalization from TMY3 interval-end labels to canonical interval-start labels.


Irradiation energy is represented canonically as interval-average W/m2.


See docs/weather-data-foundation.md.