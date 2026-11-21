<#
.SYNOPSIS
  Checks that every DLL the bundled programs import is shipped with PKOS or is part of Windows itself.

.DESCRIPTION
  Reads the import and delay-import tables of every .exe/.dll/.pyd/.node under the app folder (no Visual Studio
  needed). A dependency is OK when a file with that name is inside the same component (pgsql, ollama, pkos-api,
  the Electron root), or when it is an API set (api-ms-*/ext-ms-*) or a system DLL that exists on a clean Windows
  install. Dependencies that only resolve from System32 because some other installer put them there (the Visual C++
  runtime, for example) are reported as failures: they would be missing on a clean PC.
  GPU driver DLLs (nvcuda, nvml, vulkan-1, OpenCL) are reported separately: the driver provides them, and Ollama
  falls back to the CPU without them.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File packaging\audit-dlls.ps1 -AppDir build\installer\win-unpacked
#>
param([Parameter(Mandatory = $true)][string]$AppDir)
$ErrorActionPreference = "Stop"

Add-Type -TypeDefinition @"
using System; using System.Collections.Generic; using System.IO; using System.Text;
public static class PeImports {
  static uint Rva2Off(uint rva, List<uint[]> secs) {
    foreach (var s in secs) if (rva >= s[0] && rva < s[0] + Math.Max(s[1], s[3])) return rva - s[0] + s[2];
    return 0;
  }
  static string Str(byte[] b, uint off) { int e = (int)off; while (e < b.Length && b[e] != 0) e++; return Encoding.ASCII.GetString(b, (int)off, e - (int)off); }
  public static string[] Read(string path) {
    var result = new List<string>();
    byte[] b = File.ReadAllBytes(path);
    if (b.Length < 64 || b[0] != 'M' || b[1] != 'Z') return result.ToArray();
    int pe = BitConverter.ToInt32(b, 0x3C);
    if (pe <= 0 || pe + 24 > b.Length || BitConverter.ToUInt32(b, pe) != 0x4550) return result.ToArray();
    int nsec = BitConverter.ToUInt16(b, pe + 6), optSize = BitConverter.ToUInt16(b, pe + 20), opt = pe + 24;
    bool pe32plus = BitConverter.ToUInt16(b, opt) == 0x20B;
    int dirs = opt + (pe32plus ? 112 : 96);
    var secs = new List<uint[]>();
    int sh = opt + optSize;
    for (int i = 0; i < nsec; i++) {
      int o = sh + i * 40;
      secs.Add(new uint[] { BitConverter.ToUInt32(b, o + 12), BitConverter.ToUInt32(b, o + 8), BitConverter.ToUInt32(b, o + 20), BitConverter.ToUInt32(b, o + 16) });
    }
    foreach (int dir in new[] { 1, 13 }) {          // import table, delay-import table
      uint rva = BitConverter.ToUInt32(b, dirs + dir * 8);
      if (rva == 0) continue;
      uint off = Rva2Off(rva, secs);
      int stride = dir == 1 ? 20 : 32, nameAt = dir == 1 ? 12 : 4;
      for (int k = 0; off != 0 && off + stride <= b.Length; k++, off += (uint)stride) {
        uint nameRva = BitConverter.ToUInt32(b, (int)off + nameAt);
        if (nameRva == 0) break;
        uint no = Rva2Off(nameRva, secs);
        if (no != 0) result.Add(Str(b, no));
      }
    }
    return result.ToArray();
  }
}
"@

# Visual C++ / UCRT redistributables and other DLLs that a clean Windows does not have, even if this PC does.
$notOnCleanWindows = @('vcruntime140.dll', 'vcruntime140_1.dll', 'vcruntime140_threads.dll', 'msvcp140.dll', 'msvcp140_1.dll',
  'msvcp140_2.dll', 'msvcp140_atomic_wait.dll', 'msvcp140_codecvt_ids.dll', 'concrt140.dll', 'vcomp140.dll', 'vccorlib140.dll',
  'msvcr100.dll', 'msvcr110.dll', 'msvcr120.dll', 'msvcp100.dll', 'msvcp110.dll', 'msvcp120.dll', 'libiomp5md.dll')
$gpuDriver = @('nvcuda.dll', 'nvml.dll', 'vulkan-1.dll', 'opencl.dll', 'nvrtc64_120_0.dll', 'amdhip64.dll', 'amdhip64_6.dll')

$root = (Resolve-Path $AppDir).Path
$resources = Join-Path $root "resources"
$components = @(Get-ChildItem $resources -Directory | Where-Object Name -in 'pgsql', 'ollama', 'pkos-api' | ForEach-Object FullName)
$components += $root  # Electron itself (top-level files only)

$sys32 = Join-Path $env:WINDIR "System32"
$problems = New-Object System.Collections.Generic.List[string]
$gpu = New-Object System.Collections.Generic.HashSet[string]
$checked = 0

foreach ($comp in $components) {
  $isElectron = $comp -eq $root
  $files = if ($isElectron) { Get-ChildItem $comp -File } else { Get-ChildItem $comp -Recurse -File }
  $binaries = $files | Where-Object { $_.Extension -in '.exe', '.dll', '.pyd', '.node' }
  $available = New-Object System.Collections.Generic.HashSet[string]
  foreach ($f in $files) { [void]$available.Add($f.Name.ToLowerInvariant()) }
  foreach ($bin in $binaries) {
    $checked++
    try { $deps = [PeImports]::Read($bin.FullName) } catch { $problems.Add("cannot read $($bin.FullName): $_"); continue }
    foreach ($dep in $deps) {
      $d = $dep.ToLowerInvariant()
      if ($available.Contains($d)) { continue }
      if ($d -like 'api-ms-*' -or $d -like 'ext-ms-*') { continue }
      if ($gpuDriver -contains $d) { [void]$gpu.Add($d); continue }
      $inSystem = Test-Path (Join-Path $sys32 $dep)
      if ($inSystem -and ($notOnCleanWindows -notcontains $d)) { continue }
      $rel = $bin.FullName.Substring($root.Length + 1)
      $why = if ($inSystem) { "only in System32 here (not on a clean Windows)" } else { "not found" }
      $problems.Add("$rel -> $dep ($why)")
    }
  }
}

Write-Host "Checked $checked binaries in $($components.Count) components."
if ($gpu.Count) { Write-Host "Provided by the GPU driver when present (optional): $((@($gpu) | Sort-Object) -join ', ')" }
$unique = $problems | Sort-Object -Unique
if ($unique) {
  Write-Host "Missing on a clean PC:" -ForegroundColor Red
  $unique | ForEach-Object { Write-Host "  $_" }
  exit 1
}
Write-Host "OK: every dependency is bundled or part of Windows." -ForegroundColor Green
