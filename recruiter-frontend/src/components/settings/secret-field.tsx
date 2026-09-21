import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

/** Field left alone — the tab must omit it from the payload entirely, so an
 *  unrelated save never clobbers a stored credential. */
export const UNCHANGED = Symbol("unchanged");
/** Explicit revoke — the tab sends "", which the API turns into a NULL column. */
export const REVOKED = Symbol("revoked");

export type SecretValue = typeof UNCHANGED | typeof REVOKED | string;

/** Serialise for the request body: `undefined` means "leave this key out".
 *
 *  A typed value is trimmed, and a whitespace-only entry serialises to
 *  `undefined` rather than to the empty string: since "" now means revoke, a
 *  stray space would otherwise delete a credential. Deleting one is what the
 *  Clear button is for, and that path is deliberately two-step. */
export function secretToPayload(value: SecretValue): string | undefined {
  if (value === UNCHANGED) return undefined;
  if (value === REVOKED) return "";
  return value.trim() || undefined;
}

interface Props {
  id: string;
  label: string;
  /** Whether a credential is currently stored — drives the Clear affordance. */
  isSet: boolean;
  value: SecretValue;
  onChange: (next: SecretValue) => void;
  /** Placeholder shown when nothing is stored yet, e.g. "ghp_…". */
  unsetPlaceholder?: string;
  help?: React.ReactNode;
}

/** A stored credential with a way back out.
 *
 *  Every secret input used to be hand-rolled per tab around
 *  `if (value) body.field = value`, which silently made revoking impossible:
 *  a blank field was indistinguishable from "unchanged", so a key could be
 *  overwritten but never removed. Keeping the three states in one component
 *  fixes that once instead of nine times. */
export function SecretField({
  id, label, isSet, value, onChange, unsetPlaceholder, help,
}: Props) {
  const revoked = value === REVOKED;
  const typed = typeof value === "string" && value.length > 0;

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-2">
        <Label htmlFor={id}>{label}</Label>
        {isSet && !revoked && !typed && (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-auto px-2 py-1 text-xs"
            aria-label={`Clear ${label}`}
            onClick={() => onChange(REVOKED)}
          >
            Clear
          </Button>
        )}
        {revoked && (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-auto px-2 py-1 text-xs"
            aria-label={`Undo clearing ${label}`}
            onClick={() => onChange(UNCHANGED)}
          >
            Undo
          </Button>
        )}
      </div>
      <Input
        id={id}
        type="password"
        autoComplete="off"
        disabled={revoked}
        placeholder={
          revoked
            ? "will be removed on save"
            : isSet
              ? "•••••• (set)"
              : unsetPlaceholder
        }
        value={typed ? (value as string) : ""}
        onChange={(e) => onChange(e.target.value)}
      />
      {revoked && (
        <p className="text-xs text-warning">
          Stored credential will be removed on save.
        </p>
      )}
      {help && <p className="text-xs text-muted-foreground">{help}</p>}
    </div>
  );
}
