const p = { width: 14, height: 14, viewBox: "0 0 16 16", fill: "none", stroke: "currentColor", strokeWidth: 1.4, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
export const Eye = () => (
  <svg {...p}><path d="M1.5 8s2.4-4.5 6.5-4.5S14.5 8 14.5 8s-2.4 4.5-6.5 4.5S1.5 8 1.5 8Z" /><circle cx="8" cy="8" r="2" /></svg>
);
export const EyeOff = () => (
  <svg {...p}><path d="M2 2l12 12M6.3 4A6.6 6.6 0 0 1 8 3.5C12.1 3.5 14.5 8 14.5 8a11 11 0 0 1-1.9 2.4M10 11.9a6 6 0 0 1-2 .6C3.9 12.5 1.5 8 1.5 8a11 11 0 0 1 2.3-2.8" /></svg>
);
export const Lock = () => (
  <svg {...p}><rect x="3" y="7" width="10" height="7" rx="1" /><path d="M5 7V5a3 3 0 0 1 6 0v2" /></svg>
);
export const Unlock = () => (
  <svg {...p}><rect x="3" y="7" width="10" height="7" rx="1" /><path d="M5 7V5a3 3 0 0 1 5.8-1" /></svg>
);
