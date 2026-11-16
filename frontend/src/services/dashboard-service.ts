import { apiClient } from "@/lib/api-client";
import { DashboardSummary, Trends } from "@/types/dashboard";

export const dashboardService = {
  /** Counts "today" from the viewer's local midnight. */
  getSummary: () => {
    const midnight = new Date();
    midnight.setHours(0, 0, 0, 0);
    return apiClient<DashboardSummary>(`/dashboard/summary?since=${encodeURIComponent(midnight.toISOString())}`);
  },
  /** The last `days` days, ending today, cut at the viewer's local midnight. */
  getTrends: (days: number) => {
    const first = new Date();
    first.setHours(0, 0, 0, 0);
    first.setDate(first.getDate() - (days - 1));
    return apiClient<Trends>(`/dashboard/trends?days=${days}&since=${encodeURIComponent(first.toISOString())}`);
  },
};
