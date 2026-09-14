import AppKit
import WebKit

final class StudioWindow: NSWindow {
    override func cancelOperation(_ sender: Any?) { /* Escape is handled by the editor. */ }
}

final class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate, WKUIDelegate, WKNavigationDelegate, WKScriptMessageHandler {
    var window: NSWindow!
    var web: WKWebView!
    var server: Process?
    var readyFile: URL!
    var attempts = 0
    var readyTimer: Timer?
    var allowedOrigin: String?
    var isClosing = false
    var assetFolderPanel: NSOpenPanel?
    var closeRequestID: String?
    var closeErrorBanner: NSBox?
    var terminationReply: (Bool) -> Void = { NSApp.reply(toApplicationShouldTerminate: $0) }
    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        let menu = NSMenu(); let appItem = NSMenuItem(); menu.addItem(appItem)
        let appMenu = NSMenu(); appMenu.addItem(withTitle: "退出拾光工坊", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q"); appItem.submenu = appMenu
        let editItem = NSMenuItem(); menu.addItem(editItem); let edit = NSMenu(title: "编辑"); editItem.submenu = edit
        edit.addItem(withTitle: "撤销", action: Selector(("undo:")), keyEquivalent: "z")
        edit.addItem(withTitle: "剪切", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        edit.addItem(withTitle: "复制", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        edit.addItem(withTitle: "粘贴", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        edit.addItem(withTitle: "全选", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        NSApp.mainMenu = menu
        window = StudioWindow(contentRect: NSRect(x: 0,y: 0,width: 1440,height: 920), styleMask: [.titled,.closable,.miniaturizable,.resizable], backing: .buffered, defer: false)
        let version = Bundle.main.object(forInfoDictionaryKey: "StudioVersion") as? String ?? "b1.2.0hotfix"
        window.title = "拾光工坊·模组编辑器-\(version)"; window.minSize = NSSize(width: 1000,height: 680); if let screen = NSScreen.main { window.setFrame(screen.visibleFrame, display: false) }; window.delegate = self
        window.backgroundColor = NSColor(red: 0.957,green: 0.965,blue: 0.980,alpha: 1)
        let config = WKWebViewConfiguration(); config.websiteDataStore = .nonPersistent()
        config.mediaTypesRequiringUserActionForPlayback = []
        config.userContentController.add(self, name: "studioCloseDecision")
        config.userContentController.add(self, name: "studioAssetFolder")
        web = WKWebView(frame: window.contentView!.bounds, configuration: config)
        web.autoresizingMask = [.width,.height]; web.uiDelegate = self; web.navigationDelegate = self
        window.contentView!.addSubview(web); window.makeKeyAndOrderFront(nil); NSApp.activate(ignoringOtherApps: true)
        let sourceRoot = ProcessInfo.processInfo.environment["STUDIO_SOURCE_ROOT"]
        let resourceRoot = sourceRoot.map { URL(fileURLWithPath:$0) } ?? Bundle.main.resourceURL!
        if sourceRoot != nil { window.title = "拾光工坊 · 源码预览（未打包）" }
        let logoURL = resourceRoot.appendingPathComponent("standalone/icon.png")
        let logo = (try? Data(contentsOf:logoURL).base64EncodedString()) ?? ""
        web.loadHTMLString("<body style='margin:0;background:radial-gradient(ellipse at top left,#dceaff,transparent 65%),#f4f6fa;color:#243246;font-family:system-ui;display:grid;place-items:center;height:100vh'><div style='text-align:center'><img width='112' height='112' src='data:image/png;base64,\(logo)'><h1 style='font-size:40px;letter-spacing:.2em;margin:24px 0 8px'>拾光工坊</h1><p style='color:#5a687b'>学生时代模组编辑器</p></div></body>",baseURL:nil)
        startServer(resourceRoot: resourceRoot, sourceRoot: sourceRoot)
    }
    func startServer(resourceRoot: URL, sourceRoot: String?) {
        do {
            let resource = resourceRoot
            let program = resource.appendingPathComponent("standalone/update_bootstrap.py")
            let bundledPython = Bundle.main.resourceURL!.appendingPathComponent("python/bin/python3").path
            let executable = ProcessInfo.processInfo.environment["STUDIO_PYTHON"] ?? (FileManager.default.fileExists(atPath: bundledPython) ? bundledPython : "/Library/Frameworks/Python.framework/Versions/3.14/bin/python3")
            guard FileManager.default.fileExists(atPath: executable) else { throw NSError(domain:"Studio",code:1,userInfo:[NSLocalizedDescriptionKey:"应用运行环境不完整，请重新解压完整的 Mac 版应用。"])}
            readyFile = FileManager.default.temporaryDirectory.appendingPathComponent("student-age-studio-\(UUID().uuidString).json")
            let p = Process(); p.executableURL = URL(fileURLWithPath: executable)
            p.arguments = ["-B","-u",program.path,"--port","0","--ready-file",readyFile.path]
            var environment = ProcessInfo.processInfo.environment
            environment.removeValue(forKey: "PYTHONHOME"); environment.removeValue(forKey: "PYTHONPATH")
            environment["PYTHONNOUSERSITE"] = "1"; environment["PYTHONDONTWRITEBYTECODE"] = "1"
            environment["STUDIO_UPDATE_MANAGED"] = sourceRoot == nil ? "1" : "0"
            p.terminationHandler = { [weak self] child in
                DispatchQueue.main.async {
                    guard let self = self, !self.isClosing, child.terminationStatus == 42 else { return }
                    self.readyTimer?.invalidate(); self.attempts = 0; self.allowedOrigin = nil
                    self.startServer(resourceRoot: resourceRoot, sourceRoot: sourceRoot)
                }
            }
            p.environment = environment; p.currentDirectoryURL = resource
            p.standardOutput = FileHandle.nullDevice; p.standardError = FileHandle.nullDevice
            try p.run(); server = p
            readyTimer = Timer.scheduledTimer(withTimeInterval: 0.15,repeats: true) { [weak self] _ in self?.checkReady() }
        } catch { fail(error.localizedDescription) }
    }
    func checkReady() {
        attempts += 1
        if let bytes = try? Data(contentsOf: readyFile), let json = try? JSONSerialization.jsonObject(with: bytes) as? [String:Any], let text = json["url"] as? String, let url = URL(string:text) {
            readyTimer?.invalidate(); allowedOrigin = "\(url.scheme!)://\(url.host!):\(url.port!)"; web.load(URLRequest(url:url)); try? FileManager.default.removeItem(at:readyFile)
        } else if attempts > 200 || server?.isRunning == false { readyTimer?.invalidate(); fail("编辑服务未能启动。可以从项目目录运行 standalone/server.py 查看原因。") }
    }
    func fail(_ text:String) {
        let escaped = text.replacingOccurrences(of: "&", with: "&amp;").replacingOccurrences(of: "<", with: "&lt;").replacingOccurrences(of: ">", with: "&gt;").replacingOccurrences(of: "\"", with: "&quot;")
        web.loadHTMLString("""
        <!doctype html><html lang="zh-CN"><meta charset="utf-8"><style>
        body{margin:0;min-height:100vh;display:grid;place-items:center;background:#f4f6fa;color:#243246;font:16px/1.8 system-ui}
        main{max-width:620px;padding:36px;border:1px solid #d5dfea;border-radius:12px;background:#ffffff}h1{font-size:24px;margin-top:0}p{white-space:pre-wrap;overflow-wrap:anywhere}.hint{color:#5a687b}
        </style><main><h1>工作台启动失败</h1><p>\(escaped)</p><p class="hint">关闭此窗口后，可以重新打开工作台。</p></main></html>
        """,baseURL:nil)
    }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender:NSApplication)->Bool { true }
    func applicationShouldTerminate(_ sender:NSApplication)->NSApplication.TerminateReply {
        if isClosing || web == nil { return .terminateNow }
        if closeRequestID != nil { return .terminateLater }
        dismissCloseError()
        let requestID = UUID().uuidString; closeRequestID = requestID
        // evaluateJavaScript cannot return a JavaScript Promise as a Swift Bool.
        // Resolve the complete editor/workshop guard in the page, then reply once.
        web.evaluateJavaScript("""
        (() => {
          const id = '\(requestID)';
          const reply = (allowed, error) => window.webkit.messageHandlers.studioCloseDecision.postMessage({id, allowed: allowed === true, error: error || ''});
          if (typeof window.STUDIO_REQUEST_CLOSE !== 'function') { reply(true); return; }
          Promise.resolve().then(() => window.STUDIO_REQUEST_CLOSE()).then(value => reply(value), error => reply(false, String(error)));
        })();
        """) { [weak self] _,error in
            if let error=error { self?.finishClose(requestID, allowed:false, error:error.localizedDescription) }
        }
        return .terminateLater
    }
    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        if message.name == "studioAssetFolder" {
            guard message.frameInfo.isMainFrame, message.webView === web,
                  let request = message.body as? [String:Any], let id = request["id"] as? String,
                  let kind = request["kind"] as? String, ["portrait", "background", "cg", "audio", "social", "avatar", "mods", "game", "cache"].contains(kind) else { return }
            chooseAssetFolder(id, kind:kind)
            return
        }
        guard message.name == "studioCloseDecision", message.frameInfo.isMainFrame, message.webView === web,
              let result=message.body as? [String:Any], let requestID=result["id"] as? String,
              requestID == closeRequestID else { return }
        finishClose(requestID, allowed:result["allowed"] as? Bool == true, error:result["error"] as? String)
    }
    func chooseAssetFolder(_ id:String, kind:String) {
        guard assetFolderPanel == nil else { finishAssetFolder(id, path:nil); return }
        let panel=NSOpenPanel();assetFolderPanel=panel
        panel.canChooseDirectories=true;panel.canChooseFiles=false;panel.allowsMultipleSelection=false;panel.canCreateDirectories=true
        panel.title="选择" + (["portrait":"人物立绘", "background":"场景", "cg":"CG", "audio":"声音", "social":"动态配图", "avatar":"人物头像", "mods":"可编辑模组", "game":"游戏", "cache":"缓存"][kind] ?? "素材") + "文件夹"
        panel.prompt="使用此文件夹"
        panel.beginSheetModal(for:window) { [weak self] result in
            self?.assetFolderPanel=nil
            self?.finishAssetFolder(id,path:result == .OK ? panel.url?.path : nil)
        }
    }
    func finishAssetFolder(_ id:String, path:String?) {
        let response:[String:Any] = ["id":id, "path":path as Any? ?? NSNull()]
        guard let data=try? JSONSerialization.data(withJSONObject:response, options:[.fragmentsAllowed]), let json=String(data:data,encoding:.utf8) else { return }
        web.evaluateJavaScript("window.STUDIO_ASSET_FOLDER_CHOSEN?.(" + json + ")",completionHandler:nil)
    }
    func finishClose(_ requestID:String, allowed:Bool, error:String? = nil) {
        guard requestID == closeRequestID else { return }
        closeRequestID=nil
        let hasError = !(error?.isEmpty ?? true)
        isClosing=allowed && !hasError
        if hasError { showCloseError(error ?? "保存未完成") }
        terminationReply(isClosing)
    }
    func showCloseError(_ message:String) {
        dismissCloseError()
        guard let data=try? JSONSerialization.data(withJSONObject:[message]), let json=String(data:data,encoding:.utf8) else { return }
        web.evaluateJavaScript("window.STUDIO_NOTIFY?.((" + json + ")[0],true)",completionHandler:nil)
    }

    @objc func dismissCloseError() { closeErrorBanner?.removeFromSuperview();closeErrorBanner=nil }
    func applicationWillTerminate(_ notification:Notification) { readyTimer?.invalidate();server?.terminate();if let file=readyFile{try? FileManager.default.removeItem(at:file)} }
    func windowShouldClose(_ sender:NSWindow)->Bool {
        if isClosing { return true }
        if closeRequestID == nil { NSApp.terminate(nil) }
        return false
    }
    func webViewWebContentProcessDidTerminate(_ webView:WKWebView) {
        if let requestID=closeRequestID { finishClose(requestID,allowed:false,error:"页面暂时无法响应。") }
    }
    func webView(_ webView:WKWebView,decidePolicyFor navigationAction:WKNavigationAction,decisionHandler:@escaping(WKNavigationActionPolicy)->Void) {
        guard let url=navigationAction.request.url else{decisionHandler(.cancel);return}
        if url.scheme == "about" || allowedOrigin == nil || "\(url.scheme ?? "")://\(url.host ?? ""):\(url.port ?? 0)" == allowedOrigin {decisionHandler(.allow)}else{decisionHandler(.cancel)}
    }
    func webView(_ webView:WKWebView,runOpenPanelWith parameters:WKOpenPanelParameters,initiatedByFrame frame:WKFrameInfo,completionHandler:@escaping([URL]?)->Void){let panel=NSOpenPanel();panel.canChooseFiles=true;panel.canChooseDirectories=false;panel.allowsMultipleSelection=parameters.allowsMultipleSelection;panel.beginSheetModal(for:window){result in completionHandler(result == .OK ? panel.urls:nil)}}
}
let app=NSApplication.shared
let delegate=AppDelegate();app.delegate=delegate;app.run()
