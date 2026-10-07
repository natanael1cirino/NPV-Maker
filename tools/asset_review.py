"""Inventory external assets in a private NPC candidate before any ZIP export."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def review(candidate: Path, template_root: Path, provenance_file: Path) -> dict:
    manifest = json.loads((candidate / "candidate-manifest.json").read_text(encoding="utf8"))
    provenance = json.loads(provenance_file.read_text(encoding="utf8"))
    if manifest.get("format") != "npv-maker-local-npc-candidate" or not manifest.get("private_validation_only"):
        raise ValueError("Asset review requires a private NPC candidate")
    if provenance.get("purpose") != "local NPC development input; not licensed for automatic redistribution":
        raise ValueError("Template provenance needs review")
    root = manifest["entity_path"].rsplit("\\", 1)[0]
    items = []
    for relative in manifest["custom_assets"]:
        source = template_root.joinpath(*relative.split("\\"))
        packed = candidate / "archive_source"
        packed = packed.joinpath(*root.split("\\"), *relative.split("\\"))
        if not source.is_file() or not packed.is_file():
            raise ValueError(f"Missing source or packed asset: {relative}")
        original_hash, packed_hash = sha256(source), sha256(packed)
        items.append({"resource": relative, "source_sha256": original_hash,
                      "packed_sha256": packed_hash,
                      "transformed": original_hash != packed_hash,
                      "origin": "external_template_or_game_asset"})
    archive = Path(manifest["archive"])
    return {"format": "npv-maker-candidate-asset-review", "schema_version": 1,
            "project_digest": manifest["project_digest"],
            "archive_sha256": sha256(archive), "source_zip": provenance["source_zip"],
            "source_zip_sha256": provenance["source_sha256"],
            "origin_note": provenance["purpose"], "assets": items,
            "contains_external_assets": bool(items),
            "approved_for_distribution": False,
            "private_validation_only": True}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--template-root", type=Path, required=True)
    parser.add_argument("--provenance", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.output.exists():
            raise FileExistsError(args.output)
        data = review(args.candidate, args.template_root, args.provenance)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
        print(f"{args.output} ({len(data['assets'])} external assets)")
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        parser.exit(1, f"Asset review failed: {exc}\n")


if __name__ == "__main__":
    main()
