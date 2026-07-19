/**
 * OllamaHealthBanner - System-level Ollama health indicator (AI-05).
 * Surface 6 per 17-UI-SPEC.md.
 *
 * Uses inline styles (paint-before-CSS-bundle pattern), mirroring NoAuthBanner.tsx.
 * Two visible states:
 *   - slow: amber banner ("Ollama is responding slowly.")
 *   - down: red banner ("Ollama is unreachable.")
 *
 * Healthy / unknown / not-configured: renders nothing.
 * Not dismissible. Data source: passed as prop from server component (layout.tsx).
 */

type OllamaHealth = "healthy" | "slow" | "down" | "unknown";

interface Props {
  ollamaHealth: OllamaHealth;
}

export function OllamaHealthBanner({ ollamaHealth }: Props) {
  if (ollamaHealth === "slow") {
    return (
      <div
        role="alert"
        aria-live="polite"
        style={{
          width: "100%",
          padding: "0.5rem 1rem",
          background: "#78350f",
          color: "#fef3c7",
          borderBottom: "2px solid #92400e",
          fontFamily: "system-ui, sans-serif",
          fontSize: 14,
        }}
      >
        <span style={{ fontWeight: 600 }}>Ollama is responding slowly.</span>
        <span style={{ marginLeft: "0.5rem", fontWeight: 400 }}>
          Consider phi3:mini or gemma2:2b on CPU-only hosts.
        </span>
      </div>
    );
  }

  if (ollamaHealth === "down") {
    return (
      <div
        role="alert"
        aria-live="assertive"
        style={{
          width: "100%",
          padding: "0.5rem 1rem",
          background: "#7f1d1d",
          color: "#fee2e2",
          borderBottom: "2px solid #991b1b",
          fontFamily: "system-ui, sans-serif",
          fontSize: 14,
        }}
      >
        <span style={{ fontWeight: 600 }}>Ollama is unreachable.</span>
        <span style={{ marginLeft: "0.5rem", fontWeight: 400 }}>
          Run{" "}
          <code
            style={{
              fontFamily: "ui-monospace,monospace",
              fontSize: 13,
            }}
          >
            docker compose --profile ai up
          </code>{" "}
          or switch to a cloud provider in project settings.
        </span>
      </div>
    );
  }

  // healthy / unknown / not-configured - render nothing
  return null;
}
