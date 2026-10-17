import AppKit
import CryptoKit
import Darwin

enum LocalError: Error {case invalid}
func plain(_ path: URL) throws {
    var current=path.standardizedFileURL
    while current.path != "/" {
        var info=stat()
        guard lstat(current.path,&info)==0,UInt32(info.st_mode)&UInt32(S_IFMT) != UInt32(S_IFLNK) else {throw LocalError.invalid}
        current.deleteLastPathComponent()
    }
}
func verify(_ root: URL) throws {
    try plain(root)
    let inventory=root.appendingPathComponent("release-inventory.json");try plain(inventory)
    let raw=try Data(contentsOf:inventory)
    guard raw.count<1_000_000,SHA256.hash(data:raw).map({String(format:"%02x",$0)}).joined()==Build.inventorySHA,
          let value=try JSONSerialization.jsonObject(with:raw) as? [String:Any],value["version"] as? Int==1,
          value["sourceRevision"] as? String==Build.revision,let files=value["files"] as? [String:[String:Any]],files.count<512 else {throw LocalError.invalid}
    for (name,pin) in files {
        guard !name.hasPrefix("/"),!name.contains("\\"),!name.split(separator:"/").contains("..") else {throw LocalError.invalid}
        let file=root.appendingPathComponent(name);try plain(file)
        let info=try file.resourceValues(forKeys:[.isRegularFileKey,.fileSizeKey])
        guard info.isRegularFile==true,info.fileSize==pin["bytes"] as? Int,(info.fileSize ?? 0)<=64_000_000 else {throw LocalError.invalid}
        let bytes=try Data(contentsOf:file)
        guard SHA256.hash(data:bytes).map({String(format:"%02x",$0)}).joined()==pin["sha256"] as? String else {throw LocalError.invalid}
    }
}

final class Launcher:NSObject,NSApplicationDelegate,NSWindowDelegate {
    let root=Bundle.main.bundleURL.deletingLastPathComponent()
    var window:NSWindow!
    var status:NSTextField!
    var controls=[NSButton]()
    var child:Process?
    var preparing=false
    func applicationDidFinishLaunching(_ notification:Notification) {
        NSApp.setActivationPolicy(.regular)
        let menu=NSMenu(),item=NSMenuItem(),appMenu=NSMenu();menu.addItem(item);item.submenu=appMenu
        appMenu.addItem(withTitle:"Quit VISION",action:#selector(quit),keyEquivalent:"q");NSApp.mainMenu=menu
        window=NSWindow(contentRect:NSRect(x:0,y:0,width:570,height:460),styleMask:[.titled,.closable,.miniaturizable],backing:.buffered,defer:false)
        window.title="VISION Local Scenes";window.delegate=self
        let title=NSTextField(labelWithString:"Your local VISION library");title.font = .boldSystemFont(ofSize:26)
        let intro=NSTextField(wrappingLabelWithString:"First check this computer. Then open My library to add an MMA map, process your queue and search your saved Scenes.")
        intro.font = .systemFont(ofSize:17)
        status=NSTextField(wrappingLabelWithString:"No account or global Python installation is needed. Your results stay on this Mac.")
        let check=NSButton(title:"1. Check this computer",target:self,action:#selector(checkComputer))
        let library=NSButton(title:"2. My library",target:self,action:#selector(openLibrary))
        let queue=NSButton(title:"Open an assigned queue or backup",target:self,action:#selector(openQueue))
        let storage=NSButton(title:"Choose storage folder",target:self,action:#selector(chooseStorage))
        controls=[check,library,queue,storage]
        for button in controls {button.bezelStyle = .rounded;button.font = .systemFont(ofSize:17);button.heightAnchor.constraint(greaterThanOrEqualToConstant:40).isActive=true}
        let stack=NSStackView(views:[title,intro,check,library,queue,storage,status]);stack.orientation = .vertical;stack.alignment = .leading;stack.spacing=14;stack.translatesAutoresizingMaskIntoConstraints=false
        window.contentView!.addSubview(stack)
        NSLayoutConstraint.activate([stack.leadingAnchor.constraint(equalTo:window.contentView!.leadingAnchor,constant:26),stack.trailingAnchor.constraint(equalTo:window.contentView!.trailingAnchor,constant:-26),stack.topAnchor.constraint(equalTo:window.contentView!.topAnchor,constant:26)])
        window.center();window.makeKeyAndOrderFront(nil);NSApp.activate(ignoringOtherApps:true)
        do {try verify(root)} catch {status.stringValue="These application files do not match the release. Extract a fresh trusted download and keep the whole folder together.";controls.forEach{$0.isEnabled=false}}
    }
    @objc func checkComputer(){launch(root.appendingPathComponent("Readiness/Check this computer.json"))}
    @objc func openLibrary(){launch(root.appendingPathComponent("community/local_scene_library.json"))}
    @objc func openQueue(){let panel=NSOpenPanel();panel.canChooseDirectories=false;panel.message="Choose campaign.json from your queue folder";panel.beginSheetModal(for:window){result in if result == .OK,let url=panel.url {self.launch(url)}}}
    @objc func chooseStorage(){let panel=NSOpenPanel();panel.canChooseDirectories=true;panel.canChooseFiles=false;panel.message="Choose a folder or disk for new work. Existing queues stay where they are.";panel.beginSheetModal(for:window){result in if result == .OK,let url=panel.url {self.launch(self.root.appendingPathComponent("community/local_scene_library.json"),storage:url)}}}
    func launch(_ packet:URL,storage:URL?=nil) {
        guard child==nil && !preparing else {status.stringValue="VISION is already open. Return to its window and use Exit before opening another workspace.";return}
        let alert=NSAlert();alert.messageText="Prepare VISION on this Mac?";alert.informativeText="Setup downloads private Python and about1 GB of models once. Nothing is installed globally. The computer check uses fixed local images. Live queue processing only starts when you choose Start.";alert.addButton(withTitle:"Continue");alert.addButton(withTitle:"Cancel")
        guard alert.runModal() == .alertFirstButtonReturn else {return}
        preparing=true;controls.forEach{$0.isEnabled=false};status.stringValue="Preparing VISION. The first setup download may take a few minutes. Keep this window open."
        DispatchQueue.global(qos:.userInitiated).async {
            do {
                try verify(self.root);try plain(packet)
                let logs=FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Application Support/VISION Local Scenes/native-launcher-logs")
                try FileManager.default.createDirectory(at:logs,withIntermediateDirectories:true,attributes:[.posixPermissions:0o700]);try plain(logs)
                let log=logs.appendingPathComponent(UUID().uuidString+".log")
                guard FileManager.default.createFile(atPath:log.path,contents:nil,attributes:[.posixPermissions:0o600]) else {throw LocalError.invalid}
                let output=try FileHandle(forWritingTo:log),process=Process()
                process.executableURL=URL(fileURLWithPath:"/bin/bash")
                process.arguments=["--noprofile","--norc",self.root.appendingPathComponent("Start Local Scenes.command").path,"--accept-downloads","--packet",packet.path]
                if let storage=storage {process.arguments! += ["--storage",storage.path]}
                process.environment=["HOME":FileManager.default.homeDirectoryForCurrentUser.path,"PATH":"/usr/bin:/bin:/usr/sbin:/sbin","LC_ALL":"C"]
                process.standardInput=FileHandle.nullDevice;process.standardOutput=output;process.standardError=output
                process.terminationHandler={p in try? output.close();DispatchQueue.main.async {self.child=nil;self.preparing=false;self.controls.forEach{$0.isEnabled=true};self.status.stringValue=p.terminationStatus==0 ? "VISION closed. Your saved work is kept." : "Setup stopped. Your saved work is kept. Reopen or share the private native-launcher log with the maintainer."}}
                DispatchQueue.main.sync {self.child=process;self.preparing=false}
                try process.run()
            } catch {DispatchQueue.main.async {self.child=nil;self.preparing=false;self.controls.forEach{$0.isEnabled=true};self.status.stringValue="VISION could not open safely. Keep the whole kit together and ask the maintainer for help."}}
        }
    }
    @objc func quit(){window.performClose(nil)}
    func windowShouldClose(_ sender:NSWindow)->Bool {
        if child != nil || preparing {let alert=NSAlert();alert.messageText="Finish setup, or use Exit in the VISION window first.";alert.informativeText="Wait for its current group to stop, then close this launcher.";alert.beginSheetModal(for:window);return false}
        NSApp.terminate(nil);return false
    }
    func applicationShouldTerminate(_ sender:NSApplication)->NSApplication.TerminateReply {
        if child != nil || preparing {window.performClose(nil);return .terminateCancel};return .terminateNow
    }
}

if CommandLine.arguments.count==2 && CommandLine.arguments[1]=="--self-check" {
    do {try verify(Bundle.main.bundleURL.deletingLastPathComponent());print("LOCAL_PILOT_PACKAGE_VERIFIED");exit(0)} catch {exit(2)}
}
let launcher=Launcher();NSApplication.shared.delegate=launcher;NSApplication.shared.run()
