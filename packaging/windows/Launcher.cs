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

static class Package {
    public static string Hash(byte[] bytes) { using(var sha=SHA256.Create()) return BitConverter.ToString(sha.ComputeHash(bytes)).Replace("-", "").ToLowerInvariant(); }
    public static void Plain(string path) {
        for(var current=Path.GetFullPath(path); current!=null; current=Path.GetDirectoryName(current))
            if((File.Exists(current)||Directory.Exists(current)) && (File.GetAttributes(current)&FileAttributes.ReparsePoint)!=0) throw new IOException("redirected_package_path");
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
    public static void Verify(string root) {
        Plain(root); var path=Path.Combine(root,"release-inventory.json"); Plain(path);
        var body=File.ReadAllBytes(path); if(body.Length>1000000 || Hash(body)!=Build.InventorySHA) throw new IOException("inventory_mismatch");
        var value=new JavaScriptSerializer().Deserialize<Dictionary<string,object>>(Encoding.UTF8.GetString(body));
        if(Convert.ToInt32(value["version"])!=1 || (string)value["sourceRevision"]!=Build.Revision) throw new IOException("inventory_revision");
        var files=(Dictionary<string,object>)value["files"];
        if(files.Count>256) throw new IOException("package_limit");
        foreach(var pair in files) {
            var file=Path.Combine(root,pair.Key.Replace('/',Path.DirectorySeparatorChar)); Plain(file);
            var pin=(Dictionary<string,object>)pair.Value;
            if(new FileInfo(file).Length!=Convert.ToInt64(pin["bytes"]) || Hash(File.ReadAllBytes(file))!=(string)pin["sha256"]) throw new IOException("package_file_changed");
        }
        // Do not traverse a redirected directory, even one containing no files.
        var pending=new Stack<string>(); pending.Push(root);
        while(pending.Count>0) foreach(var entry in Directory.GetFileSystemEntries(pending.Pop())) {
            Plain(entry);
            if(Directory.Exists(entry)) pending.Push(entry);
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
    public static Process Script(string script,string arguments) {
        var shell=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Windows),"System32","WindowsPowerShell","v1.0","powershell.exe");
        var task=new Process(); task.StartInfo=new ProcessStartInfo(shell,"-NoProfile -File "+Quote(script)+" "+arguments) {
            UseShellExecute=false,CreateNoWindow=true,RedirectStandardOutput=true,RedirectStandardError=true };
        task.OutputDataReceived+=(s,e)=>{}; task.ErrorDataReceived+=(s,e)=>{};
        task.Start(); task.BeginOutputReadLine(); task.BeginErrorReadLine(); return task;
    }
    static void Shortcut(string path,string args) {
        Plain(path); Directory.CreateDirectory(Path.GetDirectoryName(path));
        var type=Type.GetTypeFromProgID("WScript.Shell"); dynamic shell=Activator.CreateInstance(type);
        dynamic link=shell.CreateShortcut(path);
        if(File.Exists(path) && !Path.GetFullPath((string)link.TargetPath).StartsWith(Base+Path.DirectorySeparatorChar,StringComparison.OrdinalIgnoreCase)) throw new IOException("unfamiliar_shortcut");
        link.TargetPath=Executable; link.Arguments=args; link.WorkingDirectory=Installed;
        link.Description="VISION Community"; link.Save();
    }
    public static void Install() {
        Plain(Installed); if(!Directory.Exists(Installed)) {
            Directory.CreateDirectory(Base); var pending=Path.Combine(Base,"staging-"+Guid.NewGuid().ToString("N"));
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
            key.SetValue("DisplayName","VISION Community"); key.SetValue("DisplayVersion","0.1.0");
            key.SetValue("InstallLocation",Installed); key.SetValue("DisplayIcon",Executable);
            key.SetValue("UninstallString",Quote(Executable)+" --uninstall"); key.SetValue("NoModify",1); key.SetValue("NoRepair",1);
        }
    }
    public static void Uninstall() {
        Verify(Project); var temporary=Path.Combine(Path.GetTempPath(),"vision-remove-"+Guid.NewGuid().ToString("N"));
        Plain(temporary); Directory.CreateDirectory(temporary);
        var helper=Path.Combine(temporary,"Remove-Vision.ps1"); File.Copy(Path.Combine(Project,"packaging","windows","Remove-Vision.ps1"),helper);
        Script(helper,"-Revision "+Build.Revision+" -InventoryHash "+Build.InventorySHA+" -WaitPid "+Process.GetCurrentProcess().Id);
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
}

sealed class Launcher: Form {
    Label status; Button start,background; Process child; bool installed,consent;
    public Launcher(bool backgroundMode) {
        installed=String.Equals(Package.Current,Package.Executable,StringComparison.OrdinalIgnoreCase);
        Text="VISION Community"; ClientSize=new Size(590,350); Font=new Font("Segoe UI",12); FormBorderStyle=FormBorderStyle.FixedDialog;
        MaximizeBox=false; StartPosition=FormStartPosition.CenterScreen;
        var heading=new Label { Text=installed?"Help VISION find places.":"Install VISION for this Windows account.",Font=new Font("Segoe UI",20,FontStyle.Bold),Left=24,Top=20,Width=540,Height=65 };
        var intro=new Label { Text="Choose Scenes, Objects or Both in the guided page. Accepted work earns search credits. Your private account code and results stay saved on this PC.",Left=24,Top=88,Width=540,Height=70 };
        status=new Label { Text=installed?"Click Start VISION to open the four simple steps.":"No Python installation or administrator password needed.",Left=24,Top=164,Width=540,Height=65 };
        start=new Button { Text=installed?"Start VISION":"Install VISION",Left=24,Top=235,Width=210,Height=48 };
        background=new Button { Text="Automatic processing",Left=249,Top=235,Width=290,Height=48,Enabled=installed };
        start.Click+=(s,e)=>Open(false); background.Click+=(s,e)=>Open(true);
        Controls.AddRange(new Control[]{heading,intro,status,start,background,new Label {Text="Keep this window open. Close VISION from its guided page first.",Left=24,Top=296,Width=540,Height=40,Font=new Font("Segoe UI",10)}});
        FormClosing+=(s,e)=>{ if(child!=null && !child.HasExited) { e.Cancel=true; MessageBox.Show(this,"Close VISION from its guided page or automatic processing controls. Wait for the current batch to finish, then close this window.","Finish safely first"); } };
        if(installed && backgroundMode) Shown+=(s,e)=>Open(true);
    }
    void Open(bool backgroundMode) {
        try {
            if(!installed) { Package.Install(); installed=true; start.Text="Start VISION"; background.Enabled=true; status.Text="Installed. Start VISION here or from the desktop shortcut."; return; }
            if(!consent) {
                if(MessageBox.Show(this,"VISION downloads its private setup files and up to about 2 GB of processing files for your chosen work. Imagery is retrieved when you request a computer check or start helping. Continue?","Allow VISION's downloads?",MessageBoxButtons.OKCancel)!=DialogResult.OK) return;
                consent=true;
            }
            Package.Verify(Package.Project);
            child=Package.Script(Path.Combine(Package.Project,"windows","Start-Vision.ps1"),"-AcceptDownloadsAndLiveImagery"+(backgroundMode?" -BackgroundControls":""));
            start.Enabled=background.Enabled=false; status.Text="Opening VISION. The first setup may take a few minutes. Keep this window open and follow the guided page.";
            var timer=new System.Windows.Forms.Timer { Interval=500 }; timer.Tick+=(s,e)=>{
                if(child!=null && child.HasExited) { var code=child.ExitCode; child.Dispose(); child=null; timer.Stop(); timer.Dispose(); start.Enabled=background.Enabled=true;
                    status.Text=code==0?"VISION closed. Your saved work is kept.":"VISION could not start. Your work and a private failure report are kept. Try again or ask the maintainer for help."; }
            }; timer.Start();
        } catch { status.Text="The VISION application files could not be verified. Get the current download. Your saved work is kept."; }
    }
}

static class Program {
    [STAThread] static int Main(string[] args) {
        if(args.Contains("--self-check")) return Package.SelfCheck();
        Application.EnableVisualStyles(); Application.SetCompatibleTextRenderingDefault(false);
        if(args.Contains("--uninstall")) {
            if(MessageBox.Show("Remove the VISION application and automatic startup? Your private account code and saved results will be kept.","Remove VISION Community",MessageBoxButtons.OKCancel)!=DialogResult.OK) return 0;
            try { Package.Uninstall(); return 0; } catch { MessageBox.Show("VISION could not be removed safely. Your application and saved work are kept. Ask the maintainer for help."); return 1; }
        }
        Application.Run(new Launcher(args.Contains("--background"))); return 0;
    }
}
