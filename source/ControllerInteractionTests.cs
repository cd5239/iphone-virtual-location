using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using System.Windows.Threading;

partial class Controller {
 internal void ValidateWifiButton(List<Dictionary<string,object>> requests){
  Action<bool,string> check=(ok,message)=>{if(!ok)throw new Exception(message);};
  Action click=()=>wifiDetect.RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
  Action<Dictionary<string,object>> complete=request=>Receive(json.Serialize(new Dictionary<string,object>{
   {"event","device"},{"request_id",request["request_id"]},{"command","probe"},{"message","synthetic phone"},
   {"transport","Network"},{"connection","connected"},{"usable",true},{"active",false}}));
  connectionMode.SelectedIndex=0;wifiHost.Text="192.0.2.15";
  click();
  check(requests.Count==1&&Mode=="Network","USB detect must switch to Wi-Fi and send exactly one probe");
  check(Convert.ToString(requests[0]["wifi_host"])=="192.0.2.15","Detect must use current IP");
  check(Convert.ToString(requests[0]["mode"])=="Network"&&Convert.ToString(requests[0]["command"])=="probe","Detect cannot send a location command");
  complete(requests[0]);
  wifiHost.RaiseEvent(new RoutedEventArgs(UIElement.LostFocusEvent));
  check(requests.Count==1,"Leaving IP field must not race the explicit detect click");
  click();check(requests.Count==2,"Same mode and IP must allow another detection");
  wifiHost.Text="192.0.2.16";click();
  check(requests.Count==2,"Pending probe must be serialized");
  complete(requests[1]);
  check(requests.Count==3&&Convert.ToString(requests[2]["wifi_host"])=="192.0.2.16","Queued detection must use the latest IP");
  complete(requests[2]);wifiHost.Text="";click();
  check(requests.Count==4&&Convert.ToString(requests[3]["wifi_host"])=="","Blank IP must retain automatic discovery");
  complete(requests[3]);state.Active=true;Render();click();
  check(!wifiDetect.IsEnabled&&requests.Count==4,"Detect cannot interrupt active location");
  state.Active=false;state.Begin("apply",999);Render();click();
  check(!wifiDetect.IsEnabled&&requests.Count==4,"Detect cannot interrupt a foreground command");
 }
 internal void DisposeTestResources(){
  exiting=true;timer.Stop();toast.Close();applyWait.Unregister(null);showWait.Unregister(null);
  applySignal.Dispose();showSignal.Dispose();tray.Visible=false;tray.Dispose();Window.Close();
 }
}

static class ControllerInteractionTests {
 static void SimulateInputFlag(Button button,Type owner,string name){
  var field=owner.GetField(name,BindingFlags.Public|BindingFlags.NonPublic|BindingFlags.Static);
  if(field==null)throw new Exception("Missing test input key: "+name);
  button.SetValue((DependencyPropertyKey)field.GetValue(null),true);
 }
 public static void Run(string directory){
  Directory.CreateDirectory(directory);
  var requests=new List<Dictionary<string,object>>();
  var controller=new Controller(false,request=>requests.Add(request));
  try{controller.ValidateWifiButton(requests);}finally{controller.DisposeTestResources();}
  var window=App.Load();var style=(Style)window.Resources["PrimaryAction"];
  foreach(string state in new[]{"Normal","MouseOver","Pressed","Disabled"}){
   var button=new Button{Style=style,Content="修改定位",FontSize=17,FontWeight=FontWeights.SemiBold,
                         Padding=new Thickness(14),Margin=new Thickness(0),Width=320,Height=54};
   button.Measure(new Size(320,54));button.Arrange(new Rect(0,0,320,54));button.ApplyTemplate();button.UpdateLayout();
   if(state=="MouseOver"||state=="Pressed")SimulateInputFlag(button,typeof(UIElement),"IsMouseOverPropertyKey");
   if(state=="Pressed")SimulateInputFlag(button,typeof(ButtonBase),"IsPressedPropertyKey");
   if(state=="Disabled")button.IsEnabled=false;
   button.UpdateLayout();
   var chrome=(Border)button.Template.FindName("Chrome",button);
   string expected=state=="Normal"?"#2563EB":state=="MouseOver"?"#1D4ED8":state=="Pressed"?"#1E40AF":"#CBD5E1";
   if(((SolidColorBrush)chrome.Background).Color!=(Color)ColorConverter.ConvertFromString(expected))throw new Exception("Incorrect button color: "+state+" actual="+((SolidColorBrush)chrome.Background).Color);
   var bitmap=new RenderTargetBitmap(480,81,144,144,PixelFormats.Pbgra32);bitmap.Render(button);
   var png=new PngBitmapEncoder();png.Frames.Add(BitmapFrame.Create(bitmap));
   using(var file=File.Create(Path.Combine(directory,"apply-"+state+".png")))png.Save(file);
  }
  File.WriteAllText(Path.Combine(directory,"result.txt"),"PASS: USB-to-Wi-Fi detection, repeated click, pending serialization, latest/blank IP, active/busy guards; normal/hover/pressed/disabled button colors.");
 }
}
