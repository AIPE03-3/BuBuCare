import { Navigate, Route, Routes } from 'react-router-dom';
import { AppLayout } from './components/AppLayout';
import { RequireAdmin } from './components/RequireAdmin';
import { RequireAuth } from './components/RequireAuth';
import { EventsProvider } from './hooks/EventsProvider';
import { EventCenter } from './pages/EventCenter';
import { EventDetail } from './pages/EventDetail';
import { History } from './pages/History';
import { Home } from './pages/Home';
import { Login } from './pages/Login';
import { MLOps } from './pages/MLOps';
import { Monitoring } from './pages/Monitoring';
import { ReportFormPage } from './pages/ReportFormPage';
import { ReportGeneration } from './pages/ReportGeneration';
import { Settings } from './pages/Settings';

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
        <Route path="/reports" element={<ReportGeneration />} />
        <Route path="/reports/:id" element={<ReportFormPage />} />
        <Route path="/history" element={<History />} />
        <Route
          path="/mlops"
          element={
            <RequireAdmin>
              <MLOps />
            </RequireAdmin>
          }
        />
        <Route
          path="/settings"
          element={
            <RequireAdmin>
              <Settings />
            </RequireAdmin>
          }
        />
      </Route>

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

export default App;
