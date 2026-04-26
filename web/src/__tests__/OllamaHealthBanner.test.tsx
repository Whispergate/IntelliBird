// Owned by: 17-09-PLAN
// OllamaHealthBanner — Surface 6 per 17-UI-SPEC.md.

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { OllamaHealthBanner } from "@/app/components/OllamaHealthBanner";

describe("OllamaHealthBanner (17-09)", () => {
  describe("slow state", () => {
    it("renders amber banner with role=alert", () => {
      render(<OllamaHealthBanner ollamaHealth="slow" />);
      const banner = screen.getByRole("alert");
      expect(banner).toBeTruthy();
    });

    it("renders aria-live=polite for slow state", () => {
      render(<OllamaHealthBanner ollamaHealth="slow" />);
      const banner = screen.getByRole("alert");
      expect(banner.getAttribute("aria-live")).toBe("polite");
    });

    it("renders exact UI-SPEC copy for slow state", () => {
      render(<OllamaHealthBanner ollamaHealth="slow" />);
      expect(screen.getByText("Ollama is responding slowly.")).toBeTruthy();
      expect(
        screen.getByText(/Consider phi3:mini or gemma2:2b on CPU-only hosts/),
      ).toBeTruthy();
    });
  });

  describe("down state", () => {
    it("renders red banner with role=alert", () => {
      render(<OllamaHealthBanner ollamaHealth="down" />);
      const banner = screen.getByRole("alert");
      expect(banner).toBeTruthy();
    });

    it("renders aria-live=assertive for down state", () => {
      render(<OllamaHealthBanner ollamaHealth="down" />);
      const banner = screen.getByRole("alert");
      expect(banner.getAttribute("aria-live")).toBe("assertive");
    });

    it("renders exact UI-SPEC copy for down state", () => {
      render(<OllamaHealthBanner ollamaHealth="down" />);
      expect(screen.getByText("Ollama is unreachable.")).toBeTruthy();
      expect(screen.getByText(/docker compose --profile ai up/)).toBeTruthy();
    });
  });

  describe("non-visible states", () => {
    it("renders nothing for healthy state", () => {
      const { container } = render(<OllamaHealthBanner ollamaHealth="healthy" />);
      expect(container.firstChild).toBeNull();
    });

    it("renders nothing for unknown state", () => {
      const { container } = render(<OllamaHealthBanner ollamaHealth="unknown" />);
      expect(container.firstChild).toBeNull();
    });
  });
});
