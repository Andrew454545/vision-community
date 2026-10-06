// Native private bootstrap. No PowerShell, policy changes, accounts or inference.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Net;
using System.Net.Http;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Web.Script.Serialization;

static class Starter {
    public const string PythonVersion="3.14.7";
    public const string PythonURL="https://www.python.org/ftp/python/3.14.7/python-3.14.7-embed-amd64.zip";
    public const string PythonSHA="d297e5ff019966817ad8502465176139f2d3d840fa4ed84b13bed399a6ab1f15";
    static readonly UTF8Encoding UTF8=new UTF8Encoding(false,true);
    [DllImport("kernel32.dll",SetLastError=true)]
    static extern bool IsWow64Process2(IntPtr process,out ushort machine,out ushort nativeMachine);
    public static string Root { get { return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"vision-community","desktop"); } }
    public static void Architecture() {
        ushort machine,nativeMachine;
        // GetNativeSystemInfo can describe x64 emulation as x64 on ARM64.
        if(!Environment.Is64BitProcess || !IsWow64Process2(Process.GetCurrentProcess().Handle,out machine,out nativeMachine) || machine!=0 || nativeMachine!=0x8664)
            throw new IOException("unsupported_computer");
    }
    public static string Hash(string path) {
        Package.Plain(path);
        using(var input=new FileStream(FilePath(path),FileMode.Open,FileAccess.Read,FileShare.Read))
        using(var sha=SHA256.Create()) return BitConverter.ToString(sha.ComputeHash(input)).Replace("-","").ToLowerInvariant();
    }
    public static string FilePath(string path) {
        path=Path.GetFullPath(path);
        // Extended local paths are supported by .NET without changing the system
        // long-path registry preference. Never create a device or UNC path here.
        if(path.Length>=248 && !path.StartsWith(@"\\") && path.Length>2 && path[1]==':') return @"\\?\"+path;
        return path;
    }
    public static long Size(string path) {
        Package.Plain(path);
        using(var input=new FileStream(FilePath(path),FileMode.Open,FileAccess.Read,FileShare.Read)) return input.Length;
    }
    public static byte[] Read(string path,int limit) {
        Package.Plain(path);
        using(var input=new FileStream(FilePath(path),FileMode.Open,FileAccess.Read,FileShare.Read)) {
            if(input.Length>limit) throw new IOException("saved_file_limit");
            using(var output=new MemoryStream()) {
                var buffer=new byte[8192]; int count;
                while((count=input.Read(buffer,0,buffer.Length))!=0) {
                    if(output.Length+count>limit) throw new IOException("saved_file_limit");
                    output.Write(buffer,0,count);
                }
                return output.ToArray();
            }
        }
    }
    public static void Json(string path,object value) {
        Package.Plain(path);
        var stage=path+"."+Guid.NewGuid().ToString("N")+".partial";
        var bytes=UTF8.GetBytes(new JavaScriptSerializer().Serialize(value)+"\n");
        using(var output=new FileStream(stage,FileMode.CreateNew,FileAccess.Write,FileShare.None)) { output.Write(bytes,0,bytes.Length); output.Flush(true); }
        // Atomic replacement; a changed/redirected destination is refused.
        Package.Plain(path);
        if(File.Exists(path)) File.Replace(stage,path,null); else File.Move(stage,path);
    }
    public static Dictionary<string,object> Object(string path,int limit=65536) {
        var value=new JavaScriptSerializer().DeserializeObject(UTF8.GetString(Read(path,limit))) as Dictionary<string,object>;
        if(value==null) throw new IOException("invalid_saved_file");
        return value;
    }
    static void Make(string path) { Package.Plain(path); Directory.CreateDirectory(path); }
    static Dictionary<string,object> Sources(string project) {
        // Build-time names come from the public source allowlist, never a checkout walk.
        var inventory=(Dictionary<string,object>)Object(Path.Combine(project,"release-inventory.json"),1000000)["files"];
        var files=new Dictionary<string,object>(StringComparer.Ordinal);
        foreach(var name in Build.SnapshotNames) {
            if(!inventory.ContainsKey(name)) throw new IOException("source_incomplete");
            files.Add(name,inventory[name]);
        }
        return files;
    }
    public static string Snapshot(string project,string root) {
        Package.Verify(project);
        var files=Sources(project);
        var lines=files.OrderBy(p=>p.Key,StringComparer.Ordinal).Select(p=>p.Key+":"+(string)((Dictionary<string,object>)p.Value)["sha256"]);
        var digest=Package.Hash(UTF8.GetBytes(String.Join("\n",lines)));
        var entries=files.OrderBy(p=>p.Key,StringComparer.Ordinal).Select(p=>new { Relative=p.Key,Sha256=(string)((Dictionary<string,object>)p.Value)["sha256"] }).ToArray();
        var metadata=UTF8.GetBytes(new JavaScriptSerializer().Serialize(new {sha256=digest,files=entries})+"\n");
        var apps=Path.Combine(root,"apps"); Make(apps);
        var target=Path.Combine(apps,digest); Package.Plain(target);
        if(!Directory.Exists(target)) {
            var stage=Path.Combine(apps,"staging-"+Guid.NewGuid().ToString("N")); Make(stage);
            foreach(var pair in files) {
                var origin=Path.Combine(project,pair.Key.Replace('/',Path.DirectorySeparatorChar)); Package.Plain(origin);
                var destination=Path.Combine(stage,pair.Key.Replace('/',Path.DirectorySeparatorChar)); Make(Path.GetDirectoryName(destination));
                File.Copy(origin,destination,false);
            }
            File.WriteAllBytes(Path.Combine(stage,"source-inventory.json"),metadata);
            VerifySnapshot(stage,files,metadata);
            Directory.Move(stage,target);
        }
        VerifySnapshot(target,files,metadata);
        return target;
    }
    static void VerifySnapshot(string target,Dictionary<string,object> files,byte[] metadata) {
        Package.Plain(target);
        var directories=new HashSet<string>(StringComparer.Ordinal);
        foreach(var name in files.Keys) {
            var parent=Path.GetDirectoryName(name.Replace('/',Path.DirectorySeparatorChar));
            while(!String.IsNullOrEmpty(parent)) { directories.Add(parent.Replace('\\','/')); parent=Path.GetDirectoryName(parent); }
        }
        var pending=new Stack<string>(); pending.Push(target);
        var seen=new HashSet<string>(StringComparer.Ordinal);
        while(pending.Count!=0) foreach(var path in Directory.GetFileSystemEntries(pending.Pop())) {
            Package.Plain(path); var name=path.Substring(target.Length+1).Replace('\\','/');
            if(Directory.Exists(path)) {
                if(!directories.Contains(name)) throw new IOException("unexpected_snapshot_directory");
                pending.Push(path);
            } else {
                if(name!="source-inventory.json" && !files.ContainsKey(name)) throw new IOException("unexpected_snapshot_file");
                seen.Add(name);
            }
        }
        if(seen.Count!=files.Count+1) throw new IOException("snapshot_incomplete");
        foreach(var pair in files) {
            var path=Path.Combine(target,pair.Key.Replace('/',Path.DirectorySeparatorChar));
            var pin=(Dictionary<string,object>)pair.Value;
            if(Size(path)!=Convert.ToInt64(pin["bytes"]) || Hash(path)!=(string)pin["sha256"]) throw new IOException("snapshot_changed");
        }
        if(!Read(Path.Combine(target,"source-inventory.json"),1000000).SequenceEqual(metadata)) throw new IOException("snapshot_receipt_changed");
    }
    static ZipArchive OpenArchive(string path) {
        Package.Plain(path); if(Size(path)>50000000) throw new IOException("python_archive_limit");
        var zip=ZipFile.OpenRead(path);
        try {
            if(zip.Entries.Count==0 || zip.Entries.Count>256) throw new IOException("python_archive_limit");
            var names=new HashSet<string>(StringComparer.OrdinalIgnoreCase); long total=0;
            foreach(var entry in zip.Entries) {
                // The official embedded distribution is flat. Reject Windows aliases.
                var name=entry.FullName; var stem=name.Split('.')[0];
                if(!Regex.IsMatch(name,@"\A[A-Za-z0-9_-][A-Za-z0-9_.-]*\z") || name.EndsWith(".") ||
                   Regex.IsMatch(stem,@"\A(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])\z",RegexOptions.IgnoreCase) ||
                   !names.Add(name) || entry.Length>64000000 || (total+=entry.Length)>256000000)
                    throw new IOException("python_archive_path");
            }
            return zip;
        } catch { zip.Dispose(); throw; }
    }
    public static void VerifyPython(string archive,string folder) {
        Package.Plain(folder);
        using(var zip=OpenArchive(archive)) {
            if(Directory.GetFileSystemEntries(folder).Length!=zip.Entries.Count) throw new IOException("python_files_changed");
            foreach(var entry in zip.Entries) {
                var path=Path.Combine(folder,entry.FullName); Package.Plain(path);
                if(!File.Exists(path) || Size(path)!=entry.Length) throw new IOException("python_files_changed");
                string expected;
                using(var input=entry.Open()) using(var sha=SHA256.Create()) expected=BitConverter.ToString(sha.ComputeHash(input)).Replace("-","").ToLowerInvariant();
                if(Hash(path)!=expected) throw new IOException("python_files_changed");
            }
        }
    }
    public static void ExtractPython(string archive,string folder) {
        Package.Plain(folder); if(Directory.Exists(folder)||File.Exists(folder)) throw new IOException("python_stage_exists");
        // Validate *all* entry names/limits before writing a file.
        using(var zip=OpenArchive(archive)) {
            Make(folder);
            foreach(var entry in zip.Entries) using(var input=entry.Open()) using(var output=new FileStream(Path.Combine(folder,entry.FullName),FileMode.CreateNew)) input.CopyTo(output);
        }
        VerifyPython(archive,folder);
    }
    static void Download(string partial) {
        Package.Plain(partial);
        using(var handler=new HttpClientHandler {AllowAutoRedirect=false,UseCookies=false,UseDefaultCredentials=false})
        using(var client=new HttpClient(handler)) using(var deadline=new CancellationTokenSource(TimeSpan.FromMinutes(3))) {
            // TLS/certificate verification and enterprise application controls stay on.
            ServicePointManager.SecurityProtocol |= SecurityProtocolType.Tls12;
            using(var response=client.GetAsync(PythonURL,HttpCompletionOption.ResponseHeadersRead,deadline.Token).GetAwaiter().GetResult()) {
                if(response.StatusCode!=HttpStatusCode.OK) throw new IOException("python_download_reply");
                if(response.Content.Headers.ContentLength>50000000) throw new IOException("python_download_limit");
                // Disposing the response at the deadline also interrupts a stalled
                // body read on Framework streams with best-effort cancellation.
                using(var cancellation=deadline.Token.Register(()=>response.Dispose()))
                using(var input=response.Content.ReadAsStreamAsync().GetAwaiter().GetResult())
                using(var output=new FileStream(partial,FileMode.CreateNew,FileAccess.Write,FileShare.None)) {
                    var buffer=new byte[65536]; long total=0; int count;
                    while((count=input.ReadAsync(buffer,0,buffer.Length,deadline.Token).GetAwaiter().GetResult())!=0) {
                        if((total+=count)>50000000) throw new IOException("python_download_limit");
                        output.Write(buffer,0,count);
                    }
                    output.Flush(true);
                    if(response.Content.Headers.ContentLength.HasValue && total!=response.Content.Headers.ContentLength.Value) throw new IOException("python_download_incomplete");
                }
            }
        }
    }
    public static string Python(string root,bool allowDownload) {
        var downloads=Path.Combine(root,"downloads"); Make(downloads);
        var archive=Path.Combine(downloads,"python-"+PythonVersion+"-embed-amd64.zip"); Package.Plain(archive);
        if(!File.Exists(archive)) {
            if(!allowDownload) throw new IOException("python_download_required");
            var partial=archive+"."+Guid.NewGuid().ToString("N")+".partial";
            Download(partial);
            if(Hash(partial)!=PythonSHA) throw new IOException("python_archive_changed");
            File.Move(partial,archive);
        }
        if(Hash(archive)!=PythonSHA) throw new IOException("python_archive_changed");
        var parent=Path.Combine(root,"python"); Make(parent);
        var folder=Path.Combine(parent,PythonVersion+"-"+PythonSHA.Substring(0,16)); Package.Plain(folder);
        if(!Directory.Exists(folder)) {
            var stage=Path.Combine(parent,"staging-"+Guid.NewGuid().ToString("N")); ExtractPython(archive,stage); Directory.Move(stage,folder);
        }
        VerifyPython(archive,folder);
        Json(Path.Combine(root,"python-provenance.json"),new {version=PythonVersion,url=PythonURL,sha256=PythonSHA});
        return Path.Combine(folder,"python.exe");
    }
    public static ProcessStartInfo Child(string python,string snapshot,string root,bool noBrowser=false) {
        var args="-I -B "+Package.Quote(Path.Combine(snapshot,"community","desktop.py"))+" --root "+Package.Quote(root)+" --native-app"+(noBrowser?" --no-browser":"");
        var info=new ProcessStartInfo(python,args) {UseShellExecute=false,CreateNoWindow=true,WindowStyle=ProcessWindowStyle.Hidden,WorkingDirectory=snapshot,RedirectStandardOutput=true,RedirectStandardError=true};
        info.EnvironmentVariables.Clear();
        foreach(var name in new[]{"SystemRoot","WINDIR","USERPROFILE","LOCALAPPDATA","APPDATA","TEMP","TMP"}) {
            var value=Environment.GetEnvironmentVariable(name); if(value!=null) info.EnvironmentVariables[name]=value;
        }
        var system=Environment.GetFolderPath(Environment.SpecialFolder.System);
        info.EnvironmentVariables["PATH"]=system+";"+Environment.GetFolderPath(Environment.SpecialFolder.Windows);
        return info;
    }
    public static bool Existing(string root,string python,bool openBrowser=true) {
        var path=Path.Combine(root,"instance.json"); Package.Plain(path);
        if(!File.Exists(path)) return false;
        try {
            var saved=Object(path); object value;
            if(!saved.TryGetValue("url",out value) || !(value is string)) return false;
            var url=(string)value; Uri uri;
            if(!Uri.TryCreate(url,UriKind.Absolute,out uri) || uri.Scheme!="http" || uri.Host!="127.0.0.1" ||
               uri.Port<1 || uri.Port>65535 || uri.AbsolutePath!="/" || uri.Query!="" || uri.UserInfo!="" ||
               !Regex.IsMatch(uri.Fragment,@"\A#[A-Za-z0-9_-]{32,128}\z") || url!=uri.AbsoluteUri) return false;
            if(!saved.TryGetValue("pid",out value) || !(value is int) || (int)value<1) return false;
            using(var process=Process.GetProcessById((int)value)) {
                if(!String.Equals(process.MainModule.FileName,python,StringComparison.OrdinalIgnoreCase) ||
                   process.SessionId!=Process.GetCurrentProcess().SessionId) return false;
                using(var handler=new HttpClientHandler {AllowAutoRedirect=false,UseProxy=false,UseCookies=false,UseDefaultCredentials=false})
                using(var client=new HttpClient(handler) {Timeout=TimeSpan.FromSeconds(5),MaxResponseContentBufferSize=65536}) {
                    var baseURL=uri.GetLeftPart(UriPartial.Authority);
                    var request=new HttpRequestMessage(HttpMethod.Get,baseURL+"/api/status");
                    request.Headers.Add("X-Vision-Token",uri.Fragment.Substring(1)); request.Headers.Add("Origin",baseURL);
                    using(request) using(var response=client.SendAsync(request).GetAwaiter().GetResult()) {
                        if(response.StatusCode!=HttpStatusCode.OK) return false;
                        var state=new JavaScriptSerializer().DeserializeObject(response.Content.ReadAsStringAsync().GetAwaiter().GetResult()) as Dictionary<string,object>;
                        if(state==null || !state.ContainsKey("busy") || !(state["busy"] is bool)) return false;
                    }
                }
                if(openBrowser) Process.Start(new ProcessStartInfo(url) {UseShellExecute=true});
                return true;
            }
        } catch { return false; }
    }
    public static Process Start(string project,string root,bool noBrowser=false,bool allowDownload=true) {
        Architecture(); Package.Verify(project); Make(root);
        var lockPath=Path.Combine(root,"launcher.lock"); Package.Plain(lockPath);
        FileStream guard;
        try { guard=new FileStream(lockPath,FileMode.OpenOrCreate,FileAccess.ReadWrite,FileShare.None); }
        catch(IOException) { throw new IOException("setup_in_progress"); }
        using(guard) {
            if(new DriveInfo(Path.GetPathRoot(root)).AvailableFreeSpace<3L*1024*1024*1024) throw new IOException("storage_required");
            if(allowDownload) Json(Path.Combine(root,"download-consent.json"),new {accepted=true,version=1,timeUtc=DateTime.UtcNow.ToString("o")});
            var snapshot=Snapshot(project,root); var python=Python(root,allowDownload);
            // Complete verification immediately before execution, including reused files.
            VerifyPython(Path.Combine(root,"downloads","python-"+PythonVersion+"-embed-amd64.zip"),Path.GetDirectoryName(python));
            Snapshot(project,root);
            if(!noBrowser && Existing(root,python)) return null;
            var child=new Process {StartInfo=Child(python,snapshot,root,noBrowser)};
            child.OutputDataReceived+=(s,e)=>{}; child.ErrorDataReceived+=(s,e)=>{};
            child.Start(); child.BeginOutputReadLine(); child.BeginErrorReadLine(); return child;
        }
    }
    public static void Failure(string root,Exception error) {
        // Fixed codes only: native output, local paths and account values never enter UI/reports.
        var known=new HashSet<string>{"unsupported_computer","setup_in_progress","storage_required","python_archive_changed","python_files_changed","python_download_required","snapshot_changed","snapshot_receipt_changed","unexpected_snapshot_file","unexpected_snapshot_directory","snapshot_incomplete","python_download_reply","python_download_limit","python_download_incomplete","source_incomplete"};
        var code=error is IOException && known.Contains(error.Message)?error.Message:"private_setup_failed";
        try { Package.Plain(root); if(Directory.Exists(root)) Json(Path.Combine(root,"setup-failure.json"),new {status="INCOMPLETE",code=code,timeUtc=DateTime.UtcNow.ToString("o")}); } catch {}
    }
}
