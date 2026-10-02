#!/usr/bin/env node
// Frontend production dependency audit gate.
//
// `npm audit` has no native ignore/allowlist option, so this wrapper keeps the
// existing high/critical blocking threshold while letting only explicitly
// triaged advisories through (`frontend/audit-allowlist.json`).

import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const BLOCKING_SEVERITIES = new Set(["high", "critical"]);
const ADVISORY_PATTERN = /GHSA-[0-9a-z-]+/i;
const ALLOWLIST_PATH = fileURLToPath(
  new URL("../audit-allowlist.json", import.meta.url),
);
const NPM_COMMAND = process.platform === "win32" ? "npm.cmd" : "npm";

function loadAllowlist() {
  const { allowlist = [] } = JSON.parse(readFileSync(ALLOWLIST_PATH, "utf8"));

  return new Map(
    allowlist.map((entry) => {
      if (entry.reviewBy && new Date(entry.reviewBy) < new Date()) {
        console.log(
          `::warning title=Expired frontend audit allowlist entry::` +
            `${entry.package} ${entry.advisory} passed its review-by date ` +
            `(${entry.reviewBy}); re-review or remove it.`,
        );
      }
      return [
        `${entry.package}:${String(entry.advisory).toUpperCase()}`,
        entry,
      ];
    }),
  );
}

function runAudit() {
  try {
    return execFileSync(NPM_COMMAND, ["audit", "--omit=dev", "--json"], {
      encoding: "utf8",
      stdio: ["ignore", "pipe", "pipe"],
    });
  } catch (error) {
    // `npm audit` exits non-zero when it reports findings but still prints JSON.
    if (typeof error.stdout === "string" && error.stdout.trim().startsWith("{")) {
      return error.stdout;
    }
    throw error;
  }
}

function parseReport(raw) {
  let report;
  try {
    report = JSON.parse(raw);
  } catch {
    throw new Error("`npm audit` did not return valid JSON.");
  }

  // A failed audit (for example an unreachable registry) returns an `error`
  // object instead of a report; failing loudly avoids a silent false pass.
  if (
    typeof report?.vulnerabilities !== "object" ||
    report.vulnerabilities === null
  ) {
    const detail = report?.error?.summary ? ` (${report.error.summary})` : "";
    throw new Error(`\`npm audit\` did not return a report${detail}.`);
  }

  return report;
}

function collectFindings(report, allowlist) {
  const blocking = [];
  const triaged = [];

  for (const [name, vulnerability] of Object.entries(report.vulnerabilities)) {
    if (!BLOCKING_SEVERITIES.has(vulnerability.severity)) continue;

    // Only direct advisories drive the decision: packages that are vulnerable
    // solely through a dependency are resolved at that dependency.
    const advisories = (vulnerability.via ?? [])
      .filter((via) => via && typeof via === "object")
      .map((via) => ({
        id: String(via.url ?? "").match(ADVISORY_PATTERN)?.[0]?.toUpperCase(),
        severity: via.severity ?? vulnerability.severity,
      }))
      .filter(({ id, severity }) => id && BLOCKING_SEVERITIES.has(severity));

    for (const { id } of advisories) {
      const key = `${name}:${id}`;
      (allowlist.has(key) ? triaged : blocking).push(
        `${name} [${vulnerability.severity}] ${id}`,
      );
    }
  }

  return { blocking, triaged };
}

function main() {
  const { blocking, triaged } = collectFindings(
    parseReport(runAudit()),
    loadAllowlist(),
  );

  if (triaged.length > 0) {
    console.log(`Triaged frontend production advisories: ${triaged.join("; ")}`);
  }

  if (blocking.length > 0) {
    console.error(
      "Frontend production dependency audit failed:\n" +
        blocking.map((finding) => `  ${finding}`).join("\n") +
        "\nFix the dependency or add a reviewed entry to frontend/audit-allowlist.json.",
    );
    process.exit(1);
  }

  console.log("No blocking frontend production dependency findings.");
}

try {
  main();
} catch (error) {
  console.error(
    `Frontend production dependency audit gate failed to run: ${error.message}`,
  );
  process.exit(1);
}
