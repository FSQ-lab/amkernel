# ADR-0002: GitHub Is the Canonical Project-Management System

- Status: Accepted
- Date: 2026-10-28
- Deciders: Project owner; Contract and Integration Lead
- Supersedes: local backlog and risk-register status files
- Related: [GitHub repository](https://github.com/FSQ-lab/amkernel), [organization Project](https://github.com/orgs/FSQ-lab/projects/2), [M1 milestone](https://github.com/FSQ-lab/amkernel/milestone/1)

## Context

AMKernel initially recorded work-item state and risks in `docs/backlog.md` and `docs/risks.md`. Those files made status visible before a hosted repository existed, but they duplicate the issue tracker once collaboration moves to GitHub. Maintaining status in both Git and GitHub would create two sources of truth, stale state, non-atomic updates, and avoidable merge conflicts.

The project now has a public repository under the FSQ-lab organization, a public organization Project, a Stage 1 milestone, issue forms, labels, and migrated work/risk issues.

## Decision

GitHub is the only canonical project-status system:

- repository: <https://github.com/FSQ-lab/amkernel>;
- organization Project: <https://github.com/orgs/FSQ-lab/projects/2>;
- work-item and risk detail: repository Issues;
- delivery grouping and exit tracking: GitHub Milestones;
- workflow, stage, work type, and priority: organization Project fields;
- dependency, blocker, owner, acceptance, and evidence: Issue bodies and links;
- implementation review: Pull Requests linked to Issues.

`docs/backlog.md` and `docs/risks.md` are removed. No generated or manually synchronized local copy replaces them.

Repository documents retain only durable material:

- architecture and delivery-stage definitions;
- development and quality policy;
- project-management workflow and field semantics;
- accepted ADRs;
- experiment definitions;
- implementation evidence that belongs with versioned code.

ADRs remain versioned in the repository because they explain durable technical decisions rather than current project status. An ADR links the relevant GitHub Issues instead of a local backlog item.

## GitHub workflow

The Project uses these canonical fields:

- `Status`: Backlog, Planning, Ready, In Progress, Review, Verification, Blocked, Done, Dropped;
- `Stage`: Stage 1, Stage 2, Stage 3, Stage 4, Governance;
- `Work Type`: Decision, Implementation, Verification, Risk, Governance, Experiment;
- `Priority`: Critical, High, Medium, Low.

A work item may move to `Ready` only when its Issue contains the complete task contract defined in `docs/project-management.md`. A blocked item records `Blocked from`, blocker, blocker owner, and resume state in its Issue.

A change that affects status, risks, or verification updates the linked Issue and Project fields. Pull Requests must link the affected work and risk Issues. Local Markdown must not be used to shadow live Project state.

## Consequences

### Positive

- One live status source for humans and Agents.
- Work, risks, milestones, review, and delivery evidence are linkable.
- Kanban state changes do not require status-only repository commits.
- Public progress is visible without reading the working tree.
- GitHub automation and branch protection can consume the same records later.

### Costs and constraints

- Status inspection and mutation require GitHub availability and authenticated API access.
- Offline clones retain durable policy and decisions but not a snapshot of current status.
- Agents must read the active Project and linked Issues before starting work.
- Project-field automation and branch protection remain separate work until CI job names are stable.
- GitHub exports may be used for disaster recovery, but an export is not a second writable source of truth.

## Alternatives considered

### Keep local backlog and risk files synchronized with GitHub

Rejected. Dual-write synchronization adds failure modes without improving project truth. A stale local file would be actively misleading.

### Keep project management entirely in local Markdown

Rejected after the public repository was created. It lacks collaborative assignment, filtering, Project views, milestone integration, review links, and hosted automation.

### Use GitHub Issues without an organization Project

Rejected. Issues hold durable item detail, but the Project provides the explicit Kanban state, stage, type, priority, and cross-repository organization required by the management model.

## Verification

This decision is in effect when:

1. the repository and organization Project are publicly readable;
2. all current Stage 1 work and registered risks exist as Issues;
3. every current Issue is linked to the Project with canonical fields;
4. the Stage 1 milestone groups required delivery work;
5. issue and pull-request templates are present on the default branch;
6. local backlog and risk status files and their imports are removed;
7. project-management documentation names GitHub as the sole status source.
