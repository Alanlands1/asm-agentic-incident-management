import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { pipelineService } from "@/services/pipeline-service";
import { AgentFeedback } from "@/types/pipeline";
import { FeedbackThumbs } from "./feedback-thumbs";

vi.mock("@/services/pipeline-service", () => ({ pipelineService: { rate: vi.fn().mockResolvedValue({}) } }));
vi.mock("@/lib/view-as", () => ({ usePerson: () => "Alan Test" }));

const props = { ticketId: "AMS-1209", runId: 7, agent: "resolution", onSent: vi.fn() };
const button = (name: string) => screen.getByRole("button", { name });

describe("FeedbackThumbs", () => {
  it("offers correct, partially correct and incorrect", () => {
    render(<FeedbackThumbs {...props} />);
    expect(screen.getByText("Was this result accurate?")).toBeInTheDocument();
    for (const name of ["Correct", "Partially correct", "Incorrect"]) expect(button(name)).toHaveAttribute("aria-pressed", "false");
  });

  it("saves partially correct as 3 stars and asks what could be improved", async () => {
    render(<FeedbackThumbs {...props} />);
    await userEvent.click(button("Partially correct"));
    expect(pipelineService.rate).toHaveBeenCalledWith("AMS-1209", { agent_run_id: 7, stars: 3, reason: "", reviewer: "Alan Test" });
    expect(button("Partially correct")).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("Thank you. What could be improved?")).toBeInTheDocument();
    expect(screen.getByRole("group", { name: "What could be improved" })).toBeInTheDocument();
  });

  it("saves the chosen reasons with the same rating", async () => {
    render(<FeedbackThumbs {...props} />);
    await userEvent.click(button("Incorrect"));
    await userEvent.click(button("Wrong runbook"));
    await userEvent.click(button("Save"));
    expect(pipelineService.rate).toHaveBeenLastCalledWith("AMS-1209", { agent_run_id: 7, stars: 1, reason: "Wrong runbook", reviewer: "Alan Test" });
    expect(button("Saved")).toBeDisabled();
  });

  it("asks for no reasons after correct", async () => {
    render(<FeedbackThumbs {...props} />);
    await userEvent.click(button("Correct"));
    expect(pipelineService.rate).toHaveBeenCalledWith("AMS-1209", expect.objectContaining({ stars: 5 }));
    expect(screen.queryByRole("button", { name: "Wrong runbook" })).not.toBeInTheDocument();
  });

  it("shows a stored 3-star rating as partially correct", () => {
    const given: AgentFeedback = { id: 1, agent_run_id: 7, agent: "resolution", stars: 3, reason: "", reviewer: "Priya", created_at: "2026-11-20T10:00:00Z" };
    render(<FeedbackThumbs {...props} given={given} />);
    expect(button("Partially correct")).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("Priya")).toBeInTheDocument();
  });
});
