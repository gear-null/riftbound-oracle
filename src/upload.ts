import { readFileSync, writeFileSync, existsSync, mkdirSync, createReadStream } from "node:fs";
import { resolve, dirname, basename } from "node:path";
import { createServer } from "node:http";
import { google } from "googleapis";
import { readManifest, type ManifestEntry } from "./manifest.js";

type Drive = ReturnType<typeof google.drive>;

const TOKEN_PATH = resolve(import.meta.dirname, "../.config/oauth-token.json");
const SCOPES = ["https://www.googleapis.com/auth/drive.file"];
const REDIRECT_PORT = 3847;
const REDIRECT_URI = `http://localhost:${REDIRECT_PORT}/callback`;

function getOAuthClient() {
  const clientId = process.env.GOOGLE_CLIENT_ID;
  const clientSecret = process.env.GOOGLE_CLIENT_SECRET;

  if (!clientId || !clientSecret) {
    throw new Error(
      "GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET are required.\n" +
        "Create OAuth2 credentials at https://console.cloud.google.com/apis/credentials"
    );
  }

  return new google.auth.OAuth2(clientId, clientSecret, REDIRECT_URI);
}

async function authorize(): Promise<InstanceType<typeof google.auth.OAuth2>> {
  const oauth2Client = getOAuthClient();

  // Check for saved token
  if (existsSync(TOKEN_PATH)) {
    const token = JSON.parse(readFileSync(TOKEN_PATH, "utf-8"));
    oauth2Client.setCredentials(token);
    return oauth2Client;
  }

  // No token — need interactive auth
  const authUrl = oauth2Client.generateAuthUrl({
    access_type: "offline",
    scope: SCOPES,
    prompt: "consent",
  });

  console.log(`\nOpen this URL to authorize:\n\n  ${authUrl}\n`);

  // Start a temporary local server to receive the callback
  const code = await new Promise<string>((resolve, reject) => {
    const server = createServer((req, res) => {
      const url = new URL(req.url!, `http://localhost:${REDIRECT_PORT}`);
      const code = url.searchParams.get("code");

      if (code) {
        res.writeHead(200, { "Content-Type": "text/html" });
        res.end("<h1>Authorized! You can close this tab.</h1>");
        server.close();
        resolve(code);
      } else {
        res.writeHead(400);
        res.end("Missing authorization code");
        server.close();
        reject(new Error("No authorization code received"));
      }
    });

    server.listen(REDIRECT_PORT);
  });

  const { tokens } = await oauth2Client.getToken(code);
  oauth2Client.setCredentials(tokens);

  // Save token for future runs
  mkdirSync(dirname(TOKEN_PATH), { recursive: true });
  writeFileSync(TOKEN_PATH, JSON.stringify(tokens, null, 2), "utf-8");

  return oauth2Client;
}

function getDriveFolderId(): string {
  const folderId = process.env.DRIVE_FOLDER_ID;
  if (!folderId) {
    throw new Error(
      "DRIVE_FOLDER_ID environment variable is required. " +
        "Set it to the Google Drive folder ID where outputs should be uploaded."
    );
  }
  return folderId;
}

/** Authorize once and return a ready-to-use Drive client + target folder id. */
async function getDriveClient(): Promise<{ drive: Drive; folderId: string }> {
  const authClient = await authorize();
  const drive = google.drive({ version: "v3", auth: authClient });
  const folderId = getDriveFolderId();
  return { drive, folderId };
}

/** Escape user-influenced values before interpolating into Drive API query strings. */
export function escapeDriveQuery(value: string): string {
  return value.replace(/\\/g, "\\\\").replace(/'/g, "\\'");
}

// Words that should stay fully uppercase in Drive file names
const UPPERCASE_WORDS = new Set(["ogn", "ogs", "opp", "sfd", "unl", "jdg", "pr", "tcg", "api", "pdf"]);

/** Convert "cards-ogn" to "Cards OGN", "tournament-rules-jan-2026-update" to "Tournament Rules Jan 2026 Update" */
function toTitleCase(slug: string): string {
  return slug
    .split("-")
    .map((word) =>
      UPPERCASE_WORDS.has(word.toLowerCase())
        ? word.toUpperCase()
        : word.charAt(0).toUpperCase() + word.slice(1)
    )
    .join(" ");
}

/**
 * Find the canonical Drive file for a name, deleting any older duplicates.
 *
 * SIDE EFFECT: if multiple files share the name, this keeps the most recently
 * modified one (matching `planCleanup`'s tiebreaker) and deletes the rest, so
 * upload converges on a single file ID per logical source. Returns the kept
 * file's id, or null if nothing matches.
 */
async function findCanonicalAndDedupe(
  drive: Drive,
  name: string,
  folderId: string,
  mimeFilter?: string
): Promise<string | null> {
  const mimeClause = mimeFilter
    ? ` and mimeType = '${escapeDriveQuery(mimeFilter)}'`
    : "";
  const existing = await drive.files.list({
    q: `name = '${escapeDriveQuery(name)}' and '${escapeDriveQuery(folderId)}' in parents${mimeClause} and trashed = false`,
    fields: "files(id, modifiedTime)",
    orderBy: "modifiedTime desc",
  });

  const files = existing.data.files ?? [];
  if (files.length === 0) return null;

  const [keep, ...extras] = files;
  for (const extra of extras) {
    await drive.files.delete({ fileId: extra.id! });
  }
  return keep.id ?? null;
}

export interface DriveFile {
  id: string;
  name: string;
  mimeType: string;
  createdTime: string;
  modifiedTime: string;
  size?: string;
}

/** List every file in the given Drive folder (handles pagination). */
async function fetchDriveFiles(
  drive: Drive,
  folderId: string
): Promise<DriveFile[]> {
  const out: DriveFile[] = [];
  let pageToken: string | undefined;
  do {
    const res = await drive.files.list({
      q: `'${escapeDriveQuery(folderId)}' in parents and trashed = false`,
      fields:
        "nextPageToken, files(id, name, mimeType, createdTime, modifiedTime, size)",
      pageSize: 100,
      pageToken,
    });
    for (const f of res.data.files ?? []) {
      if (!f.id || !f.name) continue;
      out.push({
        id: f.id,
        name: f.name,
        mimeType: f.mimeType ?? "",
        createdTime: f.createdTime ?? "",
        modifiedTime: f.modifiedTime ?? "",
        size: f.size ?? undefined,
      });
    }
    pageToken = res.data.nextPageToken ?? undefined;
  } while (pageToken);

  return out;
}

/** List every file in the target Drive folder that the current OAuth session can see. */
export async function listDriveFiles(): Promise<DriveFile[]> {
  const { drive, folderId } = await getDriveClient();
  return fetchDriveFiles(drive, folderId);
}

export interface CleanupPlan {
  kept: DriveFile[];
  toDelete: { file: DriveFile; reason: string }[];
}

/** Derive the set of expected Drive file names from the current manifest. */
export function expectedDriveNames(
  entries: ManifestEntry[]
): Set<string> {
  const names = new Set<string>();
  for (const entry of entries) {
    const baseName = entry.output.replace(/^output\//, "").replace(/\.md$/, "");
    const driveName = toTitleCase(baseName);
    if (entry.type === "pdf" && !entry.convert) {
      names.add(driveName + ".pdf");
    } else {
      names.add(driveName);
    }
    if (entry.type === "rules-hub" && entry.pdfs) {
      for (const pdfPath of entry.pdfs) {
        names.add(pdfDriveName(pdfPath));
      }
    }
  }
  return names;
}

/** Derive the Drive display name for a sibling PDF (e.g., "output/core-rules.pdf" → "Core Rules.pdf"). */
function pdfDriveName(pdfPath: string): string {
  return toTitleCase(basename(pdfPath, ".pdf")) + ".pdf";
}

/** Plan a cleanup: which visible files are orphans vs. keepers. */
export function planCleanup(
  files: DriveFile[],
  expected: Set<string>
): CleanupPlan {
  const byName = new Map<string, DriveFile[]>();
  for (const f of files) {
    const group = byName.get(f.name);
    if (group) group.push(f);
    else byName.set(f.name, [f]);
  }

  const kept: DriveFile[] = [];
  const toDelete: { file: DriveFile; reason: string }[] = [];

  for (const [name, group] of byName) {
    if (expected.has(name)) {
      // Keep the newest, delete older duplicates
      group.sort((a, b) => b.modifiedTime.localeCompare(a.modifiedTime));
      const [keep, ...extras] = group;
      kept.push(keep);
      for (const extra of extras) {
        toDelete.push({
          file: extra,
          reason: `older duplicate of "${name}" (kept ${keep.modifiedTime})`,
        });
      }
    } else {
      for (const f of group) {
        toDelete.push({ file: f, reason: "not in current manifest" });
      }
    }
  }

  return { kept, toDelete };
}

export interface CleanupResult extends CleanupPlan {
  deleted: DriveFile[];
}

/** Execute a cleanup plan against the given Drive client. Exported for testing. */
export async function executeCleanupPlan(
  drive: Drive,
  plan: CleanupPlan
): Promise<DriveFile[]> {
  const deleted: DriveFile[] = [];
  for (const { file } of plan.toDelete) {
    await drive.files.delete({ fileId: file.id });
    deleted.push(file);
  }
  return deleted;
}

/** List visible Drive files, plan a cleanup, and optionally execute deletions. */
export async function cleanupDrive(opts: {
  confirm: boolean;
}): Promise<CleanupResult> {
  const { drive, folderId } = await getDriveClient();
  const files = await fetchDriveFiles(drive, folderId);
  const manifest = readManifest();
  const expected = expectedDriveNames(manifest.entries);
  const plan = planCleanup(files, expected);

  const deleted = opts.confirm ? await executeCleanupPlan(drive, plan) : [];
  return { ...plan, deleted };
}

export async function uploadToDrive(): Promise<string[]> {
  const { drive, folderId } = await getDriveClient();
  const manifest = readManifest();
  const uploaded: string[] = [];

  for (const entry of manifest.entries) {
    const baseName = entry.output.replace(/^output\//, "").replace(/\.md$/, "");
    const driveName = toTitleCase(baseName);

    if (entry.type === "pdf" && !entry.convert) {
      // Upload the original PDF directly
      const pdfPath = resolve(entry.path);
      if (!existsSync(pdfPath)) {
        console.warn(`  Skipping ${driveName}: source PDF not found at ${entry.path}`);
        continue;
      }

      const pdfName = driveName + ".pdf";
      const existingId = await findCanonicalAndDedupe(drive, pdfName, folderId);

      if (existingId) {
        await drive.files.update({
          fileId: existingId,
          media: {
            mimeType: "application/pdf",
            body: createReadStream(pdfPath),
          },
        });
      } else {
        await drive.files.create({
          requestBody: {
            name: pdfName,
            parents: [folderId],
          },
          media: {
            mimeType: "application/pdf",
            body: createReadStream(pdfPath),
          },
        });
      }
    } else {
      // Upload markdown as Google Doc
      const filePath = resolve(entry.output);
      if (!existsSync(filePath)) {
        console.warn(`  Skipping ${driveName}: output not found at ${entry.output}`);
        continue;
      }

      const existingId = await findCanonicalAndDedupe(
        drive,
        driveName,
        folderId,
        "application/vnd.google-apps.document"
      );

      if (existingId) {
        await drive.files.update({
          fileId: existingId,
          media: {
            mimeType: "text/markdown",
            body: createReadStream(filePath),
          },
        });
      } else {
        await drive.files.create({
          requestBody: {
            name: driveName,
            parents: [folderId],
            mimeType: "application/vnd.google-apps.document",
          },
          media: {
            mimeType: "text/markdown",
            body: createReadStream(filePath),
          },
        });
      }
    }

    uploaded.push(driveName);

    // Upload any sibling PDFs discovered by the rules-hub processor.
    if (entry.type === "rules-hub" && entry.pdfs) {
      for (const pdfPath of entry.pdfs) {
        const absPath = resolve(pdfPath);
        if (!existsSync(absPath)) {
          console.warn(`  Skipping ${pdfPath}: PDF not found (run process first)`);
          continue;
        }
        const pdfName = pdfDriveName(pdfPath);
        const existingPdfId = await findCanonicalAndDedupe(drive, pdfName, folderId);
        if (existingPdfId) {
          await drive.files.update({
            fileId: existingPdfId,
            media: {
              mimeType: "application/pdf",
              body: createReadStream(absPath),
            },
          });
        } else {
          await drive.files.create({
            requestBody: { name: pdfName, parents: [folderId] },
            media: {
              mimeType: "application/pdf",
              body: createReadStream(absPath),
            },
          });
        }
        uploaded.push(pdfName);
      }
    }
  }

  return uploaded;
}
