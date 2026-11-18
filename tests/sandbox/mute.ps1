# Mutes the Sandbox's default speakers. Windows Sandbox plays its sound through the host PC, and the test media
# is plain sine tones: without this, whoever is at the PC hears beeps while the suite runs. Tests read mpv's
# state, never the sound, so muting changes nothing they check.
try {
    Add-Type -ErrorAction Stop -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
[ComImport, Guid("5CDF2C82-841E-4546-9722-0CF74078229A"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IAudioEndpointVolume {
    int RegisterControlChangeNotify(IntPtr p); int UnregisterControlChangeNotify(IntPtr p);
    int GetChannelCount(out uint c); int SetMasterVolumeLevel(float l, Guid g);
    int SetMasterVolumeLevelScalar(float l, Guid g); int GetMasterVolumeLevel(out float l);
    int GetMasterVolumeLevelScalar(out float l); int SetChannelVolumeLevel(uint n, float l, Guid g);
    int SetChannelVolumeLevelScalar(uint n, float l, Guid g); int GetChannelVolumeLevel(uint n, out float l);
    int GetChannelVolumeLevelScalar(uint n, out float l); int SetMute([MarshalAs(UnmanagedType.Bool)] bool m, Guid g);
}
[ComImport, Guid("D666063F-1587-4E43-81F1-B948E807363F"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IMMDevice { int Activate(ref Guid id, int ctx, IntPtr p, [MarshalAs(UnmanagedType.IUnknown)] out object o); }
[ComImport, Guid("A95664D2-9614-4F35-A746-DE8DB63617E6"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IMMDeviceEnumerator { int EnumAudioEndpoints(int f, int s, out IntPtr d); int GetDefaultAudioEndpoint(int f, int r, out IMMDevice d); }
[ComImport, Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")] class MMDeviceEnumerator { }
public static class SandboxAudio {
    public static void Mute() {
        var en = (IMMDeviceEnumerator)new MMDeviceEnumerator();
        IMMDevice dev; Marshal.ThrowExceptionForHR(en.GetDefaultAudioEndpoint(0, 1, out dev));
        Guid iid = typeof(IAudioEndpointVolume).GUID; object o;
        Marshal.ThrowExceptionForHR(dev.Activate(ref iid, 23, IntPtr.Zero, out o));
        var v = (IAudioEndpointVolume)o;
        v.SetMasterVolumeLevelScalar(0f, Guid.Empty);
        Marshal.ThrowExceptionForHR(v.SetMute(true, Guid.Empty));
    }
}
'@
    [SandboxAudio]::Mute()
    'muted'
} catch { "mute failed: $_" }
