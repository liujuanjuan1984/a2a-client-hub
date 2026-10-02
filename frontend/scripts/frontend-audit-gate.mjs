#!/usr/bin/env node
// Frontend production dependency audit gate.
//
// Runs `npm audit --omit=dev`, blocks on high/critical findings, and only lets
// explicitly triaged advisories through. Triaged entries live in
// `frontend/audit-allowlist.json` and must carry a rationale plus a tracking
// issue so residual risk stays reviewable.

import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const BLOCKING_SEVERITIES = new Set(["high", "critical"]);
const ALLOWLIST_PATH = fileURLToPath(
  new URL("../audit-allowlist.json", import.meta.url),
);

function loadAllowlist() {
  const parsed = JSON.parse(readFileSync(ALLOWLIST_PATH, "utf8"));
  const entries = Array.isArray(parsed.allowlist) ? parsed.allowlist : [];

  return new Map(
    entries.map((entry) => {
      if (!entry.package || !entry.advisory) {
        throw new Error(
          `Invalid audit allowlist entry, expected package and advisory: ${JSON.stringify(entry)}`,
        );
      }
      return [`${entry.package}:${entry.advisory.toUpperCase()}`, entry];
    }),
  );
}

function runAudit() {
  try {
    return execFileSync("npm", ["audit", "--omit=dev", "--json"], {
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

function advisoryIdFromVia(via) {
  if (!via || typeof via !== "object") return null;
  const url = typeof via.url === "string" ? via.url : "";
  const match = url.match(/GHSA-[0-9a-z-]+/i);
  return match ? match[0].toUpperCase() : null;
}

function classify(report, allowlist) {
  const vulnerabilities = report.vulnerabilities ?? {};
  const blocking = [];
  const triaged = [];

  for (const [name, vulnerability] of Object.entries(vulnerabilities)) {
    const severity = vulnerability.severity;
    if (!BLOCKING_SEVERITIES.has(severity)) continue;

    const directAdvisories = (vulnerability.via ?? [])
      .filter((via) => via && typeof via === "object")
      .map((via) => ({
        advisory: advisoryIdFromVia(via),
        title: via.title ?? "",
        severity: via.severity ?? severity,
      }))
      .filter((advisory) => advisory.advisory);

    // Packages that are only vulnerable because they depend on a vulnerable
    // package (string-only `via` entries) are resolved through that package.
    if (directAdvisories.length === 0) continue;

    const unresolved = directAdvisories.filter(
      (advisory) => !allowlist.has(`${name}:${advisory.advisory}`),
    );

    if (unresolved.length > 0) {
      blocking.push({ name, severity, advisories: unresolved });
    } else {
      triaged.push({ name, severity, advisories: directAdvisories });
    }
  }

  return { blocking, triaged };
}

function main() {
  const allowlist = loadAllowlist();
  const { blocking, triaged } = classify(JSON.parse(runAudit()), allowlist);

  if (triaged.length > 0) {
    console.log("Triaged frontend production advisories:");
    for (const item of triaged) {
      for (const advisory of item.advisories) {
        const entry = allowlist.get(`${item.name}:${advisory.advisory}`);
        console.log(
          `  allowed  ${item.name} [${advisory.severity}] ${advisory.advisory}` +
            ` (review by ${entry.reviewBy ?? "unset"}; ${entry.trackingIssue ?? "no tracking issue"})`,
        );
      }
    }
    console.log("");
  }

  if (blocking.length > 0) {
    console.error("Frontend production dependency audit failed:");
    for (const item of blocking) {
      for (const advisory of item.advisories) {
        console.error(
          `  blocked  ${item.name} [${advisory.severity}] ${advisory.advisory}: ${advisory.title}`,
        );
      }
    }
    console.error(
      "\nFix the dependency or add a reviewed entry to frontend/audit-allowlist.json.",
    );
    process.exit(1);
  }

  console.log("No blocking frontend production dependency findings.");
}

main();
