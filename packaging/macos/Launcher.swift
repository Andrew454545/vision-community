import AppKit
import CryptoKit
import Darwin

enum PackageError: Error { case invalid }

func plainDirectory(_ url: URL, missing: Bool = false) throws {
    var path = url.standardizedFileURL
    while path.path != "/" {
        var info = stat()
        if lstat(path.path, &info) != 0 {
            guard missing && errno == ENOENT else { throw PackageError.invalid }
        } else {
            guard UInt32(info.st_mode) & UInt32(S_IFMT) == UInt32(S_IFDIR) else { throw PackageError.invalid }
        }
        path.deleteLastPathComponent()
    }
}

func unusedRemovalIsSafe() throws -> Bool {
    let home = FileManager.default.homeDirectoryForCurrentUser
    let root = home.appendingPathComponent("Library/Application Support/VISION Community")
    // Only the never-used application can skip the existing private interpreter.
    try plainDirectory(root, missing:true)
    guard !FileManager.default.fileExists(atPath:root.path) else { return false }
    let agents = home.appendingPathComponent("Library/LaunchAgents")
    try plainDirectory(agents, missing:true)
    let plist = agents.appendingPathComponent("org.visioncommunity.background.plist")
    var info = stat()
    guard lstat(plist.path, &info) != 0 && errno == ENOENT else { throw PackageError.invalid }
    let probe = Process(); probe.executableURL = URL(fileURLWithPath:"/bin/launchctl")
    probe.arguments = ["print", "gui/\(getuid())/org.visioncommunity.background"]
    probe.environment = ["HOME":home.path,"PATH":"/usr/bin:/bin:/usr/sbin:/sbin","LC_ALL":"C"]
    probe.standardOutput = FileHandle.nullDevice; probe.standardError = FileHandle.nullDevice
    try probe.run()
    let deadline = Date().addingTimeInterval(15)
    while probe.isRunning && Date() < deadline { Thread.sleep(forTimeInterval:0.05) }
    if probe.isRunning { probe.terminate(); throw PackageError.invalid }
    guard [Int32(3), Int32(113)].contains(probe.terminationStatus) else { throw PackageError.invalid }
    return true
}

func recycleApplication(_ done: @escaping (Bool) -> Void) {
    let app = Bundle.main.bundleURL
    do {
        try plainDirectory(app)
        try verifyProject(Bundle.main.resourceURL!.appendingPathComponent("project"))
    } catch { done(false); return }
    // Use Finder's Trash operation on this bundle only, never recursively delete
    // a program/private folder. Saved account, indexes and reports are outside it.
    DispatchQueue.main.async {
        NSWorkspace.shared.recycle([app]) { moved, error in
            done(error == nil && moved[app] != nil)
        }
    }
}

func verifyProject(_ root: URL) throws {
    let manager = FileManager.default
    let inventory = root.appendingPathComponent("release-inventory.json")
    let bytes = try Data(contentsOf: inventory)
    guard bytes.count < 1_000_000,
          SHA256.hash(data: bytes).map({String(format:"%02x", $0)}).joined() == Build.inventorySHA,
          let value = try JSONSerialization.jsonObject(with:bytes) as? [String:Any],
          value["version"] as? Int == 1, value["sourceRevision"] as? String == Build.revision,
          let files = value["files"] as? [String:[String:Any]], files.count < 256 else { throw PackageError.invalid }
    for (name, pin) in files {
        guard !name.hasPrefix("/"), !name.split(separator:"/").contains("..") else { throw PackageError.invalid }
        let path = root.appendingPathComponent(name)
        let info = try path.resourceValues(forKeys:[.isRegularFileKey, .isSymbolicLinkKey, .fileSizeKey])
        guard info.isRegularFile == true, info.isSymbolicLink != true, info.fileSize == pin["bytes"] as? Int,
              (info.fileSize ?? 0) <= 64_000_000 else { throw PackageError.invalid }
        var ancestor = path.deletingLastPathComponent()
        while ancestor.path.count >= root.path.count {
            guard try ancestor.resourceValues(forKeys:[.isSymbolicLinkKey]).isSymbolicLink != true else { throw PackageError.invalid }
            ancestor.deleteLastPathComponent()
        }
        let body = try Data(contentsOf:path)
        guard SHA256.hash(data:body).map({String(format:"%02x",$0)}).joined() == pin["sha256"] as? String else { throw PackageError.invalid }
    }
    guard let walk = manager.enumerator(at:root, includingPropertiesForKeys:[.isDirectoryKey,.isSymbolicLinkKey]) else { throw PackageError.invalid }
    for case let path as URL in walk {
        let info = try path.resourceValues(forKeys:[.isDirectoryKey,.isSymbolicLinkKey])
        guard info.isSymbolicLink != true else { throw PackageError.invalid }
        let name = String(path.path.dropFirst(root.path.count + 1))
        if info.isDirectory != true && name != "release-inventory.json" && files[name] == nil { throw PackageError.invalid }
    }
}

final class Launcher: NSObject, NSApplicationDelegate, NSWindowDelegate {
    var window: NSWindow!
    var status: NSTextField!
    var start: NSButton!
    var background: NSButton!
    var remove: NSButton!
    var child: Process?
    var consent = false
    var removing = false

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        let menu = NSMenu()
        let item = NSMenuItem(); menu.addItem(item)
        let appMenu = NSMenu(); item.submenu = appMenu
        appMenu.addItem(withTitle:"Remove VISION Community…", action:#selector(removeVision), keyEquivalent:"")
        appMenu.addItem(NSMenuItem.separator())
        appMenu.addItem(withTitle:"Quit VISION Community", action:#selector(NSApplication.terminate(_:)), keyEquivalent:"q")
        NSApp.mainMenu = menu
        window = NSWindow(contentRect:NSRect(x:0,y:0,width:560,height:520), styleMask:[.titled,.closable,.miniaturizable], backing:.buffered, defer:false)
        window.title = "VISION Community"; window.delegate = self
        let heading = NSTextField(labelWithString:"Help VISION find places.")
        heading.font = .boldSystemFont(ofSize:26)
        let intro = NSTextField(wrappingLabelWithString:"Choose Scenes, Objects or Both in the guided page. Accepted work earns search credits. Your private account code and results stay saved on this Mac.")
        status = NSTextField(wrappingLabelWithString:"Click Start VISION to open the four simple steps.")
        start = NSButton(title:"Start VISION", target:self, action:#selector(openGuided))
        background = NSButton(title:"Automatic processing", target:self, action:#selector(openBackground))
        remove = NSButton(title:"Remove VISION", target:self, action:#selector(removeVision))
        for button in [start!,background!,remove!] { button.bezelStyle = .rounded; button.font = .systemFont(ofSize:17); button.heightAnchor.constraint(greaterThanOrEqualToConstant:44).isActive = true }
        // Return starts the guided page without a pointer, as in Windows.
        start.keyEquivalent = "\r"
        let foot = NSTextField(wrappingLabelWithString:"Keep this window open. To finish a running batch safely, close VISION from its guided page first.")
        foot.font = .systemFont(ofSize:13)
        let stack = NSStackView(views:[heading,intro,status,start,background,remove,foot])
        stack.orientation = .vertical; stack.alignment = .leading; stack.spacing = 14
        stack.translatesAutoresizingMaskIntoConstraints = false
        window.contentView!.addSubview(stack)
        NSLayoutConstraint.activate([stack.leadingAnchor.constraint(equalTo:window.contentView!.leadingAnchor,constant:24),
            stack.trailingAnchor.constraint(equalTo:window.contentView!.trailingAnchor,constant:-24),
            stack.topAnchor.constraint(equalTo:window.contentView!.topAnchor,constant:24)])
        window.center(); window.makeKeyAndOrderFront(nil); NSApp.activate(ignoringOtherApps:true)
    }

    @objc func openGuided() { launch(backgroundMode:false) }
    @objc func openBackground() { launch(backgroundMode:true) }

    @objc func removeVision() {
        guard !removing else { return }
        guard child == nil else {
            status.stringValue = "Close VISION from its guided page or automatic processing controls first, then choose Remove VISION."
            return
        }
        let notice = NSAlert(); notice.messageText = "Remove VISION?"
        notice.informativeText = "Automatic processing will stop after its current batch. The app moves to Trash. Your account code, saved results and failure reports are kept."
        notice.addButton(withTitle:"Remove VISION"); notice.addButton(withTitle:"Cancel")
        guard notice.runModal() == .alertFirstButtonReturn else { return }
        removing = true; start.isEnabled = false; background.isEnabled = false; remove.isEnabled = false
        status.stringValue = "Stopping automatic processing safely. A running batch may need time to finish."
        DispatchQueue.global().async {
            do {
                let project = Bundle.main.resourceURL!.appendingPathComponent("project")
                try plainDirectory(Bundle.main.bundleURL); try verifyProject(project)
                if try unusedRemovalIsSafe() { self.finishRemoval(); return }
                let task = Process(); task.executableURL = URL(fileURLWithPath:"/bin/bash")
                task.arguments = [project.appendingPathComponent("macos/Remove-Vision.command").path]
                task.environment = ["HOME":FileManager.default.homeDirectoryForCurrentUser.path,"PATH":"/usr/bin:/bin:/usr/sbin:/sbin","LC_ALL":"C"]
                let output = Pipe(); let error = Pipe()
                output.fileHandleForReading.readabilityHandler = { handle in _ = handle.availableData }
                error.fileHandleForReading.readabilityHandler = { handle in _ = handle.availableData }
                task.standardOutput = output; task.standardError = error
                try task.run()
                let deadline = Date().addingTimeInterval(120)
                while task.isRunning && Date() < deadline { Thread.sleep(forTimeInterval:0.1) }
                if task.isRunning { task.terminate(); throw PackageError.invalid }
                output.fileHandleForReading.readabilityHandler = nil
                error.fileHandleForReading.readabilityHandler = nil
                guard task.terminationStatus == 0 else { throw PackageError.invalid }
                self.finishRemoval()
            } catch { self.removalFailed() }
        }
    }

    func finishRemoval() {
        recycleApplication { okay in
            DispatchQueue.main.async {
                if okay { self.removing = false; NSApp.terminate(nil) }
                else { self.removalFailed() }
            }
        }
    }

    func removalFailed() {
        DispatchQueue.main.async {
            self.removing = false; self.start.isEnabled = true; self.background.isEnabled = true; self.remove.isEnabled = true
            self.status.stringValue = "VISION was kept. Wait for the current batch and close its guided page, then try removing again. If its files changed, get the current app first. Your saved work is kept."
        }
    }

    func launch(backgroundMode: Bool) {
        guard child == nil && !removing else { return }
        if !consent {
            let notice = NSAlert()
            notice.messageText = "Allow VISION's downloads?"
            notice.informativeText = "VISION downloads its private setup files and up to about 2 GB of processing files for your chosen work. It retrieves imagery when you request a computer check or start helping. No Python installation or administrator password is needed."
            notice.addButton(withTitle:"Continue"); notice.addButton(withTitle:"Cancel")
            guard notice.runModal() == .alertFirstButtonReturn else { return }
            consent = true
        }
        do {
            let root = Bundle.main.resourceURL!.appendingPathComponent("project")
            try verifyProject(root)
            let task = Process()
            task.executableURL = URL(fileURLWithPath:"/bin/bash")
            task.arguments = [root.appendingPathComponent("macos/Start-Vision.command").path,"--accept-downloads"] + (backgroundMode ? ["--background-controls"] : [])
            task.environment = ["HOME":FileManager.default.homeDirectoryForCurrentUser.path,"PATH":"/usr/bin:/bin:/usr/sbin:/sbin","LC_ALL":"C"]
            let output = Pipe(); let error = Pipe()
            // Drain output without displaying or persisting private child text.
            output.fileHandleForReading.readabilityHandler = { handle in _ = handle.availableData }
            error.fileHandleForReading.readabilityHandler = { handle in _ = handle.availableData }
            task.standardOutput = output; task.standardError = error
            task.terminationHandler = { process in
                output.fileHandleForReading.readabilityHandler = nil
                error.fileHandleForReading.readabilityHandler = nil
                DispatchQueue.main.async {
                    self.child = nil; self.start.isEnabled = true; self.background.isEnabled = true
                    self.status.stringValue = process.terminationStatus == 0 ? "VISION closed. Your saved work is kept." : "VISION could not start. Your work and a private failure report are kept. Try again or ask the maintainer for help."
                }
            }
            try task.run(); child = task
            start.isEnabled = false; background.isEnabled = false
            status.stringValue = "Opening VISION in your browser. The first setup may take a few minutes. Keep this window open; follow the steps on the guided page."
        } catch {
            status.stringValue = "The VISION application files could not be verified. Get the current download. Your saved work is kept."
        }
    }

    func applicationShouldTerminate(_ sender:NSApplication) -> NSApplication.TerminateReply {
        if removing { return .terminateCancel }
        if child == nil { return .terminateNow }
        let notice = NSAlert(); notice.messageText = "Finish safely first."
        notice.informativeText = "Close VISION from its guided page or automatic processing controls. Wait for the current batch to finish, then close this window."
        notice.addButton(withTitle:"Keep VISION open"); notice.runModal()
        return .terminateCancel
    }
    func windowShouldClose(_ sender:NSWindow) -> Bool { NSApp.terminate(nil); return false }
}

if CommandLine.arguments.contains("--remove-unused-check") {
    // Disposable CI only: exercise this app's actual Trash API before any
    // private folder exists. This cannot stop an installed or unfamiliar worker.
    do {
        let expected = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Applications/VISION Community.app")
        guard ProcessInfo.processInfo.environment["VISION_DISPOSABLE_LIFECYCLE"] == "1",
              Bundle.main.bundleURL.standardizedFileURL.path == expected.standardizedFileURL.path,
              try unusedRemovalIsSafe() else { throw PackageError.invalid }
        recycleApplication { okay in
            print(okay ? "{\"status\":\"UNUSED_APP_REMOVED\",\"savedWorkKept\":true}" : "{\"status\":\"INCOMPLETE\"}")
            exit(okay ? 0 : 1)
        }
        RunLoop.main.run()
    } catch { print("{\"status\":\"INCOMPLETE\"}"); exit(1) }
}
if CommandLine.arguments.contains("--self-check") {
    do {
        try verifyProject(Bundle.main.resourceURL!.appendingPathComponent("project"))
        print("{\"status\":\"PACKAGE_VERIFIED\",\"nativeInference\":false,\"accountsCreated\":0,\"productionQualified\":false}")
        exit(0)
    } catch { print("{\"status\":\"INCOMPLETE\",\"code\":\"package_check_failed\"}"); exit(1) }
}
let app = NSApplication.shared
let launcher = Launcher()
app.delegate = launcher
app.run()
