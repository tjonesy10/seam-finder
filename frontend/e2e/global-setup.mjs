import { execFileSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");

export default function globalSetup() {
  execFileSync("python3", ["tests/prepare_spa_e2e.py"], {
    cwd: root,
    stdio: "inherit",
    env: globalThis.process.env,
  });
}
