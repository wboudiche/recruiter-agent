/**
 * Heuristic: is this URL clearly a job-board / aggregator / forum page
 * rather than a single candidate's profile?
 *
 * Used to short-circuit the "Add" button on the Search tab — adding an
 * aggregator URL creates a candidate row that the extractor can never
 * meaningfully populate, because the page isn't about one person.
 *
 * Hostname check is suffix-based so subdomains (fr.linkedin.com, www.bayt.com)
 * are caught. The LinkedIn special-case lets /in/ profiles through but
 * blocks /jobs/ posts.
 */

const AGGREGATOR_HOSTS = [
  "upwork.com",
  "bayt.com",
  "indeed.com",
  "glassdoor.com",
  "monster.com",
  "levels.fyi",
  "ziprecruiter.com",
  "careerbuilder.com",
  "dice.com",
  "wellfound.com",
  "angel.co",
  "naukri.com",
  "jobstreet.com",
  "remoterocketship.com",
  "wuzzuf.net",
  "tunisietravail.net",
  "emploitunisie.com",
];

const FORUM_HOSTS = [
  "reddit.com",
  "quora.com",
  "ycombinator.com",
];

const STACK_HOSTS = [
  "stackoverflow.com", // /jobs only; /users/ is a profile (let it through)
];

export type UrlClassification =
  | { kind: "profile" }
  | { kind: "aggregator"; reason: string }
  | { kind: "forum"; reason: string }
  | { kind: "job-listing"; reason: string };

export function classifyResultUrl(rawUrl: string): UrlClassification {
  let url: URL;
  try {
    url = new URL(rawUrl);
  } catch {
    return { kind: "profile" }; // unparseable — leave it to the backend
  }
  const host = url.hostname.toLowerCase();
  const path = url.pathname.toLowerCase();

  // LinkedIn: /in/ is a profile, /jobs/ is a job posting, /pulse/ is a blog.
  if (host.endsWith("linkedin.com")) {
    if (path.startsWith("/in/")) return { kind: "profile" };
    if (path.startsWith("/jobs/")) {
      return { kind: "job-listing", reason: "Job posting" };
    }
    return { kind: "profile" }; // unknown LinkedIn path — let backend decide
  }

  // StackOverflow: /users/ is a profile, /jobs is dead, anything else is content.
  if (STACK_HOSTS.some((h) => host.endsWith(h))) {
    if (path.startsWith("/users/")) return { kind: "profile" };
    return { kind: "forum", reason: "Q&A page, not a profile" };
  }

  if (FORUM_HOSTS.some((h) => host.endsWith(h))) {
    return { kind: "forum", reason: "Forum thread, not a profile" };
  }

  if (AGGREGATOR_HOSTS.some((h) => host.endsWith(h))) {
    return { kind: "aggregator", reason: "Job board, not a profile" };
  }

  // Generic path-based hints: any URL whose path starts with /jobs/, /job/,
  // /careers/, /salaries/ is almost certainly not a person page.
  if (/^\/(jobs?|careers?|salaries|hiring)\b/.test(path)) {
    return { kind: "job-listing", reason: "Job/career page, not a profile" };
  }

  return { kind: "profile" };
}
