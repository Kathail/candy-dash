import re
from pathlib import Path

from app import create_app

app = create_app()
valid_endpoints = {rule.endpoint for rule in app.url_map.iter_rules()}

pattern = re.compile(r"url_for\(\s*['\"]([^'\"]+)['\"]")

broken = []

for path in Path("templates").rglob("*.html"):
    text = path.read_text(encoding="utf-8")
    for endpoint in pattern.findall(text):
        if endpoint not in valid_endpoints:
            broken.append((path, endpoint))

if not broken:
    print("✅ All templates use valid blueprint endpoints")
else:
    print("❌ Invalid endpoint references found:\n")
    for path, ep in broken:
        print(f"{path}: url_for('{ep}')")
