// Native per-user scheduling and controls. No PowerShell or elevated account.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using System.Security;
using System.Security.Principal;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using System.Xml;

sealed class BackgroundSettings {
    public string workType="scene",dayPace="medium",nightPace="max",dayStart="06:00",nightStart="00:00";
    public int retryMinutes=30,storageLimitGB=20;
    public bool keepAwake=true;
    public void Validate() {
        var paces=new[]{"slow","medium","max","pause"};
        if(!new[]{"scene","object","both"}.Contains(workType) || !paces.Contains(dayPace) || !paces.Contains(nightPace) ||
           !Regex.IsMatch(dayStart??"",@"\A(?:[01][0-9]|2[0-3]):[0-5][0-9]\z") ||
           !Regex.IsMatch(nightStart??"",@"\A(?:[01][0-9]|2[0-3]):[0-5][0-9]\z") || dayStart==nightStart ||
           retryMinutes<1 || retryMinutes>1440 || storageLimitGB<0 || storageLimitGB>4096) throw new IOException("schedule_invalid");
    }
    public static BackgroundSettings Read(string path) {
        var saved=Starter.Object(path); var settings=new BackgroundSettings();
        settings.workType=Background.Text(saved,"workType"); settings.dayPace=Background.Text(saved,"dayPace");
        settings.nightPace=Background.Text(saved,"nightPace"); settings.dayStart=Background.Text(saved,"dayStart"); settings.nightStart=Background.Text(saved,"nightStart");
        object value;
        if(!saved.TryGetValue("retryMinutes",out value) || !(value is int)) throw new IOException("schedule_invalid"); settings.retryMinutes=(int)value;
        if(!saved.TryGetValue("storageLimitGB",out value) || !(value is int)) throw new IOException("schedule_invalid"); settings.storageLimitGB=(int)value;
        if(!saved.TryGetValue("keepAwake",out value) || !(value is bool)) throw new IOException("schedule_invalid"); settings.keepAwake=(bool)value;
        settings.Validate(); return settings;
    }
}

sealed class SavedTask { public string xml; public int state; }
sealed class NativeScheduler: IDisposable {
    object service,folder;
    public NativeScheduler() {
        service=Activator.CreateInstance(Type.GetTypeFromProgID("Schedule.Service"));
        try { ((dynamic)service).Connect(); folder=((dynamic)service).GetFolder(@"\"); }
        catch { Dispose(); throw; }
    }
    static void Release(object value) { if(value!=null && Marshal.IsComObject(value)) Marshal.FinalReleaseComObject(value); }
    public SavedTask Find(string name) {
        object tasks=((dynamic)folder).GetTasks(1);
        try {
            for(int i=1;i<=((dynamic)tasks).Count;i++) {
                object item=((dynamic)tasks).Item(i);
                try { if(String.Equals((string)((dynamic)item).Name,name,StringComparison.OrdinalIgnoreCase)) return new SavedTask {xml=(string)((dynamic)item).Xml,state=(int)((dynamic)item).State}; }
                finally { Release(item); }
            }
            return null;
        } finally { Release(tasks); }
    }
    public void Save(string name,string xml,bool exists) {
        object definition=((dynamic)service).NewTask(0),saved=null;
        try {
            ((dynamic)definition).XmlText=xml;
            // CREATE or UPDATE, never silently overwrite a racing unfamiliar task.
            saved=((dynamic)folder).RegisterTaskDefinition(name,definition,(exists?4:2)|0x20,Background.Sid,null,3,null);
        } finally { Release(saved); Release(definition); }
    }
    public void Run(string name) {
        object task=((dynamic)folder).GetTask(name),running=null;
        try { running=((dynamic)task).Run(null); } finally { Release(running); Release(task); }
    }
    public void Delete(string name) { ((dynamic)folder).DeleteTask(name,0); }
    public void Dispose() { Release(folder); Release(service); folder=service=null; }
}

sealed class WorkerGuard: IDisposable {
    FileStream stream;
    public WorkerGuard(FileStream value) { stream=value; }
    public void Dispose() { if(stream!=null) { stream.Unlock(0,1); stream.Dispose(); stream=null; } }
}

static class Background {
    public const string TaskName="VISION Community Background Indexing";
    public const string ServiceURL="https://vision-community.visioncommunity.workers.dev";
    public static string Sid { get { using(var identity=WindowsIdentity.GetCurrent()) return identity.User.Value; } }
    public static string Text(Dictionary<string,object> value,string name) { object item; if(!value.TryGetValue(name,out item) || !(item is string)) throw new IOException("saved_file_invalid"); return (string)item; }
    static string Canonical(string path) {
        if(String.IsNullOrWhiteSpace(path) || !Path.IsPathRooted(path) || path.StartsWith(@"\\") || path.StartsWith(@"\\?\")) throw new IOException("private_path_invalid");
        var full=Path.GetFullPath(path); if(!String.Equals(full,path,StringComparison.OrdinalIgnoreCase)) throw new IOException("private_path_invalid"); Package.Plain(full); return full;
    }
    public static string Marker(string root,string name) { var path=Path.Combine(root,name); Package.Plain(path); if(Directory.Exists(path)) throw new IOException("marker_invalid"); return path; }
    public static void Mark(string root,string name) {
        var path=Marker(root,name); if(!File.Exists(path)) using(var file=new FileStream(path,FileMode.CreateNew,FileAccess.Write,FileShare.Read)) { file.Flush(true); }
    }
    static FileStream ControlLock(string root) {
        Canonical(root); Directory.CreateDirectory(root); var path=Marker(root,"background-install.lock");
        try { return new FileStream(path,FileMode.OpenOrCreate,FileAccess.ReadWrite,FileShare.None); }
        catch(IOException) { throw new IOException("background_setup_busy"); }
    }
    public static WorkerGuard TryWorker(string root) {
        var stream=new FileStream(Marker(root,"desktop.lock"),FileMode.OpenOrCreate,FileAccess.ReadWrite,FileShare.ReadWrite);
        try { stream.Lock(0,1); return new WorkerGuard(stream); }
        catch(IOException) { stream.Dispose(); return null; }
    }
    public static WorkerGuard Handover(string root,int seconds=60) {
        var guard=TryWorker(root);
        if(guard==null) {
            var privatePython=Path.Combine(root,"python",Starter.PythonVersion+"-"+Starter.PythonSHA.Substring(0,16),"python.exe");
            if(Starter.Existing(root,privatePython,false)) throw new IOException("worker_busy");
            var state=Text(Starter.Object(Path.Combine(root,"background-status.json")),"state");
            var idle=new[]{"paused","scheduled_pause","waiting_for_schedule","waiting_for_work","waiting_for_service","waiting_for_verification","waiting_for_space","needs_attention","running","stopped"};
            if(!idle.Contains(state)) throw new IOException("worker_busy");
            Mark(root,"STOP-AFTER-BATCH"); var deadline=DateTime.UtcNow.AddSeconds(seconds);
            while(guard==null && DateTime.UtcNow<deadline) { Thread.Sleep(250); guard=TryWorker(root); }
            if(guard==null) throw new IOException("worker_stopping");
        }
        try { Mark(root,"STOP-AFTER-BATCH"); return guard; } catch { guard.Dispose(); throw; }
    }
    public static void Account(string root,string code=null) {
        var account=Marker(root,"account.json");
        if(File.Exists(account)) {
            var saved=Starter.Object(account);
            if(Text(saved,"url")!=ServiceURL || String.IsNullOrWhiteSpace(Text(saved,"recoveryCode")) || Text(saved,"recoveryCode").Length>256) throw new IOException("account_needs_review");
            return; // Existing accounts and delivery-journal owners are never replaced.
        }
        if(String.IsNullOrWhiteSpace(code) || code.Trim().Length>256 || code.Any(c=>Char.IsControl(c))) throw new IOException("account_code_required");
        var stage=account+"."+Guid.NewGuid().ToString("N")+".partial";
        Starter.Json(stage,new {url=ServiceURL,accountId=(string)null,recoveryCode=code.Trim()});
        Package.Plain(account); File.Move(stage,account); // No overwrite on a racing setup.
    }
    static XmlDocument Document(string body) {
        if(body==null || body.Length>262144) throw new IOException("task_invalid");
        var document=new XmlDocument {XmlResolver=null};
        using(var input=new StringReader(body)) using(var reader=XmlReader.Create(input,new XmlReaderSettings {DtdProcessing=DtdProcessing.Prohibit,XmlResolver=null,MaxCharactersInDocument=262144})) document.Load(reader);
        return document;
    }
    static XmlNamespaceManager Names(XmlDocument document) { var names=new XmlNamespaceManager(document.NameTable); names.AddNamespace("t","http://schemas.microsoft.com/windows/2004/02/mit/task"); return names; }
    static string Get(XmlDocument document,XmlNamespaceManager names,string path) { var node=document.SelectSingleNode("/t:Task/"+path,names); return node==null?"":node.InnerText; }
    static bool Owner(string owner) {
        if(owner==Sid) return true;
        try { return new NTAccount(owner).Translate(typeof(SecurityIdentifier)).Value==Sid; } catch { return false; }
    }
    public static string Owned(SavedTask task,string root) {
        if(task==null) return null;
        var document=Document(task.xml); var names=Names(document);
        if(document.SelectNodes("/t:Task/t:Actions/*",names).Count!=1 || document.SelectNodes("/t:Task/t:Principals/*",names).Count!=1 ||
           !Owner(Get(document,names,"t:Principals/t:Principal/t:UserId")) || Get(document,names,"t:Principals/t:Principal/t:LogonType")!="InteractiveToken" ||
           !new[]{"","LeastPrivilege"}.Contains(Get(document,names,"t:Principals/t:Principal/t:RunLevel"))) throw new IOException("task_unfamiliar");
        var command=Canonical(Get(document,names,"t:Actions/t:Exec/t:Command"));
        var args=Regex.Match(Get(document,names,"t:Actions/t:Exec/t:Arguments"),@"\A--worker ""([^""\r\n]+)"" ([a-f0-9]{64})\z");
        if(!args.Success) throw new IOException("task_unfamiliar");
        var config=Canonical(args.Groups[1].Value); var pinned=Plan(config,args.Groups[2].Value,command);
        if(!String.Equals(Text(pinned,"root"),root,StringComparison.OrdinalIgnoreCase)) throw new IOException("task_wrong_folder");
        if(Get(document,names,"t:Actions/t:Exec/t:WorkingDirectory")!=Path.GetDirectoryName(command)) throw new IOException("task_unfamiliar");
        return config;
    }
    public static Dictionary<string,object> Plan(string config,string pin,string executable,bool current=false) {
        Canonical(config); Canonical(executable);
        if(!Regex.IsMatch(pin??"",@"\A[a-f0-9]{64}\z") || Starter.Hash(config)!=pin) throw new IOException("worker_config_changed");
        var saved=Starter.Object(config); object version;
        if(!saved.TryGetValue("version",out version) || !(version is int) || (int)version!=1 || !Regex.IsMatch(Text(saved,"revision"),@"\A[a-f0-9]{40}\z") ||
           !Regex.IsMatch(Text(saved,"inventorySha256"),@"\A[a-f0-9]{64}\z") || (current && (Text(saved,"revision")!=Build.Revision || Text(saved,"inventorySha256")!=Build.InventorySHA))) throw new IOException("worker_config_changed");
        var root=Canonical(Text(saved,"root")); var folder=Path.GetDirectoryName(config);
        var parent=Path.Combine(root,"launchers");
        if(!String.Equals(Path.GetDirectoryName(folder),parent,StringComparison.OrdinalIgnoreCase) ||
           Path.GetFileName(folder)!="native-"+pin || Path.GetFileName(config)!="worker.json" ||
           !String.Equals(executable,Path.Combine(folder,"VISION-worker.exe"),StringComparison.OrdinalIgnoreCase) || Starter.Hash(executable)!=Text(saved,"launcherSha256")) throw new IOException("worker_config_changed");
        var settings=BackgroundSettings.Read(config); settings.Validate();
        var names=Directory.GetFileSystemEntries(folder).Select(Path.GetFileName).OrderBy(x=>x,StringComparer.Ordinal).ToArray();
        if(!names.SequenceEqual(new[]{"VISION-worker.exe","project","worker.json"})) throw new IOException("worker_files_changed");
        Package.VerifyPinned(Path.Combine(folder,"project"),Text(saved,"revision"),Text(saved,"inventorySha256")); return saved;
    }
    public static string Prepare(string root,BackgroundSettings settings) {
        settings.Validate(); Canonical(root);
        var value=new Dictionary<string,object> { {"version",1},{"revision",Build.Revision},{"inventorySha256",Build.InventorySHA},{"root",root},{"launcherSha256",Starter.Hash(Package.Current)},
            {"workType",settings.workType},{"dayPace",settings.dayPace},{"nightPace",settings.nightPace},{"dayStart",settings.dayStart},{"nightStart",settings.nightStart},
            {"retryMinutes",settings.retryMinutes},{"storageLimitGB",settings.storageLimitGB},{"keepAwake",settings.keepAwake} };
        var bytes=new UTF8Encoding(false,true).GetBytes(new JavaScriptSerializer().Serialize(value)+"\n"); var digest=Package.Hash(bytes);
        var parent=Path.Combine(root,"launchers"); Package.Plain(parent); Directory.CreateDirectory(parent);
        var folder=Path.Combine(parent,"native-"+digest); Package.Plain(folder); var config=Path.Combine(folder,"worker.json");
        if(!Directory.Exists(folder)) {
            var stage=Path.Combine(parent,"staging-"+Guid.NewGuid().ToString("N")); Package.Plain(stage); Directory.CreateDirectory(stage);
            Package.Extract(Path.Combine(stage,"project")); File.Copy(Package.Current,Path.Combine(stage,"VISION-worker.exe"),false); File.WriteAllBytes(Path.Combine(stage,"worker.json"),bytes);
            Package.Verify(Path.Combine(stage,"project")); if(Starter.Hash(Path.Combine(stage,"VISION-worker.exe"))!=Text(value,"launcherSha256")) throw new IOException("worker_files_changed");
            Directory.Move(stage,folder);
        }
        Plan(config,digest,Path.Combine(folder,"VISION-worker.exe"),true); return config;
    }
    static string Escape(string value) { return SecurityElement.Escape(value); }
    public static string TaskXML(string config,string pin,DateTime? recovery=null) {
        var command=Path.Combine(Path.GetDirectoryName(config),"VISION-worker.exe");
        return "<Task version=\"1.2\" xmlns=\"http://schemas.microsoft.com/windows/2004/02/mit/task\"><RegistrationInfo><Description>Opt-in VISION processing. Resumes after sign-in; saved work is kept.</Description></RegistrationInfo>"+
            "<Triggers><LogonTrigger><Enabled>true</Enabled><UserId>"+Escape(Sid)+"</UserId></LogonTrigger><TimeTrigger><Repetition><Interval>PT15M</Interval><StopAtDurationEnd>false</StopAtDurationEnd></Repetition><StartBoundary>"+(recovery??DateTime.Now.AddMinutes(1)).ToString("yyyy-MM-ddTHH:mm:ss")+"</StartBoundary><Enabled>true</Enabled></TimeTrigger></Triggers>"+
            "<Principals><Principal id=\"Contributor\"><UserId>"+Escape(Sid)+"</UserId><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>"+
            "<Settings><MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy><DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries><StopIfGoingOnBatteries>false</StopIfGoingOnBatteries><StartWhenAvailable>true</StartWhenAvailable><RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable><IdleSettings><StopOnIdleEnd>false</StopOnIdleEnd><RestartOnIdle>false</RestartOnIdle></IdleSettings><AllowStartOnDemand>true</AllowStartOnDemand><Enabled>true</Enabled><Hidden>false</Hidden><RunOnlyIfIdle>false</RunOnlyIfIdle><WakeToRun>false</WakeToRun><ExecutionTimeLimit>PT0S</ExecutionTimeLimit><RestartOnFailure><Interval>PT5M</Interval><Count>3</Count></RestartOnFailure></Settings>"+
            "<Actions Context=\"Contributor\"><Exec><Command>"+Escape(command)+"</Command><Arguments>"+Escape("--worker "+Package.Quote(config)+" "+pin)+"</Arguments><WorkingDirectory>"+Escape(Path.GetDirectoryName(config))+"</WorkingDirectory></Exec></Actions></Task>";
    }
    public static void Readback(SavedTask task,string root,string config,string pin) {
        if(task==null || Owned(task,root)!=config) throw new IOException("recovery_settings_changed");
        var document=Document(task.xml); var names=Names(document);
        var expected=new Dictionary<string,string> {
            {"t:Settings/t:MultipleInstancesPolicy","IgnoreNew"},{"t:Settings/t:ExecutionTimeLimit","PT0S"},{"t:Settings/t:StartWhenAvailable","true"},
            {"t:Settings/t:DisallowStartIfOnBatteries","false"},{"t:Settings/t:StopIfGoingOnBatteries","false"},
            {"t:Settings/t:RestartOnFailure/t:Interval","PT5M"},{"t:Settings/t:RestartOnFailure/t:Count","3"},
            {"t:Triggers/t:TimeTrigger/t:Repetition/t:Interval","PT15M"},{"t:Actions/t:Exec/t:Arguments","--worker "+Package.Quote(config)+" "+pin} };
        foreach(var pair in expected) if(Get(document,names,pair.Key)!=pair.Value) throw new IOException("recovery_settings_changed");
        foreach(var path in new[]{"t:Settings/t:Enabled","t:Settings/t:AllowStartOnDemand"}) if(!new[]{"","true"}.Contains(Get(document,names,path))) throw new IOException("recovery_settings_changed");
        foreach(var path in new[]{"t:Settings/t:RunOnlyIfIdle","t:Settings/t:RunOnlyIfNetworkAvailable","t:Triggers/t:TimeTrigger/t:Repetition/t:StopAtDurationEnd"}) if(!new[]{"","false"}.Contains(Get(document,names,path))) throw new IOException("recovery_settings_changed");
        if(!Owner(Get(document,names,"t:Triggers/t:LogonTrigger/t:UserId")) || document.SelectNodes("/t:Task/t:Triggers/*",names).Count!=2 ||
           document.SelectNodes("/t:Task/t:Triggers/*/t:EndBoundary",names).Count!=0 || document.SelectNodes("/t:Task/t:Triggers/*[t:Enabled='false']",names).Count!=0 ||
           !new[]{"","PT0S"}.Contains(Get(document,names,"t:Triggers/t:TimeTrigger/t:Repetition/t:Duration"))) throw new IOException("recovery_settings_changed");
    }
    public static void Enable(string root,BackgroundSettings settings,string code) {
        settings.Validate(); Package.Verify(Package.Project);
        using(var controls=ControlLock(root)) using(var scheduler=new NativeScheduler()) {
            var existing=scheduler.Find(TaskName); Owned(existing,root);
            // Setup must already have prepared the selected native runtime.
            foreach(var binary in settings.workType=="scene"?new[]{"mma-vision.exe"}:settings.workType=="object"?new[]{"vision-object.exe"}:new[]{"mma-vision.exe","vision-object.exe"}) {
                var native=Path.Combine(root,"runtime","bin",binary); Package.Plain(native);
                if(!File.Exists(native)) throw new IOException("guided_setup_required");
            }
            using(var guard=Handover(root)) {
                try {
                    Account(root,code); Starter.Python(root,false);
                    var config=Prepare(root,settings); var pin=Starter.Hash(config);
                    // Refuse a competing task or changed action immediately before mutation.
                    var before=scheduler.Find(TaskName); Owned(before,root);
                    if((existing==null)!=(before==null) || (existing!=null && existing.xml!=before.xml)) throw new IOException("task_changed");
                    scheduler.Save(TaskName,TaskXML(config,pin),existing!=null); Readback(scheduler.Find(TaskName),root,config,pin);
                    Starter.Json(Path.Combine(root,"background-settings.json"),settings);
                    Starter.Json(Path.Combine(root,"background-registration.json"),new {status="SAVED_RECOVERY_SETTINGS_VERIFIED",nativeLauncher=true,unlimitedTaskLifetime=true,recoveryEveryMinutes=15,resumesAfterSignIn=true,preventsOverlappingTasks=true,actualStartVerified=false,enduranceVerified=false,timeUtc=DateTime.UtcNow.ToString("o")});
                    File.Delete(Marker(root,"STOP-AFTER-BATCH"));
                } catch(Exception error) { Mark(root,"STOP-AFTER-BATCH"); Failure(root,error); throw; }
            }
            Owned(scheduler.Find(TaskName),root); scheduler.Run(TaskName);
        }
    }
    public static void Pause(string root,bool pause,string taskName=TaskName) {
        using(var controls=ControlLock(root)) using(var scheduler=new NativeScheduler()) {
            var task=scheduler.Find(taskName); if(task==null) throw new IOException("schedule_required"); Owned(task,root);
            if(pause) Mark(root,"PAUSE");
            else {
                if(File.Exists(Marker(root,"NEEDS-ATTENTION")) || File.Exists(Marker(root,"STOP-AFTER-BATCH"))) throw new IOException("saved_stop_needs_review");
                if(task.state==1) throw new IOException("schedule_disabled");
                var config=Owned(task,root); var pin=Starter.Hash(config); Readback(task,root,config,pin);
                Readback(scheduler.Find(taskName),root,config,pin); File.Delete(Marker(root,"PAUSE")); scheduler.Run(taskName);
            }
        }
    }
    public static void TurnOff(string root,string taskName=TaskName) {
        using(var controls=ControlLock(root)) using(var scheduler=new NativeScheduler()) {
            var existing=scheduler.Find(taskName); Owned(existing,root);
            using(var guard=Handover(root)) {
                var before=scheduler.Find(taskName); Owned(before,root);
                if((existing==null)!=(before==null) || (existing!=null && existing.xml!=before.xml)) throw new IOException("task_changed");
                if(before!=null) scheduler.Delete(taskName);
            }
        }
    }
    public static int Worker(string config,string pin) {
        string root=null;
        try {
            Starter.Architecture();
            if(Regex.IsMatch(pin??"",@"\A[a-f0-9]{64}\z") && Path.GetFileName(config)=="worker.json" && Path.GetFileName(Path.GetDirectoryName(config))=="native-"+pin &&
               Path.GetFileName(Path.GetDirectoryName(Path.GetDirectoryName(config)))=="launchers" && String.Equals(Package.Current,Path.Combine(Path.GetDirectoryName(config),"VISION-worker.exe"),StringComparison.OrdinalIgnoreCase))
                root=Canonical(Path.GetDirectoryName(Path.GetDirectoryName(Path.GetDirectoryName(config))));
            // A previous terminal failure already has its retained report.
            // Recovery triggers must not grow the report folder indefinitely.
            if(root!=null && (File.Exists(Marker(root,"NEEDS-ATTENTION")) || File.Exists(Marker(root,"STOP-AFTER-BATCH")))) return 0;
            var saved=Plan(config,pin,Package.Current,true); root=Text(saved,"root");
            if(File.Exists(Marker(root,"STOP-AFTER-BATCH")) || File.Exists(Marker(root,"NEEDS-ATTENTION"))) return 0;
            using(var setup=ControlLock(root)) {
                if(File.Exists(Marker(root,"STOP-AFTER-BATCH")) || File.Exists(Marker(root,"NEEDS-ATTENTION"))) return 0;
                Account(root); var settings=BackgroundSettings.Read(config);
                var project=Path.Combine(Path.GetDirectoryName(config),"project"); var snapshot=Starter.Snapshot(project,root); var python=Starter.Python(root,false);
                // Recheck the complete source/runtime before executing any Python.
                Plan(config,pin,Package.Current,true); Starter.Snapshot(project,root);
                Starter.VerifyPython(Path.Combine(root,"downloads","python-"+Starter.PythonVersion+"-embed-amd64.zip"),Path.GetDirectoryName(python));
                var info=Starter.Child(python,snapshot,root,true);
                info.Arguments="-I -B "+Package.Quote(Path.Combine(snapshot,"community","windows_worker.py"))+" --root "+Package.Quote(root)+
                    " --accept-contributions --work-type "+settings.workType+" --day-pace "+settings.dayPace+" --night-pace "+settings.nightPace+" --day-start "+settings.dayStart+
                    " --night-start "+settings.nightStart+" --retry-minutes "+settings.retryMinutes+" --storage-limit-gb "+settings.storageLimitGB+(settings.keepAwake?"":" --no-keep-awake");
                using(var child=new Process {StartInfo=info}) {
                    child.OutputDataReceived+=(s,e)=>{}; child.ErrorDataReceived+=(s,e)=>{}; child.Start(); child.BeginOutputReadLine(); child.BeginErrorReadLine();
                    // Scheduler tracks this native parent for the whole worker lifetime.
                    // Release the installation lock so controls can cooperatively stop it.
                    setup.Dispose(); child.WaitForExit(); return child.ExitCode;
                }
            }
        } catch(Exception error) {
            // A simultaneous safe control action is temporary, not a corrupt
            // setup. Scheduler's next recovery attempt may retry it.
            if(error.Message=="background_setup_busy") return 0;
            if(root!=null) { Failure(root,error); try { Mark(root,"NEEDS-ATTENTION"); } catch {} } return 1;
        }
    }
    public static void Failure(string root,Exception error) {
        try { Package.Plain(root); var folder=Path.Combine(root,"setup-failures"); Package.Plain(folder); Directory.CreateDirectory(folder);
            Starter.Json(Path.Combine(folder,Guid.NewGuid().ToString("N")+".json"),new {status="INCOMPLETE",phase="native-background",errorType=error.GetType().Name,timeUtc=DateTime.UtcNow.ToString("o")}); } catch {}
    }
    public static string Status(string root) {
        Package.Plain(root); using(var scheduler=new NativeScheduler()) {
            var task=scheduler.Find(TaskName); if(task==null) return "Automatic processing is off. Finish setup in Start VISION, close it, then save your schedule here.";
            Owned(task,root);
            if(File.Exists(Marker(root,"NEEDS-ATTENTION"))) return "A saved failure needs review. Your work and reports are kept.";
            if(File.Exists(Marker(root,"STOP-AFTER-BATCH"))) return "Stopping safely, or stopped. Your saved stop request is kept.";
            if(task.state==1) return "Automatic processing is disabled. Save and enable your schedule first.";
            if(task.state!=4) return "The worker is not running now. Resume requests a start; Windows also retries after sign-in and every 15 minutes.";
            var path=Path.Combine(root,"background-status.json"); Package.Plain(path); if(!File.Exists(path)) return "The worker is starting. No progress report has been saved yet.";
            var report=Starter.Object(path); var state=Text(report,"state");
            var labels=new Dictionary<string,string> { {"processing","Processing a batch"},{"preparing","Checking processing files"},{"checking_pc","Checking this PC"},{"paused","Paused"},
                {"scheduled_pause","Paused by your schedule"},{"waiting_for_schedule","Paused by your schedule"},{"waiting_for_work","Waiting for locations"},{"waiting_for_service","Waiting for the service; retries automatically"},
                {"waiting_for_verification","Waiting for saved batches to be checked"},{"retrying_indexing","Recovering after a problem; retries after a rest"},{"waiting_for_space","Paused for storage"},{"needs_attention","A saved failure needs review"},{"running","Between batches"},{"stopped","Finishing a safe stop"} };
            DateTimeOffset time; var updated=DateTimeOffset.TryParse(Text(report,"updatedAt"),out time)?time.ToLocalTime().ToString("g"):"time unavailable";
            return "Worker running. Last saved status: "+(labels.ContainsKey(state)?labels[state]:"A progress report needs review")+".\r\nLast saved report: "+updated+".";
        }
    }
    public static string Problem(Exception error) {
        switch(error.Message) {
            case "schedule_invalid": return "Choose different day and night times, and a valid speed for each.";
            case "worker_busy": return "VISION is open or processing. Close Start VISION, or pause after the batch and let it finish, then try again. No active work was interrupted.";
            case "worker_stopping": return "VISION has not finished stopping. Its stop request and saved work are kept. Let the batch finish, then try again.";
            case "background_setup_busy": return "Another VISION setup or control action is running. Let it finish, then try again.";
            case "guided_setup_required": return "Finish Set up this PC in Start VISION first, then close VISION and return here.";
            case "account_code_required": return "Paste the account code you saved in Start VISION. Keep that code safe.";
            case "account_needs_review": return "Your saved account needs review. It has been kept; these controls cannot replace it.";
            case "saved_stop_needs_review": return "A saved stop or failure needs review. Resume cannot clear it. Your work and reports are kept.";
            case "schedule_required": return "Save and enable a schedule first.";
            default: return "This setup or automatic task needs review. Your account, saved work and private reports are kept. Repair changed application files using the original setup download, or ask the maintainer for help.";
        }
    }
}

sealed class BackgroundWindow: Form {
    readonly string root; Label status; ComboBox work,day,night; DateTimePicker dayTime,nightTime; NumericUpDown storage; CheckBox awake,consent; TextBox code; FlowLayoutPanel buttons; bool busy;
    public BackgroundWindow(string folder) {
        root=folder; Text="VISION - Automatic processing"; ClientSize=new Size(720,760); MinimumSize=new Size(660,720); Font=new Font("Segoe UI",12); StartPosition=FormStartPosition.CenterScreen;
        var layout=new FlowLayoutPanel {Dock=DockStyle.Fill,FlowDirection=FlowDirection.TopDown,WrapContents=false,AutoScroll=true,Padding=new Padding(20)}; Controls.Add(layout);
        Add(layout,"Let VISION help automatically. You can close these controls while it works."); status=Add(layout,"");
        var settings=File.Exists(Path.Combine(root,"background-settings.json"))?BackgroundSettings.Read(Path.Combine(root,"background-settings.json")):new BackgroundSettings();
        Add(layout,"Work to process. Each type needs its own computer check; Both takes turns.");
        work=Choice(layout,"Work to process",new[]{"Scenes","Objects","Both"},Array.IndexOf(new[]{"scene","object","both"},settings.workType));
        Add(layout,"Times use this PC's clock. Maximum skips extra rests and uses approved parallel settings.");
        var schedule=new FlowLayoutPanel {AutoSize=true,WrapContents=false}; layout.Controls.Add(schedule);
        day=Period(schedule,"Day",settings.dayStart,settings.dayPace,out dayTime); night=Period(schedule,"Night",settings.nightStart,settings.nightPace,out nightTime);
        Add(layout,"Saved file allowance (GB). Processing pauses at this amount; files are kept. 0 means no limit. A batch can temporarily exceed it.");
        storage=new NumericUpDown {Minimum=0,Maximum=4096,Value=settings.storageLimitGB,Width=160,AccessibleName="Saved file space allowance in gigabytes"}; layout.Controls.Add(storage);
        awake=new CheckBox {Text="Keep the PC awake while processing",AutoSize=true,Checked=settings.keepAwake}; layout.Controls.Add(awake);
        if(!File.Exists(Path.Combine(root,"account.json"))) Add(layout,"First time? Paste the account code you saved in Start VISION.");
        code=new TextBox {UseSystemPasswordChar=true,MaxLength=256,Width=620,AccessibleName="Private saved account code",Visible=!File.Exists(Path.Combine(root,"account.json"))}; layout.Controls.Add(code);
        consent=new CheckBox {Text="Allow automatic downloads, imagery and verified contributions",AutoSize=true}; layout.Controls.Add(consent);
        buttons=new FlowLayoutPanel {AutoSize=true,MaximumSize=new Size(640,0)}; layout.Controls.Add(buttons);
        Button("Save and enable",()=>{
            if(!consent.Checked) { status.Text="Tick the permission box to allow automatic processing."; return; }
            var selected=new BackgroundSettings {workType=new[]{"scene","object","both"}[work.SelectedIndex],dayPace=Pace(day),nightPace=Pace(night),dayStart=dayTime.Value.ToString("HH:mm"),nightStart=nightTime.Value.ToString("HH:mm"),retryMinutes=settings.retryMinutes,storageLimitGB=(int)storage.Value,keepAwake=awake.Checked};
            var savedCode=code.Text; Run(()=>Background.Enable(root,selected,savedCode),"Schedule saved and a start requested. Check status to see the last report."); code.Clear();
        });
        Button("Pause after batch",()=>Run(()=>Background.Pause(root,true),"Pause requested. VISION finishes the current batch, then waits."));
        Button("Resume",()=>Run(()=>Background.Pause(root,false),"Resume requested. Check status to see what happens next."));
        Button("Check status",()=>Run(()=>{},null));
        Button("Turn off automatic processing",()=>Run(()=>Background.TurnOff(root),"Automatic processing is off. Your saved work is kept."));
        Button("Open saved files",()=>{ try { Package.Plain(root); if(!Directory.Exists(root)) throw new IOException("schedule_required"); Process.Start(new ProcessStartInfo("explorer.exe",Package.Quote(root)) {UseShellExecute=true}); } catch(Exception error) { status.Text=Background.Problem(error); } });
        Add(layout,"After a restart, sign into Windows to resume. Sleep, power-off or a closed laptop lid stops computation until the PC is awake. Plug it into power for long runs.");
        Add(layout,"Connection problems retry after a rest. Lasting problems stop for review and keep your work. Recovery checks have passed; months-long operation still needs testing.");
        FormClosing+=(s,e)=>{ if(busy) { e.Cancel=true; status.Text="Let this action finish first. Your saved work is kept."; } }; Shown+=(s,e)=>Run(()=>{},null);
    }
    static Label Add(FlowLayoutPanel layout,string text) { var label=new Label {Text=text,AutoSize=true,MaximumSize=new Size(630,0),Margin=new Padding(0,0,0,14)}; layout.Controls.Add(label); return label; }
    static ComboBox Choice(FlowLayoutPanel layout,string name,string[] choices,int index) { var choice=new ComboBox {DropDownStyle=ComboBoxStyle.DropDownList,Width=220,AccessibleName=name}; choice.Items.AddRange(choices); choice.SelectedIndex=index; layout.Controls.Add(choice); return choice; }
    static ComboBox Period(FlowLayoutPanel layout,string name,string time,string pace,out DateTimePicker clock) { var panel=new FlowLayoutPanel {FlowDirection=FlowDirection.TopDown,WrapContents=false,AutoSize=true}; layout.Controls.Add(panel); Add(panel,name+" starts (24-hour time)"); clock=new DateTimePicker {Format=DateTimePickerFormat.Custom,CustomFormat="HH:mm",ShowUpDown=true,Width=160,Value=DateTime.Today.Add(TimeSpan.Parse(time)),AccessibleName=name+" start time"}; panel.Controls.Add(clock); return Choice(panel,name+" processing speed",new[]{"Slow","Medium","Maximum","Paused"},Array.IndexOf(new[]{"slow","medium","max","pause"},pace)); }
    static string Pace(ComboBox choice) { return new[]{"slow","medium","max","pause"}[choice.SelectedIndex]; }
    void Button(string title,Action action) { var button=new Button {Text=title,AutoSize=true,MinimumSize=new Size(120,46)}; button.Click+=(s,e)=>action(); buttons.Controls.Add(button); }
    void Run(Action action,string success) {
        if(busy) return; busy=true; buttons.Enabled=false; status.Text="Checking your saved setup. Please wait.";
        var worker=new System.ComponentModel.BackgroundWorker(); worker.DoWork+=(s,e)=>{ action(); e.Result=success??Background.Status(root); };
        worker.RunWorkerCompleted+=(s,e)=>{ busy=false; buttons.Enabled=true; worker.Dispose(); if(e.Error!=null) { Background.Failure(root,e.Error); status.Text=Background.Problem(e.Error); } else { status.Text=(string)e.Result; if(File.Exists(Path.Combine(root,"account.json"))) { code.Clear(); code.Visible=false; } } }; worker.RunWorkerAsync();
    }
}
