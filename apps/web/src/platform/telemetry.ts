/**
 * Product telemetry interface. A no-op by default: self-hosted installs send
 * nothing. Phase 8 (TSE-hosted) installs a sink after the user opts in.
 *
 * Event catalogue rules: event names are fixed below; properties are counts,
 * sizes, ids of steps or features, and durations. Never put personal data,
 * project names, coordinates or file contents in an event.
 */
export type TelemetryEvent =
  | "project.opened"
  | "project.created"
  | "step.viewed"
  | "command.run"
  | "pane.toggled"
  | "pane.focus"
  | "layout.filled"
  | "simulation.started"
  | "simulation.finished"
  | "export.downloaded";

export type TelemetryProps = Record<string, string | number | boolean>;
type Sink = (event: TelemetryEvent, props: TelemetryProps) => void;

let sink: Sink | null = null;

export function track(event: TelemetryEvent, props: TelemetryProps = {}): void {
  if (!sink) return;
  try {
    sink(event, props);
  } catch {
    // Telemetry must never break the workstation.
  }
}

export function setTelemetrySink(next: Sink | null): void {
  sink = next;
}
