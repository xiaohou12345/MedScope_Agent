# Controlled Skill Extension Draft v1 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a proposal-only controlled skill extension draft artifact generated from gateway-reviewed research evidence proposals.

**Architecture:** Extend `scripts/research_evidence_builder.py` after gateway review and promotion dry-run creation. The new draft must be a sibling artifact in the review package, reuse candidate extensions and review items, preserve read-only safety boundaries, and write both JSON and Markdown outputs.

**Tech Stack:** Python standard library, `unittest`, existing research evidence builder module.

---

### Task 1: Add Failing Review Package Artifact Test

**Files:**
- Modify: `tests/test_research_evidence_gateway.py`

**Step 1: Write the failing test**

Add a test that calls `build_research_evidence_review_package()` with gateway-acceptable research metadata and a matching guideline skill. Assert:
- `package["controlled_skill_extension_draft"]["schema_version"] == "controlled_skill_extension_draft.v1"`
- the draft references the input `research_evidence_proposal`
- the draft contains proposed section updates with target protocol section, candidate type, source id, evidence level, and evidence use label
- no formal skill, guideline, or diagnosis update is allowed
- both `controlled_skill_extension_draft.json` and `.md` are written

**Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_research_evidence_gateway.ResearchEvidenceGatewayTest.test_review_package_generates_controlled_skill_extension_draft -v`

Expected: FAIL because `controlled_skill_extension_draft` is missing.

### Task 2: Add Blocked/Conflict Draft Behavior Test

**Files:**
- Modify: `tests/test_research_evidence_gateway.py`

**Step 1: Write the failing test**

Add a test using weak/conflicting evidence. Assert:
- draft status is `blocked_by_gateway`
- conflicting item is not promotable
- conflict reasons are preserved
- item is marked `research_only` or `exploratory`
- no formal update and no diagnosis are allowed

**Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_research_evidence_gateway.ResearchEvidenceGatewayTest.test_controlled_skill_extension_draft_blocks_conflicted_or_weak_items -v`

Expected: FAIL because draft builder is missing.

### Task 3: Implement Controlled Draft Builder

**Files:**
- Modify: `scripts/research_evidence_builder.py`

**Step 1: Add helper**

Implement `_build_controlled_skill_extension_draft(proposal, review_artifact, promotion_dry_run)`.

**Step 2: Draft fields**

The artifact should include:
- `schema_version`
- `draft_status`
- `source_proposal_schema_version`
- `target_skill_id`
- `disease_key`
- `proposed_section_updates`
- `guideline_conflict_summary`
- `promotion_dry_run_diff`
- `human_review_required`
- `runtime_safety`

**Step 3: Item fields**

Each proposed update should include:
- `item_id`
- `candidate_type`
- `source_id`
- `target_protocol_section`
- `suggested_section_action`
- `evidence_level`
- `evidence_use_label`
- `guideline_conflict_status`
- `conflict_reasons`
- `human_review_required`
- `research_mode_only`
- `formal_update_allowed`
- `diagnosis_allowed`

### Task 4: Wire Artifact Into Review Package and Outputs

**Files:**
- Modify: `scripts/research_evidence_builder.py`

**Step 1: Add package key**

Add `controlled_skill_extension_draft` to `build_research_evidence_review_package()` output.

**Step 2: Write files**

Write:
- `controlled_skill_extension_draft.json`
- `controlled_skill_extension_draft.md`

Add both paths to `output_paths`.

**Step 3: Render Markdown**

Add `_render_controlled_skill_extension_draft_markdown(draft)`.

### Task 5: Verification and Commit

**Files:**
- Modify: `scripts/research_evidence_builder.py`
- Modify: `tests/test_research_evidence_gateway.py`
- Create: `docs/plans/2026-06-06-controlled-skill-extension-draft-v1.md`

**Step 1: Focused tests**

Run: `python -m unittest tests.test_research_evidence_gateway -v`

Expected: all tests pass.

**Step 2: Adjacent tests**

Run existing adjacent gateway/contract tests.

Expected: all tests pass.

**Step 3: Full tests**

Run: `python -m unittest discover -v`

Expected: all tests pass.

**Step 4: Diff checks**

Run: `git diff --check`

Expected: no output.

**Step 5: Commit**

Commit with message: `feat: add controlled skill extension draft`
