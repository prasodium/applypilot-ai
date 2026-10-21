import { NavLink, Route, Routes } from "react-router-dom";
import { api } from "./api/client";
import { Notice, useAsync } from "./components/ui";
import Activity from "./pages/Activity";
import ApplicationReview from "./pages/ApplicationReview";
import Applications from "./pages/Applications";
import Dashboard from "./pages/Dashboard";
import JobDetail from "./pages/JobDetail";
import Jobs from "./pages/Jobs";
import Profile from "./pages/Profile";
import ResumeStudio from "./pages/ResumeStudio";
import Settings from "./pages/Settings";

const NAV = [
  ["/", "Dashboard"], ["/profile", "Profile"], ["/resume", "Résumé studio"], ["/jobs", "Jobs"],
  ["/applications", "Applications"], ["/activity", "Activity"], ["/settings", "Settings"],
] as const;

export default function App() {
  const { data: settings } = useAsync(api.settings);
  return (
    <div className="min-h-screen">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-white focus:p-2">
        Skip to content
      </a>
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3">
          <span className="text-lg font-bold text-indigo-800">ApplyPilot AI</span>
          <nav aria-label="Main" className="flex flex-wrap gap-1">
            {NAV.map(([to, label]) => (
              <NavLink key={to} to={to} end={to === "/"} className={({ isActive }) => `rounded-md px-3 py-1.5 text-sm font-medium ${isActive ? "bg-indigo-100 text-indigo-900" : "text-slate-700 hover:bg-slate-100"}`}>
                {label}
              </NavLink>
            ))}
          </nav>
        </div>
        {settings?.ai_demo_mode && (
          <div className="mx-auto max-w-6xl px-4 pb-3">
            <Notice tone="warn">
              <strong>Demo mode.</strong> The AI provider is the deterministic mock and the only automated site is a local mock employer. Generated text is labelled
              DEMO and nothing is ever sent to a real employer.
            </Notice>
          </div>
        )}
      </header>
      <main id="main" className="mx-auto max-w-6xl px-4 py-6">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/profile" element={<Profile />} />
          <Route path="/resume" element={<ResumeStudio />} />
          <Route path="/jobs" element={<Jobs />} />
          <Route path="/jobs/:id" element={<JobDetail />} />
          <Route path="/applications" element={<Applications />} />
          <Route path="/applications/:id" element={<ApplicationReview />} />
          <Route path="/activity" element={<Activity />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="*" element={<p>Page not found.</p>} />
        </Routes>
      </main>
    </div>
  );
}
