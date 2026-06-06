# Human Review Controlled Promotion v1 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add human review decisions and a controlled promotion package for research evidence that safely supplements guideline skills without directly modifying formal skill files.

**Architecture:** Extend `build_research_evidence_review_package()` after controlled skill extension draft creation. Reviewer decisions are normalized into a decision artifact, then combined with the controlled draft to create a read-only promotion package containing approved extension previews, formal skill patch preview text, rollback notes, and an audit log. The package writes JSON/Markdown files and remains forbidden from updating formal skills or diagnosis flows.

**Tech Stack:** Python standard library, `unittest`, existing `scripts/research_evidence_builder.py` artifact pipeline.

---

### Task 1: Approved Human Review Decision RED Test

**Files:**
- Modify: `tests/test_research_evidence_gateway.py`

**Step 1: Write the failing test**

Add a test that calls `build_research_evidence_review_package()` with a gateway-passable measurement protocol and `human_review_decisions=[{"item_id": "...", "decision": "approved", ...}]`.

Assert:
- `human_review_decision.schema_version == "research_human_review_decision.v1"`
- item decision is `approved`
- `controlled_promotion_package.schema_version == "controlled_promotion_package.v1"`
- package status is `ready_for_controlled_promotion_review`
- approved updates include the target section, evidence label, and source id
- formal patch preview lists proposed additions but marks patch as not applied
- rollback notes and audit log exist
- formal skill, guideline, and diagnosis outputs are unchanged

**Step 2: Run the focused test**

Run: `python -m unittest tests.test_research_evidence_gateway.ResearchEvidenceGatewayTest.test_human_review_approval_builds_controlled_promotion_package_without_applying_patch -v`

Expected: FAIL because `human_review_decision` and `controlled_promotion_package` do not exist.

### Task 2: Rejected / Needs Revision RED Test

**Files:**
- Modify: `tests/test_research_evidence_gateway.py`

**Step 1: Write the failing test**

Add a test with one rejected item and one needs-revision item. Assert:
- package status is `not_ready_for_promotion`
- no approved updates exist
- each item decision is preserved
- patch preview has no formal skill patch
- audit log records non-approved decisions
- no formal update or diagnosis is allowed

**Step 2: Run the focused test**

Run: `python -m unittest tests.test_research_evidence_gateway.ResearchEvidenceGatewayTest.test_rejected_or_needs_revision_items_do_not_enter_promotion_package -v`

Expected: FAIL because the artifacts do not exist.

### Task 3: Implement Human Review Decision Builder

**Files:**
- Modify: `scripts/research_evidence_builder.py`

Implement `_build_human_review_decision(review_artifact, controlled_skill_extension_draft, human_review_decisions)`.

Normalize decisions to:
- `approved`
- `rejected`
- `needs_revision`
- `pending_human_review`

Keep:
- reviewer id
- reviewed at
- notes
- item id
- candidate type
- source id
- quality gate decision
- conflict status
- promotion allowed after review
- formal update / diagnosis forbidden flags

### Task 4: Implement Controlled Promotion Package Builder

**Files:**
- Modify: `scripts/research_evidence_builder.py`

Implement `_build_controlled_promotion_package(controlled_skill_extension_draft, human_review_decision)`.

Artifact fields:
- `schema_version`
- `package_status`
- `target_skill_id`
- `approved_updates`
- `rejected_or_revision_items`
- `formal_skill_patch_preview`
- `rollback_notes`
- `audit_log`
- `runtime_safety`

The formal patch preview must be a preview only and must not write or mutate a formal skill file.

### Task 5: Wire Review Package, CLI, Outputs

**Files:**
- Modify: `scripts/research_evidence_builder.py`

Add:
- `human_review_decisions` parameter to `build_research_evidence_review_package()`
- `human_review_decisions` request JSON support in CLI
- JSON/Markdown outputs:
  - `research_human_review_decision.json`
  - `controlled_promotion_package.json`
  - `controlled_promotion_package.md`

### Task 6: Verification and Commit

**Files:**
- Modify: `scripts/research_evidence_builder.py`
- Modify: `tests/test_research_evidence_gateway.py`
- Create: `docs/plans/2026-06-06-human-review-controlled-promotion-v1.md`

Run:
- `python -m unittest tests.test_research_evidence_gateway -v`
- adjacent gateway/contract tests
- `python -m unittest discover -v`
- `git diff --check`

Commit:
- `feat: add human review controlled promotion package`
