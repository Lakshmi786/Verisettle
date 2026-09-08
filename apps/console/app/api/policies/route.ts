import { NextResponse } from "next/server";
import { readdir } from "node:fs/promises";
import path from "node:path";
import { POLICIES_DIR } from "@/lib/config";

async function walk(dir: string, base: string): Promise<string[]> {
  const entries = await readdir(dir, { withFileTypes: true });
  const files: string[] = [];
  for (const entry of entries) {
    if (entry.name.startsWith(".")) continue;
    const rel = path.posix.join(base, entry.name);
    if (entry.isDirectory()) {
      files.push(...(await walk(path.join(dir, entry.name), rel)));
    } else if (entry.name.endsWith(".cedar") || entry.name.endsWith(".dw") || entry.name.endsWith(".json")) {
      files.push(rel);
    }
  }
  return files;
}

export async function GET() {
  try {
    const files = await walk(POLICIES_DIR, "");
    return NextResponse.json({ files: files.sort() });
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 });
  }
}
