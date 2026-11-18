"use client";

import { useState, useEffect, useCallback } from "react";
import { DQRun, DQRunCreateInput, DQRunDetail } from "@/types/dq";
import { dqService } from "@/services/dq-service";

export function useDQRuns() {
  const [runs, setRuns] = useState<DQRun[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const fetchRuns = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await dqService.getRuns();
      setRuns(data);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load runs");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchRuns();
  }, [fetchRuns]);

  const triggerRun = async (input: DQRunCreateInput) => {
    const created = await dqService.createRun(input);
    await fetchRuns();
    return created;
  };

  const revertRun = async (id: number) => {
    const reverted = await dqService.revertRun(id);
    await fetchRuns();
    return reverted;
  };

  const getRunDetail = async (id: number): Promise<DQRunDetail> => {
    return dqService.getRunDetail(id);
  };

  return {
    runs,
    loading,
    error,
    fetchRuns,
    triggerRun,
    revertRun,
    getRunDetail,
  };
}
