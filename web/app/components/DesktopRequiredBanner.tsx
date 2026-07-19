export function DesktopRequiredBanner() {
  return (
    <div
      role="alert"
      aria-live="polite"
      className="desktop-required-banner hidden max-[1023px]:block p-lg text-center"
      style={{
        padding: "2rem 1.5rem",
        color: "hsl(var(--foreground))",
        background: "hsl(var(--card))",
        borderRadius: "0.5rem",
      }}
    >
      <h2 className="brand-heading" style={{ marginBottom: "0.5rem" }}>
        Desktop required
      </h2>
      <p style={{ fontSize: "16px", lineHeight: 1.7, opacity: 0.85 }}>
        IntelliBird dashboards require a viewport of at least 1024px. Please
        open on a desktop browser.
      </p>
    </div>
  );
}
