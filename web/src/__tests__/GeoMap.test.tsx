import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { GeoMapImpl } from "@/app/components/GeoMapImpl";

// Tests target GeoMapImpl directly — the dynamic wrapper is untestable in jsdom.
// maplibre-gl + pmtiles are mocked globally in vitest.setup.ts.

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/blue",
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("@/app/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/app/api-client")>();
  return {
    ...actual,
    listEvents: vi.fn().mockResolvedValue({ items: [], next_cursor: null, total: 0 }),
  };
});

describe("GeoMap", () => {
  it("renders a container div with provided height", () => {
    render(<GeoMapImpl height={400} />);
    const container = screen.getByTestId("geomap-container");
    expect(container).toBeInTheDocument();
    expect(container).toHaveStyle({ height: "400px" });
  });

  it("renders overlay text when provided", () => {
    render(<GeoMapImpl overlayText="Geo layer loads in." />);
    expect(
      screen.getByText("Geo layer loads in."),
    ).toBeInTheDocument();
  });

  it("does not render overlay when overlayText is null", () => {
    render(<GeoMapImpl overlayText={null} />);
    expect(screen.queryByTestId("geomap-overlay")).not.toBeInTheDocument();
  });

  it("uses default height 50vh when no height prop", () => {
    render(<GeoMapImpl />);
    const container = screen.getByTestId("geomap-container");
    expect(container).toHaveStyle({ height: "50vh" });
  });
});
