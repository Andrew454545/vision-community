"""Run only the Windows launch-diagnostic fixture, without setup or inference."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from community.process_owner import run_owned

HARNESS = r'''
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Text;
using System.Threading;
using System.Windows.Forms;

static class Build {
    public const string Revision="fixture",InventorySHA="fixture";
    public static readonly string[] PackageNames=new string[0],SnapshotNames=new string[0];
}
static class LaunchChecks {
    static void Need(bool ok,string code) {if(!ok)throw new Exception(code);}
    static Dictionary<string,object> Record(string root) {
        var files=Directory.GetFiles(Path.Combine(root,"logs"),"*.json");
        Need(files.Length==1,"receipt_count");return Starter.Object(files[0]);
    }
    static Dictionary<string,object> StreamRecord(Dictionary<string,object> item,string name) {
        return (Dictionary<string,object>)item[name];
    }
    static ProcessStartInfo Info(string mode) {
        return new ProcessStartInfo(Assembly.GetExecutingAssembly().Location,"fixture "+mode) {
            UseShellExecute=false,CreateNoWindow=true,WindowStyle=ProcessWindowStyle.Hidden,
            RedirectStandardOutput=true,RedirectStandardError=true
        };
    }
    static PilotChild Child(string root,string mode) {Directory.CreateDirectory(root);return PilotChild.Start(Info(mode),root);}
    static void Wait(PilotChild child) {
        var clock=Stopwatch.StartNew();while(!child.Complete&&clock.ElapsedMilliseconds<15000)Thread.Sleep(10);
        Need(child.Complete,"child_did_not_finish");
    }
    static void Finished(string root,string mode,int expected) {
        using(var child=Child(root,mode)) {
            Wait(child);Need(child.ExitCode==expected,"exit_code");Need(child.ReceiptSaved,"missing_receipt");
            var receipt=Record(root);Need((string)receipt["status"]=="EXITED"&&(bool)receipt["started"],"exit_receipt");
            Need(Convert.ToInt32(receipt["exitCode"])==expected,"receipt_exit_code");
            foreach(var stream in new[]{"stdout","stderr"}) {
                var details=StreamRecord(receipt,stream);Need(!(bool)details["readFailed"]&&!(bool)details["writeFailed"],"capture_failed");
                var file=Directory.GetFiles(Path.Combine(root,"logs"),"*."+stream+".log")[0];
                Need(new FileInfo(file).Length==Convert.ToInt64(details["bytesSaved"]),"receipt_length");
                if(mode=="large") {
                    Need(new FileInfo(file).Length==PilotChild.StreamLimit,"saved_cap");
                    Need(Convert.ToInt64(details["bytesRead"])==393216&&(bool)details["truncated"],"full_pipe_not_drained");
                } else Need(!(bool)details["truncated"],"unexpected_truncation");
            }
            if(mode=="error") {
                var file=Directory.GetFiles(Path.Combine(root,"logs"),"*.stderr.log")[0];
                Need(File.ReadAllText(file)=="fixture pre-server failure", "stderr_not_preserved");
            }
        }
    }
    static void Missing(string root) {
        Directory.CreateDirectory(root);var info=Info("unused");info.FileName=Path.Combine(root,"does-not-exist.exe");
        bool failed=false;try {PilotChild.Start(info,root);}catch(IOException e){failed=e.Message=="local_pilot_launch_failed";}
        Need(failed,"missing_executable_not_refused");var receipt=Record(root);
        Need((string)receipt["status"]=="LAUNCH_FAILED"&&!(bool)receipt["started"]&&receipt["exitCode"]==null,"launch_failure_receipt");
        Need(Convert.ToInt64(StreamRecord(receipt,"stderr")["bytesSaved"])==0,"launch_failure_output");
    }
    static void UnwritableReceipt(string root) {
        using(var child=Child(root,"delayed-error")) {
            var log=Directory.GetFiles(Path.Combine(root,"logs"),"*.stdout.log")[0];
            Directory.CreateDirectory(log.Substring(0,log.Length-".stdout.log".Length)+".json");
            Wait(child);Need(child.ExitCode==19&&!child.ReceiptSaved,"unwritable_receipt_state");
            Need(PilotWindow.ExitMessage(child.ExitCode,child.ReceiptSaved).Contains("could not be saved"),"false_report_claim");
        }
    }
    static void CompletedChildClick(string root) {
        using(var child=Child(root,"success")) {
            Wait(child);
            using(var form=new PilotWindow()) {
                var field=typeof(PilotWindow).GetField("child",BindingFlags.Instance|BindingFlags.NonPublic);
                field.SetValue(form,child);
                typeof(PilotWindow).GetMethod("OpenPilot",BindingFlags.Instance|BindingFlags.NonPublic).Invoke(form,null);
                Need(Object.ReferenceEquals(field.GetValue(form),child),"completed_child_replaced_before_timer");
                Need(!(bool)typeof(PilotWindow).GetField("preparing",BindingFlags.Instance|BindingFlags.NonPublic).GetValue(form),"replacement_setup_started");
                field.SetValue(form,null);
                var preparing=typeof(PilotWindow).GetField("preparing",BindingFlags.Instance|BindingFlags.NonPublic);
                preparing.SetValue(form,true);
                typeof(PilotWindow).GetMethod("OpenPilot",BindingFlags.Instance|BindingFlags.NonPublic).Invoke(form,null);
                Need(field.GetValue(form)==null&&(bool)preparing.GetValue(form),"pending_reopen_replaced_by_setup");
                preparing.SetValue(form,false);
            }
        }
    }
    static int Fixture(string mode) {
        if(mode=="large") {
            var body=new byte[8192];for(int i=0;i<body.Length;i++)body[i]=(byte)'x';
            var stdout=Console.OpenStandardOutput();var stderr=Console.OpenStandardError();
            for(int i=0;i<48;i++){stdout.Write(body,0,body.Length);stderr.Write(body,0,body.Length);}
            stdout.Flush();stderr.Flush();return 0;
        }
        if(mode=="delayed-error"){Thread.Sleep(700);return 19;}
        if(mode=="error"){Console.Error.Write("fixture pre-server failure");return 17;}
        Console.Out.Write("fixture orderly exit");return 0;
    }
    [STAThread]public static int Main(string[] args) {
        AppContext.SetSwitch("Switch.System.IO.UseLegacyPathHandling",false);
        AppContext.SetSwitch("Switch.System.IO.BlockLongPaths",false);
        if(args.Length==2&&args[0]=="fixture")return Fixture(args[1]);
        try {
            var root=args[0];Directory.CreateDirectory(root);
            Finished(Path.Combine(root,"pre-server-error"),"error",17);Console.WriteLine("PASS pre-server nonzero diagnostics");
            Finished(Path.Combine(root,"orderly-exit"),"success",0);Console.WriteLine("PASS orderly zero exit");
            Finished(Path.Combine(root,"large-streams"),"large",0);Console.WriteLine("PASS bounded dual streams drained");
            Missing(Path.Combine(root,"missing-executable"));Console.WriteLine("PASS missing executable receipt");
            UnwritableReceipt(Path.Combine(root,"receipt-refused"));Console.WriteLine("PASS missing report message");
            CompletedChildClick(Path.Combine(root,"completed-click"));Console.WriteLine("PASS completed child click waits for timer");
            return 0;
        } catch(Exception error) {Console.Error.WriteLine(error.GetType().Name+":"+error.Message);return 1;}
    }
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if os.name != 'nt':
        raise SystemExit('Windows is required; no synthetic platform pass is claimed.')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    temp = output / 'temp'
    temp.mkdir()
    env = dict(os.environ, TEMP=str(temp), TMP=str(temp), TMPDIR=str(temp))
    harness = output / 'LaunchChecks.cs'
    harness.write_text(HARNESS, encoding='utf-8')
    executable = output / 'LaunchChecks.exe'
    compiler = Path(os.environ['WINDIR']) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    command = [str(compiler), '/nologo', '/target:exe', '/platform:x64', '/main:LaunchChecks',
        '/out:' + str(executable), '/reference:System.Windows.Forms.dll', '/reference:System.Drawing.dll',
        '/reference:System.Web.Extensions.dll', '/reference:System.IO.Compression.dll',
        '/reference:System.IO.Compression.FileSystem.dll', '/reference:System.Net.Http.dll',
        str(harness), str(REPO / 'packaging/windows/LocalScenes.cs'), str(REPO / 'packaging/windows/Starter.cs')]
    for name, argv, timeout in [('compile', command, 60), ('checks', [str(executable), str(output / 'cases')], 60)]:
        with (output / (name + '.stdout.log')).open('xb') as stdout, (output / (name + '.stderr.log')).open('xb') as stderr:
            result = run_owned(argv, env=env, cwd=REPO, stdout=stdout, stderr=stderr, timeout=timeout)
        if result.returncode:
            raise SystemExit(name + ' failed; original logs retained in the requested private output directory.')
    result = {'status': 'PASS', 'checks': 6, 'actualWindowsChildren': True,
        'boundedBytesPerStream': 65536, 'hiddenChildren': True,
        'nativeInference': False, 'modelDownloads': False, 'providerCalls': False,
        'taskRegistration': False, 'participantAcceptance': False}
    (output / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
