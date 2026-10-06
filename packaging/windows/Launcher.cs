using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using Microsoft.Win32;

[assembly: System.Runtime.Versioning.TargetFramework(".NETFramework,Version=v4.8")]

static class Package {
    public static string Hash(byte[] bytes) { using(var sha=SHA256.Create()) return BitConverter.ToString(sha.ComputeHash(bytes)).Replace("-", "").ToLowerInvariant(); }
    public static void Plain(string path) {
        for(var current=Path.GetFullPath(path); current!=null; current=Path.GetDirectoryName(current))
            try { if((File.GetAttributes(Starter.FilePath(current))&FileAttributes.ReparsePoint)!=0) throw new IOException("redirected_package_path"); }
            catch(FileNotFoundException) {} catch(DirectoryNotFoundException) {}
    }
    public static byte[] Bytes() {
        using(var body=Assembly.GetExecutingAssembly().GetManifestResourceStream("VisionPayload"))
        using(var output=new MemoryStream()) {
            if(body==null || body.Length>16000000) throw new IOException("package_limit");
            body.CopyTo(output); var bytes=output.ToArray();
            if(Hash(bytes)!=Build.PayloadSHA) throw new IOException("package_mismatch");
            return bytes;
        }
    }
    public static void Extract(string root) {
        Plain(root); if(Directory.Exists(root)||File.Exists(root)) throw new IOException("package_output_exists");
        using(var input=new MemoryStream(Bytes())) using(var zip=new ZipArchive(input,ZipArchiveMode.Read)) {
            if(zip.Entries.Count>256) throw new IOException("package_limit");
            foreach(var file in zip.Entries) {
                if(file.FullName.StartsWith("/") || file.FullName.Contains("\\") || file.FullName.Contains(":") || file.FullName.Split('/').Any(p=>p==".."||p=="."||p.Length==0) || file.Length>64000000) throw new IOException("package_path");
            }
            Directory.CreateDirectory(root);
            foreach(var file in zip.Entries) {
                var target=Path.Combine(root,file.FullName.Replace('/',Path.DirectorySeparatorChar));
                Plain(target); Directory.CreateDirectory(Path.GetDirectoryName(target));
                using(var read=file.Open()) using(var write=new FileStream(target,FileMode.CreateNew)) read.CopyTo(write);
            }
        }
        Verify(root);
    }
    public static void Verify(string root) { VerifyPinned(root,Build.Revision,Build.InventorySHA); }
    public static void VerifyPinned(string root,string revision,string inventoryPin) {
        Plain(root); var path=Path.Combine(root,"release-inventory.json"); Plain(path);
        var body=Starter.Read(path,1000000); if(Hash(body)!=inventoryPin) throw new IOException("inventory_mismatch");
        var value=new JavaScriptSerializer().Deserialize<Dictionary<string,object>>(Encoding.UTF8.GetString(body));
        if(Convert.ToInt32(value["version"])!=1 || (string)value["sourceRevision"]!=revision) throw new IOException("inventory_revision");
        var files=(Dictionary<string,object>)value["files"];
        if(files.Count>256) throw new IOException("package_limit");
        var directories=new HashSet<string>(StringComparer.Ordinal);
        foreach(var pair in files) {
            if(!Regex.IsMatch(pair.Key,@"\A[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*\z") || pair.Key.Split('/').Any(p=>p=="."||p=="..")) throw new IOException("package_path");
            var parent=Path.GetDirectoryName(pair.Key.Replace('/',Path.DirectorySeparatorChar));
            while(!String.IsNullOrEmpty(parent)) { directories.Add(parent.Replace('\\','/')); parent=Path.GetDirectoryName(parent); }
            var file=Path.Combine(root,pair.Key.Replace('/',Path.DirectorySeparatorChar)); Plain(file);
            var pin=(Dictionary<string,object>)pair.Value;
            if(Starter.Size(file)!=Convert.ToInt64(pin["bytes"]) || Starter.Hash(file)!=(string)pin["sha256"]) throw new IOException("package_file_changed");
        }
        // Do not traverse a redirected directory, even one containing no files.
        var pending=new Stack<string>(); pending.Push(root);
        while(pending.Count>0) foreach(var entry in Directory.GetFileSystemEntries(pending.Pop())) {
            Plain(entry);
            if(Directory.Exists(entry)) {
                if(!directories.Contains(entry.Substring(root.Length+1).Replace('\\','/'))) throw new IOException("unexpected_package_directory");
                pending.Push(entry);
            }
            else {
                var name=entry.Substring(root.Length+1).Replace('\\','/');
                if(name!="release-inventory.json" && !files.ContainsKey(name)) throw new IOException("unexpected_package_file");
            }
        }
    }
    public static string Quote(string value) { if(value.Contains("\"")||value.Contains("\r")||value.Contains("\n")) throw new IOException("invalid_argument"); return "\""+value+"\""; }
    public static string Base { get { return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"Programs","VISION Community"); } }
    public static string Installed { get { return Path.Combine(Base,Build.Revision.Substring(0,16)); } }
    public static string Project { get { return Path.Combine(Installed,"project"); } }
    public static string Executable { get { return Path.Combine(Installed,"VISION.exe"); } }
    public static string Current { get { return Assembly.GetExecutingAssembly().Location; } }
    static void Shortcut(string path,string args) {
        Plain(path); Directory.CreateDirectory(Path.GetDirectoryName(path));
        var type=Type.GetTypeFromProgID("WScript.Shell"); dynamic shell=Activator.CreateInstance(type);
        dynamic link=shell.CreateShortcut(path);
        if(File.Exists(path) && !Path.GetFullPath((string)link.TargetPath).StartsWith(Base+Path.DirectorySeparatorChar,StringComparison.OrdinalIgnoreCase)) throw new IOException("unfamiliar_shortcut");
        link.TargetPath=Executable; link.Arguments=args; link.WorkingDirectory=Installed;
        link.Description="VISION Community"; link.Save();
    }
    static bool Intact() {
        try { Verify(Project); return Hash(File.ReadAllBytes(Executable))==Hash(File.ReadAllBytes(Current)); }
        catch(Exception) { return false; }
    }
    // Delete a retired program copy without following a link inside it.
    public static void Remove(string path) {
        var attributes=File.GetAttributes(path);
        if((attributes&FileAttributes.Directory)!=0) {
            if((attributes&FileAttributes.ReparsePoint)==0) foreach(var entry in Directory.GetFileSystemEntries(path)) Remove(entry);
            Directory.Delete(path,false);
        } else { File.SetAttributes(path,FileAttributes.Normal); File.Delete(path); }
    }
    // Rename first: Windows refuses while VISION runs from (or inside) that copy,
    // so an open application is never partially deleted.
    public static bool Running(string path) {
        var prefix=Path.GetFullPath(path).TrimEnd(Path.DirectorySeparatorChar)+Path.DirectorySeparatorChar;
        foreach(var process in Process.GetProcessesByName("VISION")) {
            try { if(process.MainModule.FileName.StartsWith(prefix,StringComparison.OrdinalIgnoreCase)) return true; }
            catch(Exception) {} finally { process.Dispose(); }
        }
        return false;
    }
    static bool Retire(string path) {
        if(Running(path)) return false;
        var retired=Path.Combine(Base,"retired-"+Guid.NewGuid().ToString("N"));
        // Scanners and indexers briefly hold new files; an open VISION keeps failing.
        for(var attempt=0;;attempt++) {
            try { Directory.Move(path,retired); break; }
            catch(Exception error) { if(!(error is IOException || error is UnauthorizedAccessException) || attempt==9) return false; System.Threading.Thread.Sleep(500); }
        }
        try { Remove(retired); } catch(IOException) {} catch(UnauthorizedAccessException) {}
        return true;
    }
    static bool ProgramCopy(string path) {
        var names=Directory.GetFileSystemEntries(path).Select(Path.GetFileName).OrderBy(n=>n,StringComparer.OrdinalIgnoreCase).ToArray();
        return names.Length==2 && String.Equals(names[0],"project",StringComparison.OrdinalIgnoreCase) && String.Equals(names[1],"VISION.exe",StringComparison.OrdinalIgnoreCase);
    }
    // Rewrite a changed installation in place from the verified payload. Links
    // are removed, never followed; only changed, missing or extra files change.
    static void Repair() {
        if(Running(Installed)) throw new IOException("installation_in_use");
        var pending=Path.Combine(Base,"staging-"+Guid.NewGuid().ToString("N")); var staged=Path.Combine(pending,"project");
        Directory.CreateDirectory(pending); Extract(staged);
        try {
            var links=new Stack<string>(); links.Push(Installed);
            while(links.Count>0) foreach(var entry in Directory.GetFileSystemEntries(links.Pop())) {
                if((File.GetAttributes(entry)&FileAttributes.ReparsePoint)!=0) Remove(entry);
                else if(Directory.Exists(entry)) links.Push(entry);
            }
            var wanted=new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            foreach(var file in Directory.GetFiles(staged,"*",SearchOption.AllDirectories)) {
                var name=file.Substring(staged.Length+1); wanted.Add(name); var target=Path.Combine(Project,name);
                Directory.CreateDirectory(Path.GetDirectoryName(target));
                if(!File.Exists(target) || Hash(File.ReadAllBytes(target))!=Hash(File.ReadAllBytes(file))) {
                    if(File.Exists(target)) File.SetAttributes(target,FileAttributes.Normal);
                    File.Copy(file,target,true);
                }
            }
            if(Directory.Exists(Project)) foreach(var file in Directory.GetFiles(Project,"*",SearchOption.AllDirectories))
                if(!wanted.Contains(file.Substring(Project.Length+1))) { File.SetAttributes(file,FileAttributes.Normal); File.Delete(file); }
            if(Directory.Exists(Project)) foreach(var directory in Directory.GetDirectories(Project,"*",SearchOption.AllDirectories).OrderByDescending(p=>p.Length))
                if(Directory.GetFileSystemEntries(directory).Length==0) Directory.Delete(directory,false);
            foreach(var entry in Directory.GetFileSystemEntries(Installed))
                if(!String.Equals(entry,Project,StringComparison.OrdinalIgnoreCase) && !String.Equals(entry,Executable,StringComparison.OrdinalIgnoreCase)) Remove(entry);
            if(!File.Exists(Executable) || Hash(File.ReadAllBytes(Executable))!=Hash(File.ReadAllBytes(Current))) File.Copy(Current,Executable,true);
        } finally { try { Remove(pending); } catch(IOException) {} catch(UnauthorizedAccessException) {} }
    }
    public static void Install() {
        Plain(Base); Directory.CreateDirectory(Base);
        var lockPath=Path.Combine(Base,"install.lock"); Plain(lockPath);
        FileStream guard;
        try { guard=new FileStream(lockPath,FileMode.OpenOrCreate,FileAccess.ReadWrite,FileShare.None); }
        catch(IOException) { throw new IOException("install_in_progress"); }
        using(guard) {
            // Folders left by an interrupted setup or an earlier removal attempt.
            foreach(var leftover in Directory.GetDirectories(Base))
                if(Regex.IsMatch(Path.GetFileName(leftover),"^(staging|retired)-[a-f0-9]{32}$")) { try { Remove(leftover); } catch(IOException) {} catch(UnauthorizedAccessException) {} }
            Plain(Installed);
            // Repair a changed installation from this verified download.
            if(Directory.Exists(Installed) && !Intact()) Repair();
            if(!Directory.Exists(Installed)) {
                var pending=Path.Combine(Base,"staging-"+Guid.NewGuid().ToString("N"));
                Directory.CreateDirectory(pending); Extract(Path.Combine(pending,"project"));
                File.Copy(Current,Path.Combine(pending,"VISION.exe")); Directory.Move(pending,Installed);
            }
            Verify(Project);
            if(Hash(File.ReadAllBytes(Executable))!=Hash(File.ReadAllBytes(Current))) throw new IOException("installed_launcher_changed");
            // A redirected or protected desktop is optional; the Start-menu entry
            // and installed application remain usable without changing its access.
            try { Shortcut(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory),"VISION Community.lnk"),""); }
            catch(IOException) {} catch(UnauthorizedAccessException) {}
            var menu=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Programs),"VISION Community");
            Shortcut(Path.Combine(menu,"VISION Community.lnk"),"");
            Shortcut(Path.Combine(menu,"Automatic processing.lnk"),"--background");
            using(var key=Registry.CurrentUser.CreateSubKey(@"Software\Microsoft\Windows\CurrentVersion\Uninstall\VISIONCommunity")) {
                key.SetValue("DisplayName","VISION Community"); key.SetValue("DisplayVersion","0.1.0"); key.SetValue("Publisher","VISION Community");
                key.SetValue("InstallLocation",Installed); key.SetValue("DisplayIcon",Executable);
                key.SetValue("UninstallString",Quote(Executable)+" --uninstall"); key.SetValue("NoModify",1); key.SetValue("NoRepair",1);
            }
            // Shortcuts and the removal entry now name this version. Remove earlier
            // program copies that are closed; an open one is retried next setup.
            // The private worker folder and its startup snapshots are elsewhere.
            foreach(var other in Directory.GetDirectories(Base)) {
                var name=Path.GetFileName(other);
                if(Regex.IsMatch(name,"^[a-f0-9]{16}$") && name!=Build.Revision.Substring(0,16) &&
                   (File.GetAttributes(other)&FileAttributes.ReparsePoint)==0 && ProgramCopy(other)) Retire(other);
            }
        }
    }
    public static void Uninstall() {
        Verify(Project); if(!String.Equals(Current,Executable,StringComparison.OrdinalIgnoreCase)) throw new IOException("removal_scope");
        var temporary=Path.Combine(Path.GetTempPath(),"vision-remove-"+Guid.NewGuid().ToString("N"));
        Plain(temporary); Directory.CreateDirectory(temporary);
        var helper=Path.Combine(temporary,"VISION-remove.exe"); File.Copy(Current,helper,false);
        if(Starter.Hash(helper)!=Starter.Hash(Current)) throw new IOException("helper_changed");
        Process.Start(new ProcessStartInfo(helper,"--remove-child "+Process.GetCurrentProcess().Id+" "+Quote(Current)) {UseShellExecute=false,CreateNoWindow=true,WindowStyle=ProcessWindowStyle.Hidden});
    }
    public static int SelfCheck() {
        var root=Path.Combine(Path.GetTempPath(),"vision-package-check-"+Guid.NewGuid().ToString("N")); Plain(root);
        try {
            Extract(root); Verify(root);
            var changed=Path.Combine(root,"community","desktop.py"); File.AppendAllText(changed,"\nchanged fixture\n");
            bool refused=false; try { Verify(root); } catch(IOException) { refused=true; }
            if(!refused) throw new IOException("changed_file_not_refused");
            Console.WriteLine("{\"status\":\"PACKAGE_VERIFIED\",\"changedFileRefused\":true,\"accountsCreated\":0,\"nativeInference\":false,\"productionQualified\":false}"); return 0;
        } catch { Console.WriteLine("{\"status\":\"INCOMPLETE\",\"code\":\"package_check_failed\"}"); return 1; }
        finally { if(Directory.Exists(root)) Directory.Delete(root,true); }
    }
    public static int DetachedCheck(string root) {
        // Finite process fixture: no install, registry, startup, account or work.
        root=Path.GetFullPath(root); Plain(root);
        if(Directory.Exists(root)||File.Exists(root)||!root.StartsWith(Path.GetFullPath(Path.GetTempPath()).TrimEnd(Path.DirectorySeparatorChar)+Path.DirectorySeparatorChar,StringComparison.OrdinalIgnoreCase)) return 1;
        Directory.CreateDirectory(root);
        var helper=Path.Combine(root,"VISION-fixture.exe"); File.Copy(Current,helper,false);
        if(Starter.Hash(helper)!=Starter.Hash(Current)) throw new IOException("helper_changed");
        Process.Start(new ProcessStartInfo(helper,"--detached-child "+Quote(root)+" "+Process.GetCurrentProcess().Id+" "+Quote(Current)) {UseShellExecute=false,CreateNoWindow=true,WindowStyle=ProcessWindowStyle.Hidden});
        return 0;
    }
    public static int DetachedChild(string root,int parent,string executable) {
        try {
            root=Path.GetFullPath(root); Plain(root);
            if(!root.StartsWith(Path.GetFullPath(Path.GetTempPath()).TrimEnd(Path.DirectorySeparatorChar)+Path.DirectorySeparatorChar,StringComparison.OrdinalIgnoreCase) ||
               !String.Equals(Current,Path.Combine(root,"VISION-fixture.exe"),StringComparison.OrdinalIgnoreCase) || Starter.Hash(Current)!=Starter.Hash(executable)) return 1;
            try { using(var waiting=Process.GetProcessById(parent)) {
                if(!waiting.HasExited) {
                    try { if(!String.Equals(waiting.MainModule.FileName,executable,StringComparison.OrdinalIgnoreCase)) return 1; }
                    catch(System.ComponentModel.Win32Exception) { if(!waiting.HasExited) return 1; }
                    catch(InvalidOperationException) { if(!waiting.HasExited) return 1; }
                    if(!waiting.WaitForExit(20000)) return 1;
                }
            } } catch(ArgumentException) { /* The authentic parent already exited. */ }
            Starter.Json(Path.Combine(root,"result.json"),new {status="DETACHED_HELPER_PASS",helper="native",accountsCreated=0,nativeInference=false,productionQualified=false}); return 0;
        } catch { return 1; }
    }
}

sealed class Launcher: Form {
    Label status; Button start,background; Process child; bool installed,consent,preparing;
    public Launcher(bool backgroundMode) {
        installed=String.Equals(Package.Current,Package.Executable,StringComparison.OrdinalIgnoreCase);
        Text="VISION Community"; ClientSize=new Size(590,400); Font=new Font("Segoe UI",12); FormBorderStyle=FormBorderStyle.FixedDialog;
        MaximizeBox=false; StartPosition=FormStartPosition.CenterScreen;
        var heading=new Label { Text=installed?"Help VISION find places.":"Install VISION for this Windows account.",Font=new Font("Segoe UI",20,FontStyle.Bold),Left=24,Top=20,Width=540,Height=65 };
        var intro=new Label { Text="Choose Scenes, Objects or Both in the guided page. Accepted work earns search credits. Your private account code and results stay saved on this PC.",Left=24,Top=88,Width=540,Height=70 };
        status=new Label { Text=installed?"Click Start VISION to open the four simple steps.":"No Python installation or administrator password needed.",Left=24,Top=164,Width=540,Height=100 };
        start=new Button { Text=installed?"Start VISION":"Install VISION",Left=24,Top=272,Width=210,Height=48 };
        background=new Button { Text="Automatic processing",Left=249,Top=272,Width=290,Height=48,Enabled=installed };
        AcceptButton=start; start.Click+=(s,e)=>Open(false); background.Click+=(s,e)=>Open(true);
        Controls.AddRange(new Control[]{heading,intro,status,start,background,new Label {Text="Keep this window open. Close VISION from its guided page first.",Left=24,Top=334,Width=540,Height=48,Font=new Font("Segoe UI",10)}});
        FormClosing+=(s,e)=>{ if(preparing || (child!=null && !child.HasExited)) { e.Cancel=true; MessageBox.Show(this,preparing?"Please let setup finish. Your saved work is kept.":"Close VISION from its guided page or automatic processing controls. Wait for the current batch to finish, then close this window.","Finish safely first"); } };
        if(installed && backgroundMode) Shown+=(s,e)=>Open(true);
    }
    void Open(bool backgroundMode) {
        try {
            if(!installed) {
                status.Text="Installing VISION. This takes a few seconds.";  status.Refresh();
                Package.Install(); installed=true; start.Text="Start VISION"; background.Enabled=true;
                status.Text="Installed. Choose Start VISION, or use the VISION Community shortcut on your desktop or Start menu."; start.Focus(); return;
            }
            // Check the files before asking about downloads, so a damaged copy
            // never asks for consent it cannot use.
            Package.Verify(Package.Project);
            if(backgroundMode) { using(var controls=new BackgroundWindow(Starter.Root)) controls.ShowDialog(this); return; }
            if(!consent) {
                if(MessageBox.Show(this,"VISION downloads its private setup files and up to about 2 GB of processing files for your chosen work. Imagery is retrieved when you request a computer check or start helping. Continue?","Allow VISION's downloads?",MessageBoxButtons.OKCancel)!=DialogResult.OK) return;
                consent=true;
            }
            start.Enabled=background.Enabled=false; status.Text="Opening VISION. The first setup may take a few minutes. Keep this window open and follow the guided page.";
            preparing=true;
            // Native verification/download work stays off the UI thread.
            var setup=new System.ComponentModel.BackgroundWorker();
            setup.DoWork+=(s,e)=>{
                e.Result=Starter.Start(Package.Project,Starter.Root);
            };
            setup.RunWorkerCompleted+=(s,e)=>{
                preparing=false; setup.Dispose();
                if(e.Error!=null) { Starter.Failure(Starter.Root,e.Error); start.Enabled=background.Enabled=true; status.Text=StartupProblem(e.Error); return; }
                child=(Process)e.Result;
                if(child==null) { start.Enabled=background.Enabled=true; status.Text="VISION is already open. Its guided page has been reopened."; return; }
                Watch();
            };
            setup.RunWorkerAsync();
        } catch(Exception error) {
            if(backgroundMode && installed) { Background.Failure(Starter.Root,error); status.Text=Background.Problem(error); }
            else status.Text=Problem(error);
        }
    }
    void Watch() {
            var timer=new System.Windows.Forms.Timer { Interval=500 }; timer.Tick+=(s,e)=>{
                if(child!=null && child.HasExited) { var code=child.ExitCode; child.Dispose(); child=null; timer.Stop(); timer.Dispose(); start.Enabled=background.Enabled=true;
                    if(code!=0) Starter.Failure(Starter.Root,new IOException("private_setup_failed"));
                    status.Text=code==0?"VISION closed. Your saved work is kept.":"VISION could not start. Your work and a private failure report are kept. Try again or ask the maintainer for help."; }
            }; timer.Start();
    }
    static string StartupProblem(Exception error) {
        if(error.Message=="setup_in_progress") return "Another VISION setup is running. Let it finish, then try again.";
        if(error.Message=="storage_required") return "Free at least 3 GB on this drive, then try again. Your saved work is kept.";
        if(error.Message=="unsupported_computer") return "VISION needs a native 64-bit Intel or AMD Windows PC. This computer is not supported yet.";
        return "Setup could not finish safely. Your work and a private failure report are kept. Check your connection and try again; if it keeps happening, ask the maintainer for help.";
    }
    static string Problem(Exception error) {
        var code=error is IOException ? error.Message : "";
        if(code=="install_in_progress") return "Another VISION setup is already running. Finish it, then try again.";
        if(code=="installation_in_use") return "VISION is open. Choose Close VISION on its guided page, close the VISION Community window, then choose Install VISION again. Your saved work is kept.";
        if(code=="unfamiliar_shortcut") return "A different program already uses the VISION Community shortcut name. Nothing was changed. Ask the maintainer for help.";
        return "Some VISION application files changed or are missing. Open the VISION setup download again and choose Install VISION to repair it. Your saved work is kept.";
    }
}

static class Program {
    [STAThread] static int Main(string[] args) {
        // Use modern .NET path handling, including long per-user paths. These
        // process-local library switches do not change Windows/security policy.
        AppContext.SetSwitch("Switch.System.IO.UseLegacyPathHandling",false);
        AppContext.SetSwitch("Switch.System.IO.BlockLongPaths",false);
        if(args.Contains("--self-check")) return Package.SelfCheck();
        if(args.Length==2 && args[0]=="--detached-check") return Package.DetachedCheck(args[1]);
        if(args.Length==4 && args[0]=="--detached-child") { int parent; return Int32.TryParse(args[2],out parent) && parent>0?Package.DetachedChild(args[1],parent,args[3]):1; }
        if(args.Length==2 && args[0]=="--bootstrap-check") return StarterChecks.Check(args[1]);
        if(args.Length==2 && args[0]=="--guided-check") return StarterChecks.Guided(args[1]);
        if(args.Length==2 && args[0]=="--guided-download-check") return StarterChecks.Guided(args[1],true);
        if(args.Length==3 && args[0]=="--worker") return Background.Worker(args[1],args[2]);
        if(args.Length==2 && args[0]=="--background-check") return BackgroundChecks.Check(args[1]);
        if(args.Length==2 && args[0]=="--background-owner-check") return BackgroundChecks.Owner(args[1]);
        if(args.Length==2 && args[0]=="--background-run-check") return BackgroundChecks.Run(args[1]);
        if(args.Length==1 && args[0]=="--lifecycle-register") return BackgroundChecks.LifecycleRegister();
        Application.EnableVisualStyles(); Application.SetCompatibleTextRenderingDefault(false);
        if(args.Length==3 && args[0]=="--remove-child") { int parent; return Int32.TryParse(args[1],out parent) && parent>0?Removal.Run(parent,args[2]):1; }
        if(args.Contains("--uninstall")) {
            if(MessageBox.Show("Remove the VISION application and automatic startup? Your private account code and saved results will be kept.","Remove VISION Community",MessageBoxButtons.OKCancel)!=DialogResult.OK) return 0;
            try { Package.Uninstall(); return 0; } catch { MessageBox.Show("VISION could not be removed because some application files changed. Open the VISION setup download, choose Install VISION to repair it, then remove it again. Your saved work is kept.","VISION Community"); return 1; }
        }
        Application.Run(new Launcher(args.Contains("--background"))); return 0;
    }
}
