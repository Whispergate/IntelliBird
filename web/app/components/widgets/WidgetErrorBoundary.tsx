"use client";

import { Component, type ReactNode } from "react";
import { Card, CardContent } from "@/components/ui/card";

type State = { hasError: boolean };

export class WidgetErrorBoundary extends Component<
  { children: ReactNode; label?: string },
  State
> {
  state: State = { hasError: false };

  static getDerivedStateFromError(): State {
    return { hasError: true };
  }

  componentDidCatch(error: Error): void {
    // eslint-disable-next-line no-console
    console.error(`[WidgetErrorBoundary:${this.props.label ?? ""}]`, error);
  }

  render() {
    if (this.state.hasError) {
      return (
        <Card
          role="region"
          aria-label={this.props.label ?? "Widget"}
          className="p-4"
          style={{ minHeight: 120 }}
        >
          <CardContent className="p-0">
            <p
              data-testid="widget-error"
              className="text-sm text-muted-foreground"
              style={{ fontSize: 16 }}
            >
              Widget unavailable. Check console.
            </p>
          </CardContent>
        </Card>
      );
    }
    return this.props.children;
  }
}
