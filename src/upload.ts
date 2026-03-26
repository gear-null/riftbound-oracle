import { readFileSync, writeFileSync, existsSync, mkdirSync, createReadStream } from "node:fs";
import { resolve, dirname } from "node:path";
import { createServer } from "node:http";
import { google } from "googleapis";
import { readManifest, type ManifestEntry } from "./manifest.js";

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

async function deleteExisting(
  drive: ReturnType<typeof google.drive>,
  name: string,
  folderId: string,
  mimeFilter?: string
): Promise<void> {
  const mimeClause = mimeFilter ? ` and mimeType = '${mimeFilter}'` : "";
  const existing = await drive.files.list({
    q: `name = '${name}' and '${folderId}' in parents${mimeClause} and trashed = false`,
    fields: "files(id)",
  });

  if (existing.data.files) {
    for (const file of existing.data.files) {
      await drive.files.delete({ fileId: file.id! });
    }
  }
}

export async function uploadToDrive(): Promise<string[]> {
  const authClient = await authorize();
  const drive = google.drive({ version: "v3", auth: authClient });
  const folderId = getDriveFolderId();
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

      await deleteExisting(drive, driveName + ".pdf", folderId);

      await drive.files.create({
        requestBody: {
          name: driveName + ".pdf",
          parents: [folderId],
        },
        media: {
          mimeType: "application/pdf",
          body: createReadStream(pdfPath),
        },
      });
    } else {
      // Upload markdown as Google Doc
      const filePath = resolve(entry.output);
      if (!existsSync(filePath)) {
        console.warn(`  Skipping ${driveName}: output not found at ${entry.output}`);
        continue;
      }

      await deleteExisting(drive, driveName, folderId, "application/vnd.google-apps.document");

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

    uploaded.push(driveName);
  }

  return uploaded;
}
