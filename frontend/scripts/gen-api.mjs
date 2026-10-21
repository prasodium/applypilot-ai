// Regenerates src/api/schema.d.ts from the backend's OpenAPI document (types only: no runtime code is generated).
import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const backend = path.resolve(here, "../../backend");
const py = path.join(backend, ".venv/bin/python");
const spec = path.resolve(here, "../openapi.json");
if (!existsSync(py)) throw new Error("Create the backend virtualenv first (see README).");
execFileSync(py, ["scripts/dump_openapi.py", spec], { cwd: backend, stdio: "inherit", env: { ...process.env, PYTHONPATH: backend } });
execFileSync("npx", ["openapi-typescript", spec, "-o", path.resolve(here, "../src/api/schema.d.ts")], { stdio: "inherit" });
