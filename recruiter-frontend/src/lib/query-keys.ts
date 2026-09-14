export const queryKeys = {
  jobs: () => ["jobs"] as const,
  job: (id: number) => ["jobs", id] as const,
  jobApplications: (jobId: number) => ["jobs", jobId, "applications"] as const,
  application: (id: number) => ["applications", id] as const,
  candidate: (id: number) => ["candidates", id] as const,
  chat: (applicationId: number) => ["applications", applicationId, "chat"] as const,
  interviewKit: (applicationId: number) => ["interview-kit", applicationId] as const,
  interviewers: (applicationId: number) => ["interviewers", applicationId] as const,
  userDirectory: () => ["users", "directory"] as const,
  settings: () => ["settings"] as const,
  currentUser: () => ["auth", "me"] as const,
  users: () => ["users"] as const,
};
