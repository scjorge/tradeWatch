import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { useAuth } from "./auth/AuthContext";
import { Loading } from "./components/common";
import { AppLayout } from "./layout/AppLayout";
import { AdminPage } from "./pages/Admin";
import { ForgotPasswordPage, LoginPage, RegisterPage, ResetPasswordPage, VerifyEmailPage } from "./pages/auth/AuthPages";
import { IntegrationsPage } from "./pages/Integrations";
import { NotificationsPage } from "./pages/Notifications";
import { OperationsPage } from "./pages/Operations";
import { OverviewPage } from "./pages/Overview";
import { PortfolioPage } from "./pages/Portfolio";
import { ReportsPage } from "./pages/Reports";
import { SettingsPage } from "./pages/Settings";
import { TradesPage } from "./pages/Trades";

function RequireAuth({ children, permission }: { children: JSX.Element; permission?: string }) {
  const { user, loading, can } = useAuth();
  const location = useLocation();
  if (loading) return <Loading />;
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  if (permission && !can(permission)) return <Navigate to="/" replace />;
  return children;
}

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />
      <Route path="/verify-email" element={<VerifyEmailPage />} />
      <Route path="/forgot-password" element={<ForgotPasswordPage />} />
      <Route path="/reset-password" element={<ResetPasswordPage />} />
      <Route
        element={
          <RequireAuth>
            <AppLayout />
          </RequireAuth>
        }
      >
        <Route index element={<RequireAuth permission="trades:read"><OverviewPage /></RequireAuth>} />
        <Route path="/trades" element={<RequireAuth permission="trades:read"><TradesPage /></RequireAuth>} />
        <Route path="/operations" element={<RequireAuth permission="trades:read"><OperationsPage /></RequireAuth>} />
        <Route path="/portfolio" element={<RequireAuth permission="trades:read"><PortfolioPage /></RequireAuth>} />
        <Route path="/reports" element={<RequireAuth permission="trades:read"><ReportsPage /></RequireAuth>} />
        <Route path="/integrations" element={<RequireAuth permission="integrations:manage"><IntegrationsPage /></RequireAuth>} />
        <Route path="/notifications" element={<RequireAuth permission="notifications:manage"><NotificationsPage /></RequireAuth>} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="/admin" element={<RequireAuth permission="admin:users"><AdminPage /></RequireAuth>} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
