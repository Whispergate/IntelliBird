import type { SystemStatus } from "../api-client";

type Props = { status: SystemStatus | null };

/**
 * Unavoidable M1 no-auth warning banner.
 *
 * Rendered from the Server Component root layout so it is present on
 * every route. Intentionally NOT dismissible in M1 — removing it
 * requires editing this file. See PITFALLS C-1 and CONTEXT specifics.
 */
export function NoAuthBanner({ status }: Props) {
  const exposed = status && !status.host_loopback_only;
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
      <span>
        IntelliBird M1 &mdash; NO AUTHENTICATION CONFIGURED.
      </span>
      {exposed ? (
        <span style={{ marginLeft: "0.5rem" }}>
          Service is bound to <code>{status!.host}</code> &mdash; exposed
          beyond loopback. For trusted internal networks only. Auth lands in M2.
        </span>
      ) : (
        <span style={{ marginLeft: "0.5rem" }}>
          Bound to 127.0.0.1 only. Do not expose externally before M2.
        </span>
      )}
    </div>
  );
}
