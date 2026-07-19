import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("@/app/api-client", () => ({
  patchEventTags: vi.fn(),
}));

vi.mock("sonner", () => ({
  toast: { error: vi.fn(), success: vi.fn() },
}));

import { TagEditor } from "@/app/components/TagEditor";
import { toast } from "sonner";
import * as apiClient from "@/app/api-client";

const patchMock = vi.mocked(apiClient.patchEventTags);

beforeEach(() => {
  patchMock.mockReset();
  patchMock.mockResolvedValue({ tags: [] });
  (toast.error as ReturnType<typeof vi.fn>).mockReset();
});

describe("TagEditor", () => {
  it("renders initial chips", () => {
    render(<TagEditor eventId="e1" initialTags={["alpha", "beta"]} />);
    expect(screen.getByText("alpha")).toBeInTheDocument();
    expect(screen.getByText("beta")).toBeInTheDocument();
  });

  it("calls patchEventTags(add) when valid tag is entered + Enter pressed", async () => {
    render(<TagEditor eventId="e1" initialTags={[]} />);
    const input = screen.getByTestId("tag-input");
    await userEvent.type(input, "new-tag{Enter}");
    await waitFor(() => {
      expect(patchMock).toHaveBeenCalledWith("e1", {
        add: ["new-tag"],
        remove: [],
      });
    });
    expect(screen.getByText("new-tag")).toBeInTheDocument();
  });

  it("rejects tags not matching ^[a-z0-9_-]{1,32}$", async () => {
    render(<TagEditor eventId="e1" initialTags={[]} />);
    const input = screen.getByTestId("tag-input");
    await userEvent.type(input, "INVALID TAG!{Enter}");
    // should not fire
    expect(patchMock).not.toHaveBeenCalled();
    expect(screen.queryByText("INVALID TAG!")).not.toBeInTheDocument();
  });

  it("remove × calls patchEventTags(remove)", async () => {
    render(<TagEditor eventId="e1" initialTags={["alpha"]} />);
    const removeBtn = screen.getByTestId("remove-alpha");
    await userEvent.click(removeBtn);
    await waitFor(() => {
      expect(patchMock).toHaveBeenCalledWith("e1", {
        add: [],
        remove: ["alpha"],
      });
    });
    expect(screen.queryByText("alpha")).not.toBeInTheDocument();
  });

  it("reverts chip and toasts on PATCH error (remove)", async () => {
    patchMock.mockRejectedValueOnce(new Error("boom"));
    render(<TagEditor eventId="e1" initialTags={["alpha"]} />);
    const removeBtn = screen.getByTestId("remove-alpha");
    await userEvent.click(removeBtn);
    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledWith(
        "Failed to update tags. Reverted.",
      );
    });
    expect(screen.getByText("alpha")).toBeInTheDocument();
  });

  it("reverts chip and toasts on PATCH error (add)", async () => {
    patchMock.mockRejectedValueOnce(new Error("boom"));
    render(<TagEditor eventId="e1" initialTags={[]} />);
    const input = screen.getByTestId("tag-input");
    await userEvent.type(input, "new-tag{Enter}");
    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledWith(
        "Failed to update tags. Reverted.",
      );
    });
    expect(screen.queryByText("new-tag")).not.toBeInTheDocument();
  });
});
