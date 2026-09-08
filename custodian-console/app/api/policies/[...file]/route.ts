import { NextResponse } from "next/server";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { POLICIES_DIR } from "@/lib/config";

const execFileAsync = promisify(execFile);

export async function GET(_req: Request, ctx: RouteContext<"/api/policies/[...file]">) {
  const { file } = await ctx.params;
  const relPath = file.join("/");

  // This path segment is attacker-controllable - confirm it can't escape the policies dir.
  const policiesRoot = path.resolve(POLICIES_DIR);
  const target = path.resolve(policiesRoot, relPath);
  if (!target.startsWith(policiesRoot + path.sep) && target !== policiesRoot) {
    return NextResponse.json({ error: "invalid path" }, { status: 400 });
  }

  try {
    const content = await readFile(target, "utf-8");

    let history: { hash: string; author: string; date: string; message: string }[] = [];
    try {
      const { stdout } = await execFileAsync(
        "git",
        ["log", "--follow", "--pretty=format:%H|%an|%aI|%s", "--", relPath],
        { cwd: policiesRoot },
      );
      history = stdout
        .split("\n")
        .filter(Boolean)
        .map((line) => {
          const [hash, author, date, ...rest] = line.split("|");
          return { hash, author, date, message: rest.join("|") };
        });
    } catch {
      // No git repo, or no history for this file yet - real absence, not an error.
    }

    return NextResponse.json({ path: relPath, content, history });
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 404 });
  }
}
