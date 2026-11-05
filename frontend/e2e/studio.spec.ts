import { test, expect } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import path from "node:path";

test.beforeEach(async ({ page }, testInfo) => {
  // Existing journeys explicitly exercise manual controls. Automatic journeys use the real default.
  if (!testInfo.title.startsWith("automatic")) {
    await page.addInitScript(() =>
      localStorage.setItem("studio.autoSimulate", "false"),
    );
  }
});

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
  await page.getByRole("checkbox", { name: /I reviewed this model/ }).check();
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
  await page.getByLabel("Import BPMN file").setInputFiles({
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

test("automatic simulation starts after importing a file with missing inputs", async ({
  page,
}) => {
  await page.goto("/");
  await expect(
    page.getByRole("checkbox", { name: "Run simulation automatically" }),
  ).toBeChecked();
  const xml =
    '<definitions xmlns="http://www.omg.org/spec/BPMN/20100524/MODEL" targetNamespace="urn:auto"><process id="auto" name="Automatic order"><startEvent id="s"/><task id="receive" name="Receive order"/><task id="pack" name="Pack order"/><endEvent id="e"/><sequenceFlow id="f1" sourceRef="s" targetRef="receive"/><sequenceFlow id="f2" sourceRef="receive" targetRef="pack"/><sequenceFlow id="f3" sourceRef="pack" targetRef="e"/></process></definitions>';
  await page.getByLabel("Import BPMN file").setInputFiles({
    name: "automatic.bpmn",
    mimeType: "application/xml",
    buffer: Buffer.from(xml),
  });
  await expect(
    page.getByRole("heading", { name: "Measure a stated scenario.", level: 1 }),
  ).toBeVisible();
  await expect(page.locator(".experiment .status-succeeded")).toBeVisible();
  await expect(
    page.getByRole("heading", {
      name: "Automatic demo simulation",
      exact: true,
    }),
  ).toBeVisible();
  await expect(page.locator(".metric-strip")).toContainText("2");
  await expect(
    page.getByText("It is not measured business performance.", {
      exact: false,
    }),
  ).toBeVisible();
  await page.getByText(/View automatic assumptions/).click();
  await expect(
    page
      .getByText(
        /retained demo setting, duration = 1 time units, role = Demo worker/,
      )
      .first(),
  ).toBeVisible();
  await page.screenshot({
    path: "../docs/evidence/automatic-simulation.png",
    fullPage: true,
  });
  await page.reload();
  await page.getByRole("button", { name: "Simulate", exact: true }).click();
  await expect(page.locator(".experiment .status-succeeded")).toBeVisible();
});

test("automatic sample simulation preserves its supplied two-technician scenario", async ({
  page,
}) => {
  await page.goto("/");
  await page
    .getByRole("button", { name: /03 Resource-constrained operations/ })
    .click();
  await expect(page.locator(".experiment .status-succeeded")).toBeVisible();
  await expect(page.locator(".metric-strip")).toContainText("13");
  await expect(
    page.getByRole("heading", {
      name: "Automatic demo simulation",
      exact: true,
    }),
  ).toBeVisible();
  await page
    .getByText("Adjust assumptions or optimize (optional)", { exact: true })
    .click();
  await expect(page.getByLabel("Technician capacity")).toHaveValue("2");
  await expect(page.getByLabel("Time unit", { exact: true })).toHaveValue(
    "hours",
  );
});

test("automatic simulation follows acceptance of a reviewed AI draft", async ({
  page,
  request,
}) => {
  const samples = await (await request.get("/api/v1/samples")).json();
  const sample = samples.find((s: { key: string }) => s.key === "loan");
  await page.route("**/api/v1/health", async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    body.provider.configured = true;
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
    .fill("Review and approve or decline a loan.");
  await page.getByRole("button", { name: "Extract review draft" }).click();
  await page.getByRole("checkbox", { name: /I reviewed this model/ }).check();
  await page.getByRole("button", { name: "Accept reviewed model" }).click();
  await expect(page.locator(".experiment .status-succeeded")).toBeVisible();
  await expect(
    page.getByRole("heading", {
      name: "Automatic demo simulation",
      exact: true,
    }),
  ).toBeVisible();
});

test("automatic final BPMN download reproduces the optimized schedule on reimport", async ({
  page,
  request,
}) => {
  await page.goto("/");
  await page
    .getByRole("button", { name: /03 Resource-constrained operations/ })
    .click();
  await expect(page.locator(".experiment .status-succeeded")).toBeVisible();
  const output = page.getByRole("region", { name: "Final BPMN output" });
  await expect(
    output.getByRole("heading", { name: "Final optimized BPMN" }),
  ).toBeVisible();
  await expect(output).toContainText("Optimal schedule proved");
  await expect(output).toContainText("13 → 11 hours");
  await expect(
    output.locator('.djs-element[data-element-id="c_chain"]'),
  ).toBeVisible();
  const href = await output
    .getByRole("link", { name: "Download optimized BPMN" })
    .getAttribute("href");
  const response = await request.get(href!);
  expect(response.status()).toBe(200);
  const xml = await response.text();
  expect(xml).toContain("executionPlan");
  expect(xml).toContain('capacity="2"');
  await page.screenshot({
    path: "../docs/evidence/final-optimized-bpmn.png",
    fullPage: true,
  });
  const queued = page.waitForResponse(
    (res) =>
      res.url().endsWith("/runs/auto") && res.request().method() === "POST",
  );
  await page.getByLabel("Import BPMN file").setInputFiles({
    name: "optimized-reimport.bpmn",
    mimeType: "application/xml",
    buffer: Buffer.from(xml),
  });
  const next = await (await queued).json();
  await expect(page.locator(".run-meta .mono")).toHaveText(next.id.slice(0, 8));
  await expect(page.locator(".experiment .status-succeeded")).toBeVisible();
  await expect(page.locator(".metric-strip")).toContainText("11");
});

test("automatic final BPMN repairs a closed decision join deadlock", async ({
  page,
  request,
}) => {
  await page.goto("/");
  const xml =
    '<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" xmlns:studio="urn:optimodel:studio:1" targetNamespace="urn:repair"><bpmn:process id="approval" name="Order approval"><bpmn:extensionElements><studio:process time_unit="minutes"/></bpmn:extensionElements><bpmn:startEvent id="s"/><bpmn:task id="register" name="Register request"><bpmn:extensionElements><studio:metadata duration="5" role="Reviewer" provenance="source"/></bpmn:extensionElements></bpmn:task><bpmn:exclusiveGateway id="choice" name="Choose review"/><bpmn:task id="finance" name="Finance review"><bpmn:extensionElements><studio:metadata duration="4" role="Reviewer" provenance="source"/></bpmn:extensionElements></bpmn:task><bpmn:task id="manager" name="Manager review"><bpmn:extensionElements><studio:metadata duration="3" role="Reviewer" provenance="source"/></bpmn:extensionElements></bpmn:task><bpmn:parallelGateway id="join"/><bpmn:task id="release" name="Release request"><bpmn:extensionElements><studio:metadata duration="2" role="Reviewer" provenance="source"/></bpmn:extensionElements></bpmn:task><bpmn:endEvent id="e"/><bpmn:sequenceFlow id="f1" sourceRef="s" targetRef="register"/><bpmn:sequenceFlow id="f2" sourceRef="register" targetRef="choice"/><bpmn:sequenceFlow id="finance_path" sourceRef="choice" targetRef="finance"/><bpmn:sequenceFlow id="manager_path" sourceRef="choice" targetRef="manager"/><bpmn:sequenceFlow id="f5" sourceRef="finance" targetRef="join"/><bpmn:sequenceFlow id="f6" sourceRef="manager" targetRef="join"/><bpmn:sequenceFlow id="f7" sourceRef="join" targetRef="release"/><bpmn:sequenceFlow id="f8" sourceRef="release" targetRef="e"/></bpmn:process></bpmn:definitions>';
  await page.getByLabel("Import BPMN file").setInputFiles({
    name: "intentional_deadlock.bpmn",
    mimeType: "application/xml",
    buffer: Buffer.from(xml),
  });
  await expect(page.locator(".experiment .status-succeeded")).toBeVisible();
  const output = page.getByRole("region", { name: "Final BPMN output" });
  await expect(output).toContainText(
    "Gateway deadlock repaired and re-verified",
  );
  await expect(output).toContainText(
    "original deadlocked process had no valid completion time",
  );
  const evaluation = page.getByRole("region", {
    name: "Quantitative performance evaluation",
  });
  await expect(evaluation.locator('[data-metric="deadlocks"]')).toContainText(
    "2",
  );
  await expect(evaluation.locator('[data-metric="makespan"]')).toContainText(
    "N/A",
  );
  await expect(
    evaluation.getByRole("columnheader", {
      name: "Repaired baseline",
      exact: true,
    }),
  ).toBeVisible();
  const full = await output
    .getByRole("link", { name: "Full process BPMN" })
    .getAttribute("href");
  const fixed = await (await request.get(full!)).text();
  expect(fixed).toContain('<bpmn:exclusiveGateway id="join"');
  expect(fixed).toContain('id="manager"');
  const plan = await output
    .getByRole("link", { name: "Download optimized BPMN" })
    .getAttribute("href");
  expect(await (await request.get(plan!)).text()).not.toContain('id="manager"');
  await expect(
    output.locator('.djs-element[data-element-id="finance"]'),
  ).toBeVisible();
  await page.screenshot({
    path: "../docs/evidence/repaired-deadlock-bpmn.png",
    fullPage: true,
  });
});

test("automatic quantitative metrics show initial and final values and survive export", async ({
  page,
  request,
}) => {
  await page.goto("/");
  await page
    .getByRole("button", { name: /03 Resource-constrained operations/ })
    .click();
  await expect(page.locator(".experiment .status-succeeded")).toBeVisible();
  const evaluation = page.getByRole("region", {
    name: "Quantitative performance evaluation",
  });
  await expect(
    evaluation.getByRole("heading", { name: "Initial and final performance" }),
  ).toBeVisible();
  await expect(evaluation.locator("tbody tr[data-metric]")).toHaveCount(14);
  const completion = evaluation.locator('[data-metric="makespan"]');
  await expect(completion.locator("td").nth(1)).toHaveText("13");
  await expect(completion.locator("td").nth(2)).toHaveText("11");
  await expect(evaluation.locator('[data-metric="throughput"]')).toContainText(
    "0.0909",
  );
  await expect(
    evaluation.locator('[data-metric="average_concurrency"]'),
  ).toContainText("1.8182");
  await page.screenshot({
    path: "../docs/evidence/quantitative-performance.png",
    fullPage: true,
  });
  const pdfLink = page
    .getByRole("link", { name: "PDF report", exact: true })
    .first();
  const pdf = await request.get((await pdfLink.getAttribute("href"))!);
  expect(pdf.status()).toBe(200);
  // The report and API use the same stored measurement record.
  const reportUrl = (await pdfLink.getAttribute("href"))!.replace(
    "report.pdf",
    "results.json",
  );
  const result = await (await request.get(reportUrl)).json();
  expect(result.performance_evaluation.final.metrics.makespan).toBe(11);
  expect(result.performance_evaluation.rows).toHaveLength(14);
  await page.getByRole("button", { name: "Model", exact: true }).click();
  await expect(
    evaluation.getByRole("heading", { name: "Initial BPMN performance" }),
  ).toBeVisible();
  await expect(evaluation.locator('[data-metric="makespan"]')).toContainText(
    "13",
  );
  await expect(
    evaluation.getByRole("columnheader", { name: "Final BPMN" }),
  ).toHaveCount(0);
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(evaluation.locator("table").first()).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBeTruthy();
});
