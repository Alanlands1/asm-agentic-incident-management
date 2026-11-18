"use client";

import { useSyncExternalStore } from "react";
import { incidentService } from "@/services/incident-service";
import { Attention } from "@/types/incident";

const POLL_MS = 30_000;

type State = { data: Attention | null; error: string | null };
let state: State = { data: null, error: null };
const listeners = new Set<() => void>();
let timer: ReturnType<typeof setInterval> | null = null;

function emit(next: State) {
  state = next;
  listeners.forEach((l) => l());
}

/** Fetch now; every component using the hook (banner, Incidents page) shares one poll. */
export function refreshAttention() {
  incidentService
    .getAttention()
    .then((data) => emit({ data, error: null }))
    .catch((e: unknown) => emit({ data: state.data, error: e instanceof Error ? e.message : "Couldn't load incidents" }));
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  if (!timer) {
    refreshAttention();
    timer = setInterval(refreshAttention, POLL_MS);
  }
  return () => {
    listeners.delete(listener);
    if (!listeners.size && timer) {
      clearInterval(timer);
      timer = null;
    }
  };
}

const SERVER: State = { data: null, error: null };

export function useAttention(): State & { refresh: () => void } {
  const s = useSyncExternalStore(subscribe, () => state, () => SERVER);
  return { ...s, refresh: refreshAttention };
}
