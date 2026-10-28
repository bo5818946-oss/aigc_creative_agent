import { BrowserRouter, Route, Routes } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import { HealthProvider } from "./lib/health";
import { HomePage } from "./pages/Home";
import { LibraryPage } from "./pages/Library";
import { NewProjectPage } from "./pages/NewProject";
import { ProjectPage } from "./pages/Project";
import { SettingsPage } from "./pages/Settings";
import { NotFoundPage } from "./pages/NotFound";

export function App() {
  return (
    <BrowserRouter>
      <HealthProvider>
        <AppShell>
          <Routes>
            <Route path="/" element={<HomePage />} />
            <Route path="/new" element={<NewProjectPage />} />
            <Route path="/projects/:projectId" element={<ProjectPage />} />
            <Route path="/library" element={<LibraryPage />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="*" element={<NotFoundPage />} />
          </Routes>
        </AppShell>
      </HealthProvider>
    </BrowserRouter>
  );
}
