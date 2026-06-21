import type { ComponentType } from "react";
import { IntakeTab } from "../features/intake";
import { ResolutionTab } from "../features/resolution";
import { KBTab } from "../features/kb";
import { AgentTab } from "../features/agent-sandbox";
import { AnalyticsTab } from "../features/analytics";

export interface TabRoute {
  id: string;
  label: string;
  icon: string;
  // null for tabs that require injected props (rendered directly in App.tsx)
  component: ComponentType | null;
}

export const TAB_ROUTES: TabRoute[] = [
  { id: "intake", label: "Submit Ticket", icon: "＋", component: IntakeTab },
  { id: "tickets", label: "Ticket Search", icon: "🔍", component: null },
  { id: "resolution", label: "Resolution", icon: "⚡", component: ResolutionTab },
  { id: "kb", label: "Knowledge Base", icon: "📚", component: KBTab },
  { id: "agent", label: "Agent Sandbox", icon: "🔬", component: AgentTab },
  { id: "analytics", label: "Analytics", icon: "📊", component: AnalyticsTab },
];
