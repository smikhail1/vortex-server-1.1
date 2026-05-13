import json
import os

file_path = 'position_state_engine.py'
with open(file_path, 'r') as f:
    lines = f.readlines()

new_lines = []
for line in lines:
    new_lines.append(line)
    # Вставляем методы после __init__
    if 'self._closed = []' in line:
        indent = "        "
        new_lines.append(f"\n{indent}self._storage_file = 'trades_state.json'\n")
        new_lines.append(f"{indent}self._load_from_disk()\n")

# Добавляем сами методы в конец класса (перед следующим методом или в конец)
methods = """
    def _save_to_disk(self):
        try:
            data = {
                "open": {k: asdict(v) for k, v in self._open.items()},
                "closed": [asdict(v) for v in self._closed[-self.max_closed:]]
            }
            with open(self._storage_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            if self.logger: self.logger.error("STATE_ENGINE", "Save failed", {"err": str(e)})

    def _load_from_disk(self):
        if not os.path.exists(self._storage_file): return
        try:
            with open(self._storage_file, 'r') as f:
                data = json.load(f)
            for k, v in data.get("open", {}).items():
                # Восстанавливаем объекты PositionState из словарей
                events = [PositionEvent(**ev) for ev in v.pop('events', [])]
                self._open[k] = PositionState(**v, events=events)
            if self.logger: self.logger.info("STATE_ENGINE", "State restored from disk", {"open": len(self._open)})
        except Exception as e:
            if self.logger: self.logger.error("STATE_ENGINE", "Load failed", {"err": str(e)})
"""

# Вставим вызов сохранения в методы open/update/close
final_code = "".join(new_lines)
final_code = final_code.replace('self._open[key] = state', 'self._open[key] = state\\n        self._save_to_disk()')
final_code = final_code.replace('state.state = "CLOSED"', 'state.state = "CLOSED"\\n        self._save_to_disk()')

with open(file_path, 'w') as f:
    f.write(final_code)
    # Дописываем методы в конец класса (упрощенно для патча)
    f.write(methods)
