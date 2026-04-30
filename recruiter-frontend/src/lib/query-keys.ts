export const queryKeys = {
  jobs: () => ["jobs"] as const,
  job: (id: number) => ["jobs", id] as const,
  jobApplications: (jobId: number) => ["jobs", jobId, "applications"] as const,
  application: (id: number) => ["applications", id] as const,
  settings: () => ["settings"] as const,
};
