import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { FormProvider, useForm } from "react-hook-form";

import { CredentialsField } from "@/app/sources/components/CredentialsField";
import type { SourceFormValues } from "@/app/sources/lib/sourceSchema";

// Helper: wraps CredentialsField in a FormProvider so useFormContext works.
function Wrapper({
  defaultValues,
  children,
}: {
  defaultValues?: Partial<SourceFormValues>;
  children: React.ReactNode;
}) {
  const methods = useForm<SourceFormValues>({
    defaultValues: {
      feed_type: "rss",
      taxii_scheme: "none",
      ...defaultValues,
    } as SourceFormValues,
  });
  return <FormProvider {...methods}>{children}</FormProvider>;
}

// ---------------------------------------------------------------------------
// 1. RSS mode renders no DOM nodes
// ---------------------------------------------------------------------------
describe("CredentialsField - RSS", () => {
  it("RSS mode renders no DOM nodes", () => {
    const { container } = render(
      <Wrapper defaultValues={{ feed_type: "rss" }}>
        <CredentialsField feed_type="rss" mode="add" />
      </Wrapper>,
    );
    expect(container.firstChild).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// 2–3. NVD mode
// ---------------------------------------------------------------------------
describe("CredentialsField - NVD", () => {
  it("NVD add mode renders single password input with autoComplete off", () => {
    render(
      <Wrapper defaultValues={{ feed_type: "nvd" }}>
        <CredentialsField feed_type="nvd" mode="add" />
      </Wrapper>,
    );
    const input = screen.getByLabelText(/NVD API Key/i);
    expect(input).toBeInTheDocument();
    expect(input).toHaveAttribute("type", "password");
    expect(input).toHaveAttribute("autoComplete", "off");
  });

  it("NVD edit mode shows '(unchanged - type to replace)' placeholder", () => {
    render(
      <Wrapper defaultValues={{ feed_type: "nvd" }}>
        <CredentialsField feed_type="nvd" mode="edit" />
      </Wrapper>,
    );
    const input = screen.getByLabelText(/NVD API Key/i);
    expect(input).toHaveAttribute(
      "placeholder",
      "(unchanged - type to replace)",
    );
  });
});

// ---------------------------------------------------------------------------
// 4–8. TAXII mode
// ---------------------------------------------------------------------------
describe("CredentialsField - TAXII", () => {
  it("TAXII mode renders scheme Select and no password inputs for scheme=none", () => {
    render(
      <Wrapper defaultValues={{ feed_type: "taxii", taxii_scheme: "none" }}>
        <CredentialsField feed_type="taxii" mode="add" />
      </Wrapper>,
    );
    expect(screen.getByLabelText(/Auth scheme/i)).toBeInTheDocument();
    expect(screen.queryAllByRole("textbox")).toHaveLength(0);
    // No password inputs visible when scheme=none
    const inputs = document.querySelectorAll('input[type="password"]');
    expect(inputs).toHaveLength(0);
  });

  it("TAXII basic scheme reveals username + password inputs", () => {
    render(
      <Wrapper defaultValues={{ feed_type: "taxii", taxii_scheme: "basic" }}>
        <CredentialsField feed_type="taxii" mode="add" />
      </Wrapper>,
    );
    expect(screen.getByLabelText(/Username/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Password/i)).toBeInTheDocument();
    const passwordInputs = document.querySelectorAll('input[type="password"]');
    expect(passwordInputs).toHaveLength(2);
  });

  it("TAXII bearer scheme reveals single token input", () => {
    render(
      <Wrapper defaultValues={{ feed_type: "taxii", taxii_scheme: "bearer" }}>
        <CredentialsField feed_type="taxii" mode="add" />
      </Wrapper>,
    );
    expect(screen.getByLabelText(/Bearer token/i)).toBeInTheDocument();
    const passwordInputs = document.querySelectorAll('input[type="password"]');
    expect(passwordInputs).toHaveLength(1);
  });

  it("TAXII otx-apikey scheme reveals single API key input", () => {
    render(
      <Wrapper
        defaultValues={{ feed_type: "taxii", taxii_scheme: "otx-apikey" }}
      >
        <CredentialsField feed_type="taxii" mode="add" />
      </Wrapper>,
    );
    expect(screen.getByLabelText(/OTX API key/i)).toBeInTheDocument();
    const passwordInputs = document.querySelectorAll('input[type="password"]');
    expect(passwordInputs).toHaveLength(1);
  });

  it("TAXII edit mode shows '(unchanged - type to replace)' placeholder on all credential inputs", () => {
    render(
      <Wrapper defaultValues={{ feed_type: "taxii", taxii_scheme: "basic" }}>
        <CredentialsField feed_type="taxii" mode="edit" />
      </Wrapper>,
    );
    const passwordInputs = document.querySelectorAll<HTMLInputElement>(
      'input[type="password"]',
    );
    expect(passwordInputs).toHaveLength(2);
    for (const input of passwordInputs) {
      expect(input.placeholder).toBe("(unchanged - type to replace)");
    }
  });
});

// ---------------------------------------------------------------------------
// 9. All credential inputs have autoComplete="off" and spellCheck={false}
// ---------------------------------------------------------------------------
describe("CredentialsField - input attributes", () => {
  it("TAXII basic: all credential inputs have autoComplete=off", () => {
    render(
      <Wrapper defaultValues={{ feed_type: "taxii", taxii_scheme: "basic" }}>
        <CredentialsField feed_type="taxii" mode="add" />
      </Wrapper>,
    );
    const passwordInputs = document.querySelectorAll<HTMLInputElement>(
      'input[type="password"]',
    );
    expect(passwordInputs.length).toBeGreaterThanOrEqual(2);
    for (const input of passwordInputs) {
      expect(input.autocomplete).toBe("off");
    }
  });

  it("NVD: API key input has autoComplete=off", () => {
    render(
      <Wrapper defaultValues={{ feed_type: "nvd" }}>
        <CredentialsField feed_type="nvd" mode="add" />
      </Wrapper>,
    );
    const input = screen.getByLabelText(/NVD API Key/i) as HTMLInputElement;
    expect(input.autocomplete).toBe("off");
  });
});

// ---------------------------------------------------------------------------
// 10. No input has type="text" in any credential context
// ---------------------------------------------------------------------------
describe("CredentialsField - type safety", () => {
  it("no credential input has type='text' in TAXII basic mode", () => {
    render(
      <Wrapper defaultValues={{ feed_type: "taxii", taxii_scheme: "basic" }}>
        <CredentialsField feed_type="taxii" mode="add" />
      </Wrapper>,
    );
    const textInputs = document.querySelectorAll('input[type="text"]');
    expect(textInputs).toHaveLength(0);
  });

  it("no credential input has type='text' in NVD mode", () => {
    render(
      <Wrapper defaultValues={{ feed_type: "nvd" }}>
        <CredentialsField feed_type="nvd" mode="add" />
      </Wrapper>,
    );
    const textInputs = document.querySelectorAll('input[type="text"]');
    expect(textInputs).toHaveLength(0);
  });
});
