import AppKit
import WebKit
import Darwin

struct Connection {
    let url: URL
    let origin: String
    let token: String
    init(_ raw: String) throws {
        let pattern = #"^http://127\.0\.0\.1:([0-9]{1,5})/#([a-f0-9]{64})$"#
        let regex = try NSRegularExpression(pattern:pattern)
        guard let match = regex.firstMatch(in:raw,range:NSRange(raw.startIndex...,in:raw)),
              let portRange = Range(match.range(at:1),in:raw), let port = Int(raw[portRange]),
              (1...65535).contains(port),let tokenRange = Range(match.range(at:2),in:raw),
              let target = URL(string:raw) else { throw NSError(domain:"invalid_connection",code:1) }
        url=target;origin="http://127.0.0.1:\(port)";token=String(raw[tokenRange])
    }
    func local(_ url: URL) -> Bool {
        let raw=url.absoluteString
        return raw==origin || raw.hasPrefix(origin+"/") || raw.hasPrefix("blob:"+origin+"/")
    }
}

func readConnection(_ path: String) throws -> Connection {
    // Foundation canonicalization rewrites /private/tmp to /tmp, introducing a
    // symlink into a path that the backend already validated. Check the exact
    // supplied POSIX spelling, retaining the same no-link rule on every parent.
    guard path.hasPrefix("/"),!path.contains("\0"),!path.split(separator:"/").contains(".."),
          !path.split(separator:"/").contains(".") else {throw NSError(domain:"invalid_connection",code:1)}
    var current = path
    while current != "/" {
        var value=stat()
        guard lstat(current,&value)==0,UInt32(value.st_mode)&UInt32(S_IFMT) != UInt32(S_IFLNK) else {
            throw NSError(domain:"linked_connection",code:1)
        }
        current=(current as NSString).deletingLastPathComponent
    }
    let descriptor=open(path,O_RDONLY|O_NOFOLLOW)
    guard descriptor>=0 else {throw NSError(domain:"invalid_connection",code:1)}
    let file=FileHandle(fileDescriptor:descriptor,closeOnDealloc:true);defer {try? file.close()}
    var info=stat()
    guard fstat(descriptor,&info)==0,UInt32(info.st_mode)&UInt32(S_IFMT)==UInt32(S_IFREG),
          info.st_size<=1024 else {throw NSError(domain:"invalid_connection",code:1)}
    let bytes=file.readData(ofLength:1025)
    guard bytes.count<=1024,let value=try JSONSerialization.jsonObject(with:bytes) as? [String:Any],
          Set(value.keys)==["version","url"],value["version"] as? Int==1,let raw=value["url"] as? String else {
        throw NSError(domain:"invalid_connection",code:1)
    }
    return try Connection(raw)
}

final class SceneWindow: NSObject,NSApplicationDelegate,NSWindowDelegate,WKNavigationDelegate,WKUIDelegate,WKDownloadDelegate,URLSessionTaskDelegate {
    let connection: Connection
    var window: NSWindow!
    var web: WKWebView!
    var timer: Timer?
    var lastCounter = -1
    var failures=0
    var polling=false
    var stopping=false
    lazy var session: URLSession = {
        let config=URLSessionConfiguration.ephemeral
        config.connectionProxyDictionary=[:];config.httpShouldSetCookies=false
        config.timeoutIntervalForRequest=2;config.timeoutIntervalForResource=3
        return URLSession(configuration:config,delegate:self,delegateQueue:nil)
    }()
    init(_ value: Connection) { connection=value }
    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        let menu=NSMenu(),item=NSMenuItem(),appMenu=NSMenu();menu.addItem(item);item.submenu=appMenu
        appMenu.addItem(withTitle:"Quit VISION",action:#selector(quit),keyEquivalent:"q");NSApp.mainMenu=menu
        let config=WKWebViewConfiguration();config.websiteDataStore = .nonPersistent()
        web=WKWebView(frame:.zero,configuration:config);web.navigationDelegate=self;web.uiDelegate=self
        window=NSWindow(contentRect:NSRect(x:0,y:0,width:1050,height:800),styleMask:[.titled,.closable,.miniaturizable,.resizable],backing:.buffered,defer:false)
        window.title="VISION Local Scenes";window.minSize=NSSize(width:700,height:600);window.delegate=self
        window.contentView=web;window.center();window.makeKeyAndOrderFront(nil);NSApp.activate(ignoringOtherApps:true)
        web.load(URLRequest(url:connection.url))
        timer=Timer.scheduledTimer(withTimeInterval:1,repeats:true){[weak self] _ in self?.poll()}
    }
    func request(_ path: String,method: String="GET") -> URLRequest {
        var request=URLRequest(url:URL(string:connection.origin+path)!);request.httpMethod=method
        request.setValue("Bearer "+connection.token,forHTTPHeaderField:"Authorization")
        if method=="POST" { request.setValue(connection.origin,forHTTPHeaderField:"Origin");request.httpBody=Data() }
        return request
    }
    func poll() {
        guard !polling && !stopping else { return };polling=true
        session.dataTask(with:request("/api/window")){[weak self] data,response,error in
            DispatchQueue.main.async {
                guard let self=self else { return };self.polling=false
                if error != nil || (response as? HTTPURLResponse)?.statusCode != 200 {
                    self.failures += 1
                    if self.failures>=3 { self.stopping=true;NSApp.terminate(nil) };return
                }
                self.failures=0
                if let data=data,data.count<=4096,let value=try? JSONSerialization.jsonObject(with:data) as? [String:Any],
                   let counter=value["showCounter"] as? Int,counter != self.lastCounter {
                    self.lastCounter=counter;self.window.deminiaturize(nil);self.window.makeKeyAndOrderFront(nil);NSApp.activate(ignoringOtherApps:true)
                }
            }
        }.resume()
    }
    @objc func quit() { window.performClose(nil) }
    func windowShouldClose(_ sender: NSWindow) -> Bool {
        if stopping { return true }
        let alert=NSAlert();alert.messageText="Pause processing and close VISION?"
        alert.informativeText="Your saved work is kept. The current group may take a few minutes to stop."
        alert.addButton(withTitle:"Pause and close");alert.addButton(withTitle:"Keep open")
        guard alert.runModal() == .alertFirstButtonReturn else { return false }
        stopping=true;timer?.invalidate()
        session.dataTask(with:request("/api/exit",method:"POST")){_,_,_ in DispatchQueue.main.async {NSApp.terminate(nil)}}.resume()
        return false
    }
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        if stopping { return .terminateNow };window.performClose(nil);return .terminateCancel
    }
    func applicationWillTerminate(_ notification: Notification) {timer?.invalidate();session.invalidateAndCancel()}
    func urlSession(_ session: URLSession,task: URLSessionTask,willPerformHTTPRedirection response: HTTPURLResponse,newRequest request: URLRequest,completionHandler:@escaping(URLRequest?)->Void) {completionHandler(nil)}
    func webView(_ webView: WKWebView,decidePolicyFor navigationAction: WKNavigationAction,decisionHandler:@escaping(WKNavigationActionPolicy)->Void) {
        guard let url=navigationAction.request.url else {decisionHandler(.cancel);return}
        if connection.local(url) {decisionHandler(navigationAction.shouldPerformDownload ? .download : .allow);return}
        if navigationAction.navigationType == .linkActivated && url.scheme=="https" {NSWorkspace.shared.open(url)}
        decisionHandler(.cancel)
    }
    func webView(_ webView: WKWebView,decidePolicyFor navigationResponse: WKNavigationResponse,decisionHandler:@escaping(WKNavigationResponsePolicy)->Void) {
        guard let url=navigationResponse.response.url,connection.local(url) else {decisionHandler(.cancel);return}
        if (navigationResponse.response as? HTTPURLResponse)?.value(forHTTPHeaderField:"Content-Disposition")?.hasPrefix("attachment")==true {
            decisionHandler(.download)
        } else {decisionHandler(navigationResponse.canShowMIMEType ? .allow : .download)}
    }
    func webView(_ webView: WKWebView,createWebViewWith configuration: WKWebViewConfiguration,for navigationAction: WKNavigationAction,windowFeatures: WKWindowFeatures)->WKWebView? {
        if navigationAction.navigationType == .linkActivated,let url=navigationAction.request.url,url.scheme=="https" {NSWorkspace.shared.open(url)}
        return nil
    }
    func webView(_ webView: WKWebView,runOpenPanelWith parameters: WKOpenPanelParameters,initiatedByFrame frame: WKFrameInfo,completionHandler:@escaping([URL]?)->Void) {
        guard connection.local(frame.request.url ?? connection.url) else {completionHandler(nil);return}
        let panel=NSOpenPanel();panel.canChooseDirectories=false;panel.allowsMultipleSelection=parameters.allowsMultipleSelection
        panel.beginSheetModal(for:window){result in completionHandler(result == .OK ? panel.urls : nil)}
    }
    func webView(_ webView: WKWebView,runJavaScriptConfirmPanelWithMessage message: String,initiatedByFrame frame: WKFrameInfo,completionHandler:@escaping(Bool)->Void) {
        let alert=NSAlert();alert.messageText=String(message.prefix(2000));alert.addButton(withTitle:"Continue");alert.addButton(withTitle:"Cancel")
        alert.beginSheetModal(for:window){result in completionHandler(result == .alertFirstButtonReturn)}
    }
    func webView(_ webView: WKWebView,navigationAction: WKNavigationAction,didBecome download: WKDownload) {download.delegate=self}
    func webView(_ webView: WKWebView,navigationResponse: WKNavigationResponse,didBecome download: WKDownload) {download.delegate=self}
    func download(_ download: WKDownload,decideDestinationUsing response: URLResponse,suggestedFilename: String,completionHandler:@escaping(URL?)->Void) {
        guard let url=response.url,connection.local(url) else {completionHandler(nil);return}
        let panel=NSSavePanel();panel.nameFieldStringValue=URL(fileURLWithPath:suggestedFilename).lastPathComponent
        panel.beginSheetModal(for:window){result in completionHandler(result == .OK ? panel.url : nil)}
    }
    func download(_ download: WKDownload,didFailWithError error: Error,resumeData: Data?) {
        let alert=NSAlert();alert.messageText="The file could not be saved.";alert.informativeText="Your original work is kept. Try saving again from VISION.";alert.beginSheetModal(for:window)
    }
}

final class RenderCheck:NSObject,NSApplicationDelegate,WKNavigationDelegate {
    let connection:Connection
    var web:WKWebView!
    init(_ value:Connection){connection=value}
    func applicationDidFinishLaunching(_ notification:Notification) {
        NSApp.setActivationPolicy(.prohibited)
        let config=WKWebViewConfiguration();config.websiteDataStore = .nonPersistent()
        web=WKWebView(frame:NSRect(x:0,y:0,width:1000,height:800),configuration:config);web.navigationDelegate=self
        web.load(URLRequest(url:connection.url))
        DispatchQueue.main.asyncAfter(deadline:.now()+15){exit(3)}
    }
    func webView(_ webView:WKWebView,decidePolicyFor action:WKNavigationAction,decisionHandler:@escaping(WKNavigationActionPolicy)->Void) {
        decisionHandler(action.request.url.map(connection.local) == true ? .allow : .cancel)
    }
    func webView(_ webView:WKWebView,didFinish navigation:WKNavigation!) {
        web.callAsyncJavaScript("const s=await request('/api/library'); return s.localOnly===true && document.getElementById('personal-map-open')!==null && typeof createImageBitmap==='function';",arguments:[:],in:nil,in:.page){result in
            if case .success(let value)=result,value as? Bool==true {print("LOCAL_WEBKIT_RENDER_AND_AUTH_VERIFIED");exit(0)}
            exit(3)
        }
    }
    func webView(_ webView:WKWebView,didFailProvisionalNavigation navigation:WKNavigation!,withError error:Error){exit(3)}
}

if CommandLine.arguments == [CommandLine.arguments[0],"--self-check"] {
    do {
        _ = try Connection("http://127.0.0.1:1234/#"+String(repeating:"a",count:64))
        for invalid in ["https://127.0.0.1:1234/#", "http://localhost:1234/#", "http://127.0.0.1:0/#", "http://127.0.0.1:1234.evil/#"] {
            if (try? Connection(invalid+String(repeating:"a",count:64))) != nil {exit(2)}
        }
        print("LOCAL_NATIVE_WINDOW_BOUNDARY_VERIFIED");exit(0)
    } catch {exit(2)}
}
do {
    guard CommandLine.arguments.count==3 else {exit(2)}
    if CommandLine.arguments[1]=="--render-check" {
        let delegate=RenderCheck(try readConnection(CommandLine.arguments[2]));NSApplication.shared.delegate=delegate
        withExtendedLifetime(delegate){NSApplication.shared.run()};exit(0)
    }
    guard CommandLine.arguments[1]=="--connection" else {exit(2)}
    let delegate=SceneWindow(try readConnection(CommandLine.arguments[2]))
    NSApplication.shared.delegate=delegate;withExtendedLifetime(delegate){NSApplication.shared.run()}
} catch {exit(2)}
