"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { SELECT } from "@/components/console/assign-control";
import { apiClient } from "@/lib/api-client";
import { ROLES, setPersona, useSignedIn, useUser, type User } from "@/lib/view-as";

/** For an admin: view the console as another person (their menu, their worklist, their name on what is done). */
export function PersonaSelect() {
  const me = useSignedIn();
  const shown = useUser();
  const router = useRouter();
  const [people, setPeople] = useState<User[]>([]);
  const admin = me?.role === "admin";

  useEffect(() => {
    if (admin) apiClient<User[]>("/auth/users").then(setPeople, () => setPeople([])); // without the list: yourself only
  }, [admin]);

  if (!admin || !me) return null;
  const others = people.filter((p) => p.email !== me.email);
  const label = (role: User["role"]) => ROLES.find((r) => r.value === role)!.label;

  const choose = (email: string) => {
    const next = others.find((p) => p.email === email) ?? null;
    setPersona(next);
    router.push(ROLES.find((r) => r.value === (next ?? me).role)!.home);
  };

  return (
    <select aria-label="View as" value={shown && shown.email !== me.email ? shown.email : ""} onChange={(e) => choose(e.target.value)} className={SELECT}>
      <option value="">Myself ({me.name})</option>
      {/* the chosen person stays listed while the list loads */}
      {(others.length ? others : shown && shown.email !== me.email ? [shown] : []).map((p) => (
        <option key={p.email} value={p.email}>
          {p.name} · {label(p.role)}
        </option>
      ))}
    </select>
  );
}
