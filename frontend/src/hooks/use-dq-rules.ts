"use client";

import { useState, useEffect, useCallback } from "react";
import { DQRule, DQRuleCreateInput, DQRuleUpdateInput, DQRuleFilterParams } from "@/types/dq";
import { dqService } from "@/services/dq-service";

export function useDQRules(initialFilters?: DQRuleFilterParams) {
  const [rules, setRules] = useState<DQRule[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [filters, setFilters] = useState<DQRuleFilterParams | undefined>(initialFilters);

  const fetchRules = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await dqService.getRules(filters);
      setRules(data);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load DQ rules");
    } finally {
      setLoading(false);
    }
  }, [filters]);

  useEffect(() => {
    fetchRules();
  }, [fetchRules]);

  const createRule = async (payload: DQRuleCreateInput) => {
    const created = await dqService.createRule(payload);
    await fetchRules();
    return created;
  };

  const updateRule = async (id: number, payload: DQRuleUpdateInput) => {
    const updated = await dqService.updateRule(id, payload);
    await fetchRules();
    return updated;
  };

  const toggleRule = async (id: number, isEnabled: boolean) => {
    // Optimistic UI update
    setRules((prev) =>
      prev.map((r) => (r.id === id ? { ...r, is_enabled: isEnabled } : r))
    );
    try {
      const updated = await dqService.toggleRule(id, isEnabled);
      setRules((prev) => prev.map((r) => (r.id === id ? updated : r)));
      return updated;
    } catch (err) {
      await fetchRules();
      throw err;
    }
  };

  const deleteRule = async (id: number) => {
    const deleted = await dqService.deleteRule(id);
    await fetchRules();
    return deleted;
  };

  return {
    rules,
    loading,
    error,
    filters,
    setFilters,
    fetchRules,
    createRule,
    updateRule,
    toggleRule,
    deleteRule,
  };
}
