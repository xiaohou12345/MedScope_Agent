from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd
from PIL import Image
from pycocotools import mask as mask_utils

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.gaodoctor_agent import GaoDoctorAgent
from api.service import MedScopeService
from scripts.agent_trace_recorder import AgentTraceRecorder, make_trace_id
from tools.structured_visual_fact_builder import build_structured_visual_facts


DEFAULT_EXPORT_DIR = Path(
    "/data/gongwenxin/datasets/onfh/cjfh/exports/"
    "onfh_mri_xray_coco_instances_clean_20260605"
)
DEFAULT_OUTPUT_DIR = Path("output/fake/onfh_coco_mock_api_eval")
DATA_ROOT = Path("/data/gongwenxin/datasets/onfh/cjfh/data")


XRAY_LABEL_TO_TARGET = {
    "硬化带": "sclerotic_band",
    "嚢性变": "cystic_change",
    "囊性变": "cystic_change",
    "软骨下骨骨折": "subchondral_fracture",
    "混杂密度区": "mixed_density_region",
}

TARGET_COLORS = {
    "sclerotic_band": (255, 74, 74),
    "cystic_change": (70, 160, 255),
    "subchondral_fracture": (255, 193, 7),
    "mixed_density_region": (76, 175, 80),
}

STAGE_SEVERITY = {
    "未发现异常": 0,
    "2期": 1,
    "3期": 2,
}

SIDE_VALUES = ("左", "右")
STRUCTURAL_COLLAPSE_TARGETS = frozenset(
    {"collapse", "subchondral_fracture", "crescent_sign"}
)


def normalize_structural_collapse_findings(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for finding in findings:
        item = dict(finding)
        target = str(item.get("target") or "")
        if target in STRUCTURAL_COLLAPSE_TARGETS and target != "collapse":
            item["original_target"] = target
            item["target"] = "collapse"
            measurements = dict(item.get("measurements") or {})
            measurements.setdefault("original_target", target)
            measurements["structural_collapse_target"] = target
            item["measurements"] = measurements
            item.setdefault("evidence_mapping", "structural_target_to_collapse")
        normalized.append(item)
    return normalized


def _has_structural_collapse_target(findings: list[dict[str, Any]]) -> bool:
    targets = {
        str(finding.get("target") or finding.get("original_target") or "")
        for finding in findings
    }
    targets.update(
        str((finding.get("measurements") or {}).get("original_target") or "")
        for finding in findings
    )
    return bool(targets & STRUCTURAL_COLLAPSE_TARGETS)


class OnfhCocoMockVisualRunner:
    """Turns reviewed Xray COCO masks into a no-model visual pipeline output."""

    def __init__(
        self,
        export_dir: Path | str = DEFAULT_EXPORT_DIR,
        side_mapping: str = "ap_flip",
    ) -> None:
        self.export_dir = Path(export_dir)
        if side_mapping not in {"no_flip", "ap_flip"}:
            raise ValueError(f"unsupported side_mapping: {side_mapping}")
        self.side_mapping = side_mapping
        self.active_patient_side: str | None = None
        self.active_source_image_path: str | None = None
        self.manifest = pd.read_csv(self.export_dir / "manifest.csv")
        self.instances = pd.read_csv(self.export_dir / "instances.csv")
        self.tags = pd.read_csv(self.export_dir / "image_tags.csv")
        self.coco = json.loads((self.export_dir / "instances_coco.json").read_text(encoding="utf-8"))
        self.categories = {item["id"]: item["name"] for item in self.coco["categories"]}
        self.annotations_by_image_id: dict[int, list[dict[str, Any]]] = {}
        for annotation in self.coco["annotations"]:
            self.annotations_by_image_id.setdefault(int(annotation["image_id"]), []).append(annotation)
        self.manifest_by_abs = {
            str(row.absolute_path): row
            for row in self.manifest.itertuples(index=False)
        }
        self.manifest_by_rel = {
            str(row.file_name): row
            for row in self.manifest.itertuples(index=False)
        }
        self.mri_tags_by_patient_key = self._build_mri_tags_by_patient_key()
        self.mri_stage_by_patient_side = self._build_mri_stage_by_patient_side()
        self.xray_stage_by_image_side = self._build_xray_stage_by_image_side()

    def runnable_xray_rows(self) -> list[Any]:
        rows = []
        for row in self.manifest[self.manifest["modality"].eq("Xray")].itertuples(index=False):
            if int(row.image_id) not in self.xray_stage_by_image_side:
                continue
            rows.append(row)
        return rows

    def skipped_xray_rows(self) -> list[dict[str, Any]]:
        skipped = []
        for row in self.manifest[self.manifest["modality"].eq("Xray")].itertuples(index=False):
            patient_key = self._patient_key(row.category, row.patient)
            reasons = []
            if int(row.image_id) not in self.xray_stage_by_image_side:
                reasons.append("no_xray_gt_tag")
            if reasons:
                skipped.append(
                    {
                        "image_id": int(row.image_id),
                        "patient_key": patient_key,
                        "file_name": row.file_name,
                        "reasons": reasons,
                    }
                )
        return skipped

    def __call__(
        self,
        *,
        image_path: Path | str,
        output_dir: Path | str,
        disease_skill: dict[str, Any],
        disease_key: str,
        patient_message: str,
        **_: Any,
    ) -> dict[str, Any]:
        row = self._row_for_image_path(self.active_source_image_path or image_path)
        image_id = int(row.image_id)
        annotations = self.annotations_by_image_id.get(image_id, [])
        if self.active_patient_side:
            annotations = self._annotations_for_patient_side(
                annotations=annotations,
                width=int(row.width),
                patient_side=self.active_patient_side,
            )
        patient_key = self._patient_key(row.category, row.patient)
        gt_mri_tags = self.mri_tags_by_patient_key.get(patient_key, [])
        gt_mri_stage_by_side = self.mri_stage_by_patient_side.get(patient_key, {})
        gt_xray_stage_by_side = self.xray_stage_by_image_side.get(image_id, {})
        if self.active_patient_side:
            gt_xray_stage_by_side = {
                self.active_patient_side: gt_xray_stage_by_side[self.active_patient_side]
            } if self.active_patient_side in gt_xray_stage_by_side else {}
        if not gt_xray_stage_by_side:
            return {
                "status": "skipped_no_xray_gt_tag",
                "image_path": str(image_path),
                "visual_analysis_result": None,
            }

        output = Path(output_dir)
        output.mkdir(parents=True, exist_ok=True)
        image = Image.open(row.absolute_path).convert("RGB")
        side_suffix = f"_{self.active_patient_side}" if self.active_patient_side else ""
        mask_path = output / f"image_{image_id}{side_suffix}_mock_mask.png"
        overlay_path = output / f"image_{image_id}{side_suffix}_mock_overlay.png"
        raw_findings = self._write_masks_and_build_findings(
            image=image,
            annotations=annotations,
            mask_path=mask_path,
            overlay_path=overlay_path,
        )
        findings = normalize_structural_collapse_findings(raw_findings)
        structured_facts = build_structured_visual_facts(findings)
        total_area = sum(int(finding["measurements"]["area_px"]) for finding in raw_findings)
        image_area = max(int(row.width) * int(row.height), 1)
        requested_targets = sorted({str(finding["target"]) for finding in findings})
        suspected_findings = [
            f"{finding['display_name']}：{finding['status']}，area={finding['measurements']['area_px']}px"
            for finding in findings
        ]
        measurements = {
            "mock_source_export_dir": "COCO_EXPORT_DIR" if self.active_source_image_path else str(self.export_dir),
            "xray_image_id": image_id,
            "patient_key": (
                f"xray_roi_{image_id}_{self.active_patient_side or 'image'}"
                if self.active_source_image_path
                else patient_key
            ),
            "lesion_area_px": total_area,
            "lesion_area_ratio": total_area / image_area,
        }

        result_image_path = "roi.png" if self.active_source_image_path else str(row.absolute_path)
        visual_analysis_result = {
            "image_path": result_image_path,
            "modality": "xray",
            "body_part": "hip",
            "requested_targets": requested_targets,
            "requested_features": [
                "mock_xray_coco_mask",
                "lesion_area_ratio",
                "bbox",
            ],
            "image_outputs": {
                "original_image_path": result_image_path,
                "mask_path": str(mask_path),
                "overlay_path": str(overlay_path),
            },
            "visual_evidence": {
                "femoral_head_shape": "未评估",
                "collapse": _has_structural_collapse_target(findings),
                "sclerosis": "候选阳性" if any(f["target"] == "sclerotic_band" for f in findings) else "未见标注",
                "cystic_change": "候选阳性" if any(f["target"] == "cystic_change" for f in findings) else "未见标注",
                "joint_space_narrowing": False,
                "joint_space": "未评估",
                "lesion_mask": str(mask_path),
                "confidence": 1.0,
                "texture_abnormality_score": 1.0 if findings else 0.0,
                "lesion_area_ratio": total_area / image_area,
                "collapse_ratio": 0.0,
                "joint_space_width": "unknown",
                "lesion_detected": bool(findings),
                "lesion_location": "reviewed_xray_coco_mask",
                "segmentation_quality": "mock_from_reviewed_coco_gt",
                "visual_output_mode": "mock_reviewed_coco",
                "segmentation_status": "completed",
                "disease_target": "femoral_head_necrosis",
                "measurements": measurements,
                "completeness": {
                    "xray_mask": {
                        "status": "present" if annotations else "absent",
                        "reason": (
                            "Reviewed COCO mask exists."
                            if annotations
                            else "No reviewed COCO mask for this Xray image; findings are empty."
                        ),
                    },
                },
                "findings": findings,
                "structured_visual_facts": structured_facts,
                "segmentation_results": [
                    {
                        "task_name": "mock_xray_coco_segmentation",
                        "target": "xray_onfh_findings",
                        "status": "completed" if findings else "no_reviewed_xray_mask",
                        "mask_path": str(mask_path),
                        "overlay_path": str(overlay_path),
                        "measurements": {"instance_count": len(raw_findings), "area_px": total_area},
                        "quality": {"level": "gt_reviewed_mock"},
                        "completeness": {"status": "present"},
                        "diagnosis_usable": True,
                    }
                ],
                "suspected_visual_findings": suspected_findings,
            },
        }
        summary = {
            "status": "ok",
            "image_path": str(row.absolute_path),
            "image_id": image_id,
            "patient_key": patient_key,
            "gt_mri_tags": gt_mri_tags,
            "gt_mri_stage_by_side": gt_mri_stage_by_side,
            "gt_xray_stage_by_side": gt_xray_stage_by_side,
            "finding_count": len(raw_findings),
            "mask_path": str(mask_path),
            "overlay_path": str(overlay_path),
            "visual_analysis_result": visual_analysis_result,
        }
        (output / "mock_visual_summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return summary

    def _annotations_for_patient_side(
        self,
        *,
        annotations: list[dict[str, Any]],
        width: int,
        patient_side: str,
    ) -> list[dict[str, Any]]:
        selected = []
        for annotation in annotations:
            bbox = [float(value) for value in annotation["bbox"]]
            centroid_x = bbox[0] + bbox[2] / 2
            image_side = "left" if centroid_x < width / 2 else "right"
            if self._patient_side_from_image_side(image_side) == patient_side:
                selected.append(annotation)
        return selected

    def _row_for_image_path(self, image_path: Path | str) -> Any:
        path = Path(image_path)
        key_abs = str(path)
        if key_abs in self.manifest_by_abs:
            return self.manifest_by_abs[key_abs]
        try:
            rel = str(path.relative_to(DATA_ROOT))
        except ValueError:
            rel = str(path)
        if rel in self.manifest_by_rel:
            return self.manifest_by_rel[rel]
        raise KeyError(f"image is not in export manifest: {image_path}")

    def _write_masks_and_build_findings(
        self,
        *,
        image: Image.Image,
        annotations: list[dict[str, Any]],
        mask_path: Path,
        overlay_path: Path,
    ) -> list[dict[str, Any]]:
        width, height = image.size
        label_mask = Image.new("L", (width, height), 0)
        overlay = image.convert("RGBA")
        findings = []
        for index, annotation in enumerate(annotations, start=1):
            label = self.categories[int(annotation["category_id"])]
            target = XRAY_LABEL_TO_TARGET.get(label, label)
            color = TARGET_COLORS.get(target, (180, 80, 220))
            decoded = mask_utils.decode(annotation["segmentation"])
            component = Image.fromarray((decoded > 0).astype("uint8") * int(annotation["category_id"]), mode="L")
            label_mask = Image.composite(component, label_mask, component.point(lambda value: 255 if value else 0))
            color_layer = Image.new("RGBA", (width, height), (*color, 95))
            alpha = Image.fromarray((decoded > 0).astype("uint8") * 95, mode="L")
            overlay = Image.composite(color_layer, overlay, alpha)
            bbox = [float(value) for value in annotation["bbox"]]
            area = int(annotation.get("area") or 0)
            centroid = [bbox[0] + bbox[2] / 2, bbox[1] + bbox[3] / 2]
            image_side = "left" if centroid[0] < width / 2 else "right"
            patient_side = self._patient_side_from_image_side(image_side)
            findings.append(
                {
                    "finding_id": f"mock_coco_ann_{annotation['id']}",
                    "target": target,
                    "display_name": label,
                    "status": "detected",
                    "regions": [
                        {
                            "region_id": f"ann_{annotation['id']}",
                            "mask_path": str(mask_path),
                            "overlay_path": str(overlay_path),
                            "bbox": bbox,
                            "centroid": centroid,
                            "area_px": area,
                            "area_ratio_in_image": area / max(width * height, 1),
                            "image_side": image_side,
                            "patient_side": patient_side,
                        }
                    ],
                    "confidence": 1.0,
                    "evidence_basis": "reviewed_coco_mask_as_mock_visual_output",
                    "diagnosis_usable": True,
                    "measurements": {
                        "area_px": area,
                        "area_ratio_in_image": area / max(width * height, 1),
                        "bbox": bbox,
                        "centroid": centroid,
                        "image_side": image_side,
                        "patient_side": patient_side,
                        "laterality": patient_side,
                    },
                    "segmentation_ref": {
                        "source": "clean_reviewed_coco",
                        "annotation_id": int(annotation["id"]),
                        "category_id": int(annotation["category_id"]),
                        "quality": {"level": "gt_reviewed_mock"},
                    },
                }
            )
        label_mask.save(mask_path)
        overlay.convert("RGB").save(overlay_path)
        return findings

    def _build_mri_tags_by_patient_key(self) -> dict[str, list[str]]:
        mri_tags = self.tags[self.tags["modality"].eq("MRI")].copy()
        result: dict[str, list[str]] = {}
        for row in mri_tags.itertuples(index=False):
            patient_key = self._patient_key(row.category, row.patient)
            result.setdefault(patient_key, [])
            tag = str(row.tag_label)
            if tag not in result[patient_key]:
                result[patient_key].append(tag)
        return result

    def _build_mri_stage_by_patient_side(self) -> dict[str, dict[str, dict[str, Any]]]:
        mri_tags = self.tags[self.tags["modality"].eq("MRI")].copy()
        result: dict[str, dict[str, dict[str, Any]]] = {}
        for row in mri_tags.itertuples(index=False):
            side = self._side_from_tag_label(row.tag_label)
            stage = self._stage_from_tag_label(row.tag_label)
            if side not in SIDE_VALUES or stage is None:
                continue
            patient_key = self._patient_key(row.category, row.patient)
            payload = result.setdefault(patient_key, {}).setdefault(
                side,
                {
                    "stage": stage,
                    "stage_values": [],
                    "tag_labels": [],
                    "frames": [],
                    "aggregation": "max_severity",
                },
            )
            if stage not in payload["stage_values"]:
                payload["stage_values"].append(stage)
            tag_label = str(row.tag_label)
            if tag_label not in payload["tag_labels"]:
                payload["tag_labels"].append(tag_label)
            frame = int(row.frame)
            if frame not in payload["frames"]:
                payload["frames"].append(frame)
            if STAGE_SEVERITY[stage] > STAGE_SEVERITY[payload["stage"]]:
                payload["stage"] = stage
        for sides in result.values():
            for payload in sides.values():
                payload["stage_values"] = sorted(
                    payload["stage_values"],
                    key=lambda value: STAGE_SEVERITY[value],
                )
                payload["frames"] = sorted(payload["frames"])
                payload["frame_count"] = len(payload["frames"])
        return result

    def _build_xray_stage_by_image_side(self) -> dict[int, dict[str, dict[str, Any]]]:
        xray_tags = self.tags[self.tags["modality"].eq("Xray")].copy()
        result: dict[int, dict[str, dict[str, Any]]] = {}
        for row in xray_tags.itertuples(index=False):
            side = self._side_from_tag_label(row.tag_label)
            stage = self._stage_from_tag_label(row.tag_label)
            if side not in SIDE_VALUES or stage is None:
                continue
            image_id = int(row.image_id)
            payload = result.setdefault(image_id, {}).setdefault(
                side,
                {
                    "stage": stage,
                    "stage_values": [],
                    "tag_labels": [],
                    "frames": [],
                    "aggregation": "max_severity",
                },
            )
            if stage not in payload["stage_values"]:
                payload["stage_values"].append(stage)
            tag_label = str(row.tag_label)
            if tag_label not in payload["tag_labels"]:
                payload["tag_labels"].append(tag_label)
            frame = int(row.frame)
            if frame not in payload["frames"]:
                payload["frames"].append(frame)
            if STAGE_SEVERITY[stage] > STAGE_SEVERITY[payload["stage"]]:
                payload["stage"] = stage
        for sides in result.values():
            for payload in sides.values():
                payload["stage_values"] = sorted(
                    payload["stage_values"],
                    key=lambda value: STAGE_SEVERITY[value],
                )
                payload["frames"] = sorted(payload["frames"])
                payload["frame_count"] = len(payload["frames"])
        return result

    def _patient_key(self, category: Any, patient: Any) -> str:
        return f"{category}-{patient}"

    def _patient_side_from_image_side(self, image_side: str) -> str:
        if self.side_mapping == "ap_flip":
            # AP pelvis display convention for this dataset: image left is patient right.
            return "右" if image_side == "left" else "左"
        return "左" if image_side == "left" else "右"

    def _side_from_tag_label(self, tag_label: Any) -> str | None:
        label = str(tag_label)
        if label.endswith("左"):
            return "左"
        if label.endswith("右"):
            return "右"
        return None

    def _stage_from_tag_label(self, tag_label: Any) -> str | None:
        label = str(tag_label)
        if "III" in label:
            return "3期"
        if "II" in label or "I /II" in label or "I/II" in label:
            return "2期"
        if "未见" in label or "无明显异常" in label:
            return "未发现异常"
        return None


def run_eval(
    *,
    export_dir: Path,
    output_dir: Path,
    limit: int | None,
    image_ids: list[int] | None,
    case_scope: str,
    side_mapping: str,
    patient_sides: list[str] | None,
    use_llm: bool = False,
    continue_on_error: bool = False,
) -> dict[str, Any]:
    runner = OnfhCocoMockVisualRunner(
        export_dir,
        side_mapping=side_mapping,
    )
    prompt_runner = None
    diagnosis_agent = None
    if use_llm:
        from agents.diagnosis_agent import DiagnosisDoctorAgent
        from llm.model_client import OpenAICompatibleModelClient
        from scripts.no_mask_vision_prompt_demo import _load_dotenv_local
        from scripts.recording_prompt_runner import RecordingPromptRunner

        _load_dotenv_local()
        prompt_runner = RecordingPromptRunner(OpenAICompatibleModelClient())
        diagnosis_agent = DiagnosisDoctorAgent(prompt_runner=prompt_runner)
    service = MedScopeService(
        gaodoctor_agent=GaoDoctorAgent(
            no_mask_visual_pipeline_runner=runner,
            diagnosis_agent=diagnosis_agent,
            prompt_runner=prompt_runner,
        )
    )
    rows = runner.runnable_xray_rows()
    if image_ids:
        selected_image_ids = set(image_ids)
        rows = [row for row in rows if int(row.image_id) in selected_image_ids]
    if limit is not None:
        rows = rows[:limit]
    service_units = _build_service_units(
        rows,
        runner,
        case_scope=case_scope,
        patient_sides=patient_sides,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    trace_recorder = AgentTraceRecorder(
        output_dir / "agent_traces",
        experiment_name="xray_mask_mock_original_flow",
    )
    case_results = []
    failed_service_units: list[dict[str, Any]] = []
    for unit in service_units:
        row = unit["row"]
        unit_side = unit.get("patient_side")
        patient_key = f"{row.category}-{row.patient}"
        runner.active_patient_side = str(unit_side) if unit_side else None
        side_phrase = f"本次只评估{unit_side}侧股骨头 ROI。" if unit_side else ""
        runner_image_path = str(row.absolute_path)
        service_image_path = "roi.png" if use_llm else runner_image_path
        service_payload = {
            "patient_message": (
                "请用 clean COCO 里的 Xray 医生标注 mask 作为 mock 视觉模型输出，"
                "按正式股骨头坏死流程生成结构化影像证据和报告。"
                f"{side_phrase}"
            ),
            "image_path": service_image_path,
            "patient_info": {
                "patient_id": (
                    f"xray_roi_{int(row.image_id)}_{unit_side or 'unknown'}"
                    if use_llm
                    else f"{patient_key}-{unit_side}" if unit_side else patient_key
                ),
                "symptoms": ["髋关节疼痛"],
                "source": "onfh_clean_coco_mock_eval",
                "patient_side": unit_side,
                "case_scope": case_scope,
            },
            "disease_key": "femoral_head_necrosis",
            "vision_mode": "no_mask_skill",
        }
        call_start = len(prompt_runner.calls) if prompt_runner else 0
        try:
            runner.active_source_image_path = runner_image_path
            try:
                result = service.handle_request(service_payload)
            except Exception as exc:
                live_model_calls = prompt_runner.take_new_calls(call_start) if prompt_runner else []
                failed_service_units.append(
                    {
                        "image_id": int(row.image_id),
                        "patient_key": patient_key,
                        "patient_side": unit_side,
                        "case_scope": case_scope,
                        "image_path": str(row.absolute_path),
                        "error_type": exc.__class__.__name__,
                        "error": str(exc),
                        "live_model_call_count": len(live_model_calls),
                        "live_model_calls": live_model_calls,
                    }
                )
                if continue_on_error:
                    continue
                raise
        finally:
            runner.active_patient_side = None
            runner.active_source_image_path = None
        live_model_calls = prompt_runner.take_new_calls(call_start) if prompt_runner else []
        evidence = result.get("visual_input_contract", {}).get("visual_evidence", {})
        local_gt_mri_tags = runner.mri_tags_by_patient_key.get(patient_key, [])
        local_gt_mri_stage_by_side = runner.mri_stage_by_patient_side.get(patient_key, {})
        local_gt_xray_stage_by_side = runner.xray_stage_by_image_side.get(int(row.image_id), {})
        if unit_side:
            local_gt_xray_stage_by_side = {
                str(unit_side): local_gt_xray_stage_by_side[str(unit_side)]
            } if str(unit_side) in local_gt_xray_stage_by_side else {}
        agent_final_stage = _stage_from_agent_report(result.get("report") or {})
        agent_loose_stage = _stage_from_agent_report(result.get("report") or {}, loose=True)
        agent_xray_3class_stage = _stage_from_agent_report_xray_3class(
            result.get("report") or {},
            patient_side=str(unit_side) if unit_side else None,
        )
        case_results.append(
            {
                "case_id": result.get("case_id"),
                "analysis_status": result.get("analysis_status"),
                "patient_key": patient_key,
                "case_scope": case_scope,
                "patient_side": unit_side,
                "image_id": int(row.image_id),
                "image_path": runner_image_path,
                "image_width": int(row.width),
                "image_height": int(row.height),
                "image_area_px": int(row.width) * int(row.height),
                "case_memory_path": result.get("case_memory_path"),
                "diagnostic_tendency": (result.get("report") or {}).get("diagnostic_tendency"),
                "report_stage_text": (result.get("report") or {}).get("分期判断"),
                "agent_final_stage": agent_final_stage,
                "agent_loose_stage": agent_loose_stage,
                "agent_xray_3class_stage": agent_xray_3class_stage,
                "finding_count": len(evidence.get("findings", [])),
                "live_model_call_count": len(live_model_calls),
                "live_model_calls": live_model_calls,
                "gt_xray_stage_by_side": local_gt_xray_stage_by_side,
                "gt_mri_tags": local_gt_mri_tags,
                "gt_mri_stage_by_side": local_gt_mri_stage_by_side,
                "mask_path": result.get("image_outputs", {}).get("mask_path")
                or result.get("visual_input_contract", {}).get("image_outputs", {}).get("mask_path"),
                "overlay_path": result.get("image_outputs", {}).get("overlay_path")
                or result.get("visual_input_contract", {}).get("image_outputs", {}).get("overlay_path"),
                "findings": evidence.get("findings", []),
            }
        )
    side_level_rows = _build_side_level_eval(case_results)
    instance_level_rows = _build_instance_level_visual_outputs(case_results)
    case_by_id = {str(case.get("case_id")): case for case in case_results}
    for side_row in side_level_rows:
        gt_xray_stage = side_row.get("gt_xray_stage")
        if not gt_xray_stage:
            continue
        image_id = int(side_row.get("image_id") or 0)
        case = case_by_id.get(str(side_row.get("case_id") or ""))
        if not case:
            continue
        side = str(side_row.get("patient_side") or "")
        service_payload = {
            "patient_message": (
                "请用 clean COCO 里的 Xray 医生标注 mask 作为 mock 视觉模型输出，"
                "按正式股骨头坏死流程生成结构化影像证据和报告。"
            ),
            "image_path": str(case.get("image_path") or ""),
            "patient_info": {
                "patient_id": case.get("patient_key"),
                "symptoms": ["髋关节疼痛"],
                "source": "onfh_clean_coco_mock_eval",
                "case_scope": case.get("case_scope"),
                "patient_side": side,
            },
            "disease_key": "femoral_head_necrosis",
            "vision_mode": "no_mask_skill",
        }
        side_findings = [
            finding for finding in case.get("findings", [])
            if isinstance(finding, dict)
            and (finding.get("measurements") or {}).get("patient_side") == side
        ]
        trace_recorder.add_case(
            trace_id=make_trace_id("mock", image_id, side, case.get("patient_key")),
            case_id=case.get("case_id"),
            patient_key=str(case.get("patient_key") or ""),
            image_path="roi.png" if use_llm else str(case.get("image_path") or ""),
            source="mock_xray_coco_mask_roi_side" if case_scope == "roi_side" else "mock_xray_coco_mask_side",
            service_payload=service_payload,
            visual_runner_input={
                "runner": "OnfhCocoMockVisualRunner",
                "export_dir": str(export_dir),
                "image_id": image_id,
                "patient_side": side,
                "image_path": "roi.png" if use_llm else str(case.get("image_path") or ""),
                "mock_source_image_path": str(case.get("image_path") or ""),
                "side_mapping": side_mapping,
                "case_scope": case_scope,
            },
            visual_runner_output={
                "visual_analysis_result": _side_scoped_visual_trace(
                    case=case,
                    side_row=side_row,
                    side=side,
                    side_findings=side_findings,
                ),
                "finding_count": len(side_findings),
                "side_targets": side_row.get("xray_targets"),
                "side_labels": side_row.get("xray_labels"),
                "mask_path": side_row.get("mask_path"),
                "overlay_path": side_row.get("overlay_path"),
            },
            service_result={
                "case_id": case.get("case_id"),
                "analysis_status": case.get("analysis_status"),
                "case_memory_path": case.get("case_memory_path"),
                "report": {
                    "diagnostic_tendency": case.get("diagnostic_tendency"),
                    "分期判断": case.get("report_stage_text"),
                },
            },
            evaluation={
                "image_id": image_id,
                "patient_side": side,
                "gt_xray_stage": gt_xray_stage,
                "gt_xray_tag_labels": side_row.get("gt_xray_tag_labels"),
                "gt_xray_stage_values": side_row.get("gt_xray_stage_values"),
                "agent_final_stage": side_row.get("agent_final_stage"),
                "agent_loose_stage": side_row.get("agent_loose_stage"),
                "agent_xray_3class_stage": side_row.get("agent_xray_3class_stage"),
                "correct": side_row.get("correct"),
                "loose_correct": side_row.get("loose_correct"),
                "xray_3class_correct": side_row.get("xray_3class_correct"),
                "abstained": side_row.get("abstained"),
                "loose_abstained": side_row.get("loose_abstained"),
                "xray_3class_abstained": side_row.get("xray_3class_abstained"),
                "report_stage_text": side_row.get("report_stage_text"),
            },
            model_calls=case.get("live_model_calls", []),
        )
    side_level_csv_path = output_dir / "side_level_eval.csv"
    side_level_json_path = output_dir / "side_level_eval.json"
    instance_level_csv_path = output_dir / "instance_level_visual_outputs.csv"
    instance_level_json_path = output_dir / "instance_level_visual_outputs.json"
    pd.DataFrame(side_level_rows).to_csv(side_level_csv_path, index=False)
    pd.DataFrame(instance_level_rows).to_csv(instance_level_csv_path, index=False)
    side_level_json_path.write_text(
        json.dumps(side_level_rows, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    instance_level_json_path.write_text(
        json.dumps(instance_level_rows, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    side_level_metrics = _side_level_metrics(side_level_rows, side_mapping=side_mapping)
    trace_summary = trace_recorder.write()
    public_case_results = [
        {
            key: value
            for key, value in case.items()
            if key not in {"findings", "live_model_calls"}
        }
        for case in case_results
    ]
    summary = {
        "status": "ok",
        "export_dir": str(export_dir),
        "output_dir": str(output_dir),
        "side_mapping": side_mapping,
        "use_llm": use_llm,
        "case_scope": case_scope,
        "gt_usage": "Xray GT tags are used for primary metrics. MRI GT tags are retained only as reference metadata.",
        "runnable_xray_images": len(runner.runnable_xray_rows()),
        "selected_image_ids": image_ids or [],
        "selected_patient_sides": patient_sides or [],
        "evaluated_images": len(rows),
        "evaluated_cases": len(case_results),
        "evaluated_service_units": len(service_units),
        "failed_service_units": [
            {key: value for key, value in item.items() if key != "live_model_calls"}
            for item in failed_service_units
        ],
        "failed_service_unit_count": len(failed_service_units),
        "skipped_xray_images": runner.skipped_xray_rows(),
        "side_level_eval_csv": str(side_level_csv_path),
        "side_level_eval_json": str(side_level_json_path),
        "instance_level_visual_outputs_csv": str(instance_level_csv_path),
        "instance_level_visual_outputs_json": str(instance_level_json_path),
        "agent_trace_export": trace_summary,
        "side_level_metrics": side_level_metrics,
        "cases": public_case_results,
    }
    summary_path = output_dir / "summary.json"
    summary["summary_path"] = str(summary_path)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def _side_scoped_visual_trace(
    *,
    case: dict[str, Any],
    side_row: dict[str, Any],
    side: str,
    side_findings: list[dict[str, Any]],
) -> dict[str, Any]:
    """Return only the current side's visual evidence for audit traces.

    Xray/MRI GT labels are scoring references and must not be embedded in the
    visual-evidence event, otherwise the trace looks like the vision stage saw
    labels from both sides.
    """
    return {
        "case_id": case.get("case_id"),
        "analysis_status": case.get("analysis_status"),
        "patient_key": case.get("patient_key"),
        "image_id": case.get("image_id"),
        "patient_side": side,
        "image_width": case.get("image_width"),
        "image_height": case.get("image_height"),
        "image_area_px": case.get("image_area_px"),
        "finding_count": len(side_findings),
        "mask_path": side_row.get("mask_path"),
        "overlay_path": side_row.get("overlay_path"),
        "side_targets": side_row.get("xray_targets"),
        "side_labels": side_row.get("xray_labels"),
        "side_findings": side_findings,
    }


def _build_service_units(
    rows: list[Any],
    runner: OnfhCocoMockVisualRunner,
    *,
    case_scope: str,
    patient_sides: list[str] | None = None,
) -> list[dict[str, Any]]:
    if case_scope == "image":
        return [{"row": row, "patient_side": None} for row in rows]
    if case_scope != "roi_side":
        raise ValueError(f"unsupported case_scope: {case_scope}")
    units: list[dict[str, Any]] = []
    selected_sides = set(patient_sides or SIDE_VALUES)
    for row in rows:
        image_id = int(row.image_id)
        for side in SIDE_VALUES:
            if side not in selected_sides:
                continue
            if side in runner.xray_stage_by_image_side.get(image_id, {}):
                units.append({"row": row, "patient_side": side})
    return units


def _build_side_level_eval(case_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for case in case_results:
        findings = [
            dict(finding)
            for finding in case.get("findings", [])
            if isinstance(finding, dict)
        ]
        case_side = case.get("patient_side")
        sides_to_eval = [str(case_side)] if case_side in SIDE_VALUES else list(SIDE_VALUES)
        for side in sides_to_eval:
            side_findings = [
                finding for finding in findings
                if (finding.get("measurements") or {}).get("patient_side") == side
            ]
            side_measurements = [
                dict(finding.get("measurements") or {})
                for finding in side_findings
            ]
            targets = sorted({str(finding.get("target")) for finding in side_findings})
            labels = sorted({str(finding.get("display_name")) for finding in side_findings})
            agent_final_stage = _normalize_stage(case.get("agent_final_stage"))
            agent_loose_stage = _normalize_stage(case.get("agent_loose_stage"))
            report_for_side = {
                "diagnostic_tendency": case.get("diagnostic_tendency"),
                "分期判断": case.get("report_stage_text"),
            }
            agent_xray_3class_stage = _stage_from_agent_report_xray_3class(
                report_for_side,
                patient_side=side,
            )
            gt_xray_payload = (case.get("gt_xray_stage_by_side") or {}).get(side) or {}
            gt_mri_payload = (case.get("gt_mri_stage_by_side") or {}).get(side) or {}
            gt_xray_stage = gt_xray_payload.get("stage")
            gt_mri_stage = gt_mri_payload.get("stage")
            side_area_px = sum(int(item.get("area_px") or 0) for item in side_measurements)
            image_area_px = int(case.get("image_area_px") or 0)
            union_bbox = _union_bbox(
                [
                    item.get("bbox")
                    for item in side_measurements
                    if isinstance(item.get("bbox"), list)
                ]
            )
            rows.append(
                {
                    "case_id": case.get("case_id"),
                    "patient_key": case.get("patient_key"),
                    "image_id": case.get("image_id"),
                    "image_path": case.get("image_path"),
                    "image_width": case.get("image_width"),
                    "image_height": case.get("image_height"),
                    "image_area_px": image_area_px,
                    "patient_side": side,
                    "agent_final_stage": agent_final_stage,
                    "agent_loose_stage": agent_loose_stage,
                    "agent_xray_3class_stage": agent_xray_3class_stage,
                    "gt_xray_stage": gt_xray_stage,
                    "correct": bool(agent_final_stage == gt_xray_stage) if gt_xray_stage else False,
                    "loose_correct": bool(agent_loose_stage == gt_xray_stage) if gt_xray_stage else False,
                    "xray_3class_correct": (
                        bool(agent_xray_3class_stage == gt_xray_stage) if gt_xray_stage else False
                    ),
                    "abstained": agent_final_stage == "abstain",
                    "loose_abstained": agent_loose_stage == "abstain",
                    "xray_3class_abstained": agent_xray_3class_stage == "abstain",
                    "gt_mri_stage_reference": gt_mri_stage,
                    "correct_vs_mri_reference": (
                        bool(agent_final_stage == gt_mri_stage) if gt_mri_stage else False
                    ),
                    "has_xray_side_mask": bool(side_findings),
                    "xray_targets": "|".join(targets),
                    "xray_labels": "|".join(labels),
                    "xray_instance_count": len(side_findings),
                    "xray_side_area_px": side_area_px,
                    "xray_side_area_ratio": side_area_px / image_area_px if image_area_px else 0.0,
                    "xray_side_union_bbox_x": union_bbox[0] if union_bbox else None,
                    "xray_side_union_bbox_y": union_bbox[1] if union_bbox else None,
                    "xray_side_union_bbox_w": union_bbox[2] if union_bbox else None,
                    "xray_side_union_bbox_h": union_bbox[3] if union_bbox else None,
                    "xray_instance_area_px_list": "|".join(
                        str(int(item.get("area_px") or 0)) for item in side_measurements
                    ),
                    "xray_instance_area_ratio_list": "|".join(
                        f"{float(item.get('area_ratio_in_image') or 0.0):.8g}"
                        for item in side_measurements
                    ),
                    "gt_xray_stage_values": "|".join(gt_xray_payload.get("stage_values") or []),
                    "gt_xray_tag_labels": "|".join(gt_xray_payload.get("tag_labels") or []),
                    "gt_xray_frame_count": gt_xray_payload.get("frame_count", 0),
                    "gt_mri_stage_values_reference": "|".join(gt_mri_payload.get("stage_values") or []),
                    "gt_mri_tag_labels_reference": "|".join(gt_mri_payload.get("tag_labels") or []),
                    "gt_mri_frame_count_reference": gt_mri_payload.get("frame_count", 0),
                    "report_stage_text": case.get("report_stage_text"),
                    "mask_path": case.get("mask_path"),
                    "overlay_path": case.get("overlay_path"),
                }
            )
    return rows


def _build_instance_level_visual_outputs(case_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for case in case_results:
        image_area_px = int(case.get("image_area_px") or 0)
        for finding in case.get("findings", []):
            if not isinstance(finding, dict):
                continue
            measurements = dict(finding.get("measurements") or {})
            bbox = measurements.get("bbox") or [None, None, None, None]
            centroid = measurements.get("centroid") or [None, None]
            area_px = int(measurements.get("area_px") or 0)
            rows.append(
                {
                    "case_id": case.get("case_id"),
                    "patient_key": case.get("patient_key"),
                    "image_id": case.get("image_id"),
                    "image_path": case.get("image_path"),
                    "image_width": case.get("image_width"),
                    "image_height": case.get("image_height"),
                    "image_area_px": image_area_px,
                    "finding_id": finding.get("finding_id"),
                    "target": finding.get("target"),
                    "label": finding.get("display_name"),
                    "status": finding.get("status"),
                    "patient_side": measurements.get("patient_side"),
                    "image_side": measurements.get("image_side"),
                    "area_px": area_px,
                    "area_ratio_in_image": float(measurements.get("area_ratio_in_image") or 0.0),
                    "area_ratio_recomputed": area_px / image_area_px if image_area_px else 0.0,
                    "bbox_x": bbox[0],
                    "bbox_y": bbox[1],
                    "bbox_w": bbox[2],
                    "bbox_h": bbox[3],
                    "centroid_x": centroid[0],
                    "centroid_y": centroid[1],
                    "diagnosis_usable": finding.get("diagnosis_usable"),
                    "evidence_basis": finding.get("evidence_basis"),
                    "annotation_id": (finding.get("segmentation_ref") or {}).get("annotation_id"),
                    "category_id": (finding.get("segmentation_ref") or {}).get("category_id"),
                    "mask_path": case.get("mask_path"),
                    "overlay_path": case.get("overlay_path"),
                }
            )
    return rows


def _union_bbox(bboxes: list[list[Any]]) -> list[float] | None:
    valid = [
        [float(value) for value in bbox]
        for bbox in bboxes
        if len(bbox) == 4 and all(value is not None for value in bbox)
    ]
    if not valid:
        return None
    min_x = min(bbox[0] for bbox in valid)
    min_y = min(bbox[1] for bbox in valid)
    max_x = max(bbox[0] + bbox[2] for bbox in valid)
    max_y = max(bbox[1] + bbox[3] for bbox in valid)
    return [min_x, min_y, max_x - min_x, max_y - min_y]


def _stage_from_agent_report(report: dict[str, Any], loose: bool = False) -> str:
    stage_text = str(report.get("分期判断") or "")
    tendency = str(report.get("diagnostic_tendency") or report.get("诊断倾向") or "")
    text = f"{tendency}\n{stage_text}"
    return _normalize_stage(text, loose=loose)


def _stage_from_agent_report_xray_3class(
    report: dict[str, Any],
    *,
    patient_side: str | None = None,
) -> str:
    stage_text = str(report.get("分期判断") or "")
    tendency = str(report.get("diagnostic_tendency") or report.get("诊断倾向") or "")
    text = f"{tendency}\n{stage_text}"
    if patient_side:
        # Prefer the structured stage field for side-aware scoring. The broader
        # diagnostic tendency can contain comparative phrases such as "left is
        # more advanced than right", which are not a right-side stage statement.
        for source_text in (stage_text, text):
            side_text = _extract_side_specific_report_text(source_text, patient_side)
            if not side_text:
                continue
            side_stage = _normalize_stage_xray_3class(side_text)
            if side_stage != "abstain":
                return side_stage
    return _normalize_stage_xray_3class(text)


def _extract_side_specific_report_text(text: str, patient_side: str) -> str:
    other_side = "右" if patient_side == "左" else "左"
    side_markers = (f"{patient_side}髋", f"{patient_side}侧", f"{patient_side}股骨头")
    other_markers = (f"{other_side}髋", f"{other_side}侧", f"{other_side}股骨头")
    candidates: list[str] = []
    for marker in side_markers:
        start = text.find(marker)
        if start < 0:
            continue
        end_positions = [
            pos
            for other in other_markers
            for pos in [text.find(other, start + len(marker))]
            if pos >= 0
        ]
        sentence_positions = [
            pos
            for sep in ("。", "\n")
            for pos in [text.find(sep, start + len(marker))]
            if pos >= 0
        ]
        end = min(end_positions + sentence_positions) if (end_positions or sentence_positions) else len(text)
        candidates.append(text[start:end])
    return "\n".join(candidates)


def _normalize_stage_xray_3class(value: Any) -> str:
    text = str(value or "")
    if not text.strip():
        return "abstain"
    if text in {"未发现异常", "2期", "3期"}:
        return text
    if text in {"normal", "无异常", "无明显异常"}:
        return "未发现异常"
    if text in {"III+", "III", "III期", "ARCO III", "ARCO III期"}:
        return "3期"
    if text in {"I/II", "II", "II期", "ARCO II", "ARCO II期"}:
        return "2期"
    if _has_affirmed_stage3_xray_evidence(text):
        return "3期"
    if _has_affirmed_stage2_xray_evidence(text):
        return "2期"
    if _has_broad_uncertainty(text):
        return "abstain"
    if "未见" in text or "无明显异常" in text or "未发现异常" in text or "normal" in text.lower():
        return "未发现异常"
    return "abstain"


def _has_affirmed_stage3_xray_evidence(text: str) -> bool:
    positive_terms = ("ARCO III", "III期", "3期", "三期", "软骨下骨折", "新月征", "塌陷")
    if not any(term in text for term in positive_terms):
        return False
    if "不能按塌陷阴性处理" in text:
        return True
    negative_phrases = (
        "未见明确塌陷",
        "未形成可确认的塌陷",
        "未形成可确认的塌陷分期证据",
        "未见塌陷",
        "无塌陷",
        "塌陷阴性",
        "未见软骨下骨折",
        "无软骨下骨折",
        "未见新月征",
        "无新月征",
    )
    return not any(phrase in text for phrase in negative_phrases)


def _has_affirmed_stage2_xray_evidence(text: str) -> bool:
    positive_terms = ("ARCO II", "II期", "2期", "二期", "I/II", "I-II", "硬化带", "囊性变", "嚢性变")
    if not any(term in text for term in positive_terms):
        return False
    if _has_affirmed_stage3_xray_evidence(text):
        return False
    negative_phrases = (
        "未见硬化带",
        "无硬化带",
        "硬化带阴性",
        "未见囊性变",
        "无囊性变",
        "囊性变阴性",
        "未见嚢性变",
        "无嚢性变",
    )
    return not any(phrase in text for phrase in negative_phrases)


def _has_broad_uncertainty(text: str) -> bool:
    uncertainty_terms = ("暂无法", "不能可靠", "证据不足")
    if not any(term in text for term in uncertainty_terms):
        return False
    # In the Xray 3-class task, uncertainty about ARCO IV does not invalidate
    # an explicit ARCO III prediction because IV is outside the label space.
    iv_terms = ("IV", "4期", "四期")
    if any(term in text for term in iv_terms) and _has_affirmed_stage3_xray_evidence(text):
        return False
    return True


def _normalize_stage(value: Any, loose: bool = False) -> str:
    text = str(value or "")
    if not text.strip():
        return "abstain"
    if text in {"未发现异常", "2期", "3期", "abstain"}:
        return text
    if text in {"normal", "无异常", "无明显异常"}:
        return "未发现异常"
    if text in {"I/II", "II", "II期", "ARCO II", "ARCO II期"}:
        return "2期"
    if text in {"III+", "III", "III期", "ARCO III", "ARCO III期"}:
        return "3期"
    if not loose and ("暂无法" in text or "不能可靠" in text or "证据不足" in text):
        return "abstain"
    if "III" in text or "3期" in text or "三期" in text or "软骨下骨折" in text:
        return "3期"
    if "II" in text or "2期" in text or "二期" in text or "I-II" in text or "I/II" in text:
        return "2期"
    if "塌陷" in text and not any(phrase in text for phrase in ("未见塌陷", "无塌陷", "塌陷阴性")):
        return "3期"
    if "未见" in text or "无明显异常" in text or "未发现异常" in text or "normal" in text.lower():
        return "未发现异常"
    return "abstain"


def _side_level_metrics(rows: list[dict[str, Any]], *, side_mapping: str) -> dict[str, Any]:
    evaluable = [row for row in rows if row.get("gt_xray_stage")]
    
    def _compute_metrics(pred_col: str, correct_col: str, abstain_col: str) -> dict[str, Any]:
        correct = [row for row in evaluable if row.get(correct_col)]
        non_abstain = [row for row in evaluable if not row.get(abstain_col)]
        non_abstain_correct = [row for row in non_abstain if row.get(correct_col)]
        by_stage: dict[str, dict[str, int]] = {}
        confusion: dict[str, dict[str, int]] = {}
        for row in evaluable:
            gt_stage = str(row.get("gt_xray_stage"))
            pred_stage = str(row.get(pred_col))
            bucket = by_stage.setdefault(gt_stage, {"total": 0, "correct": 0})
            bucket["total"] += 1
            if row.get(correct_col):
                bucket["correct"] += 1
            confusion.setdefault(gt_stage, {})
            confusion[gt_stage][pred_stage] = confusion[gt_stage].get(pred_stage, 0) + 1
        for payload in by_stage.values():
            payload["accuracy"] = payload["correct"] / payload["total"] if payload["total"] else 0.0
        return {
            "evaluable_side_cases": len(evaluable),
            "correct": len(correct),
            "accuracy": len(correct) / len(evaluable) if evaluable else None,
            "abstained": len(evaluable) - len(non_abstain),
            "coverage": len(non_abstain) / len(evaluable) if evaluable else None,
            "non_abstain_correct": len(non_abstain_correct),
            "non_abstain_accuracy": (
                len(non_abstain_correct) / len(non_abstain) if non_abstain else None
            ),
            "by_gt_stage": by_stage,
            "confusion": confusion,
        }

    return {
        "side_cases": len(rows),
        "prediction_rule": "Primary prediction is parsed from the original MedScope final report.",
        "xray_3class_prediction_rule": (
            "Xray 3-class parsing treats explicit ARCO III evidence as 3期 even if the report "
            "says ARCO IV cannot be assessed, because IV is outside the current label space."
        ),
        "gt_rule": "Xray tags are aggregated per image side by max severity: 未发现异常 < 2期 < 3期.",
        "side_mapping": _side_mapping_description(side_mapping),
        "agent_final_metrics": _compute_metrics("agent_final_stage", "correct", "abstained"),
        "agent_loose_metrics": _compute_metrics("agent_loose_stage", "loose_correct", "loose_abstained"),
        "agent_xray_3class_metrics": _compute_metrics(
            "agent_xray_3class_stage",
            "xray_3class_correct",
            "xray_3class_abstained",
        ),
    }


def _side_mapping_description(side_mapping: str) -> str:
    if side_mapping == "no_flip":
        return "no_flip: image_left -> patient_left, image_right -> patient_right."
    return "ap_flip: image_left -> patient_right, image_right -> patient_left."


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run MedScope API flow using clean ONFH Xray COCO masks as mock visual outputs."
    )
    parser.add_argument("--export-dir", type=Path, default=DEFAULT_EXPORT_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--limit", type=int, default=None, help="Limit evaluated Xray images.")
    parser.add_argument(
        "--image-id",
        type=int,
        action="append",
        default=None,
        help="Evaluate only the specified Xray image_id. Can be repeated.",
    )
    parser.add_argument(
        "--case-scope",
        choices=["image", "roi_side"],
        default="image",
        help=(
            "image: run one MedScope case per Xray image, then score sides. "
            "roi_side: run one MedScope case per patient-side ROI."
        ),
    )
    parser.add_argument(
        "--side-mapping",
        choices=["no_flip", "ap_flip"],
        default="ap_flip",
        help=(
            "How to map Xray image halves to patient sides. "
            "ap_flip: image_left->patient_right. no_flip: image_left->patient_left."
        ),
    )
    parser.add_argument(
        "--patient-side",
        choices=list(SIDE_VALUES),
        action="append",
        default=None,
        help=(
            "Evaluate only the specified patient side in roi_side mode. "
            "Can be repeated. Defaults to all sides."
        ),
    )
    parser.add_argument(
        "--use-llm",
        action="store_true",
        help="Use PromptRunner-backed diagnosis/explanation calls and record them in agent traces.",
    )
    parser.add_argument(
        "--continue-on-error",
        action="store_true",
        help="Record failed service units and continue the batch instead of aborting.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = run_eval(
        export_dir=args.export_dir,
        output_dir=args.output_dir,
        limit=args.limit,
        image_ids=args.image_id,
        case_scope=args.case_scope,
        side_mapping=args.side_mapping,
        patient_sides=args.patient_side,
        use_llm=args.use_llm,
        continue_on_error=args.continue_on_error,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
