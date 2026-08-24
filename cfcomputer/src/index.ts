// Песочница Cloudflare Computer, поднятая локально.
// Наружу торчит один HTTP-контракт, чтобы её могла дёргать любая модель:
//   POST /box/<id>/exec   {"command": "..."}      -> {stdout, stderr, exitCode}
//   PUT  /box/<id>/file/<path>                    -> 204
//   GET  /box/<id>/file/<path>                    -> содержимое
//   GET  /box/<id>/tree                           -> плоский список файлов
//   DELETE /box/<id>                              -> вычистить /workspace
import { DurableObject } from "cloudflare:workers";
import {
  type DurableObjectStorageLike,
  getWorkspace,
  WorkspaceServiceProxy,
  withWorkspace,
} from "@cloudflare/computer";
import { WorkerShellBackend } from "@cloudflare/computer/backends/worker-shell";
import jq from "@cloudflare/computer/shell/jq";

export { WorkspaceServiceProxy };

export class Box extends withWorkspace(class extends DurableObject<Env> {}, (self) => {
  const { ctx, env } = self as unknown as { ctx: DurableObjectState; env: Env };
  return {
    storage: ctx.storage as unknown as DurableObjectStorageLike,
    backends: [
      new WorkerShellBackend({
        loader: env.LOADER,
        workspace: { binding: "Box", id: ctx.id.toString() },
        ctx,
        // Сети у песочницы нет намеренно: curl не подключаем.
        // Группы python и sqlite в 0.2.1 в воркере не поднимаются
        // ("command not available in browser environments" / "worker not found"),
        // так что их тут нет — подробности в README.
        commands: [jq],
      }),
    ],
  };
}) {}

const ROOT = "/workspace";

type Ws = Awaited<ReturnType<typeof getWorkspace>>;

async function open(env: Env, name: string): Promise<Ws> {
  const stub = env.Box.get(env.Box.idFromName(name));
  return getWorkspace(stub as unknown as Parameters<typeof getWorkspace>[0]);
}

function fail(error: unknown, status: number): Response {
  const message = error instanceof Error ? error.message : String(error);
  return json({ error: message, code: (error as { code?: string }).code }, status);
}

function json(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function safePath(rest: string): string | null {
  const p = `/${rest}`;
  if (p !== ROOT && !p.startsWith(`${ROOT}/`)) return null;
  if (p.split("/").includes("..")) return null;
  return p;
}

async function walk(ws: Ws, dir: string, out: string[]): Promise<void> {
  let entries: Array<{ name: string; isDirectory: boolean }>;
  try {
    entries = (await ws.fs.readdir(dir)) as Array<{ name: string; isDirectory: boolean }>;
  } catch {
    return;
  }
  for (const e of entries) {
    const child = dir === "/" ? `/${e.name}` : `${dir}/${e.name}`;
    if (e.isDirectory) await walk(ws, child, out);
    else out.push(child);
  }
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);

    const file = url.pathname.match(/^\/box\/([^/]+)\/file\/(.+)$/);
    if (file) {
      const path = safePath(file[2]);
      if (!path) return fail(new Error(`путь должен лежать под ${ROOT}`), 400);
      using ws = await open(env, file[1]);
      if (request.method === "PUT") {
        try {
          const dir = path.slice(0, path.lastIndexOf("/"));
          if (dir && dir !== "") await ws.fs.mkdir(dir, { recursive: true });
          await ws.fs.writeFile(path, new Uint8Array(await request.arrayBuffer()));
          return new Response(null, { status: 204 });
        } catch (e) {
          return fail(e, 500);
        }
      }
      if (request.method === "GET") {
        try {
          return new Response(await ws.fs.readFile(path, {}), {
            headers: { "content-type": "application/octet-stream" },
          });
        } catch (e) {
          return fail(e, (e as { code?: string }).code === "ENOENT" ? 404 : 500);
        }
      }
      return new Response("method not allowed", { status: 405, headers: { allow: "GET, PUT" } });
    }

    const exec = url.pathname.match(/^\/box\/([^/]+)\/exec\/?$/);
    if (exec) {
      if (request.method !== "POST") {
        return new Response("method not allowed", { status: 405, headers: { allow: "POST" } });
      }
      let body: { command?: string; cwd?: string };
      try {
        body = (await request.json()) as { command?: string; cwd?: string };
      } catch {
        return fail(new Error("тело не разобралось как JSON"), 400);
      }
      if (!body.command) return fail(new Error("нужно поле command"), 400);
      using ws = await open(env, exec[1]);
      try {
        using handle = await ws.runtime.exec(body.command, {
          cwd: body.cwd ?? ROOT,
          encoding: "utf8",
        });
        return json(await handle.result());
      } catch (e) {
        return fail(e, 500);
      }
    }

    const tree = url.pathname.match(/^\/box\/([^/]+)\/tree\/?$/);
    if (tree) {
      using ws = await open(env, tree[1]);
      const out: string[] = [];
      await walk(ws, ROOT, out);
      return json({ files: out.sort() });
    }

    const reset = url.pathname.match(/^\/box\/([^/]+)\/?$/);
    if (reset && request.method === "DELETE") {
      using ws = await open(env, reset[1]);
      try {
        await ws.fs.rm(ROOT, { recursive: true });
      } catch {
        // пустой воркспейс — уже то, что просили
      }
      await ws.fs.mkdir(ROOT, { recursive: true });
      return new Response(null, { status: 204 });
    }

    if (url.pathname === "/health") return json({ ok: true });

    return new Response(
      [
        "cfcomputer-lab",
        "",
        "  POST   /box/<id>/exec          {\"command\": \"...\"}",
        "  PUT    /box/<id>/file/workspace/<path>",
        "  GET    /box/<id>/file/workspace/<path>",
        "  GET    /box/<id>/tree",
        "  DELETE /box/<id>",
        "",
      ].join("\n"),
      { headers: { "content-type": "text/plain" } },
    );
  },
} satisfies ExportedHandler<Env>;
