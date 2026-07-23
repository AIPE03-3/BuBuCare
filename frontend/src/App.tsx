import { Navigate, Route, Routes } from 'react-router-dom';
import { AppLayout } from './components/AppLayout';
import { RequireAdmin } from './components/RequireAdmin';
import { RequireAuth } from './components/RequireAuth';
import { RequirePasswordChanged } from './components/RequirePasswordChanged';
import { EventsProvider } from './hooks/EventsProvider';
import { EventCenter } from './pages/EventCenter';
import { EventDetail } from './pages/EventDetail';
import { ForceChangePassword } from './pages/ForceChangePassword';
import { HazardDetail } from './pages/HazardDetail';
import { History } from './pages/History';
import { HistoryEventDetail } from './pages/HistoryEventDetail';
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

      {/* 強制改密碼頁：需登入，但不套 RequirePasswordChanged（否則旗標 True 會自我跳轉成無限迴圈） */}
      <Route
        path="/force-change-password"
        element={
          <RequireAuth>
            <ForceChangePassword />
          </RequireAuth>
        }
      />

      <Route
        element={
          <RequireAuth>
            <RequirePasswordChanged>
              <EventsProvider>
                <AppLayout />
              </EventsProvider>
            </RequirePasswordChanged>
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
        <Route path="/history/:id" element={<HistoryEventDetail />} />
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
