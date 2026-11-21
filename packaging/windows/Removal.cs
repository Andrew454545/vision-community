// Detached native removal. Private processing files are outside the program.
using System;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Windows.Forms;
using Microsoft.Win32;

static class Removal {
    const string Key=@"Software\Microsoft\Windows\CurrentVersion\Uninstall\VISIONCommunity";
    public static int Run(int parent,string executable) {
        FileStream guard=null;
        var helper=Path.GetDirectoryName(Package.Current);
        try {
            Package.Plain(helper); Package.Plain(executable);
            var temporary=Path.GetFullPath(Path.GetTempPath()).TrimEnd(Path.DirectorySeparatorChar);
            if(Path.GetDirectoryName(helper)!=temporary || !System.Text.RegularExpressions.Regex.IsMatch(Path.GetFileName(helper),@"\Avision-remove-[a-f0-9]{32}\z") ||
               Path.GetFileName(Package.Current)!="VISION-remove.exe" || !String.Equals(executable,Package.Executable,StringComparison.OrdinalIgnoreCase) || Starter.Hash(executable)!=Starter.Hash(Package.Current)) throw new IOException("removal_scope");
            try { using(var waiting=Process.GetProcessById(parent)) {
                if(!waiting.HasExited) {
                    try { if(!String.Equals(waiting.MainModule.FileName,executable,StringComparison.OrdinalIgnoreCase)) throw new IOException("removal_scope"); }
                    catch(System.ComponentModel.Win32Exception) { if(!waiting.HasExited) throw; }
                    catch(InvalidOperationException) { if(!waiting.HasExited) throw; }
                    if(!waiting.WaitForExit(30000)) throw new IOException("application_still_running");
                }
            } } catch(ArgumentException) { /* The authentic parent already exited. */ }
            Package.Plain(Package.Base); var lockPath=Path.Combine(Package.Base,"install.lock"); Package.Plain(lockPath);
            try { guard=new FileStream(lockPath,FileMode.OpenOrCreate,FileAccess.ReadWrite,FileShare.None); }
            catch(IOException) { throw new IOException("setup_in_progress"); }
            Package.Verify(Package.Project);
            if(Starter.Hash(executable)!=Starter.Hash(Package.Current) || Package.Running(Package.Installed)) throw new IOException("application_still_running");
            var contents=Directory.GetFileSystemEntries(Package.Installed).Select(Path.GetFileName).OrderBy(x=>x,StringComparer.Ordinal).ToArray();
            if(!contents.SequenceEqual(new[]{"VISION.exe","project"})) throw new IOException("unfamiliar_program_file");
            // Validate the task before touching any marker, shortcut or program.
            using(var scheduler=new NativeScheduler()) Background.Owned(scheduler.Find(Background.TaskName),Starter.Root);
            if(Directory.Exists(Starter.Root)) Background.TurnOff(Starter.Root);
            else using(var scheduler=new NativeScheduler()) { if(scheduler.Find(Background.TaskName)!=null) throw new IOException("task_unfamiliar"); }
            var menu=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Programs),"VISION Community"); Package.Plain(menu);
            var links=new[]{Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory),"VISION Community.lnk"),Path.Combine(menu,"VISION Community.lnk"),Path.Combine(menu,"Automatic processing.lnk")};
            dynamic shell=Activator.CreateInstance(Type.GetTypeFromProgID("WScript.Shell"));
            try {
                foreach(var linkPath in links) {
                    Package.Plain(linkPath); if(!File.Exists(linkPath)) continue;
                    dynamic link=shell.CreateShortcut(linkPath);
                    try { if(String.Equals((string)link.TargetPath,executable,StringComparison.OrdinalIgnoreCase)) File.Delete(linkPath); }
                    finally { System.Runtime.InteropServices.Marshal.FinalReleaseComObject(link); }
                }
            } finally { System.Runtime.InteropServices.Marshal.FinalReleaseComObject(shell); }
            using(var key=Registry.CurrentUser.OpenSubKey(Key)) {
                if(key!=null && String.Equals(key.GetValue("InstallLocation") as string,Package.Installed,StringComparison.OrdinalIgnoreCase)) Registry.CurrentUser.DeleteSubKeyTree(Key,false);
            }
            // Verify once more, then rename only this exact per-user program.
            // A locked/open program refuses the rename and preserves its bytes.
            Package.Verify(Package.Project);
            var retired=Path.Combine(Package.Base,"retired-"+Guid.NewGuid().ToString("N")); Package.Plain(retired);
            Directory.Move(Package.Installed,retired); Package.Remove(retired);
            if(Directory.Exists(menu) && Directory.GetFileSystemEntries(menu).Length==0) Directory.Delete(menu,false);
            guard.Dispose(); guard=null;
            // A racing setup's exclusive handle refuses deletion; a populated
            // program folder refuses this nonrecursive empty-folder removal.
            try { File.Delete(lockPath); if(Directory.GetFileSystemEntries(Package.Base).Length==0) Directory.Delete(Package.Base,false); } catch(IOException) {} catch(UnauthorizedAccessException) {}
            Starter.Json(Path.Combine(helper,"result.json"),new {status="NATIVE_REMOVAL_COMPLETE",privateFilesPreserved=true,forceStoppedProcesses=0,productionQualified=false});
            // The running executable cannot erase itself. This bounded temporary
            // helper and receipt stay together; no shell or policy workaround.
            return 0;
        } catch(Exception error) {
            try { Starter.Json(Path.Combine(helper,"result.json"),new {status="INCOMPLETE",phase="native-removal",errorType=error.GetType().Name,privateFilesPreserved=true}); } catch {}
            var message=error.Message=="setup_in_progress"?"VISION setup is still running. Finish setup, then try removing VISION again. Your application and saved work are kept.":
                "VISION was not removed because it is still processing or its files changed. Your application and saved work are kept. Choose Pause after this batch, wait for the batch to finish, close VISION, then remove it again.";
            MessageBox.Show(message,"VISION Community"); return 1;
        } finally { if(guard!=null) guard.Dispose(); }
    }
}
