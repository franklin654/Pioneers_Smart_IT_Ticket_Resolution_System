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
  component: ComponentType;
}

export const TAB_ROUTES: TabRoute[] = [
  { id: "intake", label: "Submit Ticket", icon: "＋", component: IntakeTab },
  { id: "resolution", label: "Resolution", icon: "⚡", component: ResolutionTab },
  { id: "kb", label: "Knowledge Base", icon: "📚", component: KBTab },
  { id: "agent", label: "Agent Sandbox", icon: "🔬", component: AgentTab },
  { id: "analytics", label: "Analytics", icon: "📊", component: AnalyticsTab },
];
