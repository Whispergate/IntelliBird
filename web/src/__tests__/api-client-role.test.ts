import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { listEvents, getEvent, getEventGraph } from "@/app/api-client";

const fetchMock = vi.fn();

function mockResponse<T>(body: T): Response {
  return {
    ok: true,
    status: 200,
    statusText: "OK",
    json: async () => body,
    text: async () => JSON.stringify(body),
  } as unknown as Response;
}

beforeEach(() => {
  fetchMock.mockReset();
  fetchMock.mockResolvedValue(
    mockResponse({ items: [], next_cursor: null, total: null }),
  );
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function headersSent(callIdx = 0): Record<string, string> {
  const [, init] = fetchMock.mock.calls[callIdx] as [
    string,
    RequestInit | undefined,
  ];
  const hdrs = (init?.headers ?? {}) as Record<string, string>;
  return hdrs;
}

describe("api-client role header contract (D-28)", () => {
  it("listEvents sends X-Dashboard-Role: blue when role='blue'", async () => {
    await listEvents({}, "blue");
    expect(fetchMock).toHaveBeenCalled();
    expect(headersSent()["X-Dashboard-Role"]).toBe("blue");
  });

  it("listEvents sends X-Dashboard-Role: red when role='red'", async () => {
    await listEvents({}, "red");
    expect(headersSent()["X-Dashboard-Role"]).toBe("red");
  });

  it("listEvents omits X-Dashboard-Role when role is undefined (admin surface)", async () => {
    await listEvents({});
    const hdrs = headersSent();
    expect(hdrs["X-Dashboard-Role"]).toBeUndefined();
  });

  it("getEvent sends X-Dashboard-Role when role provided", async () => {
    fetchMock.mockResolvedValueOnce(
      mockResponse({
        id: "e1",
        observed_at: "",
        fetched_at: "",
        source_id: null,
        source_name: null,
        source_type: null,
        stix_id: null,
        stix_type: "indicator",
        title: null,
        description: null,
        tlp: null,
        tags: [],
        attack_techniques: [],
        archived: false,
        visibility: "shared",
        raw_stix: null,
      }),
    );
    await getEvent("evt-1", "red");
    expect(headersSent()["X-Dashboard-Role"]).toBe("red");
  });

  it("getEventGraph sends X-Dashboard-Role when role provided", async () => {
    fetchMock.mockResolvedValueOnce(
      mockResponse({ nodes: [], edges: [], truncated: false }),
    );
    await getEventGraph("evt-1", 2, "blue");
    expect(headersSent()["X-Dashboard-Role"]).toBe("blue");
  });
});
