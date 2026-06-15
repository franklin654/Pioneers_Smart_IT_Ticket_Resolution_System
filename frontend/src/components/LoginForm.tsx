import React, { useState } from "react";
import { Cpu, Lock, LogIn, AlertTriangle } from "lucide-react";

interface LoginFormProps {
  onSuccess: (token: string) => void;
}

export default function LoginForm({ onSuccess }: LoginFormProps) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!username.trim() || !password.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/api/v1/auth/token", {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: new URLSearchParams({ username, password }).toString(),
      });
      if (res.ok) {
        const data = await res.json();
        // Guard against missing or malformed token in the response (W-4)
        if (data.access_token && typeof data.access_token === "string") {
          onSuccess(data.access_token);
        } else {
          setError("Authentication failed: invalid server response.");
        }
      } else {
        const data = await res.json().catch(() => ({}));
        setError(data?.detail || "Invalid credentials. Please try again.");
      }
    } catch {
      setError("Cannot reach the backend. Is the FastAPI server running?");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-[#02040a] flex items-center justify-center z-50">
      <div className="fixed inset-0 pointer-events-none">
        <div className="absolute top-[-10%] right-[-10%] w-[700px] h-[700px] bg-cyan-500/5 rounded-full blur-[140px]" />
        <div className="absolute bottom-[-10%] left-[-10%] w-[600px] h-[600px] bg-purple-600/5 rounded-full blur-[120px]" />
        <div className="cyber-grid absolute inset-0 opacity-40" />
        <div className="cyber-scanline absolute top-0 w-full" />
      </div>

      <div className="relative z-10 w-full max-w-sm mx-4">
        <div className="glass-container border border-white/10 rounded-2xl p-8 bg-black/50 shadow-2xl backdrop-blur-md flex flex-col gap-6">
          {/* Logo */}
          <div className="flex flex-col items-center gap-3 text-center">
            <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-cyan-400 to-blue-600 flex items-center justify-center shadow-lg shadow-cyan-500/20">
              <Cpu className="w-6 h-6 text-white animate-pulse" />
            </div>
            <div>
              <h1 className="text-xl font-display font-semibold tracking-wide uppercase text-white">
                TicketIQ
              </h1>
              <p className="text-[9px] font-mono uppercase tracking-widest text-slate-400 mt-0.5">
                Autonomous Cognitive Core
              </p>
            </div>
          </div>

          <div className="border-t border-white/5" />

          {/* Form */}
          <form onSubmit={handleSubmit} className="flex flex-col gap-4">
            <div className="flex flex-col gap-1.5">
              <label className="text-[10px] font-mono uppercase tracking-widest text-slate-400 font-bold">
                Username
              </label>
              <input
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="admin"
                autoFocus
                className="w-full bg-slate-950/60 border border-white/10 rounded-xl py-2.5 px-3.5 text-sm text-slate-200 placeholder-slate-600 focus:outline-none focus:border-cyan-400/50 transition-all font-sans"
              />
            </div>

            <div className="flex flex-col gap-1.5">
              <label className="text-[10px] font-mono uppercase tracking-widest text-slate-400 font-bold">
                Password
              </label>
              <div className="relative">
                <Lock className="absolute left-3 top-2.5 w-4 h-4 text-slate-500" />
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••••"
                  className="w-full bg-slate-950/60 border border-white/10 rounded-xl py-2.5 pl-10 pr-3.5 text-sm text-slate-200 placeholder-slate-600 focus:outline-none focus:border-cyan-400/50 transition-all font-sans"
                />
              </div>
            </div>

            {error && (
              <div className="flex items-center gap-2 bg-rose-950/30 border border-rose-500/30 rounded-xl px-3 py-2.5 text-xs text-rose-300 font-sans">
                <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
                <span>{error}</span>
              </div>
            )}

            <button
              type="submit"
              disabled={loading || !username.trim() || !password.trim()}
              className="flex items-center justify-center gap-2 w-full py-2.5 rounded-xl bg-cyan-500/15 border border-cyan-500/40 text-cyan-400 font-mono font-bold text-xs uppercase tracking-wider hover:bg-cyan-500/25 transition-all disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {loading ? (
                <>
                  <span className="w-3.5 h-3.5 border-2 border-cyan-400/30 border-t-cyan-400 rounded-full animate-spin" />
                  Authenticating...
                </>
              ) : (
                <>
                  <LogIn className="w-3.5 h-3.5" />
                  Sign In
                </>
              )}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}
