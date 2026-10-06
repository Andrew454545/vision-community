// Finite synthetic checks. Never uses a production task, account or indexer.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Text;
using System.Threading;

static class BackgroundChecks {
    static int count;
    static void Check(bool value) { if(!value) throw new IOException("background_check_failed"); count++; }
    static void Refuses(Action operation) { try { operation(); } catch(Exception) { count++; return; } throw new IOException("background_guard_missing"); }
    public static int LifecycleRegister() {
        try {
            if(Environment.GetEnvironmentVariable("VISION_DISPOSABLE_LIFECYCLE")!="1" || !String.Equals(Package.Current,Package.Executable,StringComparison.OrdinalIgnoreCase)) return 1;
            Package.Verify(Package.Project); Background.Account(Starter.Root);
            using(var scheduler=new NativeScheduler()) {
                if(scheduler.Find(Background.TaskName)!=null) return 1;
                Background.Mark(Starter.Root,"PAUSE"); Background.Mark(Starter.Root,"STOP-AFTER-BATCH");
                var config=Background.Prepare(Starter.Root,new BackgroundSettings {workType="both"}); var pin=Starter.Hash(config);
                // A disposable, stopped registration only. Never request a start.
                scheduler.Save(Background.TaskName,Background.TaskXML(config,pin,new DateTime(2099,1,1)),false);
                Background.Readback(scheduler.Find(Background.TaskName),Starter.Root,config,pin);
            }
            Console.WriteLine("{\"status\":\"STOPPED_NATIVE_FIXTURE_REGISTERED\",\"accountsCreated\":0,\"serviceRequests\":0,\"nativeInference\":false}"); return 0;
        } catch { return 1; }
    }
    public static int Check(string folder) {
        string taskName=null,config=null,pin=null; bool registered=false;
        try {
            if(Environment.GetEnvironmentVariable("VISION_DISPOSABLE_BACKGROUND")!="1") return 1;
            folder=Path.GetFullPath(folder); Package.Plain(folder);
            if(Directory.Exists(folder) || File.Exists(folder) || !folder.StartsWith(Path.GetFullPath(Path.GetTempPath()).TrimEnd(Path.DirectorySeparatorChar)+Path.DirectorySeparatorChar,StringComparison.OrdinalIgnoreCase)) return 1;
            Directory.CreateDirectory(folder); var root=Path.Combine(folder,"private"); Directory.CreateDirectory(root);
            var account=Path.Combine(root,"account.json"); Background.Account(root,"SYNTHETIC-NATIVE-CHECK-NOT-AN-ACCOUNT"); var accountHash=Starter.Hash(account);
            Background.Account(root,"DO-NOT-REPLACE"); Check(Starter.Hash(account)==accountHash);
            var settings=new BackgroundSettings {workType="both"}; config=Background.Prepare(root,settings); pin=Starter.Hash(config);
            var exe=Path.Combine(Path.GetDirectoryName(config),"VISION-worker.exe");
            Check(Background.Text(Background.Plan(config,pin,exe,true),"root")==root);
            Check(Background.Prepare(root,settings)==config);
            Refuses(()=>Background.Plan(config,new string('0',64),exe));
            Refuses(()=>Background.Plan(config,pin,Package.Current));
            Refuses(()=>Background.Owned(new SavedTask {xml=Background.TaskXML(config,pin).Replace("<UserId>"+Background.Sid+"</UserId>","<UserId>S-1-5-18</UserId>")},root));
            Refuses(()=>Background.Owned(new SavedTask {xml=Background.TaskXML(config,pin).Replace("LeastPrivilege","HighestAvailable")},root));
            Refuses(()=>Background.Owned(new SavedTask {xml=Background.TaskXML(config,pin).Replace("--worker ","--other ")},root));
            Refuses(()=>Background.Owned(new SavedTask {xml=Background.TaskXML(config,pin)},Path.Combine(root,"other")));
            foreach(var change in new[]{new[]{"PT0S","PT72H"},new[]{"PT15M","PT1H"},new[]{"IgnoreNew","Parallel"},new[]{"<StartWhenAvailable>true","<StartWhenAvailable>false"},new[]{"<RunOnlyIfIdle>false","<RunOnlyIfIdle>true"},new[]{"<RunOnlyIfNetworkAvailable>false","<RunOnlyIfNetworkAvailable>true"},new[]{"<Enabled>true","<Enabled>false"},new[]{"<Count>3","<Count>1"},new[]{"<StopIfGoingOnBatteries>false","<StopIfGoingOnBatteries>true"}})
                Refuses(()=>Background.Readback(new SavedTask {xml=Background.TaskXML(config,pin).Replace(change[0],change[1])},root,config,pin));
            var altered=Path.Combine(Path.GetDirectoryName(config),"project","community","windows_worker.py"); var original=File.ReadAllBytes(altered);
            File.AppendAllText(altered,"\nchanged\n"); Refuses(()=>Background.Plan(config,pin,exe)); File.WriteAllBytes(altered,original);
            var extra=Path.Combine(Path.GetDirectoryName(config),"unexpected"); Directory.CreateDirectory(extra); Refuses(()=>Background.Plan(config,pin,exe)); Directory.Delete(extra,false);
            var executableBytes=File.ReadAllBytes(exe); File.AppendAllText(exe,"changed"); Refuses(()=>Background.Plan(config,pin,exe)); File.WriteAllBytes(exe,executableBytes);
            var supplied=File.ReadAllBytes(config); File.AppendAllText(config," "); Refuses(()=>Background.Plan(config,pin,exe)); File.WriteAllBytes(config,supplied);
            Background.Mark(root,"PAUSE"); var pauseHash=Starter.Hash(Path.Combine(root,"PAUSE"));
            using(var guard=Background.Handover(root,1)) Check(File.Exists(Path.Combine(root,"STOP-AFTER-BATCH")));
            Check(Starter.Hash(Path.Combine(root,"PAUSE"))==pauseHash && Starter.Hash(account)==accountHash);
            File.Delete(Path.Combine(root,"STOP-AFTER-BATCH"));
            // A real competing byte-range owner in another process exercises
            // refusal and cooperative handover, with no Python or network.
            var owner=new Process {StartInfo=new ProcessStartInfo(Package.Current,"--background-owner-check "+Package.Quote(root)) {UseShellExecute=false,CreateNoWindow=true}};
            owner.Start(); var ready=Path.Combine(root,"fixture-ready.json"); var deadline=DateTime.UtcNow.AddSeconds(15);
            while(!File.Exists(ready) && !owner.HasExited && DateTime.UtcNow<deadline) Thread.Sleep(100);
            Check(File.Exists(ready)); Refuses(()=>Background.Handover(root,1)); Check(!File.Exists(Path.Combine(root,"STOP-AFTER-BATCH")));
            Starter.Json(Path.Combine(root,"background-status.json"),new {state="waiting_for_work"});
            using(var guard=Background.Handover(root,10)) Check(owner.WaitForExit(10000));
            Check(Starter.Object(Path.Combine(root,"fixture-exit.json"))["observedStop"] is bool && (bool)Starter.Object(Path.Combine(root,"fixture-exit.json"))["observedStop"]);
            owner.Dispose();
            Check(Starter.Hash(account)==accountHash && Starter.Hash(Path.Combine(root,"PAUSE"))==pauseHash);
            // Actual COM registration and readback, unique name, future timer;
            // STOP prevents processing even if this account signs in during it.
            taskName="VISION Community Native Check "+Guid.NewGuid().ToString("N");
            using(var scheduler=new NativeScheduler()) {
                Check(scheduler.Find(taskName)==null); scheduler.Save(taskName,Background.TaskXML(config,pin,new DateTime(2099,1,1)),false); registered=true;
                var saved=scheduler.Find(taskName); Background.Readback(saved,root,config,pin); count++;
                Check(Background.Owned(saved,root)==config);
                Background.Pause(root,true,taskName); Check(File.Exists(Path.Combine(root,"PAUSE")));
                Refuses(()=>Background.Pause(root,false,taskName)); Check(File.Exists(Path.Combine(root,"PAUSE")) && File.Exists(Path.Combine(root,"STOP-AFTER-BATCH")));
                File.Delete(Path.Combine(root,"STOP-AFTER-BATCH")); Background.Mark(root,"NEEDS-ATTENTION");
                Refuses(()=>Background.Pause(root,false,taskName)); Check(File.Exists(Path.Combine(root,"PAUSE")) && File.Exists(Path.Combine(root,"NEEDS-ATTENTION")));
                File.Delete(Path.Combine(root,"NEEDS-ATTENTION"));
                scheduler.Save(taskName,Background.TaskXML(config,pin,new DateTime(2099,1,1)).Replace("<Enabled>true</Enabled><Hidden>","<Enabled>false</Enabled><Hidden>"),true);
                Refuses(()=>Background.Pause(root,false,taskName)); Check(File.Exists(Path.Combine(root,"PAUSE")));
                scheduler.Save(taskName,Background.TaskXML(config,pin,new DateTime(2099,1,1)),true);
                Background.TurnOff(root,taskName); registered=false; Check(scheduler.Find(taskName)==null);
                Check(Starter.Hash(account)==accountHash && Starter.Hash(Path.Combine(root,"PAUSE"))==pauseHash && File.Exists(Path.Combine(root,"STOP-AFTER-BATCH")));
            }
            Starter.Json(Path.Combine(folder,"result.json"),new {status="NATIVE_BACKGROUND_GUARDS_PASS",checks=count,accountsCreated=0,serviceRequests=0,nativeInference=false,productionQualified=false,enduranceVerified=false});
            Console.WriteLine(File.ReadAllText(Path.Combine(folder,"result.json"))); return 0;
        } catch(Exception error) {
            try { Starter.Json(Path.Combine(folder,"failure.json"),new {status="INCOMPLETE",errorType=error.GetType().Name,checks=count}); } catch {}
            Console.WriteLine("{\"status\":\"INCOMPLETE\",\"phase\":\"native-background-check\",\"checks\":"+count+"}"); return 1;
        } finally {
            if(registered) try { using(var scheduler=new NativeScheduler()) {
                var task=scheduler.Find(taskName); var root=Path.Combine(folder,"private");
                if(Background.Owned(task,root)==config) scheduler.Delete(taskName);
            } } catch { /* Preserve a stopped fixture and report if ownership changed. */ }
        }
    }
    public static int Owner(string root) {
        try {
            if(Environment.GetEnvironmentVariable("VISION_DISPOSABLE_BACKGROUND")!="1" || Path.GetFileName(root)!="private" ||
               !root.StartsWith(Path.GetFullPath(Path.GetTempPath()).TrimEnd(Path.DirectorySeparatorChar)+Path.DirectorySeparatorChar,StringComparison.OrdinalIgnoreCase)) return 1;
            Package.Plain(root);
            using(var guard=Background.TryWorker(root)) {
                if(guard==null) return 1;
                Starter.Json(Path.Combine(root,"background-status.json"),new {state="processing"}); Starter.Json(Path.Combine(root,"fixture-ready.json"),new {ready=true});
                var deadline=DateTime.UtcNow.AddSeconds(30);
                while(!File.Exists(Background.Marker(root,"STOP-AFTER-BATCH")) && DateTime.UtcNow<deadline) Thread.Sleep(100);
                var observed=File.Exists(Background.Marker(root,"STOP-AFTER-BATCH")); Starter.Json(Path.Combine(root,"fixture-exit.json"),new {observedStop=observed}); return observed?0:1;
            }
        } catch { return 1; }
    }
    public static int Run(string folder) {
        Process worker=null; string root=null;
        try {
            if(Environment.GetEnvironmentVariable("VISION_DISPOSABLE_BACKGROUND")!="1") return 1;
            folder=Path.GetFullPath(folder); Package.Plain(folder);
            if(!folder.StartsWith(Path.GetFullPath(Path.GetTempPath()).TrimEnd(Path.DirectorySeparatorChar)+Path.DirectorySeparatorChar,StringComparison.OrdinalIgnoreCase)) return 1;
            root=Path.Combine(folder,"private"); var downloads=Path.Combine(root,"downloads");
            if(!Directory.GetFileSystemEntries(folder).SequenceEqual(new[]{root}) || !Directory.GetFileSystemEntries(root).SequenceEqual(new[]{downloads}) ||
               Directory.GetFileSystemEntries(downloads).Length!=1 || Starter.Hash(Path.Combine(downloads,"python-"+Starter.PythonVersion+"-embed-amd64.zip"))!=Starter.PythonSHA) return 1;
            Background.Account(root,"SYNTHETIC-PAUSED-WORKER-NOT-AN-ACCOUNT"); Background.Mark(root,"PAUSE"); var accountHash=Starter.Hash(Path.Combine(root,"account.json"));
            var config=Background.Prepare(root,new BackgroundSettings {workType="both",keepAwake=false}); var pin=Starter.Hash(config); var exe=Path.Combine(Path.GetDirectoryName(config),"VISION-worker.exe");
            worker=Process.Start(new ProcessStartInfo(exe,"--worker "+Package.Quote(config)+" "+pin) {UseShellExecute=false,CreateNoWindow=true});
            var status=Path.Combine(root,"background-status.json"); var deadline=DateTime.UtcNow.AddSeconds(30);
            while(!File.Exists(status) && !worker.HasExited && DateTime.UtcNow<deadline) Thread.Sleep(100);
            if(!File.Exists(status) || Background.Text(Starter.Object(status),"state")!="paused" || Background.Text(Starter.Object(status),"workType")!="both") throw new IOException("real_worker_not_paused");
            Background.Mark(root,"STOP-AFTER-BATCH"); if(!worker.WaitForExit(20000) || worker.ExitCode!=0) throw new IOException("real_worker_not_stopped");
            worker.Dispose(); worker=null;
            if(Starter.Hash(Path.Combine(root,"account.json"))!=accountHash || File.Exists(Path.Combine(root,"NEEDS-ATTENTION"))) throw new IOException("real_worker_private_state_changed");
            // Damaged private Python must be refused by the native parent before
            // Python executes, with a retained redacted report and attention marker.
            File.Delete(Path.Combine(root,"STOP-AFTER-BATCH")); File.Move(status,status+".previous");
            var python=Path.Combine(root,"python",Starter.PythonVersion+"-"+Starter.PythonSHA.Substring(0,16),"python314._pth"); var original=File.ReadAllBytes(python); File.AppendAllText(python,"\nchanged\n");
            worker=Process.Start(new ProcessStartInfo(exe,"--worker "+Package.Quote(config)+" "+pin) {UseShellExecute=false,CreateNoWindow=true});
            if(!worker.WaitForExit(20000) || worker.ExitCode==0 || File.Exists(status) || !File.Exists(Path.Combine(root,"NEEDS-ATTENTION"))) throw new IOException("damaged_python_not_refused");
            worker.Dispose(); worker=null; File.WriteAllBytes(python,original);
            var failures=Directory.GetFiles(Path.Combine(root,"setup-failures"),"*.json");
            if(failures.Length!=1 || failures.Any(p=>File.ReadAllText(p).Contains("SYNTHETIC-PAUSED-WORKER"))) throw new IOException("startup_report_not_private");
            worker=Process.Start(new ProcessStartInfo(exe,"--worker "+Package.Quote(config)+" "+pin) {UseShellExecute=false,CreateNoWindow=true});
            if(!worker.WaitForExit(20000) || worker.ExitCode!=0 || Directory.GetFiles(Path.Combine(root,"setup-failures"),"*.json").Length!=1 || File.Exists(status)) throw new IOException("terminal_recovery_not_stopped");
            worker.Dispose(); worker=null;
            Starter.Json(Path.Combine(folder,"result.json"),new {status="NATIVE_PAUSED_BACKGROUND_PASS",realPrivatePython=true,workType="both",cooperativeStop=true,damagedPythonRefused=true,terminalRecoveryDoesNotRepeatReports=true,accountsCreated=0,serviceRequests=0,nativeInference=false,productionQualified=false,enduranceVerified=false});
            Console.WriteLine(File.ReadAllText(Path.Combine(folder,"result.json"))); return 0;
        } catch(Exception error) {
            try { Starter.Json(Path.Combine(folder,"failure.json"),new {status="INCOMPLETE",phase="native-paused-background-check",errorType=error.GetType().Name}); } catch {}
            Console.WriteLine("{\"status\":\"INCOMPLETE\",\"phase\":\"native-paused-background-check\"}"); return 1;
        } finally {
            if(worker!=null) { try { if(!worker.HasExited && root!=null) { Background.Mark(root,"STOP-AFTER-BATCH"); worker.WaitForExit(20000); } } catch {} worker.Dispose(); }
        }
    }
}
