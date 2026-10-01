import express from "express";
import multer from "multer";
import { writeFile } from "node:fs/promises";
import type { Server } from "node:http";
import { basename, extname, resolve } from "node:path";

import { parsePlan, summarizePlan, validatePlanData } from "../config/load-plan";
import { controllerSchema, type OmadaPlan } from "../config/schema";
import { OmadaPortal } from "../omada/portal";
import { launchLoginBrowser, withAuthenticatedSession } from "../omada/session";
import { browserProfileDir, ensureRuntimeDirs, examplesDir, publicDir, uploadsDir } from "../runtime/paths";
import { RunReporter, type RunReport } from "../runtime/report";
import { runPlanFromFile } from "../runtime/run-plan";

const upload = multer({ storage: multer.memoryStorage() });
const webhookTextTypes = [
  "text/plain",
  "text/yaml",
  "text/x-yaml",
  "application/yaml",
  "application/x-yaml",
  "text/json",
];

export interface StartServerOptions {
  port?: number;
  host?: string;
}

export interface StartedServer {
  app: express.Express;
  server: Server;
  port: number;
  url: string;
}

interface WebhookJob {
  id: string;
  source: "webhook";
  status: "queued" | "running" | "success" | "failed";
  createdAt: string;
  startedAt?: string;
  finishedAt?: string;
  planFileName: string;
  savedPath: string;
  summary: Record<string, number | string | boolean>;
  report?: RunReport;
  error?: string;
}

type ControllerSettings = OmadaPlan["controller"];

function timestampedFileName(originalName: string): string {
  const stamp = new Date().toISOString().replace(/[:.]/g, "-");
  return `${stamp}-${basename(originalName)}`;
}

function createJobId(): string {
  return `job-${new Date().toISOString().replace(/[:.]/g, "-")}-${Math.random().toString(36).slice(2, 8)}`;
}

function normalizePlanFileName(fileName: string | undefined, fallbackExt: ".yaml" | ".json"): string {
  const candidate = basename(fileName?.trim() || `webhook-plan${fallbackExt}`);

  if (/\.(yaml|yml|json)$/i.test(candidate)) {
    return candidate;
  }

  return `${candidate}${fallbackExt}`;
}

async function persistUploadedPlan(file: Express.Multer.File): Promise<string> {
  const targetPath = resolve(uploadsDir, timestampedFileName(file.originalname));
  await writeFile(targetPath, file.buffer);
  return targetPath;
}

async function persistPlanContent(fileName: string, content: string): Promise<string> {
  const targetPath = resolve(uploadsDir, timestampedFileName(fileName));
  await writeFile(targetPath, content, "utf8");
  return targetPath;
}

function readWebhookToken(req: express.Request): string | null {
  const authorization = req.get("authorization");
  if (authorization?.startsWith("Bearer ")) {
    const token = authorization.slice("Bearer ".length).trim();
    return token.length > 0 ? token : null;
  }

  const headerToken = req.get("x-omada-webhook-token")?.trim();
  return headerToken ? headerToken : null;
}

function requireWebhookAuth(req: express.Request, res: express.Response): string | null {
  const configuredToken = process.env.OMADA_SITE_CREATOR_WEBHOOK_TOKEN;
  if (!configuredToken) {
    res.status(503).json({
      ok: false,
      error: "Webhook support is disabled. Set OMADA_SITE_CREATOR_WEBHOOK_TOKEN first.",
    });
    return null;
  }

  const providedToken = readWebhookToken(req);
  if (providedToken !== configuredToken) {
    res.status(401).json({
      ok: false,
      error: "Webhook token is invalid.",
    });
    return null;
  }

  return configuredToken;
}

function readBoolean(value: string | undefined): boolean | undefined {
  if (value === undefined) {
    return undefined;
  }

  const normalized = value.trim().toLowerCase();
  if (["1", "true", "yes", "on"].includes(normalized)) {
    return true;
  }
  if (["0", "false", "no", "off"].includes(normalized)) {
    return false;
  }
  return undefined;
}

function buildDiscoveryController(req: express.Request): ControllerSettings {
  const organizationName = String(
    req.query.organizationName
    ?? process.env.OMADA_SITE_CREATOR_ORGANIZATION_NAME
    ?? process.env.OMADA_ORGANIZATION_NAME
    ?? "",
  ).trim();

  if (!organizationName) {
    throw new Error("Discovery requests need organizationName in the query string or OMADA_SITE_CREATOR_ORGANIZATION_NAME in the environment.");
  }

  const browserChannel = String(
    req.query.browserChannel
    ?? process.env.OMADA_SITE_CREATOR_BROWSER_CHANNEL
    ?? "chromium",
  ).trim();

  const headless = readBoolean(String(req.query.headless ?? "")) ?? readBoolean(process.env.OMADA_SITE_CREATOR_HEADLESS) ?? true;
  const baseUrl = String(
    req.query.baseUrl
    ?? process.env.OMADA_SITE_CREATOR_BASE_URL
    ?? process.env.OMADA_CLOUD_BASE_URL
    ?? "https://use1-omada-cloud.tplinkcloud.com/",
  ).trim();

  return controllerSchema.parse({
    organizationName,
    baseUrl,
    browserChannel,
    headless,
  });
}

async function resolveWebhookPlan(req: express.Request): Promise<{
  savedPath: string;
  summary: Record<string, number | string | boolean>;
}> {
  const headerFileName = req.get("x-plan-file-name");

  if (typeof req.body === "string") {
    const fallbackExt = req.is("application/json") || req.is("text/json") ? ".json" : ".yaml";
    const sourceName = normalizePlanFileName(headerFileName, fallbackExt);
    const plan = parsePlan(req.body, sourceName);
    const savedPath = await persistPlanContent(sourceName, req.body);

    return {
      savedPath,
      summary: summarizePlan(plan),
    };
  }

  if (!req.body || typeof req.body !== "object") {
    throw new Error("Webhook body must be a JSON plan object or raw YAML/JSON text.");
  }

  const body = req.body as Record<string, unknown>;
  const fileName = typeof body.fileName === "string" ? body.fileName : headerFileName;

  if (typeof body.planText === "string") {
    const sourceName = normalizePlanFileName(fileName, ".yaml");
    const plan = parsePlan(body.planText, sourceName);
    const savedPath = await persistPlanContent(sourceName, body.planText);

    return {
      savedPath,
      summary: summarizePlan(plan),
    };
  }

  const rawPlan = Object.prototype.hasOwnProperty.call(body, "plan") ? body.plan : body;
  const plan = validatePlanData(rawPlan);
  const sourceName = normalizePlanFileName(fileName, ".json");
  const savedPath = await persistPlanContent(sourceName, JSON.stringify(plan, null, 2));

  return {
    savedPath,
    summary: summarizePlan(plan),
  };
}

export function createApp(): express.Express {
  ensureRuntimeDirs();

  const app = express();
  // The unauthenticated legacy controller executor is retired. Containment is
  // intrinsic to the service and survives reverse-proxy configuration loss.
  app.use((req, res, next) => {
    if (req.method === "GET" && req.path === "/api/health") return next();
    res.status(403).json({ ok: false, error: "Legacy Omada executor retired" });
  });
  let activeForegroundRun = false;
  let activeWebhookJobId: string | null = null;
  const queuedWebhookJobIds: string[] = [];
  const webhookJobs = new Map<string, WebhookJob>();

  const isBusy = (): boolean => activeForegroundRun || activeWebhookJobId !== null;

  const pumpWebhookQueue = async (): Promise<void> => {
    if (isBusy()) {
      return;
    }

    const nextJobId = queuedWebhookJobIds.shift();
    if (!nextJobId) {
      return;
    }

    const job = webhookJobs.get(nextJobId);
    if (!job) {
      await pumpWebhookQueue();
      return;
    }

    activeWebhookJobId = job.id;
    job.status = "running";
    job.startedAt = new Date().toISOString();

    try {
      const result = await runPlanFromFile(job.savedPath, false);
      job.report = result.report;
      job.status = result.report.overallStatus === "failed" ? "failed" : "success";
      if (job.status === "failed") {
        job.error = "Webhook-triggered run finished with failures. See report for details.";
      }
    } catch (error) {
      job.status = "failed";
      job.error = String(error);
    } finally {
      job.finishedAt = new Date().toISOString();
      activeWebhookJobId = null;
      void pumpWebhookQueue();
    }
  };

  app.use(express.json({ limit: "2mb" }));
  app.use(express.text({ type: webhookTextTypes, limit: "2mb" }));
  app.use(express.static(publicDir));
  app.use("/examples", express.static(examplesDir));

  app.get("/api/health", (_req, res) => {
    res.json({
      ok: true,
      browserProfileDir,
      activeForegroundRun,
      activeWebhookJobId,
      queuedWebhookJobs: queuedWebhookJobIds.length,
      webhookEnabled: Boolean(process.env.OMADA_SITE_CREATOR_WEBHOOK_TOKEN),
    });
  });

  app.get("/api/jobs/:jobId", (req, res) => {
    const job = webhookJobs.get(req.params.jobId);

    if (!job) {
      res.status(404).json({
        ok: false,
        error: `Webhook job ${req.params.jobId} was not found.`,
      });
      return;
    }

    res.json({
      ok: true,
      job,
    });
  });

  app.get("/api/discovery/sites", async (req, res) => {
    if (!requireWebhookAuth(req, res)) {
      return;
    }

    try {
      const controller = buildDiscoveryController(req);
      const search = typeof req.query.search === "string" ? req.query.search : undefined;
      const reporter = new RunReporter("omada-discovery", true);

      const items = await withAuthenticatedSession(controller, async ({ page }) => {
        const portal = new OmadaPortal(page, reporter, controller);
        await portal.ensureOrganizationSelected(controller.organizationName);
        return await portal.listSites(search);
      });

      res.json({
        ok: true,
        organizationName: controller.organizationName,
        count: items.length,
        items,
      });
    } catch (error) {
      res.status(500).json({
        ok: false,
        error: String(error),
      });
    }
  });

  app.get("/api/discovery/sites/:siteId", async (req, res) => {
    if (!requireWebhookAuth(req, res)) {
      return;
    }

    try {
      const controller = buildDiscoveryController(req);
      const reporter = new RunReporter("omada-discovery", true);

      const site = await withAuthenticatedSession(controller, async ({ page }) => {
        const portal = new OmadaPortal(page, reporter, controller);
        await portal.ensureOrganizationSelected(controller.organizationName);
        return await portal.getSiteById(req.params.siteId);
      });

      if (!site) {
        res.status(404).json({
          ok: false,
          error: `Site ${req.params.siteId} was not found.`,
        });
        return;
      }

      res.json({
        ok: true,
        site,
      });
    } catch (error) {
      res.status(500).json({
        ok: false,
        error: String(error),
      });
    }
  });

  app.get("/api/discovery/sites/:siteId/lans", async (req, res) => {
    if (!requireWebhookAuth(req, res)) {
      return;
    }

    try {
      const controller = buildDiscoveryController(req);
      const reporter = new RunReporter("omada-discovery", true);

      const items = await withAuthenticatedSession(controller, async ({ page }) => {
        const portal = new OmadaPortal(page, reporter, controller);
        await portal.ensureOrganizationSelected(controller.organizationName);
        return await portal.listLanNetworksForSite(req.params.siteId);
      });

      res.json({
        ok: true,
        siteId: req.params.siteId,
        count: items.length,
        items,
      });
    } catch (error) {
      res.status(500).json({
        ok: false,
        error: String(error),
      });
    }
  });

  app.get("/api/discovery/sites/:siteId/wlan-groups", async (req, res) => {
    if (!requireWebhookAuth(req, res)) {
      return;
    }

    try {
      const controller = buildDiscoveryController(req);
      const reporter = new RunReporter("omada-discovery", true);

      const items = await withAuthenticatedSession(controller, async ({ page }) => {
        const portal = new OmadaPortal(page, reporter, controller);
        await portal.ensureOrganizationSelected(controller.organizationName);
        return await portal.listWlanGroupsForSite(req.params.siteId);
      });

      res.json({
        ok: true,
        siteId: req.params.siteId,
        count: items.length,
        items,
      });
    } catch (error) {
      res.status(500).json({
        ok: false,
        error: String(error),
      });
    }
  });

  app.get("/api/discovery/sites/:siteId/wlan-groups/:wlanId/ssids", async (req, res) => {
    if (!requireWebhookAuth(req, res)) {
      return;
    }

    try {
      const controller = buildDiscoveryController(req);
      const reporter = new RunReporter("omada-discovery", true);

      const items = await withAuthenticatedSession(controller, async ({ page }) => {
        const portal = new OmadaPortal(page, reporter, controller);
        await portal.ensureOrganizationSelected(controller.organizationName);
        return await portal.listSsidsForGroup(req.params.siteId, req.params.wlanId);
      });

      res.json({
        ok: true,
        siteId: req.params.siteId,
        wlanId: req.params.wlanId,
        count: items.length,
        items,
      });
    } catch (error) {
      res.status(500).json({
        ok: false,
        error: String(error),
      });
    }
  });

  app.post("/api/session/login", async (_req, res) => {
    try {
      const session = await launchLoginBrowser({
        organizationName: "Set in your plan file",
        baseUrl: "https://use1-omada-cloud.tplinkcloud.com/",
        browserChannel: process.platform === "win32" ? "msedge" : "chromium",
        headless: false,
      });

      res.json({
        ok: true,
        message: session.message,
        alreadyOpen: session.alreadyOpen,
      });
    } catch (error) {
      res.status(500).json({
        ok: false,
        error: String(error),
      });
    }
  });

  app.post("/api/runs/validate", upload.single("plan"), async (req, res) => {
    try {
      const file = req.file;

      if (!file) {
        res.status(400).json({ error: "Upload a plan file first." });
        return;
      }

      const sourceName = file.originalname || `plan${extname(file.originalname) || ".yaml"}`;
      const plan = parsePlan(file.buffer.toString("utf8"), sourceName);
      const savedPath = await persistUploadedPlan(file);

      res.json({
        ok: true,
        savedPath,
        summary: summarizePlan(plan),
      });
    } catch (error) {
      res.status(400).json({
        ok: false,
        error: String(error),
      });
    }
  });

  app.post("/api/runs/start", upload.single("plan"), async (req, res) => {
    if (isBusy() || queuedWebhookJobIds.length > 0) {
      res.status(409).json({
        ok: false,
        error: "Another run is already in progress or queued.",
      });
      return;
    }

    const file = req.file;

    if (!file) {
      res.status(400).json({
        ok: false,
        error: "Upload a plan file first.",
      });
      return;
    }

    activeForegroundRun = true;

    try {
      const savedPath = await persistUploadedPlan(file);
      const result = await runPlanFromFile(savedPath, false);
      const statusCode = result.report.overallStatus === "failed" ? 500 : 200;

      res.status(statusCode).json({
        ok: result.report.overallStatus !== "failed",
        savedPath,
        report: result.report,
      });
    } catch (error) {
      res.status(500).json({
        ok: false,
        error: String(error),
      });
    } finally {
      activeForegroundRun = false;
      void pumpWebhookQueue();
    }
  });

  app.post("/api/webhooks/run", async (req, res) => {
    if (!requireWebhookAuth(req, res)) {
      return;
    }

    try {
      const { savedPath, summary } = await resolveWebhookPlan(req);
      const job: WebhookJob = {
        id: createJobId(),
        source: "webhook",
        status: "queued",
        createdAt: new Date().toISOString(),
        planFileName: basename(savedPath),
        savedPath,
        summary,
      };

      webhookJobs.set(job.id, job);
      queuedWebhookJobIds.push(job.id);
      void pumpWebhookQueue();

      res.status(202).json({
        ok: true,
        accepted: true,
        job,
        statusUrl: `/api/jobs/${job.id}`,
      });
    } catch (error) {
      res.status(400).json({
        ok: false,
        error: String(error),
      });
    }
  });

  return app;
}

export async function startServer(options: StartServerOptions = {}): Promise<StartedServer> {
  const app = createApp();
  const host = options.host ?? process.env.OMADA_SITE_CREATOR_HOST ?? "127.0.0.1";
  const requestedPort = options.port ?? Number(process.env.PORT ?? 3210);

  return await new Promise<StartedServer>((resolveStart, rejectStart) => {
    const server = app.listen(requestedPort, host, () => {
      const address = server.address();

      if (!address || typeof address === "string") {
        rejectStart(new Error("Server started without a numeric port."));
        return;
      }

      resolveStart({
        app,
        server,
        port: address.port,
        url: `http://${host}:${address.port}`,
      });
    });

    server.once("error", rejectStart);
  });
}
