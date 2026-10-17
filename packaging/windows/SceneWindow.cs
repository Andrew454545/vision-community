// Optional WebView2 view: the Python backend continues to own all processing.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Net.Http;
using System.Text.RegularExpressions;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

sealed class Connection {
    public readonly string Url,Origin,Token;
    public Connection(string raw) {
        var match=Regex.Match(raw,@"\Ahttp://127\.0\.0\.1:([0-9]{1,5})/#([a-f0-9]{64})\z");
        int port;
        if(!match.Success||!Int32.TryParse(match.Groups[1].Value,out port)||port<1||port>65535)throw new IOException("invalid_connection");
        Url=raw;Origin="http://127.0.0.1:"+port;Token=match.Groups[2].Value;
    }
    public bool Local(string raw) {return raw==Origin||raw.StartsWith(Origin+"/",StringComparison.Ordinal)||raw.StartsWith("blob:"+Origin+"/",StringComparison.Ordinal);}
    public static void Plain(string path) {
        for(var p=Path.GetFullPath(path);p!=null;p=Path.GetDirectoryName(p))
            if((File.GetAttributes(p)&FileAttributes.ReparsePoint)!=0)throw new IOException("linked_connection");
    }
    public static Connection Read(string path) {
        Plain(path);if(new FileInfo(path).Length>1024)throw new IOException("invalid_connection");
        var value=new JavaScriptSerializer().Deserialize<Dictionary<string,object>>(File.ReadAllText(path));
        if(value.Count!=2||!value.ContainsKey("version")||!value.ContainsKey("url")||Convert.ToInt32(value["version"])!=1)throw new IOException("invalid_connection");
        return new Connection((string)value["url"]);
    }
}

sealed class SceneWindow:Form {
    readonly Connection connection;
    readonly string profile;
    readonly WebView2 web=new WebView2();
    readonly Timer timer=new Timer {Interval=1000};
    readonly HttpClient http=new HttpClient(new HttpClientHandler {AllowAutoRedirect=false,UseProxy=false,UseCookies=false}) {Timeout=TimeSpan.FromSeconds(2)};
    bool stopping,polling;int failures,lastCounter=-1;
    public int Result=0;
    public SceneWindow(Connection c,string path) {
        connection=c;profile=Path.Combine(Path.GetDirectoryName(path),"webview-profile");Connection.Plain(Path.GetDirectoryName(profile));
        Text="VISION Local Scenes";Width=1100;Height=850;MinimumSize=new System.Drawing.Size(750,650);StartPosition=FormStartPosition.CenterScreen;
        web.Dock=DockStyle.Fill;Controls.Add(web);Shown+=async(s,e)=>await Initialize();
        timer.Tick+=async(s,e)=>await Poll();FormClosing+=Closing;
    }
    async Task Initialize() {
        try {
            web.CreationProperties=new CoreWebView2CreationProperties {UserDataFolder=profile,IsInPrivateModeEnabled=true};
            await web.EnsureCoreWebView2Async(null);
            var core=web.CoreWebView2;
            core.Settings.AreDevToolsEnabled=false;core.Settings.IsStatusBarEnabled=false;
            core.Settings.IsPasswordAutosaveEnabled=false;core.Settings.IsGeneralAutofillEnabled=false;
            core.Settings.AreDefaultContextMenusEnabled=false;
            core.PermissionRequested+=(s,e)=>e.State=CoreWebView2PermissionState.Deny;
            core.NavigationStarting+=(s,e)=>{
                if(!connection.Local(e.Uri)) {e.Cancel=true;if(e.IsUserInitiated)External(e.Uri);}
            };
            core.NewWindowRequested+=(s,e)=>{e.Handled=true;if(e.IsUserInitiated)External(e.Uri);};
            core.DownloadStarting+=(s,e)=>{
                var pending=e.GetDeferral();
                try {
                    if(!connection.Local(e.DownloadOperation.Uri)){e.Cancel=true;return;}
                    using(var dialog=new SaveFileDialog {FileName=Path.GetFileName(e.ResultFilePath),OverwritePrompt=true}) {
                        if(dialog.ShowDialog(this)==DialogResult.OK){e.ResultFilePath=dialog.FileName;e.Handled=true;}else e.Cancel=true;
                    }
                } finally {pending.Complete();}
            };
            core.Navigate(connection.Url);timer.Start();
        } catch {
            // Do not install or update WebView2 automatically. The backend will
            // open its complete browser interface when this optional view fails.
            Result=23;stopping=true;Close();
        }
    }
    static void External(string raw) {
        Uri uri;if(Uri.TryCreate(raw,UriKind.Absolute,out uri)&&uri.Scheme=="https")
            Process.Start(new ProcessStartInfo(uri.AbsoluteUri){UseShellExecute=true});
    }
    async Task<HttpResponseMessage> Request(string path,bool post=false) {
        using(var request=new HttpRequestMessage(post?HttpMethod.Post:HttpMethod.Get,connection.Origin+path)) {
            request.Headers.TryAddWithoutValidation("Authorization","Bearer "+connection.Token);
            if(post){request.Headers.TryAddWithoutValidation("Origin",connection.Origin);request.Content=new ByteArrayContent(new byte[0]);}
            return await http.SendAsync(request);
        }
    }
    async Task Poll() {
        if(polling||stopping)return;polling=true;
        try {
            using(var response=await Request("/api/window")) {
                response.EnsureSuccessStatusCode();
                if(response.Content.Headers.ContentLength>4096)throw new IOException("response_limit");
                var raw=await response.Content.ReadAsStringAsync();if(raw.Length>4096)throw new IOException("response_limit");
                var value=new JavaScriptSerializer().Deserialize<Dictionary<string,object>>(raw);
                int counter=Convert.ToInt32(value["showCounter"]);failures=0;
                if(counter!=lastCounter){lastCounter=counter;if(WindowState==FormWindowState.Minimized)WindowState=FormWindowState.Normal;Show();Activate();}
            }
        } catch {failures++;if(failures>=3){stopping=true;Close();}}
        finally {polling=false;}
    }
    async void Closing(object sender,FormClosingEventArgs e) {
        if(stopping){timer.Stop();return;}
        e.Cancel=true;
        if(MessageBox.Show(this,"Pause processing and close VISION? Your saved work is kept. The current group may take a few minutes to stop.","Close VISION",MessageBoxButtons.OKCancel)!=DialogResult.OK)return;
        stopping=true;timer.Stop();
        try {using(var response=await Request("/api/exit",true)) {}}catch {}
        Close();
    }
    protected override void Dispose(bool disposing) {if(disposing){timer.Dispose();http.Dispose();}base.Dispose(disposing);}
}

static class Program {
    [STAThread]static int Main(string[] args) {
        try {
            if(args.Length==1&&args[0]=="--self-check") {
                new Connection("http://127.0.0.1:1234/#"+new string('a',64));
                foreach(var prefix in new[]{"https://127.0.0.1:1234/#","http://localhost:1234/#","http://127.0.0.1:0/#","http://127.0.0.1:1234.evil/#"}) {
                    bool rejected=false;try{new Connection(prefix+new string('a',64));}catch(IOException){rejected=true;}if(!rejected)return 2;
                }
                Console.WriteLine("LOCAL_NATIVE_WINDOW_BOUNDARY_VERIFIED");return 0;
            }
            if(args.Length!=2||args[0]!="--connection")return 2;
            var connection=Connection.Read(args[1]);
            Application.EnableVisualStyles();Application.SetCompatibleTextRenderingDefault(false);
            using(var window=new SceneWindow(connection,args[1])) {Application.Run(window);return window.Result;}
        } catch {return 23;}
    }
}
