"use client";

import { Suspense, useEffect, useId, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { ApiError, apiClient } from "@/lib/api-client";
import { ROLES, setUser, useSignedIn, type User } from "@/lib/view-as";

// Why the way back from Atlassian ended here (?error=…, set by the API's callback)
const ATLASSIAN_ERRORS: Record<string, string> = {
  no_access: "Your Atlassian account has no access to this console. Ask an admin to add your email.",
  atlassian: "Couldn't sign in with Atlassian. Try again.",
};

/** Sign in with email and password, or with Atlassian; the API sets the session cookie. */
export default function LoginPage() {
  return (
    <Suspense>
      <LoginForm />
    </Suspense>
  );
}

function LoginForm() {
  const router = useRouter();
  const fromAtlassian = ATLASSIAN_ERRORS[useSearchParams().get("error") ?? ""] ?? null;
  const [atlassian, setAtlassian] = useState(false);
  useEffect(() => {
    apiClient<{ atlassian: boolean }>("/auth/providers").then((p) => setAtlassian(p.atlassian), () => setAtlassian(false));
  }, []);
  const user = useSignedIn();
  const id = useId();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Already signed in (or just now): on to their home page
  useEffect(() => {
    if (user) router.replace(ROLES.find((r) => r.value === user.role)!.home);
  }, [user, router]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      setUser(await apiClient<User>("/auth/login", { method: "POST", body: JSON.stringify({ email, password }) }));
    } catch (err) {
      setError(err instanceof ApiError && err.status === 401 ? "Wrong email or password." : "Couldn't sign in. Try again.");
      setBusy(false);
    }
  };

  return (
    // Two panels, as in the 19 Nov reference design: the brand on the left, signing in on the right
    <main className="flex min-h-screen items-center justify-center bg-gradient-to-br from-primary to-foreground p-4 text-foreground">
      <Card className="grid w-full max-w-3xl gap-0 overflow-hidden p-0 md:grid-cols-2">
        <div className="hidden flex-col justify-between gap-8 bg-primary p-8 text-primary-foreground md:flex">
          <div className="flex flex-col gap-2">
            <span className="font-serif text-3xl font-semibold leading-none">AMS Console</span>
            <span className="text-[13px] opacity-90">Incident quality, triage and resolution in one place.</span>
          </div>
          <AgentHub />
        </div>
        <div className="flex flex-col gap-4 py-8">
        <CardHeader>
          <CardTitle>
            <h1 className="font-serif text-2xl font-semibold leading-none">Sign in</h1>
          </CardTitle>
          <CardDescription>Use your email and password{atlassian ? ", or your Atlassian account" : ""}.</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={submit} className="flex flex-col gap-4">
            <div className="flex flex-col gap-1.5">
              <label htmlFor={`${id}-email`} className="text-[13px] font-semibold">
                Email
              </label>
              <Input id={`${id}-email`} type="email" autoComplete="username" required autoFocus value={email} onChange={(e) => setEmail(e.target.value)} />
            </div>
            <div className="flex flex-col gap-1.5">
              <label htmlFor={`${id}-password`} className="text-[13px] font-semibold">
                Password
              </label>
              <Input id={`${id}-password`} type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
            </div>
            {(error ?? fromAtlassian) && (
              <Alert variant="destructive">
                <AlertDescription>{error ?? fromAtlassian}</AlertDescription>
              </Alert>
            )}
            <Button type="submit" disabled={busy || user === undefined}>
              {busy ? "Signing in…" : "Sign in"}
            </Button>
            {atlassian && (
              // A full page load: the API sends the browser to Atlassian and back
              <Button type="button" variant="outline" onClick={() => (window.location.href = "/api/v1/auth/atlassian/start")}>
                Sign in with Atlassian
              </Button>
            )}
          </form>
        </CardContent>
        </div>
      </Card>
    </main>
  );
}

const AGENTS = [
  { label: "Data Quality", x: 100, y: 22 },
  { label: "Triage", x: 178, y: 100 },
  { label: "Resolution", x: 100, y: 178 },
  { label: "Knowledge", x: 22, y: 100 },
];

/** The agents around the ticket they work on. Decoration only. */
function AgentHub() {
  return (
    <svg viewBox="-30 0 260 200" aria-hidden="true" className="w-full max-w-[280px] self-center" fill="none" stroke="currentColor">
      {AGENTS.map((a) => (
        <line key={a.label} x1="100" y1="100" x2={a.x} y2={a.y} strokeWidth="1" opacity="0.5" />
      ))}
      <circle cx="100" cy="100" r="22" strokeWidth="1.5" />
      <text x="100" y="104" textAnchor="middle" fontSize="11" fontWeight="600" fill="currentColor" stroke="none">
        Ticket
      </text>
      {AGENTS.map((a) => (
        <g key={a.label}>
          <circle cx={a.x} cy={a.y} r="5" fill="currentColor" stroke="none" />
          <text x={a.x} y={a.y + (a.y > 100 ? 18 : a.y < 100 ? -10 : 18)} textAnchor="middle" fontSize="10" fill="currentColor" stroke="none">
            {a.label}
          </text>
        </g>
      ))}
    </svg>
  );
}
