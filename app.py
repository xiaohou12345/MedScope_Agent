from __future__ import annotations

import argparse
import json

from api.service import MedScopeService


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the MedScope Agent MVP.")
    parser.add_argument("--image", required=True, help="Path to the medical image.")
    parser.add_argument("--message", required=True, help="Patient message.")
    parser.add_argument("--age", type=int, default=45)
    parser.add_argument("--sex", default="male")
    parser.add_argument(
        "--symptom",
        action="append",
        default=["髋关节疼痛"],
        help="Patient symptom. Can be passed multiple times.",
    )
    parser.add_argument(
        "--risk-factor",
        action="append",
        default=[],
        help="Patient risk factor. Can be passed multiple times.",
    )
    parser.add_argument("--disease-key", help="Optional disease knowledge key, e.g. diffuse_glioma_brats.")
    parser.add_argument(
        "--vision-mode",
        choices=["ground_truth", "medsam2"],
        help="Optional disease-specific vision mode.",
    )
    parser.add_argument("--mask", dest="mask_path", help="Optional mask path for visual workflows.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = run_cli_request(
        service=MedScopeService(),
        image_path=args.image,
        message=args.message,
        age=args.age,
        sex=args.sex,
        symptoms=args.symptom,
        risk_factors=args.risk_factor,
        disease_key=args.disease_key,
        vision_mode=args.vision_mode,
        mask_path=args.mask_path,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


def run_cli_request(
    service: MedScopeService,
    image_path: str,
    message: str,
    age: int,
    sex: str,
    symptoms: list[str],
    risk_factors: list[str],
    disease_key: str | None = None,
    vision_mode: str | None = None,
    mask_path: str | None = None,
) -> dict:
    payload = {
        "patient_message": message,
        "image_path": image_path,
        "patient_info": {
            "age": age,
            "sex": sex,
            "symptoms": symptoms,
            "risk_factors": risk_factors,
        },
    }
    optional_fields = {
        "disease_key": disease_key,
        "vision_mode": vision_mode,
        "mask_path": mask_path,
    }
    payload.update({key: value for key, value in optional_fields.items() if value})
    return service.handle_request(payload)


if __name__ == "__main__":
    main()
