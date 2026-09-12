using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Security.Cryptography;
using System.Runtime.InteropServices;
using System.Windows.Forms;
[assembly: System.Reflection.AssemblyVersion("1.3.0.0")]
[assembly: System.Reflection.AssemblyFileVersion("1.3.0.0")]
[assembly: System.Reflection.AssemblyTitle("拾光工坊") ]
[assembly: System.Reflection.AssemblyProduct("拾光工坊·模组编辑器-beta-1.3.0") ]
[assembly: System.Reflection.AssemblyInformationalVersion("beta-1.3.1") ]
class Launcher {
 [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
 static extern bool DeleteFile(string path);
 [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
 static extern Microsoft.Win32.SafeHandles.SafeFileHandle CreateFile(string path,uint access,uint sharing,IntPtr security,uint disposition,uint flags,IntPtr template);
 static void PrepareRuntime(string root) {
  // Manifest is compiled into this launcher, not read from a mutable sidecar.
  using(var stream=Assembly.GetExecutingAssembly().GetManifestResourceStream("runtime-sha256.txt")) {
   if(stream==null) throw new IOException("安装文件缺少运行库校验清单，请重新完整解压官方安装包。");
   using(var reader=new StreamReader(stream)) {
    string line;
    while((line=reader.ReadLine())!=null) {
     int split=line.IndexOf("  ",StringComparison.Ordinal);
     if(split!=64) throw new IOException("运行库校验清单格式错误。");
     string relative=line.Substring(66), path=Path.GetFullPath(Path.Combine(root,relative));
     if(!path.StartsWith(Path.Combine(root,"runtime")+Path.DirectorySeparatorChar,StringComparison.OrdinalIgnoreCase) || !path.EndsWith(".dll",StringComparison.OrdinalIgnoreCase)) throw new IOException("运行库清单路径错误。");
     string mark=path+":Zone.Identifier";
     using(var handle=CreateFile(mark,0x80000000,3,IntPtr.Zero,3,0,IntPtr.Zero)) {
      if(handle.IsInvalid) {int code=Marshal.GetLastWin32Error();if(code==2||code==3)continue;throw new IOException("无法读取运行库下载标记："+relative);}
     }
     string actual;
     using(var file=File.OpenRead(path)) using(var sha=SHA256.Create()) actual=BitConverter.ToString(sha.ComputeHash(file)).Replace("-","").ToLowerInvariant();
     if(!String.Equals(actual,line.Substring(0,64),StringComparison.OrdinalIgnoreCase)) throw new IOException("运行库校验失败："+relative+"。请重新解压官方安装包。");
     if(!DeleteFile(mark)) throw new IOException("无法解除此安装包运行库的下载限制。请先在原始 ZIP 的属性中解除锁定，再重新解压。");
    }
   }
  }
 }
 [STAThread] static void Main() {
  try {
   string root=AppDomain.CurrentDomain.BaseDirectory;
   PrepareRuntime(root);
   while (true) {
    var start = new ProcessStartInfo(Path.Combine(root,"runtime","StudioEngine.exe")) {WorkingDirectory=root,UseShellExecute=false,CreateNoWindow=true};
    start.EnvironmentVariables["STUDIO_UPDATE_MANAGED"]="1";
    using (var process=Process.Start(start)) { process.WaitForExit(); if(process.ExitCode!=42) break; }
   }
  } catch(Exception e) {MessageBox.Show("无法打开工作台，请完整解压安装包后重试。\n"+e.Message,"拾光工坊·模组编辑器-beta-1.3.0");}
 }
}
