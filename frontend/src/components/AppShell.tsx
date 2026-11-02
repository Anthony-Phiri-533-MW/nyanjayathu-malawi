import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useState } from "react";
import {
  Activity,
  AlertTriangle,
  BarChart3,
  Boxes,
  CloudRain,
  Database,
  FileDown,
  FileText,
  Gauge,
  Globe,
  LayoutDashboard,
  ListChecks,
  Map,
  ScrollText,
  SlidersHorizontal,
  Users,
  type LucideIcon,
} from "lucide-react";
import { useAuth } from "@/auth/AuthContext";
import { Button } from "@/components/ui/Button";
import { cn } from "@/lib/cn";

interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  /** Shown only when the user holds this permission. */
  permission?: string;
}

interface NavSection {
  title: string;
  items: NavItem[];
}

const SECTIONS: NavSection[] = [
  {
    title: "Overview",
    items: [
      { to: "/", label: "Dashboard", icon: LayoutDashboard },
      { to: "/public", label: "Public dashboard", icon: Globe },
    ],
  },
  {
    title: "Administration",
    items: [
      { to: "/admin/users", label: "Users & roles", icon: Users, permission: "admin.users.read" },
      { to: "/admin/data-sources", label: "Data sources", icon: Database, permission: "admin.data_sources.read" },
      { to: "/admin/thresholds", label: "Thresholds", icon: SlidersHorizontal, permission: "admin.thresholds.read" },
      { to: "/admin/audit", label: "Audit log", icon: ScrollText, permission: "admin.audit.read" },
    ],
  },
  {
    title: "Research",
    items: [
      { to: "/research/datasets", label: "Datasets", icon: Boxes, permission: "research.datasets.read" },
      { to: "/research/map", label: "Map", icon: Map, permission: "research.datasets.read" },
      { to: "/research/processing", label: "Preprocessing", icon: Activity, permission: "research.processing.run" },
      { to: "/research/indicators", label: "Indicators", icon: Gauge, permission: "research.indicators.read" },
      { to: "/research/analysis", label: "Analysis", icon: BarChart3, permission: "research.indicators.read" },
      { to: "/research/jobs", label: "Jobs", icon: ListChecks, permission: "research.datasets.read" },
      { to: "/research/exports", label: "Exports", icon: FileDown, permission: "research.exports.download" },
    ],
  },
  {
    title: "Disaster response",
    items: [
      { to: "/disaster/alerts", label: "Alerts", icon: AlertTriangle, permission: "disaster.alerts.read" },
      { to: "/disaster/forecasts", label: "Forecast values", icon: CloudRain, permission: "disaster.alerts.read" },
    ],
  },
  {
    title: "Reports",
    items: [
      { to: "/reports", label: "Reports", icon: FileText, permission: "reports.read" },
    ],
  },
];

export function AppShell() {
  const { user, can, logout } = useAuth();
  const navigate = useNavigate();
  const [menuOpen, setMenuOpen] = useState(false);

  const visibleSections = SECTIONS.map((section) => ({
    ...section,
    items: section.items.filter((item) => !item.permission || can(item.permission)),
  })).filter((section) => section.items.length > 0);

  const primaryRole = user?.roles[0] ?? "";

  return (
    <div className="flex min-h-screen bg-canvas">
      <aside className="hidden w-64 shrink-0 flex-col border-r border-border bg-surface lg:flex">
        <div className="flex items-center gap-2 border-b border-border px-5 py-4">
          <span className="flex h-8 w-8 items-center justify-center rounded-md bg-water-700 text-sm font-semibold text-white">
            LW
          </span>
          <div className="leading-tight">
            <p className="text-sm font-semibold text-ink">LakeWatch</p>
            <p className="text-xs text-muted">Lake Malawi monitoring</p>
          </div>
        </div>

        <nav className="flex-1 space-y-6 overflow-y-auto px-3 py-4">
          {visibleSections.map((section) => (
            <div key={section.title}>
              <p className="px-2 pb-2 text-xs font-semibold uppercase tracking-wide text-muted">
                {section.title}
              </p>
              <ul className="space-y-0.5">
                {section.items.map((item) => (
                  <li key={item.to}>
                    <NavLink
                      to={item.to}
                      end={item.to === "/"}
                      className={({ isActive }) =>
                        cn(
                          "flex items-center gap-2.5 rounded-md px-2.5 py-2 text-sm transition-colors",
                          isActive
                            ? "bg-water-50 font-medium text-water-700"
                            : "text-ink-soft hover:bg-canvas",
                        )
                      }
                    >
                      {({ isActive }) => (
                        <>
                          <item.icon
                            size={16}
                            className={isActive ? "text-water-700" : "text-muted"}
                          />
                          <span>{item.label}</span>
                          {/* 10% accent: a single marker for the active item. */}
                          {isActive ? (
                            <span className="ml-auto h-1.5 w-1.5 rounded-full bg-signal-400" />
                          ) : null}
                        </>
                      )}
                    </NavLink>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </nav>

        <div className="border-t border-border px-4 py-3 text-xs text-muted">
          <p className="font-medium text-ink-soft">{user?.full_name}</p>
          <p className="truncate">{user?.email}</p>
          <p className="mt-1 capitalize">{primaryRole.replace(/_/g, " ")}</p>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-between gap-3 border-b border-border bg-surface px-4 py-3 lg:px-6">
          <div className="flex items-center gap-3">
            <button
              type="button"
              className="btn-secondary px-2 py-1 text-xs lg:hidden"
              onClick={() => setMenuOpen((v) => !v)}
              aria-expanded={menuOpen}
            >
              Menu
            </button>
            <div className="lg:hidden">
              <p className="text-sm font-semibold">LakeWatch</p>
            </div>
          </div>

          <div className="flex items-center gap-3">
            <div className="hidden text-right sm:block">
              <p className="text-sm font-medium text-ink">{user?.full_name}</p>
              <p className="text-xs capitalize text-muted">
                {user?.roles.join(", ").replace(/_/g, " ")}
              </p>
            </div>
            <Button
              variant="secondary"
              size="sm"
              onClick={() => {
                logout();
                navigate("/login", { replace: true });
              }}
            >
              Sign out
            </Button>
          </div>
        </header>

        {menuOpen ? (
          <nav className="space-y-4 border-b border-border bg-surface px-4 py-3 lg:hidden">
            {visibleSections.map((section) => (
              <div key={section.title}>
                <p className="pb-1 text-xs font-semibold uppercase tracking-wide text-muted">
                  {section.title}
                </p>
                <ul className="space-y-0.5">
                  {section.items.map((item) => (
                    <li key={item.to}>
                      <NavLink
                        to={item.to}
                        end={item.to === "/"}
                        onClick={() => setMenuOpen(false)}
                        className={({ isActive }) =>
                          cn(
                            "block rounded-md px-2.5 py-2 text-sm",
                            isActive ? "bg-water-50 text-water-700" : "text-ink-soft",
                          )
                        }
                      >
                        {item.label}
                      </NavLink>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </nav>
        ) : null}

        <main className="min-w-0 flex-1 px-4 py-6 lg:px-8">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
