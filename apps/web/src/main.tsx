import "ag-grid-community/styles/ag-grid.css";
import "ag-grid-community/styles/ag-theme-quartz.css";
import "./styles.css";

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Link, Route, Routes } from "react-router-dom";
import { Layout } from "./components";
import { AuthProvider } from "./lib/auth";
import AuthCallback from "./pages/AuthCallback";
import Home from "./pages/Home";
import JobPage from "./pages/JobPage";
import Login from "./pages/Login";
import Me from "./pages/Me";
import NewJob from "./pages/NewJob";
import Review from "./pages/Review";
import Verdict from "./pages/Verdict";
import Verify from "./pages/Verify";

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
        </Layout>
      </AuthProvider>
    </BrowserRouter>
  </StrictMode>,
);
