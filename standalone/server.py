#!/usr/bin/env python3
"""Local StudentAge Studio backend for installed game and mod files."""
from __future__ import annotations
from storage_paths import game_cache, auxiliary_cache

import argparse
import base64
import copy
import hashlib
import hmac
import io
import json
import mimetypes
import math
import os
import re
import secrets
import shutil
import socket
import struct
import subprocess
import sys
import threading
import tempfile
import time
import urllib.parse
import warnings
from dataclasses import dataclass
from contextlib import nullcontext, contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# The macOS app bundle is signed. Keep Python and its asset workers from
# creating bytecode files inside the installed resources while they run.
sys.dont_write_bytecode = True
os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
sys.path.insert(0, str(Path(__file__).resolve().parent))
import save_review
import gameplay_features
import original_mode
from portraits import normalize_portrait, expression_status, native_cache_faces
from platform_support import lock_file as lock_file_acquire, unlock_file, worker_command, process_options, reveal_file, replace_file, file_fingerprint
from game_locator import GameLocations, settings_path, local_mod_candidates, preferred_mods_path, is_workshop_path
from error_logs import ErrorLogs
from startup import StartupPreparation
from media_warmup import MediaWarmup
from asset_labels import asset_name
from record_ids import RecordIds
from asset_catalog import AssetCatalog
from social import SocialEditor
from space import SpaceEditor
from backups import ModBackups
from mod_copy import excluded_entry, stable_copy
from condition_library import ConditionLibrary, UserConditionPresets, named_entries

try:
    from PIL import Image, UnidentifiedImageError
except ImportError:
    Image = None

TABLES = {
    "talks": "TalkCfg.json", "events": "EvtCfg.json", "options": "OptionCfg.json",
    "persons": "PersonCfg.json", "faces": "ModFaceCfg.json", "backgrounds": "BgCfg.json", "cgs": "CGCfg.json", "papers": "PaperCfg.json",
    "actions": "ActionCfg.json", "actionEvents": "ActionEvtCfg.json", "interactions": "InteractCfg.json", "giftEvents": "GiftEvtCfg.json", "minigameActions": "MinigameActionCfg.json",
}
TALK_FIELDS = {"nextTalk", "nextTalk2", "talkId", "talkId2", "startTalks", "finishTalk", "failTalk", "startTalk", "winTalk", "loseTalk", "talk"}
MAX_JSON = 96 * 1024 * 1024
MAX_IMAGE = 24 * 1024 * 1024
MAX_PIXELS = 16 * 1024 * 1024
MAX_DIMENSION = 4096
DRIVE = Path.home() / "Library/Application Support/CrossOver/Bottles/Steam/drive_c"
DEFAULT_MODS = DRIVE / "users/crossover/AppData/LocalLow/PakyiGame/StudentAge/Mods"
DEFAULT_WORKSHOP = DRIVE / "Program Files (x86)/Steam/steamapps/workshop/content/1991040"
DEFAULT_GAME = DRIVE / "Program Files (x86)/Steam/steamapps/common/StudentAge"
if os.name == "nt":
    DEFAULT_MODS = preferred_mods_path(local_mod_candidates())
    DEFAULT_GAME = Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)")) / "Steam/steamapps/common/StudentAge"
    DEFAULT_WORKSHOP = DEFAULT_GAME.parent.parent / "workshop/content/1991040"


class ApiError(Exception):
    def __init__(self, message, status=400, code="invalid_request"):
        super().__init__(message)
        self.message, self.status, self.code = message, status, code


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def compatible_json(text):
    """Match the game's Newtonsoft comment/trailing-comma syntax without touching strings."""
    strings = r'"(?:\\.|[^"\\])*"'
    text = re.sub(strings + r'|//[^\r\n]*|/\*[\s\S]*?\*/',
                  lambda match: match[0] if match[0].startswith('"') else re.sub(r'[^\r\n]', ' ', match[0]), text)
    return re.sub(strings + r'|,(?=\s*[}\]])', lambda match: match[0] if match[0].startswith('"') else ' ', text)


def load_compatible_json(text):
    """Recover only missing separators before an explicit field on a new line."""
    text = compatible_json(text)
    field = re.compile(r'"(?:\\.|[^"\\])*"[ \t\r\n]*:')
    # Re-decoding establishes that the preceding value is complete. Bound the
    # retries and total input scanned so a damaged large file cannot loop forever.
    budget = max(1, min(64, 4 * MAX_JSON // max(1, len(text))))
    for attempt in range(budget + 1):
        try:
            return json.loads(text, strict=False, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
        except json.JSONDecodeError as error:
            if attempt == budget or error.msg != "Expecting ',' delimiter" or not field.match(text, error.pos):
                raise
            start = error.pos
            while start and text[start - 1] in ' \t\r\n':
                start -= 1
            if not any(c in '\r\n' for c in text[start:error.pos]):
                raise
            # Insert outside strings, before whitespace; original line numbers
            # and the next field's column remain intact for any later error.
            text = text[:start] + ',' + text[start:]


JSON_MESSAGES = [
    ("Expecting ',' delimiter", "缺少逗号「,」：上一项结尾没有用逗号隔开"),
    ("Expecting ':' delimiter", "缺少冒号「:」：字段名后面应该是冒号"),
    ("Expecting property name enclosed in double quotes", "这里应该是带双引号的字段名（可能多写了一个逗号，或少了字段）"),
    ("Expecting value", "这里缺少一个值（可能多写了逗号，或值没有填）"),
    ("Unterminated string starting at", "字符串没有结束的双引号"),
    ("Extra data", "文件结尾之后还有多余内容（例如多了一个大括号或第二份数据）"),
    ("Invalid control character at", "字符串里有不能直接出现的换行或控制字符"),
    ("Invalid \\escape", "反斜杠转义写法不正确"),
    ("Invalid \\uXXXX escape", "\\u 转义后面必须是 4 位十六进制"),
]


def _json_line_col(text, pos):
    line = text.count("\n", 0, pos) + 1
    col = pos - (text.rfind("\n", 0, pos) + 1) + 1
    return line, col


def analyze_json_text(text, repair=False, max_fixes=64):
    """Locate syntax errors in the user's own text and optionally repair the safe ones.

    Comments and trailing commas are accepted like the game's Json.NET reader.
    Positions always refer to the text as the user sees it: the tolerant copy keeps
    every character position, and the repair inserts commas without moving lines.
    Only a missing separator before a field name, or before an object/array that
    starts on its own line, is repaired; nothing is guessed for other errors.
    """
    text = str(text or "")
    if text.startswith("\ufeff"):
        text = text[1:]
    work = compatible_json(text)
    field = re.compile(r'"(?:\\.|[^"\\])*"[ \t\r\n]*:')
    errors, fixes, inserts = [], [], []
    budget = max_fixes if repair else 0
    decoder = lambda value: json.loads(value, strict=False, parse_constant=lambda v: (_ for _ in ()).throw(ValueError(v)))
    for attempt in range(budget + 1):
        try:
            decoder(work)
            valid = True
            break
        except json.JSONDecodeError as error:
            valid = False
            original_pos = error.pos - sum(1 for offset in inserts if offset < error.pos)
            line, col = _json_line_col(text, original_pos)
            message = next((zh for en, zh in JSON_MESSAGES if error.msg.startswith(en)), error.msg)
            entry = {"line": line, "col": col, "pos": original_pos, "message": message, "raw": error.msg, "fixLine": line, "fixCol": col}
            start = error.pos
            while start and work[start - 1] in " \t\r\n":
                start -= 1
            if error.msg == "Expecting ',' delimiter":
                fix_pos = start - sum(1 for offset in inserts if offset < start)
                entry["fixLine"], entry["fixCol"] = _json_line_col(text, fix_pos)
                newline = any(c in "\r\n" for c in work[start:error.pos])
                nxt = work[error.pos:error.pos + 1]
                if newline and (field.match(work, error.pos) or nxt in "{["):
                    entry["fixable"] = True
                    if attempt < budget:
                        work = work[:start] + "," + work[start:]
                        inserts.append(start)
                        fixes.append({"line": entry["fixLine"], "col": entry["fixCol"], "kind": "comma"})
                        continue
            errors.append(entry)
            break
        except (ValueError, RecursionError) as error:
            valid = False
            errors.append({"line": 1, "col": 1, "pos": 0, "message": "无法解析：" + str(error), "raw": str(error), "fixLine": 1, "fixCol": 1})
            break
    else:
        valid = False
    result = {"valid": valid, "errors": errors, "fixes": fixes}
    if repair:
        repaired = text
        for offset in sorted(inserts, reverse=True):
            original = offset - sum(1 for other in inserts if other < offset)
            repaired = repaired[:original] + "," + repaired[original:]
        result["text"] = repaired
    return result


def read_json(path, fallback=None):
    try:
        try: size = path.stat().st_size
        except FileNotFoundError: return copy.deepcopy(fallback)
        if size > MAX_JSON:
            raise ApiError("配置文件过大，无法安全打开：" + str(path), 413)
        # Json.NET-written mods may contain literal control characters inside dialogue strings.
        text = ''
        text = path.read_text(encoding="utf-8-sig")
        try:
            return json.loads(text, strict=False, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
        except json.JSONDecodeError:
            return load_compatible_json(text)
    except PermissionError:
        raise ApiError("无法读取配置，请检查此文件的访问权限：" + str(path), 403, "file_permission")
    except OSError:
        raise ApiError("无法读取配置，请检查文件是否仍存在或被其他程序占用：" + str(path), 422, "file_unavailable")
    except (UnicodeError, ValueError, RecursionError) as error:
        position = ''
        if isinstance(error, json.JSONDecodeError):
            position = '（第 ' + str(error.lineno) + ' 行，第 ' + str(error.colno) + ' 列）'
            try:
                # Report the first error that blocks reading, after the safe comma
                # repairs the tolerant loader would apply; mention repairable ones.
                analysis = analyze_json_text(text, repair=True)
                found = analysis.get('errors') or []
                if found:
                    first = found[0]
                    position = '（第 ' + str(first['line']) + ' 行，第 ' + str(first['col']) + ' 列：' + first['message'] + ('；应在第 ' + str(first['fixLine']) + ' 行，第 ' + str(first['fixCol']) + ' 列补上' if (first['fixLine'], first['fixCol']) != (first['line'], first['col']) else '') + ('；另有 ' + str(len(analysis.get('fixes') or [])) + ' 处缺少逗号可在「JSON 编码」窗口一键修复' if analysis.get('fixes') else '') + '）'
            except Exception:
                pass
        raise ApiError("配置文件不是有效 JSON，请先修复该文件：" + path.name + position, 422)


def inside(path, root):
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (ValueError, OSError, RuntimeError):
        return False


def safe_path(root, relative):
    relative = str(relative).replace("\\", "/")
    if not relative or relative.startswith("/") or ":" in relative or "\x00" in relative:
        raise ApiError("文件路径无效。")
    parts = Path(relative).parts
    if any(part in ("..", ".") for part in parts):
        raise ApiError("文件路径不能越过模组目录。")
    path = root.joinpath(*parts)
    if not inside(path, root):
        raise ApiError("文件路径不能越过模组目录。", 403)
    return path


def atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name("." + path.name + "." + secrets.token_hex(8) + ".tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        replace_file(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def valid_id(value):
    if isinstance(value, bool):
        return False
    if isinstance(value, str):
        return bool(re.fullmatch(r"[1-9][0-9]{0,9}", value)) and int(value) <= 2147483647
    return isinstance(value, int) and 0 < value <= 2147483647


def premise_command_pair(value, writer=False):
    if not isinstance(value, list) or len(value) < 5:
        return None
    try:
        code, mode, event, slot = (int(float(n)) for n in value[:4])
    except (ValueError, TypeError, OverflowError):
        return None
    if (code == 50 and mode in (2, 20)) or (not writer and code == 111):
        return event, slot
    return None


def premise_writers(value):
    pair = premise_command_pair(value, True)
    if pair is not None: return {pair}
    children = value.values() if isinstance(value, dict) else value if isinstance(value, list) else []
    result = set()
    for child in children: result.update(premise_writers(child))
    return result


def strip_premise_commands(value, pairs):
    if isinstance(value, dict):
        for key in value: value[key] = strip_premise_commands(value[key], pairs)
    elif isinstance(value, list):
        value[:] = [strip_premise_commands(child, pairs) for child in value if premise_command_pair(child) not in pairs]
    return value


def reconcile_premises(state, previous, maps, original):
    """Remove deleted named definitions and their commands in one transaction."""
    old = previous.get('premises', {})
    incoming = state.setdefault('premises', copy.deepcopy(old))
    if not isinstance(old, dict) or not isinstance(incoming, dict): raise ApiError('前提列表格式无效。')
    before, after = premise_writers(original), premise_writers(maps)
    deleted = {tuple(pair) for pair in previous.get('deletedPremisePairs', []) if isinstance(pair, list) and len(pair) == 2}
    for key, premise in list(incoming.items()):
        pair = (premise.get('eventId'), premise.get('slot'))
        removed_event = str(pair[0]) in original.get('EvtCfg.json', {}) and str(pair[0]) not in maps.get('EvtCfg.json', {})
        if removed_event or pair in before - after or (pair in deleted and pair not in after):
            incoming.pop(key)
            deleted.add(pair)
    for key, premise in old.items():
        if key not in incoming: deleted.add((premise.get('eventId'), premise.get('slot')))
    # Undo can explicitly restore a definition along with its writer.
    deleted -= {(p.get('eventId'), p.get('slot')) for p in incoming.values()}
    if deleted:
        strip_premise_commands(maps, deleted)
        strip_premise_commands(state, deleted)
    state['deletedPremisePairs'] = [list(pair) for pair in sorted(deleted)]
    return deleted


def premise_pairs(value):
    """Find native event-save storage addressed by effects or conditions."""
    result, stack = set(), [value]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            if "eventId" in node and "slot" in node:
                pair = (node["eventId"], node["slot"])
                if all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) and x == int(x) for x in pair):
                    result.add(tuple(int(x) for x in pair))
            stack.extend(node.values())
        elif isinstance(node, list):
            if len(node) >= 5 and all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) for x in node[:5]):
                try:
                    # Effects use float[]; conditions use double[]. Both consume a prefix.
                    native = [int(struct.unpack("f", struct.pack("f", x))[0]) for x in node[:4]]
                    if native[0] == 50 and native[1] in (2, 20):
                        result.add(tuple(native[2:4]))
                    if int(node[0]) == 111:
                        result.add((int(node[2]), int(node[3])))
                except (OverflowError, ValueError):
                    pass
                stack.extend(node[5:])
            else:
                stack.extend(node)
    return result


def validate_map(value, name, allow_zero=False):
    if not isinstance(value, dict) or len(value) > 250000:
        raise ApiError(name + " 必须是以编号为键的配置表。")
    for key, row in value.items():
        if (not valid_id(key) and not (allow_zero and key == "0")) or not isinstance(row, dict) or row.get("id") != int(key) or isinstance(row.get("id"), bool):
            raise ApiError(name + " 中的编号必须为正整数，并与行内 id 一致。")
    return value


def repair_map(value, name, allow_zero=False, warnings=None):
    """Saving is never refused over row numbering: keys and row ids are reconciled and reported."""
    if not isinstance(value, dict) or len(value) > 250000:
        raise ApiError(name + " 必须是以编号为键的配置表。")
    result, notes = {}, []
    for key, row in value.items():
        if not isinstance(row, dict):
            result[key] = row; notes.append(str(key) + ' 不是记录'); continue
        key_ok = valid_id(key) or (allow_zero and key == "0")
        ident = row.get("id")
        if key_ok and not isinstance(ident, bool) and ident == int(key):
            result[key] = row; continue
        if valid_id(ident) and str(ident) not in value and str(ident) not in result:
            # The id typed inside the row wins: the row moves to that number.
            notes.append(str(key) + ' 的表键已按行内 id 改为 ' + str(ident)); key = str(ident)
        elif key_ok:
            row = {**row, "id": int(key)}; notes.append(str(key) + ' 的行内 id 已按表键改为 ' + str(key))
        else:
            notes.append(str(key) + ' 不是有效编号，已按原样保留')
        result[key] = row
    if notes and warnings is not None:
        warnings.append(name + ' 有 ' + str(len(notes)) + ' 处编号不一致，已自动修正：' + '；'.join(notes[:5]) + ('…' if len(notes) > 5 else ''))
    return result


def flat_deletions(value):
    """Accept legacy flat markers and native event-bucket markers without mistaking event IDs for talk IDs."""
    result = {}
    def visit(node):
        if not isinstance(node, dict):
            return
        for key, entry in node.items():
            if isinstance(entry, dict):
                visit(entry)
            elif valid_id(key) and isinstance(entry, list):
                if any(not valid_id(target) for target in entry):
                    raise ApiError("删除记录中存在无效跳转，请检查 deleted-talks.json。", 422)
                result[str(key)] = [int(target) for target in entry]
    visit(value)
    return result


def nested_deletions(flat):
    result = {}
    for key in sorted(flat, key=int):
        result.setdefault(str(int(key) // 1000), {})[str(key)] = list(flat[key])
    return result


def inert_talk(ident, targets):
    row = {field: [] for field in ("check", "effect", "effect2", "highlights", "miniGame", "nextTalk2", "option",
                                      "replace", "roleIds", "roles", "screenEffect", "vocals")}
    row.update({"id": int(ident), "content": "", "nextTalk": list(targets), "audio": 0, "bg": 0,
                "maxoptions": 0, "roleName": None, "showTxt": None, "time": 0})
    return row


def display_name(value, fallback="新建模组"):
    if not isinstance(value, str):
        return fallback
    result = "".join(character for character in value.strip() if ord(character) >= 32)
    return result[:100] or fallback


@dataclass(frozen=True)
class Project:
    id: str
    path: Path
    readonly: bool
    name: str
    package: str
    original_mode: bool = False

    def public(self):
        return {"id": self.id, "name": self.name, "path": str(self.path), "readOnly": self.readonly,
                "packageId": self.package, "source": "workshop" if self.readonly else "local", "originalMode": self.original_mode}


class StudioStore:
    def __init__(self, mods=DEFAULT_MODS, workshop=DEFAULT_WORKSHOP, game=DEFAULT_GAME, extra_mods=(), asset_settings_path=None, backup_root=None, migrate_cache=True):
        self.mods = Path(mods).expanduser().resolve()
        self.workshop = Path(workshop).expanduser().resolve()
        self.game = Path(game).expanduser().resolve()
        from storage_paths import prepare_game_cache
        if migrate_cache: prepare_game_cache(self.game)
        self.extra_mods = [Path(path).expanduser().resolve() for path in extra_mods if not is_workshop_path(path, self.workshop)]
        self.lock = threading.RLock()
        self.backups = ModBackups(self, sys.modules[__name__], backup_root)
        self.conditions = ConditionLibrary(self, sys.modules[__name__])
        self._catalog_stamp = None
        self._catalog_cache = {}
        # Startup preparation, location polling and asset requests may all ask for
        # the catalog at once; one load at a time keeps the memory peak single.
        self._catalog_lock = threading.RLock()
        self._read_context = threading.local()
        self._revision_cache = {}
        self.asset_catalog = AssetCatalog(self, sys.modules[__name__], asset_settings_path or os.environ.get('STUDIO_ASSET_FOLDER_SETTINGS'))
        self._orphan_cleanup_done = set()
        self._project_paths = {}
        self._project_metadata = {}
        self._project_index_path = auxiliary_cache(self.asset_catalog.settings_path.parent, 'AssetCache/project-paths-v1.json')
        self._project_index_roots = [str(self.mods), str(self.workshop), *map(str, self.extra_mods)]
        self._project_index_saved = None
        self._load_project_paths()
        self.social = SocialEditor(self, sys.modules[__name__])
        self.space = SpaceEditor(self, sys.modules[__name__])
        self.record_ids = RecordIds(self, sys.modules[__name__])

    def _project_root(self, path, readonly):
        if readonly:
            return self.workshop if path.parent == self.workshop else None
        if is_workshop_path(path, self.workshop): return None
        if path in self.extra_mods: return path
        return self.mods if path.parent == self.mods else None

    def _load_project_paths(self):
        # This is an optional, disposable index of paths and manifest metadata only.
        try:
            if self._project_index_path.stat().st_size > 8 * 1024 * 1024: return
            data = read_json(self._project_index_path, {})
            if data.get('version') != 1 or data.get('roots') != self._project_index_roots: return
            for row in data.get('entries', [])[:10000]:
                if not isinstance(row, dict) or not isinstance(row.get('path'), str) or type(row.get('readonly')) is not bool: continue
                path, readonly = Path(row['path']), row['readonly']
                if not path.is_absolute() or self._project_root(path, readonly) is None: continue
                if not isinstance(row.get('name'), str) or not isinstance(row.get('package'), str): continue
                ident = ('workshop:' if readonly else 'local:') + hashlib.sha256(str(path).encode()).hexdigest()[:24]
                self._project_paths[ident] = Project(ident, path, readonly, row['name'], row['package'])
                self._project_metadata[str(path)] = row
        except (OSError, ApiError, ValueError, TypeError, AttributeError):
            self._project_paths.clear(); self._project_metadata.clear()

    def _project_at(self, root, path, readonly):
        if root is None or self.backups.excluded(path): return None
        if not path.is_dir() or path.name.startswith('.') or path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction()) or not inside(path, root): return None
        manifest_path = path / 'manifest.json'
        if not manifest_path.is_file() and not (path / 'Cfgs/zh-cn').is_dir(): return None
        if not inside(manifest_path, path): return None
        try: version = list(file_fingerprint(manifest_path))
        except FileNotFoundError: version = None
        cached = self._project_metadata.get(str(path))
        if cached and cached.get('stamp') == version:
            name, package = cached['name'], cached['package']
        else:
            try: manifest = read_json(manifest_path, {})
            except (ApiError, OSError): manifest = {}
            if not isinstance(manifest, dict): manifest = {}
            metadata = manifest.get('metadata') or {}
            if not isinstance(metadata, dict): metadata = {}
            name, package = display_name(manifest.get('title'), path.name), str(metadata.get('packageId') or path.name)
            self._project_metadata[str(path)] = {'path': str(path), 'readonly': readonly, 'stamp': version, 'name': name, 'package': package}
        ident = ('workshop:' if readonly else 'local:') + hashlib.sha256(str(path).encode()).hexdigest()[:24]
        project = Project(ident, path, readonly, name, package)
        self._project_paths[ident] = project
        return project

    def projects(self):
        with self.lock:
            result, candidates = [], []
            if not is_workshop_path(self.mods, self.workshop):
                try: candidates.extend((self.mods, path, False) for path in sorted(self.mods.iterdir(), key=lambda p: p.name.casefold()))
                except OSError: pass
            candidates.extend((path, path, False) for path in self.extra_mods if not is_workshop_path(path, self.workshop))
            try: candidates.extend((self.workshop, path, True) for path in sorted(self.workshop.iterdir(), key=lambda p: p.name.casefold()))
            except OSError: pass
            seen = set()
            for root, path, readonly in candidates:
                identity = os.path.normcase(str(path))
                if identity in seen: continue
                seen.add(identity)
                try: project = self._project_at(root, path, readonly)
                except OSError: project = None
                if project: result.append(project)
            self._project_paths = {p.id: p for p in result}
            self._project_metadata = {str(p.path): self._project_metadata[str(p.path)] for p in result}
            data = {'version': 1, 'roots': self._project_index_roots, 'entries': list(self._project_metadata.values())[:10000]}
            encoded = json_bytes(data)
            digest = hashlib.sha256(encoded).hexdigest()
            if digest != self._project_index_saved:
                try:
                    atomic_write(self._project_index_path, encoded)
                    self._project_index_saved = digest
                except OSError: pass
            return result

    def project_list(self):
        return self.projects()

    def preserve_editing_rows(self, project, name, rows):
        return original_mode.preserve_rows(self, project, name, rows)

    def editing_rows(self, project, name):
        import original_mode
        rows = read_json(safe_path(project.path, 'Cfgs/zh-cn/'+name+'.json'), {})
        if project.original_mode: validate_map(rows, name, allow_zero=True)
        return original_mode.visible_rows(self, project, name, rows)

    def project(self, project_id, writable=False):
        if not isinstance(project_id, str) or not project_id.startswith(('local:', 'workshop:')):
            raise ApiError('模组编号无效，请刷新列表。', 404, 'not_found')
        with self.lock:
            known = self._project_paths.get(project_id)
            if known:
                try: project = self._project_at(self._project_root(known.path, known.readonly), known.path, known.readonly)
                except OSError: project = None
                if project is None:
                    self._project_paths.pop(project_id, None)
                    self._project_metadata.pop(str(known.path), None)
            else: project = next((p for p in self.projects() if p.id == project_id), None)
            if project:
                if writable and project.readonly:
                    raise ApiError('订阅模组只能浏览；请复制为本地副本后编辑。', 403, 'read_only')
                return original_mode.view_project(project)
        raise ApiError('找不到这个模组，请刷新列表或检查游戏目录。', 404, 'not_found')

    def cfg_files(self, project):
        folder = safe_path(project.path, "Cfgs/zh-cn")
        if not folder.exists():
            return {}
        result = {}
        for path in sorted(folder.glob("*.json")):
            if path.is_symlink() or not inside(path, project.path):
                raise ApiError("配置中存在越界文件链接，请先移除。", 403)
            result[path.name] = path
        return result

    def cfg_table_files(self, project):
        # Field-label dictionaries are auxiliary documents, not numbered game rows.
        # Keep them in cfg_files for revision checks, raw JSON access and copying.
        # Do not infer this exemption from invalid contents: damaged Cfg tables
        # must still block destructive reference rewrites.
        auxiliary = {'customkeymap.json'}
        return {name: path for name, path in self.cfg_files(project).items()
                if name.casefold() not in auxiliary}

    def readable_maps(self, project):
        maps, failures = {}, {}
        for name, path in self.cfg_table_files(project).items():
            try:
                rows = read_json(path, {})
                normalized = copy.deepcopy(rows)
                if isinstance(normalized, dict):
                    for key, row in normalized.items():
                        if valid_id(key) and isinstance(row, dict): row["id"] = int(key)
                validate_map(normalized, name, allow_zero=True)
                maps[name] = rows
            except ApiError as error: failures[name] = error
        return maps, failures

    @contextmanager
    def catalog_scope(self):
        """Share one original catalogue within a read operation; revisions stay live."""
        if hasattr(self._read_context, 'catalog'):
            yield
            return
        self._read_context.catalog = self.catalog()
        try:
            yield
        finally:
            del self._read_context.catalog

    def catalog_paths(self):
        root = game_cache(self.game)
        return root, [root / "game-catalog.json", root / "asset-map.json", root / "audio-map.json"]

    def catalog_stamp(self):
        root, paths = self.catalog_paths()
        return tuple((str(path), path.stat().st_mtime_ns, path.stat().st_size) for path in paths
                     if path.is_file() and inside(path, root))

    def catalog_prepared(self):
        """Whether the original game tables were extracted, without loading the catalog.

        extract_catalog writes game-catalog.json atomically from catalog-schema.json,
        so the file's presence answers the same question as catalog()['schemas'].
        """
        if self._catalog_stamp is not None and self.catalog_stamp() == self._catalog_stamp:
            return bool(self._catalog_cache.get('schemas'))
        root, paths = self.catalog_paths()
        try:
            return paths[0].is_file() and inside(paths[0], root) and paths[0].stat().st_size > 0
        except OSError:
            return False

    def catalog(self):
        if hasattr(self._read_context, 'catalog'):
            return self._read_context.catalog
        with self._catalog_lock:
            return self._load_catalog()

    def _load_catalog(self):
        root, paths = self.catalog_paths()
        stamp = self.catalog_stamp()
        if stamp == self._catalog_stamp:
            return self._catalog_cache
        # Release the previous copy before parsing the new one.
        self._catalog_stamp, self._catalog_cache = None, {}
        merged = {}
        deferred_maps = []
        for path in paths:
            if not path.is_file() or not inside(path, root):
                continue
            # Read the canonical table catalog first. Asset and audio maps are
            # independent lazy groups; opening event text does not parse either.
            def read_generated(path=path):
                from catalog_reader import read_catalog
                try:
                    data = read_catalog(path)
                except (OSError, ValueError, UnicodeError, RecursionError):
                    return {}
                return data if isinstance(data, dict) else {}
            if path.name in ('asset-map.json', 'audio-map.json'):
                names = ('assetMap', 'bundles', 'failures') if path.name == 'asset-map.json' else ('audioMap', 'audioMetadata', 'audioBundles', 'audioFailures')
                expected = (path.stat().st_mtime_ns, path.stat().st_size)
                def deferred(path=path, names=names, expected=expected, read_generated=read_generated):
                    if (path.stat().st_mtime_ns, path.stat().st_size) != expected:
                        raise ApiError('素材索引已更新，请重试读取；当前草稿不受影响。', 409, 'conflict')
                    data = read_generated()
                    return {key: data[key] for key in names if key in data}
                deferred_maps.append((names, deferred))
                continue
            data = read_generated()
            for key, value in data.items():
                if isinstance(value, dict) and isinstance(merged.get(key), dict):
                    merged[key].update(value)
                elif key == 'baseTalkIds' and isinstance(value, list):
                    merged[key] = list(dict.fromkeys((merged.get(key) or []) + value))
                else:
                    merged[key] = value
        if "PaperCfg" not in merged.get("tables", {}):
            from paper_ui import base_papers
            merged.setdefault("tables", {})["PaperCfg"] = base_papers(self.game)
        if 'GiftEvtCfg' not in merged.get('tables', {}):
            from paper_ui import base_papers
            merged.setdefault('tables', {})['GiftEvtCfg'] = base_papers(self.game, 'GiftEvtCfg')
        # The compact story endpoint keeps local dialogue/event scope. Generic table endpoints expose all base rows.
        for name in ("persons", "faces", "backgrounds", "cgs", "papers", "giftEvents"):
            if name not in merged and isinstance(merged.get("tables"), dict):
                merged[name] = merged["tables"].get(TABLES[name][:-5], {})
        from catalog_reader import DeferredCatalog
        result = DeferredCatalog(merged, deferred_maps, self._catalog_lock)
        self._catalog_stamp, self._catalog_cache = stamp, result
        return result

    def catalog_rows(self, table, catalog=None):
        catalog = self.catalog() if catalog is None else catalog
        tables = catalog.get("tables", {})
        if isinstance(tables, dict):
            rows = tables.get(table, tables.get(table + ".json"))
            if isinstance(rows, dict):
                return rows
        if table in (*gameplay_features.NAMES, *gameplay_features.LOOKUPS):
            return gameplay_features.original_rows(self.game, table)
        alias = next((key for key, filename in TABLES.items() if filename == table + ".json"), None)
        rows = catalog.get(alias, {}) if alias else {}
        return rows if isinstance(rows, dict) else {}

    def api_romance(self, project):
        data = read_json(safe_path(project.path,'StudentAgeStudio/character-romance.json'), {})
        if not isinstance(data, dict): raise ApiError('恋爱配置文件格式无效，原文件已保留。')
        return data

    def revision(self, project):
        # Keep the byte-identical revision contract while avoiding repeated reads
        # of the multi-megabyte original catalogue for every image in a picker.
        with self.lock:
            paths = [path for relative,path in self.json_document_files(project).items() if relative != 'manifest.json']
            paths += [project.path / "manifest.json", project.path / "StudentAgeStudio/deleted-talks.json",
                      project.path / "StudentAgeStudio/editor-state.json", project.path / "StudentAgeStudio/audio-cues.json",
                      project.path / "StudentAgeStudio/original-edits.json", project.path / "StudentAgeStudio/social-state.json", project.path / "StudentAgeStudio/character-outfits.json", project.path / "StudentAgeStudio/character-romance.json", project.path / "StudentAgeStudio/space-layouts.json"]
            catalog_path = game_cache(self.game) / 'game-catalog.json'
            def fingerprint(path):
                try:
                    return file_fingerprint(path)
                except FileNotFoundError:
                    return None
            fingerprints = tuple((str(path), fingerprint(path)) for path in [*paths, catalog_path])
            key = str(project.path)
            cached = self._revision_cache.get(key)
            if cached and cached[0] == fingerprints:
                return cached[1]
            digest = hashlib.sha256()
            for path in paths:
                digest.update(str(path.relative_to(project.path)).encode())
                if path.exists():
                    if not inside(path, project.path) or path.stat().st_size > MAX_JSON:
                        raise ApiError("配置文件过大或路径无效。", 413)
                    with path.open('rb') as stream:
                        for block in iter(lambda: stream.read(1024 * 1024), b''):
                            digest.update(block)
                else:
                    digest.update(b"<missing>")
            if catalog_path.is_file() and inside(catalog_path, game_cache(self.game)) and catalog_path.stat().st_size <= MAX_JSON:
                digest.update(b"game-catalog.json")
                with catalog_path.open('rb') as stream:
                    for block in iter(lambda: stream.read(1024 * 1024), b''):
                        digest.update(block)
            revision = digest.hexdigest()
            if tuple((str(path), fingerprint(path)) for path in [*paths, catalog_path]) == fingerprints:
                if key not in self._revision_cache and len(self._revision_cache) >= 64:
                    self._revision_cache.pop(next(iter(self._revision_cache)))
                self._revision_cache[key] = (fingerprints, revision)
            return revision

    def load(self, project_id):
        with self.lock:
            project = self.project(project_id)
            revision = self.revision(project)
            catalog = self.catalog()
            result = {"project": project.public(), "revision": revision, "localIds": {},
                      "catalogAvailable": bool(catalog), "warnings": [], "unreadableTables": {}}
            for name, filename in TABLES.items():
                try:
                    local = read_json(safe_path(project.path, "Cfgs/zh-cn/" + filename), {})
                    # Key/id mismatches are normalized below as before.
                    validate_map({k: {**v, 'id': int(k)} if valid_id(k) and isinstance(v, dict) else v
                                  for k, v in local.items()} if isinstance(local, dict) else local,
                                 filename, allow_zero=True)
                except ApiError as error:
                    if error.status not in (400, 422) or error.code != 'invalid_request': raise
                    local = {}
                    result['unreadableTables'][name] = error.message
                    result['warnings'].append(error.message + '。已保留原文件并跳过该表；其他正常内容仍可编辑。')
                if isinstance(local, dict):
                    mismatches = 0
                    for key, row in local.items():
                        if valid_id(key) and isinstance(row, dict) and row.get("id") != int(key):
                            row["id"] = int(key)
                            mismatches += 1
                    if mismatches:
                        result["warnings"].append(filename + " 有 " + str(mismatches) + " 处行编号不一致，已在编辑副本中按表键修复；保存时会备份原文件。")
                validate_map(local, filename, allow_zero=True)
                inherited = self.catalog_rows(filename[:-5], catalog) if project.original_mode else catalog.get(name, {})
                if not isinstance(inherited, dict):
                    inherited = {}
                merged = copy.deepcopy(inherited)
                merged.update(local)
                if project.original_mode: merged = original_mode.visible_rows(self, project, filename[:-5], local)
                result[name] = merged
                result["localIds"][name] = list(merged) if project.original_mode else list(local)
                result.setdefault("catalogIds", {})[name] = list(inherited)
            deleted = flat_deletions(read_json(safe_path(project.path, "StudentAgeStudio/deleted-talks.json"), {}))
            result["deletedIds"] = [int(key) for key in deleted]
            result["replacements"] = deleted
            for key in deleted:
                result["talks"].pop(key, None)
            editor_state = read_json(safe_path(project.path, "StudentAgeStudio/editor-state.json"), {})
            order = editor_state.get("order", []) if isinstance(editor_state, dict) else []
            result["order"] = [int(ident) for ident in order if valid_id(ident) and str(ident) in result["talks"]]
            folders = editor_state.get("branchFolders", {}) if isinstance(editor_state, dict) else {}
            if not isinstance(folders, dict):
                raise ApiError("对话夹记录格式无效，请先恢复编辑记录备份。")
            result["protagonistGender"] = 2 if isinstance(editor_state,dict) and editor_state.get("protagonistGender")==2 else 1
            grades=editor_state.get("eventGrades", {}) if isinstance(editor_state,dict) else {}
            result["eventGrades"]={str(k):v for k,v in grades.items() if type(v) is int and v in (0,1)} if isinstance(grades,dict) else {}
            result["branchFolders"] = copy.deepcopy(folders)
            from event_ownership import ownership
            previous_owners = editor_state.get('talkOwners', {})
            self.validate_talk_owners(previous_owners)
            result['talkOwners'] = ownership(result.get('events', {}), result.get('talks', {}), result.get('options', {}), folders, previous_owners)
            premises = editor_state.get("premises", {}) if isinstance(editor_state, dict) else {}
            if not isinstance(premises, dict):
                raise ApiError("剧情前提记录格式无效，请先恢复编辑记录备份。")
            result["premises"] = copy.deepcopy(premises)
            result["pinnedIds"] = self.clean_pinned(editor_state.get("pinnedIds") if isinstance(editor_state, dict) else None)
            result["goalImageIds"] = list(read_json(project.path/"StudentAgeStudio/goal-images.json", {}))
            result["characterOutfits"] = read_json(safe_path(project.path, "StudentAgeStudio/character-outfits.json"), {})
            result["audioCues"] = self.audio_cues(project, result["talks"])
            if revision != self.revision(project):
                raise ApiError("读取时模组发生了变化，请重新打开。", 409, "conflict")
            return result

    def other_premise_pairs(self, project):
        pairs = set()
        for other in self.projects():
            if other.id == project.id:
                continue
            try:
                state = read_json(safe_path(other.path, "StudentAgeStudio/editor-state.json"), {})
                pairs.update(premise_pairs(state.get("premises", {}) if isinstance(state, dict) else {}))
            except ApiError:
                pass
            try:
                files = self.cfg_table_files(other)
            except ApiError:
                continue
            for path in files.values():
                try:
                    pairs.update(premise_pairs(read_json(path, {})))
                except ApiError:
                    # Skip only the broken source; later valid tables still reserve their slots.
                    continue
        return pairs

    def normalize_premises(self, incoming, previous, all_maps, original_maps, catalog, project):
        if not isinstance(incoming, dict) or not isinstance(previous, dict) or len(incoming) > 20000:
            raise ApiError("剧情前提必须是有效的完整列表。")
        events = {**self.catalog_rows("EvtCfg", catalog), **all_maps.get("EvtCfg.json", {})}
        # Existing slots cannot move. Only newly allocated slots can collide
        # with other mods; normal text edits do not need to read every mod.
        occupied = (premise_pairs(original_maps) | premise_pairs(catalog) | self.other_premise_pairs(project)) if incoming.keys() - previous.keys() else set()
        names, pairs, result = set(), set(), {}
        for key, item in incoming.items():
            if not valid_id(key) or not isinstance(item, dict) or not valid_id(item.get("id")) or item.get("id") != int(key):
                raise ApiError("剧情前提的记录编号不一致。")
            old = previous.get(key, {})
            if not isinstance(old, dict):
                raise ApiError("已有剧情前提记录格式无效，请先恢复编辑记录备份。")
            row = {**copy.deepcopy(old), **copy.deepcopy(item)}
            talk = row.get("talkId")
            if talk is not None and (isinstance(talk, bool) or not isinstance(talk, int) or not valid_id(talk)):
                raise ApiError("剧情前提绑定的对话编号无效，请重新添加前提。")
            event, slot = row.get("eventId"), row.get("slot")
            if talk is not None:
                # A "talk reached" premise is pure editor data: eventId/slot are only a legacy identity, never storage.
                if not isinstance(event, int) or isinstance(event, bool) or event < 0: row["eventId"] = event = 0
                if not isinstance(slot, int) or isinstance(slot, bool) or slot < 0: row["slot"] = slot = int(key)
                pair = (event, slot)
            else:
                if not isinstance(event, int) or not valid_id(event) or event > 16777215 or not isinstance(slot, int) or isinstance(slot, bool) or not 0 <= slot <= 16777215:
                    raise ApiError("剧情前提的存储位置无效，请重新添加前提。")
                if str(event) not in events:
                    raise ApiError("剧情前提所属的剧情已不存在，请保留该剧情或先移除前提引用。")
                pair = (event, slot)
                if old and pair != (old.get("eventId"), old.get("slot")):
                    raise ApiError("已有前提只能修改名称，不能更换存储位置。")
                if pair in pairs or (not old and pair in occupied):
                    raise ApiError("前提存储位置已经被使用，请重新添加前提。", 409, "premise_conflict")
            name = row.get("name", "")
            if not isinstance(name, str) or len(name.strip()) > 120 or any(ord(c) < 32 for c in name):
                raise ApiError("前提名称最多 120 个字，不能包含换行。")
            name = name.strip() or "前提" + key
            if name in names and talk is None:
                raise ApiError("存在同名剧情前提，请更换名称或选择已有前提。")
            names.add(name)
            pairs.add(pair)
            row["name"] = name
            result[key] = row
        return result

    @staticmethod
    def clean_pinned(value):
        """IDs the author set by hand: never renumbered automatically."""
        result = {"talks": [], "options": [], "events": []}
        if isinstance(value, dict):
            for key in result:
                items = value.get(key)
                if isinstance(items, list):
                    result[key] = sorted({int(v) for v in items if valid_id(v)})[:100000]
        return result

    def premise_references(self, payload):
        project = self.project(payload.get('projectId'), writable=True)
        maps, failures = self.readable_maps(project)
        # Unreadable tables are skipped (and named) instead of blocking the check.
        for name, filename in TABLES.items():
            if name in payload: maps[filename] = validate_map(payload[name], filename, allow_zero=True)
        pair = (payload.get('eventId'), payload.get('slot'))
        talk = payload.get('talkId') if type(payload.get('talkId')) is int else None
        def referenced(value):
            if isinstance(value, list) and premise_command_pair(value) == pair and Number_code(value) == 111: return True
            if talk is not None and isinstance(value, list) and len(value) >= 3 and Number_code(value) == 3 and abs(Number_code(value[1:]) or 0) in (3, 30) and any(Number_code(value[i:]) == talk for i in (2, 3) if i < len(value)): return True
            children = value.values() if isinstance(value, dict) else value if isinstance(value, list) else []
            return any(referenced(child) for child in children)
        def Number_code(value):
            try: return int(float(value[0]))
            except (ValueError, TypeError, IndexError): return None
        refs = []
        for filename, rows in maps.items():
            for key, row in rows.items():
                if referenced(row): refs.append(str(row.get('title') or row.get('name') or row.get('content') or filename[:-5])[:80] + ' [' + str(key) + ']')
        for key,row in self.api_romance(project).items():
            if referenced(row): refs.append('人物表白前提 [' + str(key) + ']')
        result = {'references': list(dict.fromkeys(refs))}
        if failures: result['unreadable'] = [f'{name}（{error.message}）' for name, error in failures.items()]
        return result

    def create_catalog_premise(self, payload):
        with self.lock:
            proposed = self.propose_premise(payload)
            project = self.project(payload.get('projectId'), writable=True)
            relative = 'StudentAgeStudio/editor-state.json'
            state = read_json(safe_path(project.path,relative), {})
            premise = proposed['premise']
            state.setdefault('premises', {})[str(premise['id'])] = premise
            self.commit(project, {relative:json_bytes(state)}, proposed['revision'])
            return {'premise':premise, 'previousRevision':proposed['revision'], 'revision':self.revision(project), 'projectId':project.id}

    def propose_premise(self, payload):
        with self.lock:
            project = self.project(payload.get("projectId"), writable=True)
            revision = self.revision(project)
            if payload.get("revision") != revision:
                raise ApiError("模组已发生变化，请重新载入后添加前提。", 409, "conflict")
            maps, failures = self.readable_maps(project)
            for name in ('TalkCfg.json', 'EvtCfg.json', 'OptionCfg.json'):
                if name in failures: raise failures[name]
            original = copy.deepcopy(maps)
            if "events" in payload:
                maps["EvtCfg.json"] = validate_map(payload["events"], "EvtCfg.json")
            state = read_json(safe_path(project.path, "StudentAgeStudio/editor-state.json"), {})
            if not isinstance(state, dict):
                raise ApiError("编辑记录格式无效，请先恢复备份。")
            catalog = self.catalog()
            premises = self.normalize_premises(payload.get("premises", state.get("premises", {})), state.get("premises", {}), maps, original, catalog, project)
            events = maps.get("EvtCfg.json", {})
            event = payload.get("eventId")
            if not isinstance(event, int) or not valid_id(event) or event > 16777215 or str(event) not in events:
                event = next((int(key) for key in events if valid_id(key) and int(key) <= 16777215), None)
            if event is None:
                raise ApiError("请先在当前模组新建一个剧情，再添加前提。")
            ident = max((int(key) for key in premises), default=0) + 1
            names = {row["name"] for row in premises.values()}
            name = payload.get("name", "")
            if not isinstance(name, str):
                raise ApiError("前提名称必须是文字。")
            if not name.strip():
                while "前提" + str(ident) in names:
                    ident += 1
            occupied = premise_pairs(original) | premise_pairs(maps) | premise_pairs(premises) | premise_pairs(catalog) | self.other_premise_pairs(project)
            slot = 1000000
            while (event, slot) in occupied and slot <= 16777215:
                slot += 1
            if 'slot' in payload:
                slot = payload['slot']
                if type(slot) is not int or not 0 <= slot <= 16777215:
                    raise ApiError('前提编号须为 0 到 16777215 的整数。')
                if (event, slot) in occupied: raise ApiError('该前提编号在本事件中已被占用。', 409)
            proposed = {"id": ident, "name": name.strip() or "前提" + str(ident), "eventId": event, "slot": slot}
            # A premise created on a dialogue line is the game's own "talk reached" check (3,3,<talk>).
            if 'talkId' in payload:
                talk = payload['talkId']
                if type(talk) is not int or not valid_id(talk):
                    raise ApiError('前提绑定的对话编号无效。')
                proposed['talkId'] = talk
            normalized = self.normalize_premises({**premises, str(ident): proposed}, state.get("premises", {}), maps, original, catalog, project)
            if revision != self.revision(project):
                raise ApiError("读取过程中模组已发生变化，请重新载入。", 409, "conflict")
            return {"premise": normalized[str(ident)], "revision": revision}

    @property
    def export_root(self):
        return safe_path(self.game, "StudentAgeStudio/Exports")

    def export_text(self, payload):
        self.project(payload.get("projectId"))
        kind, content = payload.get("format", "txt"), payload.get("content")
        if kind not in {"txt", "md", "json"} or not isinstance(content, str) or not content.strip():
            raise ApiError("请选择导出格式和有效的对话内容。")
        if len(content.encode("utf-8")) > 16 * 1024 * 1024:
            raise ApiError("导出内容超过 16 MB，请分段导出。", 413)
        if kind == "json":
            try:
                json.loads(content, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
            except (ValueError, RecursionError):
                raise ApiError("导出的 JSON 内容格式不完整。")
        label = payload.get("filename") or "历史对话"
        if not isinstance(label, str):
            raise ApiError("导出文件名必须是文字。")
        label = re.sub(r'[\\/:<>"|?*\x00-\x1f]', "_", label).strip(" .")[:100] or "历史对话"
        if label.lower().endswith("." + kind):
            label = label[:-(len(kind) + 1)]
        name = label + "-" + time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(3) + "." + kind
        destination = safe_path(self.export_root, name)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("xb") as output:
            output.write(content.encode("utf-8-sig") if kind == "txt" else content.encode("utf-8"))
        return {"ok": True, "name": name, "path": str(destination), "url": "/api/exports?name=" + urllib.parse.quote(name)}

    def export_file(self, name):
        if not isinstance(name, str) or name != Path(name).name or Path(name).suffix not in {".txt", ".md", ".json"}:
            raise ApiError("导出文件名无效。")
        path = safe_path(self.export_root, name)
        if not path.is_file():
            raise ApiError("找不到导出的文件。", 404)
        return path

    def open_export(self, name):
        path = self.export_file(name)
        reveal_file(path)
        return {"ok": True, "path": str(path)}

    def commit(self, project, changes, expected_revision=None, *, allowed_record_ids=None, raw=False):
        """Serialize writers across independent desktop application instances."""
        save_review.checkpoint()
        lock_path = safe_path(project.path, "StudentAgeStudio/.save.lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+b") as lock_file:
            lock_file_acquire(lock_file)
            try:
                return self._commit_unlocked(project, changes, expected_revision, allowed_record_ids=allowed_record_ids, raw=raw)
            finally:
                unlock_file(lock_file)

    def _commit_unlocked(self, project, changes, expected_revision=None, *, allowed_record_ids=None, raw=False):
        """Back up every changed file, stage all writes, replace atomically per file, and roll back errors.

        raw=True writes the user's own JSON text (raw source editor): the premise
        reconcile and record-ID checks need parsed tables and are skipped.
        Nothing here refuses a save except a stale revision; everything else becomes a note in commit_warnings.
        """
        self.commit_warnings = []
        if project.readonly:
            raise ApiError("创意工坊模组为只读。", 403)
        if expected_revision is not None and expected_revision != self.revision(project):
            raise ApiError("模组已被游戏或另一个窗口修改，请重新载入后再保存。", 409, "conflict")
        if project.original_mode and not raw:
            changes = dict(changes)
            for relative, data in changes.items():
                match = re.fullmatch(r'Cfgs/zh-cn/([A-Za-z][A-Za-z0-9_]*Cfg)\.json', relative)
                if match:
                    rows = validate_map(json.loads(data), match[1], allow_zero=True)
                    changes[relative] = json_bytes(self.preserve_editing_rows(project, match[1], rows))
        # Premises are editor data (editor-state.json): saving never reads or rewrites other tables for them.
        if project.original_mode and not raw:
            import original_mode
            changes = original_mode.compact_changes(self, project, changes, sys.modules[__name__])
        if not raw: self.commit_warnings.extend(self.record_ids.validate_created(project, changes, allowed_record_ids))
        normalized = {}
        for relative, data in changes.items():
            path = safe_path(project.path, relative)
            if path.exists():
                original_bytes = path.read_bytes()
                if original_bytes == data: continue
                if not raw and relative.endswith('.json'):
                    original_value = read_json(path, {})  # Fail closed if this target is unreadable.
                    incoming_value = json.loads(data)
                    ordered_talks = relative == 'Cfgs/zh-cn/TalkCfg.json' and isinstance(original_value,dict) and isinstance(incoming_value,dict) and list(original_value) != list(incoming_value)
                    if original_value == incoming_value and not ordered_talks: continue
            elif not raw and relative.startswith('Cfgs/zh-cn/') and json.loads(data) == {}:
                continue
            normalized[relative] = (path, data)
        if not normalized:
            return None
        stamp = time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(5)
        backup = safe_path(project.path, "StudentAgeStudio/Backups/" + stamp)
        backup.mkdir(parents=True, exist_ok=False)
        originals = {}
        stages = {}
        replaced = []
        try:
            for relative, (path, data) in normalized.items():
                originals[relative] = path.read_bytes() if path.exists() else None
                if originals[relative] is not None:
                    destination = safe_path(backup, relative)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    atomic_write(destination, originals[relative])
                path.parent.mkdir(parents=True, exist_ok=True)
                stage = path.with_name("." + path.name + "." + secrets.token_hex(6) + ".tmp")
                with stage.open("xb") as stream:
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
                stages[relative] = stage
            journal = {"state": "prepared", "files": {key: value is not None for key, value in originals.items()}, "time": stamp}
            atomic_write(backup / "transaction.json", json_bytes(journal))
            if expected_revision is not None and expected_revision != self.revision(project):
                raise ApiError("保存前模组发生了变化，请重新载入。", 409, "conflict")
            for relative, (path, _) in normalized.items():
                # Also catch changes made by external editors after the original snapshot.
                current = path.read_bytes() if path.exists() else None
                if current != originals[relative]:
                    raise ApiError("保存过程中检测到外部修改，已停止写入。", 409, "conflict")
                replace_file(stages[relative], path)
                replaced.append(relative)
            journal["state"] = "committed"
            atomic_write(backup / "transaction.json", json_bytes(journal))
            return str(backup)
        except Exception:
            for relative in reversed(replaced):
                path = normalized[relative][0]
                if originals[relative] is None:
                    path.unlink(missing_ok=True)
                else:
                    atomic_write(path, originals[relative])
            try:
                atomic_write(backup / "transaction.json", json_bytes({"state": "rolled_back", "files": list(originals)}))
            except OSError:
                pass
            raise
        finally:
            for stage in stages.values():
                stage.unlink(missing_ok=True)

    def normalize_branch_folders(self, incoming, previous, all_maps, original_maps, catalog, redirects, removed_options):
        """Validate editor ownership only; runtime edges remain exclusively in the submitted Cfg rows."""
        if not isinstance(incoming, dict) or not isinstance(previous, dict):
            raise ApiError("对话夹记录必须是完整的对象。")
        if len(incoming) > 20000:
            raise ApiError("对话夹数量过多。", 413)

        def preserve_unknown(old, new):
            result = copy.deepcopy(old) if isinstance(old, dict) else {}
            for key, value in new.items():
                result[key] = preserve_unknown(result.get(key), value) if isinstance(value, dict) else copy.deepcopy(value)
            return result

        def merged(table, maps):
            return {**self.catalog_rows(table, catalog), **maps.get(table + ".json", {})}

        talks = merged("TalkCfg", all_maps)
        old_talks = merged("TalkCfg", original_maps)
        options = merged("OptionCfg", all_maps)
        events = merged("EvtCfg", all_maps)
        known_talks = set(talks)
        known_talks.update(str(ident) for ident in catalog.get("baseTalkIds", []) if valid_id(ident))
        known_talks.difference_update(redirects)
        normalized, owners = {}, {}
        for key, incoming_folder in incoming.items():
            old = previous.get(key, {})
            if not isinstance(incoming_folder, dict):
                raise ApiError("每个对话夹都需要有效的归属记录。")
            folder = preserve_unknown(old, incoming_folder)
            parent, option = folder.get("parentTalkId"), folder.get("optionId")
            conditional = folder.get("kind") == "condition"
            if conditional:
                branch = folder.get("branchId")
                if not valid_id(parent) or not valid_id(branch) or key != f"{parent}:branch:{branch}":
                    raise ApiError("条件分支的父对话与名称不一致。")
                parent = int(parent)
                if str(parent) in redirects:
                    continue
                if str(parent) not in talks:
                    raise ApiError("条件分支的父对话不存在。")
                for field in ("routerId", "exitId", "endId"):
                    ident = folder.get(field)
                    node = talks.get(str(ident))
                    if not valid_id(ident) or not node or ident == parent:
                        raise ApiError("条件分支的连接记录不完整。")
                    if str(node.get("content") or "").strip() or node.get("roles") or node.get("option") or node.get("effect") or node.get("screenEffect"):
                        raise ApiError("分支连接记录不能包含台词、选项或演出效果。")
                base = folder.get("baseNext")
                if not isinstance(base, list) or any((x != 0 and not valid_id(x)) or (x != 0 and str(x) not in known_talks) for x in base):
                    raise ApiError("条件分支的后续对话无效。")
            else:
                if not valid_id(parent) or not valid_id(option) or key != str(parent) + ":" + str(option):
                    raise ApiError("对话夹的父对话、选项与记录名称不一致。")
                parent, option = int(parent), int(option)
                if str(parent) in redirects or str(option) in removed_options:
                    continue
                parent_row = talks.get(str(parent))
                old_parent = old_talks.get(str(parent), {})
                # Stale folders (their parent talk or option was renamed or removed, e.g. through
                # the JSON editor) carry nothing the talks themselves do not: drop them quietly.
                if parent_row is not None and option not in (parent_row.get("option") or []):
                    continue
                if parent_row is None:
                    if str(parent) not in known_talks or not isinstance(old, dict) or old.get("parentTalkId") != parent or old.get("optionId") != option:
                        continue
                if str(option) not in options:
                    continue
            if conditional and folder.get("failureNext") is not None:
                failure = folder["failureNext"]
                if not isinstance(failure, list) or any(not valid_id(ident) for ident in failure):
                    raise ApiError("分支失败去向必须是有效的对话。")
                failure = [new for ident in failure for new in redirects.get(str(ident), [ident])]
                if any(str(ident) not in known_talks for ident in failure):
                    raise ApiError("分支失败去向不存在。")
                folder["failureNext"] = failure
            members = folder.get("talkIds")
            if not isinstance(members, list) or any(not valid_id(ident) for ident in members):
                raise ApiError("对话夹内容必须是有序的对话列表。")
            members = [int(ident) for ident in members if str(ident) not in redirects]
            if len(members) != len(set(members)):
                raise ApiError("同一句对话不能在对话夹中重复出现。")
            for ident in members:
                if str(ident) not in known_talks:
                    raise ApiError("对话夹引用了不存在的对话。")
                if ident in owners:
                    raise ApiError("同一句对话不能同时属于两个对话夹。")
                owners[ident] = parent
            continuation = folder.get("continuation", {"kind": "end"})
            if not isinstance(continuation, dict):
                raise ApiError("对话夹后续设置格式无效。")
            kind = continuation.get("kind")
            if kind == "talk":
                target = continuation.get("talkId")
                if not valid_id(target):
                    raise ApiError("请选择有效的后续对话。")
                if str(target) in redirects:
                    replacements = redirects[str(target)]
                    if len(replacements) == 1:
                        continuation["talkId"] = target = replacements[0]
                    else:
                        continuation["kind"] = "end"
                        continuation.pop("talkId", None)
                        kind = "end"
                if kind == "talk" and str(target) not in known_talks:
                    raise ApiError("对话夹的后续对话不存在。")
            elif kind == "event":
                target = continuation.get("eventId")
                if not valid_id(target) or str(target) not in events:
                    raise ApiError("对话夹的后续剧情不存在。")
            elif kind == "targets" and conditional:
                if not isinstance(continuation.get("targets"), list) or any((x != 0 and not valid_id(x)) or (x != 0 and str(x) not in known_talks) for x in continuation["targets"]):
                    raise ApiError("原有分支出口无效。")
            elif kind == "following" and conditional:
                pass
            elif kind != "end":
                old_continuation = old.get("continuation") if isinstance(old, dict) else None
                if not isinstance(old_continuation, dict) or continuation != old_continuation:
                    raise ApiError("尚不支持这种对话夹后续设置。")
            folder.update(parentTalkId=parent, talkIds=members, continuation=continuation)
            if not conditional:
                folder["optionId"] = option
            normalized[key] = folder
        internal_owners = {}
        for key, folder in normalized.items():
            if folder.get("kind") != "condition":
                continue
            for field in ("routerId", "exitId", "endId"):
                ident = folder[field]
                identity = (folder["parentTalkId"], "end") if field == "endId" else (key, field)
                if ident in owners or (ident in internal_owners and internal_owners[ident] != identity):
                    raise ApiError("分支连接记录不能被其他对话夹占用。")
                internal_owners[ident] = identity
        # Parent dialogues can themselves live in another folder, but ownership must form a forest.
        finished = set()
        for member in owners:
            current, chain = member, set()
            while current in owners and current not in finished:
                if current in chain:
                    raise ApiError("对话夹不能包含自己的父对话，或形成循环归属。")
                chain.add(current)
                current = owners[current]
            finished.update(chain)
        return normalized

    def validate_talk_owners(self, value):
        if not isinstance(value, dict) or any(not valid_id(t) or not isinstance(owners, list) or any(not valid_id(e) for e in owners) for t,owners in value.items()):
            raise ApiError('对话所属事件记录格式无效，请恢复编辑记录备份。')

    def clean_orphan_dialogues(self, project_id):
        # Event-less dialogue belongs to other native systems or the external
        # dialogue workspace. Opening a project must never delete it.
        return 0

    def renumber_rows(self, payload):
        """Rewrite the given rows for a client-computed TalkCfg/OptionCfg renumbering.

        The editor keeps its own copy of the mod; only rows that reference the
        renumbered IDs are sent. References inside effects, conditions and
        typed fields follow the same rules as manual ID changes."""
        with self.lock:
            project = self.project(payload.get("projectId"), writable=True)
            if project.original_mode:
                raise ApiError("原版资源修改模式不整理对话编号。")
            catalog = self.catalog()
            mappings = {}; conflicts = {}
            for table, mapping in (payload.get("mappings") or {}).items():
                if table not in ("TalkCfg", "OptionCfg", "EvtCfg") or not isinstance(mapping, dict):
                    raise ApiError("编号映射格式无效。")
                clean = {}
                for before, after in mapping.items():
                    if not valid_id(before) or not valid_id(after):
                        raise ApiError("编号映射格式无效。")
                    clean[str(int(before))] = int(after)
                if len(set(clean.values())) != len(clean):
                    raise ApiError("编号映射存在重复的新编号。")
                base = set(self.catalog_rows(table, catalog))
                if table == "TalkCfg" and isinstance(catalog.get("baseTalkIds"), list):
                    base.update(str(ident) for ident in catalog["baseTalkIds"] if valid_id(ident))
                # A mod row may take an original row's ID (it overrides that row in the game); the editor
                # shows the conflict beside the record instead of refusing the change.
                collisions = sorted(v for v in clean.values() if str(v) in base and str(v) not in clean)
                if collisions: conflicts[table] = collisions
                if clean: mappings[table] = clean
            tables = {}
            for name, rows in (payload.get("tables") or {}).items():
                table = self.table_name(name)
                if not isinstance(rows, dict) or any(not valid_id(k) or not isinstance(v, dict) for k, v in rows.items()):
                    raise ApiError(table + " 的行格式无效。")
                revised = self.record_ids.rewrite(table, rows, mappings) if mappings else copy.deepcopy(rows)
                if table in mappings:
                    mapping = mappings[table]
                    revised = {str(mapping.get(key, int(key))): {**row, "id": mapping.get(key, int(key))} for key, row in revised.items()}
                tables[table] = revised
            return {"tables": tables, "mappings": mappings, "conflicts": conflicts}

    def save(self, payload):
        with self.lock:
            save_warnings = []
            project = self.project(payload.get("projectId"), writable=True)
            expected = payload.get("revision")
            if not isinstance(expected, str) or not hmac.compare_digest(expected, self.revision(project)):
                raise ApiError("模组已变化或缺少版本信息，请重新载入后再保存。", 409, "conflict")
            catalog = self.catalog()
            all_maps, unreadable = self.readable_maps(project)
            payload = dict(payload)
            if project.original_mode:
                for name, filename in TABLES.items():
                    if name in payload:
                        payload[name] = repair_map(payload[name], filename, allow_zero=True, warnings=save_warnings)
                        payload[name] = self.preserve_editing_rows(project, filename[:-5], payload[name])
            for name, filename in TABLES.items():
                if name in payload and filename in unreadable:
                    # A partially loaded project sends the unchanged reference
                    # map too. Never serialize that placeholder over a bad file.
                    if payload[name] != catalog.get(name, {}): save_warnings.append(unreadable[filename].message + "。为避免覆盖损坏的文件，这张表的修改未写入。")
                    del payload[name]
            original_maps = copy.deepcopy(all_maps)
            original_talks = copy.deepcopy(all_maps.get("TalkCfg.json", {}))
            catalog_talks = self.catalog_rows("TalkCfg", catalog)
            base_talk_ids = set(catalog_talks)
            if isinstance(catalog.get("baseTalkIds"), list):
                base_talk_ids.update(str(ident) for ident in catalog["baseTalkIds"] if valid_id(ident))
            previous_options = set(all_maps.get("OptionCfg.json", {}))
            touched = set()
            for name, filename in TABLES.items():
                if name not in payload:
                    continue
                old = all_maps.get(filename, {})
                inherited = self.catalog_rows(filename[:-5], catalog)
                incoming = repair_map(payload[name], filename, allow_zero="0" in old or "0" in inherited, warnings=save_warnings)
                revised = {}
                for key, row in incoming.items():
                    if key not in old and inherited.get(key) == row:
                        continue
                    revised[key] = {**old.get(key, {}), **copy.deepcopy(row)}
                    if filename == "TalkCfg.json" and revised[key].get("roleName") == "":
                        revised[key]["roleName"] = None
                all_maps[filename] = revised
                if revised != old: touched.add(filename)
            # Automatic renumbering already rewrote the editor's own tables; tables
            # it never loads (goals, phone messages, space content…) follow here.
            id_mappings = payload.get("idMappings") or {}
            if id_mappings:
                if not isinstance(id_mappings, dict) or any(t not in ("TalkCfg", "OptionCfg", "EvtCfg") or not isinstance(m, dict) or any(not valid_id(k) or not valid_id(v) for k, v in m.items()) for t, m in id_mappings.items()):
                    save_warnings.append("编号映射格式无效，其他配置表中的引用未同步改写。"); id_mappings = {}
                if unreadable:
                    save_warnings.append(next(iter(unreadable.values())).message + "。该文件中的引用未同步整理后的编号。")
                id_mappings = {t: {str(int(k)): int(v) for k, v in m.items()} for t, m in id_mappings.items()}
                sent = {TABLES[name] for name in TABLES if name in payload}
                for filename in list(all_maps):
                    if filename in sent or filename in ("TalkCfg.json", "OptionCfg.json", "EvtCfg.json"):
                        continue
                    rewritten = self.record_ids.rewrite(filename[:-5], all_maps[filename], id_mappings)
                    if rewritten != all_maps[filename]:
                        all_maps[filename] = rewritten
                        touched.add(filename)
            premise_state = read_json(safe_path(project.path, 'StudentAgeStudio/editor-state.json'), {})
            from event_ownership import ownership, deletion
            if not isinstance(premise_state, dict):
                save_warnings.append('编辑记录格式无效，已重建。'); premise_state = {}
            old_owners = premise_state.get('talkOwners', {})
            try: self.validate_talk_owners(old_owners)
            except ApiError: old_owners = {}
            removed_event_ids = set(original_maps.get('EvtCfg.json', {})) - set(all_maps.get('EvtCfg.json', {})) - set(self.catalog_rows('EvtCfg', catalog))
            # A rename is not an event deletion: pinned/shared children remain attached.
            removed_event_ids -= {old for old,new in id_mappings.get('EvtCfg',{}).items() if str(new) in all_maps.get('EvtCfg.json',{})}
            cascade_deleted = set()
            if removed_event_ids:
                if unreadable: save_warnings.append(next(iter(unreadable.values())).message + '。该文件中对被删事件的引用未检查。')
                cascade_deleted, cascade_options = deletion({**self.catalog_rows('EvtCfg', catalog), **original_maps.get('EvtCfg.json', {})}, original_talks,
                    original_maps.get('OptionCfg.json', {}), premise_state.get('branchFolders', {}), old_owners, removed_event_ids, {**self.catalog_rows('InteractCfg',catalog),**all_maps.get('InteractCfg.json', {})},catalog_talks)
                migrating={str(v) for v in payload.get('_idleChatMigration',[])}
                if migrating:
                    from event_ownership import interaction_talks
                    if not migrating<=removed_event_ids or any((original_maps.get('EvtCfg.json',{}).get(e,{}).get('studioSocial') or {}).get('kind') not in ('talk','loveTalk') for e in migrating):save_warnings.append('闲聊转换记录已变化，本次按普通删除处理。');migrating=set()
                    kept=interaction_talks(all_maps.get('InteractCfg.json',{}),all_maps.get('TalkCfg.json',{}),all_maps.get('OptionCfg.json',{}))
                    cascade_deleted-=kept
                    cascade_options-={str(o) for t in kept for o in all_maps.get('TalkCfg.json',{}).get(t,{}).get('option',[])}
                for t in cascade_deleted: all_maps.setdefault('TalkCfg.json', {}).pop(t, None)
                for o in cascade_options: all_maps.setdefault('OptionCfg.json', {}).pop(o, None)
                for name, field in [('TalkCfg.json','option'), ('EvtCfg.json','options')]:
                    for row in all_maps.get(name, {}).values():
                        if isinstance(row.get(field),list): row[field]=[o for o in row[field] if str(o) not in cascade_options]
                for row in all_maps.get('ActionEvtCfg.json', {}).values():
                    if isinstance(row.get('evts'),list): row['evts']=[e for e in row['evts'] if str(e) not in removed_event_ids]
                for row in all_maps.get('ActionCfg.json', {}).values():
                    if str(row.get('evtId')) in removed_event_ids: row['evtId']=0
                for event_id in removed_event_ids:
                    binding=original_maps.get('EvtCfg.json',{}).get(event_id,{}).get('studioSocial',{})
                    if event_id not in migrating and binding.get('interactionId'):all_maps.get('InteractCfg.json',{}).pop(str(binding['interactionId']),None)
                    if binding.get('unlockedActionId'):all_maps.get('ActionCfg.json',{}).pop(str(binding['unlockedActionId']),None)
                # Gift entry conditions reference the owning event; remove its dialogue slots before reference validation.
                for key,row in list(all_maps.get('GiftEvtCfg.json', {}).items()):
                    slots={i for i,roots in enumerate(row.get('talkId',[])) if isinstance(roots,list) and any(str(t) in cascade_deleted for t in roots)}
                    if not slots: continue
                    for field in ('npc','talkId','type'):
                        if isinstance(row.get(field),list):row[field]=[v for i,v in enumerate(row[field]) if i not in slots]
                    if not row.get('npc'):all_maps['GiftEvtCfg.json'].pop(key,None)
                    for remaining in all_maps.get('EvtCfg.json',{}).values():
                        if not isinstance(remaining.get('studioGiftBindings'),list):continue
                        remaining['studioGiftBindings']=[{**v,'index':int(v.get('index',0))-sum(i<int(v.get('index',0)) for i in slots)} if str(v.get('id'))==key else v for v in remaining['studioGiftBindings'] if str(v.get('id'))!=key or int(v.get('index',0)) not in slots]
                for key,row in list(all_maps.get('InteractCfg.json', {}).items()):
                    if str(row.get('talkId')) in cascade_deleted: del all_maps['InteractCfg.json'][key]
            reconciled_state = copy.deepcopy(premise_state)
            if 'premises' in payload: reconciled_state['premises'] = copy.deepcopy(payload['premises'])
            reconcile_premises(reconciled_state, premise_state, all_maps, original_maps)
            payload = {**payload, 'premises': reconciled_state.get('premises', {})}
            for filename, rows in all_maps.items():
                if rows != original_maps.get(filename): touched.add(filename)
            removed_events = set(original_maps.get("EvtCfg.json", {})) - set(all_maps.get("EvtCfg.json", {})) - set(self.catalog_rows("EvtCfg", catalog))
            if removed_events:
                if unreadable:
                    save_warnings.append(next(iter(unreadable.values())).message + "。该文件中对被删事件的引用未检查。")
                try: references = self.deletion_references(project, "EvtCfg", removed_events, all_maps.get("EvtCfg.json", {}), proposed_maps=all_maps)
                except ApiError as error: references = []; save_warnings.append('未能检查事件引用：' + error.message)
                if references:
                    save_warnings.append("已删除仍被引用的事件，以下位置的引用需要自行调整：" + "；".join(references))
            deleted = payload.get("deletedIds", [])
            if not isinstance(deleted, list): deleted = []
            if any(not valid_id(ident) for ident in deleted):
                save_warnings.append("待删除对话编号中有无效项，已忽略。"); deleted = [ident for ident in deleted if valid_id(ident)]
            # The full talks map authorizes deletion of rows omitted from it as well.
            removed = set(str(ident) for ident in deleted) | cascade_deleted
            if "talks" in payload:
                removed.update(set(original_talks) - set(payload["talks"]))
                if payload.get("_fullCatalogTable") == "TalkCfg" or isinstance(catalog.get("talks"), dict):
                    removed.update(set(catalog_talks) - set(payload["talks"]))
            if unreadable and (removed or ('options' in payload and previous_options - set(payload['options']))):
                error = next(iter(unreadable.values()))
                save_warnings.append(error.message + '。该文件中对被删对话或选项的引用未检查。')
            replacements = payload.get("replacements") or {}
            if not isinstance(replacements, dict):
                save_warnings.append("对话替换关系格式无效，已忽略。"); replacements = {}
            prior_deleted = read_json(safe_path(project.path, "StudentAgeStudio/deleted-talks.json"), {})
            prior_redirects = flat_deletions(prior_deleted)
            redirects = copy.deepcopy(prior_redirects)
            # Existing native redirect overrides must survive even before a base-game catalog is exported.
            native_tombstones = set(prior_redirects).intersection(original_talks)
            for key in removed:
                if key in cascade_deleted:
                    values = []
                elif key in replacements:
                    values = replacements[key]
                    if isinstance(values, int):
                        values = [values] if values else []
                    if not isinstance(values, list) or any(not valid_id(value) for value in values):
                        save_warnings.append("对话 " + str(key) + " 的替换目标无效，已按无后续处理。"); values = []
                elif key in redirects:
                    values = redirects[key]
                else:
                    row = original_talks.get(key, catalog_talks.get(key, {}))
                    following = row.get("nextTalk") or []
                    values = following if not row.get("check") and not row.get("option") and len(following) <= 1 else []
                redirects[key] = [int(value) for value in values if str(value) != key]
            # Restoring an ID through undo should remove its old tombstone.
            for key in list(redirects):
                if "talks" in payload and key not in removed and key in payload["talks"]:
                    redirects.pop(key)

            def resolve(value, seen=None):
                key = str(value)
                if key not in redirects:
                    return [value]
                seen = set() if seen is None else set(seen)
                if key in seen:
                    return []
                seen.add(key)
                result = []
                for following in redirects[key]:
                    result.extend(resolve(following, seen))
                return result

            redirects = {key: [int(value) for value in resolve(int(key))] for key in redirects}
            if redirects:
                all_maps.setdefault("TalkCfg.json", {})
            for filename, table in all_maps.items():
                if not isinstance(table, dict):
                    continue
                before = json_bytes(table)
                for row in table.values():
                    if not isinstance(row, dict):
                        continue
                    for field in TALK_FIELDS.intersection(row):
                        value = row[field]
                        if isinstance(value, list) and all(isinstance(entry, int) and not isinstance(entry, bool) for entry in value):
                            row[field] = [target for ident in value for target in resolve(ident)]
                        elif filename == 'GiftEvtCfg.json' and field == 'talkId' and isinstance(value, list):
                            # One dialogue list per recipient; preserve slot alignment.
                            row[field] = [[target for ident in entry for target in resolve(ident)]
                                          if isinstance(entry, list) else entry for entry in value]
                        elif isinstance(value, int) and not isinstance(value, bool) and str(value) in redirects:
                            targets = resolve(value)
                            if len(targets) > 1:
                                save_warnings.append("删除后的多个跳转无法写入单目标字段 " + filename + "/" + field + "，已使用第一个替代对话。")
                            row[field] = targets[0] if targets else 0
                if filename == "TalkCfg.json":
                    for key in redirects:
                        if key in base_talk_ids or key in native_tombstones:
                            table[key] = inert_talk(key, redirects[key])
                        else:
                            table.pop(key, None)
                if json_bytes(table) != before:
                    touched.add(filename)
            removed_options = set()
            if "options" in payload or cascade_deleted:
                removed_options = previous_options - set(all_maps.get("OptionCfg.json", {}))
                for row in all_maps.get("TalkCfg.json", {}).values():
                    if isinstance(row, dict) and isinstance(row.get("option"), list):
                        old = row["option"]
                        row["option"] = [ident for ident in old if str(ident) not in removed_options]
                        if row["option"] != old:
                            touched.add("TalkCfg.json")
            changes = {}
            prior_cues = self.audio_cues(project, original_talks)
            if "audioCues" in payload or redirects or prior_cues.get("bgm") and ("talks" in payload or "events" in payload):
                incoming_cues = copy.deepcopy(payload.get("audioCues", prior_cues))
                deleted_talks = set(redirects)
                if isinstance(incoming_cues, dict) and isinstance(incoming_cues.get("sfx", {}), dict) and isinstance(incoming_cues.get("bgm", []), list):
                    incoming_cues["sfx"] = {key: value for key, value in incoming_cues.get("sfx", {}).items() if key not in deleted_talks}
                    for group in incoming_cues.get("bgm", []):
                        if isinstance(group, dict) and isinstance(group.get("talkIds"), list):
                            group["talkIds"] = [ident for ident in group["talkIds"] if str(ident) not in deleted_talks]
                    incoming_cues["bgm"] = [group for group in incoming_cues.get("bgm", []) if not isinstance(group, dict) or group.get("talkIds") != []]
                    if isinstance(incoming_cues.get("nativeAudio"), dict):
                        incoming_cues["nativeAudio"] = {key: value for key, value in incoming_cues["nativeAudio"].items() if key not in deleted_talks}
                cues = self.validate_audio_cues(incoming_cues, all_maps, prior_cues)
                from native_audio import export as export_native_audio
                before_audio = {k:r.get("audio", 0) for k,r in all_maps.get("TalkCfg.json", {}).items()}
                export_native_audio(cues, prior_cues, all_maps.setdefault("TalkCfg.json", {}), original_talks,
                                    {**self.catalog_rows("AudioCfg"), **all_maps.get("AudioCfg.json", {})},
                                    all_maps.get("EvtCfg.json", {}), all_maps.get("OptionCfg.json", {}))
                if before_audio != {k:r.get("audio", 0) for k,r in all_maps["TalkCfg.json"].items()}:
                    touched.add("TalkCfg.json")
                if cues != prior_cues:
                    changes["StudentAgeStudio/audio-cues.json"] = json_bytes(cues)
            canonical_deleted = nested_deletions(redirects)
            if canonical_deleted != prior_deleted:
                changes["StudentAgeStudio/deleted-talks.json"] = json_bytes(canonical_deleted)
            state = read_json(safe_path(project.path, "StudentAgeStudio/editor-state.json"), {})
            if not isinstance(state, dict):
                save_warnings.append("编辑记录格式无效，已重建。"); state = {}
            old_state = copy.deepcopy(state)
            if 'externalDialogueFolders' in payload:
                from external_dialogues import folders as external_folders
                external_owners=self.load(project.id).get('talkOwners',{})
                external_rows={k:v for k,v in all_maps.get('TalkCfg.json',{}).items() if not external_owners.get(k)}
                state['externalDialogueFolders']=external_folders(payload['externalDialogueFolders'],external_rows,sys.modules[__name__])
            if "protagonistGender" in payload:
                gender=payload["protagonistGender"]
                if type(gender) is not int or gender not in (1,2): gender = 1
                state["protagonistGender"]=gender
            if "eventGrades" in payload:
                grades=payload["eventGrades"]
                if not isinstance(grades,dict): grades = {}
                grades = {key: value for key, value in grades.items() if (key == "all" or valid_id(key)) and type(value) is int and value in (0, 1)}
                state["eventGrades"]={str(key):value for key,value in grades.items() if key=="all" or str(key) in all_maps.get("EvtCfg.json",{})}
            lighting = {}
            for ident, row in all_maps.get("TalkCfg.json", {}).items():
                value = row.get("studioLighting", {})
                if not isinstance(value, dict) or any(not str(role).isdigit() or not isinstance(enabled, bool) for role, enabled in value.items()):
                    save_warnings.append('对话 ' + str(ident) + ' 的人物高光设置无效，已清除。')
                    row["studioLighting"] = {}; touched.add("TalkCfg.json"); value = {}
                # The current speaker cannot be dimmed, including by old editor metadata.
                # Game/third-party mods use null for narration as well as [].
                # Interpret it as no speaker without rewriting the source field.
                speakers = {str(role) for role in (row.get("roleIds") or [])}
                canonical = {role: enabled for role, enabled in value.items() if enabled or str(role) not in speakers}
                if canonical != value:
                    row["studioLighting"] = canonical
                    touched.add("TalkCfg.json")
                lighting[ident] = copy.deepcopy(canonical)
            if lighting or "lighting" in state:
                state["lighting"] = lighting
            # The old "deleted premise slots" ledger is no longer kept: it never expired and turned into spurious errors.
            state.pop('deletedPremisePairs', None)
            previous_folders = state.get("branchFolders", {})
            incoming_folders = payload.get("branchFolders", previous_folders)
            try:
                folders = self.normalize_branch_folders(incoming_folders, previous_folders, all_maps, original_maps, catalog, redirects, removed_options)
            except ApiError as error:
                # Saving is never refused over editor bookkeeping: keep every folder that validates on its
                # own, drop the rest, and tell the editor what was left out. The Cfg rows are saved as sent.
                folders, dropped = {}, []
                for key, folder in (incoming_folders if isinstance(incoming_folders, dict) else {}).items():
                    try:
                        folders.update(self.normalize_branch_folders({key: folder}, {key: previous_folders[key]} if key in previous_folders else {}, all_maps, original_maps, catalog, redirects, removed_options))
                    except ApiError as inner:
                        dropped.append(str(key) + '：' + inner.message)
                save_warnings.append('对话夹记录有问题，已保存对话内容并略过 ' + str(len(dropped)) + ' 个对话夹（' + error.message + '）。')
            if "branchFolders" in payload or folders != previous_folders:
                state["branchFolders"] = folders
            proposed_owners = payload.get('talkOwners', old_owners)
            try: self.validate_talk_owners(proposed_owners)
            except ApiError as error:
                save_warnings.append('对话归属记录无效，已按当前对话连接重新推算（' + error.message + '）。'); proposed_owners = old_owners if isinstance(old_owners, dict) else {}
                try: self.validate_talk_owners(proposed_owners)
                except ApiError: proposed_owners = {}
            # Original connectivity records ownership before a submitted edit
            # disconnects a segment. This also covers non-UI table saves.
            inferred_owners = ownership({**self.catalog_rows('EvtCfg', catalog), **original_maps.get('EvtCfg.json', {})}, original_talks,
                original_maps.get('OptionCfg.json', {}), previous_folders, old_owners)
            known_owners = {t:list(set(inferred_owners.get(t, [])) | set(proposed_owners.get(t, []))) for t in set(inferred_owners) | set(proposed_owners)}
            state['talkOwners'] = ownership({**self.catalog_rows('EvtCfg', catalog), **all_maps.get('EvtCfg.json', {})},
                {t:r for t,r in all_maps.get('TalkCfg.json', {}).items() if t not in redirects}, all_maps.get('OptionCfg.json', {}), folders, known_owners)
            premises = state.get("premises", {})
            if "premises" in payload or premises:
                try:
                    premises = self.normalize_premises(payload.get("premises", premises), premises, all_maps, original_maps, catalog, project)
                except ApiError as error:
                    save_warnings.append('前提记录有问题，本次保存沿用上一次的前提列表（' + error.message + '）。')
                    premises = state.get("premises", {}) if isinstance(state.get("premises"), dict) else {}
                state["premises"] = premises
            if "pinnedIds" in payload:
                state["pinnedIds"] = self.clean_pinned(payload.get("pinnedIds"))
            if "order" in payload:
                order = payload["order"]
                if not isinstance(order, list): order = []
                order = [ident for ident in order if valid_id(ident)]
                talk_map = all_maps.get("TalkCfg.json", {})
                order = list(dict.fromkeys(int(ident) for ident in order if str(ident) in talk_map and str(ident) not in redirects))
                old_order = state.get("order", []) if isinstance(state.get("order"), list) else []
                order.extend(int(ident) for ident in old_order if valid_id(ident) and int(ident) not in order and str(ident) not in redirects)
                ordered_map = {str(ident): talk_map[str(ident)] for ident in order if str(ident) in talk_map}
                ordered_map.update({key: row for key, row in talk_map.items() if key not in ordered_map})
                if list(ordered_map) != list(talk_map):
                    all_maps["TalkCfg.json"] = ordered_map
                    touched.add("TalkCfg.json")
                state["order"] = order
            if state != old_state:
                changes["StudentAgeStudio/editor-state.json"] = json_bytes(state)
            changes.update({"Cfgs/zh-cn/" + filename: json_bytes(all_maps[filename]) for filename in touched})
            backup = self.commit(project, changes, expected)
            return {"ok": True, "revision": self.revision(project), "backup": backup, "repairedIds": list(redirects),
                    "branchFolders": folders, "premises": premises, "talkOwners": state["talkOwners"],
                    "warnings": [error.message + '。此次保存保留了此文件的原始内容。' for error in unreadable.values()] + save_warnings + list(getattr(self, 'commit_warnings', []))}

    def create(self, name):
        with self.lock:
            self.mods.mkdir(parents=True, exist_ok=True)
            package = "STUDIO_" + time.strftime("%Y%m%d") + "_" + secrets.token_hex(4).upper()
            path = self.mods / package
            path.mkdir(exist_ok=False)
            try:
                (path / "Cfgs/zh-cn").mkdir(parents=True)
                for folder in ("Textures/Bg", "Textures/Role", "Textures/CG", "Audios"):
                    (path / folder).mkdir(parents=True)
                manifest = {"title": display_name(name), "description": "使用学生时代创作工坊创建", "tags": [], "dependencies": [],
                            "visible": 2, "metadata": {"id": 0, "version": "1.0.0", "packageId": package}}
                atomic_write(path / "manifest.json", json_bytes(manifest))
                for filename in TABLES.values():
                    atomic_write(path / "Cfgs/zh-cn" / filename, b"{}\n")
            except Exception:
                shutil.rmtree(path)
                raise
            return next(project.public() for project in self.projects() if project.path == path)

    def duplicate(self, project_id, name):
        with self.lock:
            source = self.project(project_id)
            created = self.create(name or source.name + "（本地副本）")
            destination = self.project(created["id"], writable=True)
            try:
                total = 0
                before_revision = self.revision(source)
                for root, directories, files in os.walk(source.path, followlinks=False):
                    base = Path(root)
                    directories[:] = [entry for entry in directories if not (base / entry).is_symlink()
                                      and not excluded_entry(base / entry, source.path)]
                    for filename in files:
                        file = base / filename
                        if excluded_entry(file, source.path) or file.is_symlink() or not inside(file, source.path):
                            continue
                        relative = file.relative_to(source.path)
                        if relative == Path("manifest.json"):
                            continue
                        total += file.stat().st_size
                        if total > 4 * 1024 * 1024 * 1024:
                            raise ApiError("模组素材超过 4 GB，复制已停止。", 413)
                        target = safe_path(destination.path, relative)
                        target.parent.mkdir(parents=True, exist_ok=True)
                        try:
                            stable_copy(file, target)
                        except OSError as error:
                            raise ApiError('无法复制模组文件：' + str(relative) + '。请等待其他程序写入完成后重试。' + str(error), 422, 'copy_file_unavailable') from error
                manifest = read_json(source.path / "manifest.json", {})
                metadata = manifest.get("metadata") or {}
                manifest["title"] = display_name(name, source.name + "（本地副本）")
                manifest["metadata"] = {**metadata, "id": 0, "packageId": destination.package}
                atomic_write(destination.path / "manifest.json", json_bytes(manifest))
                # Resource paths identify a mod by packageId, not by workshop folder number.
                warnings_list = []
                for file in [*self.cfg_files(destination).values(), *[p for p in [destination.path/"StudentAgeStudio/goal-images.json"] if p.is_file()]]:
                    try: data = read_json(file, {})
                    except ApiError as error:
                        warnings_list.append(error.message + '。副本保留了此文件的原始内容。')
                        continue
                    def remap(value):
                        if isinstance(value, dict):
                            return {key: remap(item) for key, item in value.items()}
                        if isinstance(value, list):
                            return [remap(item) for item in value]
                        if isinstance(value, str):
                            match = re.match(r"^(Mods[\\/])([^\\/]+)([\\/].*)$", value, re.IGNORECASE)
                            if match and match.group(2).casefold() in {source.package.casefold(), source.path.name.casefold()}:
                                return match.group(1) + destination.package + match.group(3)
                        return value
                    remapped = remap(data)
                    if remapped != data:
                        atomic_write(file, json_bytes(remapped))
                if self.revision(source) != before_revision:
                    raise ApiError('另一编辑器在复制过程中保存了模组，请重试创建副本。原模组未修改。', 409, 'copy_conflict')
                result = self.project(created["id"]).public()
                if warnings_list: result['warnings'] = warnings_list
                return result
            except Exception:
                shutil.rmtree(destination.path)
                raise

    @staticmethod
    def table_name(value):
        name = str(value or "")
        if name.endswith(".json"):
            name = name[:-5]
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*Cfg", name):
            raise ApiError("配置表名称无效。")
        return name

    def table_schema(self, name, rows=None):
        catalog = self.catalog()
        schemas = catalog.get("schemas", catalog.get("tableSchemas", {}))
        schema = schemas.get(name, {}) if isinstance(schemas, dict) else {}
        schema = copy.deepcopy(schema) if isinstance(schema, dict) else {}
        if name == 'GiftEvtCfg' and not schema:
            schema = copy.deepcopy(json.loads((Path(__file__).parent / 'catalog-schema.json').read_text(encoding='utf-8'))['schemas'][name])
        if name in gameplay_features.schemas():
            schema = copy.deepcopy(gameplay_features.schemas()[name])
        schema.setdefault("name", name)
        schema.setdefault("label", {"EvtCfg": "剧情事件", "TalkCfg": "对话", "OptionCfg": "对话选项", "PersonCfg": "人物",
                                     "ModFaceCfg": "人物表情", "BgCfg": "场景背景", "CGCfg": "CG 插画", "AudioCfg": "音频", "EndingPartCfg": "结局片段"}.get(name, name))
        schema.setdefault("category", "剧情" if name in {"EvtCfg", "TalkCfg", "OptionCfg", "EndingCfg", "EndingPartCfg"}
                          else "人物" if "Person" in name or name == "ModFaceCfg" else "素材" if name in {"BgCfg", "CGCfg", "AudioCfg"} else "玩法与配置")
        if not isinstance(schema.get("fields"), list):
            schema["fields"] = []
        known = {field.get("name") for field in schema["fields"] if isinstance(field, dict)}
        samples = list((rows or {}).values())[:200]
        for row in samples:
            if not isinstance(row, dict):
                continue
            for field, value in row.items():
                if field in known:
                    continue
                kind = ("bool" if isinstance(value, bool) else "int" if isinstance(value, int) else "float" if isinstance(value, float)
                        else "string" if isinstance(value, str) else "array" if isinstance(value, list) else "object" if isinstance(value, dict) else "unknown")
                schema["fields"].append({"name": field, "label": field, "type": kind, "advanced": True, "inferred": True})
                known.add(field)
        if "id" not in known:
            schema["fields"].insert(0, {"name": "id", "label": "编号", "type": "int", "required": True})
        if name == "PhoneMsgCfg":
            for field in schema["fields"]:
                key = field["name"]
                if key == "next":field["range"] = {"table":"PhoneMsgCfg"}
                if key == "role":field["range"] = {"table":"PersonCfg"}
                if key == "cond":field["editorType"] = "Condition"
                if key == "effect":field["editorType"] = "Effect"
        if name == "IntentCfg":
            from goal_workbench import FIELD_LABELS
            links = {'npc':'PersonCfg','before':'IntentCfg','finishTalk':'TalkCfg','failTalk':'TalkCfg','renshengguan':'RenshengguanTypeCfg'}
            for field in schema['fields']:
                key = field['name']
                if key in FIELD_LABELS:field['label'] = FIELD_LABELS[key]
                if key in links:field['range'] = {'table':links[key]}
                if key == 'fail':field['editorType'] = 'Effect'
                if key == 'next':field.pop('range', None)
        return schema

    def workshop_features(self, tables):
        definitions = read_json(Path(__file__).with_name("workshop-features.json"), [])
        by_name = {row["name"]: row for row in tables}
        result = []
        for definition in definitions:
            feature = copy.deepcopy(definition)
            name = feature.get("primaryTable")
            if name and feature.get("id") != "external-dialogues" and not by_name.get(name, {}).get("schema", {}).get("nativePage"):
                continue
            feature["localCount"] = sum(by_name.get(t, {}).get("localCount", 0) for t in ([name] if feature.get("id")=="idle-chats" else feature.get("tables", [])))
            feature["tables"] = [table for table in feature.get("tables", []) if table in by_name]
            result.append(feature)
        known = {name for feature in result for name in feature.get("tables", [])}
        for table in tables:
            if not table["schema"].get("nativePage") or table["name"] in known:
                continue
            result.append({"id": table["name"], "label": table["label"], "description": "编辑当前模组的内容", "tables": [table["name"]],
                           "primaryTable": table["name"], "entry": {"kind": "table", "table": table["name"]}, "previewKind": "summary",
                           "group": "其他功能", "createLabel": "添加", "native": True, "localCount": table["localCount"]})
        return result

    def workshop_info(self, project_id):
        with self.lock, self.catalog_scope():
            project = self.project(project_id)
            catalog = self.catalog()
            files = self.cfg_files(project)
            names = {filename[:-5] for filename in files if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*Cfg\.json", filename)}
            names.update(filename[:-5] for filename in TABLES.values())
            names.update(gameplay_features.NAMES)
            for source in (catalog.get("tables", {}), catalog.get("schemas", {}), catalog.get("tableSchemas", {})):
                if isinstance(source, dict):
                    names.update(name.removesuffix(".json") for name in source if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*Cfg(?:\.json)?", name))
            result, warnings_list = [], []
            for name in names:
                inherited = self.catalog_rows(name, catalog)
                error_message = None
                try:
                    local = read_json(files[name + ".json"], {}) if name + ".json" in files else {}
                    if not isinstance(local, dict): raise ApiError(name + " 配置不是编号表。", 422)
                except ApiError as error:
                    local, error_message = {}, error.message
                    warnings_list.append(error.message)
                schema = self.table_schema(name, local or inherited)
                result.append({"name": name, "file": name + ".json", "label": schema["label"], "category": schema["category"],
                               "order": schema.get("order", 9999), "count": len(set(local) | set(inherited)), "localCount": len(set(inherited) | (set(local) & set(original_mode.owned(self, project).get(name, [])))) if project.original_mode else len(local),
                               "hasLocal": name + ".json" in files, "hasCatalog": bool(inherited), "readOnly": project.readonly,
                               "schema": schema, "fields": schema["fields"], **({'error': error_message} if error_message else {})})
            result.sort(key=lambda entry: (entry["order"] if isinstance(entry["order"], (int, float)) else 9999, entry["category"], entry["name"]))
            resolution = catalog.get("referenceResolution")
            if not isinstance(resolution, list) or len(resolution) != 2 or any(not isinstance(value, (int, float)) or value <= 0 for value in resolution):
                resolution = [2560, 1440]
            commands = copy.deepcopy(catalog.get("commands", {}))
            def signature(row):
                return json.dumps([len(row.get("template", [])), {key: float(value) if isinstance(value, (int, float)) else value for key, value in row.get("match", {}).items()}], sort_keys=True)
            for kind in ("condition", "effect"):
                bundled = read_json(Path(__file__).with_name(kind + "-templates.json"), [])
                rows = commands.setdefault(kind, [])
                existing = {signature(row) for row in rows if isinstance(row, dict)}
                rows.extend(row for row in bundled if signature(row) not in existing)
                if kind == 'effect': rows.sort(key=lambda row: row.get('label') != '直接成为恋人')
            state = read_json(safe_path(project.path, 'StudentAgeStudio/editor-state.json'), {})
            premises = state.get('premises', {}) if isinstance(state, dict) else {}
            for entry in named_entries(premises):
                row = entry['rows'][0]
                commands['condition'].insert(0, {'label': entry['title'], 'template': row,
                                               'match': dict(enumerate(row)), 'parameters': []})
            return {"project": project.public(), "revision": self.revision(project), "tables": result,
                    "features": self.workshop_features(result), "warnings": warnings_list,
                    "supported": [entry["name"] for entry in result], "catalogAvailable": bool(catalog.get("schemas")),
                    "operations": catalog.get("operations", []), "commands": commands,
                    "referenceResolution": resolution}

    def table(self, project_id, requested):
        with self.lock:
            project = self.project(project_id)
            name = self.table_name(requested)
            revision = self.revision(project)
            local = read_json(safe_path(project.path, "Cfgs/zh-cn/" + name + ".json"), {})
            inherited = self.catalog_rows(name)
            if name == 'MinigameActionCfg':
                from character_rules import native_rules
                inherited = {**native_rules(self.game).get(name, {}), **inherited}
            warnings_list = []
            if isinstance(local, dict):
                for key, row in local.items():
                    if valid_id(key) and isinstance(row, dict) and row.get("id") != int(key):
                        row["id"] = int(key)
                        warnings_list.append(name + " #" + key + " 已在编辑副本中按表键修复编号。")
            validate_map(local, name, allow_zero=True)
            rows = copy.deepcopy(inherited)
            rows.update(local)
            if project.original_mode: rows = original_mode.visible_rows(self, project, name, local)
            if name == "TalkCfg":
                markers = flat_deletions(read_json(safe_path(project.path, "StudentAgeStudio/deleted-talks.json"), {}))
                for key in markers:
                    rows.pop(key, None)
            if revision != self.revision(project):
                raise ApiError("读取时配置发生变化，请重新载入。", 409, "conflict")
            local_rows = copy.deepcopy(rows) if project.original_mode else {key: copy.deepcopy(rows[key]) for key in local if key in rows}
            if name == "PersonCfg":
                for ident in read_json(project.path/"StudentAgeStudio/goal-images.json", {}): rows.pop(ident, None)
            return {"project": project.public(), "name": name, "rows": rows, "referenceRows": copy.deepcopy(inherited), "localRows": local_rows, "localIds": list(local_rows), "schema": self.table_schema(name, rows), "revision": revision, "warnings": warnings_list}

    def validate_fields(self, name, rows, previous):
        # Work in progress is saveable; these editors do not gate on completeness.
        if name in gameplay_features.NAMES:return
        fields = self.table_schema(name).get("fields", [])
        for key, row in rows.items():
            original = previous.get(key, {})
            for field in fields:
                with save_review.checking(ApiError, name + " 编号 " + key):
                    if not isinstance(field, dict) or not field.get("name"):
                        continue
                    prop = field["name"]
                    if prop not in row:
                        if key not in previous and field.get("required") and field.get("default") is None:
                            raise ApiError(name + " 缺少必填字段 " + str(field.get("label", prop)) + "。")
                        continue
                    if prop in original and row[prop] == original[prop]:
                        continue
                    value = row[prop]
                    if value is None:
                        if field.get("required"):
                            raise ApiError(name + " 的 " + str(field.get("label", prop)) + " 不能为空。")
                        continue
                    kind = str(field.get("type", "")).lower().replace("system.", "")
                    invalid = False
                    if kind in {"int", "int32", "integer"}:
                        invalid = isinstance(value, bool) or not isinstance(value, int) or value < -2147483648 or value > 2147483647
                    elif kind in {"long", "int64"}:
                        invalid = isinstance(value, bool) or not isinstance(value, int) or value < -9223372036854775808 or value > 9223372036854775807
                    elif kind in {"float", "single", "double", "decimal", "number"}:
                        invalid = isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
                    elif kind in {"bool", "boolean"}:
                        invalid = not isinstance(value, bool)
                    elif kind == "string":
                        invalid = not isinstance(value, str)
                    elif kind in {"array", "list"} or kind.startswith("list<") or kind.endswith("[]"):
                        invalid = not isinstance(value, list)
                        if not invalid and (kind.startswith("list<") or kind.endswith("[]")):
                            from native_character import valid_value
                            invalid = not valid_value(value, kind)
                    elif kind in {"object", "dictionary"} or kind.startswith("dictionary<"):
                        invalid = not isinstance(value, dict)
                    if invalid:
                        raise ApiError(name + " 编号 " + key + " 的 " + str(field.get("label", prop)) + " 数据类型不正确。" + ("班级请填写数字编号，例如三班填 3。" if name == "PersonGrowCfg" and prop == "className" else ""))


    def deletion_references(self, project, target, removed, proposed, proposed_maps=None):
        """Return source locations using native range metadata plus non-scalar cinematic references."""
        if not removed:
            return []
        catalog = self.catalog()
        local_files = self.cfg_table_files(project)
        sources = set(filename[:-5] for filename in local_files)
        if isinstance(catalog.get("schemas"), dict):
            sources.update(catalog["schemas"])
        explicit = {"PersonCfg": {"TalkCfg": {"roleIds"}, "EvtCfg": {"npc"}, "IntentCfg": {"npc"}, "KZoneContentCfg": {"role"}, "KZoneCommentCfg": {"roles"}, "KZoneProfileCfg": {"id"}},
                    "BgCfg": {"TalkCfg": {"bg"}, "BgCfg": {"gaozhongUrl"}},
                    "AudioCfg": {"TalkCfg": {"audio", "vocals"}, "BgCfg": {"audio"}, "PersonCfg": {"clickAudio"}},
                    "EvtCfg": {"OptionCfg": {"nextEvtId"}, "ActionEvtCfg": {"evts"}},
                    "IntentCfg": {"IntentCfg": {"before"}},
                    "TalkCfg": {"IntentCfg": {"finishTalk", "failTalk"}}}
        event_templates = []
        if target in ("EvtCfg", "IntentCfg", "PhoneMsgCfg"):
            for kind in ("condition", "effect"):
                event_templates.extend(catalog.get("commands", {}).get(kind, []))
                event_templates.extend(read_json(Path(__file__).with_name(kind + "-templates.json"), []))
            event_templates = [template for template in event_templates if any(p.get("range", {}).get("table") == target for p in template.get("parameters", []))]
        results = []
        if target == "AudioCfg" and removed:
            cues = self.audio_cues(project)
            for ident, entries in cues.get("sfx", {}).items():
                if any(isinstance(entry, dict) and str(entry.get("audioId")) in removed for entry in entries):
                    results.append("对话 #" + ident + " · 音效")
            for group in cues.get("bgm", []):
                if isinstance(group, dict) and str(group.get("audioId")) in removed:
                    results.append("背景音乐范围 " + str(group.get("id", "")))
        def contains(value):
            if isinstance(value, int) and not isinstance(value, bool):
                return str(value) in removed
            if isinstance(value, list):
                return any(contains(item) for item in value)
            return False
        for source in sources:
            if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*Cfg", source):
                continue
            rows = copy.deepcopy(self.catalog_rows(source, catalog))
            local = (proposed_maps.get(source + ".json", {}) if proposed_maps is not None
                     else read_json(local_files[source + ".json"], {}) if source + ".json" in local_files else {})
            if isinstance(local, dict):
                rows.update(local)
            if source == target:
                rows = {**self.catalog_rows(source, catalog), **proposed}
            fields = set(explicit.get(target, {}).get(source, set()))
            tuple_fields = []
            for field in self.table_schema(source).get("fields", []):
                bounds = field.get("range", {}) if isinstance(field, dict) else {}
                reference = bounds.get("table") if isinstance(bounds, dict) else None
                if reference and str(reference).split(".")[-1] == target:
                    fields.add(field["name"])
                for item in field.get("itemFields", []):
                    if item.get("range", {}).get("table") == target:
                        tuple_fields.append((field["name"], item["index"]))
            for ident, row in rows.items():
                if not isinstance(row, dict):
                    continue
                for field in fields:
                    if contains(row.get(field)):
                        results.append(source + " #" + str(ident) + " · " + field)
                for field, index in tuple_fields:
                    if any(isinstance(pair, list) and len(pair) > index and isinstance(pair[index], (int, float)) and str(int(pair[index])) in removed for pair in row.get(field, []) or []):
                        results.append(source + " #" + str(ident) + " · " + field)
                if event_templates:
                    for field, commands in row.items():
                        if not isinstance(commands, list):
                            continue
                        for command in commands:
                            if not isinstance(command, list):
                                continue
                            for template in event_templates:
                                if len(command) != len(template.get("template", [])):
                                    continue
                                try:
                                    matches = all(float(command[int(index)]) == float(value) for index, value in template.get("match", {}).items())
                                    referenced = matches and any(p.get("range", {}).get("table") == target and str(int(command[p["index"]])) in removed for p in template.get("parameters", []))
                                except (ValueError, TypeError, IndexError, KeyError):
                                    referenced = False
                                if referenced:
                                    results.append(source + " #" + str(ident) + " · " + field)
                                    break
                if source == "TalkCfg" and target == "PersonCfg":
                    if any(isinstance(command, list) and command and contains(command[0]) for command in row.get("roles") or []):
                        results.append(source + " #" + str(ident) + " · roles")
                if source == "KZoneContentCfg" and target == "PersonCfg":
                    if any(isinstance(like, list) and like and contains(like[0]) for like in row.get("thumbs") or []):
                        results.append(source + " #" + str(ident) + " · thumbs")
                if source == "TalkCfg" and target == "CGCfg":
                    effect = row.get("screenEffect") or []
                    if isinstance(effect, list) and len(effect) >= 2 and effect[0] == 4015 and contains(effect[1]):
                        results.append(source + " #" + str(ident) + " · screenEffect")
                if len(results) >= 12:
                    return results
        return results

    def workshop_person_faces(self, project, incoming, previous, removed):
        """Let an edited static portrait replace only its existing default-expression override."""
        relative = "Cfgs/zh-cn/ModFaceCfg.json"
        local = read_json(safe_path(project.path, relative), {})
        revised = copy.deepcopy(local)
        all_faces = {**self.catalog_rows("ModFaceCfg"), **local}
        for ident, row in incoming.items():
            before = previous.get(ident, {})
            for url_field, model_field, icon_field in (("url", "l2d", "icon_xx"), ("url2", "l2d2", "icon")):
                if row.get(model_field) or url_field not in row:
                    continue
                urls, old_urls = row.get(url_field) or [], before.get(url_field) or []
                # For NPCs the native full portrait uses the first URL. Extra entries
                # are not a clothing index and must not alter other default faces.
                current, old_url = urls[0] if urls else "", old_urls[0] if old_urls else ""
                face_id = str(int(ident) * 1000)
                if current == old_url or face_id not in all_faces:
                    continue
                face = copy.deepcopy(revised.get(face_id, all_faces[face_id]))
                if face.get(icon_field):
                    face[icon_field] = ""
                    revised[face_id] = face
        revised = {key: row for key, row in revised.items() if not valid_id(key) or str(int(key) // 1000) not in removed}
        return {relative: json_bytes(revised)} if revised != local else {}

    def workshop_social_changes(self, project, name, incoming, previous, removed):
        """Validate game-required links and save new/deleted comments with their local owners."""
        if name not in {"KZoneContentCfg", "KZoneCommentCfg"}:
            return {}
        def local(table):
            return read_json(safe_path(project.path, "Cfgs/zh-cn/" + table + ".json"), {})
        people = {**self.catalog_rows("PersonCfg"), **local("PersonCfg")}
        post_local, comment_local = local("KZoneContentCfg"), local("KZoneCommentCfg")
        post_revised = copy.deepcopy(post_local)
        promoted = {}
        if name == "KZoneCommentCfg" and removed:
            for ident in removed:
                parent = previous[ident]
                for child in parent.get("comments") or []:
                    if isinstance(child, list) and child and str(child[0]) in incoming:
                        promoted[str(child[0])] = False
                for child in parent.get("options") or []:
                    if str(child) in incoming:
                        promoted[str(child)] = True
            for ident, row in incoming.items():
                if str(row.get("parent")) in removed:
                    promoted.setdefault(ident, False)
            for row in list(post_revised.values()) + list(incoming.values()):
                for field in ("comments", "options"):
                    if isinstance(row.get(field), list):
                        row[field] = [entry for entry in row[field] if str(entry[0] if isinstance(entry, list) and entry else entry) not in removed]
                if str(row.get("parent")) in removed:
                    row["parent"] = 0
        posts = {**self.catalog_rows("KZoneContentCfg"), **(incoming if name == "KZoneContentCfg" else post_local)}
        comments = {**self.catalog_rows("KZoneCommentCfg"), **(incoming if name == "KZoneCommentCfg" else comment_local)}
        def known(value, rows):
            return isinstance(value, int) and not isinstance(value, bool) and str(value) in rows
        for ident, row in incoming.items():
            if row == previous.get(ident):
                continue
            owner = int(ident) if name == "KZoneContentCfg" else int(ident) // 100
            if name == "KZoneCommentCfg":
                roles = row.get("roles")
                if roles != previous.get(ident, {}).get('roles') and (not isinstance(roles, list) or not roles or not known(roles[0], people) or any(role != -1 and not known(role, people) for role in roles[1:])):
                    raise ApiError("请为评论选择至少一个有效人物。")
                parent = row.get("parent", 0)
                if parent and (not known(parent, comments) or parent // 100 != owner or parent == int(ident)):
                    raise ApiError("回复的上级评论必须属于同一条动态，且不能是当前评论。")
            elif row.get("role") != previous.get(ident, {}).get("role") and not known(row.get("role"), people):
                raise ApiError("请为动态选择有效的发布人物。")
            for field, target in (("thumbs", people), ("comments", comments)):
                for entry in row.get(field) or []:
                    if not isinstance(entry, list) or not entry or not known(entry[0], target):
                        raise ApiError("点赞或评论中有未选择的项目，请选择人物/评论或删除空行。")
                    if field == "comments" and entry[0] // 100 != owner:
                        raise ApiError("请使用属于当前动态的评论。")
            for option in row.get("options") or []:
                if not known(option, comments) or option // 100 != owner:
                    raise ApiError("可选回复必须属于当前动态。")
        changes = {}
        if name == "KZoneContentCfg" and removed:
            kept = {key: row for key, row in comment_local.items() if str(int(key) // 100) not in removed}
            if kept != comment_local:
                changes["Cfgs/zh-cn/KZoneCommentCfg.json"] = json_bytes(kept)
        if name == "KZoneCommentCfg":
            for ident in (set(incoming) - set(previous)) | set(promoted):
                row = incoming[ident]
                parent = str(row.get("parent", 0))
                if parent != "0":
                    if parent not in incoming:
                        incoming[parent] = copy.deepcopy(comments[parent])
                    owner = incoming[parent]
                else:
                    post_id = str(int(ident) // 100)
                    if post_id not in post_revised:
                        post_revised[post_id] = copy.deepcopy(posts[post_id])
                    owner = post_revised[post_id]
                links = owner.get("comments") or []
                # A selectable reply must stay selectable; do not also publish it immediately.
                if int(ident) not in (owner.get("options") or []) and not any(isinstance(entry, list) and entry and entry[0] == int(ident) for entry in links):
                    if promoted.get(ident):
                        owner["options"] = (owner.get("options") or []) + [int(ident)]
                    else:
                        owner["comments"] = links + [[int(ident), 0]]
            if post_revised != post_local:
                changes["Cfgs/zh-cn/KZoneContentCfg.json"] = json_bytes(post_revised)
        return changes

    def table_save(self, payload):
        with self.lock:
            project = self.project(payload.get("projectId"), writable=True)
            name = self.table_name(payload.get("name"))
            revision = self.revision(project)
            if payload.get("revision") != revision:
                raise ApiError("配置已被其他窗口或游戏修改，请重新载入。", 409, "conflict")
            old = read_json(safe_path(project.path, "Cfgs/zh-cn/" + name + ".json"), {})
            inherited = self.catalog_rows(name)
            incoming = validate_map(payload.get("rows"), name, allow_zero="0" in old or "0" in inherited)
            incoming = self.preserve_editing_rows(project, name, incoming)
            previous = {**inherited, **old}
            self.validate_fields(name, incoming, previous)
            scope = payload.get("scope", "merged")
            if scope not in {"local", "merged"}:
                raise ApiError("编辑范围无效。")
            if scope == "local" and name == "TalkCfg" and payload.get("externalDialogues"):
                doc = self.load(project.id)
                owners = doc.get("talkOwners", {})
                for ident in set(old) | set(incoming):
                    if owners.get(ident) and incoming.get(ident) != old.get(ident):
                        raise ApiError("事件所属对话请在剧情编辑中修改。", 409)
                removed = set(old) - set(incoming)
                try: references = self.deletion_references(project, name, removed, {**inherited, **incoming}) if removed else []
                except ApiError: references = []
                result = self.save({'projectId':project.id, 'revision':revision,
                                    'talks':{**inherited, **incoming}, '_fullCatalogTable':'TalkCfg'})
                if references: result.setdefault('warnings', []).append("已删除仍被引用的对话，以下位置需要自行调整：" + "；".join(references))
                return result
            if scope == "local" and name == 'EvtCfg':
                return self.save({'projectId':project.id, 'revision':revision, 'events':{**inherited, **incoming}})
            if scope == "local":
                created_ids = set(incoming) - set(previous)
                if name in {"PersonGrowCfg", "KZoneProfileCfg"} and created_ids:
                    people = {**self.catalog_rows("PersonCfg"), **read_json(safe_path(project.path, "Cfgs/zh-cn/PersonCfg.json"), {})}
                    if any(key not in people for key in created_ids):
                        raise ApiError("成长设置和企鹅个人档需要关联已有的人物，请先选择人物。")
                if name == "KZoneCommentCfg" and created_ids:
                    posts = {**self.catalog_rows("KZoneContentCfg"), **read_json(safe_path(project.path, "Cfgs/zh-cn/KZoneContentCfg.json"), {})}
                    if any(str(int(key) // 100) not in posts or int(key) % 100 == 0 for key in created_ids):
                        raise ApiError("企鹅评论编号需要关联所属动态，请先选择动态再添加评论。")
                if name in {"TalkCfg", "OptionCfg"}:
                    raise ApiError("请通过剧情编辑管理对话和选项，以保留剧情连接。")
                # Omitted vanilla records were never part of the editing list. Removing a local
                # override restores its vanilla row; only missing custom IDs are actual deletions.
                removed = set(old) - set(incoming) - set(inherited)
                linked_changes = self.workshop_social_changes(project, name, incoming, previous, removed)
                proposed = {**inherited, **incoming}
                references = [] if name == "KZoneCommentCfg" else self.deletion_references(project, name, removed, proposed)
                if references:
                    raise ApiError("无法删除仍被引用的内容，请先调整以下位置：" + "；".join(references), 409, "referenced")
                revised = {key: {**old.get(key, {}), **copy.deepcopy(row)} for key, row in incoming.items()}
                changes = {"Cfgs/zh-cn/" + name + ".json": json_bytes(revised)}
                changes.update(linked_changes)
                if name == "PersonCfg":
                    changes.update(self.workshop_person_faces(project, revised, previous, removed))
                if name == "PersonCfg" and removed:
                    for child in ("PersonGrowCfg",):
                        relative = "Cfgs/zh-cn/" + child + ".json"
                        path = safe_path(project.path, relative)
                        children = read_json(path, {})
                        kept = {key: row for key, row in children.items() if not valid_id(key) or str(int(key) if child == "PersonGrowCfg" else int(key) // 1000) not in removed}
                        if kept != children:
                            changes[relative] = json_bytes(kept)
                backup = self.commit(project, changes, revision)
                return {"ok": True, "revision": self.revision(project), "backup": backup, "scope": "local", "rows": self.editing_rows(project, name),
                        "updatedTables": [Path(path).stem for path in changes]}
            removed = set(previous) - set(incoming)
            if name != "TalkCfg" and removed.intersection(inherited):
                raise ApiError("原版配置不能通过删除文件行停用。请修改其本地覆盖，或先移除使用该配置的引用。", 409, "base_row_delete")
            if name not in {"TalkCfg", "OptionCfg"}:
                references = self.deletion_references(project, name, removed, incoming)
                if references:
                    raise ApiError("无法删除仍被引用的配置，请先调整以下位置：" + "；".join(references), 409, "referenced")
            alias = next((key for key, filename in TABLES.items() if filename == name + ".json"), None)
            if alias:
                request = {"projectId": project.id, "revision": revision, alias: incoming, "_fullCatalogTable": name}
                for key in ("deletedIds", "replacements", "order", "branchFolders"):
                    if key in payload:
                        request[key] = payload[key]
                return self.save(request)
            revised = {}
            for key, row in incoming.items():
                if key not in old and inherited.get(key) == row:
                    continue
                revised[key] = {**old.get(key, {}), **copy.deepcopy(row)}
            backup = self.commit(project, {"Cfgs/zh-cn/" + name + ".json": json_bytes(revised)}, revision)
            return {"ok": True, "revision": self.revision(project), "backup": backup}

    def warehouse_save(self, payload):
        """Commit the warehouse's related native tables in one backed-up transaction."""
        with self.lock, self.catalog_scope():
            project = self.project(payload.get("projectId"), writable=True)
            revision = self.revision(project)
            if payload.get("revision") != revision:
                raise ApiError("模组已变化，请重新载入仓库。", 409, "conflict")
            incoming = payload.get("tables")
            if not isinstance(incoming, dict) or set(incoming) != {"ItemCfg", "BookCfg", "ShopCfg"}:
                raise ApiError("仓库配置不完整。")
            maps, unreadable = self.readable_maps(project)
            original = copy.deepcopy(maps)
            changes = {}
            for name, values in incoming.items():
                filename = name + ".json"
                if filename in unreadable:
                    raise unreadable[filename]
                old = maps.get(filename, {})
                inherited = self.catalog_rows(name)
                rows = validate_map(values, name, allow_zero="0" in old or "0" in inherited)
                rows = self.preserve_editing_rows(project, name, rows)
                self.validate_fields(name, rows, {**inherited, **old})
                maps[filename] = rows
            mappings = {}
            migrations = payload.get("migrations", [])
            if not isinstance(migrations, list):
                raise ApiError("物品类型迁移信息无效。")
            if migrations and unreadable:
                raise ApiError("有配置无法读取，暂时不能同步物品类型和引用。")
            for move in migrations:
                if not isinstance(move, dict) or move.get("fromTable") not in {"ItemCfg", "BookCfg"} or move.get("toTable") not in {"ItemCfg", "BookCfg"}:
                    raise ApiError("物品类型迁移信息无效。")
                before, after = str(move.get("oldId")), str(move.get("newId"))
                if before not in original.get(move['fromTable'] + '.json', {}) or before in maps[move['fromTable'] + '.json'] or after not in maps[move['toTable'] + '.json']:
                    raise ApiError("物品迁移的编号不匹配，请重新打开仓库。")
                for table in ("ItemCfg", "BookCfg"):
                    mappings.setdefault(table, {})[before] = int(after)
                if before in maps['ShopCfg.json']:
                    if after in maps['ShopCfg.json']:
                        raise ApiError("新物品编号已有商品，无法替换。")
                    product = maps[move['toTable'] + '.json'][after]
                    row = maps['ShopCfg.json'].pop(before)
                    maps['ShopCfg.json'][after] = {**row, 'id': int(after), 'type': 3 if move['toTable'] == 'BookCfg' else product.get('type', 1)}
            if mappings:
                for filename, rows in list(maps.items()):
                    maps[filename] = self.record_ids.rewrite(filename[:-5], rows, mappings)
                changes.update(self.record_ids.editor_changes(project, mappings))
            for name in incoming:
                filename = name + ".json"
                inherited = self.catalog_rows(name)
                removed = set(original.get(filename, {})) - set(maps[filename]) - set(inherited)
                refs = self.deletion_references(project, name, removed, {**inherited, **maps[filename]}, maps)
                if refs:
                    raise ApiError("无法删除仍被引用的物品：" + "；".join(refs), 409, "referenced")
                if maps[filename] != original.get(filename, {}):
                    changes["Cfgs/zh-cn/" + filename] = json_bytes(maps[filename])
            for filename, rows in maps.items():
                if rows != original.get(filename, {}):
                    changes['Cfgs/zh-cn/' + filename] = json_bytes(rows)
            products = {**self.catalog_rows("ItemCfg"), **maps["ItemCfg.json"], **self.catalog_rows("BookCfg"), **maps["BookCfg.json"]}
            for key, row in maps["ShopCfg.json"].items():
                if key not in products and row != original.get("ShopCfg.json", {}).get(key):
                    raise ApiError("商品需要选择已有物品或书籍。")
            backup = self.commit(project, changes, revision) if changes else None
            return {"ok": True, "revision": self.revision(project), "backup": backup,
                    "tables": {n: self.editing_rows(project,n) for n in incoming}}

    def manifest(self, project_id):
        with self.lock:
            project = self.project(project_id)
            return {"project": project.public(), "manifest": read_json(safe_path(project.path, "manifest.json"), {}), "revision": self.revision(project)}

    def manifest_save(self, payload):
        with self.lock:
            project = self.project(payload.get("projectId"), writable=True)
            revision = self.revision(project)
            if payload.get("revision") != revision:
                raise ApiError("模组说明已发生变化，请重新载入。", 409, "conflict")
            original = read_json(safe_path(project.path, "manifest.json"), {})
            incoming = payload.get("manifest")
            if not isinstance(incoming, dict):
                raise ApiError("模组说明必须为对象。")
            def merge(old, new):
                result = copy.deepcopy(old)
                for key, value in new.items():
                    if key.lower().replace("_", "") in {"apikey", "authorization", "password", "secret", "accesstoken"}:
                        raise ApiError("模组说明不接受密钥或认证字段。")
                    result[key] = merge(old.get(key, {}), value) if isinstance(value, dict) and isinstance(old.get(key, {}), dict) else copy.deepcopy(value)
                return result
            revised = merge(original, incoming)
            old_meta = original.get("metadata") or {}
            metadata = revised.get("metadata") or {}
            if not isinstance(metadata, dict) or metadata.get("packageId", project.package) != old_meta.get("packageId", project.package):
                raise ApiError("不能直接修改包标识，否则已有素材路径会失效；请使用制作副本。")
            if metadata.get("id", 0) != old_meta.get("id", 0):
                raise ApiError("工坊发布编号由游戏管理，不能在本地说明中修改。")
            revised["title"] = display_name(revised.get("title"), project.name)
            if revised.get("description") is not None and (not isinstance(revised["description"], str) or len(revised["description"]) > 20000):
                raise ApiError("模组说明最多 20000 个字符。")
            for field in ("tags", "dependencies"):
                if revised.get(field) is not None and not isinstance(revised[field], list):
                    raise ApiError(field + " 必须是列表。")
            backup = self.commit(project, {"manifest.json": json_bytes(revised)}, revision)
            return {"ok": True, "revision": self.revision(project), "backup": backup, "manifest": revised, "project": self.project(project.id).public()}

    def audio_cues(self, project, talks=None):
        data = read_json(safe_path(project.path, "StudentAgeStudio/audio-cues.json"), {})
        if not isinstance(data, dict):
            raise ApiError("声音设置不是有效对象。", 422)
        from native_audio import reconcile
        return reconcile({"version": 1, "sfx": {}, "bgm": [], **data},
                         talks if talks is not None else read_json(safe_path(project.path, "Cfgs/zh-cn/TalkCfg.json"), {}))

    def validate_audio_cues(self, data, all_maps, previous=None):
        if not isinstance(data, dict) or data.get("version", 1) != 1 or not isinstance(data.get("sfx", {}), dict) or not isinstance(data.get("bgm", []), list):
            raise ApiError("声音设置格式或版本无效。")
        result = {**copy.deepcopy(previous or {}), **copy.deepcopy(data), "version": 1}
        result.setdefault("sfx", {}); result.setdefault("bgm", [])
        audios = {**self.catalog_rows("AudioCfg"), **all_maps.get("AudioCfg.json", {})}
        talks = set(all_maps.get("TalkCfg.json", {})) | set(self.catalog_rows("TalkCfg"))
        talks.update(str(value) for value in self.catalog().get("baseTalkIds", []) if valid_id(value))
        def sound(cue):
            if not isinstance(cue, dict) or not valid_id(cue.get("audioId")) or str(cue["audioId"]) not in audios:
                raise ApiError("声音设置引用了不存在的音频，请重新选择。")
            volume = cue.get("volume", 1)
            if isinstance(volume, bool) or not isinstance(volume, (float, int)) or not math.isfinite(volume) or volume < 0 or volume > 1:
                raise ApiError("音量需要在 0 到 1 之间。")
        for ident, cues in result["sfx"].items():
            if not valid_id(ident) or str(ident) not in talks or not isinstance(cues, list) or len(cues) > 16:
                raise ApiError("句子音效引用无效或同一句音效过多。")
            for cue in cues: sound(cue)
        if "nativeAudio" in result:
            if not isinstance(result["nativeAudio"], dict): raise ApiError("原有背景音乐记录格式无效。")
            for ident, audio in result["nativeAudio"].items():
                if not valid_id(ident) or str(ident) not in talks: raise ApiError("原有背景音乐引用了不存在的对话。")
                sound({"audioId": audio})
        occupied = set(); groups = set()
        for group in result["bgm"]:
            sound(group)
            if not isinstance(group.get("id"), str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,120}", group["id"]) or group["id"] in groups:
                raise ApiError("背景音乐范围标识无效或重复。")
            groups.add(group["id"])
            if not isinstance(group.get("loop"), bool) or not isinstance(group.get("talkIds"), list):
                raise ApiError("请选择背景音乐的范围和循环方式。")
            ids = group["talkIds"]
            if any(not valid_id(ident) or str(ident) not in talks for ident in ids):
                raise ApiError("背景音乐范围包含不存在的对话。")
            ids = list(dict.fromkeys(int(ident) for ident in ids)); group["talkIds"] = ids
            if occupied.intersection(ids):
                raise ApiError("同一句不能属于两个背景音乐范围，请先替换原范围。")
            occupied.update(ids)
        return result

    JSON_SOURCE_LIMIT = 16 * 1024 * 1024

    def json_document_files(self, project):
        """All mod config JSON, including unsupported tables and other locales.

        Excludes resources, caches, editor history and backups; never follows links.
        """
        files = {}
        roots = [safe_path(project.path, 'Cfgs')]
        candidates = list(project.path.glob('*.json'))
        for root in roots:
            if not root.is_dir() or root.is_symlink(): continue
            for base, directories, names in os.walk(root, followlinks=False):
                base = Path(base)
                directories[:] = [name for name in directories if not (base/name).is_symlink()]
                candidates.extend(base/name for name in names if name.lower().endswith('.json'))
        for path in sorted(candidates):
            if path.is_symlink() or not path.is_file() or not inside(path, project.path): continue
            files[path.relative_to(project.path).as_posix()] = path
        return files

    def json_files(self, project_id):
        project = self.project(project_id)
        files = [{'path':relative,'name':relative,'size':path.stat().st_size,'table':path.stem,'config':relative.startswith('Cfgs/')}
                 for relative,path in self.json_document_files(project).items()]
        return {'files':files,'revision':self.revision(project),'readOnly':project.readonly}

    def json_source(self, payload):
        project = self.project(payload.get("projectId"))
        relative = str(payload.get("path") or "").replace("\\", "/")
        path = safe_path(project.path, relative)
        if not path.is_file() or path.suffix.lower() != ".json" or path.is_symlink():
            raise ApiError("没有找到这个 JSON 文件。", 404)
        if path.stat().st_size > self.JSON_SOURCE_LIMIT:
            raise ApiError("文件超过 16 MB，请用外部编辑器打开。", 413)
        data = path.read_bytes()
        bom = data.startswith(b"\xef\xbb\xbf")
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = data.decode("utf-8", errors="replace")
        return {"path": relative, "text": text, "bom": bom, "size": len(data), "revision": self.revision(project),
                "readOnly": project.readonly, "analysis": analyze_json_text(text)}

    def json_save(self, payload):
        with self.lock:
            project = self.project(payload.get("projectId"), writable=True)
            relative = str(payload.get("path") or "").replace("\\", "/")
            path = safe_path(project.path, relative)
            create = bool(payload.get("create")) and not path.exists() and bool(re.fullmatch(r"Cfgs/zh-cn/[A-Za-z][A-Za-z0-9_]*Cfg\.json", relative))
            if (not path.is_file() and not create) or path.suffix.lower() != ".json" or path.is_symlink():
                raise ApiError("没有找到这个 JSON 文件。", 404)
            text = payload.get("text")
            if not isinstance(text, str) or len(text.encode("utf-8")) > self.JSON_SOURCE_LIMIT:
                raise ApiError("文本无效或超过 16 MB。", 413)
            if text.startswith("\ufeff"):
                text = text[1:]
            analysis = analyze_json_text(text)
            if not analysis["valid"] and not payload.get("force"):
                raise ApiError("JSON 仍有语法错误，请先修复或选择仍然保存。", 422, "json_invalid")
            data = (b"\xef\xbb\xbf" if payload.get("bom") else b"") + text.encode("utf-8")
            backup = self.commit(project, {relative: data}, payload.get("revision"), raw=True)
            return {"ok": True, "path": relative, "revision": self.revision(project), "backup": backup, "analysis": analysis}

    def audio_files(self, project_id):
        project = self.project(project_id)
        root = safe_path(project.path, "Audios")
        files = []
        if root.is_dir():
            for base, directories, filenames in os.walk(root, followlinks=False):
                base = Path(base)
                directories[:] = [name for name in directories if not (base / name).is_symlink()]
                for name in filenames:
                    path = base / name
                    if path.is_symlink() or not inside(path, project.path) or path.suffix.lower() not in {".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac"}:
                        continue
                    relative = str(path.relative_to(project.path)).replace("\\", "/")
                    files.append({"path": relative, "name": path.name, "size": path.stat().st_size,
                                  "url": "Mods\\" + project.package + "\\" + relative.replace("/", "\\")})
                    if len(files) >= 10000:
                        break
                if len(files) >= 10000:
                    break
        local = read_json(safe_path(project.path, "Cfgs/zh-cn/AudioCfg.json"), {})
        rows = {**self.catalog_rows("AudioCfg"), **local}
        metadata = self.catalog().get("audioMetadata", {})
        audios = []
        for ident, row in rows.items():
            if not isinstance(row, dict): continue
            resource = str(row.get("url") or "")
            try:
                self.asset(project_id, resource); available = True
            except ApiError:
                available = False
            info = metadata.get(resource.replace("\\", "/").lower(), {})
            audios.append({"id": int(ident), "name": row.get("name") or resource or ("声音 " + ident), "type": row.get("type", 1),
                           "url": resource, "assetPath": resource, "available": available, "source": "local" if ident in local else "game",
                           "volume": row.get("volumn") or 1, **info})
        # AudioMgrEx.PlayBgm uses AudioCfg 4 outside an active game save.
        # Resolve it from the original catalogue, even if a mod overrides ID 4.
        default_bgm = self.catalog_rows("AudioCfg").get("4")
        default_bgm = ({"id": 4, "name": default_bgm.get("name", "开学季"), "url": default_bgm.get("url"),
                        "volume": default_bgm.get("volumn") or 1} if default_bgm and default_bgm.get("url") else None)
        return {"files": sorted(files, key=lambda item: item["path"]), "audios": audios, "defaultBgm": default_bgm,
                "audioCues": self.audio_cues(project), "revision": self.revision(project)}

    _audio_digests = {}

    def find_imported_audio(self, project, table, raw, kind):
        """Return (id, row) of a local AudioCfg row whose file has identical bytes and type."""
        digest = None
        for ident, row in table.items():
            if not isinstance(row, dict) or row.get("type", 1) != kind:
                continue
            url = str(row.get("url") or "").replace("\\", "/")
            parts = url.split("/", 2)
            if len(parts) < 3 or parts[0].lower() != "mods" or parts[1].casefold() not in {project.package.casefold(), project.path.name.casefold()}:
                continue
            try:
                path = safe_path(project.path, parts[2])
                stat = path.stat()
            except (ApiError, OSError):
                continue
            if not path.is_file() or stat.st_size != len(raw):
                continue
            key = (str(path), stat.st_size, stat.st_mtime_ns)
            known = self._audio_digests.get(key)
            if known is None:
                try:
                    known = hashlib.sha256(path.read_bytes()).hexdigest()
                except OSError:
                    continue
                if len(self._audio_digests) > 4096: self._audio_digests.clear()
                self._audio_digests[key] = known
            if digest is None: digest = hashlib.sha256(raw).hexdigest()
            if known == digest:
                try: return int(ident), row
                except ValueError: continue
        return None

    def audio_import(self, payload):
        with self.lock:
            project = self.project(payload.get("projectId"), writable=True)
            revision = self.revision(project)
            if payload.get("revision") != revision:
                raise ApiError("导入前模组已经变化，请重新载入。", 409, "conflict")
            raw, extension = decode_audio(payload)
            table = read_json(safe_path(project.path, "Cfgs/zh-cn/AudioCfg.json"), {})
            kind = payload.get("type", 1)
            if not isinstance(kind, int) or isinstance(kind, bool) or kind < 0 or kind > 128:
                raise ApiError("音频类型无效。")
            # Selecting the same sound again reuses the row already imported into
            # this mod instead of writing another studio_ file and a new ID.
            existing = self.find_imported_audio(project, table, raw, kind)
            if existing is not None:
                ident, row = existing
                relative = str(row.get("url") or "").replace("\\", "/")
                relative = relative.split("/", 2)[2] if relative.lower().startswith("mods/") and relative.count("/") >= 2 else relative
                return {"ok": True, "id": ident, "row": row, "assetPath": relative, "url": row.get("url"),
                        "revision": revision, "backup": None, "reused": True}
            inherited = self.catalog_rows("AudioCfg")
            occupied = set(table) | set(inherited)
            ident = self.record_ids.allocate('AudioCfg', {str(k): {} for k in occupied})
            if not valid_id(ident):
                raise ApiError("可用音频编号不足。")
            relative = "Audios/studio_" + time.strftime("%Y%m%d_%H%M%S") + "_" + secrets.token_hex(5) + extension
            resource_url = "Mods\\" + project.package + "\\" + relative.replace("/", "\\")
            row = {"id": ident, "name": display_name(payload.get("name"), Path(str(payload.get("fileName"))).stem),
                   "url": resource_url, "type": kind, "volumn": 0, "group": [], "cond": [], "disable": 0, "uiType": 0}
            table[str(ident)] = row
            backup = self.commit(project, {relative: raw, "Cfgs/zh-cn/AudioCfg.json": json_bytes(table)}, revision)
            return {"ok": True, "id": ident, "row": row, "assetPath": relative, "url": resource_url,
                    "revision": self.revision(project), "backup": backup}

    def asset(self, project_id, requested):
        project = self.project(project_id)
        return self.project_asset(project, requested)

    def mod_image_path(self, project, requested):
        """Resolve Unity-style image names without rescanning the asset library."""
        path = safe_path(project.path, requested)
        if path.is_file(): return path
        current = project.path
        parts = Path(str(requested).replace("\\", "/")).parts
        for index, part in enumerate(parts):
            exact = safe_path(current, part)
            if exact.exists(): current = exact; continue
            if not current.is_dir(): return path
            last = index == len(parts)-1
            matches = [entry for entry in current.iterdir() if entry.name.casefold() == part.casefold() or
                       (last and not Path(part).suffix and entry.suffix.lower() in {'.png','.jpg','.jpeg','.webp'} and entry.stem.casefold() == part.casefold())]
            if len(matches) != 1: return path
            current = matches[0]
            if not inside(current, project.path): raise ApiError("文件路径不能越过模组目录。", 403)
        return current

    def project_asset(self, project, requested):
        text = str(requested or "").replace("\\", "/")
        explicit_mod = text.lower().startswith("mods/")
        if explicit_mod:
            parts = text.split("/", 2)
            if len(parts) < 3 or parts[1].casefold() not in {project.package.casefold(), project.path.name.casefold()}:
                raise ApiError("图片不属于当前模组。", 404)
            text = parts[2]
        catalog = self.catalog()
        asset_map = catalog.get("assetMap", {})
        if not isinstance(asset_map, dict): asset_map = {}
        asset_key = text if text in asset_map else text.lower()
        audio_map = catalog.get("audioMap", {})
        if not isinstance(audio_map, dict): audio_map = {}
        audio_key = text if text in audio_map else text.lower()
        if explicit_mod:
            path = self.mod_image_path(project, text)
        elif re.fullmatch(r"portrait-cache/(?:[0-9]+|0-female)-[0-9]+-[0-9]+-[0-9]+\.png", text):
            female=Path(text).stem.startswith("0-female-")
            role, grade, cloth, face = map(int, Path(text).stem.replace("0-female-","0-").split("-"))
            if str(role) not in catalog.get("persons", {}) or face not in native_cache_faces(self.game, role, grade, cloth, **({"gender":2} if female else {})):
                raise ApiError("此人物表情尚未从原版游戏读取。", 404)
            path = safe_path(game_cache(self.game), text)
            # Native frame metadata describes these exact pixels, including padding.
            # A second alpha crop changes the model origin and must not be applied.
        elif isinstance(audio_map, dict) and audio_key in audio_map:
            path = safe_path(game_cache(self.game), audio_map[audio_key])
        elif asset_key in asset_map:
            exported = str(asset_map[asset_key]).replace("\\", "/")
            if exported.startswith("StudentAgeStudio/"):
                exported = exported[len("StudentAgeStudio/"):]
            path = safe_path(game_cache(self.game), exported)
        else:
            path = self.mod_image_path(project, text)
        suffix = path.suffix.lower()
        audio = suffix in {".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac"}
        if not path.is_file() or suffix not in {".png", ".jpg", ".jpeg", ".webp", ".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac"} or path.stat().st_size > (256 if audio else 72) * 1024 * 1024:
            raise ApiError("图片不存在或格式不支持；游戏内置 Live2D 需要在游戏版预览。", 404)
        return path

    def reuse_assets(self, project_id, kind):
        project = self.project(project_id)
        kind = 'portrait' if kind == 'person' else kind
        if kind not in {'background', 'cg', 'portrait', 'audio'}: raise ApiError('素材类型无效。')
        assets, warnings_list = [], []

        def rows(name):
            try:
                value = read_json(safe_path(project.path, 'Cfgs/zh-cn/' + name + '.json'), {})
                if not isinstance(value, dict): raise ApiError(name + ' 配置不是编号表。', 422)
                return {str(key): row for key, row in value.items() if (valid_id(key) or key == '0') and isinstance(row, dict)}
            except ApiError as error:
                warnings_list.append(error.message); return {}

        def label(value, fallback):
            return display_name(next((v for v in value if isinstance(v, str) and v), None) if isinstance(value, list) else value, fallback)

        def add(ident, name, resource, suffix='', **extra):
            if not isinstance(resource, str) or not resource.strip(): return
            item = {'assetId': kind + ':' + str(ident) + ':' + suffix, 'kind': kind, 'sourceId': int(ident),
                    'name': name, 'assetPath': resource, 'available': True, **extra}
            try:
                path = self.project_asset(project, resource)
                if kind == 'audio' and path.suffix.lower() not in {'.wav', '.mp3', '.ogg', '.flac', '.m4a', '.aac'}: raise ApiError('不是声音文件。')
                if kind != 'audio' and path.suffix.lower() not in {'.png', '.jpg', '.jpeg', '.webp'}: raise ApiError('此资源不是可导入的静态图片。')
            except ApiError as error:
                item.update(available=False, message=error.message)
            assets.append(item)

        if kind in {'background', 'cg', 'audio'}:
            table = {'background': 'BgCfg', 'cg': 'CGCfg', 'audio': 'AudioCfg'}[kind]
            local = rows(table)
            names = {**self.catalog_rows(table), **local}
            for ident, row in local.items():
                name = asset_name(row, kind, names)
                resources = row.get('urls') if kind == 'cg' else [row.get('url')]
                if isinstance(resources, str): resources = [resources]
                for index, resource in enumerate(resources or []):
                    add(ident, name + (' · ' + str(index + 1) if kind == 'cg' and len(resources) > 1 else ''), resource, str(index),
                        sourceIndex=index, **({'type': row.get('type', 1)} if kind == 'audio' else {}))
        else:
            persons, faces = rows('PersonCfg'), rows('ModFaceCfg')
            person_ids = set(persons) | {str(int(key) // 1000) for key in faces}
            original = self.catalog_rows('PersonCfg')
            for ident in sorted(person_ids, key=int):
                row = persons.get(ident, original.get(ident, {}))
                name = asset_name(row, 'portrait', original)
                for grade, field, icon in ((1, 'url', 'icon_xx'), (2, 'url2', 'icon')):
                    urls = row.get(field) or []
                    if isinstance(urls, str): urls = [urls]
                    variants = {(index, 0): value for index, value in enumerate(urls) if ident in persons}
                    for face_id, face in faces.items():
                        if int(face_id) // 1000 != int(ident): continue
                        cloth, expression = (int(face_id) % 1000) // 100, int(face_id) % 100
                        if face.get(icon): variants[(cloth, expression)] = face[icon]
                    for (cloth, expression), resource in sorted(variants.items()):
                        face = faces.get(str(int(ident) * 1000 + cloth * 100 + expression), {})
                        face_name = label(face.get('name'), '默认表情' if expression == 0 else '表情 ' + str(expression))
                        add(ident, name + ' · ' + ('小学' if grade == 1 else '中学') + ' · ' + face_name, resource,
                            str(grade) + ':' + str(cloth) + ':' + str(expression), sourceGrade=grade, sourceCloth=cloth, sourceFace=expression,
                            personName=name, faceName=face_name)
        return {'project': project.public(), 'assets': assets, 'warnings': warnings_list}

    def reuse_asset(self, payload):
        with self.lock:
            target = self.project(payload.get('projectId', payload.get('targetProjectId')), writable=True)
            if payload.get('revision') != self.revision(target): raise ApiError('目标模组已变化，请保存并重新载入后再沿用素材。', 409, 'conflict')
            source = self.project(payload.get('sourceProjectId'))
            kind = 'portrait' if payload.get('kind') == 'person' else payload.get('kind')
            choices = self.reuse_assets(source.id, kind)['assets']
            chosen = next((row for row in choices if row['assetId'] == payload.get('assetId')), None)
            if chosen is None: raise ApiError('源模组中已找不到这项素材，请刷新素材列表。', 404)
            if not chosen['available']: raise ApiError(chosen.get('message') or '此素材无法读取。', 422)
            path = self.project_asset(source, chosen['assetPath'])
            name = display_name(payload.get('name'), chosen.get('personName', chosen['name']) if kind == 'portrait' else chosen['name'])
            data = {'projectId': target.id, 'revision': payload['revision'], 'kind': kind, 'name': name,
                    'fileName': path.name, 'data': base64.b64encode(path.read_bytes()).decode('ascii')}
            if kind == 'audio':
                data['type'] = chosen.get('type', 1)
                result = self.audio_import(data)
            else:
                if kind == 'portrait':
                    data.update(personId=payload.get('personId'), grade=payload.get('grade', chosen.get('sourceGrade', 1)),
                                cloth=payload.get('cloth', chosen.get('sourceCloth', 0)), faceId=payload.get('faceId', chosen.get('sourceFace', 0)))
                result = self.import_image(data)
            result.update(kind=kind, name=name, sourceProjectId=source.id, sourceAssetId=chosen['assetId'])
            return result

    def import_field_image(self, payload):
        """Import a real image without registering an unrelated character, background or CG."""
        with self.lock:
            project = self.project(payload.get("projectId"), writable=True)
            revision = self.revision(project)
            if payload.get("revision") != revision:
                raise ApiError("模组已被其他窗口或游戏修改，请重新载入。", 409, "conflict")
            encoded = payload.get("data", "")
            if not isinstance(encoded, str) or len(encoded) > (MAX_IMAGE + 2) // 3 * 4 + 128:
                raise ApiError("图片超过大小限制。", 413)
            if encoded.startswith("data:"):
                if ";base64," not in encoded:
                    raise ApiError("图片编码无效。")
                encoded = encoded.split(";base64,", 1)[1]
            try:
                raw = base64.b64decode(encoded, validate=True)
            except (ValueError, TypeError):
                raise ApiError("图片编码无效。")
            converted, extension, width, height = normalize_image(raw)
            filename = "image_" + time.strftime("%Y%m%d_%H%M%S") + "_" + secrets.token_hex(7) + extension
            relative = "Textures/Workshop/" + filename
            backup = self.commit(project, {relative: converted}, revision)
            return {"ok": True, "projectId": project.id, "revision": self.revision(project), "assetPath": relative,
                    "url": "Mods\\" + project.package + "\\" + relative.replace("/", "\\"), "width": width, "height": height, "backup": backup}

    def import_image(self, payload):
        with self.lock:
            project = self.project(payload.get("projectId"), writable=True)
            revision = self.revision(project)
            if payload.get("revision") is not None and payload["revision"] != revision:
                raise ApiError("导入前模组已发生变化，请先重新载入。", 409, "conflict")
            image_limit = MAX_IMAGE
            if payload.get("data"):
                encoded = payload["data"]
                if not isinstance(encoded, str) or len(encoded) > (MAX_IMAGE + 2) // 3 * 4 + 128:
                    raise ApiError("导入图片超过 24 MB。", 413)
                if encoded.startswith("data:"):
                    encoded = encoded.split(",", 1)[-1]
                try:
                    raw = base64.b64decode(encoded, validate=True)
                except ValueError:
                    raise ApiError("图片编码无效。")
            elif payload.get("assetPath"):
                source = self.asset(project.id, payload["assetPath"])
                if not inside(source, project.path):
                    raise ApiError("请上传要导入的图片。")
                raw = source.read_bytes()
                image_limit = 72 * 1024 * 1024
            else:
                raise ApiError("请选择图片文件。")
            converted, extension, width, height = normalize_image(raw, image_limit)
            kind = normalize_kind(payload.get("kind"))
            name = display_name(payload.get("name"), {"cg": "新 CG", "portrait": "新立绘", "background": "新场景"}[kind])
            filename = "studio_" + time.strftime("%Y%m%d_%H%M%S") + "_" + secrets.token_hex(5) + extension
            relative = "Textures/" + {"cg": "CG", "portrait": "Role", "background": "Bg"}[kind] + "/" + filename
            resource_url = "Mods\\" + project.package + "\\" + relative.replace("/", "\\")
            changes = {relative: converted}
            result = {"projectId": project.id, "kind": kind, "assetPath": relative, "url": resource_url, "width": width, "height": height}
            catalog = self.catalog()

            def local_map(table):
                return read_json(safe_path(project.path, "Cfgs/zh-cn/" + TABLES[table]), {})

            if kind == "portrait":
                persons, faces = local_map("persons"), local_map("faces")
                person_id = payload.get("personId")
                if person_id is None or person_id == "":
                    occupied_persons = {**catalog.get("persons", {}), **{str(int(key) // 1000): {} for key in {**catalog.get("faces", {}), **faces} if str(key).isdigit()}}
                    person_id = self.record_ids.allocate('PersonCfg', {**occupied_persons, **persons})
                elif not valid_id(person_id) and not (person_id in (0, '0') and not isinstance(person_id, bool)
                                                       and ('0' in persons or '0' in catalog.get('persons', {}))):
                    raise ApiError("请选择已有的有效人物，或选择新建人物。")
                person_id = int(person_id)
                face, cloth = int(payload.get("faceId") or 0), int(payload.get("cloth") or 0)
                grade = int(payload.get("grade") or 1)
                if face < 0 or face > 99 or cloth < 0 or cloth > 9 or grade not in (1, 2, 3):
                    raise ApiError("表情、服装或学段编号无效。")
                face_id = person_id * 1000 + cloth * 100 + face
                if not valid_id(face_id) and not (person_id == 0 and face_id == 0):
                    raise ApiError("人物编号过大，无法创建兼容的表情编号。")
                inherited = catalog.get("persons", {}).get(str(person_id), {})
                person = copy.deepcopy(persons.get(str(person_id), inherited))
                if not person:
                    gender = payload.get("gender", 2)
                    if isinstance(gender, bool) or gender not in (0, 1, 2): raise ApiError("人物性别无效。")
                    person = {"id": person_id, "name": name, "gender": gender, "init": [0], "birthday": [], "url": [], "url2": [],
                              "urlParm": [0, 0, 1], "urlParm2": [0, 0, 1], "l2d": [], "l2d2": [], "l2dParm": [], "l2dParm2": [],
                              "bubbleParm": [900], "bubbleParm2": [900], "nicknames": []}
                url_field, model_field, parm_field = ("url", "l2d", "urlParm") if grade == 1 else ("url2", "l2d2", "urlParm2")
                urls = person.get(url_field) or []
                if not isinstance(urls, list):
                    urls = []
                urls = list(urls)
                while len(urls) <= cloth:
                    urls.append(resource_url)
                if face == 0 or not urls[cloth]:
                    urls[cloth] = resource_url
                person[url_field] = urls
                person[model_field] = []
                if not person.get(parm_field):
                    person[parm_field] = [0, 0, 1]
                persons[str(person_id)] = person
                face_row = copy.deepcopy(faces.get(str(face_id), catalog.get("faces", {}).get(str(face_id), {"id": face_id, "name": name, "icon": "", "icon_xx": "", "photobooth": None})))
                face_row["icon_xx" if grade == 1 else "icon"] = resource_url
                face_row["name"] = name
                faces[str(face_id)] = face_row
                changes["Cfgs/zh-cn/PersonCfg.json"] = json_bytes(persons)
                changes["Cfgs/zh-cn/ModFaceCfg.json"] = json_bytes(faces)
                result.update({"id": face_id, "personId": person_id, "row": face_row, "persons": {str(person_id): person}, "faces": {str(face_id): face_row}})
            else:
                table = "cgs" if kind == "cg" else "backgrounds"
                rows = local_map(table)
                ident = self.record_ids.allocate(TABLES[table][:-5], rows)
                row = ({"id": ident, "name": name, "urls": [resource_url], "group": 3, "gender": 0, "comic": [], "idx": 0, "move": [], "startTalks": []}
                       if kind == "cg" else {"id": ident, "name": name, "url": resource_url, "audio": 0, "cloth": [], "gaozhongCond": [], "gaozhongUrl": 0})
                rows[str(ident)] = row
                changes["Cfgs/zh-cn/" + TABLES[table]] = json_bytes(rows)
                result.update({"id": ident, "row": row})
                if kind == "cg" and isinstance(payload.get("_assetAssociation"), dict):
                    self.asset_catalog.add_association(changes, project, ident, payload["_assetAssociation"])
            result["backup"] = self.commit(project, changes, revision)
            result["revision"] = self.revision(project)
            return result



def decode_audio(payload):
    extension = Path(str(payload.get("fileName") or "")).suffix.lower()
    encoded = payload.get("data")
    if extension not in {".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac"} or not isinstance(encoded, str):
        raise ApiError("请选择 MP3、WAV、OGG、FLAC、M4A 或 AAC 音频。")
    if len(encoded) > 64 * 1024 * 1024 + 128:
        raise ApiError("上传音频不能超过 48 MB。", 413)
    if encoded.startswith("data:"):
        encoded = encoded.split(",", 1)[-1]
    try:
        raw = base64.b64decode(encoded, validate=True)
    except ValueError:
        raise ApiError("音频编码无效。")
    if not raw or len(raw) > 48 * 1024 * 1024:
        raise ApiError("上传音频为空或超过 48 MB。", 413)
    signatures = {".wav": len(raw) >= 12 and raw[:4] in (b"RIFF", b"RF64") and raw[8:12] == b"WAVE",
                  ".ogg": raw.startswith(b"OggS"), ".flac": raw.startswith(b"fLaC"),
                  ".mp3": raw.startswith(b"ID3") or len(raw) >= 4 and raw[0] == 255 and raw[1] & 224 == 224 and raw[1] & 6 != 0,
                  ".aac": len(raw) >= 4 and raw[0] == 255 and raw[1] & 246 == 240,
                  ".m4a": len(raw) >= 12 and raw[4:8] == b"ftyp"}
    if not signatures[extension]:
        raise ApiError("文件内容与音频格式不符，请使用完整的音频文件。")
    if extension in {".m4a", ".aac", ".flac"}:
        converter = shutil.which("afconvert")
        ffmpeg = None
        if not converter and os.name == "nt":
            try:
                import imageio_ffmpeg
                ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
            except ImportError: pass
        if not converter and not ffmpeg:
            raise ApiError("游戏不能直接读取此格式，请先转换为 WAV 或 MP3。")
        with tempfile.TemporaryDirectory(prefix="student-age-audio-") as temporary:
            source = Path(temporary) / ("source" + extension); destination = Path(temporary) / "converted.wav"
            source.write_bytes(raw)
            command = [converter, "-f", "WAVE", "-d", "LEI16", str(source), str(destination)] if converter else [ffmpeg,"-nostdin","-v","error","-i",str(source),"-acodec","pcm_s16le",str(destination)]
            process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **process_options())
            started = time.monotonic()
            try:
                while process.poll() is None:
                    if time.monotonic() - started > 45 or destination.exists() and destination.stat().st_size > 128 * 1024 * 1024:
                        process.kill(); raise ApiError("转换后的音频过长，请剪短后重试。")
                    time.sleep(.05)
                if process.returncode != 0 or not destination.is_file(): raise ApiError("无法解码这个音频，请转换为完整 WAV 或 MP3。")
                raw = destination.read_bytes(); extension = ".wav"
            finally:
                if process.poll() is None: process.kill()
                process.wait()
    if extension == ".wav":
        import wave
        try:
            with wave.open(io.BytesIO(raw), "rb") as decoded:
                if decoded.getnchannels() <= 0 or decoded.getnframes() <= 0 or decoded.getframerate() <= 0: raise ValueError()
                if len(decoded.readframes(decoded.getnframes())) < decoded.getnframes() * decoded.getnchannels() * decoded.getsampwidth(): raise ValueError()
        except (wave.Error, EOFError, ValueError):
            raise ApiError("WAV 音频不完整或无法解码。")
    return raw, extension

def normalize_kind(value):
    mapping = {0: "cg", 1: "portrait", 2: "background", "0": "cg", "1": "portrait", "2": "background",
               "cg": "cg", "portrait": "portrait", "background": "background", "CG": "cg"}
    try:
        return mapping[value]
    except (KeyError, TypeError):
        raise ApiError("素材类型无效。")


def normalize_image(raw, maximum=MAX_IMAGE):
    if not raw or len(raw) > maximum:
        raise ApiError("图片为空或超过 24 MB。", 413)
    if Image is None:
        # Refuse to write an unverified header-only image. The desktop package uses the bundled Pillow runtime.
        raise ApiError("当前 Python 缺少图片解码组件 Pillow，请使用桌面应用启动。", 503)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as source:
                if source.format not in ("PNG", "JPEG", "WEBP") or source.width > MAX_DIMENSION or source.height > MAX_DIMENSION or source.width * source.height > MAX_PIXELS:
                    raise ApiError("请使用不超过 4096 边长的 PNG、JPEG 或 WebP 图片。")
                source.verify()
            with Image.open(io.BytesIO(raw)) as source:
                source.load()
                width, height = source.size
                clean = source.convert("RGBA" if "A" in source.getbands() or "transparency" in source.info else "RGB")
                clean.info.clear()
                output = io.BytesIO()
                clean.save(output, format="PNG")
                clean.close()
                return output.getvalue(), ".png", width, height
    except ApiError:
        raise
    except Exception:
        raise ApiError("图片无法解码，请选择完整的 PNG、JPEG 或 WebP 文件。", 422)




class ResourceJobs:
    """Run the installed local bundle reader in a separate process, keeping the editing UI responsive."""
    def __init__(self, store, script):
        self.store, self.script = store, Path(script)
        self.audio = self.script.name == "extract_audio_assets.py"
        self.lock = threading.Lock()
        self.state = {"status": "idle", "message": "可读取已安装游戏的原版素材。", "progress": None}

    def get(self):
        catalog = self.store.catalog()
        mapping = catalog.get("audioMap" if self.audio else "assetMap", {})
        if not isinstance(mapping, dict):
            mapping = {}
        with self.lock:
            result = copy.deepcopy(self.state)
        result.update({"available": bool(mapping), "resourceKeys": len(mapping), "images": len(set(mapping.values())),
                       "bundles": len(catalog.get("audioBundles" if self.audio else "bundles", {})), "failures": len(catalog.get("audioFailures" if self.audio else "failures", [])),
                       "canRefresh": self.script.is_file(), "schemaAvailable": bool(catalog.get("schemas"))})
        return result

    def start(self):
        if not self.script.is_file():
            raise ApiError("本地资源读取组件缺失，请重新安装独立版应用。", 503)
        if not self.store.game.is_dir():
            raise ApiError("找不到已安装的游戏目录。", 404)
        with self.lock:
            if self.state["status"] == "running":
                raise ApiError("素材正在刷新，请稍候。", 409, "busy")
            self.state = {"status": "running", "message": "正在读取本机游戏资源…", "progress": None}
        threading.Thread(target=self.run, daemon=True).start()
        return self.get()

    def run(self):
        process, timer, lock_file = None, None, None
        timed_out = threading.Event()
        try:
            root = game_cache(self.store.game)
            root.mkdir(parents=True, exist_ok=True)
            lock_file = safe_path(root, ".audio-refresh.lock" if self.audio else ".resource-refresh.lock").open("a+b")
            try:
                lock_file_acquire(lock_file, blocking=False)
            except BlockingIOError:
                raise ApiError("另一个窗口正在刷新素材，请稍候再试。", 409)
            process = subprocess.Popen(worker_command(self.script, self.store.game),
                                       stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf-8", **process_options())
            def stop_after_timeout():
                timed_out.set()
                if process.poll() is None:
                    process.kill()
            timer = threading.Timer(1200, stop_after_timeout)
            timer.daemon = True
            timer.start()
            final = None
            for line in process.stdout:
                if len(line) > 32768:
                    continue
                try:
                    value = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(value, dict):
                    continue
                if "bundle" in value:
                    with self.lock:
                        self.state["progress"] = {key: value.get(key) for key in ("bundle", "total", "exported", "fraction", "item", "items")}
                        self.state["message"] = "正在读取原版素材包 " + str(value.get("bundle", "")) + " / " + str(value.get("total", "")) + "…"
                        if self.audio and value.get("items"):
                            self.state["message"] += " 音频 " + str(value.get("item",0)) + " / " + str(value["items"])
                if "resourceKeys" in value:
                    final = {key: value.get(key) for key in ("exported", "resourceKeys", "failures")}
            code = process.wait()
            if code != 0 or timed_out.is_set():
                raise ApiError("资源刷新超时，请稍后重试。" if timed_out.is_set() else "资源读取失败，请检查游戏文件与本地素材读取组件。", 503)
            if final and not final.get("resourceKeys"):
                raise ApiError("没有读出可用素材，请检查游戏文件或本地解码组件后重新读取。",503)
            message = "原版音频已刷新，可试听并应用到对话。" if self.audio else "原版素材已刷新，可继续预览场景与人物。"
            if final and final.get("failures"):
                message = "部分素材已读取，仍有 " + str(final["failures"]) + " 项未能读取，可重新读取重试。"
            with self.lock:
                self.state.update(status="complete", message=message, result=final)
        except ApiError as exc:
            diagnostic = ErrorLogs().response(exc, exc.message, exc.code, '后台素材读取：' + self.script.name)
            with self.lock:
                self.state.update(status="error", message=diagnostic['error'], errorLog=diagnostic['errorLog'])
        except Exception as exc:
            diagnostic = ErrorLogs().response(exc, "资源刷新未完成，请检查游戏目录与读取组件。", 'internal_error', '后台素材读取：' + self.script.name)
            with self.lock:
                self.state.update(status="error", message=diagnostic['error'], errorLog=diagnostic['errorLog'])
        finally:
            if timer is not None:
                timer.cancel()
            if process is not None:
                if process.poll() is None:
                    process.kill()
                    process.wait()
                if process.stdout:
                    process.stdout.close()
            if lock_file is not None:
                lock_file.close()


class StudioServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 64
    allow_reuse_address = False

    def __init__(self, address, store, web_root=None, locations=None):
        super().__init__(address, StudioHandler)
        self.locations = locations
        self.error_logs = ErrorLogs()
        self.location_lock = threading.RLock()
        self.display_lock = threading.RLock()
        self.display_path = Path(os.environ.get('STUDIO_DISPLAY_SETTINGS') or settings_path().with_name('display-settings.json'))
        self.condition_presets = UserConditionPresets(self.display_path.with_name('condition-presets.json'), sys.modules[__name__])
        self.store = store
        self.token = secrets.token_urlsafe(32)
        self.web_root = Path(web_root or Path(__file__).parent).resolve()
        self.resources = ResourceJobs(store, self.web_root / "extract_game_assets.py")
        self.audio_resources = ResourceJobs(store, self.web_root / "extract_audio_assets.py")
        self.store.asset_catalog.request_resources = self.request_asset_resources
        self.origin = "http://127.0.0.1:" + str(self.server_port)
        self.startup = StartupPreparation(self)
        self.media_warmup = MediaWarmup(self)
        from app_updates import AppUpdates
        from error_logs import APP_VERSION
        self.updates = AppUpdates(self.web_root, APP_VERSION)
        self.update_restart_requested = False
        self.request_update_restart = self.restart_for_update

    def restart_for_update(self):
        self.update_restart_requested = True
        threading.Thread(target=self.shutdown, daemon=True).start()


    def display_settings(self, payload=None):
        # Persist outside mods; each delta is applied to the latest saved choices.
        with self.display_lock:
            definitions = read_json(Path(__file__).with_name('workshop-features.json'), [])
            eligible = {r['id'] for r in definitions if r.get('native') is not False and not r.get('resourceOnly')}
            defaults = [r['id'] for r in sorted(definitions, key=lambda r: r.get('favoriteOrder', 100)) if r.get('defaultFavorite') and r['id'] in eligible]
            try:
                from user_preferences import load
                saved = load(self.display_path)
            except (OSError, ValueError) as error:
                raise ApiError('无法读取用户设置，原文件已保留：' + str(error), 500, 'settings_unreadable')
            favorites = saved.get('workshopFavorites', defaults)
            if not isinstance(favorites, list): favorites = defaults
            favorites = list(dict.fromkeys(v for v in favorites if isinstance(v, str) and v in eligible))
            if payload is not None:
                if not isinstance(payload, dict) or not any(key in payload for key in ('showRecordIds', 'autoSave', 'saveOnExit', 'onboardingComplete', 'favoriteFeature', 'theme', 'idCheckExcludedProjects')):
                    raise ApiError('请选择要修改的显示、保存或收藏设置。')
                for key in ('showRecordIds', 'autoSave', 'saveOnExit', 'onboardingComplete'):
                    if key in payload and type(payload[key]) is not bool:
                        raise ApiError('保存设置必须为开启或关闭。')
                if 'idCheckExcludedProjects' in payload:
                    value = payload['idCheckExcludedProjects']
                    if not isinstance(value, list) or len(value) > 1000 or any(not isinstance(v, str) or len(v) > 512 for v in value):
                        raise ApiError('请选择要排除的模组。')
                    saved['idCheckExcludedProjects'] = list(dict.fromkeys(value))
                if 'theme' in payload:
                    if payload['theme'] not in ('classic', 'glass', 'glass-dusk', 'glass-moon'): raise ApiError('请选择经典主题或液态玻璃。')
                    saved['theme'] = payload['theme']
                if 'favoriteFeature' in payload:
                    change = payload['favoriteFeature']
                    if not isinstance(change, dict) or not isinstance(change.get('id'), str) or change['id'] not in eligible or type(change.get('enabled')) is not bool:
                        raise ApiError('此功能不能收藏。')
                    favorites = [v for v in favorites if v != change['id']]
                    if change['enabled']: favorites.append(change['id'])
                    saved['workshopFavorites'] = favorites
                for key in ('showRecordIds', 'autoSave', 'saveOnExit', 'onboardingComplete'):
                    if key in payload: saved[key] = payload[key]
                self.display_path.parent.mkdir(parents=True, exist_ok=True)
                atomic_write(self.display_path, json_bytes(saved))
            return {'idCheckExcludedProjects': saved.get('idCheckExcludedProjects', []), 'theme': saved.get('theme') if saved.get('theme') in ('classic', 'glass', 'glass-dusk', 'glass-moon') else 'glass', 'showRecordIds': saved.get('showRecordIds') is not False, 'autoSave': saved.get('autoSave') is True, 'workshopFavorites': favorites, 'saveOnExit': saved.get('saveOnExit', saved.get('autoSave',False)) is True, 'onboardingComplete': saved.get('onboardingComplete') is True}

    def server_close(self):
        if hasattr(self, 'media_warmup'): self.media_warmup.close()
        super().server_close()

    def cache_settings(self, payload=None):
        from storage_paths import cache_root, saved_cache_path
        from user_preferences import load
        import tempfile
        with self.display_lock:
            saved = load(self.display_path)
            previous = saved.get('cachePath', '')
            active = cache_root()
            if payload is not None:
                value = payload.get('path')
                if not isinstance(value, str) or not value.strip():
                    raise ApiError('缓存路径必须设置，请选择专用的缓存文件夹。')
                target = Path(value.strip()).expanduser()
                if not target.is_absolute(): raise ApiError('请填写缓存文件夹的完整路径。')
                target = target.resolve()
                if target == self.display_path.resolve().parent or target in self.display_path.resolve().parents:
                    raise ApiError('请选择单独的缓存文件夹，不要直接使用用户配置目录或磁盘根目录。')
                try:
                    target.mkdir(parents=True, exist_ok=True)
                    with tempfile.TemporaryFile(dir=target) as probe: probe.write(b'cache-path-check'); probe.flush()
                except OSError as error:
                    raise ApiError('缓存目录无法写入，请检查磁盘和权限：' + str(error))
                # Only first-time setup before preparation can switch in place.
                # Later changes are saved without touching current drafts/workers.
                activate = self.startup.get()['status'] == 'idle' and self.resources.state['status'] != 'running' and self.audio_resources.state['status'] != 'running'
                old_override = os.environ.get('STUDIO_CACHE_ROOT')
                saved['cachePath'] = str(target)
                self.display_path.parent.mkdir(parents=True, exist_ok=True)
                if activate:
                    old_store = self.store
                    try:
                        os.environ['STUDIO_CACHE_ROOT'] = str(target)
                        self.use_location({'mods': str(old_store.mods), 'workshop': str(old_store.workshop),
                                           'game': str(old_store.game), 'extraMods': list(map(str, old_store.extra_mods))}, migrate_cache=False)
                        atomic_write(self.display_path, json_bytes(saved))
                    except Exception:
                        self.store = old_store
                        self.resources = ResourceJobs(old_store, self.web_root/'extract_game_assets.py')
                        self.audio_resources = ResourceJobs(old_store, self.web_root/'extract_audio_assets.py')
                        if old_override is None: os.environ.pop('STUDIO_CACHE_ROOT', None)
                        else: os.environ['STUDIO_CACHE_ROOT'] = old_override
                        raise
                else:
                    # Pin the old root before committing the preference.
                    os.environ['STUDIO_CACHE_ROOT'] = str(active)
                    atomic_write(self.display_path, json_bytes(saved))
                saved_cache_path.cache_clear()
                previous = str(target)
            path = str(previous or '')
            error = ''
            if path:
                try:
                    with tempfile.TemporaryFile(dir=path) as probe: probe.write(b'check'); probe.flush()
                except OSError:
                    error = '已设置的缓存目录暂时不可用，请连接对应磁盘或重新选择。'
            return {'path': path, 'activePath': str(cache_root()), 'suggestedPath': str(active),
                    'required': not bool(path) or bool(error), 'error': error,
                    'restartRequired': bool(path) and Path(path) != cache_root()}

    def request_asset_resources(self, kind):
        jobs = self.audio_resources if kind == "audio" else self.resources
        state = jobs.get()
        if state["status"] == "idle":
            try: return jobs.start()
            except ApiError as error:
                if error.code != "busy": raise
                return jobs.get()
        return state

    def location_state(self):
        state = self.locations.state() if self.locations else {"managed": False, "active": {"game": str(self.store.game), "mods": str(self.store.mods)}}
        state['backups'] = self.store.backups.status()
        state['errorLogs'] = self.error_logs.status()
        from storage_paths import storage_info
        state['storage'] = storage_info(self.store.game)
        state['needsPreparation'] = bool(state.get('active')) and not self.store.catalog_prepared()
        root, exists, readable = self.store.mods, False, True
        try:
            exists = root.is_dir()
            if exists and not is_workshop_path(root, self.store.workshop): next(root.iterdir(), None)
        except OSError: readable = False
        projects = self.store.projects()
        count = sum(not project.readonly for project in projects)
        message = ('已找到 ' + str(count) + ' 个自己的本地开发模组。' +
                   ('新建模组目录尚不存在，首次新建时会自动建立。' if not exists else
                    '主开发目录无法读取，请检查访问权限。' if not readable else '') if count else
                   '此目录无法读取，请检查文件夹访问权限或手动选择开发目录。' if not readable else
                   '本地开发目录尚不存在；可在游戏内创建模组，或手动选择自己的模组文件夹。' if not exists else
                   '此目录没有本地开发模组，可手动选择自己的 Mods 目录或单个模组。')
        state['modsStatus'] = {'path': str(root), 'exists': exists, 'readable': readable, 'projectCount': count,
                               'extraProjects': [str(p) for p in self.store.extra_mods], 'message': message}
        count = sum(project.readonly for project in projects)
        state['workshopStatus'] = {'path': str(self.store.workshop), 'exists': self.store.workshop.is_dir(), 'projectCount': count,
                                  'message': '已找到 ' + str(count) + ' 个订阅模组，可浏览或复制为本地副本。' if count else '此游戏目录未发现已下载的订阅模组。'}
        return state

    def require_location_idle(self):
        if not self.locations: raise ApiError("此窗口使用指定目录，请重新打开应用以切换目录。", 409)
        if self.resources.get()['status'] == 'running' or self.audio_resources.get()['status'] == 'running':
            raise ApiError("请等待素材读取完成后再切换目录。", 409)

    def use_location(self, row, migrate_cache=True):
        if hasattr(self, "media_warmup"): self.media_warmup.close()
        self.store = StudioStore(row['mods'],row['workshop'],row['game'],row.get('extraMods', []), self.store.asset_catalog.settings_path, self.store.backups.root, migrate_cache=migrate_cache)
        self.resources = ResourceJobs(self.store,self.web_root / 'extract_game_assets.py')
        self.audio_resources = ResourceJobs(self.store,self.web_root / 'extract_audio_assets.py')
        self.store.asset_catalog.request_resources = self.request_asset_resources
        self.media_warmup = MediaWarmup(self)
        self.startup = StartupPreparation(self)

    def select_game(self, path):
        self.require_location_idle()
        try: row = self.locations.choose(path)
        except (ValueError, TypeError): raise ApiError("请选择包含 StudentAge.exe 和 StudentAge_Data 的游戏文件夹。")
        self.use_location(row)
        return self.location_state()

    def select_mods(self, path):
        self.require_location_idle()
        try: row, selected = self.locations.choose_mods(path)
        except (ValueError, TypeError, RuntimeError) as error: raise ApiError(str(error))
        self.use_location(row)
        state = self.location_state()
        if selected:
            project = next((p for p in self.store.projects() if str(p.path) == selected), None)
            if project: state['selectedProjectId'] = project.id
        return state

    def prepare_game(self):
        if not self.location_state().get('active'): raise ApiError("请先选择游戏目录。",409)
        if not self.store.catalog_prepared():
            try:
                result = subprocess.run(worker_command(self.web_root / 'extract_catalog.py',self.store.game), capture_output=True, text=True, encoding='utf-8', timeout=180, **process_options())
                if result.returncode: raise ApiError("游戏配置读取失败，请检查游戏文件完整性和目录写入权限。",503)
            except subprocess.TimeoutExpired: raise ApiError("游戏配置读取超时，请重试。",503)
        return self.location_state()


class StudioHandler(BaseHTTPRequestHandler):
    server_version = "StudentAgeStudio"

    def log_message(self, *_):
        pass  # Never log URLs containing local session tokens or request bodies.

    def verify_request(self, needs_token=True):
        if self.headers.get("Host") != "127.0.0.1:" + str(self.server.server_port):
            raise ApiError("本地访问地址无效。", 403)
        origin = self.headers.get("Origin")
        if origin and origin != self.server.origin:
            raise ApiError("不允许其他网站访问本地编辑器。", 403)
        if self.headers.get("Sec-Fetch-Site") == "cross-site":
            raise ApiError("不允许跨站请求。", 403)
        if needs_token:
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            token = self.headers.get("X-Studio-Token") or query.get("token", [""])[0]
            if not isinstance(token, str) or not hmac.compare_digest(token, self.server.token):
                raise ApiError("本地会话已失效，请重新打开应用。", 403, "unauthorized")

    def send_data(self, data, content_type, status=200, extra=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, value, status=200):
        self.send_data(json_bytes(value), "application/json; charset=utf-8", status)

    def send_file(self, path):
        stat = path.stat()
        length = stat.st_size
        etag = '"' + hashlib.sha256((str(path) + str((stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size))).encode()).hexdigest()[:32] + '"'
        if not self.headers.get('Range') and self.headers.get('If-None-Match') == etag:
            self.send_response(304)
            self.send_header('ETag', etag)
            self.send_header('Cache-Control', 'private, no-cache')
            self.send_header('Cross-Origin-Resource-Policy', 'same-origin')
            self.end_headers()
            return
        start, end, partial = 0, length - 1, False
        requested = self.headers.get("Range")
        if requested:
            match = re.fullmatch(r"bytes=([0-9]*)-([0-9]*)", requested.strip())
            if not match or not any(match.groups()):
                raise ApiError("资源范围无效。", 416)
            if match.group(1):
                start = int(match.group(1))
                end = min(int(match.group(2)), end) if match.group(2) else end
            else:
                start = max(0, length - int(match.group(2)))
            if start >= length or start > end:
                raise ApiError("资源范围超出文件。", 416)
            partial = True
        self.send_response(206 if partial else 200)
        self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "private, no-cache")
        self.send_header("ETag", etag)
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        if partial:
            self.send_header("Content-Range", "bytes " + str(start) + "-" + str(end) + "/" + str(length))
        self.end_headers()
        with path.open("rb") as stream:
            stream.seek(start)
            remaining = end - start + 1
            while remaining:
                data = stream.read(min(65536, remaining))
                if not data:
                    break
                self.wfile.write(data)
                remaining -= len(data)

    def dispatch(self, method):
        parsed = urllib.parse.urlsplit(self.path)
        route = parsed.path
        query = urllib.parse.parse_qs(parsed.query)
        self.verify_request(needs_token=route.startswith("/api/"))
        if route.startswith('/api/updates'):
            try:
                if method == 'GET' and route == '/api/updates':return self.send_json(self.server.updates.status())
                if method == 'POST':
                    if route == '/api/updates/healthy':
                        from update_bootstrap import mark_healthy
                        mark_healthy();return self.send_json({'ok':True})
                    if route == '/api/updates/check':return self.send_json(self.server.updates.check())
                    if route == '/api/updates/download':return self.send_json(self.server.updates.download())
                    if route in ('/api/updates/restart','/api/updates/rollback'):
                        result=self.server.updates.activate(rollback=route.endswith('/rollback'))
                        self.send_json(result)
                        threading.Timer(.5,self.server.request_update_restart).start()
                        return
                raise ApiError('未知的更新操作。',404)
            except ValueError as error:raise ApiError(str(error),400)
        if method == "GET":
            if route == "/api/startup-preparation":
                return self.send_json(self.server.startup.get())
            if route == "/api/background-status":
                tasks = []
                for key, state in [('startup',self.server.startup.get()),('all-media',self.server.media_warmup.get())]:
                    if state['status'] in ('running','error'):
                        tasks.append({'id':key,**state})
                # Read worker counters only; do not parse media indexes just to
                # display a progress indicator.
                for key, label, jobs in [('images','读取原版图片',self.server.resources),('audio','读取原版声音',self.server.audio_resources)]:
                    with jobs.lock: state = copy.deepcopy(jobs.state)
                    if state['status'] == 'running':
                        progress = state.get('progress') or {}
                        tasks.append({'id':key, 'phase':label, 'percent':min(99,int(100*(progress.get('bundle') or 0)/max(1,progress.get('total') or 0)))})
                hashing = self.server.store.asset_catalog.hash_progress()
                if hashing['running']: tasks.append({'id':'image-index','phase':'整理图片缓存','percent':hashing['percent']})
                return self.send_json({'tasks':tasks})
            if route == "/api/ids":
                return self.send_json(self.server.store.record_ids.public(query.get('projectId',[''])[0]))
            if route == "/api/space":
                return self.send_json(self.server.store.space.load(query.get('projectId',[''])[0]))
            if route == "/api/space-head":
                return self.send_file(self.server.store.space.head(query.get('projectId',[''])[0],query.get('personId',[''])[0]))
            if route == "/api/social":
                result = self.server.store.social.load(query.get("projectId", [""])[0], self.server.token)
                if any(row.get('avatarPath') and not row.get('avatarAvailable') and not row['avatarPath'].lower().startswith('mods/') for row in result['accounts']):
                    try: result['resourceStatus'] = self.server.request_asset_resources('portrait')
                    except ApiError as error: result['resourceStatus'] = {'status': 'error', 'message': error.message}
                else: result['resourceStatus'] = self.server.resources.get()
                return self.send_json(result)
            if route == '/api/live-model-file' or route.startswith('/ui-assets/live2d/'):
                raise ApiError('Live2D 动态预览暂时停用，请使用静态立绘。', 410)
            if route == '/api/model-idle-image':
                from model_idle import destination
                role,grade,gender=[int(query.get(k,[d])[0]) for k,d in [('role','0'),('grade','1'),('gender','1')]]
                if role<0 or grade not in (0,1) or gender not in (1,2): raise ApiError('模型参数无效')
                return self.send_file(destination(self.server.store.game,role,grade,gender))
            if route == "/api/minigame-image":
                from minigame_assets import image_file
                return self.send_file(image_file(self.server.store.game,query.get("path",[""])[0]))
            if route == "/api/space-ui":
                from space_assets import resources, resource_file
                name = query.get("resource", [""])[0]
                return self.send_file(resource_file(self.server.store.game, name)) if name else self.send_json(resources(self.server.store.game))
            if route == "/api/preview-ui":
                from preview_ui import resources, resource_file
                name = query.get("resource", [""])[0]
                return self.send_file(resource_file(self.server.store.game, name)) if name else self.send_json(resources(self.server.store.game))
            if route == "/api/social-emojis":
                from social_media import emoji_atlas
                return self.send_file(emoji_atlas(self.server.store.game))
            if route == "/api/social-image":
                return self.send_file(self.server.store.asset(query.get("projectId", [""])[0], query.get("path", [""])[0]))
            if route == "/api/asset-folders":
                return self.send_json(self.server.store.asset_catalog.folders())
            if route == "/api/asset-catalog":
                self.server.media_warmup.request_scan()
                return self.send_json(self.server.store.asset_catalog.list({key: value[0] for key, value in query.items()}))
            if route == "/api/asset-preview":
                return self.send_file(self.server.store.asset_catalog.preview({key: value[0] for key, value in query.items()}))
            if route == "/api/cache-settings":
                return self.send_json(self.server.cache_settings())
            if route == "/api/game-locations":
                return self.send_json(self.server.location_state())
            if route == "/api/backups":
                return self.send_json(self.server.store.backups.status(query.get('projectId', [None])[0]))
            if route == "/api/projects":
                return self.send_json([project.public() for project in self.server.store.project_list()])
            if route == "/api/condition-presets":
                return self.send_json(self.server.condition_presets.access())
            if route == "/api/condition-library":
                if query.get("source", [""])[0] == "mods":
                    return self.send_json(self.server.store.conditions.get_mods(query.get("projectId", [""])[0], query.get("modId", ["all"])[0]))
                return self.send_json(self.server.store.conditions.get(query.get('projectId', [''])[0]))
            if route == "/api/project":
                from playback_repair import repair
                repair_warning=None
                try:repair(self.server.store,query.get("id", [""])[0])
                except ApiError as error:repair_warning='自动播放修复暂未完成，原文件已保留：'+error.message
                except Exception as error:
                    diagnostic=self.error_response(error,'自动播放修复未完成，仍可继续编辑。','playback_repair_failed',method)
                    repair_warning='自动播放修复未完成，已跳过；仍可继续编辑。'+(' 错误日志：'+diagnostic['errorLog'] if diagnostic.get('errorLog') else '')
                self.server.store.clean_orphan_dialogues(query.get("id", [""])[0])
                data=self.server.store.load(query.get("id", [""])[0])
                if repair_warning:data.setdefault('warnings',[]).append(repair_warning)
                return self.send_json(data)
            if route == "/api/workshop":
                self.server.store.clean_orphan_dialogues(query.get("projectId", [""])[0])
                return self.send_json(self.server.store.workshop_info(query.get("projectId", [""])[0]))
            if route == "/api/table":
                return self.send_json(self.server.store.table(query.get("projectId", [""])[0], query.get("name", [""])[0]))
            if route == "/api/manifest":
                return self.send_json(self.server.store.manifest(query.get("projectId", [""])[0]))
            if route == "/api/audio":
                return self.send_json(self.server.store.audio_files(query.get("projectId", [""])[0]))
            if route == "/api/reuse-assets":
                return self.send_json(self.server.store.reuse_assets(query.get('projectId', [''])[0], query.get('kind', ['background'])[0]))
            if route == "/api/resource-status":
                return self.send_json(self.server.resources.get())
            if route == "/api/audio-status":
                return self.send_json(self.server.audio_resources.get())
            if route == '/api/talk-head':
                from headshots import head_paths, crop_head
                store = self.server.store
                project = store.project(query.get('projectId', [''])[0])
                role = str(int(query.get('roleId', ['0'])[0])); grade = int(query.get('grade', ['1'])[0])
                persons = {**store.catalog_rows('PersonCfg', store.catalog()), **read_json(safe_path(project.path, 'Cfgs/zh-cn/PersonCfg.json'), {})}
                person = persons.get(role, {})
                for resource in ([] if role == '0' and query.get('gender', ['1'])[0] == '2' else head_paths(person, grade)):
                    try: return self.send_file(store.asset(project.id, resource))
                    except ApiError: pass
                urls = person.get('url2' if grade > 1 and person.get('url2') else 'url') or []
                candidates = [u for u in urls if isinstance(u, str) and u.lower().startswith('mods/')]
                identity = '0-female' if role == '0' and query.get('gender', ['1'])[0] == '2' else role
                candidates.append('portrait-cache/' + identity + '-' + str(max(0, grade - 1)) + '-0-0.png')
                for resource in candidates:
                    try:
                        path = store.asset(project.id, resource)
                        return self.send_file(crop_head(path, auxiliary_cache(store.asset_catalog.settings_path.parent, 'AssetCache/talk-heads')))
                    except (ApiError, FileNotFoundError): pass
                raise ApiError('人物头像尚未读取。', 404)
            if route == "/api/assets":
                path = self.server.store.asset(query.get("projectId", [""])[0], query.get("path", [""])[0])
                return self.send_file(path)
            if route == "/api/exports":
                path = self.server.store.export_file(query.get("name", [""])[0])
                return self.send_data(path.read_bytes(), "application/json" if path.suffix == ".json" else "text/plain; charset=utf-8",
                                      extra={"Content-Disposition": "attachment; filename*=UTF-8''" + urllib.parse.quote(path.name)})
            if route == "/api/health":
                return self.send_json({"ok": True, "pillow": Image is not None, "modsPath": str(self.server.store.mods)})
            if route == "/api/json-files":
                return self.send_json(self.server.store.json_files(query.get("projectId", [""])[0]))
            if route == "/api/idle-chats":
                import idle_chats
                return self.send_json(idle_chats.load(self.server.store, query.get("projectId", [""])[0], sys.modules[__name__]))
            if route == "/api/messages":
                import messages
                return self.send_json(messages.load(self.server.store, query.get("projectId", [""])[0], self.server.token, sys.modules[__name__]))
            if route == "/api/talk-ui":
                # Original talk bubble artwork (extracted by tools/extract_talk_bubble.py); 404 until extracted.
                from ui_resources import resource_manifest, resource_path
                name = query.get("resource", [""])[0]
                try:
                    return self.send_file(resource_path('talk', name, self.server.store.game)) if name else self.send_json(resource_manifest('talk', self.server.store.game))
                except (FileNotFoundError, OSError, ValueError):
                    raise ApiError("原版气泡素材尚未提取。", 404)
            if route == "/api/cg-ui":
                from ui_resources import resource_manifest, resource_path
                name = query.get("resource", [""])[0]
                return self.send_file(resource_path('cg', name, self.server.store.game)) if name else self.send_json(resource_manifest('cg', self.server.store.game))
            if route == "/api/phone-ui":
                from phone_ui import resources, resource_file
                name = query.get("resource", [""])[0]
                return self.send_file(resource_file(name, self.server.store.game)) if name else self.send_json(resources(self.server.store.game))
            if route == "/api/goals":
                import goal_workbench
                return self.send_json(goal_workbench.load(self.server.store, query.get("projectId", [""])[0], sys.modules[__name__]))
            if route == "/api/goal-ui":
                from goal_ui import resources, resource_file
                name = query.get("resource", [""])[0]
                return self.send_file(resource_file(name, self.server.store.game)) if name else self.send_json(resources(self.server.store.game))
            if route == '/api/external-dialogues':
                import external_dialogues
                return self.send_json(external_dialogues.load(self.server.store,query.get('projectId',[''])[0],sys.modules[__name__]))
            if route == "/api/characters":
                import character_workbench
                return self.send_json(character_workbench.load(self.server.store, query.get("projectId", [""])[0]))
            if route == "/api/display-settings":
                return self.send_json(self.server.display_settings())
            if route in ("/", "/index.html"):
                path = self.server.web_root / "index.html"
                if not path.is_file():
                    raise ApiError("应用界面文件缺失。", 503)
                page = path.read_text(encoding="utf-8")
                if os.name == "nt": page = page.replace("⇧", "Shift+").replace("⌘", "Ctrl+")
                page = page.replace('<script>window.STUDIO_TOKEN = "__STUDIO_TOKEN__";</script>', "")
                nonce = secrets.token_urlsafe(18)
                preferences = self.server.display_settings()
                bootstrap = '<script nonce="' + nonce + '">window.STUDIO_TOKEN=' + json.dumps(self.server.token) + ';window.STUDIO_BOOTSTRAPPING=true;window.STUDIO_DISPLAY_IDS=' + json.dumps(preferences['showRecordIds']) + ';window.STUDIO_AUTO_SAVE=' + json.dumps(preferences['autoSave']) + ';window.STUDIO_SAVE_ON_EXIT='+json.dumps(preferences['saveOnExit'])+';window.STUDIO_ONBOARDING_COMPLETE='+json.dumps(preferences['onboardingComplete'])+';window.STUDIO_WORKSHOP_FAVORITES=' + json.dumps(preferences['workshopFavorites']) + ";</script>"
                bootstrap = bootstrap.replace('</script>', ';window.STUDIO_THEME='+json.dumps(preferences['theme'])+';document.documentElement.dataset.theme=window.STUDIO_THEME;</script>')
                if preferences['theme'] == 'classic':
                    for sheet in ('glass-palette.css', 'glass-theme.css'):
                        page = page.replace('href="/'+sheet+'"', 'href="/'+sheet+'" media="not all"')
                page = page.replace("</head>", bootstrap + "</head>", 1) if "</head>" in page else bootstrap + page
                policy = "default-src 'none'; script-src 'self' 'wasm-unsafe-eval' 'nonce-" + nonce + "'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; media-src 'self' blob:; connect-src 'self'; font-src 'self' data:; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
                return self.send_data(page.encode(), "text/html; charset=utf-8", extra={"Content-Security-Policy": policy})
            if route in ("/character-images.js", "/external-dialogues.js", "/app-updates.js", "/original-mode.js", "/event-ownership.js", "/live-preview.js", "/config-doctor.js", "/save-review.js", "/libraries.js", "/json-editor.js", "/json-editor.css", "/editor-theme.css", "/glass-palette.css", "/glass-theme.css", "/liquid-glass.js", "/theme.js", "/glass-tones.css", "/onboarding.js", "/onboarding.css", "/brand.svg", "/branch-tree.js", "/idle-chats.js", "/idle-chats.css", "/message-graph.js", "/messages.js", "/messages.css", "/goals.js", "/goals.css", "/character-ui.js", "/characters.js", "/character-model.js", "/character-states.js", "/character-model.css", "/character-controls.js", "/space-style.js", "/space-style.css", "/minigame-sudoku.js", "/minigame-library.js", "/minigame-library.css", "/characters.css", "/event-types.js", "/record-labels.js", "/record-labels.css", "/search-pinyin.js", "/search.js", "/record-ids.js", "/record-ids.css", "/navigation.js", "/navigation.css", "/help.js", "/app.js", "/scene.js", "/screen-effects.js", "/screen-effects.css", "/branches.js", "/timeline.js", "/conditions.js", "/condition-library.js", "/effects.js", "/history.js", "/dialogue-text.js", "/action-editor.js", "/performance.css", "/preview-ui.js", "/preview-ui.css", "/locations.js", "/event-bindings.js", "/warehouse.js", "/warehouse.css", "/workshop.js", "/workshop.css", "/social-media.js", "/social.js", "/social.css", "/space.js", "/reuse-assets.js", "/reuse-assets.css", "/events.js", "/events.css", "/asset-picker.js", "/asset-picker.css", "/ui-controls.js", "/ui-controls.css", "/scene-dialogue.css", "/asset-names.js", "/expressions.js", "/styles.css", "/icon.png"):
                file = self.server.web_root / route.lstrip("/")
                if file.is_file():
                    data = file.read_bytes()
                    if os.name == "nt" and file.suffix == ".js": data = data.decode("utf-8").replace("⇧", "Shift+").replace("⌘", "Ctrl+").replace("CrossOver 的本地模组", "本机的模组").encode("utf-8")
                    return self.send_data(data, mimetypes.guess_type(file.name)[0] or "application/octet-stream")
            raise ApiError("页面不存在。", 404)
        if method == "POST":
            if self.headers.get("Content-Type", "").split(";", 1)[0].strip() != "application/json":
                raise ApiError("请求格式必须是 JSON。", 415)
            if self.headers.get("Transfer-Encoding"):
                raise ApiError("请求格式不支持。", 400)
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                raise ApiError("请求长度无效。")
            if length <= 0 or length > MAX_JSON:
                raise ApiError("请求为空或超过大小限制。", 413)
            try:
                payload = json.loads(self.rfile.read(length), parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
            except (ValueError, UnicodeError, RecursionError):
                raise ApiError("请求 JSON 无效。")
            if not isinstance(payload, dict):
                raise ApiError("请求内容必须为对象。")
            if route == "/api/condition-presets":
                return self.send_json(self.server.condition_presets.access(payload))
            if route == "/api/cache-settings":
                return self.send_json(self.server.cache_settings(payload))
            if route == "/api/display-settings":
                return self.send_json(self.server.display_settings(payload))
            if route == "/api/asset-folders":
                result = self.server.store.asset_catalog.set_folder(payload)
                self.server.media_warmup.request_scan()
                return self.send_json(result)
            if route == '/api/open-storage':
                from storage_paths import user_data_root, cache_root
                from platform_support import open_directory
                if payload.get('kind') not in ('userData','cache'): raise ApiError('未知的存储目录。')
                folder = user_data_root() if payload['kind'] == 'userData' else cache_root()
                folder.mkdir(parents=True,exist_ok=True)
                open_directory(folder)
                return self.send_json({'ok':True})
            if route == '/api/asset-catalog-delete':
                return self.send_json(self.server.store.asset_catalog.delete_asset(payload))
            if route == "/api/asset-library-import":
                return self.send_json(self.server.store.asset_catalog.import_folder(payload), 201)
            if route == "/api/asset-catalog-import":
                if isinstance(payload.get("assetIds"), list):
                    return self.send_json(self.server.store.asset_catalog.import_assets(payload), 201)
                return self.send_json(self.server.store.asset_catalog.import_asset(payload), 201)
            if route == "/api/game-scan":
                if not self.server.locations: raise ApiError("此窗口使用指定目录。",409)
                return self.send_json(self.server.locations.start(deep=payload.get('deep') is True))
            if route == "/api/game-scan-cancel":
                if self.server.locations: self.server.locations.cancel.set()
                return self.send_json(self.server.location_state())
            if route == "/api/game-select":
                return self.send_json(self.server.select_game(payload.get('game')))
            if route == "/api/mods-select":
                return self.send_json(self.server.select_mods(payload.get('mods')))
            if route == "/api/game-prepare":
                return self.send_json(self.server.prepare_game())
            if route == "/api/startup-preparation":
                return self.send_json(self.server.startup.start(payload.get("projectId"), payload.get("foldersOnly") is True))
            if route == "/api/error-log-settings":
                return self.send_json(self.server.error_logs.configure(payload))
            if route == "/api/backup-settings":
                return self.send_json(self.server.store.backups.configure(payload))
            if route == "/api/open-error-logs":
                from platform_support import open_directory
                self.server.error_logs.root.mkdir(parents=True, exist_ok=True)
                open_directory(self.server.error_logs.root)
                return self.send_json(self.server.error_logs.status())
            if route == "/api/open-backups":
                state = self.server.store.backups.status()
                reveal_file(Path(state['path']))
                return self.send_json(state)
            if self.server.locations and not self.server.locations.active:
                raise ApiError("请先选择《学生时代》的安装目录。",409)
            if route == "/api/portrait-dimensions":
                self.server.store.project(payload.get("projectId"))
                paths = payload.get("paths", [])
                if not isinstance(paths, list) or len(paths) > 128:
                    raise ApiError("立绘尺寸请求无效。")
                from extract_game_assets import portrait_dimensions
                with self.server.store.lock:
                    result = portrait_dimensions(self.server.store.game, self.server.store.catalog(), paths)
                for path in paths:
                    if path in result:continue
                    try:
                        with Image.open(self.server.store.asset(payload.get('projectId'),path)) as source:result[path]=list(source.size)
                    except (ApiError,OSError,ValueError):pass
                return self.send_json(result)
            if route == '/api/live-model':
                raise ApiError('Live2D 动态预览暂时停用，请使用静态立绘。', 410)
            if route == '/api/model-idle':
                self.server.store.project(payload.get('projectId'))
                from model_idle import request
                return self.send_json(request(self.server.store.game,payload.get('role'),payload.get('grade'),payload.get('gender',1)))
            if route == "/api/portraits":
                self.server.store.project(payload.get("projectId"))
                if str(payload.get("role")) not in self.server.store.catalog().get("persons", {}):
                    raise ApiError("未找到原版人物模型；自建人物可使用自己导入的表情图片。", 404)
                try: result=expression_status(self.server.store.game, payload.get("role"),payload.get("grade"),payload.get("cloth"),payload.get("face",0),request=True,gender=payload.get("gender",1))
                except ValueError as error: raise ApiError(str(error))
                return self.send_json(result)
            if route == "/api/save":
                return self.send_json(save_review.perform(self.server.store.save, payload, ApiError))
            if route == "/api/story/renumber":
                return self.send_json(self.server.store.renumber_rows(payload))
            if route == "/api/backup":
                return self.send_json(self.server.store.backups.create(payload), 201)
            if route == '/api/premises/references':
                return self.send_json(self.server.store.premise_references(payload))
            if route == "/api/premises/create":
                return self.send_json(self.server.store.create_catalog_premise(payload),201)
            if route == "/api/premises/new":
                return self.send_json(self.server.store.propose_premise(payload))
            if route == "/api/export":
                return self.send_json(self.server.store.export_text(payload), 201)
            if route == "/api/open-export":
                return self.send_json(self.server.store.open_export(payload.get("name")))
            if route == "/api/space-save":
                return self.send_json(save_review.perform(self.server.store.space.save, payload, ApiError))
            if route == "/api/social-save":
                return self.send_json(save_review.perform(self.server.store.social.save, payload, ApiError))
            if route == "/api/ids/rename":
                return self.send_json(self.server.store.record_ids.rename(payload))
            if route == "/api/ids/check":
                return self.send_json(self.server.store.record_ids.collision_report(payload))
            if route == "/api/ids/undo":
                return self.send_json(self.server.store.record_ids.undo(payload))
            if route == "/api/idle-chats-save":
                import idle_chats
                return self.send_json(idle_chats.save(self.server.store, payload, sys.modules[__name__]))
            if route == "/api/messages-save":
                import messages
                return self.send_json(save_review.perform(lambda value: messages.save(self.server.store, value, sys.modules[__name__]), payload, ApiError))
            if route == "/api/goals-save":
                import goal_workbench
                return self.send_json(save_review.perform(lambda value: goal_workbench.save(self.server.store, value, sys.modules[__name__]), payload, ApiError))
            if route == '/api/external-dialogues-save':
                import external_dialogues
                return self.send_json(save_review.perform(lambda value: external_dialogues.save(self.server.store,value,sys.modules[__name__]),payload,ApiError))
            if route == "/api/characters-save":
                import character_workbench
                return self.send_json(save_review.perform(lambda value: character_workbench.save(self.server.store, value, sys.modules[__name__]), payload, ApiError))
            if route == '/api/character-companion':
                from character_images import import_companion
                return self.send_json(import_companion(self.server.store,payload,sys.modules[__name__]))
            if route == "/api/character-image":
                import character_workbench
                return self.send_json(character_workbench.import_media(self.server.store, payload, sys.modules[__name__]))
            if route == "/api/warehouse-save":
                return self.send_json(save_review.perform(self.server.store.warehouse_save, payload, ApiError))
            if route == "/api/table-save":
                return self.send_json(save_review.perform(self.server.store.table_save, payload, ApiError))
            if route == "/api/manifest":
                return self.send_json(self.server.store.manifest_save(payload))
            if route in ('/api/config-check','/api/config-repair'):
                import config_doctor
                operation = config_doctor.check if route == '/api/config-check' else config_doctor.repair
                return self.send_json(operation(self.server.store,payload,sys.modules[__name__]))
            if route == "/api/json-source":
                return self.send_json(self.server.store.json_source(payload))
            if route == "/api/json-analyze":
                text = payload.get("text")
                if not isinstance(text, str) or len(text) > self.server.store.JSON_SOURCE_LIMIT:
                    raise ApiError("文本无效或超过 16 MB。", 413)
                result = analyze_json_text(text, repair=bool(payload.get("repair")))
                if payload.get("parse") and result.get("valid"):
                    result["value"] = json.loads(compatible_json(result.get("text", text)), strict=False)
                return self.send_json(result)
            if route == "/api/json-save":
                return self.send_json(self.server.store.json_save(payload))
            if route == "/api/audio-import":
                return self.send_json(self.server.store.audio_import(payload), 201)
            if route == "/api/audio-refresh":
                return self.send_json(self.server.audio_resources.start(), 202)
            if route == "/api/resource-refresh":
                return self.send_json(self.server.resources.start(), 202)
            if route == "/api/create":
                return self.send_json(self.server.store.create(payload.get("name")), 201)
            if route == "/api/copy":
                return self.send_json(self.server.store.duplicate(payload.get("projectId"), payload.get("name")), 201)
            if route == "/api/image-import":
                return self.send_json(self.server.store.import_field_image(payload), 201)
            if route == "/api/import":
                return self.send_json(self.server.store.import_image(payload), 201)
            if route == "/api/reuse-asset":
                return self.send_json(self.server.store.reuse_asset(payload), 201)
            raise ApiError("接口不存在。", 404)
        raise ApiError("请求方法不支持。", 405)

    def error_response(self, error, message, code, method):
        # Keep request bodies, headers and URL queries out of diagnostics.
        route = urllib.parse.urlsplit(self.path).path
        return self.server.error_logs.response(error, message, code, method + " " + route, (self.server.token,))

    def handle_request(self, method):
        try:
            self.connection.settimeout(30)
            # Resolved image/audio paths remain valid during a location switch.
            # Do not hold the global location lock while streaming their bytes.
            route = urllib.parse.urlsplit(self.path).path
            independent = method == 'GET' and (
                (not route.startswith('/api/') and route not in ('/', '/index.html'))
                or route in {'/api/assets', '/api/asset-preview', '/api/background-status', '/api/preview-ui', '/api/minigame-image', '/api/phone-ui', '/api/goal-ui', '/api/talk-ui', '/api/cg-ui'})
            with nullcontext() if independent else self.server.location_lock:
                with original_mode.scope(self.headers.get("X-Studio-Original-Project")):
                    self.dispatch(method)
        except ApiError as exc:
            try:
                diagnostic = exc.status >= 500 or isinstance(exc.__cause__ or exc.__context__, (OSError, json.JSONDecodeError))
                data = self.error_response(exc, exc.message, exc.code, method) if diagnostic else {"error": exc.message, "code": exc.code}
                if hasattr(exc, "warnings"): data["warnings"] = exc.warnings
                self.send_json(data, exc.status)
            except (BrokenPipeError, ConnectionResetError):
                pass
        except (BrokenPipeError, ConnectionResetError, socket.timeout):
            pass
        except PermissionError as exc:
            self.send_json(self.error_response(exc, "文件访问被拒绝，请检查访问权限：" + str(exc.filename or "当前模组目录"), "file_permission", method), 403)
        except OSError as exc:
            detail = str(exc.strerror or exc)
            code = getattr(exc, 'winerror', None) or exc.errno
            self.send_json(self.error_response(exc, "文件访问失败：" + str(exc.filename or "模组或备份目录") + "。" + detail + ("（系统错误 " + str(code) + "）" if code else ''), "file_unavailable", method), 422)
        except Exception as exc:
            try:
                self.send_json(self.error_response(exc, "操作未完成，请检查文件权限、配置格式或重新打开应用。", "internal_error", method), 500)
            except (BrokenPipeError, ConnectionResetError):
                pass

    def do_GET(self):
        self.handle_request("GET")

    def do_POST(self):
        self.handle_request("POST")

    def do_OPTIONS(self):
        self.handle_request("OPTIONS")


def create_server(args):
    locations = None if any((args.game, args.mods, args.workshop)) else GameLocations(path=getattr(args, 'qa_location_settings', None))
    active = locations.active if locations else None
    fallback = settings_path().parent / "Unconfigured"
    store = StudioStore(args.mods or (active["mods"] if active else fallback / "Mods" if locations else DEFAULT_MODS),
                        args.workshop or (active["workshop"] if active else fallback / "Workshop" if locations else DEFAULT_WORKSHOP),
                        args.game or (active["game"] if active else fallback / "Game" if locations else DEFAULT_GAME),
                        active.get('extraMods', []) if active else (), migrate_cache=False)
    server = StudioServer(("127.0.0.1", args.port), store, args.web_root, locations)
    return server


def main():
    parser = argparse.ArgumentParser(description="学生时代创作工坊本地服务")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--ready-file")
    parser.add_argument("--mods")
    parser.add_argument("--workshop")
    parser.add_argument("--game")
    parser.add_argument("--web-root")
    args = parser.parse_args()
    server = create_server(args)
    ready = {"url": server.origin + "/#" + server.token, "port": server.server_port, "pid": os.getpid()}
    if args.ready_file:
        destination = Path(args.ready_file).expanduser()
        atomic_write(destination, json_bytes(ready))
        os.chmod(destination, 0o600)
    else:
        print(json.dumps(ready), flush=True)
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    if server.update_restart_requested:
        from update_bootstrap import RESTART_EXIT
        raise SystemExit(RESTART_EXIT)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        ErrorLogs().write(error, operation="启动本地服务")
        raise
