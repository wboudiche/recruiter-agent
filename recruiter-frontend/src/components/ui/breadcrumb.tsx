import { Link } from "react-router-dom";
import { ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";

interface Crumb {
  label: string;
  to?: string;          // when omitted, rendered as the (current-page) leaf
}

interface Props {
  items: Crumb[];
  className?: string;
}

/**
 * Editorial breadcrumb — uppercase, fine letter-spaced, amber separators.
 * Last crumb is the current page (no link). All others are <Link>s.
 *
 * Example:
 *   <Breadcrumb items={[
 *     { label: "Jobs", to: "/jobs" },
 *     { label: "Senior Data Scientist", to: "/jobs/8" },
 *     { label: "Yale Waller" },     // current page, no `to`
 *   ]} />
 */
export function Breadcrumb({ items, className }: Props) {
  return (
    <nav
      aria-label="Breadcrumb"
      className={cn(
        "flex items-center gap-1.5 text-[11px] uppercase tracking-[0.22em] text-muted-foreground",
        className,
      )}
    >
      {items.map((crumb, idx) => {
        const isLast = idx === items.length - 1;
        const showLink = crumb.to && !isLast;
        return (
          <span key={`${crumb.label}-${idx}`} className="flex items-center gap-1.5 min-w-0">
            {showLink ? (
              <Link
                to={crumb.to!}
                className="truncate transition-colors hover:text-foreground"
              >
                {crumb.label}
              </Link>
            ) : (
              <span
                className={cn("truncate", isLast && "text-foreground")}
                aria-current={isLast ? "page" : undefined}
              >
                {crumb.label}
              </span>
            )}
            {!isLast && (
              <ChevronRight
                className="h-3 w-3 shrink-0 text-[hsl(var(--ed-amber)/0.6)]"
                aria-hidden="true"
              />
            )}
          </span>
        );
      })}
    </nav>
  );
}
