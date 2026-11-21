# Read-only: calls the ASUS WMI DSTS (get) method for a fixed list of side-effect-free IDs.
param([string]$Label = "read")
$ids = @(0x001200D2,0x001200D3,0x001200D4,0x00060094,0x00130021,0x00120061,0x00110013,0x00110014,0x00090031,0x00090033,0x00090034,0x0012005A,0x0012005B,0x0012006C,0x0012006D,0x0012006F,0x0012007E,0x00120094,0x001200E2,0x001200F2,0x00130024,0x00130026,0x00130031,0x00130022,0x00120057)
$inst = Get-CimInstance -Namespace root/wmi -ClassName AsusAtkWmi_WMNB | Select-Object -First 1
$m = (Get-CimClass -Namespace root/wmi -ClassName AsusAtkWmi_WMNB).CimClassMethods['DSTS']
$inName = ($m.Parameters | Where-Object { $_.Qualifiers.Name -contains 'In' } | Select-Object -First 1).Name
$outName = ($m.Parameters | Where-Object { $_.Qualifiers.Name -contains 'Out' } | Select-Object -First 1).Name
"# $Label $(Get-Date -Format s) in=$inName out=$outName"
foreach ($id in $ids) {
  try {
    $r = Invoke-CimMethod -InputObject $inst -MethodName DSTS -Arguments @{ $inName = [uint32]$id }
    "{0:X8} {1:X8}" -f $id, [uint32]$r.$outName
  } catch { "{0:X8} ERR {1}" -f $id, $_.Exception.Message }
}
