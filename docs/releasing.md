# Releasing

## Why not changesets

Changesets exists to coordinate versions across a monorepo. This is one package, released
roughly when Riot ships a set, and the history is already conventional-commit shaped — so a
`.changeset/` file per PR would be ceremony without a payoff.

A plain conventional-commit generator is not enough either. For this project the most
important thing in a release is usually not a code change: *"rules 2026-07-16 → 2026-08-20,
28 cards corrected by errata"* is what a user needs, and no generic tool derives it from
commit messages.

So `oracle changelog` does both — groups commits by type, **and** diffs the corpus against
whatever the previous tag shipped, reading both from git rather than from memory.

## Cutting a release

```bash
# 1. Refresh the corpus (see maintaining.md — rules BEFORE cards, so errata applies)
npm run oracle process -- --only=rules && npm run oracle extract
npm run oracle process -- --only=cards && npm run oracle skill-data
(cd .claude/skills/rules-report/lib && python3 rules_cli.py build && python3 rules_cli.py selftest)

# 2. Everything green
npx tsc --noEmit && npx vitest run

# 3. Draft the entry, edit it into CHANGELOG.md
npm run oracle changelog

# 4. Bump package.json, commit, then build the artifact
npm run oracle package

# 5. Tag and publish with both files attached
gh release create vX.Y.Z \
  dist/riftbound-rules-report-vX.Y.Z.zip \
  dist/riftbound-rules-report-vX.Y.Z.zip.sha256 \
  --title "vX.Y.Z — ..." --notes-file <notes>
```

Verify the published asset by downloading it back and running `selftest` from the unzipped
copy. The build is byte-reproducible, so the checksum you publish is the one a rebuild
produces.

## Writing commits so the changelog works

Conventional prefixes: `feat`, `fix`, `docs`, `test`, `refactor`, `perf`, `build`, `ci`,
`chore`. Append `!` for a breaking change. The subject line becomes a changelog bullet, so
write it for a reader of the release, not a reader of the diff.

The body is for *why*, and it is worth the space — it is the only record of what was measured.

## Distribution channels

Three, because they serve different consumers and none of them subsumes the others:

| channel | consumer | mechanism |
|---|---|---|
| `npx skills add gear-null/riftbound-oracle` | terminal agents (17+) | clones from **git `main`** |
| Release zip | Claude Desktop / mobile | a file the GUI uploads |
| `install.sh` | no Node available | downloads the release, verifies its checksum |

The registry path needs no publishing step: Vercel's `skills` CLI installs from any public git
repo, and skills.sh lists a skill through install telemetry rather than an upload. Our layout
already satisfies it — `.claude/skills/rules-report/SKILL.md` with `name` matching the folder.

**It tracks `main`, not a tag.** So `main` must always be installable: never leave the corpus
half-regenerated there. `install.sh` and the zip are the release-pinned paths.

`SKILL-VERSION.json` is committed rather than injected at package time, precisely because the
registry path never sees the archive. Commit it when the corpus moves — `oracle package`
rewrites it and `git status` will show the drift.

It deliberately records **no commit hash**. The manifest is itself committed, so "the commit
this was built from" is self-referential — building at A writes A, committing yields B, and the
archive can never be rebuilt from its own tag, which defeats the point of reproducibility. The
version names the release; the tag names the commit.

## The installer

`install.sh` lives at the repo root and is fetched from `main`, so it is **not** versioned with
the release — a fix to the installer reaches everyone immediately, and it resolves the latest
release itself rather than hardcoding a version that goes stale every time you publish.

It resolves `latest` by following GitHub's redirect rather than parsing the API: no token, no
`jq`, and it cannot fail because a rate-limit response parsed badly.

If you rename the release asset, change the archive layout, or move the skill folder, the
installer breaks for everyone at once. `npx vitest run src/__tests__/install.test.ts` pins the
asset name and the option parsing against the packaging code.

## Versioning

Semver against the **skill's behaviour**, not the corpus:

- **patch** — corpus refresh, corrections, no behaviour change
- **minor** — new capability, new command, new report surface
- **major** — a change that breaks an existing install or the answer schema

A rules update alone is a patch, even though it is the headline in the changelog.
