using System;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;
[assembly: System.Reflection.AssemblyVersion("1.3.0.0")]
[assembly: System.Reflection.AssemblyFileVersion("1.3.0.0")]
[assembly: System.Reflection.AssemblyTitle("拾光工坊") ]
[assembly: System.Reflection.AssemblyProduct("拾光工坊·模组编辑器-beta-1.3.0") ]
[assembly: System.Reflection.AssemblyInformationalVersion("1.3.0-beta.1") ]
class Launcher {
 [STAThread] static void Main() {
  try {
   string root=AppDomain.CurrentDomain.BaseDirectory;
   while (true) {
    var start = new ProcessStartInfo(Path.Combine(root,"runtime","StudioEngine.exe")) {WorkingDirectory=root,UseShellExecute=false,CreateNoWindow=true};
    start.EnvironmentVariables["STUDIO_UPDATE_MANAGED"]="1";
    using (var process=Process.Start(start)) { process.WaitForExit(); if(process.ExitCode!=42) break; }
   }
  } catch(Exception e) {MessageBox.Show("无法打开工作台，请完整解压安装包后重试。\n"+e.Message,"拾光工坊·模组编辑器-beta-1.3.0");}
 }
}
