"""Upload local mods to the Steam Workshop (backend only, no UI here).

Flow per job: validate payload -> stage a clean copy -> create-or-reuse the
Workshop entry -> fill title/description/visibility/tags/metadata/content/
preview -> submit -> poll progress -> persist the published id to a sidecar.

Only ``local:`` projects may publish. Valve's ``steam_api`` is never shipped:
see :mod:`steam_bridge`. The future frontend wizard drives this through
``POST /api/publish`` (202), ``GET /api/publish-status`` and
``POST /api/publish-cancel``.
"""
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
STAGING_SKIP_FILES = {'.save.lock', 'workshop.json'}


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
    try:
        data = json.loads((project.path / SIDECAR).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


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
            if source.is_symlink() or name in STAGING_SKIP_FILES or name.endswith(('.tmp', '.log')):
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
        with Image.open(Path(source_file)) as image:
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
    visibility = payload.get('visibility', manifest.get('visible', VISIBILITY_PRIVATE))
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

    def say(self, message):
        self.log.append(message)
        del self.log[:max(0, len(self.log) - 100)]

    def public(self):
        body = {'jobId': self.id, 'projectId': self.project_id, 'state': self.state,
                'phase': self.phase, 'percent': self.percent,
                'processedBytes': self.processed_bytes, 'totalBytes': self.total_bytes,
                'log': list(self.log), 'warnings': list(self.warnings),
                'createdAt': self.created_at}
        if self.published_file_id:
            body['publishedFileId'] = self.published_file_id
            body['itemUrl'] = ITEM_URL.format(id=self.published_file_id)
        if self.error:
            body['error'] = self.error
        if self.state == 'cancelled':
            body['note'] = '已停止轮询；若提交已发出，服务端仍可能收录，请用物品链接确认。'
        return body


class Publisher:
    """Owns publish jobs and the single Steam session. Construct cheaply and
    share on the server object; pass ``bridge_factory`` in tests."""

    def __init__(self, bridge_factory=None):
        self._lock = threading.RLock()
        self._jobs = {}
        self._bridge = None
        self._bridge_factory = bridge_factory or SteamBridge

    # ---- job registry ----

    def _register(self, job):
        with self._lock:
            self._jobs[job.id] = job
            while len(self._jobs) > 32:
                self._jobs.pop(next(iter(self._jobs)))

    def status(self, job_id):
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            return job.public()

    def cancel(self, job_id):
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            return None
        job.cancelled.set()
        if job.state not in ('done', 'error'):
            job.state = 'cancelled'
            job.phase = '已取消'
            job.say('用户取消：停止轮询。')
        return job.public()

    def _bridge_instance(self, game=None):
        with self._lock:
            if self._bridge is None:
                self._bridge = self._bridge_factory()
            return self._bridge

    def close(self):
        with self._lock:
            bridge, self._bridge = self._bridge, None
        if bridge is not None:
            try:
                bridge.shutdown()
            except Exception:
                pass

    # ---- preflight (no side effects beyond a Steam session) ----

    def prereq(self, store, api, project_id):
        project = store.project(project_id, writable=True)
        manifest = api.read_json(project.path / 'manifest.json', {})
        if not isinstance(manifest, dict):
            manifest = {}
        warnings = []
        try:
            normalize_payload(api, project, manifest, {})
        except PublishError as error:
            manifest_check = {'ok': False, 'reason': error.message}
        else:
            manifest_check = {'ok': True}
        preview = project.path / 'preview.jpg'
        try:
            preview_ok = preview.is_file() and preview.stat().st_size <= PREVIEW_MAX
        except OSError:
            preview_ok = False
        try:
            bridge = self._bridge_instance(getattr(store, 'game', None))
            info = bridge.ensure_running(getattr(store, 'game', None))
            steam = {'available': True, 'appId': info.get('appId', APP_ID)}
        except SteamBridgeError as error:
            steam = {'available': False, 'reason': error.message, 'code': error.code}
        except PublishError as error:
            steam = {'available': False, 'reason': error.message, 'code': error.code}
        binding = read_sidecar(project)
        try:
            talk_files = sum(1 for _ in (project.path / 'Cfgs/zh-cn').glob('*.json'))
        except OSError:
            talk_files = 0
        if not talk_files:
            warnings.append('Cfgs/zh-cn 为空，上传后游戏中可能没有内容。')
        return {'ready': bool(steam['available'] and manifest_check['ok'] and preview_ok),
                'steam': steam, 'manifest': manifest_check,
                'preview': {'ok': preview_ok} if preview_ok else {
                    'ok': False, 'reason': '缺少 preview.jpg（≤1MB），请先准备封面。'},
                'binding': {'publishedFileId': int(binding.get('publishedFileId') or 0)},
                'warnings': warnings}

    # ---- publish entry ----

    def start(self, store, api, payload, bridge=None):
        if not isinstance(payload, dict):
            raise PublishError('发布参数必须是对象。')
        project = store.project(payload.get('projectId'), writable=True)
        expected = payload.get('revision')
        revision = store.revision(project)
        if not isinstance(expected, str) or expected != revision:
            raise PublishError('发布前模组已经变化，请保存后重新发布。', 409, 'conflict')
        manifest = api.read_json(project.path / 'manifest.json', {})
        if not isinstance(manifest, dict):
            raise PublishError('manifest.json 无效，请先修复模组信息。', 422, 'publish_manifest_invalid')
        fields = normalize_payload(api, project, manifest, payload)
        metadata = manifest.get('metadata') if isinstance(manifest.get('metadata'), dict) else {}
        fields['packageId'] = str(metadata.get('packageId') or project.package)
        preview_source = resolve_preview(api, project, manifest, payload)
        job = PublishJob(secrets.token_hex(8), project.id)
        self._register(job)
        worker = threading.Thread(target=self._run, args=(store, api, job, project, revision, fields, preview_source, bridge),
                                  daemon=True, name='workshop-publish')
        worker.start()
        return job.public()

    # ---- worker ----

    def _run(self, store, api, job, project, revision, fields, preview_source, bridge):
        started = time.monotonic()
        temporary = None
        try:
            job.state = 'preflight'
            job.phase = '准备上传内容'
            job.say('revision 已确认，开始暂存。')
            if store.revision(project) != revision:
                raise PublishError('暂存前模组发生变化，已中止；请重新发布。', 409, 'conflict')
            temporary = Path(tempfile.mkdtemp(prefix='student-age-publish-'))
            staged = temporary / 'content'
            staged.mkdir()
            files, total, skipped = stage_mod(api, project, staged)
            if skipped:
                job.warnings.append('跳过 ' + str(len(skipped)) + ' 个编辑器临时文件。')
            if total > WARNING_BYTES:
                job.warnings.append('内容超过 900 MB，上传可能很慢或被 Steam 限制。')
            job.say(f'已暂存 {files} 个文件。')
            prepare_preview(api, preview_source, staged)
            if store.revision(project) != revision:
                raise PublishError('暂存后模组发生变化，已中止；请重新发布。', 409, 'conflict')
            job.state = 'staging'
            job.percent = 5
            bridge = bridge or self._bridge_instance(getattr(store, 'game', None))
            try:
                bridge.ensure_running(getattr(store, 'game', None))
            except SteamBridgeError as error:
                raise PublishError(error.message, error.status, error.code)
            binding = read_sidecar(project)
            file_id = int(binding.get('publishedFileId') or 0)
            if file_id:
                job.say(f'复用工坊条目 {file_id}。')
            else:
                job.state = 'creating'
                job.phase = '创建工坊条目'
                job.say('创建新的工坊条目…')
                file_id = bridge.create_item(timeout=CALLBACK_TIMEOUT)
                _check_cancelled(job)
                job.published_file_id = file_id
                job.say(f'已创建条目 {file_id}，继续填写内容…')
            try:
                result, handle = self._submit_once(api, bridge, job, file_id, fields, staged)
                _check_cancelled(job)
            except PublishError as error:
                if error.code == 'steam_item_missing':
                    # The item was deleted on the Workshop; forget the binding
                    # and create a fresh entry once, then submit again.
                    job.say('原条目在工坊已不存在，重新创建…')
                    self._write_sidecar(api, project, 0, fields)
                    job.published_file_id = 0
                    file_id = bridge.create_item(timeout=CALLBACK_TIMEOUT)
                    job.published_file_id = file_id
                    result, handle = self._submit_once(api, bridge, job, file_id, fields, staged)
                else:
                    raise
            if result != ERESULT_OK:
                raise PublishError('提交更新失败：' + bridge.describe_result(result) + '。',
                                   502, 'steam_submit_failed')
            self._poll_until_done(bridge, job, handle, started)
            if job.cancelled.is_set():
                job.state = 'cancelled'
                job.phase = '已取消'
                return
            self._write_sidecar(api, project, file_id, fields)
            job.published_file_id = file_id
            job.state = 'done'
            job.phase = '上传完成'
            job.percent = 100
            job.say('上传完成：' + ITEM_URL.format(id=file_id))
        except _Cancelled:
            job.state = 'cancelled'
            job.phase = '已取消'
            job.say('用户取消：停止轮询。')
        except PublishError as error:
            if job.state != 'cancelled':
                job.state = 'error'
                job.phase = '失败'
                job.error = {'message': error.message, 'code': error.code}
                job.say('失败：' + error.message)
        except SteamBridgeError as error:
            if job.state != 'cancelled':
                job.state = 'error'
                job.phase = '失败'
                job.error = {'message': error.message, 'code': error.code}
                job.say('失败：' + error.message)
        except Exception as error:
            if job.state != 'cancelled':
                job.state = 'error'
                job.phase = '失败'
                job.error = {'message': f'上传出现未预期的错误：{error}', 'code': 'internal_error'}
                job.say(job.error['message'])
        finally:
            if temporary is not None:
                shutil.rmtree(temporary, ignore_errors=True)

    def _submit_once(self, api, bridge, job, file_id, fields, staged):
        job.state = 'updating'
        job.phase = '填写条目内容并提交'
        job.percent = 8
        try:
            handle = bridge.start_update(file_id)
        except SteamBridgeError as error:
            raise PublishError(error.message, error.status, error.code)
        setters = [('标题', bridge.set_title, fields['title']),
                   ('简介', bridge.set_description, fields['description']),
                   ('可见性', bridge.set_visibility, fields['visibility']),
                   ('标签', bridge.set_tags, fields['tags']),
                   ('元数据', bridge.set_metadata, self._metadata_json(api, file_id, fields)),
                   ('内容目录', bridge.set_content, str(staged)),
                   ('封面', bridge.set_preview, str(staged / 'preview.jpg'))]
        for label, setter, value in setters:
            try:
                ok = setter(handle, value)
            except SteamBridgeError as error:
                raise PublishError(error.message, error.status, error.code)
            if not ok:
                raise PublishError(f'Steam 拒绝了{label}设置。', 502, 'steam_set_failed')
        job.say('已提交，等待 Steam 处理…')
        try:
            result = bridge.submit_update(handle, fields['changeNote'], timeout=CALLBACK_TIMEOUT)
        except SteamBridgeError as error:
            raise PublishError(error.message, error.status, error.code)
        if result == ERESULT_FILE_NOT_FOUND:
            raise PublishError('工坊上找不到该条目（可能已被删除），将重新创建。',
                               502, 'steam_item_missing')
        return result, handle

    @staticmethod
    def _metadata_json(api, file_id, fields):
        return json.dumps({'id': int(file_id), 'version': '1.0.0', 'packageId': fields.get('packageId', '')},
                          ensure_ascii=False, separators=(',', ':'))

    def _poll_until_done(self, bridge, job, handle, started):
        last_change = time.monotonic()
        last_processed = -1
        while True:
            if job.cancelled.is_set():
                return
            if time.monotonic() - started > JOB_TIMEOUT:
                raise PublishError('上传超过 30 分钟仍未完成，已中止；请用物品链接确认状态。',
                                   504, 'publish_timeout')
            try:
                progress = bridge.update_progress(handle)
            except SteamBridgeError as error:
                raise PublishError(error.message, error.status, error.code)
            total = progress['totalBytes']
            processed = progress['processedBytes']
            job.processed_bytes = processed
            job.total_bytes = total
            status = progress['status']
            if status in (3, 4):
                job.phase = '正在上传' + ('封面' if status == 4 else '内容')
                job.percent = min(99, 8 + int(88 * processed / total)) if total else 10
            elif status == 5:
                job.phase = '提交收尾'
                job.percent = 99
            elif status in (1, 2):
                job.phase = '准备中'
                job.percent = 6
            else:
                job.phase = '等待 Steam'
            if processed != last_processed:
                last_processed = processed
                last_change = time.monotonic()
            elif time.monotonic() - last_change > STALL_TIMEOUT:
                raise PublishError('上传 10 分钟没有进展，已中止；请用物品链接确认状态。',
                                   504, 'publish_stalled')
            if total and processed >= total and status == 5:
                return
            if total and processed >= total:
                # Bytes are there; give the commit a grace window.
                time.sleep(2)
                continue
            time.sleep(1.5)

    @staticmethod
    def _write_sidecar(api, project, file_id, fields):
        body = {'publishedFileId': int(file_id),
                'itemUrl': ITEM_URL.format(id=file_id) if file_id else '',
                'lastPublishedAt': _utcnow(), 'lastChangeNote': fields.get('changeNote', ''),
                'appId': APP_ID}
        target = project.path / SIDECAR
        target.parent.mkdir(parents=True, exist_ok=True)
        api.atomic_write(target, api.json_bytes(body))
