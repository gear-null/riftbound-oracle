/**
 * Detect upstream changes cheaply, so a rebuild happens when Riot ships
 * something rather than on a timer.
 *
 * Two upstreams, and they are not equally reachable — this was measured, not
 * assumed:
 *
 *   Riftcodex (api.riftcodex.com)  reachable, and `/sets` reports every set's
 *                                  id, card count and publish date in ONE
 *                                  request. That is the whole detection budget.
 *
 *   Riot's Rules Hub               unreachable from a datacenter IP. Both
 *                                  riftbound.leagueoflegends.com and
 *                                  playriftbound.com resolve and then refuse
 *                                  the connection outright (http 000), which is
 *                                  the Cloudflare posture the docs warn about.
 *
 * So rules updates cannot be detected or fetched by CI, and pretending
 * otherwise would produce a job that fails every night or, worse, half-
 * regenerates. Card changes can be, and a card rebuild needs no hub access at
 * all: errata is applied from the committed `output/rules.md`.
 *
 * The watcher therefore reports card-side drift precisely and says plainly that
 * the rules side is a human's job.
 *
 * A later measurement narrowed this further: Riftcodex is behind Cloudflare too
 * and returns 403 to GitHub-hosted runners, consistently, while answering every
 * User-Agent from an ordinary connection. So NEITHER upstream is reachable from
 * hosted CI. `checkUpstream` therefore distinguishes "nothing changed" from "I
 * could not look" — a scheduled job that cannot tell the difference either
 * cries wolf nightly or silently reports all-clear, and both are worse than
 * saying so.
 */
import { readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";

export const STATE_PATH = "manifests/upstream.json";

export interface SetSnapshot {
  set_id: string;
  card_count: number;
  published_on?: string | null;
}

export interface UpstreamState {
  /** Last state a regeneration was built from. Committed, so drift is a diff. */
  sets: SetSnapshot[];
  checked?: string;
}

export interface Drift {
  changed: boolean;
  newSets: string[];
  removedSets: string[];
  countChanges: Array<{ set_id: string; from: number; to: number }>;
  summary: string;
}

export function loadState(path = STATE_PATH): UpstreamState {
  try {
    return JSON.parse(readFileSync(resolve(path), "utf-8")) as UpstreamState;
  } catch {
    return { sets: [] };
  }
}

export function saveState(sets: SetSnapshot[], checked: string, path = STATE_PATH): void {
  // Sorted so a regeneration produces a reviewable diff rather than a reshuffle.
  const ordered = [...sets].sort((a, b) => a.set_id.localeCompare(b.set_id));
  writeFileSync(
    resolve(path),
    JSON.stringify({ sets: ordered, checked }, null, 2) + "\n",
    "utf-8"
  );
}

/** Normalise whatever `/sets` returns into the fields we watch. */
export function toSnapshots(payload: unknown): SetSnapshot[] {
  const raw = Array.isArray(payload)
    ? payload
    : ((payload as { items?: unknown[] })?.items ?? []);
  return (raw as Array<Record<string, unknown>>)
    // `set_id` reaches a PR title and a commit message, so it is constrained
    // here rather than trusted. A set id is a short alphanumeric code; anything
    // else is either an API change worth noticing or something we should not be
    // interpolating into a workflow.
    .filter((s) => typeof s.set_id === "string" && /^[A-Za-z0-9_-]{1,16}$/.test(s.set_id))
    .map((s) => ({
      set_id: s.set_id as string,
      card_count: Number.isFinite(Number(s.card_count)) ? Number(s.card_count) : 0,
      published_on: (s.published_on as string) ?? null,
    }))
    .sort((a, b) => a.set_id.localeCompare(b.set_id));
}

export function diffSets(before: SetSnapshot[], after: SetSnapshot[]): Drift {
  const was = new Map(before.map((s) => [s.set_id, s]));
  const now = new Map(after.map((s) => [s.set_id, s]));

  const newSets = [...now.keys()].filter((id) => !was.has(id)).sort();
  const removedSets = [...was.keys()].filter((id) => !now.has(id)).sort();
  const countChanges = [...now.values()]
    .filter((s) => was.has(s.set_id) && was.get(s.set_id)!.card_count !== s.card_count)
    .map((s) => ({ set_id: s.set_id, from: was.get(s.set_id)!.card_count, to: s.card_count }))
    .sort((a, b) => a.set_id.localeCompare(b.set_id));

  const parts: string[] = [];
  if (newSets.length) parts.push(`new set(s): ${newSets.join(", ")}`);
  if (removedSets.length) parts.push(`set(s) withdrawn: ${removedSets.join(", ")}`);
  for (const c of countChanges) parts.push(`${c.set_id} ${c.from} → ${c.to} cards`);

  return {
    changed: parts.length > 0,
    newSets,
    removedSets,
    countChanges,
    summary: parts.length ? parts.join("; ") : "no card-side changes upstream",
  };
}

export interface CheckOptions {
  apiUrl?: string;
  statePath?: string;
  fetchSets?: (url: string) => Promise<unknown>;
}

async function defaultFetch(url: string): Promise<unknown> {
  const res = await fetch(url, { headers: { "User-Agent": "riftbound-oracle" } });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

export async function checkUpstream(opts: CheckOptions = {}) {
  const api = opts.apiUrl ?? process.env.RIFTCODEX_API_URL ?? "https://api.riftcodex.com";
  const get = opts.fetchSets ?? defaultFetch;

  let payload: unknown;
  try {
    payload = await get(`${api}/sets`);
  } catch (err) {
    // Unreachable is not the same as unchanged, and must never be reported as
    // it. Cloudflare 403s every hosted CI runner.
    return {
      reachable: false as const,
      reason: err instanceof Error ? err.message : String(err),
      drift: null,
      live: [] as SetSnapshot[],
    };
  }

  const live = toSnapshots(payload);
  if (!live.length) {
    // An empty list is far more likely to be an API hiccup than every set
    // being withdrawn, and acting on it would blank the corpus.
    throw new Error("/sets returned nothing — refusing to treat that as a change");
  }

  const state = loadState(opts.statePath);
  return { reachable: true as const, drift: diffSets(state.sets, live), live };
}
