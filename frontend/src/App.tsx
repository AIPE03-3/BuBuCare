import { Navigate, Route, Routes } from 'react-router-dom';
import { AppLayout } from './components/AppLayout';
import { RequireAdmin } from './components/RequireAdmin';
import { RequireAuth } from './components/RequireAuth';
import { EventsProvider } from './hooks/EventsProvider';
import { EventCenter } from './pages/EventCenter';
import { EventDetail } from './pages/EventDetail';
import { HazardDetail } from './pages/HazardDetail';
import { History } from './pages/History';
import { Home } from './pages/Home';
import { Login } from './pages/Login';
import { Monitoring } from './pages/Monitoring';
import { ReportFormPage } from './pages/ReportFormPage';
import { ReportPreview } from './pages/ReportPreview';
import { ReportGeneration } from './pages/ReportGeneration';
import { UserManagement } from './pages/UserManagement';
import { UserDetail } from './pages/UserDetail';

function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />

      <Route
        element={
          <RequireAuth>
            <EventsProvider>
              <AppLayout />
            </EventsProvider>
          </RequireAuth>
        }
      >
        <Route path="/" element={<Home />} />
        <Route path="/monitoring" element={<Monitoring />} />
        <Route path="/events" element={<EventCenter />} />
        <Route path="/events/:id" element={<EventDetail />} />
        <Route path="/hazards/:id" element={<HazardDetail />} />
        <Route path="/reports" element={<ReportGeneration />} />
        <Route path="/reports/:id" element={<ReportFormPage />} />
        <Route path="/reports/:id/preview" element={<ReportPreview />} />
        <Route path="/history" element={<History />} />
        <Route
          path="/users"
          element={
            <RequireAdmin>
              <UserManagement />
            </RequireAdmin>
          }
        />
        <Route
          path="/users/:id"
          element={
            <RequireAdmin>
              <UserDetail />
            </RequireAdmin>
          }
        />
      </Route>

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

export default App;
