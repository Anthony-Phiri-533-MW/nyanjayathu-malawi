import { Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "@/components/AppShell";
import { RequireAuth, RequirePermission } from "@/auth/guards";
import { useAuth } from "@/auth/AuthContext";
import { LoginPage } from "@/pages/LoginPage";
import { DashboardPage } from "@/pages/DashboardPage";
import { AccountPage } from "@/pages/AccountPage";
import { NotFoundPage } from "@/pages/NotFoundPage";
import { UsersPage } from "@/pages/admin/UsersPage";
import { DataSourcesPage } from "@/pages/admin/DataSourcesPage";
import { ThresholdsPage } from "@/pages/admin/ThresholdsPage";
import { AuditPage } from "@/pages/admin/AuditPage";
import { DatasetsPage } from "@/pages/research/DatasetsPage";
import { DatasetDetailPage } from "@/pages/research/DatasetDetailPage";
import { MapPage } from "@/pages/research/MapPage";
import { ProcessingPage } from "@/pages/research/ProcessingPage";
import { IndicatorsPage } from "@/pages/research/IndicatorsPage";
import { AnalysisPage } from "@/pages/research/AnalysisPage";
import { JobsPage } from "@/pages/research/JobsPage";
import { ExportsPage } from "@/pages/research/ExportsPage";
import { AlertsPage } from "@/pages/disaster/AlertsPage";
import { AlertDetailPage } from "@/pages/disaster/AlertDetailPage";
import { ForecastsPage } from "@/pages/disaster/ForecastsPage";
import { ReportsPage } from "@/pages/reports/ReportsPage";
import { PublicDashboardPage } from "@/pages/public/PublicDashboardPage";

/**
 * Routing. Every protected route is wrapped in `RequireAuth` (session) and,
 * where the screen needs a specific capability, `RequirePermission`. These are
 * convenience gates only — the API re-checks every call server-side.
 */
export function App() {
  const { user, ready } = useAuth();

  return (
    <Routes>
      <Route
        path="/login"
        element={ready && user ? <Navigate to="/" replace /> : <LoginPage />}
      />

      {/* Public Data Module — intentionally outside RequireAuth: anyone can
          view published data, and the route itself has no console chrome. */}
      <Route path="/public" element={<PublicDashboardPage />} />

      <Route
        element={
          <RequireAuth>
            <AppShell />
          </RequireAuth>
        }
      >
        <Route path="/" element={<DashboardPage />} />
        <Route path="/account" element={<AccountPage />} />

        {/* Administration */}
        <Route
          path="/admin/users"
          element={
            <RequirePermission permission="admin.users.read">
              <UsersPage />
            </RequirePermission>
          }
        />
        <Route
          path="/admin/data-sources"
          element={
            <RequirePermission permission="admin.data_sources.read">
              <DataSourcesPage />
            </RequirePermission>
          }
        />
        <Route
          path="/admin/thresholds"
          element={
            <RequirePermission permission="admin.thresholds.read">
              <ThresholdsPage />
            </RequirePermission>
          }
        />
        <Route
          path="/admin/audit"
          element={
            <RequirePermission permission="admin.audit.read">
              <AuditPage />
            </RequirePermission>
          }
        />

        {/* Research */}
        <Route
          path="/research/datasets"
          element={
            <RequirePermission permission="research.datasets.read">
              <DatasetsPage />
            </RequirePermission>
          }
        />
        <Route
          path="/research/datasets/:datasetId"
          element={
            <RequirePermission permission="research.datasets.read">
              <DatasetDetailPage />
            </RequirePermission>
          }
        />
        <Route
          path="/research/map"
          element={
            <RequirePermission permission="research.datasets.read">
              <MapPage />
            </RequirePermission>
          }
        />
        <Route
          path="/research/processing"
          element={
            <RequirePermission permission="research.processing.run">
              <ProcessingPage />
            </RequirePermission>
          }
        />
        <Route
          path="/research/indicators"
          element={
            <RequirePermission permission="research.indicators.read">
              <IndicatorsPage />
            </RequirePermission>
          }
        />
        <Route
          path="/research/analysis"
          element={
            <RequirePermission permission="research.indicators.read">
              <AnalysisPage />
            </RequirePermission>
          }
        />
        <Route
          path="/research/jobs"
          element={
            <RequirePermission permission="research.datasets.read">
              <JobsPage />
            </RequirePermission>
          }
        />
        <Route
          path="/research/exports"
          element={
            <RequirePermission permission="research.exports.read">
              <ExportsPage />
            </RequirePermission>
          }
        />

        {/* Disaster response */}
        <Route
          path="/disaster/alerts"
          element={
            <RequirePermission permission="disaster.alerts.read">
              <AlertsPage />
            </RequirePermission>
          }
        />
        <Route
          path="/disaster/alerts/:alertId"
          element={
            <RequirePermission permission="disaster.alerts.read">
              <AlertDetailPage />
            </RequirePermission>
          }
        />
        <Route
          path="/disaster/forecasts"
          element={
            <RequirePermission permission="disaster.alerts.read">
              <ForecastsPage />
            </RequirePermission>
          }
        />

        {/* Report generation */}
        <Route
          path="/reports"
          element={
            <RequirePermission permission="reports.read">
              <ReportsPage />
            </RequirePermission>
          }
        />

        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
