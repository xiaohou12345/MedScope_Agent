from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import os
import time
from pathlib import Path
from typing import Any, Protocol
from urllib import request

from PIL import Image

from llm.model_call_logger import elapsed_ms, log_model_call, new_call_id
from llm.model_client import ApiRouteLog
from llm.response_stream import parse_openai_compatible_sse_response


class VisionClient(Protocol):
    def chat_with_image(
        self,
        *,
        image_path: Path | str,
        system_prompt: str,
        user_payload: dict[str, Any],
        task: str,
    ) -> str:
        """Return model text for one image-grounded prompt."""


class OpenAICompatibleVisionClient:
    """OpenAI-compatible image chat client for lesion prompt generation."""

    def __init__(
        self,
        route_log: ApiRouteLog | None = None,
        timeout_seconds: int = 90,
        responses_stream: bool | None = None,
    ) -> None:
        self.route_log = route_log or ApiRouteLog.from_file()
        self.timeout_seconds = timeout_seconds
        self.responses_stream = (
            _env_flag("MEDSCOPE_VISION_RESPONSES_STREAM", default=False)
            if responses_stream is None
            else responses_stream
        )

    def chat_completions_url(self) -> str:
        base_url = self.route_log.base_url_for_active_route().rstrip("/")
        if base_url.endswith("/v1/chat/completions"):
            return base_url
        if base_url.endswith("/chat/completions"):
            return base_url
        if base_url.endswith("/v1"):
            return f"{base_url}/chat/completions"
        return f"{base_url}/v1/chat/completions"

    def responses_url(self) -> str:
        base_url = self.route_log.base_url_for_active_route().rstrip("/")
        if base_url.endswith("/v1/responses"):
            return base_url
        if base_url.endswith("/responses"):
            return base_url
        if base_url.endswith("/v1"):
            return f"{base_url}/responses"
        return f"{base_url}/v1/responses"

    def chat_with_image(
        self,
        *,
        image_path: Path | str,
        system_prompt: str,
        user_payload: dict[str, Any],
        task: str,
    ) -> str:
        api_key_env = self.route_log.api_key_env_for_active_route()
        api_key = os.environ.get(api_key_env)
        if not api_key:
            raise RuntimeError(f"Missing {api_key_env}; configure the active vision route first.")
        image = Path(image_path)
        data_url = self._image_data_url(image)
        image_summary = self._image_summary(image)
        if self.route_log.api_endpoint_for_active_route() == "responses":
            return self._chat_with_image_responses_api(
                image_summary=image_summary,
                data_url=data_url,
                system_prompt=system_prompt,
                user_payload=user_payload,
                task=task,
                api_key=api_key,
            )
        return self._chat_with_image_chat_completions_api(
            image_summary=image_summary,
            data_url=data_url,
            system_prompt=system_prompt,
            user_payload=user_payload,
            task=task,
            api_key=api_key,
        )

    def _chat_with_image_chat_completions_api(
        self,
        *,
        image_summary: dict[str, Any],
        data_url: str,
        system_prompt: str,
        user_payload: dict[str, Any],
        task: str,
        api_key: str,
    ) -> str:
        started_at = time.time()
        call_id = new_call_id()
        payload = {
            "model": self.route_log.vision_model_for_active_route(),
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(user_payload, ensure_ascii=False, indent=2),
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": data_url},
                        },
                    ],
                },
            ],
            "metadata": {"task": task},
            "temperature": 0,
        }
        url = self.chat_completions_url()
        req = request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "User-Agent": self.route_log.user_agent_for_active_route(),
            },
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=self.timeout_seconds) as response:
                raw_text = response.read().decode("utf-8")
                raw = json.loads(raw_text)
            content = raw["choices"][0]["message"]["content"]
            log_model_call(
                self._build_call_log_record(
                    call_id=call_id,
                    task=task,
                    endpoint="chat_completions",
                    url=url,
                    image_summary=image_summary,
                    request_payload=payload,
                    response_raw=raw,
                    response_content=content,
                    duration_ms=elapsed_ms(started_at),
                    status="ok",
                )
            )
            return content
        except Exception as exc:
            log_model_call(
                self._build_call_log_record(
                    call_id=call_id,
                    task=task,
                    endpoint="chat_completions",
                    url=url,
                    image_summary=image_summary,
                    request_payload=payload,
                    response_raw=locals().get("raw"),
                    response_text=locals().get("raw_text"),
                    duration_ms=elapsed_ms(started_at),
                    status="error",
                    error=exc,
                )
            )
            raise

    def _chat_with_image_responses_api(
        self,
        *,
        image_summary: dict[str, Any],
        data_url: str,
        system_prompt: str,
        user_payload: dict[str, Any],
        task: str,
        api_key: str,
    ) -> str:
        started_at = time.time()
        call_id = new_call_id()
        payload = {
            "model": self.route_log.vision_model_for_active_route(),
            "input": [
                {
                    "role": "system",
                    "content": [
                        {
                            "type": "input_text",
                            "text": system_prompt,
                        }
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": json.dumps(user_payload, ensure_ascii=False, indent=2),
                        },
                        {
                            "type": "input_image",
                            "image_url": data_url,
                        },
                    ],
                },
            ],
            "metadata": {"task": task},
            "store": False,
            "stream": self.responses_stream,
        }
        url = self.responses_url()
        req = request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Accept": "text/event-stream" if self.responses_stream else "application/json",
                "User-Agent": self.route_log.user_agent_for_active_route(),
            },
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=self.timeout_seconds) as response:
                if self.responses_stream:
                    content, raw = parse_openai_compatible_sse_response(response)
                    if not content:
                        raise ValueError("Responses stream did not contain output text")
                else:
                    raw_text = response.read().decode("utf-8")
                    raw = json.loads(raw_text)
                    content = self._content_from_responses_api(raw)
            log_model_call(
                self._build_call_log_record(
                    call_id=call_id,
                    task=task,
                    endpoint="responses",
                    url=url,
                    image_summary=image_summary,
                    request_payload=payload,
                    response_raw=raw,
                    response_content=content,
                    duration_ms=elapsed_ms(started_at),
                    status="ok",
                )
            )
            return content
        except Exception as exc:
            log_model_call(
                self._build_call_log_record(
                    call_id=call_id,
                    task=task,
                    endpoint="responses",
                    url=url,
                    image_summary=image_summary,
                    request_payload=payload,
                    response_raw=locals().get("raw"),
                    response_text=locals().get("raw_text"),
                    duration_ms=elapsed_ms(started_at),
                    status="error",
                    error=exc,
                )
            )
            raise

    def _content_from_responses_api(self, raw: dict[str, Any]) -> str:
        output_text = raw.get("output_text")
        if isinstance(output_text, str):
            return output_text
        texts: list[str] = []
        for item in raw.get("output") or []:
            for content in item.get("content") or []:
                text = content.get("text")
                if isinstance(text, str):
                    texts.append(text)
        if texts:
            return "\n".join(texts)
        raise ValueError("Responses API payload did not contain output text")

    def _image_data_url(self, image_path: Path) -> str:
        mime_type = mimetypes.guess_type(str(image_path))[0] or "image/png"
        encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
        return f"data:{mime_type};base64,{encoded}"

    def _image_summary(self, image_path: Path) -> dict[str, Any]:
        payload = image_path.read_bytes()
        summary: dict[str, Any] = {
            "image_path": str(image_path),
            "mime_type": mimetypes.guess_type(str(image_path))[0] or "image/png",
            "byte_length": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
        try:
            with Image.open(image_path) as image:
                summary["width"] = int(image.width)
                summary["height"] = int(image.height)
                summary["mode"] = image.mode
        except Exception as exc:
            summary["image_metadata_error"] = str(exc)
        return summary

    def _build_call_log_record(
        self,
        *,
        call_id: str,
        task: str,
        endpoint: str,
        url: str,
        image_summary: dict[str, Any],
        request_payload: dict[str, Any],
        duration_ms: int,
        status: str,
        response_raw: dict[str, Any] | None = None,
        response_content: str | None = None,
        response_text: str | None = None,
        error: Exception | None = None,
    ) -> dict[str, Any]:
        record: dict[str, Any] = {
            "call_id": call_id,
            "task": task,
            "client": self.__class__.__name__,
            "modality": "vision",
            "route": self.route_log.active_route,
            "model": self.route_log.vision_model_for_active_route(),
            "endpoint": endpoint,
            "url": url,
            "timeout_seconds": self.timeout_seconds,
            "duration_ms": duration_ms,
            "status": status,
            "image": image_summary,
            "request": {
                "payload": request_payload,
            },
            "response": {
                "content": response_content,
                "raw": response_raw,
                "raw_text": response_text,
            },
        }
        if error is not None:
            record["error"] = {
                "type": error.__class__.__name__,
                "message": str(error),
            }
        return record


class VisionPromptGenerator:
    """Turns an unmasked medical image into candidate segmentation prompts."""

    def __init__(self, client: VisionClient | None = None) -> None:
        self.client = client or OpenAICompatibleVisionClient()

    def generate(
        self,
        *,
        image_path: Path | str,
        disease_skill: dict[str, Any],
        patient_message: str,
    ) -> dict[str, Any]:
        image = Path(image_path)
        width, height = self._image_size(image)
        user_payload = self._build_user_payload(
            image_path=image,
            width=width,
            height=height,
            disease_skill=disease_skill,
            patient_message=patient_message,
        )
        content = self.client.chat_with_image(
            image_path=image,
            system_prompt=self._system_prompt(),
            user_payload=user_payload,
            task="vision_prompt_generation",
        )
        try:
            model_payload = self._parse_json_content(content)
            return self._result_from_model_payload(
                image_path=image,
                width=width,
                height=height,
                model_payload=model_payload,
                skill_required_next_images=user_payload["skill_required_next_images"],
            )
        except ValueError as exc:
            return self._invalid_result(image, width, height, str(exc), content)

    def _build_user_payload(
        self,
        *,
        image_path: Path,
        width: int,
        height: int,
        disease_skill: dict[str, Any],
        patient_message: str,
    ) -> dict[str, Any]:
        visual_protocol = disease_skill.get("visual_protocol") or {}
        finding_targets = [
            dict(item)
            for item in visual_protocol.get("finding_targets") or []
            if isinstance(item, dict)
        ]
        return {
            "patient_message": patient_message,
            "image_path": str(image_path),
            "image_size": {"width": width, "height": height},
            "disease_skill": {
                "disease_name": disease_skill.get("disease_name"),
                "visual_protocol": visual_protocol,
            },
            "requested_finding_targets": finding_targets,
            "skill_required_next_images": [
                dict(item)
                for item in visual_protocol.get("required_next_images") or []
                if isinstance(item, dict)
            ],
            "required_output_schema": {
                "modality": "xray|ct|mri|ultrasound|unknown",
                "body_part": "chest|brain|hip|abdomen|unknown",
                "needs_next_imaging": True,
                "required_next_images": [
                    {
                        "modality": "MRI|CT|X-ray|ultrasound",
                        "region": "body region",
                        "reason": "why this image is needed by the skill/guideline",
                    }
                ],
                "suspected_regions": [
                    {
                        "target": "one_of_requested_finding_targets",
                        "bbox": [0, 0, width, height],
                        "polygon": [[0, 0], [width, 0], [width, height], [0, height]],
                        "confidence": 0.0,
                        "evidence_text": "short visual evidence phrase",
                        "rationale": "visual reason only",
                    }
                ],
                "limitations": ["uncertainty or missing view"],
            },
            "safety_rules": [
                "Return strict JSON only.",
                "Do not make a final diagnosis.",
                "If requested_finding_targets is non-empty, use target values from that list.",
                "If no localizable region is visible, return an empty suspected_regions list.",
                "Coordinates must be pixel coordinates in the supplied image size.",
            ],
        }

    def _system_prompt(self) -> str:
        return (
            "You are a medical image prompt generator for a segmentation agent. "
            "Your only job is to identify candidate regions that may need segmentation. "
            "Return strict JSON only. Do not provide diagnosis or treatment advice."
        )

    def _parse_json_content(self, content: str) -> dict[str, Any]:
        text = content.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            text = "\n".join(lines).strip()
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Model did not return valid JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError("Model JSON must be an object")
        return payload

    def _result_from_model_payload(
        self,
        *,
        image_path: Path,
        width: int,
        height: int,
        model_payload: dict[str, Any],
        skill_required_next_images: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        regions = model_payload.get("suspected_regions") or []
        if not isinstance(regions, list):
            raise ValueError("suspected_regions must be a list")
        checked_regions = []
        rejected_regions = []
        for index, region in enumerate(regions, start=1):
            try:
                checked_regions.append(
                    self._checked_region(region, width=width, height=height)
                )
            except ValueError as exc:
                rejected_regions.append(
                    {
                        "index": index,
                        "reason": str(exc),
                        "raw_region": region,
                    }
                )
        if rejected_regions and not checked_regions:
            raise ValueError(rejected_regions[0]["reason"])
        boxes = [region["bbox"] for region in checked_regions]
        status = "ok" if boxes else "no_suspected_region"
        required_next_images = self._normalized_required_next_images(
            model_payload=model_payload,
            skill_required_next_images=skill_required_next_images or [],
        )
        needs_next_imaging = bool(model_payload.get("needs_next_imaging")) or bool(required_next_images)
        return {
            "status": status,
            "image_path": str(image_path),
            "image_size": {"width": width, "height": height},
            "modality": str(model_payload.get("modality") or "unknown"),
            "body_part": str(model_payload.get("body_part") or "unknown"),
            "needs_next_imaging": needs_next_imaging,
            "required_next_images": required_next_images,
            "suspected_regions": checked_regions,
            "segmentation_prompt": {
                "source": "vision_model_bbox",
                "boxes": boxes,
                "points": [],
                "image_size": {"width": width, "height": height},
            },
            "limitations": list(model_payload.get("limitations") or []),
            "rejected_regions": rejected_regions,
            "diagnosis_usable": False,
            "diagnosis_usable_reason": "This is a candidate localization prompt, not a validated segmentation result.",
            "raw_model_payload": model_payload,
        }

    def _checked_region(self, region: Any, *, width: int, height: int) -> dict[str, Any]:
        if not isinstance(region, dict):
            raise ValueError("Each suspected region must be an object")
        bbox = region.get("bbox")
        if (
            not isinstance(bbox, list)
            or len(bbox) != 4
            or not all(isinstance(value, (int, float)) for value in bbox)
        ):
            raise ValueError(f"Invalid bbox: {bbox}")
        x1, y1, x2, y2 = [int(round(value)) for value in bbox]
        if not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
            raise ValueError(f"Invalid bbox outside image bounds or empty: {[x1, y1, x2, y2]}")
        confidence = float(region.get("confidence", 0.0))
        polygon = self._checked_polygon(region.get("polygon"), width=width, height=height)
        evidence_text = str(region.get("evidence_text") or region.get("rationale") or "")
        return {
            "target": str(region.get("target") or "candidate_region"),
            "bbox": [x1, y1, x2, y2],
            "polygon": polygon,
            "confidence": max(0.0, min(1.0, confidence)),
            "evidence_text": evidence_text,
            "rationale": str(region.get("rationale") or ""),
        }

    def _checked_polygon(
        self,
        polygon: Any,
        *,
        width: int,
        height: int,
    ) -> list[list[int]]:
        if polygon in (None, ""):
            return []
        if not isinstance(polygon, list):
            raise ValueError(f"Invalid polygon: {polygon}")
        checked_points: list[list[int]] = []
        for point in polygon:
            if (
                not isinstance(point, list)
                or len(point) != 2
                or not all(isinstance(value, (int, float)) for value in point)
            ):
                raise ValueError(f"Invalid polygon point: {point}")
            x, y = [int(round(value)) for value in point]
            if not (0 <= x <= width and 0 <= y <= height):
                raise ValueError(f"Invalid polygon point outside image bounds: {[x, y]}")
            checked_points.append([x, y])
        if checked_points and len(checked_points) < 3:
            raise ValueError("Invalid polygon: at least 3 points are required")
        return checked_points

    def _normalized_required_next_images(
        self,
        *,
        model_payload: dict[str, Any],
        skill_required_next_images: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        raw_items = (
            model_payload.get("required_next_images")
            or model_payload.get("recommended_next_images")
            or skill_required_next_images
            or []
        )
        if not isinstance(raw_items, list):
            return []
        normalized: list[dict[str, Any]] = []
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            normalized.append(
                {
                    "modality": str(item.get("modality") or "unknown"),
                    "region": str(item.get("region") or item.get("body_part") or "unknown"),
                    "reason": str(item.get("reason") or ""),
                }
            )
        return normalized

    def _invalid_result(
        self,
        image_path: Path,
        width: int,
        height: int,
        error: str,
        raw_content: str,
    ) -> dict[str, Any]:
        return {
            "status": "invalid_model_output",
            "image_path": str(image_path),
            "image_size": {"width": width, "height": height},
            "modality": "unknown",
            "body_part": "unknown",
            "needs_next_imaging": False,
            "required_next_images": [],
            "suspected_regions": [],
            "segmentation_prompt": {
                "source": "vision_model_bbox",
                "boxes": [],
                "points": [],
                "image_size": {"width": width, "height": height},
            },
            "limitations": [],
            "diagnosis_usable": False,
            "diagnosis_usable_reason": "Vision model output could not be validated.",
            "errors": [error],
            "raw_model_content": raw_content,
        }

    def _image_size(self, image_path: Path) -> tuple[int, int]:
        with Image.open(image_path) as image:
            return image.size


def _env_flag(name: str, *, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}
