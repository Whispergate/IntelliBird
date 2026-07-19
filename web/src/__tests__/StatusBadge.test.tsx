import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { StatusBadge } from "../../app/sources/components/StatusBadge";
import { TypeBadge } from "../../app/sources/components/TypeBadge";

const BASE_PROPS = {
  last_status: null,
  effective_status: null,
  last_polled_at: null,
  consecutive_failures: 0,
};

// Brand-aligned tests: label (semantic) + title (ISO) are the stable contract.
// Color encoding is validated visually against the brand book, not via brittle
// class-name or hex-string grep - jsdom's style-attribute serialization drops
// some values and normalises hex→rgb.

describe("StatusBadge", () => {
  it("renders OK label", () => {
    render(<StatusBadge {...BASE_PROPS} effective_status="ok" last_polled_at="2026-04-17T10:00:00Z" />);
    expect(screen.getByText("OK")).toBeDefined();
  });

  it("renders RATE LIMITED label", () => {
    render(<StatusBadge {...BASE_PROPS} effective_status="rate_limited" last_polled_at="2026-04-17T10:00:00Z" />);
    expect(screen.getByText("RATE LIMITED")).toBeDefined();
  });

  it("renders HTTP ERROR label", () => {
    render(<StatusBadge {...BASE_PROPS} effective_status="http_error" last_polled_at="2026-04-17T10:00:00Z" />);
    expect(screen.getByText("HTTP ERROR")).toBeDefined();
  });

  it("renders NETWORK ERROR label", () => {
    render(<StatusBadge {...BASE_PROPS} effective_status="network_error" last_polled_at="2026-04-17T10:00:00Z" />);
    expect(screen.getByText("NETWORK ERROR")).toBeDefined();
  });

  it("renders PARSE ERROR label", () => {
    render(<StatusBadge {...BASE_PROPS} effective_status="parse_error" last_polled_at="2026-04-17T10:00:00Z" />);
    expect(screen.getByText("PARSE ERROR")).toBeDefined();
  });

  it("renders SILENT label", () => {
    render(<StatusBadge {...BASE_PROPS} effective_status="silent" last_polled_at="2026-04-17T10:00:00Z" />);
    expect(screen.getByText("SILENT")).toBeDefined();
  });

  it("renders NEVER POLLED when status is null", () => {
    render(<StatusBadge {...BASE_PROPS} />);
    expect(screen.getByText("NEVER POLLED")).toBeDefined();
  });

  it("uses effective_status over last_status when both present", () => {
    render(
      <StatusBadge
        last_status="ok"
        effective_status="silent"
        last_polled_at="2026-04-17T10:00:00Z"
        consecutive_failures={0}
      />
    );
    expect(screen.getByText("SILENT")).toBeDefined();
    expect(screen.queryByText("OK")).toBeNull();
  });

  it("appends '· N fails' when consecutive_failures > 0", () => {
    render(
      <StatusBadge
        {...BASE_PROPS}
        effective_status="ok"
        last_polled_at="2026-04-17T10:00:00Z"
        consecutive_failures={3}
      />
    );
    expect(screen.getByText(/3 fails/)).toBeDefined();
  });

  it("does not append fails suffix when count is 0", () => {
    render(
      <StatusBadge
        {...BASE_PROPS}
        effective_status="ok"
        last_polled_at="2026-04-17T10:00:00Z"
        consecutive_failures={0}
      />
    );
    expect(screen.queryByText(/fails/)).toBeNull();
  });

  it("title attribute contains last_polled_at ISO string", () => {
    const { container } = render(
      <StatusBadge
        {...BASE_PROPS}
        effective_status="ok"
        last_polled_at="2026-04-17T10:00:00Z"
        consecutive_failures={0}
      />
    );
    const wrapper = container.firstChild as HTMLElement;
    expect(wrapper.getAttribute("title")).toBe("2026-04-17T10:00:00Z");
  });

  it("title attribute is 'Never polled' when last_polled_at is null", () => {
    const { container } = render(<StatusBadge {...BASE_PROPS} />);
    const wrapper = container.firstChild as HTMLElement;
    expect(wrapper.getAttribute("title")).toBe("Never polled");
  });
});

describe("TypeBadge", () => {
  it("renders RSS", () => {
    render(<TypeBadge feed_type="rss" />);
    expect(screen.getByText("RSS")).toBeDefined();
  });

  it("renders TAXII", () => {
    render(<TypeBadge feed_type="taxii" />);
    expect(screen.getByText("TAXII")).toBeDefined();
  });

  it("renders NVD", () => {
    render(<TypeBadge feed_type="nvd" />);
    expect(screen.getByText("NVD")).toBeDefined();
  });
});
