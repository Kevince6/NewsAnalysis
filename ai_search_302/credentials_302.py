"""只在进程内读取302密钥；不执行.env内容，不输出密钥。"""

import os
from pathlib import Path


def load_api_key(path=None):
    value = os.environ.get("AI302_API_KEY", "").strip()
    if value:
        return value
    path = Path(path) if path else Path(__file__).resolve().parent / ".env"
    if not path.is_file():
        return ""
    lines = [
        line.strip() for line in path.read_text(encoding="utf-8-sig").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    names = {"AI302_API_KEY", "API302_API_KEY", "API_302_KEY", "AI_302_API_KEY", "API_KEY", "302_API_KEY"}
    for line in lines:
        name, sep, value = line.removeprefix("export ").partition("=")
        if sep and name.strip() in names:
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                value = value[1:-1]
            elif " #" in value:
                value = value.split(" #", 1)[0].rstrip()
            return value
    if len(lines) == 1 and not any(char.isspace() for char in lines[0]):
        return lines[0].strip("'\"")
    raise ValueError(".env格式无法识别，请使用AI302_API_KEY=密钥；也支持单独一行密钥。")
