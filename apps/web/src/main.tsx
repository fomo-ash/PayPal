import "ag-grid-community/styles/ag-grid.css";
import "ag-grid-community/styles/ag-theme-quartz.css";
import "./styles.css";

import { lazy, StrictMode, Suspense } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Link, Route, Routes } from "react-router-dom";
import { Layout, Spinner } from "./components";
import { AuthProvider } from "./lib/auth";

// Each page is its own chunk: the sample suite and AG Grid load only where they are used.
const AuthCallback = lazy(() => import("./pages/AuthCallback"));
const Home = lazy(() => import("./pages/Home"));
const JobPage = lazy(() => import("./pages/JobPage"));
const Login = lazy(() => import("./pages/Login"));
const Me = lazy(() => import("./pages/Me"));
const NewJob = lazy(() => import("./pages/NewJob"));
const Review = lazy(() => import("./pages/Review"));
const Verdict = lazy(() => import("./pages/Verdict"));
const Verify = lazy(() => import("./pages/Verify"));

function NotFound() {
  return (
    <div className="empty">
      <h2>Nothing here</h2>
      <Link className="btn" to="/">Back to jobs</Link>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <AuthProvider>
        <Layout>
          <Suspense fallback={<Spinner label="Loading" />}>
          <Routes>
            <Route path="/" element={<Home />} />
            <Route path="/login" element={<Login />} />
            <Route path="/auth/callback" element={<AuthCallback />} />
            <Route path="/jobs/new" element={<NewJob />} />
            <Route path="/jobs/:id" element={<JobPage />} />
            <Route path="/submissions/:id" element={<Verdict />} />
            <Route path="/me" element={<Me />} />
            <Route path="/review" element={<Review />} />
            <Route path="/verify" element={<Verify />} />
            <Route path="*" element={<NotFound />} />
          </Routes>
          </Suspense>
        </Layout>
      </AuthProvider>
    </BrowserRouter>
  </StrictMode>,
);
