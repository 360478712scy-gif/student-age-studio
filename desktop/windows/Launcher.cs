using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Reflection;
using System.Security.Cryptography;
using System.Runtime.InteropServices;
using System.Text;
using System.Web.Script.Serialization;
using System.Windows.Forms;
[assembly: AssemblyVersion("1.3.0.0")]
[assembly: AssemblyFileVersion("1.3.0.0")]
[assembly: AssemblyTitle("拾光工坊")]
[assembly: AssemblyProduct("拾光工坊·模组编辑器")]
class Launcher {
 const string DownloadUrl="https://github.com/360478712scy-gif/student-age-studio/releases/latest";
 const string NetfxUrl="https://dotnet.microsoft.com/download/dotnet-framework/net48";
 const string WebviewUrl="https://developer.microsoft.com/microsoft-edge/webview2/";
 [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
 static extern bool DeleteFile(string path);
 [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
 static extern Microsoft.Win32.SafeHandles.SafeFileHandle CreateFile(string path,uint access,uint sharing,IntPtr security,uint disposition,uint flags,IntPtr template);
 class RuntimeCheck {
  public string Code="package_ok", Summary="安装包运行库校验通过。";
  public List<string> Marked=new List<string>();
 }
 static string QuoteArg(string value) {
  var result=new StringBuilder("\"");int slashes=0;
  foreach(char c in value) {
   if(c=='\\'){slashes++;continue;}
   if(c=='"'){result.Append('\\',slashes*2+1);result.Append(c);}
   else{result.Append('\\',slashes);result.Append(c);}
   slashes=0;
  }
  result.Append('\\',slashes*2);return result.Append('"').ToString();
 }
 static string Arguments(string[] args) {
  var values=new List<string>();foreach(string arg in args)values.Add(QuoteArg(arg));return String.Join(" ",values.ToArray());
 }
 static bool HasDownloadMark(string path) {
  using(var handle=CreateFile(path+":Zone.Identifier",0x80000000,3,IntPtr.Zero,3,0,IntPtr.Zero)) {
   if(!handle.IsInvalid)return true;
   int code=Marshal.GetLastWin32Error();
   if(code==2||code==3)return false;
   throw new IOException("无法读取运行库下载标记："+path+"，Windows 错误 "+code);
  }
 }
 static RuntimeCheck InspectRuntime(string root) {
  var check=new RuntimeCheck();
  try {
   string runtime=Path.GetFullPath(Path.Combine(root,"runtime"))+Path.DirectorySeparatorChar;
   using(var stream=Assembly.GetExecutingAssembly().GetManifestResourceStream("runtime-sha256.txt")) {
    if(stream==null)throw new IOException("安装文件缺少运行库校验清单。");
    using(var reader=new StreamReader(stream)) {
     string line;int count=0;
     while((line=reader.ReadLine())!=null) {
      int split=line.IndexOf("  ",StringComparison.Ordinal);
      if(split!=64)throw new IOException("运行库校验清单格式错误。");
      string relative=line.Substring(66),path=Path.GetFullPath(Path.Combine(root,relative));
      if(!path.StartsWith(runtime,StringComparison.OrdinalIgnoreCase)||!path.EndsWith(".dll",StringComparison.OrdinalIgnoreCase))throw new IOException("运行库清单路径错误。");
      if(!File.Exists(path)){check.Code="package_missing";check.Summary="安装包缺少运行库文件："+relative;return check;}
      for(var parent=new DirectoryInfo(Path.GetDirectoryName(path));parent!=null&&parent.FullName.StartsWith(runtime.TrimEnd(Path.DirectorySeparatorChar),StringComparison.OrdinalIgnoreCase);parent=parent.Parent)
       if((parent.Attributes&FileAttributes.ReparsePoint)!=0)throw new IOException("运行库目录是重定向目录，不能自动解除下载限制。");
      if((File.GetAttributes(path)&FileAttributes.ReparsePoint)!=0)throw new IOException("运行库文件是链接，不能自动解除下载限制。");
      string actual;
      using(var file=File.OpenRead(path))using(var sha=SHA256.Create())actual=BitConverter.ToString(sha.ComputeHash(file)).Replace("-","").ToLowerInvariant();
      if(!String.Equals(actual,line.Substring(0,64),StringComparison.OrdinalIgnoreCase)){check.Code="package_changed";check.Summary="运行库文件与官方安装包不一致："+relative;return check;}
      if(HasDownloadMark(path))check.Marked.Add(path);
      count++;
     }
     if(count==0)throw new IOException("运行库校验清单为空。");
    }
   }
   if(!File.Exists(Path.Combine(root,"runtime","StudioEngine.exe"))){check.Code="package_missing";check.Summary="安装包缺少 runtime\\StudioEngine.exe。";}
  }catch(Exception error){check.Code="package_unreadable";check.Summary="无法完成本安装包校验："+error.Message;}
  return check;
 }
 // Explicit repair after failure; never called on a normal startup.
 static void PrepareRuntime(string root) {
  var check=InspectRuntime(root);
  if(check.Code!="package_ok")throw new IOException(check.Summary);
  foreach(string path in check.Marked)
   if(!DeleteFile(path+":Zone.Identifier"))throw new IOException("无法解除本包下载限制："+path+"。请在原始 ZIP 属性中解除锁定，再完整解压到新目录。");
 }
 static string Text(Dictionary<string,object> report,string key,string fallback) {
  object value;return report.TryGetValue(key,out value)&&value!=null?Convert.ToString(value):fallback;
 }
 static void Open(string target) {
  try{Process.Start(new ProcessStartInfo(target){UseShellExecute=true});}
  catch(Exception error){MessageBox.Show("无法打开：\n"+target+"\n"+error.Message,"拾光工坊启动诊断",MessageBoxButtons.OK,MessageBoxIcon.Warning);}
 }
 static string SaveLog(Exception error) {
  try {
   string directory=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"StudentAgeStudio","Diagnostics");Directory.CreateDirectory(directory);
   string path=Path.Combine(directory,"startup-"+DateTime.UtcNow.ToString("yyyyMMddTHHmmssfff")+"-"+Guid.NewGuid().ToString("N")+".log");
   File.WriteAllText(path,error.ToString(),new UTF8Encoding(false));return path;
  }catch{return "";}
 }
 static Dictionary<string,object> ReadReport(string path) {
  if(File.Exists(path)&&new FileInfo(path).Length<=262144)
   try{return new JavaScriptSerializer().Deserialize<Dictionary<string,object>>(File.ReadAllText(path,Encoding.UTF8));}catch{}
  return new Dictionary<string,object>();
 }
 static bool ShowFailure(string root,Dictionary<string,object> report) {
  var check=InspectRuntime(root);
  string code=Text(report,"code","startup_unknown"),summary=Text(report,"summary","引擎启动失败，请查看详细日志。");
  if(check.Code!="package_ok"){code=check.Code;summary=check.Summary;}
  else if(check.Marked.Count>0&&code!="netfx_missing"&&code!="netfx_too_old"&&code!="webview_missing"){code="download_marked";summary="已校验的运行库带有 Windows 下载限制标记，可解除本包标记后重试。";}
  string log=Text(report,"logPath",""),details=Text(report,"details","");
  string instructions=code.StartsWith("package_")?"请重新完整解压官方 ZIP 到新目录，再运行顶层“拾光工坊.exe”。不要覆盖或删除自己的 Mod 和草稿。":
   code=="download_marked"?"解除下载限制只处理本安装包中已通过校验的运行库文件，不修改系统组件或个人数据。":
   (code=="netfx_missing"||code=="netfx_too_old")?"检查结果显示 .NET Framework 缺失或版本不足，可打开微软官方安装页面。":
   code=="webview_missing"?"检查结果显示 WebView2 Runtime 不可用，可打开微软官方安装页面。":
   "此错误尚不能唯一确定原因。请从完整安装包的顶层启动器重试，并保留日志供排查。";
  bool retry=false;
  using(var form=new Form()) {
   form.Text="拾光工坊 · 启动诊断";form.StartPosition=FormStartPosition.CenterScreen;form.ClientSize=new Size(740,500);form.MinimumSize=new Size(680,500);form.Font=new Font("Microsoft YaHei UI",9F);form.AutoScaleMode=AutoScaleMode.Dpi;
   var title=new Label{Text=summary,Location=new Point(18,18),Size=new Size(704,64),Font=new Font(form.Font,FontStyle.Bold),Anchor=AnchorStyles.Top|AnchorStyles.Left|AnchorStyles.Right};form.Controls.Add(title);
   var hint=new Label{Text=instructions,Location=new Point(18,84),Size=new Size(704,68),Anchor=AnchorStyles.Top|AnchorStyles.Left|AnchorStyles.Right};form.Controls.Add(hint);
   var body=new TextBox{Multiline=true,ReadOnly=true,ScrollBars=ScrollBars.Both,WordWrap=false,Location=new Point(18,155),Size=new Size(704,240),Text="诊断分类："+code+"\r\n详细日志："+(log.Length>0?log:"日志写入失败")+"\r\n\r\n"+details,Anchor=AnchorStyles.Top|AnchorStyles.Bottom|AnchorStyles.Left|AnchorStyles.Right};form.Controls.Add(body);
   var buttons=new FlowLayoutPanel{Location=new Point(18,408),Size=new Size(704,74),Anchor=AnchorStyles.Bottom|AnchorStyles.Left|AnchorStyles.Right,WrapContents=true};form.Controls.Add(buttons);
   Action<string,Action> add=(text,action)=>{var button=new Button{Text=text,AutoSize=true,MinimumSize=new Size(110,30)};button.Click+=(sender,eventArgs)=>action();buttons.Controls.Add(button);};
   if(code=="download_marked")add("解除本包下载限制",()=>{try{PrepareRuntime(root);hint.Text="本包下载限制已解除。请点击“重试启动”。";}catch(Exception error){hint.Text=error.Message;}});
   if(code=="netfx_missing"||code=="netfx_too_old")add("微软 .NET 安装页面",()=>Open(NetfxUrl));
   if(code=="webview_missing")add("微软 WebView2 安装页面",()=>Open(WebviewUrl));
   add("下载官方完整包",()=>Open(DownloadUrl));if(File.Exists(log))add("打开日志",()=>Open(log));
   add("复制诊断",()=>{try{Clipboard.SetText(summary+"\r\n"+instructions+"\r\n"+body.Text);}catch(Exception error){hint.Text=error.Message;}});
   add("重试启动",()=>{retry=true;form.Close();});add("关闭",()=>form.Close());form.ShowDialog();
  }
  return retry;
 }
 [STAThread] static void Main(string[] args) {
  string root=AppDomain.CurrentDomain.BaseDirectory;
  if(args.Length==2&&args[0]=="--startup-error"){
   if(ShowFailure(root,ReadReport(args[1])))Process.Start(new ProcessStartInfo(Assembly.GetExecutingAssembly().Location){WorkingDirectory=root,UseShellExecute=false});
   return;
  }
  bool diagnosticsOnly=Array.IndexOf(args,"--diagnose-runtime")>=0||Array.IndexOf(args,"--server-only")>=0||Array.IndexOf(args,"--extract")>=0;
  while(true) {
   string reportPath=Path.Combine(Path.GetTempPath(),"StudioStartup-"+Guid.NewGuid().ToString("N")+".json"),readyPath=reportPath+".ready";bool retry=false;
   try {
    // Successful starts do not probe dependencies, hash files, repair marks, or show dialogs.
    var start=new ProcessStartInfo(Path.Combine(root,"runtime","StudioEngine.exe")){Arguments=Arguments(args),WorkingDirectory=root,UseShellExecute=false,CreateNoWindow=true};
    start.EnvironmentVariables["STUDIO_UPDATE_MANAGED"]="1";start.EnvironmentVariables["STUDIO_STARTUP_REPORT"]=reportPath;start.EnvironmentVariables["STUDIO_STARTUP_READY"]=readyPath;
    using(var process=Process.Start(start)) {
     process.WaitForExit();
     if(diagnosticsOnly){Environment.ExitCode=process.ExitCode;return;}
     if(process.ExitCode==42)continue;
     if(process.ExitCode!=0&&!File.Exists(readyPath)){
      var report=ReadReport(reportPath);
      if(report.Count==0){var error=new IOException("StudioEngine 启动退出，代码："+process.ExitCode);report["details"]=error.ToString();report["logPath"]=SaveLog(error);}
      retry=ShowFailure(root,report);
     }
    }
   }catch(Exception error){
    if(diagnosticsOnly){Console.Error.WriteLine(error);Environment.ExitCode=11;return;}
    var report=new Dictionary<string,object>{{"details",error.ToString()},{"logPath",SaveLog(error)}};retry=ShowFailure(root,report);
   }
   finally{try{if(File.Exists(reportPath))File.Delete(reportPath);if(File.Exists(readyPath))File.Delete(readyPath);}catch{}}
   if(!retry)break;
  }
 }
}
