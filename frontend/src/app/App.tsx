import { useState, useCallback } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { useAuth } from "../features/auth";
import { LoginForm } from "../features/auth";
import { ResolutionTab } from "../features/resolution";
import { TicketSearchTab } from "../features/tickets";
import { TAB_ROUTES } from "./routes";

const SLIDE = {
  initial: { opacity: 0, y: 12 },
  animate: { opacity: 1, y: 0, transition: { duration: 0.2 } },
  exit: { opacity: 0, y: -12, transition: { duration: 0.15 } },
};

export default function App() {
  const { isAuthenticated, username, login, signOut } = useAuth();
  const [activeTab, setActiveTab] = useState(TAB_ROUTES[0].id);
  const [pendingTicketId, setPendingTicketId] = useState<string | null>(null);

  const handleOpenTicket = useCallback((id: string) => {
    setPendingTicketId(id);
    setActiveTab("resolution");
  }, []);

  const handleTabChange = useCallback((id: string) => {
    // Clear pending ticket when user manually navigates away from resolution
    if (id !== "resolution") {
      setPendingTicketId(null);
    }
    setActiveTab(id);
  }, []);

  if (!isAuthenticated) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[var(--color-surface)] px-4">
        <div className="w-full max-w-sm">
          <h1 className="mb-8 text-center text-2xl font-bold tracking-tight text-slate-100">
            TicketIQ
          </h1>
          <LoginForm onLogin={login} />
        </div>
      </div>
    );
  }

  const renderTab = () => {
    if (activeTab === "tickets") {
      return <TicketSearchTab onOpenTicket={handleOpenTicket} />;
    }
    if (activeTab === "resolution") {
      return <ResolutionTab initialTicketId={pendingTicketId} />;
    }
    const route = TAB_ROUTES.find((r) => r.id === activeTab);
    if (!route?.component) return null;
    const ActiveComponent = route.component;
    return <ActiveComponent />;
  };

  return (
    <div className="flex min-h-screen flex-col bg-[var(--color-surface)] text-slate-100">
      {/* Top nav */}
      <header className="border-b border-[var(--color-border)] bg-[var(--color-panel)]">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-4 py-3">
          <span className="text-lg font-bold tracking-tight text-indigo-400">
            TicketIQ
          </span>
          <nav aria-label="Main navigation">
            <ul className="flex gap-1" role="list">
              {TAB_ROUTES.map((route) => (
                <li key={route.id}>
                  <button
                    onClick={() => handleTabChange(route.id)}
                    aria-current={activeTab === route.id ? "page" : undefined}
                    className={`rounded-lg px-3 py-1.5 text-sm font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-indigo-500 ${
                      activeTab === route.id
                        ? "bg-indigo-600/30 text-indigo-300"
                        : "text-slate-400 hover:text-slate-200 hover:bg-slate-700/50"
                    }`}
                  >
                    <span aria-hidden="true" className="mr-1.5">
                      {route.icon}
                    </span>
                    {route.label}
                  </button>
                </li>
              ))}
            </ul>
          </nav>
          <div className="flex items-center gap-3">
            <span className="text-xs text-slate-500">{username}</span>
            <button
              onClick={() => void signOut()}
              className="rounded-lg border border-[var(--color-border)] px-3 py-1.5 text-xs text-slate-400 hover:text-slate-200 focus:outline-none focus:ring-2 focus:ring-indigo-500"
            >
              Sign out
            </button>
          </div>
        </div>
      </header>

      {/* Tab content */}
      <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-6">
        <AnimatePresence mode="wait">
          <motion.div key={activeTab} {...SLIDE}>
            {renderTab()}
          </motion.div>
        </AnimatePresence>
      </main>
    </div>
  );
}
