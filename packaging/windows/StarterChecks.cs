// Finite native fixtures: no installed application/task, service, account or inference.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using System.Web.Script.Serialization;

static class StarterChecks {
    [DllImport("kernel32.dll",CharSet=CharSet.Unicode,SetLastError=true)]
    static extern bool CreateSymbolicLink(string link,string target,int flags);
    static string Fresh(string root) {
        root=Path.GetFullPath(root); Package.Plain(root);
        var temp=Path.GetFullPath(Path.GetTempPath()).TrimEnd(Path.DirectorySeparatorChar)+Path.DirectorySeparatorChar;
        if(!root.StartsWith(temp,StringComparison.OrdinalIgnoreCase) || Directory.Exists(root) || File.Exists(root)) throw new IOException("fixture_scope");
        Directory.CreateDirectory(root); return root;
    }
    static void Require(bool value,string code) { if(!value) throw new IOException(code); }
    static void Refuse(Action action,string code) {
        bool refused=false; try { action(); } catch(IOException) { refused=true; } catch(UnauthorizedAccessException) { refused=true; }
        Require(refused,code);
    }
    static void Zip(string file,params string[] names) {
        using(var zip=ZipFile.Open(file,ZipArchiveMode.Create)) foreach(var name in names) {
            var entry=zip.CreateEntry(name); using(var output=entry.Open()) { var bytes=Encoding.UTF8.GetBytes("trusted fixture "+name); output.Write(bytes,0,bytes.Length); }
        }
    }
    public static int Check(string requested) {
        var checks=new List<string>(); var skips=new List<string>(); string root=null; string phase="scope";
        try {
            root=Fresh(requested); Starter.Architecture(); checks.Add("native_x64");
            var project=Path.Combine(root,"project"); phase="package"; Package.Extract(project); phase="snapshot";
            var data=Path.Combine(root,"private"); Directory.CreateDirectory(data);
            // Synthetic private values are never copied into an application snapshot.
            var saved=Path.Combine(data,"account.json"); File.WriteAllText(saved,"synthetic private data");
            var snapshot=Starter.Snapshot(project,data);
            Require(Starter.Snapshot(project,data)==snapshot,"snapshot_not_reused"); checks.Add("snapshot_reused");
            Require(!File.Exists(Path.Combine(snapshot,"account.json")),"private_data_copied"); checks.Add("private_data_excluded");
            Starter.Json(Path.Combine(data,"instance.json"),new {pid=Process.GetCurrentProcess().Id,url="https://example.invalid/#"+new String('a',32)});
            Require(!Starter.Existing(data,Package.Current,false),"external_instance_opened"); checks.Add("external_instance_refused");
            Starter.Json(Path.Combine(data,"instance.json"),new {pid=Process.GetCurrentProcess().Id,url="http://127.0.0.1:1/#"+new String('a',32)});
            Require(!Starter.Existing(data,Path.Combine(data,"python.exe"),false),"unowned_instance_opened"); File.Delete(Path.Combine(data,"instance.json")); checks.Add("unowned_instance_refused");
            var changed=Path.Combine(snapshot,"community","desktop.py"); var original=File.ReadAllBytes(changed);
            File.AppendAllText(changed,"\nchanged fixture\n"); Refuse(()=>Starter.Snapshot(project,data),"changed_snapshot_accepted"); File.WriteAllBytes(changed,original); checks.Add("changed_snapshot_refused");
            var extra=Path.Combine(snapshot,"unknown.dll"); File.WriteAllText(extra,"fixture"); Refuse(()=>Starter.Snapshot(project,data),"extra_snapshot_accepted"); File.Delete(extra); checks.Add("extra_snapshot_file_refused");
            extra=Path.Combine(snapshot,"unknown-folder"); Directory.CreateDirectory(extra); Refuse(()=>Starter.Snapshot(project,data),"empty_directory_accepted"); Directory.Delete(extra); checks.Add("extra_snapshot_directory_refused");
            var metadata=Path.Combine(snapshot,"source-inventory.json"); var receipt=File.ReadAllBytes(metadata); File.AppendAllText(metadata," "); Refuse(()=>Starter.Snapshot(project,data),"receipt_changed_accepted"); File.WriteAllBytes(metadata,receipt); checks.Add("snapshot_receipt_refused");
            File.Delete(changed); Refuse(()=>Starter.Snapshot(project,data),"missing_snapshot_accepted"); File.WriteAllBytes(changed,original); checks.Add("missing_snapshot_refused");
            var outside=Path.Combine(root,"outside.py"); File.WriteAllBytes(outside,original); File.Delete(changed);
            if(CreateSymbolicLink(changed,outside,2) || CreateSymbolicLink(changed,outside,0)) {
                Refuse(()=>Starter.Snapshot(project,data),"linked_snapshot_accepted"); File.Delete(changed); checks.Add("linked_snapshot_refused");
            } else skips.Add("linked_snapshot_privilege_unavailable");
            File.WriteAllBytes(changed,original);
            var archive=Path.Combine(root,"python.zip"); Zip(archive,"python.exe","python314._pth");
            var python=Path.Combine(root,"python"); Starter.ExtractPython(archive,python); Starter.VerifyPython(archive,python); checks.Add("runtime_extract_and_reuse");
            var exe=Path.Combine(python,"python.exe"); var bytes=File.ReadAllBytes(exe); bytes[0]^=1; File.WriteAllBytes(exe,bytes); Refuse(()=>Starter.VerifyPython(archive,python),"runtime_change_accepted"); bytes[0]^=1; File.WriteAllBytes(exe,bytes); checks.Add("same_size_runtime_change_refused");
            var unknown=Path.Combine(python,"extra.dll"); File.WriteAllText(unknown,"fixture"); Refuse(()=>Starter.VerifyPython(archive,python),"runtime_extra_accepted"); File.Delete(unknown); checks.Add("extra_runtime_refused");
            File.Delete(exe); Refuse(()=>Starter.VerifyPython(archive,python),"missing_runtime_accepted"); File.WriteAllBytes(exe,bytes); checks.Add("missing_runtime_refused");
            var badNames=new[]{new[]{"../outside.dll"},new[]{"nested/file.dll"},new[]{"python.exe:stream"},new[]{"python.exe","PYTHON.EXE"},new[]{"NUL.dll"},new[]{"trailing."},new[]{"python.exe","late/invalid"}};
            for(var i=0;i<badNames.Length;i++) {
                var bad=Path.Combine(root,"invalid-"+i+".zip"); Zip(bad,badNames[i]); var target=Path.Combine(root,"invalid-"+i);
                Refuse(()=>Starter.ExtractPython(bad,target),"unsafe_zip_accepted"); Require(!Directory.Exists(target),"unsafe_zip_wrote_files"); checks.Add("unsafe_archive_refused_"+i);
            }
            var corrupt=Path.Combine(root,"corrupt"); Directory.CreateDirectory(Path.Combine(corrupt,"downloads"));
            File.WriteAllText(Path.Combine(corrupt,"downloads","python-"+Starter.PythonVersion+"-embed-amd64.zip"),"invalid archive");
            Refuse(()=>Starter.Python(corrupt,false),"corrupt_saved_archive_accepted"); Require(!Directory.Exists(Path.Combine(corrupt,"python")),"corrupt_archive_extracted"); checks.Add("corrupt_saved_archive_not_extracted");
            var empty=Path.Combine(root,"no-download"); Directory.CreateDirectory(empty); Refuse(()=>Starter.Python(empty,false),"unconsented_download"); checks.Add("download_permission_required");
            using(var guard=new FileStream(Path.Combine(data,"launcher.lock"),FileMode.OpenOrCreate,FileAccess.ReadWrite,FileShare.None))
                Refuse(()=>Starter.Start(project,data,true,false),"parallel_setup_accepted");
            Require(!File.Exists(Path.Combine(data,"download-consent.json")),"busy_setup_wrote_consent"); checks.Add("concurrent_setup_refused_before_download");
            Starter.Failure(data,new Exception("synthetic private secret"));
            var failure=Starter.Object(Path.Combine(data,"setup-failure.json")); Require((string)failure["code"]=="private_setup_failed" && !File.ReadAllText(Path.Combine(data,"setup-failure.json")).Contains("secret"),"private_error_leaked"); checks.Add("fixed_private_failure_report");
            var info=Starter.Child("private-python.exe",snapshot,data,true);
            Require(!info.UseShellExecute && info.CreateNoWindow && info.Arguments.StartsWith("-I -B ") && !info.EnvironmentVariables.ContainsKey("PYTHONPATH") && !info.EnvironmentVariables.ContainsKey("BROWSER"),"unsafe_child_environment"); checks.Add("isolated_direct_child");
            Require(File.ReadAllText(saved)=="synthetic private data","saved_private_file_changed"); checks.Add("private_account_preserved");
            Console.WriteLine(new JavaScriptSerializer().Serialize(new {status="NATIVE_BOOTSTRAP_GUARDS_PASS",checks=checks,skips=skips,accountsCreated=0,nativeInference=false,productionQualified=false})); return 0;
        } catch(Exception error) { Console.WriteLine(new JavaScriptSerializer().Serialize(new {status="INCOMPLETE",code="native_bootstrap_check_failed",failureType=error.GetType().Name,phase=phase,missingFixtureFile=error is FileNotFoundException?Path.GetFileName(((FileNotFoundException)error).FileName):null,checks=checks,skips=skips})); return 1; }
        // The Python harness owns the disposable tree and preserves it on failure.
    }
    public static int Guided(string requested,bool allowDownload=false) {
        string data=null; Process child=null;
        try {
            Require(Environment.GetEnvironmentVariable("VISION_DISPOSABLE_GUIDED")=="1","fixture_permission");
            var root=Path.GetFullPath(requested); Package.Plain(root);
            Require(root.StartsWith(Path.GetFullPath(Path.GetTempPath()).TrimEnd(Path.DirectorySeparatorChar)+Path.DirectorySeparatorChar,StringComparison.OrdinalIgnoreCase),"fixture_scope");
            // The caller supplies only the pinned cached archive in a fresh fixture.
            Require(Directory.GetFileSystemEntries(root).Length==1 && Directory.Exists(Path.Combine(root,"private")),"fixture_not_fresh");
            data=Path.Combine(root,"private"); Require(Directory.GetFileSystemEntries(data).Length==1 && Directory.Exists(Path.Combine(data,"downloads")),"fixture_not_fresh");
            var downloads=Path.Combine(data,"downloads"); Require(Directory.GetFileSystemEntries(downloads).Length==(allowDownload?0:1),"fixture_not_fresh");
            var project=Path.Combine(root,"project"); Package.Extract(project);
            child=Starter.Start(project,data,true,allowDownload);
            var deadline=DateTime.UtcNow.AddSeconds(20); var instance=Path.Combine(data,"instance.json");
            while(!File.Exists(instance) && !child.HasExited && DateTime.UtcNow<deadline) Thread.Sleep(100);
            var python=Path.Combine(data,"python",Starter.PythonVersion+"-"+Starter.PythonSHA.Substring(0,16),"python.exe");
            Require(Starter.Existing(data,python,false),"authentic_instance_not_reused");
            Starter.Json(Path.Combine(data,"native-check-ready.json"),new {authenticatedPageVerified=true});
            // The harness sends only authenticated /api/quit to the empty local page.
            if(!child.WaitForExit(60000) || child.ExitCode!=0) throw new IOException("guided_fixture_failed");
            Require(!File.Exists(Path.Combine(data,"account.json")) && !File.Exists(Path.Combine(data,"instance.json")) && !File.Exists(Path.Combine(data,"local-test-url.txt")),"guided_fixture_cleanup_failed");
            File.Delete(Path.Combine(data,"native-check-ready.json"));
            Console.WriteLine(new JavaScriptSerializer().Serialize(new {status="NATIVE_GUIDED_START_PASS",downloadedPrivatePython=allowDownload,pythonSha256=Starter.PythonSHA,authenticatedExistingPageVerified=true,accountsCreated=0,nativeInference=false,productionQualified=false})); return 0;
        } catch(Exception error) {
            if(data!=null) Starter.Failure(data,error);
            Console.WriteLine("{\"status\":\"INCOMPLETE\",\"code\":\"guided_fixture_failed\"}"); return 1;
        } finally {
            // Only this finite empty-page fixture can be terminated after failure.
            // This path is never used for the installed app or an inference worker.
            if(child!=null) { if(!child.HasExited) { child.Kill(); child.WaitForExit(5000); } child.Dispose(); }
        }
    }
}
