import { Navigate } from "react-router-dom";

export default function IndexRedirect() {
  return <Navigate to="/jobs" replace />;
}
