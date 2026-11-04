# ADR-0008: Retain Raw Release Evidence Outside Git

- **Status:** Accepted
- **Date:** 2026-11-04
- **Deciders:** Maintainers, Release Owner, Integration Lead
- **Supersedes:** None
- **Related:** GitHub Issue #120; Stage 3 implementation plan; `docs/development.md`

## Context

AMKernel release claims depend on reviewable mobile, client, and cross-platform evidence. The repository currently retains both normalized decision records and raw outputs such as logs, screenshots, binaries, transcripts, repeated environment captures, and per-environment process records. Those raw files account for most tracked worktree bytes and include exact duplicates. Stage 3 planning instead assigned large transcripts, screenshots, and logs to workflow or run artifacts.

Short-lived GitHub Actions artifacts are not sufficient for published support claims. Conversely, adding files to an existing immutable GitHub Release would violate the release contract in `docs/development.md`. The first safe migration point is therefore the next normal patch release, `v0.1.2`.

## Decision

AMKernel separates release evidence into two retention classes.

Git retains bounded evidence required to understand and verify a decision without fetching network content:

- schemas and validators;
- normalized indexes and manifests;
- decision and validation reports;
- independent review records;
- bounded final summaries and omitted-parts declarations;
- content digests and durable release-asset provenance.

Git does not retain raw logs, screenshots, binaries, full transcripts, repeated intermediate captures, or per-environment output once those files are present in an immutable release evidence archive.

The `v0.1.2` release preserves the complete pre-migration `evidence/` corpus in two immutable assets built by authoritative CI from the exact release commit:

- `amkernel-evidence-0.1.2.tar.gz`;
- `amkernel-evidence-0.1.2.manifest.json`.

The archive is deterministic: sorted regular files, normalized metadata, one `evidence/` prefix, and no links. The external manifest records the release version, full commit, archive name, byte size and SHA-256, and every member path, size and SHA-256. Release preparation validates the archive and manifest before publication. Release verification requires the exact wheel and both evidence assets; no source distribution or unlisted asset is accepted.

After the immutable `v0.1.2` assets are published and independently verified, a follow-up commit removes migrated raw files from the default branch, updates retained indexes with the archive provenance, and ignores future raw output locations. The migration does not rewrite Git history.

Normal tests remain offline. Archive validators accept local paths and never download release assets. Workflows may download an explicitly identified release asset for release or audit jobs, but product tests do not depend on network availability.

## Consequences

Published raw evidence remains durable and content-addressed without increasing every future checkout. The release grows by one compressed archive and one manifest. The `v0.1.2` release must not be published until authoritative CI has generated and validated both assets from the exact release commit.

Repository cleanup is intentionally two-step. Raw evidence remains tracked until the immutable release exists; deleting it in the same unpublished change would leave no durable source if release publication failed. Release immutability prevents repairing a missing or incorrect evidence asset after publication, so archive validation is fail-closed.

Existing historical commits continue to contain the old files. This is acceptable because the Git object database is small and no confirmed secret requires destructive history rewriting.

## Verification

- Two independent archive builds from one source tree are byte-identical.
- The external manifest and tar members match in path, byte size, and SHA-256.
- Authoritative CI retains the archive and manifest with the exact tested wheel.
- Release preparation rejects version, commit, member, or digest drift.
- GitHub release verification rejects every asset set other than the exact wheel, archive, and manifest.
- The post-release cleanup does not begin until GitHub reports the release immutable and all three assets independently verify.

## Alternatives Considered

### Add evidence to `v0.1.1`

Rejected because published release tags and assets are immutable by repository contract.

### Create an `evidence-v0.1.1` release and tag

Rejected because it introduces a second release namespace and weakens the one-version, one-authoritative-release model.

### Keep all evidence in Git

Rejected because raw output dominates checkout size, repeats exact content, and conflicts with the established workflow-artifact boundary.

### Rewrite repository history

Rejected because current Git storage is small, while rewriting would invalidate commit, tag, issue, and provenance references.
