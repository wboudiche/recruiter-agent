/**
 * Editorial spinner — a 1-pixel hairline circle with a single amber
 * dot rotating around it. Pure CSS (no JS animation tick), respects
 * `prefers-reduced-motion`.
 */
import { cn } from "@/lib/utils";

interface SpinnerProps {
  /** Diameter in px. Defaults to 12 (inline-with-text size). */
  size?: number;
  className?: string;
}

export function Spinner({ size = 12, className }: SpinnerProps) {
  return (
    <span
      role="status"
      aria-label="loading"
      className={cn("inline-block align-middle", className)}
      style={{
        width: size,
        height: size,
      }}
    >
      <svg
        viewBox="0 0 24 24"
        width={size}
        height={size}
        className="block"
        style={{
          animation: "ed-spin 1.1s linear infinite",
        }}
      >
        <circle
          cx="12"
          cy="12"
          r="9"
          fill="none"
          stroke="currentColor"
          strokeOpacity="0.25"
          strokeWidth="2"
        />
        <path
          d="M 12 3 a 9 9 0 0 1 9 9"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
        />
      </svg>
      <style>{`
        @keyframes ed-spin {
          to { transform: rotate(360deg); }
        }
        @media (prefers-reduced-motion: reduce) {
          [role="status"] svg { animation: none !important; }
        }
      `}</style>
    </span>
  );
}
