# GitFlow Branching Strategy & Semantic Versioning

**Effective from**: v0.7-asbuilt  
**Repository**: SE2026-24311351019-lake-malawi-monitoring (and mirror nyanjayathu-malawi)  
**Baseline Token**: AP19-H4WL-ZQ26  
**Date**: 2026-11-21  

---

## 1. Overview

From `v0.7-asbuilt` onward, this project will follow a **GitFlow branching model** combined with **Semantic Versioning (SemVer)**. This document ensures that:

- Human readers know which branch to use for which purpose
- AI models and automation can correctly interpret version bumps and branch semantics
- Hotfixes, features, and releases are traceable and consistent
- The `v0.7-asbuilt` baseline is the anchor for all future versioning

---

## 2. Branch Architecture

### `main` (Production)

- **Source of truth** for the currently deployed production version
- **Protected branch**: No direct commits; all changes must go through Pull Requests/Merge Requests
- **Tracking releases**: Every merge to `main` that passes CI/CD triggers a GitHub Release
- **Version**: Corresponds to the released SemVer (e.g., `v0.8.0`, `v1.0.0`)
- **Never commit directly** to `main` — use feature branches + PRs only

### `develop`

- **Integration branch** for the next release
- Contains features that are "in progress" but not yet released
- **Rebase/Squash merge** from feature branches into `develop`
- **Version**: Represents the "development snapshot" — version is `v0.N.x` where features are being accumulated for the next minor release
- **Never push raw commits directly**; use PRs to add/merge work

### `feature/*`

- **Branch off**: `develop`
- **Branch off purpose**: New module, indicator, UI page, backend service, or refactor
- **Naming convention**: `feature/description-of-feature` (lowercase, hyphens, no spaces)
- **Example**: `feature/water-extent-indicator`, `feature/ui-dashboard-redesign`, `feature/api-rate-limiting`
- **Merge back**: Into `develop` via PR, with squash or squash-and-merge preferred
- **Delete after merge**: Branch should be deleted remotely after successful merge

### `release/*`

- **Branch off**: `develop`
- **Branch off purpose**: Preparing a new production release — bump version, freeze functionality, add release notes
- **Naming convention**: `release/x.y` or `release/x.y.z` (e.g., `release/0.8`, `release/0.8.1`)
- **Activities on release branch**:
  - Bump version in `README.md`, `ADR-001.md`, or configuration files
  - Generate changelog entry
  - Final bug fixes and documentation updates
  - Tag the release (e.g., `v0.8.0`)
  - Merge to `main` and `develop` (to propagate version bump)
- **Once merged**, the release branch is considered done and can be deleted

### `hotfix/*`

- **Branch off**: `main` (not `develop`)
- **Branch off purpose**: Emergency production fix for the released version
- **Naming convention**: `hotfix/description-of-bug` (lowercase, hyphens)
- **Example**: `hotfix/crash-on-startup`, `hotfix/water-extent-negative-area`
- **Activities on hotfix branch**:
  - Apply the fix
  - Bump patch version (e.g., `v0.7.1` → `v0.8.0` if moving up, or `v0.7.1`)
  - Tag the fix on `main` (e.g., `v0.7.1`)
  - Merge to `main` (deploy production fix)
  - Merge to `develop` (propagate fix version for future releases)
- **Once merged**, the hotfix branch is deleted

---

## 3. Semantic Versioning (SemVer) Policy

### Version Format

```
MAJOR.MINOR.PATCH
```

Examples: `v0.7-asbuilt`, `v0.8.0`, `v0.8.1`, `v1.0.0`, `v1.2.3`

### Version Bump Rules

| Bump Type | When to Increment | Example |
|-----------|-------------------|---------|
| **Patch** (`PATCH + 1`) | Bug fixes, small improvements, no new functionality, backward-compatible | `v0.7.1` → `v0.7.2` after minor bug fix |
| **Minor** (`MINOR + 1`, `PATCH reset to 0`) | New features, added modules, backward-compatible enhancements, finishing a development milestone | `v0.7.0` → `v0.8.0` after completing a feature set |
| **Major** (`MAJOR + 1`, `MINOR reset to 0`, `PATCH reset to 0`) | Breaking API changes, architecture redesign, significant API changes, dropping backward compatibility | `v0.8.0` → `v1.0.0` after API-breaking changes |

### Baseline Version: `v0.7-asbuilt`

- This is the **as-built baseline** — it is **not** a standard SemVer release
- It serves as the anchor: all future versions branch from this state
- `v0.7-asbuilt` is effectively `0.7.0`-preceding, but with the `asbuilt` suffix to indicate it's the starting state
- **First release from this baseline**: `v0.8.0` (first minor release after baseline)
- **Patch releases from `v0.8.0`**: `v0.8.1`, `v0.8.2`, etc.
- **Next minor**: `v0.9.0`, then `v1.0.0`

### Version Declaration

- Declare the version in the **README** (already present in Section 1 Architecture table)
- Declare the version in **ADR-001** (already documents technology stack and decisions)
- Git tags follow the pattern: `vMAJOR.MINOR.PATCH` (e.g., `v0.8.0`, `v0.8.1`, `v1.0.0`)
- Git branch names indicate their purpose (`feature/*`, `release/*`, `hotfix/*`)

### Version in Git Tags

| Branch/Context | Expected Tag Pattern |
|----------------|----------------------|
| `main` after release | `v0.8.0`, `v1.0.0` |
| `release/*` branch | Preparing `v0.8.1`, `v1.1.0` etc. |
| `hotfix/*` branch | `v0.8.1` (patch on top of released `v0.8.0`) |
| `v0.7-asbuilt` baseline | Special tag — not a standard SemVer, but the baseline |
| Development snapshots | No tag, or `dev-v0.8.0-<date>` if needed |

---

## 4. Branch-to-Version Mapping Workflow

### Typical Flow: New Feature → Release

1. **Start feature**: `git checkout develop && git pull`
2. **Create feature branch**: `git checkout -b feature/new-indicator develop`
3. **Develop and commit**: Work in the feature branch
4. **Finish feature**: 
   - `git checkout develop`
   - `git merge --squash feature/new-indicator`
   - `git commit -m "feat: add new indicator (squashed from feature branch)"`
   - `git push origin develop`
   - `git branch -d feature/new-indicator`
   - `git push origin --delete feature/new-indicator`
5. **Create release branch**: `git checkout -b release/0.8 develop`
6. **On release branch**: 
   - Bump version: `v0.8.0` (update README, any config)
   - Add changelog/notes
   - `git commit -m "chore: bump version to v0.8.0 for release"`
7. **Merge release**: 
   - `git checkout main && git merge --no-ff release/0.8`
   - `git checkout develop && git merge --no-ff release/0.8`
   - `git tag v0.8.0`
   - `git push origin main develop --tags`
   - `gh release create v0.8.0 --notes "..."`
8. **Delete release branch**: `git branch -d release/0.8 && git push origin --delete release/0.8`

### Typical Flow: Production Hotfix

1. **Start hotfix**: `git checkout main && git pull`
2. **Create hotfix branch**: `git checkout -b hotfix/crash-fix main`
3. **Apply fix and commit**: Work in hotfix branch
4. **Finish hotfix**:
   - `git checkout main && git merge --no-ff hotfix/crash-fix`
   - `git tag v0.8.1` (patch release)
   - `git push origin main --tags`
   - `gh release create v0.8.1 --notes "Patch for crash-fix"`
   - `git checkout develop && git merge --no-ff hotfix/crash-fix` (propagate patch version)
   - `git branch -d hotfix/crash-fix && git push origin --delete hotfix/crash-fix`

---

## 5. AI & Automation Notes

This section ensures AI models and automation tools know the conventions:

### Branch Naming Patterns Recognized by CI/CD

| Pattern | Meaning |
|---------|---------|
| `feature/*` | New work — will be merged to `develop` |
| `release/*` | Release preparation — will merge to `main` and `develop`, create tag |
| `hotfix/*` | Emergency production fix — will merge to `main` and `develop`, create patch tag |
| `main` | Production — corresponds to released version tag |
| `develop` | Development snapshot — next release in progress |

### Version Increment Patterns Recognized by CI/CD

| Trigger | Version Bump |
|---------|-------------|
| PR merged to `main` with "minor" label or feature complete | `MINOR + 1`, `PATCH = 0` |
| Hotfix merged to `main` | `PATCH + 1` |
| Release branch finalized | Tag created at `vMAJOR.MINOR.PATCH` |
| `v0.7-asbuilt` baseline used as starting point | First release = `v0.8.0` |

### Expected Behavior from AI Assistants/Subagents

- When code is requested "from the current version", assume `main` branch and `v0.7-asbuilt` baseline context
- When version bump is requested, follow the SemVer rules above
- When branch is requested, use the naming conventions (`feature/*`, `release/*`, `hotfix/*`)
- When releasing, always create a Git tag `vMAJOR.MINOR.PATCH` and a GitHub Release
- The baseline `v0.7-asbuilt` should be referenced explicitly when starting new work ("from v0.7-asbuilt onward")

---

## 6. Diagram: Branch-to-Version Flow

```
                +----------------------+
                |       main           |
                |   v0.8.0 (released)  |
                +----------+-----------+
                           |
                           | hotfix
                           v
                +--------v-----------+
                |   main             |
                |   v0.8.1 (patch)   |
                +--------+-----------+
                           |
                           | merge to develop
                           v
                +--------v-----------+
                |   develop          |
                |   next release     |
                +--------+-----------+
                           |
                           | feature completions
                           v
                +--------v-----------+
                |   feature/*        |
                +--------+-----------+
                           |
                           | when enough features
                           v
                +--------v-----------+
                |   release/0.8.x    |
                +--------+-----------+
                           |
                           | finalize, bump version
                           v
                +--------v-----------+
                |   main             |
                |   v0.8.1 (or v0.9.0)|
                +--------+-----------+
                           |
                           | tag v0.8.1 created
                           v
                +--------v-----------+
                | GitHub Release     |
                +--------------------+
```

---

## 7. Checklist for Contributors

Before creating a PR or branch, verify:

- [ ] Branch name follows convention: `feature/...`, `release/...`, or `hotfix/...`
- [ ] Target branch is correct:
  - `feature/` → `develop`
  - `release/` → `main` + `develop`
  - `hotfix/` → `main` + `develop`
- [ ] Version is bumped appropriately (per SemVer rules) if this is a release/hotfix
- [ ] Git tag will be created at the appropriate version (e.g., `v0.8.0`)
- [ ] Release notes are prepared for the GitHub Release
- [ ] `v0.7-asbuilt` is acknowledged as the baseline if this is the first work after the baseline
- [ ] Commit messages follow the format: `type: description` (e.g., `feat:`, `fix:`, `chore:`, `docs:`, `refactor:`)

---

## 7. Revision History

| Version | Date | Change | Author |
|---------|------|--------|--------|
| v0.7-asbuilt baseline | 2026-11-21 | Initial GitFlow & SemVer strategy document | OpenCode analysis |
| (future) | (future) | Branch/version operations per this strategy | Project contributors |

---

*This document is the authoritative source for branching and versioning conventions for the LakeWatch project from v0.7-asbuilt onward. All contributors, AI assistants, and automation tools should reference this document when working with the repository.*