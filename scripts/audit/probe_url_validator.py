"""Exercise only the reviewed pure URL-validator function with local synthetic strings."""
import ast
import argparse
import json
from pathlib import Path
import sys
from urllib.parse import urlparse

root = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--output", default=str(root / "evidence/A00/url-validator.json"))
args = parser.parse_args()
source = root / ".audit-cache/parse_video/backend/app/api/router/videos.py"
tree = ast.parse(source.read_text(encoding="utf-8"))
domains = next(n.value for n in tree.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "ALLOWED_DOUYIN_DOMAINS" for t in n.targets))
cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "DouyinRequest")
function = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "validate_douyin_url")
function.decorator_list = []
module = ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[]))
namespace = {"urlparse": urlparse, "ALLOWED_DOUYIN_DOMAINS": ast.literal_eval(domains)}
exec(compile(module, str(source), "exec"), namespace)
cases = [
    ("valid-platform-url", "https://www.douyin.com/video/123", True),
    ("reject-loopback-literal", "http://127.0.0.1/video", False),
    ("reject-file-scheme", "file:///etc/passwd", False),
    ("reject-suffix-confusion", "https://evildouyin.com/video/123", False),
    ("reject-unexpected-port", "https://www.douyin.com:8443/video/123", False),
    ("reject-userinfo", "https://synthetic:synthetic@www.douyin.com/video/123", False),
    ("extract-share-text-before-validation", "分享视频 https://v.douyin.com/example/ 复制打开", True),
]
results = []
for name, url, expected in cases:
    try:
        namespace["validate_douyin_url"](None, url)
        accepted = True
    except ValueError:
        accepted = False
    results.append(dict(case=name, expected_accept=expected, actual_accept=accepted, status="PASS" if accepted == expected else "FAIL"))
report = dict(scope="Reviewed AST function only; no HTTP, DNS, database, model, or API integration", results=results,
              passed=sum(r["status"] == "PASS" for r in results), failed=sum(r["status"] == "FAIL" for r in results), skipped=0)
output = Path(args.output)
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
print(json.dumps(report, indent=2))
sys.exit(1 if report["failed"] else 0)
