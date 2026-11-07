"""从固定的项目检出机械导入纯 DSL 与原始样例，便于离线回归和测量。"""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import shutil
import subprocess


ROOT = Path(__file__).resolve().parent
REVISIONS = {
    "challenges": "c5c4d638101fbbfc8abe12f81cbac2ef94a25b3d",
    "lab": "3debbe3b5b580c2e4a86ab0f0c1d3ba050adfda6",
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--challenges", type=Path, required=True)
    parser.add_argument("--lab", type=Path, required=True)
    args = parser.parse_args()
    target = ROOT / "fixtures"
    target.mkdir(exist_ok=True)
    entries = []
    for project in ("challenges", "lab"):
        source = getattr(args, project)
        revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=source, capture_output=True,
                                  text=True, check=True).stdout.strip()
        if revision != REVISIONS[project]:
            raise ValueError(f"{project} 必须检出固定提交 {REVISIONS[project]}")
        if project == "challenges":
            catalog = json.loads((source / "catalog.json").read_text(encoding="utf-8"))
            rows = [(entry["id"], source / entry["directory"] / "solution.pp3",
                     json.loads((source / entry["directory"] / "cases.json").read_text(encoding="utf-8")))
                    for entry in catalog["problems"] if entry["status"] == "solved"]
        else:
            samples = json.loads((source / "examples/cases.json").read_text(encoding="utf-8"))
            rows = [(name, source / "examples" / f"{name}.pp3", cases) for name, cases in samples.items()]
        for name, path, cases in rows:
            filename = f"{name}.pp3"
            shutil.copyfile(path, target / filename)
            entries.append({"name": name, "project": project, "revision": revision,
                            "file": filename, "sha256": sha256(path.read_text(encoding="ascii").encode("ascii")).hexdigest(),
                            "cases": cases})
    (target / "manifest.json").write_text(json.dumps(entries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"已导入 {len(entries)} 个固定程序")


if __name__ == "__main__":
    main()
