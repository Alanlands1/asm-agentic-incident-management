import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { pipelineService } from "@/services/pipeline-service";
import { PipelineTicket } from "@/types/pipeline";
import { RequesterEmail } from "./requester-email";

vi.mock("@/services/pipeline-service", () => ({
  pipelineService: {
    draftEmail: vi.fn().mockResolvedValue({ subject: "Resolved: payslips & PDFs", body: "Hello Meera,\n\nFixed.\n\nIT Support" }),
    addComment: vi.fn().mockResolvedValue({}),
  },
}));
vi.mock("@/lib/view-as", () => ({ usePerson: () => "Alan Test" }));

const ticket = { id: "AMS-1209", reporter_name: "Meera Nair", reporter_email: "meera@contoso.com" } as unknown as PipelineTicket;
const show = (ready: string | null = null, toJira = true, onSent = vi.fn()) =>
  render(<RequesterEmail ticket={ticket} ready={ready} toJira={toJira} source="Jira" onSent={onSent} />);

describe("RequesterEmail", () => {
  it("waits for a complete closure note", () => {
    show("Save a complete closure note first.");
    expect(screen.getByRole("button", { name: "Draft email" })).toBeDisabled();
    expect(screen.getByText("Save a complete closure note first.")).toBeInTheDocument();
  });

  it("drafts an editable email addressed to the requester", async () => {
    show();
    await userEvent.click(screen.getByRole("button", { name: "Draft email" }));
    expect(pipelineService.draftEmail).toHaveBeenCalledWith("AMS-1209");
    expect(screen.getByLabelText("Subject")).toHaveValue("Resolved: payslips & PDFs");
    expect(screen.getByLabelText("Message")).toHaveValue("Hello Meera,\n\nFixed.\n\nIT Support");
    expect(screen.getByText("To: Meera Nair <meera@contoso.com>")).toBeInTheDocument();
    const mail = screen.getByRole("link", { name: "Open in email app" });
    expect(mail).toHaveAttribute("href", expect.stringContaining("mailto:meera@contoso.com?subject=Resolved%3A%20payslips%20%26%20PDFs"));
    expect(screen.getByRole("button", { name: "Redraft" })).toBeEnabled();
  });

  it("posts the edited message as a reply on Jira only when asked", async () => {
    const onSent = vi.fn();
    show(null, true, onSent);
    await userEvent.click(screen.getByRole("button", { name: "Draft email" }));
    const body = screen.getByLabelText("Message");
    await userEvent.clear(body);
    await userEvent.type(body, "Hello Meera, all fixed.");
    expect(pipelineService.addComment).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Post as reply on Jira" }));
    expect(pipelineService.addComment).toHaveBeenCalledWith("AMS-1209", "Alan Test", "Hello Meera, all fixed.", true);
    expect(onSent).toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Posted on Jira" })).toBeDisabled();
  });

  it("copies the subject and the message separately, or both at once", async () => {
    const user = userEvent.setup();
    show(null, false);
    await user.click(screen.getByRole("button", { name: "Draft email" }));
    expect(screen.queryByRole("button", { name: "Post as reply on Jira" })).not.toBeInTheDocument(); // writing to Jira is off

    await user.click(screen.getByRole("button", { name: "Copy subject" }));
    expect(await navigator.clipboard.readText()).toBe("Resolved: payslips & PDFs");
    expect(screen.getByRole("button", { name: "Copy subject" })).toHaveTextContent("Copied");

    await user.click(screen.getByRole("button", { name: "Copy message" }));
    expect(await navigator.clipboard.readText()).toBe("Hello Meera,\n\nFixed.\n\nIT Support");
    expect(screen.getByRole("button", { name: "Copy subject" })).toHaveTextContent("Copy"); // only the last copy is marked

    await user.click(screen.getByRole("button", { name: "Copy all" }));
    expect(await navigator.clipboard.readText()).toBe("Subject: Resolved: payslips & PDFs\n\nHello Meera,\n\nFixed.\n\nIT Support");
    expect(screen.getByRole("button", { name: "Copied" })).toBeInTheDocument();
  });

  it("shows the reason when the draft fails", async () => {
    vi.mocked(pipelineService.draftEmail).mockRejectedValueOnce(new Error("The model is switched off, so no draft can be written"));
    show();
    await userEvent.click(screen.getByRole("button", { name: "Draft email" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The model is switched off");
  });
});
