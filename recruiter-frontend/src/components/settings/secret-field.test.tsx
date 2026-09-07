import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it } from "vitest";
import { SecretField, type SecretValue, UNCHANGED, REVOKED } from "./secret-field";

/** Mirrors how a settings tab drives the field: it owns the value and reads
 *  it back at submit time. */
function Harness({ isSet }: { isSet: boolean }) {
  const [value, setValue] = useState<SecretValue>(UNCHANGED);
  return (
    <>
      <SecretField
        id="test-secret"
        label="GitHub token"
        isSet={isSet}
        value={value}
        onChange={setValue}
        unsetPlaceholder="ghp_…"
      />
      <output data-testid="submitted">
        {value === UNCHANGED ? "<omitted>" : value === REVOKED ? "<empty-string>" : value}
      </output>
    </>
  );
}

describe("SecretField", () => {
  it("submits nothing when the field is untouched", () => {
    render(<Harness isSet />);
    expect(screen.getByTestId("submitted")).toHaveTextContent("<omitted>");
  });

  it("submits the typed value", () => {
    render(<Harness isSet={false} />);
    fireEvent.change(screen.getByLabelText(/^github token$/i), {
      target: { value: "ghp_new" },
    });
    expect(screen.getByTestId("submitted")).toHaveTextContent("ghp_new");
  });

  it("submits an empty string when cleared, which the API treats as revoke", () => {
    render(<Harness isSet />);
    fireEvent.click(screen.getByRole("button", { name: /clear/i }));
    expect(screen.getByTestId("submitted")).toHaveTextContent("<empty-string>");
  });

  it("offers no Clear control when nothing is stored", () => {
    render(<Harness isSet={false} />);
    expect(screen.queryByRole("button", { name: /clear/i })).not.toBeInTheDocument();
  });

  it("says the credential will be removed on save, so Clear is not mistaken for a local reset", () => {
    render(<Harness isSet />);
    fireEvent.click(screen.getByRole("button", { name: /clear/i }));
    expect(screen.getByText(/removed on save/i)).toBeInTheDocument();
  });

  it("lets a clear be undone before saving", () => {
    render(<Harness isSet />);
    fireEvent.click(screen.getByRole("button", { name: /clear/i }));
    fireEvent.click(screen.getByRole("button", { name: /undo/i }));
    expect(screen.getByTestId("submitted")).toHaveTextContent("<omitted>");
  });

  it("never renders the stored secret", () => {
    render(<Harness isSet />);
    const input = screen.getByLabelText(/^github token$/i) as HTMLInputElement;
    expect(input.value).toBe("");
    expect(input.type).toBe("password");
  });
});
