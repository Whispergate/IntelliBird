import "@testing-library/jest-dom/vitest";
import { vi } from "vitest";

// next-auth/react — mock useSession + SessionProvider so TopNav and other
// client components that call useSession() work in jsdom without a real
// NextAuth provider. Returns a null session by default; individual tests that
// need a user can override via vi.mocked(useSession).mockReturnValue(...).
vi.mock("next-auth/react", () => ({
  useSession: vi.fn(() => ({ data: null, status: "unauthenticated" })),
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  SessionProvider: ({ children }: { children: any }) => children,
}));

// Polyfill Element.scrollIntoView — jsdom does not implement it. Radix UI
// Select calls scrollIntoView on the selected option at mount time. Without
// this stub the call throws "candidate?.scrollIntoView is not a function"
// and leaks as an unhandled error in every test that renders a Select.
if (typeof Element !== "undefined" && !Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = () => {};
}

// Polyfill ResizeObserver — required by Radix UI primitives (Select, RadioGroup, Sheet, etc.)
// in jsdom which does not implement it natively.
if (typeof globalThis.ResizeObserver === "undefined") {
  globalThis.ResizeObserver = class ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
}

// jsdom has no Canvas 2D or WebGL context. MapLibre and Cytoscape both try to obtain one at
// module init / render time. Stub getContext globally so jsdom test files that transitively
// import these libs do not throw "Cannot read properties of null (reading '2d')".
if (typeof HTMLCanvasElement !== "undefined") {
  HTMLCanvasElement.prototype.getContext = vi.fn(() => null) as never;
}

// Stub URL.createObjectURL (used by maplibre-gl internally).
if (typeof globalThis.URL !== "undefined" && !globalThis.URL.createObjectURL) {
  globalThis.URL.createObjectURL = vi.fn(() => "blob:mock");
}

// maplibre-gl — default export is the maplibregl namespace. Tests that render GeoMap
// should not attempt a real Map instantiation; Map constructor is a noop returning a
// minimal shape. addProtocol is tracked as a spy so SeedPresets / GeoMap tests can assert
// registration behaviour.
//
// IMPORTANT: The Map constructor must be a regular function (not an arrow function)
// because GeoMapImpl calls `new Map(...)` which requires a constructable function.
// Arrow functions cannot be used with `new` and will throw "is not a constructor".
vi.mock("maplibre-gl", () => {
  const mapInstance = {
    remove: vi.fn(),
    on: vi.fn(),
    off: vi.fn(),
    addControl: vi.fn(),
    addSource: vi.fn(),
    addLayer: vi.fn(),
    setStyle: vi.fn(),
    getSource: vi.fn(),
    easeTo: vi.fn(),
  };
  // Use a regular function so `new Map(...)` works in tests.
  const MapConstructor = vi.fn(function MapMock() { return mapInstance; });
  return {
    default: {
      addProtocol: vi.fn(),
      getProtocol: vi.fn(),
      Map: MapConstructor,
    },
    addProtocol: vi.fn(),
    getProtocol: vi.fn(),
    Map: MapConstructor,
  };
});

// pmtiles — Protocol constructor produces .tile() method bound to MapLibre.
// Must use a regular function (not arrow) since GeoMapImpl calls `new Protocol()`.
vi.mock("pmtiles", () => {
  const tileMethod = vi.fn();
  const ProtocolConstructor = vi.fn(function ProtocolMock() {
    return { tile: tileMethod };
  });
  return { Protocol: ProtocolConstructor };
});

// react-cytoscapejs — default export renders a placeholder div. Tests asserting graph
// mount should query by data-testid="cytoscape-graph".
vi.mock("react-cytoscapejs", () => ({
  default: vi.fn(({ style }: { style?: React.CSSProperties }) => {
    // Return a React element via JSX-compatible object. Vitest + vitejs/plugin-react
    // transpiles this factory file before it runs, so React must be available.
    const React = require("react") as typeof import("react");
    return React.createElement("div", {
      "data-testid": "cytoscape-graph",
      style,
    });
  }),
}));

// cytoscape + cytoscape-dagre — constructor stubs to avoid DOM dependency.
vi.mock("cytoscape", () => ({
  default: Object.assign(vi.fn(), { use: vi.fn() }),
}));
vi.mock("cytoscape-dagre", () => ({ default: {} }));

// supercluster — pin-clustering library used by GeoMapImpl. jsdom cannot execute the
// WebAssembly/native path. Expose a constructor stub whose returned instance implements
// the four methods GeoMapImpl calls.
vi.mock("supercluster", () => {
  const instance = {
    load: vi.fn().mockReturnThis(),
    getClusters: vi.fn(() => []),
    getClusterExpansionZoom: vi.fn(() => 14),
    getLeaves: vi.fn(() => []),
  };
  return {
    default: vi.fn().mockImplementation(() => instance),
  };
});
