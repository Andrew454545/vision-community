// Local-only Scene pilot. Reuse the verified private bootstrap; no PowerShell.
using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Windows.Forms;

static class Package {
    public static string Project { get { return Path.Combine(Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location),"project"); } }
    public static string Hash(byte[] body) { using(var sha=SHA256.Create()) return BitConverter.ToString(sha.ComputeHash(body)).Replace("-","").ToLowerInvariant(); }
    public static string Quote(string value) {
        if(value.Contains("\"")||value.Contains("\r")||value.Contains("\n")||value.EndsWith("\\")) throw new IOException("invalid_argument");
        return "\""+value+"\"";
    }
    public static void Plain(string path) {
        for(var current=Path.GetFullPath(path);current!=null;current=Path.GetDirectoryName(current))
            try { if((File.GetAttributes(Starter.FilePath(current))&FileAttributes.ReparsePoint)!=0) throw new IOException("redirected_package_path"); }
            catch(FileNotFoundException) {} catch(DirectoryNotFoundException) {}
    }
    public static void Verify(string root) {
        root=Path.GetFullPath(root); Plain(root);
        var path=Path.Combine(root,"release-inventory.json");
        var bytes=Starter.Read(path,1000000);
        if(Hash(bytes)!=Build.InventorySHA) throw new IOException("inventory_changed");
        var value=Starter.Object(path,1000000);
        if(Convert.ToInt32(value["version"])!=1 || (string)value["sourceRevision"]!=Build.Revision) throw new IOException("inventory_revision");
        var files=(Dictionary<string,object>)value["files"];
        var expected=new HashSet<string>(Build.PackageNames,StringComparer.Ordinal);
        if(files.Count!=expected.Count || files.Keys.Any(name=>!expected.Contains(name))) throw new IOException("package_names_changed");
        var directories=new HashSet<string>(StringComparer.Ordinal);
        foreach(var name in expected) {
            // Names are generated from the checked source inventory, not user input.
            if(name.StartsWith("/")||name.Contains("\\")||name.Contains(":")||name.Split('/').Any(p=>p=="."||p==".."||p.Length==0)) throw new IOException("package_path");
            var pin=(Dictionary<string,object>)files[name];
            var file=Path.Combine(root,name.Replace('/',Path.DirectorySeparatorChar)); Plain(file);
            if(Starter.Size(file)!=Convert.ToInt64(pin["bytes"]) || Starter.Hash(file)!=(string)pin["sha256"]) throw new IOException("package_file_changed");
            var parent=Path.GetDirectoryName(name.Replace('/',Path.DirectorySeparatorChar));
            while(!String.IsNullOrEmpty(parent)) { directories.Add(parent.Replace('\\','/')); parent=Path.GetDirectoryName(parent); }
        }
        var pending=new Stack<string>();pending.Push(root);
        while(pending.Count>0) foreach(var item in Directory.GetFileSystemEntries(pending.Pop())) {
            Plain(item);var name=item.Substring(root.Length+1).Replace('\\','/');
            if(Directory.Exists(item)) { if(!directories.Contains(name)) throw new IOException("unexpected_package_directory");pending.Push(item); }
            else if(name!="release-inventory.json"&&!expected.Contains(name)) throw new IOException("unexpected_package_file");
        }
    }
}

static class LocalScenes {
    public static string Root { get { return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"vision-community","local-scene-pilot-app"); } }
    public static ProcessStartInfo Child(string python,string snapshot,string root,string module,string arguments) {
        var info=Starter.Child(python,snapshot,root);
        info.Arguments="-I -B "+Package.Quote(Path.Combine(snapshot,"community",module))+" "+arguments;
        var temp=Path.Combine(root,"temp");Package.Plain(temp);Directory.CreateDirectory(temp);
        info.EnvironmentVariables["TEMP"]=temp;info.EnvironmentVariables["TMP"]=temp;info.EnvironmentVariables["TMPDIR"]=temp;
        return info;
    }
    public static int Run(ProcessStartInfo info,string root,string label,int seconds) {
        var folder=Path.Combine(root,"logs");Package.Plain(folder);Directory.CreateDirectory(folder);
        var stem=Path.Combine(folder,label+"-"+Guid.NewGuid().ToString("N"));
        using(var output=new StreamWriter(stem+".stdout.log")) using(var error=new StreamWriter(stem+".stderr.log"))
        using(var process=new Process {StartInfo=info}) {
            process.OutputDataReceived+=(s,e)=>{if(e.Data!=null) output.WriteLine(e.Data);};
            process.ErrorDataReceived+=(s,e)=>{if(e.Data!=null) error.WriteLine(e.Data);};
            process.Start();process.BeginOutputReadLine();process.BeginErrorReadLine();
            if(!process.WaitForExit(seconds*1000)) {process.Kill();process.WaitForExit();throw new IOException("local_setup_timeout");}
            process.WaitForExit();return process.ExitCode;
        }
    }
    public static Process Start(string packet,string root,bool downloads) {
        Starter.Architecture();Package.Verify(Package.Project);Package.Plain(root);Directory.CreateDirectory(root);
        Package.Plain(packet);
        if(Starter.Size(packet)>16*1024*1024)throw new IOException("packet_limit");
        var lockPath=Path.Combine(root,"launcher.lock");Package.Plain(lockPath);
        using(var guard=new FileStream(lockPath,FileMode.OpenOrCreate,FileAccess.ReadWrite,FileShare.None)) {
            if(new DriveInfo(Path.GetPathRoot(root)).AvailableFreeSpace<3L*1024*1024*1024) throw new IOException("storage_required");
            var snapshot=Starter.Snapshot(Package.Project,root);
            var python=Starter.Python(root,downloads);
            if(Run(Child(python,snapshot,root,"local_scene_ui.py","--packet "+Package.Quote(packet)+" --check-only"),root,"packet-check",60)!=0)
                throw new IOException("invalid_scene_packet");
            var runtime=Path.Combine(root,"runtime");
            var setup="--kit-runtime "+Package.Quote(Path.Combine(Package.Project,"pilot-runtime"))+" --runtime-root "+Package.Quote(runtime)+(downloads?" --download-models":"");
            if(Run(Child(python,snapshot,root,"local_scene_setup.py",setup),root,"scene-setup",1900)!=0) throw new IOException("local_scene_setup_failed");
            // Recheck Python/source before the long-lived user-controlled UI.
            Starter.Python(root,false);Starter.Snapshot(Package.Project,root);
            var nativeArguments="";
            var nativeManifest=Path.Combine(Package.Project,"native-window","manifest.json");
            if(File.Exists(nativeManifest)) {
                if(Run(Child(python,snapshot,root,"local_scene_window.py","--provision-from "+Package.Quote(Package.Project)+" --root "+Package.Quote(root)),root,"native-window-setup",60)!=0)
                    throw new IOException("native_window_setup_failed");
                nativeArguments=" --native-window-dir "+Package.Quote(Path.Combine(root,"native-windows",Starter.Hash(nativeManifest)));
            }
            var info=Child(python,snapshot,root,"local_scene_supervisor.py","--packet "+Package.Quote(packet)+" --data-dir "+Package.Quote(Path.Combine(root,"results"))+" --runtime-root "+Package.Quote(runtime)+" --app-root "+Package.Quote(root)+nativeArguments);
            var child=new Process {StartInfo=info};
            // The UI writes durable worker diagnostics. It does not send private
            // paths or native output into this beginner-facing launcher window.
            child.OutputDataReceived+=(s,e)=>{};child.ErrorDataReceived+=(s,e)=>{};
            child.Start();child.BeginOutputReadLine();child.BeginErrorReadLine();return child;
        }
    }
    public static int Reopen(string packet,string root) {
        Package.Verify(Package.Project);
        var python=Starter.Python(root,false);var snapshot=Starter.Snapshot(Package.Project,root);
        return Run(Child(python,snapshot,root,"local_scene_ui.py","--packet "+Package.Quote(packet)+" --data-dir "+
            Package.Quote(Path.Combine(root,"results"))+" --runtime-root "+Package.Quote(Path.Combine(root,"runtime"))+" --app-root "+Package.Quote(root)+" --reopen-only"),root,"reopen-window",15);
    }
    public static int CheckComputer() {
        var root=Root;
        Starter.Architecture();Package.Verify(Package.Project);Package.Plain(root);Directory.CreateDirectory(root);
        var packet=Path.Combine(Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location),"Readiness","Check this computer.json");
        Package.Plain(packet);
        if(!File.Exists(packet))throw new IOException("readiness_files_missing");
        var lockPath=Path.Combine(root,"launcher.lock");Package.Plain(lockPath);
        using(var guard=new FileStream(lockPath,FileMode.OpenOrCreate,FileAccess.ReadWrite,FileShare.None)) {
            if(new DriveInfo(Path.GetPathRoot(root)).AvailableFreeSpace<3L*1024*1024*1024)throw new IOException("storage_required");
            var snapshot=Starter.Snapshot(Package.Project,root);
            var python=Starter.Python(root,true);
            var runtime=Path.Combine(root,"runtime");
            var setup="--kit-runtime "+Package.Quote(Path.Combine(Package.Project,"pilot-runtime"))+" --runtime-root "+Package.Quote(runtime)+" --download-models";
            if(Run(Child(python,snapshot,root,"local_scene_setup.py",setup),root,"scene-setup",1900)!=0)throw new IOException("local_scene_setup_failed");
            var result=Path.Combine(root,"computer-check-"+Guid.NewGuid().ToString("N")+".json");
            var args="--check "+Package.Quote(packet)+" --data-dir "+Package.Quote(Path.Combine(root,"results"))+" --runtime-root "+Package.Quote(runtime)+" --result "+Package.Quote(result);
            var code=Run(Child(python,snapshot,root,"local_scene_check.py",args),root,"computer-check",2200);
            if(File.Exists(result))Console.WriteLine(Encoding.UTF8.GetString(Starter.Read(result,16384)));
            return code;
        }
    }
    public static int Offline(string root) {
        var prefix=Path.GetFullPath(Path.GetTempPath()).TrimEnd(Path.DirectorySeparatorChar)+Path.DirectorySeparatorChar;
        root=Path.GetFullPath(root);Package.Plain(root);
        if(!root.StartsWith(prefix,StringComparison.OrdinalIgnoreCase)||!Path.GetFileName(root).StartsWith("vision-local-pilot-"))throw new IOException("offline_fixture_scope");
        Starter.Architecture();Package.Verify(Package.Project);Directory.CreateDirectory(root);
        var snapshot=Starter.Snapshot(Package.Project,root);var python=Starter.Python(root,false);
        if(Run(Child(python,snapshot,root,"local_scene_ui.py","--help"),root,"ui-import",60)!=0)throw new IOException("private_ui_import_failed");
        var packet=Path.Combine(root,"synthetic-packet.json");
        if(Run(Child(python,snapshot,root,"local_scene_ui.py","--packet "+Package.Quote(packet)+" --check-only"),root,"packet-check",60)!=0)
            throw new IOException("offline_packet_check_failed");
        var runtime=Path.Combine(root,"runtime");
        var setup="--kit-runtime "+Package.Quote(Path.Combine(Package.Project,"pilot-runtime"))+" --runtime-root "+Package.Quote(runtime);
        if(Run(Child(python,snapshot,root,"local_scene_setup.py",setup),root,"offline-setup",120)!=0)throw new IOException("offline_setup_failed");
        Application.EnableVisualStyles();Application.SetCompatibleTextRenderingDefault(false);
        using(var form=new PilotWindow()) using(var bitmap=new Bitmap(form.Width,form.Height)) {
            var formHandle=form.Handle;
            foreach(Control control in form.Controls){var controlHandle=control.Handle;}
            form.PerformLayout();
            form.DrawToBitmap(bitmap,new Rectangle(0,0,bitmap.Width,bitmap.Height));
            bitmap.Save(Path.Combine(root,"launcher-preview.png"),System.Drawing.Imaging.ImageFormat.Png);
        }
        Starter.Json(Path.Combine(root,"offline-launcher-check.json"),new {status="LOCAL_PILOT_OFFLINE_PASS",privatePythonVerified=true,sourceSnapshotVerified=true,
            cachedSceneFilesVerified=true,syntheticPacketValidated=true,windowConstructedWithoutShowing=true,hiddenChildren=true,powershellUsed=false,downloadsAllowed=false,accountsCreated=0,imageryCalls=0,cloudCalls=0,inferenceRuns=0,productionQualified=false});
        Console.WriteLine("LOCAL_PILOT_OFFLINE_PASS");return 0;
    }
}

sealed class PilotWindow:Form {
    Label status; Button choose,open,library,storage; string packet; Process child;bool preparing;
    public PilotWindow() {
        Text="VISION Local Scenes";ClientSize=new Size(610,510);Font=new Font("Segoe UI",11);
        FormBorderStyle=FormBorderStyle.FixedDialog;MaximizeBox=false;StartPosition=FormStartPosition.CenterScreen;
        var title=new Label {Text="Process and search on your computer.",Font=new Font("Segoe UI",19,FontStyle.Bold),Left=24,Top=22,Width=560,Height=65};
        var intro=new Label {Text="Process your personal queue and search your saved Scenes. Results stay here. No account or cloud search is needed.",Left=24,Top=95,Width=560,Height=70};
        status=new Label {Text="Check this computer first. After approval, open your personal queue. My library opens your saved Scenes.",Left=24,Top=173,Width=560,Height=75};
        choose=new Button {Text="Open personal queue",Left=24,Top=260,Width=250,Height=48};
        open=new Button {Text="Check this computer",Left=290,Top=260,Width=285,Height=48,Enabled=false};
        library=new Button {Text="My library",Left=24,Top=320,Width=551,Height=48};
        storage=new Button {Text="Choose storage folder",Left=24,Top=378,Width=551,Height=42};
        var readiness=Path.Combine(Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location),"Readiness","Check this computer.json");
        if(File.Exists(readiness)) {packet=readiness;open.Enabled=true;status.Text="Click Check this computer to begin. When the checks finish, save results and send them to the maintainer.";}
        Controls.AddRange(new Control[]{title,intro,status,choose,open,library,storage,new Label {Text="Use Exit in the local window before closing this launcher.",Left=24,Top=440,Width=560,Height=44}});
        choose.Click+=(s,e)=>{using(var picker=new OpenFileDialog {Title="Choose Check this computer.json or your approved campaign.json",Filter="VISION check or queue (*.json)|*.json"})
            if(picker.ShowDialog(this)==DialogResult.OK){packet=picker.FileName;status.Text="Your file is selected. Open the local pilot to continue.";open.Text="Open local pilot";open.Enabled=true;}};
        open.Click+=(s,e)=>OpenPilot();
        library.Click+=(s,e)=>{packet=Path.Combine(Package.Project,"community","local_scene_library.json");OpenPilot();};
        storage.Click+=(s,e)=>{using(var picker=new FolderBrowserDialog {Description="Choose a disk or folder for new Scene work. Existing files stay in place.",ShowNewFolderButton=true})
            if(picker.ShowDialog(this)==DialogResult.OK)try {var root=LocalScenes.Root;Package.Plain(root);Directory.CreateDirectory(root);Package.Plain(picker.SelectedPath);
                Starter.Json(Path.Combine(root,"local-scene-storage-choice.json"),new {version=1,selected=Path.GetFullPath(picker.SelectedPath)});
                status.Text="New queues and searchable copies will use VISION Local Scenes Data in that folder. Keep earlier work folders connected; My library can recover them.";
            }catch(Exception error){Starter.Failure(LocalScenes.Root,error);status.Text="The storage choice could not be saved. Your existing work is kept.";}};
        FormClosing+=(s,e)=>{if(preparing||(child!=null&&!child.HasExited)){e.Cancel=true;MessageBox.Show(this,"Finish setup, or choose Exit in the local pilot window and wait for the current group to finish.","Keep your work safe");}};
    }
    void OpenPilot() {
        if(child!=null&&!child.HasExited) {
            preparing=true;open.Enabled=false;
            var reopen=new BackgroundWorker();
            reopen.DoWork+=(s,e)=>{e.Result=LocalScenes.Reopen(packet,LocalScenes.Root);};
            reopen.RunWorkerCompleted+=(s,e)=>{preparing=false;reopen.Dispose();open.Enabled=true;
                status.Text=e.Error==null&&(int)e.Result==0?"Your existing local pilot window has been reopened.":"The pilot window could not be reopened. Keep your files and ask the maintainer for help.";};
            reopen.RunWorkerAsync();return;
        }
        if(MessageBox.Show(this,"Setup downloads private Python and about 1 GB of Scene models once. The first computer check uses fixed local images. Your approved personal queue later retrieves Street View imagery and uses your CPU. Results stay on this computer. Continue?","Local Scene setup",MessageBoxButtons.OKCancel)!=DialogResult.OK)return;
        preparing=true;storage.Enabled=library.Enabled=choose.Enabled=open.Enabled=false;status.Text="Preparing the local Scene files. Keep this window open; the first download may take a few minutes.";
        var setup=new BackgroundWorker();
        setup.DoWork+=(s,e)=>{e.Result=LocalScenes.Start(packet,LocalScenes.Root,true);};
        setup.RunWorkerCompleted+=(s,e)=>{
            preparing=false;setup.Dispose();
            if(e.Error!=null){Starter.Failure(LocalScenes.Root,e.Error);storage.Enabled=library.Enabled=choose.Enabled=open.Enabled=true;status.Text="Setup could not finish. Your files and a private report are kept. Ask the maintainer for help.";return;}
            child=(Process)e.Result;open.Enabled=true;open.Text="Reopen VISION";status.Text="VISION is opening. Use Start and Pause in its window. If WebView2 is unavailable, the browser interface opens instead.";
            var timer=new System.Windows.Forms.Timer {Interval=500};timer.Tick+=(sender,ev)=>{
                if(child.HasExited){var code=child.ExitCode;child.Dispose();child=null;timer.Stop();timer.Dispose();storage.Enabled=library.Enabled=choose.Enabled=open.Enabled=true;open.Text="Open local pilot";
                    status.Text=code==0?"Local pilot closed or its existing window reopened. Your saved work is kept.":"The local pilot stopped. Your files are kept; ask the maintainer to review the saved report.";}};
            timer.Start();};
        setup.RunWorkerAsync();
    }
}

static class Program {
    [STAThread] static int Main(string[] args) {
        AppContext.SetSwitch("Switch.System.IO.UseLegacyPathHandling",false);AppContext.SetSwitch("Switch.System.IO.BlockLongPaths",false);
        try {
            if(args.Length==1&&args[0]=="--self-check") {Starter.Architecture();Package.Verify(Package.Project);
                Console.WriteLine("LOCAL_PILOT_PACKAGE_VERIFIED");return 0;}
            if(args.Length==2&&args[0]=="--check-computer"&&args[1]=="--accept-downloads")return LocalScenes.CheckComputer();
            if(args.Length==2&&args[0]=="--offline-check")return LocalScenes.Offline(args[1]);
            if(args.Length!=0)return 2;
            Starter.Architecture();Package.Verify(Package.Project);
            Application.EnableVisualStyles();Application.SetCompatibleTextRenderingDefault(false);
            Application.Run(new PilotWindow());return 0;
        } catch(Exception error) {
            Starter.Failure(LocalScenes.Root,error);
            if(args.Length==0){MessageBox.Show("VISION Local Scenes could not start. Ask the maintainer for a complete trusted pilot kit. Your saved work is kept.","VISION Local Scenes");}
            else Console.WriteLine("LOCAL_PILOT_CHECK_FAILED");return 1;
        }
    }
}
