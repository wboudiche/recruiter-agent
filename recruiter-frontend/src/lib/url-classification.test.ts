import { describe, it, expect } from "vitest";
import { classifyResultUrl } from "./url-classification";

describe("classifyResultUrl", () => {
  it.each([
    // Real LinkedIn profile URLs from a sourcing search — these must pass through.
    "https://www.linkedin.com/in/marie-laval-ds/",
    "https://fr.linkedin.com/in/sergey-stepanyan-57999424",
    "https://uk.linkedin.com/in/solenne-de-pellegars",
    // GitHub profile URLs (not in any block list).
    "https://github.com/karpathy",
    "https://github.com/torvalds",
    // Personal blog / portfolio.
    "https://andrejkarpathy.ai/",
    "https://example.com/about-me",
    // StackOverflow user profiles are people pages.
    "https://stackoverflow.com/users/12345/jane",
  ])("treats %s as a profile", (url) => {
    expect(classifyResultUrl(url).kind).toBe("profile");
  });

  it.each([
    ["https://www.upwork.com/hire/data-scientists/tn/tunis/", "aggregator"],
    ["https://www.bayt.com/en/tunisia/jobs/data-scientist-jobs/", "aggregator"],
    ["https://www.indeed.com/q-data-scientist-jobs.html", "aggregator"],
    ["https://www.glassdoor.com/Jobs/", "aggregator"],
    ["https://www.levels.fyi/t/data-scientist/locations/tunisia", "aggregator"],
    ["https://www.wuzzuf.net/jobs/data-scientist", "aggregator"],
  ])("flags %s as an aggregator", (url) => {
    expect(classifyResultUrl(url).kind).toBe("aggregator");
  });

  it.each([
    "https://www.reddit.com/r/Tunisia/comments/abc/some_thread/",
    "https://www.quora.com/What-are-the-best",
  ])("flags %s as a forum", (url) => {
    expect(classifyResultUrl(url).kind).toBe("forum");
  });

  it("flags LinkedIn /jobs/ as a job-listing, not a profile", () => {
    const r = classifyResultUrl("https://www.linkedin.com/jobs/senior-data-scientist-jobs");
    expect(r.kind).toBe("job-listing");
  });

  it("flags generic /jobs/ paths on unknown hosts as job-listings", () => {
    const r = classifyResultUrl("https://random-company.io/jobs/sde-iii");
    expect(r.kind).toBe("job-listing");
  });

  it("flags StackOverflow questions (not user pages) as a forum", () => {
    const r = classifyResultUrl("https://stackoverflow.com/questions/abc");
    expect(r.kind).toBe("forum");
  });

  it("returns profile for unparseable URLs (defers to backend)", () => {
    expect(classifyResultUrl("not a url").kind).toBe("profile");
  });
});
