import AppKit
import CryptoKit

enum PackageError: Error { case invalid }

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
    var child: Process?
    var consent = false

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        let menu = NSMenu()
        let item = NSMenuItem(); menu.addItem(item)
        let appMenu = NSMenu(); item.submenu = appMenu
        appMenu.addItem(withTitle:"Quit VISION Community", action:#selector(NSApplication.terminate(_:)), keyEquivalent:"q")
        NSApp.mainMenu = menu
        window = NSWindow(contentRect:NSRect(x:0,y:0,width:560,height:440), styleMask:[.titled,.closable,.miniaturizable], backing:.buffered, defer:false)
        window.title = "VISION Community"; window.delegate = self
        let heading = NSTextField(labelWithString:"Help VISION find places.")
        heading.font = .boldSystemFont(ofSize:26)
        let intro = NSTextField(wrappingLabelWithString:"Choose Scenes, Objects or Both in the guided page. Accepted work earns search credits. Your private account code and results stay saved on this Mac.")
        status = NSTextField(wrappingLabelWithString:"Click Start VISION to open the four simple steps.")
        start = NSButton(title:"Start VISION", target:self, action:#selector(openGuided))
        background = NSButton(title:"Automatic processing", target:self, action:#selector(openBackground))
        for button in [start!,background!] { button.bezelStyle = .rounded; button.font = .systemFont(ofSize:17); button.heightAnchor.constraint(greaterThanOrEqualToConstant:44).isActive = true }
        // Return starts the guided page without a pointer, as in Windows.
        start.keyEquivalent = "\r"
        let foot = NSTextField(wrappingLabelWithString:"Keep this window open. To finish a running batch safely, close VISION from its guided page first.")
        foot.font = .systemFont(ofSize:13)
        let stack = NSStackView(views:[heading,intro,status,start,background,foot])
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

    func launch(backgroundMode: Bool) {
        guard child == nil else { return }
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
        if child == nil { return .terminateNow }
        let notice = NSAlert(); notice.messageText = "Finish safely first."
        notice.informativeText = "Close VISION from its guided page or automatic processing controls. Wait for the current batch to finish, then close this window."
        notice.addButton(withTitle:"Keep VISION open"); notice.runModal()
        return .terminateCancel
    }
    func windowShouldClose(_ sender:NSWindow) -> Bool { NSApp.terminate(nil); return false }
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
