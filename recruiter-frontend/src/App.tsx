import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { Toaster } from "sonner";
import { AppShell } from "@/components/layout/app-shell";
import { useSSE } from "@/lib/sse";
import IndexRedirect from "@/routes/index";
import JobsList from "@/routes/jobs-list";
import JobsNew from "@/routes/jobs-new";
import JobDetail from "@/routes/job-detail";
import ApplicationDetail from "@/routes/application-detail";
import Login from "@/routes/login";
import Settings from "@/routes/settings";

interface AppProps {
  noBrowserRouter?: boolean;
}

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
});

function SSEMounter() {
  useSSE();
  return null;
}

export default function App({ noBrowserRouter = false }: AppProps = {}) {
  const tree = (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route element={<AppShell />}>
        <Route path="/" element={<IndexRedirect />} />
        <Route path="/jobs" element={<JobsList />} />
        <Route path="/jobs/new" element={<JobsNew />} />
        <Route path="/jobs/:jobId" element={<JobDetail />} />
        <Route path="/applications/:appId" element={<ApplicationDetail />} />
        <Route path="/settings" element={<Settings />} />
      </Route>
    </Routes>
  );

  return (
    <QueryClientProvider client={queryClient}>
      <SSEMounter />
      {noBrowserRouter ? tree : <BrowserRouter>{tree}</BrowserRouter>}
      <Toaster richColors closeButton theme="dark" />
    </QueryClientProvider>
  );
}
