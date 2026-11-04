import { cpSync } from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

// Match the production Docker image's standalone server and static assets.
cpSync(".next/static", ".next/standalone/.next/static", { recursive: true });
process.env.HOSTNAME = "127.0.0.1";
process.env.PORT = "17800";
await import(pathToFileURL(path.resolve(".next/standalone/server.js")).href);
