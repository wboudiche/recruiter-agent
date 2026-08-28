/** Shared copy for the "you can't do this as a viewer" notices scattered
 * across read-only UI. `action` is the specific thing being withheld, e.g.
 * "create jobs" or "edit criteria". */
export function readOnlyNotice(action: string): string {
  return `Read-only access — ask an admin for a recruiter account to ${action}.`;
}
