import { put } from "@vercel/blob";
import { readFileSync } from "fs";
import { fileURLToPath } from "url";
import { dirname, join } from "path";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");

const FILES = [
  "reels_playwright_output.json",
  "profile_info.json",
  "trending_reels_30.json",
];

async function main() {
  const uploaded = {};
  for (const name of FILES) {
    const content = readFileSync(join(ROOT, name));
    const blob = await put(name, content, {
      access: "public",
      addRandomSuffix: false,
      allowOverwrite: true,
      contentType: "application/json",
    });
    uploaded[name] = blob.url;
    console.log(`uploaded ${name} -> ${blob.url}`);
  }

  const status = {
    status: "done",
    updated_at: new Date().toISOString(),
    files: uploaded,
  };
  const statusBlob = await put("status.json", JSON.stringify(status, null, 2), {
    access: "public",
    addRandomSuffix: false,
    allowOverwrite: true,
    contentType: "application/json",
  });
  console.log(`uploaded status.json -> ${statusBlob.url}`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
