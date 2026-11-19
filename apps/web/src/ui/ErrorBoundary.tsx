import { Component, type ReactNode } from "react";
import i18n from "../i18n";

export class ErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() {
    return this.state.failed ? <p role="status">{i18n.t("s7d.mapFallback")}</p> : this.props.children;
  }
}
