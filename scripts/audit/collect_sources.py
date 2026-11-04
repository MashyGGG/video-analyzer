"""Pin candidate source/model revisions and preserve only public license metadata."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "evidence/A00/sources"
REPOS = ["XztCloud/parse_video", "JuneYaooo/rea-video",
         "Evil0ctal/Douyin_TikTok_Download_API", "yt-dlp/yt-dlp", "FFmpeg/FFmpeg",
         "Breakthrough/PySceneDetect", "modelscope/FunASR", "PaddlePaddle/PaddleOCR",
         "QwenLM/Qwen3-VL", "vllm-project/vllm", "volcengine/volcengine-python-sdk"]
MODELS = ["Qwen/Qwen3-VL-8B-Instruct", "funasr/paraformer-zh",
          "PaddlePaddle/PP-OCRv5_server_det", "PaddlePaddle/PP-OCRv5_server_rec"]


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "video-analyzer-A00-audit"})
    with urllib.request.urlopen(req, timeout=35) as response:
        return response.read()


def save_text(folder, name, data):
    (folder / name).write_bytes(data)
    return {"file": str((folder / name).relative_to(ROOT)).replace("\\", "/"),
            "sha256": hashlib.sha256(data).hexdigest()}


def repository(repo):
    folder = OUT / repo.replace("/", "__")
    folder.mkdir(parents=True, exist_ok=True)
    if (folder / "metadata.json").exists():
        return json.loads((folder / "metadata.json").read_text(encoding="utf-8"))
    result = {"kind": "source", "repository": repo, "observed_at_utc": datetime.now(timezone.utc).isoformat()}
    try:
        proc = subprocess.run(["git", "ls-remote", f"https://github.com/{repo}.git", "HEAD"],
                              capture_output=True, text=True, timeout=60, check=True)
        sha = proc.stdout.split()[0]
        result["revision"] = sha
        tree = json.loads(fetch(f"https://api.github.com/repos/{repo}/git/trees/{sha}"))
        result["root_entries"] = [entry["path"] for entry in tree["tree"]]
        result["license_files"] = []
        for entry in tree["tree"]:
            name = entry["path"]
            if entry["type"] != "blob" or not name.upper().startswith(("LICENSE", "LICENCE", "NOTICE", "COPYING")):
                continue
            url = f"https://raw.githubusercontent.com/{repo}/{sha}/{name}"
            data = fetch(url)
            result["license_files"].append(dict(url=url, **save_text(folder, name, data)))
        result["status"] = "FETCHED"
    except Exception as exc:
        result.update(status="BLOCKED", error=f"{type(exc).__name__}: {exc}")
    (folder / "metadata.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def model(repo):
    folder = OUT / repo.replace("/", "__")
    folder.mkdir(parents=True, exist_ok=True)
    if (folder / "metadata.json").exists():
        return json.loads((folder / "metadata.json").read_text(encoding="utf-8"))
    result = {"kind": "model", "repository": repo, "observed_at_utc": datetime.now(timezone.utc).isoformat(),
              "weights_downloaded": False, "inference_tested": False}
    try:
        info = json.loads(fetch(f"https://huggingface.co/api/models/{repo}"))
        sha = info["sha"]
        result.update(revision=sha, card_license=info.get("cardData", {}).get("license"),
                      card_license_link=info.get("cardData", {}).get("license_link"),
                      gated=info.get("gated"), files=[])
        names = [s["rfilename"] for s in info.get("siblings", [])]
        result["repository_files"] = names
        for name in names:
            if name != "README.md" and not name.upper().startswith(("LICENSE", "NOTICE", "COPYING")):
                continue
            url = f"https://huggingface.co/{repo}/resolve/{sha}/{name}"
            result["files"].append(dict(url=url, **save_text(folder, name.replace("/", "__"), fetch(url))))
        result["status"] = "FETCHED"
    except Exception as exc:
        result.update(status="BLOCKED", error=f"{type(exc).__name__}: {exc}")
    (folder / "metadata.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(repository, REPOS)) + list(pool.map(model, MODELS))
    (OUT / "index.json").write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for row in results:
        print(row["repository"], row.get("revision", "UNKNOWN"), row["status"], row.get("card_license", ""), row.get("error", ""))
