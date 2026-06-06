# Formal Skill Extension Patch Preview v1 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Convert a gateway-approved controlled promotion package into a human-reviewable formal skill extension patch preview without applying the patch.

**Architecture:** Extend `build_research_evidence_review_package()` after controlled promotion package generation. The new `formal_skill_extension_patch_preview` artifact consumes approved updates from the controlled package, emits target skill and section metadata, diff preview text, sign-off checklist, rollback plan, and pre-apply audit results. The audit blocks any patch touching guideline core, diagnosis rules, or skill registry, and only permits research-mode supplemental sections.

**Tech Stack:** Python standard library, `unittest`, existing `scripts/research_evidence_builder.py` artifact pipeline.

---

### Task 1: Approved Package Patch Preview RED Test

**Files:**
- Modify: `tests/test_research_evidence_gateway.py`

**Step 1: Write failing test**

Call `build_research_evidence_review_package()` with gateway-passable metadata and an approved human review decision. Assert:
- `formal_skill_extension_patch_preview.schema_version == "formal_skill_extension_patch_preview.v1"`
- target skill id is present
- target section is a research-mode supplemental section
- diff preview is present
- sign-off checklist is present
- rollback plan is present
- pre-apply audit passes
- patch is not applied
- formal skill, guideline core, diagnosis rules, and registry are unchanged
- JSON/MD files are written

**Step 2: Run focused test**

Run: `python -m unittest tests.test_research_evidence_gateway.ResearchEvidenceGatewayTest.test_formal_skill_extension_patch_preview_is_generated_for_approved_supplemental_update -v`

Expected: FAIL because the artifact does not exist.

### Task 2: Forbidden Section Audit RED Test

**Files:**
- Modify: `tests/test_research_evidence_gateway.py`

**Step 1: Write failing test**

Call `build_research_evidence_review_package()` with an approved candidate targeting a diagnosis/core section. Assert:
- pre-apply audit blocks the patch
- violation includes forbidden target section
- diagnosis rules are not modified
- registry is not modified
- no diff preview is emitted as apply-ready
- patch remains not applied

**Step 2: Run focused test**

Run: `python -m unittest tests.test_research_evidence_gateway.ResearchEvidenceGatewayTest.test_formal_skill_extension_patch_preview_blocks_diagnosis_or_core_sections -v`

Expected: FAIL because pre-apply artifact does not exist.

### Task 3: Implement Patch Preview Builder

**Files:**
- Modify: `scripts/research_evidence_builder.py`

Add `_build_formal_skill_extension_patch_preview(controlled_promotion_package)`.

Artifact fields:
- `schema_version`
- `patch_status`
- `target_skill_id`
- `target_skill_file_preview`
- `target_sections`
- `diff_preview`
- `sign_off_checklist`
- `rollback_plan`
- `pre_apply_audit`
- `runtime_safety`

### Task 4: Implement Pre-Apply Audit

**Files:**
- Modify: `scripts/research_evidence_builder.py`

Audit rules:
- allow only `research_mode_extensions.*`, `research_evidence_supplements.*`, or research-mode supplemental wrappers generated from approved updates
- block sections containing `diagnosis_rule`, `diagnosis_rules`, `guideline_core`, `core_guideline`, `registry`, or `skill_registry`
- always set formal skill/guideline/diagnosis/registry mutation flags to false

### Task 5: Wire Outputs and Markdown

**Files:**
- Modify: `scripts/research_evidence_builder.py`

Write:
- `formal_skill_extension_patch_preview.json`
- `formal_skill_extension_patch_preview.md`

Add both paths to review package `output_paths`.

### Task 6: Verification and Commit

Run:
- `python -m unittest tests.test_research_evidence_gateway -v`
- adjacent gateway/contract tests
- `python -m unittest discover -v`
- `git diff --check`

Commit:
- `feat: add formal skill extension patch preview`
