import re
from pathlib import Path


def tokenize(text):
    words = re.findall(r"[a-zA-Z0-9_]+", str(text).lower())
    grams = []
    for run in re.findall(r"[\u4e00-\u9fff]+", str(text)):
        if len(run) == 1:
            grams.append(run)
        else:
            grams.extend(run[i:i + 2] for i in range(len(run) - 1))
    return words + grams


def estimate_tokens(text):
    return max(1, (len(str(text)) + 2) // 3)


def truncate(text, limit):
    text = str(text)
    return text if len(text) <= limit else text[:limit] + "…"


def safe_name(name):
    cleaned = re.sub(r"[^\w-]", "_", str(name), flags=re.UNICODE).strip("_")
    return cleaned or "default"


def path_within(root, *segments):
    joined = "/".join(str(part) for part in (root, *segments))
    if ".." in joined or "~" in joined or "\\" in joined:
        raise ValueError("路径不合法")
    base = Path(str(root)).resolve()
    target = base.joinpath(*[str(part) for part in segments]).resolve()
    if not target.is_relative_to(base):
        raise ValueError("文件路径越界")
    return target
