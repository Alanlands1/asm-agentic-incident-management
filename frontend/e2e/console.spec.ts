import { expect, test, type Page } from "@playwright/test";

// Every page in the admin menu, and the ticket page of the seeded ticket.
const PAGES = [
  "/", "/lead", "/team", "/my-tickets", "/incidents", "/trends", "/reports", "/tickets", "/review", "/dq-rules", "/dq-rules/execute",
  "/agents/data-quality", "/agents/triage", "/agents/resolution", "/agents/closure", "/agents/knowledge",
  "/settings/jira", "/settings/confluence", "/settings/reference", "/settings/history", "/tickets/AMS-1209",
];

/** Fails the test on any uncaught error in the page. */
function watchErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  return errors;
}

/** Signs in as one of the people seeded by backend/scripts/seed_e2e.py; the cookie stays with the page. */
const signIn = async (page: Page, role: "admin" | "lead" | "engineer") => {
  const res = await page.request.post("/api/v1/auth/login", { data: { email: `${role}@e2e.test`, password: "e2e-password" } });
  expect(res.ok()).toBe(true);
};

test.beforeEach(({ page }) => signIn(page, "admin"));

test.describe("sign-in", () => {
  test("nobody signed in is sent to the sign-in page, and signing in opens the console", async ({ page }) => {
    await page.context().clearCookies();
    await page.goto("/tickets");
    await expect(page).toHaveURL(/\/login$/);
    await page.getByLabel("Email").fill("engineer@e2e.test");
    await page.getByLabel("Password").fill("wrong");
    await page.getByRole("button", { name: "Sign in", exact: true }).click();
    await expect(page.getByText("Wrong email or password.")).toBeVisible();
    await page.getByLabel("Password").fill("e2e-password");
    await page.getByRole("button", { name: "Sign in", exact: true }).click();
    await expect(page).toHaveURL(/\/team$/); // the engineer's home
    await expect(page.getByLabel("View as")).toHaveCount(0); // the persona list is the admin's
    await page.getByRole("button", { name: "Sign out" }).click();
    await expect(page).toHaveURL(/\/login$/);
  });

  test("an admin views the console as another person and comes back", async ({ page }) => {
    await page.goto("/");
    await page.getByLabel("View as").selectOption({ label: "E2E Engineer · Engineer" });
    await expect(page).toHaveURL(/\/team$/); // the engineer's home and menu
    await expect(page.getByRole("link", { name: "Reports" })).toHaveCount(0);
    await page.reload(); // the choice stays
    await expect(page.getByLabel("View as")).toHaveValue("engineer@e2e.test");
    await page.getByLabel("View as").selectOption({ label: "Myself (E2E Admin)" });
    await expect(page).toHaveURL(/\/$/);
    await expect(page.getByRole("link", { name: "Reports" })).toBeVisible();
  });
});

test.describe("smoke", () => {
  for (const path of PAGES) {
    test(`${path} loads`, async ({ page }) => {
      const errors = watchErrors(page);
      await page.goto(path);
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      await expect(page.getByText(/Application error|Unhandled Runtime Error/)).toHaveCount(0);
      expect(errors).toEqual([]);
    });
  }
});

test.describe("ticket page", () => {
  test("rating the suggested fix partially correct is saved and shows in the activity log", async ({ page }) => {
    const errors = watchErrors(page);
    await page.goto("/tickets/AMS-1209");
    await expect(page.getByRole("heading", { name: "Activity log" })).toBeVisible();
    const now = page.locator("#now"); // the step to act on: the suggested fix, open
    await expect(now.getByText("Suggested fix", { exact: true })).toBeVisible();
    await expect(now.getByText("Did the fix resolve the issue?")).toBeVisible();
    await now.getByText("Why this fix was suggested").click(); // the rating sits under the fix's details
    await expect(now.getByText("Was this result accurate?")).toBeVisible();

    const partly = now.getByRole("button", { name: "Partially correct" });
    await partly.click();
    await expect(partly).toHaveAttribute("aria-pressed", "true");
    await expect(now.getByText("Thank you. What could be improved?")).toBeVisible();

    await page.reload(); // stored, not just shown
    await page.locator("#now").getByText("Why this fix was suggested").click();
    await expect(page.locator("#now").getByRole("button", { name: "Partially correct" })).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByText("rated Resolution partially correct")).toBeVisible();
    expect(errors).toEqual([]);
  });

  test("uses the requester wording", async ({ page }) => {
    await page.goto("/tickets/AMS-1209");
    await expect(page.getByRole("button", { name: "Reply to requester" })).toBeVisible();
    await expect(page.getByText("Who did what")).toHaveCount(0);
  });
});

test.describe("reports", () => {
  test("shows the four reports for the chosen period and downloads a CSV", async ({ page }) => {
    const errors = watchErrors(page);
    await page.goto("/reports");
    for (const title of ["Tickets by application", "Agent performance", "Resolution and closure outcomes", "Engineers"])
      await expect(page.getByRole("heading", { name: title })).toBeVisible();
    await expect(page.getByRole("cell", { name: "Knowledge Builder" })).toBeVisible(); // one row per agent

    await page.getByRole("tab", { name: "7 days" }).click();
    await expect(page.getByRole("tab", { name: "7 days" })).toHaveAttribute("aria-selected", "true");

    const agents = page.locator("[data-slot=card]", { has: page.getByRole("heading", { name: "Agent performance" }) });
    const [download] = await Promise.all([page.waitForEvent("download"), agents.getByRole("button", { name: "Download CSV" }).click()]);
    expect(download.suggestedFilename()).toBe("agent-performance-last-7-days.csv");
    expect(errors).toEqual([]);
  });

  test("is for admins only", async ({ page }) => {
    await signIn(page, "lead");
    await page.goto("/reports");
    await expect(page).toHaveURL(/\/lead$/); // a page outside the lead's menu sends them home
    await expect(page.getByRole("link", { name: "Reports" })).toHaveCount(0);
  });
});

test.describe("knowledge builder", () => {
  test("switches between drafts, repeat issues and coverage", async ({ page }) => {
    await page.goto("/agents/knowledge");
    await expect(page.getByRole("heading", { name: /Drafted articles/ })).toBeVisible();
    await page.getByRole("tab", { name: "Repeat issues" }).click();
    await expect(page.getByText("No recurring issues detected.")).toBeVisible();
    await page.getByRole("tab", { name: "Coverage" }).click();
    await expect(page.getByRole("heading", { name: "Coverage per application" })).toBeVisible();
  });
});
