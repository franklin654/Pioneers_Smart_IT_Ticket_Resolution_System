import { useState, type FormEvent } from "react";

interface Props {
  onLogin: (username: string, password: string) => Promise<unknown>;
}

export function LoginForm({ onLogin }: Props) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      await onLogin(username, password);
    } catch {
      setError("Invalid credentials. Please try again.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-[var(--color-surface)]">
      <div className="w-full max-w-sm rounded-xl border border-[var(--color-border)] bg-[var(--color-panel)] p-8 shadow-xl">
        <h1 className="mb-6 text-center text-2xl font-semibold text-slate-100">
          TicketIQ
        </h1>

        <form onSubmit={(e) => void handleSubmit(e)} noValidate>
          <div className="mb-4">
            <label
              htmlFor="username"
              className="mb-1 block text-sm text-slate-300"
            >
              Username
            </label>
            <input
              id="username"
              type="text"
              autoComplete="username"
              required
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="w-full rounded-lg border border-[var(--color-border)] bg-slate-800 px-3 py-2 text-sm text-slate-100 placeholder-slate-500 focus:border-indigo-500 focus:outline-none"
              placeholder="admin"
            />
          </div>

          <div className="mb-6">
            <label
              htmlFor="password"
              className="mb-1 block text-sm text-slate-300"
            >
              Password
            </label>
            <input
              id="password"
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full rounded-lg border border-[var(--color-border)] bg-slate-800 px-3 py-2 text-sm text-slate-100 placeholder-slate-500 focus:border-indigo-500 focus:outline-none"
              placeholder="••••••••"
            />
          </div>

          {error && (
            <p role="alert" className="mb-4 text-sm text-rose-400">
              {error}
            </p>
          )}

          <button
            type="submit"
            disabled={loading}
            className="w-full rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-indigo-500"
          >
            {loading ? "Signing in…" : "Sign in"}
          </button>
        </form>
      </div>
    </div>
  );
}
