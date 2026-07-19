import { describe, it, expect, vi, beforeEach } from "vitest";

const { upsertMock } = vi.hoisted(() => ({
  upsertMock: vi.fn(),
}));

vi.mock("@/app/api-client", () => ({
  upsertPreset: upsertMock,
}));

import {
  seedPresets,
  DEFAULT_BLUE_PRESET,
  DEFAULT_RED_PRESET,
} from "@/app/lib/seed-presets";

beforeEach(() => {
  upsertMock.mockReset();
  upsertMock.mockResolvedValue({
    id: "p1",
    name: "default-blue",
    query_params: {},
    created_at: "",
    updated_at: "",
  });
  window.sessionStorage.clear();
});

describe("seedPresets", () => {
  it("PUTs default-blue with the locked D-20 payload on first call (role=blue)", async () => {
    await seedPresets("blue");
    expect(upsertMock).toHaveBeenCalledTimes(1);
    expect(upsertMock).toHaveBeenCalledWith("default-blue", DEFAULT_BLUE_PRESET);
    expect(
      window.sessionStorage.getItem("intellibird:preset-seeded-blue"),
    ).toBe("1");
  });

  it("PUTs default-red with the locked D-21 payload on first call (role=red)", async () => {
    await seedPresets("red");
    expect(upsertMock).toHaveBeenCalledTimes(1);
    expect(upsertMock).toHaveBeenCalledWith("default-red", DEFAULT_RED_PRESET);
    expect(
      window.sessionStorage.getItem("intellibird:preset-seeded-red"),
    ).toBe("1");
  });

  it("short-circuits on second call when sessionStorage guard is set", async () => {
    await seedPresets("blue");
    await seedPresets("blue");
    expect(upsertMock).toHaveBeenCalledTimes(1);
  });

  it("does not set sessionStorage guard when upsert fails (retry next session)", async () => {
    upsertMock.mockRejectedValueOnce(new Error("boom"));
    await seedPresets("blue");
    expect(upsertMock).toHaveBeenCalledTimes(1);
    expect(
      window.sessionStorage.getItem("intellibird:preset-seeded-blue"),
    ).toBeNull();
  });

  it("exports the exact D-20 default-blue payload shape", () => {
    expect(DEFAULT_BLUE_PRESET).toEqual({
      source_type: ["nvd", "rss"],
      tlp: ["clear", "green"],
    });
  });

  it("exports the exact D-21 default-red payload shape", () => {
    expect(DEFAULT_RED_PRESET).toEqual({
      source_type: ["taxii", "rss"],
      tlp: ["clear", "green", "amber"],
    });
  });
});
