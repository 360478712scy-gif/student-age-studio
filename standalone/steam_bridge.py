"""Minimal Steamworks bridge for Workshop publishing.

Loads the MIT-licensed ``vendor-steamworks/SteamworksPy64.dll`` (a thin C++
bridge over Valve's ``steam_api``) with ctypes and exposes only the calls the
Workshop publisher needs. All function signatures are declared explicitly.

Valve's ``steam_api64.dll`` is proprietary and is NEVER shipped here: it is
loaded from the user's own game installation or Steam client directory
(see :func:`find_official_dll`).

Only Windows x64 is supported.
"""
import ctypes
import os
import sys
import threading
import time
from ctypes import c_bool, c_char_p, c_int, c_int32, c_uint32, c_uint64
from pathlib import Path

APP_ID = 1991040
BRIDGE_NAME = 'SteamworksPy64.dll'

# EWorkshopFileType (Valve public values).
FILE_TYPE_COMMUNITY = 0

# ERemoteStoragePublishedFileVisibility (Valve public values).
VISIBILITY_PUBLIC = 0
VISIBILITY_FRIENDS = 1
VISIBILITY_PRIVATE = 2

# EItemUpdateStatus (Valve public values).
UPDATE_STATUS_NAMES = {
    0: 'INVALID', 1: 'PREPARING_CONFIG', 2: 'PREPARING_CONTENT',
    3: 'UPLOADING_CONTENT', 4: 'UPLOADING_PREVIEW_FILE', 5: 'COMMITTING_CHANGES',
}

# EResult subset used for user-facing messages (Valve public values).
ERESULT_OK = 1
ERESULT_FAIL = 2
ERESULT_NO_CONNECTION = 3
ERESULT_INVALID_PARAM = 8
ERESULT_FILE_NOT_FOUND = 9
ERESULT_ACCESS_DENIED = 15
ERESULT_LIMIT_EXCEEDED = 25
ERESULT_TIMEOUT = 21


class SteamBridgeError(Exception):
    """Raised for every Steam runtime problem, with an API-style shape."""

    def __init__(self, message, status=503, code='steam_unavailable'):
        super().__init__(message)
        self.message, self.status, self.code = message, status, code


class CreateItemResult(ctypes.Structure):
    _fields_ = [('result', c_int), ('publishedFileId', c_uint64),
                ('userNeedsToAcceptWorkshopLegalAgreement', c_bool)]


class SubmitItemUpdateResult(ctypes.Structure):
    _fields_ = [('result', c_int),
                ('userNeedsToAcceptWorkshopLegalAgreement', c_bool),
                ('publishedFileId', c_uint64)]


BRIDGE_SHA256 = '2a5b09e8a0f76a083bac50e79462fdf9086edcc7346fef8561644fcaf2420d4b'


def packaged_bridge():
    import base64
    import hashlib
    import json
    from storage_paths import cache_root
    # The caller checks Windows before extracting any native file.
    try:
        resource = json.loads((Path(__file__).parent / 'steamworks-runtime.json').read_text('utf-8'))
        raw = base64.b64decode(resource['data'], validate=True)
        if hashlib.sha256(raw).hexdigest() != BRIDGE_SHA256:
            raise ValueError('hash mismatch')
        directory = Path(cache_root()) / 'SteamBridge' / BRIDGE_SHA256
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / BRIDGE_NAME
        if not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest() != BRIDGE_SHA256:
            import tempfile
            fd, name = tempfile.mkstemp(dir=directory, suffix='.tmp')
            try:
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(raw)
                os.replace(name, target)
            finally:
                Path(name).unlink(missing_ok=True)
        return target
    except (OSError, ValueError, KeyError) as error:
        raise SteamBridgeError('Steam 桥接组件缺失或损坏，请重新检查更新。', 503, 'steam_bridge_missing') from error


def bridge_candidates():
    """Ordered locations of our own MIT bridge DLL (never Valve's)."""
    here = Path(__file__).resolve().parent
    yield here / 'vendor-steamworks' / BRIDGE_NAME
    if getattr(sys, 'frozen', False):
        yield Path(sys.executable).resolve().parent / 'vendor-steamworks' / BRIDGE_NAME
        yield Path(sys.executable).resolve().parent / BRIDGE_NAME


def find_official_dll(game=None):
    """Locate the user's own Valve steam_api64.dll (game install, then client)."""
    seen = []
    if game is not None:
        seen.append(Path(game) / 'StudentAge_Data/Plugins/x86_64/steam_api64.dll')
    try:
        from game_locator import steam_roots
        for root in steam_roots():
            seen.append(Path(root) / 'steam_api64.dll')
    except Exception:
        pass
    for path in seen:
        try:
            if path.is_file():
                return path
        except OSError:
            continue
    return None


def _suppress_dialogs():
    """Block Windows error dialogs while probing native libraries."""
    if os.name != 'nt':
        return 0
    try:
        previous = ctypes.windll.kernel32.SetErrorMode(0x8001)
        return previous
    except (AttributeError, OSError):
        return 0


def _restore_dialogs(previous):
    if os.name == 'nt':
        try:
            ctypes.windll.kernel32.SetErrorMode(previous)
        except (AttributeError, OSError):
            pass


class SteamBridge:
    """One Steam session. All blocking waits carry timeouts; callbacks are
    pumped on a dedicated thread while a job is active. Instances are cheap
    to construct but SteamInit/Shutdown is process-global: use one per app."""

    def __init__(self, bridge_path=None, official_dll=None, app_id=APP_ID, cdll_factory=None):
        self.app_id = int(app_id)
        self.bridge_path = Path(bridge_path) if bridge_path else next(
            (p for p in bridge_candidates() if p.is_file()), None)
        self.official_dll = Path(official_dll) if official_dll else None
        self._factory = cdll_factory or ctypes.CDLL
        self._lib = None
        self._lock = threading.RLock()
        self._pump_stop = threading.Event()
        self._pump_thread = None
        # CFUNCTYPE handles MUST stay referenced or Steam will call into freed
        # memory and crash the process. Never drop these while initialized.
        self._on_created = None
        self._on_updated = None
        self._create_event = threading.Event()
        self._create_result = None
        self._update_event = threading.Event()
        self._update_result = None
        self._initialized = False
        self._dll_directory = None
        self._official_lib = None
        self._uncertain = False

    # ---- low-level library handling ----

    def _declare(self):
        lib = self._lib
        string = c_char_p
        lib.SteamInit.restype = c_int
        lib.SteamInit.argtypes = []
        lib.SteamShutdown.restype = None
        lib.SteamShutdown.argtypes = []
        lib.RunCallbacks.restype = None
        lib.RunCallbacks.argtypes = []
        lib.IsSteamRunning.restype = c_bool
        lib.IsSteamRunning.argtypes = []
        lib.Workshop_CreateItem.restype = None
        lib.Workshop_CreateItem.argtypes = [c_uint32, c_uint32]
        lib.Workshop_StartItemUpdate.restype = c_uint64
        lib.Workshop_StartItemUpdate.argtypes = [c_uint32, c_uint64]
        lib.Workshop_SetItemTitle.restype = c_bool
        lib.Workshop_SetItemTitle.argtypes = [c_uint64, string]
        lib.Workshop_SetItemDescription.restype = c_bool
        lib.Workshop_SetItemDescription.argtypes = [c_uint64, string]
        lib.Workshop_SetItemMetadata.restype = c_bool
        lib.Workshop_SetItemMetadata.argtypes = [c_uint64, string]
        lib.Workshop_SetItemVisibility.restype = c_bool
        lib.Workshop_SetItemVisibility.argtypes = [c_uint64, c_uint32]
        lib.Workshop_SetItemTags.restype = c_bool
        lib.Workshop_SetItemTags.argtypes = [c_uint64, ctypes.POINTER(c_char_p), c_int32]
        lib.Workshop_SetItemContent.restype = c_bool
        lib.Workshop_SetItemContent.argtypes = [c_uint64, string]
        lib.Workshop_SetItemPreview.restype = c_bool
        lib.Workshop_SetItemPreview.argtypes = [c_uint64, string]
        lib.Workshop_SubmitItemUpdate.restype = None
        lib.Workshop_SubmitItemUpdate.argtypes = [c_uint64, string]
        lib.Workshop_GetItemUpdateProgress.restype = c_uint32
        lib.Workshop_GetItemUpdateProgress.argtypes = [c_uint64, ctypes.POINTER(c_uint64), ctypes.POINTER(c_uint64)]
        lib.Workshop_SetItemCreatedCallback.restype = None
        lib.Workshop_SetItemUpdatedCallback.restype = None

    def _register_callbacks(self):
        created_type = ctypes.CFUNCTYPE(None, CreateItemResult)
        updated_type = ctypes.CFUNCTYPE(None, SubmitItemUpdateResult)

        def on_created(result):
            self._create_result = (result.result, result.publishedFileId,
                                   bool(result.userNeedsToAcceptWorkshopLegalAgreement))
            self._create_event.set()

        def on_updated(result):
            self._update_result = (result.result,
                                   bool(result.userNeedsToAcceptWorkshopLegalAgreement))
            self._update_event.set()

        # Held on self for the whole session (see class docstring).
        self._on_created = created_type(on_created)
        self._on_updated = updated_type(on_updated)
        self._lib.Workshop_SetItemCreatedCallback.argtypes = [created_type]
        self._lib.Workshop_SetItemUpdatedCallback.argtypes = [updated_type]
        self._lib.Workshop_SetItemCreatedCallback(self._on_created)
        self._lib.Workshop_SetItemUpdatedCallback(self._on_updated)

    # ---- session lifecycle ----

    def ensure_running(self, game=None, timeout=30):
        """Load libraries, init Steam and verify the client session.

        Returns ``{'appId': ..., 'officialDll': ...}``. Raises
        :class:`SteamBridgeError` with a user-facing message otherwise.
        """
        with self._lock:
            if self._uncertain:
                raise SteamBridgeError('上次 Steam 操作尚未确认，请先检查工坊条目并重新启动编辑器。', 409, 'steam_result_unconfirmed')
            if self._initialized:
                return {'appId': self.app_id, 'officialDll': str(self.official_dll)}
            if os.name != 'nt' or sys.maxsize <= 2 ** 32:
                raise SteamBridgeError('创意工坊上传目前仅支持 Windows 64 位，请在 Windows 客户端中发布。',
                                       503, 'steam_unsupported_platform')
            if self.bridge_path is None:
                self.bridge_path = packaged_bridge()
            if self.official_dll is None:
                found = find_official_dll(game)
                if found is None:
                    raise SteamBridgeError(
                        '未找到 Steam 运行环境：在游戏目录或 Steam 客户端中没有 steam_api64.dll。'
                        '请确认游戏是通过 Steam 安装的。', 503, 'steam_api_missing')
                self.official_dll = found
            if self._factory is ctypes.CDLL:
                import hashlib
                if hashlib.sha256(self.bridge_path.read_bytes()).hexdigest() != BRIDGE_SHA256:
                    raise SteamBridgeError('Steam 桥接组件校验失败，请重新检查更新。', 503, 'steam_bridge_invalid')
            previous_mode = _suppress_dialogs()
            try:
                try:
                    self._dll_directory = os.add_dll_directory(str(self.official_dll.parent))
                except (AttributeError, OSError):
                    pass
                try:
                    self._official_lib = self._factory(str(self.official_dll.resolve()))
                    self._lib = self._factory(str(self.bridge_path.resolve()))
                except OSError as error:
                    raise SteamBridgeError(
                        f'无法加载 Steam 桥接组件：{error}。请重新安装完整客户端。',
                        503, 'steam_bridge_load_failed')
                self._declare()
                old_appid = os.environ.get('SteamAppId')
                os.environ['SteamAppId'] = str(self.app_id)
                try:
                    initialized = self._lib.SteamInit()
                finally:
                    if old_appid is None:
                        os.environ.pop('SteamAppId', None)
                    else:
                        os.environ['SteamAppId'] = old_appid
                self._initialized = True
                if initialized != 0:
                    raise SteamBridgeError(
                        'Steam 初始化失败。请先启动并登录 Steam 客户端（需要拥有《学生时代》），'
                        '然后重试。', 503, 'steam_init_failed')
                self._initialized = True
                try:
                    running = self._lib.IsSteamRunning()
                except (OSError, ValueError, ctypes.ArgumentError):
                    running = False
                if not running:
                    raise SteamBridgeError('Steam 客户端未运行。请先启动并登录 Steam，然后重试。',
                                           503, 'steam_not_running')
                self._register_callbacks()
                self._initialized = True
                return {'appId': self.app_id, 'officialDll': str(self.official_dll)}
            except Exception:
                self.shutdown()
                raise
            finally:
                _restore_dialogs(previous_mode)

    def shutdown(self):
        # Native callbacks must finish before releasing either library/search handle.
        self.stop_pump()
        with self._lock:
            if self._pump_thread is not None and self._pump_thread.is_alive():
                return False
            if self._initialized and self._lib is not None:
                self._lib.SteamShutdown()
            self._initialized = False
            self._lib = None
            self._official_lib = None
            if self._dll_directory is not None:
                self._dll_directory.close()
                self._dll_directory = None
        return True

    # ---- callback pump (only while a job is active) ----

    def start_pump(self, interval=0.05):
        with self._lock:
            if self._pump_thread is not None and self._pump_thread.is_alive():
                return
            self._pump_stop.clear()

            def loop():
                while not self._pump_stop.is_set():
                    try:
                        self._lib.RunCallbacks()
                    except (OSError, ValueError, ctypes.ArgumentError):
                        pass
                    self._pump_stop.wait(interval)

            self._pump_thread = threading.Thread(target=loop, daemon=True, name='steam-callbacks')
            self._pump_thread.start()

    def stop_pump(self):
        thread = None
        with self._lock:
            self._pump_stop.set()
            thread = self._pump_thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=5)
        if thread is None or not thread.is_alive():
            self._pump_thread = None

    # ---- UGC operations (require ensure_running first) ----

    def _require(self):
        if not self._initialized or self._lib is None:
            raise SteamBridgeError('Steam 会话尚未建立，请先完成预检。', 503, 'steam_not_initialized')

    def create_item(self, timeout=120):
        """Create a new Workshop entry; returns the published file id."""
        self._require()
        self._create_event.clear()
        self._create_result = None
        self.start_pump()
        self._lib.Workshop_CreateItem(c_uint32(self.app_id), c_uint32(FILE_TYPE_COMMUNITY))
        if not self._create_event.wait(timeout):
            self._uncertain = True
            raise SteamBridgeError('创建工坊条目超时（Steam 无响应），请稍后重试。', 504, 'steam_create_timeout')
        self.stop_pump()
        result, file_id, needs_agreement = self._create_result
        if needs_agreement:
            error = SteamBridgeError(
                '需要先同意 Steam 创意工坊法律协议：'
                'https://steamcommunity.com/sharedfiles/workshopagreement',
                403, 'steam_legal_agreement')
            error.published_file_id = int(file_id)
            raise error
        if result != ERESULT_OK or not file_id:
            raise SteamBridgeError(
                '创建工坊条目失败：' + self.describe_result(result) + '。', 502, 'steam_create_failed')
        return int(file_id)

    def start_update(self, published_file_id):
        self._require()
        handle = self._lib.Workshop_StartItemUpdate(c_uint32(self.app_id), c_uint64(int(published_file_id)))
        if not handle:
            raise SteamBridgeError('无法开始物品更新（Steam 拒绝了更新句柄）。', 502, 'steam_update_start_failed')
        return int(handle)

    @staticmethod
    def _encode(text):
        return str(text or '').encode('utf-8')

    def set_title(self, handle, title):
        return bool(self._lib.Workshop_SetItemTitle(c_uint64(handle), self._encode(title)))

    def set_description(self, handle, description):
        return bool(self._lib.Workshop_SetItemDescription(c_uint64(handle), self._encode(description)))

    def set_metadata(self, handle, metadata):
        return bool(self._lib.Workshop_SetItemMetadata(c_uint64(handle), self._encode(metadata)))

    def set_visibility(self, handle, visibility):
        return bool(self._lib.Workshop_SetItemVisibility(c_uint64(handle), c_uint32(int(visibility))))

    def set_tags(self, handle, tags):
        cleaned = [str(tag).strip() for tag in (tags or []) if str(tag).strip()]
        array = (c_char_p * len(cleaned))(*[tag.encode('utf-8') for tag in cleaned])
        return bool(self._lib.Workshop_SetItemTags(c_uint64(handle), array, c_int32(len(cleaned))))

    def set_content(self, handle, directory):
        return bool(self._lib.Workshop_SetItemContent(c_uint64(handle), self._encode(directory)))

    def set_preview(self, handle, image_path):
        return bool(self._lib.Workshop_SetItemPreview(c_uint64(handle), self._encode(image_path)))

    def submit_update(self, handle, change_note, timeout=1800, progress=None):
        self._require()
        self._update_event.clear()
        self._update_result = None
        self.start_pump()
        self._lib.Workshop_SubmitItemUpdate(c_uint64(handle), self._encode(change_note))
        deadline = time.monotonic() + timeout
        last_bytes, last_change = -1, time.monotonic()
        while not self._update_event.wait(.2):
            current = self.update_progress(handle)
            if progress:
                progress(current)
            if current['processedBytes'] != last_bytes:
                last_bytes, last_change = current['processedBytes'], time.monotonic()
            if time.monotonic() >= deadline or time.monotonic() - last_change > 600:
                self._uncertain = True
                raise SteamBridgeError('Steam 尚未确认上传结果，请通过条目链接确认后重启编辑器。', 504, 'steam_submit_timeout')
        self.stop_pump()
        result, needs_agreement = self._update_result
        if needs_agreement:
            raise SteamBridgeError(
                '需要先同意 Steam 创意工坊法律协议：'
                'https://steamcommunity.com/sharedfiles/workshopagreement',
                403, 'steam_legal_agreement')
        return int(result)

    def update_progress(self, handle):
        self._require()
        processed = c_uint64(0)
        total = c_uint64(0)
        status = int(self._lib.Workshop_GetItemUpdateProgress(
            c_uint64(handle), ctypes.byref(processed), ctypes.byref(total)))
        return {'status': status, 'phase': UPDATE_STATUS_NAMES.get(status, 'UNKNOWN'),
                'processedBytes': int(processed.value), 'totalBytes': int(total.value)}

    # ---- result vocabulary ----

    @staticmethod
    def describe_result(code):
        return {
            ERESULT_OK: '成功',
            ERESULT_FAIL: '失败（可在 Steam/logs/workshop_log.txt 查看服务端原因）',
            ERESULT_NO_CONNECTION: '网络未连接',
            ERESULT_INVALID_PARAM: '参数无效',
            ERESULT_FILE_NOT_FOUND: '物品不存在（可能已被删除）',
            ERESULT_ACCESS_DENIED: '无权限（不是该物品的作者吗）',
            ERESULT_LIMIT_EXCEEDED: '超出 Steam 限制',
            ERESULT_TIMEOUT: 'Steam 超时',
        }.get(int(code), f'Steam 返回码 {code}')
