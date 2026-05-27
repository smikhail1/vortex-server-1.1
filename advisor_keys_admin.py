import json
import sys
from pathlib import Path

BINDINGS = Path("_runtime/advisor_device_bindings.json")
KEYS = Path("_runtime/advisor_access_keys.json")


def load_json(path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def key_label_map():
    data = load_json(KEYS, {"keys": []})
    out = {}
    for item in data.get("keys") or []:
        if isinstance(item, dict):
            out[item.get("key")] = item.get("label")
    return out


def cmd_list():
    labels = key_label_map()
    data = load_json(BINDINGS, {"bindings": {}})
    bindings = data.get("bindings") or {}
    if not bindings:
        print("no bindings")
        return

    for key, b in bindings.items():
        print()
        print("label:", b.get("key_label") or labels.get(key))
        print("key:", key)
        print("fingerprint:", b.get("fingerprint"))
        print("first_seen:", b.get("first_seen"))
        print("last_seen:", b.get("last_seen"))
        print("last_screen:", b.get("last_screen"))
        print("last_payload:", b.get("last_payload"))


def cmd_reset(label_or_key):
    data = load_json(BINDINGS, {"bindings": {}})
    bindings = data.get("bindings") or {}
    labels = key_label_map()

    target_key = None
    for key, label in labels.items():
        if key == label_or_key or label == label_or_key:
            target_key = key
            break

    if target_key is None and label_or_key in bindings:
        target_key = label_or_key

    if not target_key:
        print("not found:", label_or_key)
        raise SystemExit(1)

    if target_key in bindings:
        bindings.pop(target_key)
        data["bindings"] = bindings
        save_json(BINDINGS, data)
        print("reset binding:", labels.get(target_key), target_key)
    else:
        print("binding not present:", labels.get(target_key), target_key)


def main():
    if len(sys.argv) < 2:
        print("usage:")
        print("  python3 advisor_keys_admin.py list")
        print("  python3 advisor_keys_admin.py reset 'Device 01'")
        raise SystemExit(1)

    if sys.argv[1] == "list":
        cmd_list()
    elif sys.argv[1] == "reset":
        if len(sys.argv) < 3:
            print("missing label/key")
            raise SystemExit(1)
        cmd_reset(sys.argv[2])
    else:
        print("unknown command:", sys.argv[1])
        raise SystemExit(1)


if __name__ == "__main__":
    main()
