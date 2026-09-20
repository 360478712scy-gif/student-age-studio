"""Upload local mods to the Steam Workshop (backend only, no UI here).

Flow per job: validate payload -> stage a clean copy -> create-or-reuse the
Workshop entry -> fill title/description/visibility/tags/metadata/content/
preview -> submit -> poll progress -> persist the published id to a sidecar.

Only ``local:`` projects may publish. Valve's ``steam_api`` is never shipped:
see :mod:`steam_bridge`. The publishing dialog drives this through
``POST /api/publish`` (202), ``GET /api/publish-status`` and
``POST /api/publish-cancel``.
"""
import io
import hashlib
import base64
import json
import os
import secrets
import shutil
import tempfile
import threading
import time
from pathlib import Path

from steam_bridge import (
    APP_ID, ERESULT_FILE_NOT_FOUND, ERESULT_OK,
    SteamBridge, SteamBridgeError,
    VISIBILITY_FRIENDS, VISIBILITY_PRIVATE, VISIBILITY_PUBLIC,
)

try:
    from PIL import Image as _PILImage
except ImportError:
    _PILImage = None

SIDECAR = 'StudentAgeStudio/workshop.json'
ITEM_URL = 'https://steamcommunity.com/sharedfiles/filedetails/?id={id}'
LEGAL_URL = 'https://steamcommunity.com/sharedfiles/workshopagreement'

TITLE_MAX = 128
DESCRIPTION_MAX = 8000
PREVIEW_MAX = 1024 * 1024
CHANGE_NOTE_MAX = 2000
CHANGE_NOTE_DEFAULT = '通过拾光工坊上传'
WARNING_BYTES = 900 * 1024 * 1024
SINGLE_FILE_WARNING = 100 * 1024 * 1024
JOB_TIMEOUT = 30 * 60
STALL_TIMEOUT = 10 * 60
CALLBACK_TIMEOUT = 120
VISIBILITIES = {VISIBILITY_PUBLIC, VISIBILITY_FRIENDS, VISIBILITY_PRIVATE}
WORKSHOP_TAGS = {'剧情', '其他'}
# Staging drops editor-private and volatile entries; everything else (Cfgs,
# Audios, Textures, manifest.json, deleted-talks.json, …) uploads verbatim
# like the game's own publisher. Our sidecar must never leave the machine.
STAGING_SKIP_DIRS = {'Backups'}
STAGING_SKIP_FILES = {'.save.lock', 'workshop.json', 'workshop-pending.json', 'workshop-binding-backup.json'}


class PublishError(Exception):
    """Carries an API-style shape across the server boundary."""

    def __init__(self, message, status=400, code='invalid_request'):
        super().__init__(message)
        self.message, self.status, self.code = message, status, code


def _utcnow():
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())


class _Cancelled(Exception):
    pass


def _check_cancelled(job):
    if job.cancelled.is_set():
        raise _Cancelled()


def read_sidecar(project):
    path = project.path / SIDECAR
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(data, dict):
            raise ValueError('not an object')
        ident = int(data.get('publishedFileId') or 0)
        if ident < 0 or ident >= 2 ** 64:
            raise ValueError('invalid item id')
        return data
    except FileNotFoundError:
        return {}
    except (OSError, ValueError, TypeError) as error:
        raise PublishError('本地工坊绑定损坏或无法读取，请先修复，不能自动创建新条目。', 409, 'publish_binding_invalid') from error


def publish_files(project):
    from mod_copy import excluded_entry
    for base, directories, names in os.walk(project.path, followlinks=False):
        base = Path(base)
        directories[:] = sorted(name for name in directories
            if not (base / name).is_symlink() and name not in STAGING_SKIP_DIRS
            and not excluded_entry(base / name, project.path))
        for name in sorted(names):
            path = base / name
            if path.is_symlink() or name in STAGING_SKIP_FILES or name.lower().endswith(('.tmp', '.log', '.lock')) or excluded_entry(path, project.path):
                continue
            yield path


def snapshot(project):
    result = {}
    for path in publish_files(project):
        before = path.stat()
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        after = path.stat()
        if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
            raise PublishError('发布素材正在被修改，请等待保存完成后重试。', 409, 'conflict')
        result[path.relative_to(project.path).as_posix()] = (after.st_size, digest)
    return result


def stage_mod(api, project, destination):
    """Copy publishable mod content. Returns (files, bytes, skipped)."""
    from mod_copy import excluded_entry, stable_copy
    destination = Path(destination)
    files, total, skipped = 0, 0, []
    for base, directories, names in os.walk(project.path, followlinks=False):
        base = Path(base)
        directories[:] = [name for name in directories
                          if not (base / name).is_symlink() and (base / name).name not in STAGING_SKIP_DIRS
                          and not excluded_entry(base / name, project.path)]
        for name in names:
            source = base / name
            if source.is_symlink() or name in STAGING_SKIP_FILES or name.lower().endswith(('.tmp', '.log', '.lock')):
                skipped.append(str(source.relative_to(project.path)))
                continue
            if excluded_entry(source, project.path):
                skipped.append(str(source.relative_to(project.path)))
                continue
            target = destination / source.relative_to(project.path)
            target.parent.mkdir(parents=True, exist_ok=True)
            stable_copy(source, target)
            files += 1
            try:
                total += target.stat().st_size
            except OSError:
                pass
            if total > WARNING_BYTES * 4:
                raise PublishError('模组内容超过 3.5 GB，无法上传。请精简后再试。', 413, 'publish_too_large')
    return files, total, skipped


def prepare_preview(api, source_file, staged_dir):
    """Place a Steam-ready preview.jpg into the staged copy. Returns its path."""
    if _PILImage is None:
        raise PublishError('当前 Python 缺少图片组件 Pillow，请使用桌面应用发布。', 503, 'publish_no_pillow')
    Image = _PILImage
    staged = Path(staged_dir) / 'preview.jpg'
    raw = Path(source_file).read_bytes()
    if len(raw) > PREVIEW_MAX:
        raise PublishError('封面图片超过 1 MB，请压缩后再试。', 413, 'publish_preview_too_large')
    try:
        with Image.open(io.BytesIO(raw)) as image:
            image.load()
            picture = image.convert('RGB')
    except Exception:
        raise PublishError('封面图片无法解码，请选择完整的图片文件。', 422, 'publish_preview_undecodable')
    staged.parent.mkdir(parents=True, exist_ok=True)
    picture.save(staged, format='JPEG', quality=85)
    if staged.stat().st_size > PREVIEW_MAX:
        small = picture.copy()
        width, height = small.size
        while staged.stat().st_size > PREVIEW_MAX and min(width, height) > 64:
            width, height = max(64, width * 3 // 4), max(64, height * 3 // 4)
            small.resize((width, height), Image.Resampling.LANCZOS).save(staged, format='JPEG', quality=85)
    if staged.stat().st_size > PREVIEW_MAX:
        raise PublishError('封面压缩后仍然超过 1 MB，请换一张更小的图。', 413, 'publish_preview_too_large')
    return staged


def normalize_payload(api, project, manifest, payload):
    """Merge manifest defaults with explicit overrides; raise on any violation."""
    if not isinstance(payload, dict):
        raise PublishError('发布参数必须是对象。')
    title = payload.get('title', manifest.get('title', ''))
    description = payload.get('description', manifest.get('description', ''))
    visibility = payload.get('visibility', VISIBILITY_PRIVATE)
    tags = payload.get('tags', manifest.get('tags', []))
    change_note = payload.get('changeNote', CHANGE_NOTE_DEFAULT)
    if not isinstance(title, str) or not title.strip():
        raise PublishError('请填写模组标题。', 422, 'publish_title_missing')
    if len(title.strip()) > TITLE_MAX:
        raise PublishError(f'标题最多 {TITLE_MAX} 个字符。', 422, 'publish_title_too_long')
    if not isinstance(description, str):
        raise PublishError('简介必须是文本。', 422, 'publish_description_invalid')
    if len(description) > DESCRIPTION_MAX:
        raise PublishError(f'简介最多 {DESCRIPTION_MAX} 个字符。', 422, 'publish_description_too_long')
    try:
        visibility = int(visibility)
    except (TypeError, ValueError):
        raise PublishError('可见性取值无效（0 公开 / 1 仅好友 / 2 私密）。', 422, 'publish_visibility_invalid')
    if visibility not in VISIBILITIES:
        raise PublishError('可见性取值无效（0 公开 / 1 仅好友 / 2 私密）。', 422, 'publish_visibility_invalid')
    if tags is None:
        tags = []
    if not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags):
        raise PublishError('标签必须是字符串数组。', 422, 'publish_tags_invalid')
    illegal = [tag for tag in tags if tag.strip() not in WORKSHOP_TAGS]
    if illegal:
        raise PublishError('暂不支持的标签：' + '、'.join(illegal) + '（目前仅支持：剧情、其他）。',
                           422, 'publish_tags_unsupported')
    if not isinstance(change_note, str) or not change_note.strip():
        raise PublishError('请填写本次更新说明。', 422, 'publish_change_note_missing')
    if len(change_note) > CHANGE_NOTE_MAX:
        raise PublishError(f'更新说明最多 {CHANGE_NOTE_MAX} 个字符。', 422, 'publish_change_note_too_long')
    return {'title': title.strip(), 'description': description,
            'visibility': visibility, 'tags': [tag.strip() for tag in tags if tag.strip()],
            'changeNote': change_note.strip()}


def resolve_preview(api, project, manifest, payload):
    """Locate the cover image. Returns a Path inside the mod or cache."""
    raw = payload.get('previewPath', 'preview.jpg')
    if not isinstance(raw, str) or not raw.strip():
        raise PublishError('请提供封面图片。', 422, 'publish_preview_missing')
    raw = raw.strip()
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = project.path / raw.replace('\\', '/')
    try:
        resolved = candidate.resolve()
    except OSError:
        raise PublishError('封面路径无效。', 422, 'publish_preview_missing')
    allowed = [project.path.resolve()]
    try:
        from storage_paths import cache_root
        allowed.append(Path(cache_root()).resolve())
    except Exception:
        pass
    if not any(resolved == base or base in resolved.parents for base in allowed):
        raise PublishError('封面必须在模组目录或本机缓存内。', 403, 'publish_preview_outside')
    if not resolved.is_file():
        raise PublishError('找不到封面图片：' + raw + '。', 404, 'publish_preview_missing')
    return resolved


class PublishJob:
    def __init__(self, job_id, project_id):
        self.id = job_id
        self.project_id = project_id
        self.state = 'queued'
        self.phase = '等待开始'
        self.percent = 0
        self.processed_bytes = 0
        self.total_bytes = 0
        self.log = []
        self.warnings = []
        self.error = None
        self.published_file_id = 0
        self.item_url = ''
        self.created_at = _utcnow()
        self.cancelled = threading.Event()
        self.submitted = False
        self.binding_pending = False
        self.fields = {}

    def say(self, message):
        self.log.append(message)
        del self.log[:max(0, len(self.log) - 100)]

    def public(self):
        body = {'jobId': self.id, 'projectId': self.project_id, 'state': self.state,
                'phase': self.phase, 'percent': self.percent,
                'processedBytes': self.processed_bytes, 'totalBytes': self.total_bytes,
                'log': list(self.log), 'warnings': list(self.warnings),
                'createdAt': self.created_at, 'submitted': self.submitted,
                'bindingPending': self.binding_pending}
        if self.published_file_id:
            body['publishedFileId'] = str(self.published_file_id)
            body['itemUrl'] = ITEM_URL.format(id=self.published_file_id)
        if self.error:
            body['error'] = self.error
        if self.cancelled.is_set():
            body['note'] = '已停止轮询；若提交已发出，服务端仍可能收录，请用物品链接确认。'
        return body


class Publisher:
    """One worker owns the process-global native session until its callback settles."""
    TERMINAL = {'done', 'error', 'cancelled', 'unconfirmed'}

    def __init__(self, bridge_factory=None):
        self._lock = threading.RLock()
        self._jobs = {}
        self._bridge = None
        self._bridge_factory = bridge_factory or SteamBridge
        self._worker = None
        self._closing = False
        self._blocked = False

    def _register(self, job):
        self._jobs[job.id] = job
        for ident, previous in list(self._jobs.items()):
            if len(self._jobs) <= 32:
                break
            if previous.state in self.TERMINAL and not previous.binding_pending and ident != job.id:
                self._jobs.pop(ident)

    def busy(self):
        with self._lock:
            return bool(self._worker and self._worker.is_alive())

    def status(self, job_id):
        with self._lock:
            job = self._jobs.get(job_id)
            return job.public() if job else None

    def cancel(self, job_id):
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            if job.state not in self.TERMINAL:
                job.cancelled.set()
                job.state = 'cancelling'
                job.phase = '等待 Steam 确认，已提交的内容无法撤回' if job.submitted else '正在停止发布'
            return job.public()

    def _bridge_instance(self, game=None):
        with self._lock:
            if self._bridge is None:
                self._bridge = self._bridge_factory()
            return self._bridge

    def close(self):
        with self._lock:
            self._closing = True
            for job in self._jobs.values():
                if job.state not in self.TERMINAL:
                    job.cancelled.set()
            worker = self._worker
        if worker and worker is not threading.current_thread():
            worker.join(timeout=3)
        # A still-running worker owns shutdown; never unload underneath native calls.
        if not worker or not worker.is_alive():
            with self._lock:
                if self._bridge is not None:
                    self._bridge.shutdown()
                    self._bridge = None

    def prereq(self, store, api, project_id, payload=None):
        payload = payload or {}
        project = store.project(project_id, writable=True)
        with store.lock:
            manifest = api.read_json(project.path / 'manifest.json', {})
            if not isinstance(manifest, dict):
                manifest = {}
            revision = store.revision(project)
            try:
                fields = normalize_payload(api, project, manifest, payload)
                manifest_check = {'ok': True}
            except PublishError as error:
                fields = None
                manifest_check = {'ok': False, 'reason': error.message}
            try:
                preview = resolve_preview(api, project, manifest, payload)
                with tempfile.TemporaryDirectory(prefix='studio-cover-check-') as folder:
                    prepare_preview(api, preview, folder)
                preview_check = {'ok': True}
            except (PublishError, OSError) as error:
                preview_check = {'ok': False, 'reason': str(error)}
            binding = {}
            try:
                binding = read_sidecar(project)
                binding_check = {'ok': True, 'publishedFileId': str(binding.get('publishedFileId') or (manifest.get('metadata') or {}).get('id') or 0)}
            except PublishError as error:
                binding_check = {'ok': False, 'reason': str(error), 'publishedFileId': '0'}
            pending_path = project.path / 'StudentAgeStudio/workshop-pending.json'
            if pending_path.exists():
                binding_check['ok'] = False
                binding_check['reason'] = '上次创建条目的结果尚未确认，请先在 Steam 工坊核实，避免重复创建。'
        with self._lock:
            active = self._worker is not None and self._worker.is_alive()
            if self._closing or self._blocked:
                steam = {'available': False, 'reason': '上次操作尚未确认或编辑器正在关闭，请核实工坊后重启。', 'code': 'publish_unavailable'}
            elif active:
                steam = {'available': False, 'reason': '已有发布任务进行中，请等待结束。', 'code': 'publish_busy'}
            else:
                try:
                    info = self._bridge_instance().ensure_running(getattr(store, 'game', None))
                    steam = {'available': True, 'appId': info.get('appId', APP_ID)}
                except SteamBridgeError as error:
                    steam = {'available': False, 'reason': error.message, 'code': error.code}
            current_job = next((job.public() for job in reversed(list(self._jobs.values())) if job.project_id == project.id and (job.state not in self.TERMINAL or job.binding_pending)), None)
        return {'currentJob': current_job, 'ready': steam['available'] and manifest_check['ok'] and preview_check['ok'] and binding_check['ok'],
                'steam': steam, 'manifest': manifest_check, 'preview': preview_check, 'binding': binding_check,
                'revision': revision, 'fields': fields, 'defaults': {'title': manifest.get('title', project.id),
                'description': manifest.get('description', ''), 'tags': manifest.get('tags', []),
                'visibility': binding.get('visibility', VISIBILITY_PRIVATE)}, 'warnings': []}

    def start(self, store, api, payload, bridge=None):
        if not isinstance(payload, dict):
            raise PublishError('发布参数必须是对象。')
        with self._lock:
            if self._closing or self._blocked:
                raise PublishError('上次操作尚未确认或编辑器正在关闭，请核实后重启。', 409, 'publish_unavailable')
            if self._worker is not None and self._worker.is_alive():
                raise PublishError('已有发布任务进行中，请等待结束。', 409, 'publish_busy')
            project = store.project(payload.get('projectId'), writable=True)
            with store.lock:
                revision = store.revision(project)
                if not isinstance(payload.get('revision'), str) or payload['revision'] != revision:
                    raise PublishError('模组已经变化，请保存后重新检查发布内容。', 409, 'conflict')
                manifest = api.read_json(project.path / 'manifest.json', {})
                if not isinstance(manifest, dict):
                    raise PublishError('manifest.json 无效。', 422, 'publish_manifest_invalid')
                binding = read_sidecar(project)
                pending = project.path / 'StudentAgeStudio/workshop-pending.json'
                if pending.exists():
                    raise PublishError('上次创建条目结果未确认，请先核实工坊，不能重复创建。', 409, 'publish_result_unconfirmed')
                fields = normalize_payload(api, project, manifest, payload)
                metadata = manifest.get('metadata') if isinstance(manifest.get('metadata'), dict) else {}
                fields['packageId'] = str(metadata.get('packageId') or project.package)
                fields['version'] = str(metadata.get('version') or manifest.get('version') or '1.0.0')
                try:
                    fields['existingId'] = int(binding.get('publishedFileId') or metadata.get('id') or 0)
                    if not 0 <= fields['existingId'] < 2 ** 64:
                        raise ValueError()
                except (ValueError, TypeError):
                    raise PublishError('工坊条目编号无效，请修复绑定。', 422, 'publish_binding_invalid')
                preview_source = resolve_preview(api, project, manifest, payload)
            job = PublishJob(secrets.token_hex(8), project.id)
            job.fields = fields
            self._register(job)
            self._worker = threading.Thread(target=self._run, args=(store, api, job, project, revision, preview_source, bridge), daemon=True, name='workshop-publish')
            self._worker.start()
            return job.public()

    def cover(self, store, api, payload):
        from storage_paths import cache_root
        project = store.project(payload.get('projectId'), writable=True)
        encoded = payload.get('data')
        if not isinstance(encoded, str) or len(encoded) > PREVIEW_MAX * 2:
            raise PublishError('封面图片需要小于 1 MB。', 413, 'publish_preview_too_large')
        try:
            raw = base64.b64decode(encoded, validate=True)
        except ValueError:
            raise PublishError('图片编码无效。', 422, 'publish_preview_undecodable')
        folder = Path(cache_root()) / 'PublishPreviews' / hashlib.sha256(project.id.encode()).hexdigest()[:20]
        folder.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=folder) as temporary:
            source = Path(temporary) / 'input'
            source.write_bytes(raw)
            preview = prepare_preview(api, source, temporary)
            body = preview.read_bytes()
        target = folder / (hashlib.sha256(body).hexdigest() + '.jpg')
        api.atomic_write(target, body)
        return {'previewPath': str(target)}

    def bind_existing(self, store, api, payload):
        value = payload.get('publishedFileId')
        if not isinstance(value, str) or not value.isdigit() or not 0 < int(value) < 2 ** 64:
            raise PublishError('请输入有效的工坊条目编号。', 422, 'publish_binding_invalid')
        with self._lock:
            if self.busy() or self._closing:
                raise PublishError('请等待当前发布结束。', 409, 'publish_busy')
            project = store.project(payload.get('projectId'), writable=True)
            with store.lock:
                if payload.get('revision') != store.revision(project):
                    raise PublishError('模组已变化，请重新打开发布窗口。', 409, 'conflict')
                target = project.path / SIDECAR
                if target.exists():
                    api.atomic_write(target.with_name('workshop-binding-backup.json'), target.read_bytes())
                self._write_sidecar(api, project, int(value), {})
                (project.path / 'StudentAgeStudio/workshop-pending.json').unlink(missing_ok=True)
            return {'publishedFileId': value, 'revision': store.revision(project)}

    def recover_binding(self, store, api, payload):
        with self._lock:
            job = self._jobs.get(payload.get('jobId'))
            if not job or not job.published_file_id or job.state not in self.TERMINAL:
                raise PublishError('没有可恢复的发布绑定。', 409, 'publish_no_recovery')
            project = store.project(job.project_id, writable=True)
            with store.lock:
                self._write_sidecar(api, project, job.published_file_id, job.fields)
                (project.path / 'StudentAgeStudio/workshop-pending.json').unlink(missing_ok=True)
            job.binding_pending = False
            job.warnings = [message for message in job.warnings if '本地绑定未能写入' not in message]
            return job.public()

    def _bind(self, store, api, project, job):
        try:
            with store.lock:
                self._write_sidecar(api, project, job.published_file_id, job.fields)
                (project.path / 'StudentAgeStudio/workshop-pending.json').unlink(missing_ok=True)
            job.binding_pending = False
        except OSError:
            job.binding_pending = True
            job.warnings.append('工坊条目已保留，但本地绑定未能写入。请点击“重试保存绑定”，不要重新创建。')

    def _run(self, store, api, job, project, revision, preview_source, bridge):
        temporary = None
        try:
            job.state, job.phase = 'preflight', '准备上传副本'
            _check_cancelled(job)
            temporary = Path(tempfile.mkdtemp(prefix='student-age-publish-'))
            staged = temporary / 'content'
            staged.mkdir()
            with store.lock:
                if store.revision(project) != revision:
                    raise PublishError('暂存前模组发生变化，请重新检查。', 409, 'conflict')
                before = snapshot(project)
                files, total, skipped = stage_mod(api, project, staged)
                staged_project = type('Staged', (), {'path': staged})()
                if snapshot(staged_project) != before or snapshot(project) != before or store.revision(project) != revision:
                    raise PublishError('暂存时模组配置或素材发生变化，请重新发布。', 409, 'conflict')
                # Decode the captured project cover, never reopen the changing original.
                try:
                    cover = staged / preview_source.relative_to(project.path)
                except ValueError:
                    cover = preview_source
                prepare_preview(api, cover, staged)
            if total > WARNING_BYTES:
                job.warnings.append('内容超过 900 MB，上传可能较慢。')
            job.say(f'已准备 {files} 个文件；仅上传此副本。')
            _check_cancelled(job)
            bridge = bridge or self._bridge_instance()
            bridge.ensure_running(getattr(store, 'game', None))
            job.published_file_id = job.fields['existingId']
            if not job.published_file_id:
                job.state, job.phase = 'creating', '创建工坊条目'
                # Persist intent before remote creation, so a crash cannot silently retry.
                pending = project.path / 'StudentAgeStudio/workshop-pending.json'
                with store.lock:
                    pending.parent.mkdir(parents=True, exist_ok=True)
                    api.atomic_write(pending, api.json_bytes({'jobId': job.id, 'createdAt': job.created_at}))
                try:
                    job.published_file_id = bridge.create_item(timeout=CALLBACK_TIMEOUT)
                except SteamBridgeError as error:
                    if getattr(error, 'published_file_id', 0):
                        job.published_file_id = error.published_file_id
                        self._bind(store, api, project, job)
                    elif error.code == 'steam_create_failed':
                        with store.lock:
                            pending.unlink(missing_ok=True)
                    raise
                self._bind(store, api, project, job)
                if job.binding_pending:
                    raise PublishError('条目已创建，但本地绑定写入失败；恢复绑定后再上传。', 507, 'publish_binding_failed')
            _check_cancelled(job)
            result = self._submit_once(bridge, job, staged)
            if result != ERESULT_OK:
                code = 'steam_item_missing' if result == ERESULT_FILE_NOT_FOUND else 'steam_submit_failed'
                raise PublishError('Steam 未完成上传：' + bridge.describe_result(result) + '。' + ('请先核实该条目，编辑器不会自动另建。' if result == ERESULT_FILE_NOT_FOUND else ''), 502, code)
            # SubmitItemUpdate callback is the completion authority. Status 0 afterwards is normal.
            self._bind(store, api, project, job)
            job.state, job.phase, job.percent = 'done', '上传完成', 100
            if job.cancelled.is_set():
                job.warnings.append('停止请求前内容已提交，Steam 已确认上传成功。')
            job.say('上传完成：' + ITEM_URL.format(id=job.published_file_id))
        except _Cancelled:
            job.state, job.phase = 'cancelled', '已停止，尚未提交上传'
        except (PublishError, SteamBridgeError) as error:
            unknown = error.code in ('steam_create_timeout', 'steam_submit_timeout', 'steam_result_unconfirmed')
            job.state, job.phase = ('unconfirmed', '等待核实工坊结果') if unknown else ('error', '发布未完成')
            job.error = {'message': error.message, 'code': error.code}
            if unknown:
                self._blocked = True
        except Exception as error:
            job.state, job.phase = 'error', '发布未完成'
            job.error = {'message': '发布失败：' + str(error), 'code': 'internal_error'}
        finally:
            if temporary is not None and job.state != 'unconfirmed':
                shutil.rmtree(temporary, ignore_errors=True)
            if self._closing and bridge is not None:
                bridge.shutdown()
                with self._lock:
                    if self._bridge is bridge:
                        self._bridge = None

    def _submit_once(self, bridge, job, staged):
        job.state, job.phase, job.percent = 'updating', '准备提交', 8
        handle = bridge.start_update(job.published_file_id)
        fields = job.fields
        setters = [('标题', bridge.set_title, fields['title']),
                   ('简介', bridge.set_description, fields['description']),
                   ('可见性', bridge.set_visibility, fields['visibility']),
                   ('标签', bridge.set_tags, fields['tags']),
                   ('元数据', bridge.set_metadata, json.dumps({'id': job.published_file_id, 'version': fields['version'], 'packageId': fields['packageId']}, ensure_ascii=False)),
                   ('内容目录', bridge.set_content, str(staged)),
                   ('封面', bridge.set_preview, str(staged / 'preview.jpg'))]
        for label, setter, value in setters:
            _check_cancelled(job)
            if not setter(handle, value):
                raise PublishError('Steam 拒绝了' + label + '设置。', 502, 'steam_set_failed')
        _check_cancelled(job)
        job.state, job.phase, job.submitted = 'uploading', '正在上传', True
        def progress(value):
            job.processed_bytes = value['processedBytes']
            job.total_bytes = value['totalBytes']
            job.percent = min(99, 8 + int(90 * job.processed_bytes / job.total_bytes)) if job.total_bytes else 8
            if not job.cancelled.is_set():
                job.phase = '提交收尾' if value['status'] == 5 else '正在上传'
        return bridge.submit_update(handle, fields['changeNote'], timeout=JOB_TIMEOUT, progress=progress)

    @staticmethod
    def _write_sidecar(api, project, file_id, fields):
        body = {'publishedFileId': int(file_id), 'itemUrl': ITEM_URL.format(id=file_id),
                'visibility': fields.get('visibility', VISIBILITY_PRIVATE), 'lastPublishedAt': _utcnow(), 'lastChangeNote': fields.get('changeNote', ''), 'appId': APP_ID}
        target = project.path / SIDECAR
        target.parent.mkdir(parents=True, exist_ok=True)
        api.atomic_write(target, api.json_bytes(body))
