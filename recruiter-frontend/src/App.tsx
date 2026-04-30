import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { Toaster } from "sonner";
import { AppShell } from "@/components/layout/app-shell";
import { ThemeProvider } from "@/components/theme/theme-provider";
import IndexRedirect from "@/routes/index";
import JobsList from "@/routes/jobs-list";
import JobsNew from "@/routes/jobs-new";
import JobDetail from "@/routes/job-detail";
import Settings from "@/routes/settings";

interface AppProps {
  noBrowserRouter?: boolean;
}

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
});

export default function App({ noBrowserRouter = false }: AppProps = {}) {
  const tree = (
    <Routes>
      <Route element={<AppShell />}>
        <Route path="/" element={<IndexRedirect />} />
        <Route path="/jobs" element={<JobsList />} />
        <Route path="/jobs/new" element={<JobsNew />} />
        <Route path="/jobs/:jobId" element={<JobDetail />} />
        <Route path="/settings" element={<Settings />} />
      </Route>
    </Routes>
  );

  return (
    <ThemeProvider>
      <QueryClientProvider client={queryClient}>
        {noBrowserRouter ? tree : <BrowserRouter>{tree}</BrowserRouter>}
        <Toaster richColors closeButton />
      </QueryClientProvider>
    </ThemeProvider>
  );
}
