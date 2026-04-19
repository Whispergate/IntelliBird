import type { SystemStatus } from "../api-client";

type Props = { status: SystemStatus | null };

/**
 * Pre-auth + credentials-health indicator banner — Phase 8 / INFRA-03 + INFRA-04.
 *
 * Three mutually-exclusive visible states (plus null when everything is green):
 *   1. Decrypt failure  — critical red #b00020, takes precedence over auth warning.
 *   2. Auth disabled + exposed beyond loopback — red #b00020.
 *   3. Auth disabled + loopback only — amber #8a6d00.
 *
 * Not dismissible. Rendered at top of root layout above all page content.
 * Uses inline styles (not shadcn/ui Alert) so it paints before CSS bundles
 * load — deliberate, per UI-SPEC.
 */
export function NoAuthBanner({ status }: Props) {
  // 1. Decrypt failure — highest precedence.
  if (status?.decrypt_check === "failed") {
    return (
      <div
        role="alert"
        aria-live="assertive"
        style={{
          width: "100%",
          padding: "0.75rem 1rem",
          background: "#b00020",
          color: "white",
          fontWeight: 700,
          textAlign: "center",
          fontFamily: "system-ui, sans-serif",
          borderBottom: "2px solid rgba(0,0,0,0.25)",
        }}
      >
        <span>CREDENTIAL DECRYPTION FAILURE</span>
        <span style={{ marginLeft: "0.5rem", fontWeight: 400 }}>
          &mdash; Encrypted source credentials cannot be read under the current
          SECRET_KEY. Run{" "}
          <code
            style={{
              fontFamily:
                "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
              fontSize: 13,
            }}
          >
            POST /api/admin/rekey-credentials
          </code>{" "}
          with{" "}
          <code
            style={{
              fontFamily:
                "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
              fontSize: 13,
            }}
          >
            REKEY_FROM_SECRET
          </code>{" "}
          set to the previous key. See{" "}
          <code
            style={{
              fontFamily:
                "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
              fontSize: 13,
            }}
          >
            docs/ops/secret-rotation.md
          </code>
          .
        </span>
      </div>
    );
  }

  // 2+3. Auth disabled — either exposed (red) or loopback-only (amber).
  if (!status || status.auth_enabled === false) {
    const exposed = status && !status.host_loopback_only;
    const host = status?.host ?? "127.0.0.1";
    return (
      <div
        role="alert"
        aria-live="assertive"
        style={{
          width: "100%",
          padding: "0.75rem 1rem",
          background: exposed ? "#b00020" : "#8a6d00",
          color: "white",
          fontWeight: 700,
          textAlign: "center",
          fontFamily: "system-ui, sans-serif",
          borderBottom: "2px solid rgba(0,0,0,0.25)",
        }}
      >
        <span>IntelliBird &mdash; NO AUTHENTICATION CONFIGURED.</span>
        {exposed ? (
          <span style={{ marginLeft: "0.5rem" }}>
            Service is bound to{" "}
            <code
              style={{
                fontFamily:
                  "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
                fontSize: 13,
              }}
            >
              {host}
            </code>{" "}
            &mdash; exposed beyond loopback. For trusted internal networks
            only. Auth lands in Phase 9.
          </span>
        ) : (
          <span style={{ marginLeft: "0.5rem" }}>
            Bound to 127.0.0.1 only. Do not expose externally before enabling auth.
          </span>
        )}
      </div>
    );
  }

  // 4. Auth enabled and no decrypt failure — render nothing. Phase 9 steady state.
  return null;
}
