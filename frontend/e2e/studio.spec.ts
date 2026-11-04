import { test, expect } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import path from "node:path";

test("import → validate → simulate → optimize → compare → export → reopen", async ({
  page,
  request,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Three ways into the studio" }),
  ).toBeVisible();
  await mkdir("../docs/evidence", { recursive: true });
  await page.screenshot({
    path: "../docs/evidence/workspace.png",
    fullPage: true,
  });
  // Exercise a real file import from the server's transparent sample dataset.
  const samples = await (await request.get("/api/v1/samples")).json();
  const source = samples.find((s: { key: string }) => s.key === "operations");
  await page.getByLabel("Import BPMN file").setInputFiles({
    name: "operations.bpmn",
    mimeType: "application/xml",
    buffer: Buffer.from(source.xml),
  });
  await expect(
    page.getByRole("heading", { level: 1, name: source.name }),
  ).toBeVisible();
  await expect(
    page.locator('.djs-element[data-element-id="c_chain"]'),
  ).toBeVisible();
  await page.screenshot({ path: "../docs/evidence/model.png", fullPage: true });
  await page
    .getByRole("button", { name: "Validate model", exact: true })
    .click();
  await expect(
    page.getByText("Structure valid · supported subset"),
  ).toBeVisible();
  await page.getByRole("button", { name: "Configure simulation" }).click();
  await page.getByLabel("Technician capacity").fill("2");
  await page.getByLabel("Time unit", { exact: true }).selectOption("hours");
  await page
    .getByRole("button", { name: "Run baseline simulation", exact: true })
    .click();
  await expect(page.locator(".experiment .status-succeeded")).toBeVisible();
  await expect(page.locator(".metric-strip")).toContainText("13");
  await page
    .getByRole("button", { name: "Open fixed-resource optimizer" })
    .click();
  await page
    .getByRole("button", {
      name: "Run fixed-resource optimization",
      exact: true,
    })
    .click();
  await expect(page.locator(".experiment .status-succeeded")).toBeVisible();
  await expect(page.locator(".result-banner .status-optimal")).toBeVisible();
  await expect(page.locator(".metric-strip")).toContainText("11");
  await page.screenshot({
    path: "../docs/evidence/optimization.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: "Compare", exact: true }).click();
  const options = await page
    .getByLabel("Reference experiment", { exact: true })
    .locator("option")
    .evaluateAll((items) =>
      items.map((o) => (o as HTMLOptionElement).value).filter(Boolean),
    );
  await page
    .getByLabel("Reference experiment", { exact: true })
    .selectOption(options[0]);
  await page
    .getByLabel("Comparison experiment", { exact: true })
    .selectOption(options[1]);
  await page.getByRole("button", { name: "Compare runs" }).click();
  await expect(
    page.getByText("identical assumptions", { exact: true }),
  ).toBeVisible();
  await page
    .locator(".compare-grid .timeline tbody .text-button")
    .first()
    .click();
  await expect(
    page.getByRole("heading", { level: 1, name: source.name }),
  ).toBeVisible();
  await expect(page.locator(".inspector code")).toHaveText("a_short");
  await page.getByRole("button", { name: "Reports", exact: true }).click();
  const report = page
    .getByRole("link", { name: "PDF report", exact: true })
    .first();
  const href = await report.getAttribute("href");
  const pdf = await request.get(href!);
  expect(pdf.status()).toBe(200);
  expect((await pdf.body()).subarray(0, 4).toString()).toBe("%PDF");
  const download = page.waitForEvent("download");
  await report.click();
  expect((await download).suggestedFilename()).toMatch(/report\.pdf$/);
  await page.reload();
  await page.getByRole("button", { name: "Reports", exact: true }).click();
  await expect(
    page.getByRole("link", { name: "PDF report", exact: true }),
  ).toHaveCount(2);
  expect(errors).toEqual([]);
});

test("sample XOR, explicit routing, mobile view and unsafe labels", async ({
  page,
  request,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await page.getByRole("button", { name: /02 Loan review/ }).click();
  await expect(
    page.getByRole("heading", { level: 1, name: "Loan review" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Toggle navigation" }).click();
  await page.getByRole("button", { name: "Simulate", exact: true }).click();
  await page.getByLabel("decision route").selectOption("flow_4");
  await page
    .getByRole("button", { name: "Run baseline simulation", exact: true })
    .click();
  await expect(page.locator(".experiment .status-succeeded")).toBeVisible();
  await expect(page.locator(".timeline tbody")).toContainText(
    "Send decline notice",
  );
  await expect(page.locator(".timeline tbody")).not.toContainText(
    "Prepare approved offer",
  );
  const overflow = await page.evaluate(() => ({
    width: window.innerWidth,
    scroll: document.documentElement.scrollWidth,
    elements: [...document.querySelectorAll("body *")]
      .map((el) => ({
        tag: el.tagName,
        class: el.className.toString(),
        right: el.getBoundingClientRect().right,
        width: el.getBoundingClientRect().width,
      }))
      .filter((el) => el.right > window.innerWidth + 1)
      .slice(0, 20),
  }));
  expect(overflow.scroll, JSON.stringify(overflow)).toBeLessThanOrEqual(
    overflow.width,
  );
  await page.screenshot({
    path: "../docs/evidence/mobile.png",
    fullPage: true,
  });
  await request.post("/api/v1/projects", {
    data: { name: '<img src=x onerror="alert(1)">' },
  });
  await page.goto("/");
  expect(await page.locator('img[src="x"]').count()).toBe(0);
});

test("optional NLP draft requires explicit review with mocked extraction", async ({
  page,
  request,
}) => {
  const samples = await (await request.get("/api/v1/samples")).json();
  const sample = samples[0];
  await page.route("**/api/v1/health", async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    body.provider = {
      configured: true,
      model: "mock",
      destination: "mock.example",
      notice: "Test provider. Only submitted description is sent.",
    };
    await route.fulfill({ json: body });
  });
  await page.route("**/api/v1/generation/extract", (route) =>
    route.fulfill({
      json: {
        ir: sample.ir,
        diagnostics: [],
        review_required: true,
        xml_preview: sample.xml,
      },
    }),
  );
  await page.goto("/");
  await page
    .getByLabel("Process description", { exact: true })
    .fill(
      "Verify inventory for 4 hours and prepare invoice for 7 hours in parallel, then dispatch for 2 hours. Operations performs all work.",
    );
  await page.getByRole("button", { name: "Extract review draft" }).click();
  await expect(
    page.getByLabel("Structured draft", { exact: false }),
  ).toBeVisible();
  const accept = page.getByRole("button", { name: "Accept reviewed model" });
  await expect(accept).toBeDisabled();
  await page.getByRole("checkbox").check();
  await accept.click();
  await expect(
    page.getByRole("heading", { level: 1, name: sample.name }),
  ).toBeVisible();
});

test("XOR branches without conditions import and run with explicit route selection", async ({
  page,
  request,
}) => {
  const samples = await (await request.get("/api/v1/samples")).json();
  const sample = samples.find((item: { key: string }) => item.key === "loan");
  const xml = sample.xml
    .replace(
      /<bpmn:conditionExpression>[\s\S]*?<\/bpmn:conditionExpression>/g,
      "",
    )
    .replace(/ default="[^"]+"/g, "");
  await request.post("/api/v1/projects", {
    data: { name: "Explicit decision routes" },
  });
  await page.goto("/");
  await page
    .getByLabel("Import BPMN file")
    .setInputFiles({
      name: "unlabeled-xor.bpmn",
      mimeType: "application/xml",
      buffer: Buffer.from(xml),
    });
  await expect(
    page.getByRole("heading", { level: 1, name: "Loan review" }),
  ).toBeVisible();
  await expect(
    page.getByRole("region", { name: "BPMN structural inspection" }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "Simulate", exact: true }).click();
  await expect(page.getByLabel("decision route")).toHaveValue("");
  await page.getByLabel("decision route").selectOption("flow_4");
  await page
    .getByRole("button", { name: "Run baseline simulation", exact: true })
    .click();
  await expect(page.locator(".experiment .status-succeeded")).toBeVisible();
  await expect(page.locator(".timeline tbody")).toContainText(
    "Send decline notice",
  );
  await expect(page.locator(".timeline tbody")).not.toContainText(
    "Prepare approved offer",
  );
});

test("unsupported file gets actionable diagnostics and does not save a model", async ({
  page,
  request,
}) => {
  await request.post("/api/v1/projects", {
    data: { name: "Unsupported model assessment" },
  });
  await page.goto("/");
  const xml =
    '<definitions xmlns="http://www.omg.org/spec/BPMN/20100524/MODEL"><process id="p"><subProcess id="nested"/></process></definitions>';
  await page.getByLabel("Import BPMN file").setInputFiles({
    name: "unsupported.xml",
    mimeType: "application/xml",
    buffer: Buffer.from(xml),
  });
  await expect(page.getByRole("alert")).toContainText(
    "Unsupported embedded subprocess",
  );
  await expect(page.getByRole("alert")).toContainText("nested");
  await expect(
    page.getByRole("region", { name: "BPMN structural inspection" }),
  ).toContainText("Structural inspection only");
  await page.screenshot({
    path: "../docs/evidence/complex-inspection.png",
    fullPage: true,
  });
});

test("nested subprocess import validates and simulates its selected route", async ({
  page,
  request,
}) => {
  await request.post("/api/v1/projects", {
    data: { name: "Nested subprocess demonstration" },
  });
  await page.goto("/");
  await page
    .getByLabel("Import BPMN file")
    .setInputFiles("../examples/complex/nested-order.bpmn");
  await expect(
    page.getByRole("heading", {
      level: 1,
      name: "Order fulfillment with nested subprocesses",
    }),
  ).toBeVisible();
  await page.screenshot({
    path: "../docs/evidence/nested-model.png",
    fullPage: true,
  });
  await page
    .getByRole("button", { name: "Validate model", exact: true })
    .click();
  await expect(page.getByText("6 tasks ·", { exact: false })).toBeVisible();
  await page.getByRole("button", { name: "Configure simulation" }).click();
  await expect(page.getByLabel("Time unit", { exact: true })).toHaveValue(
    "minutes",
  );
  await page.getByLabel("stock route").selectOption("stock_yes");
  await page
    .getByRole("button", { name: "Run baseline simulation", exact: true })
    .click();
  await expect(page.locator(".experiment .status-succeeded")).toBeVisible();
  await expect(page.locator(".metric-strip")).toContainText("35");
});

test("draft extraction shows pending state and a local provider failure", async ({
  page,
}) => {
  await page.route("**/api/v1/health", async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    body.provider.configured = true;
    await route.fulfill({ json: body });
  });
  let finish: (() => Promise<void>) | undefined;
  await page.route("**/api/v1/generation/extract", (route) => {
    finish = () =>
      route.fulfill({
        status: 504,
        json: { error: { message: "Provider was unreachable or timed out." } },
      });
  });
  await page.goto("/");
  await page
    .getByLabel("Process description", { exact: true })
    .fill("Start → Receive order → End");
  await page.getByRole("button", { name: "Extract review draft" }).click();
  await expect(
    page.getByRole("button", { name: "Extracting draft" }),
  ).toBeDisabled();
  await expect(page.locator(".generation").getByRole("status")).toContainText(
    "Waiting for the AI provider",
  );
  await finish!();
  await expect(page.locator(".generation").getByRole("alert")).toContainText(
    "Provider was unreachable",
  );
  await expect(
    page.getByRole("button", { name: "Extract review draft" }),
  ).toBeEnabled();
});

test("vague prompts show clarification without a fabricated draft", async ({
  page,
}) => {
  await page.route("**/api/v1/health", async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    body.provider.configured = true;
    await route.fulfill({ json: body });
  });
  await page.route("**/api/v1/generation/extract", (route) =>
    route.fulfill({
      json: {
        ir: null,
        diagnostics: [
          {
            code: "clarification_required",
            message: "Which tasks should the process contain?",
            severity: "warning",
          },
        ],
        clarification_questions: ["Which tasks should the process contain?"],
        xml_preview: null,
        review_required: true,
      },
    }),
  );
  await page.goto("/");
  await page
    .getByLabel("Process description", { exact: true })
    .fill("make it better");
  await page.getByRole("button", { name: "Extract review draft" }).click();
  await expect(page.locator(".generation")).toContainText(
    "Which tasks should the process contain?",
  );
  await expect(
    page.getByRole("button", { name: "Accept reviewed model" }),
  ).toHaveCount(0);
});
