# Render the small, code-native SVG palette into a multi-size Windows icon.
# Only rectangles and polygons are supported; no external assets or fonts.
[CmdletBinding()]
param(
    [string]$SourceSvg = (Join-Path $PSScriptRoot '..\outputs\formfiller\web_static\formfiller.svg'),
    [Parameter(Mandatory = $true)][string]$DestinationIco,
    [string]$PreviewPng
)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
$document = [Xml.XmlDocument]::new()
$document.XmlResolver = $null
$document.Load((Resolve-Path -LiteralPath $SourceSvg).Path)
$images = @()
foreach ($size in @(16, 24, 32, 48, 64, 128, 256)) {
    $bitmap = [Drawing.Bitmap]::new($size, $size)
    $graphics = [Drawing.Graphics]::FromImage($bitmap)
    $stream = [IO.MemoryStream]::new()
    try {
        $graphics.Clear([Drawing.Color]::Transparent)
        $graphics.ScaleTransform(($size / 64.0), ($size / 64.0))
        foreach ($element in $document.DocumentElement.ChildNodes) {
            if ($element.LocalName -eq 'title') { continue }
            $brush = [Drawing.SolidBrush]::new([Drawing.ColorTranslator]::FromHtml($element.GetAttribute('fill')))
            try {
                if ($element.LocalName -eq 'rect') {
                    $graphics.FillRectangle($brush, [single]$element.GetAttribute('x'), [single]$element.GetAttribute('y'),
                        [single]$element.GetAttribute('width'), [single]$element.GetAttribute('height'))
                } elseif ($element.LocalName -eq 'polygon') {
                    $points = @($element.GetAttribute('points').Split(' ', [StringSplitOptions]::RemoveEmptyEntries) | ForEach-Object {
                        $coordinates = $_.Split(',')
                        [Drawing.PointF]::new([single]$coordinates[0], [single]$coordinates[1])
                    })
                    $graphics.FillPolygon($brush, [Drawing.PointF[]]$points)
                } else { throw 'icon_element_unsupported' }
            } finally { $brush.Dispose() }
        }
        $bitmap.Save($stream, [Drawing.Imaging.ImageFormat]::Png)
        $images += @{ Size = $size; Bytes = $stream.ToArray() }
        if ($size -eq 256 -and $PreviewPng) {
            [IO.File]::WriteAllBytes([IO.Path]::GetFullPath($PreviewPng), $stream.ToArray())
        }
    } finally { $graphics.Dispose(); $bitmap.Dispose(); $stream.Dispose() }
}
$output = [IO.MemoryStream]::new()
$writer = [IO.BinaryWriter]::new($output)
try {
    $writer.Write([uint16]0)
    $writer.Write([uint16]1)
    $writer.Write([uint16]$images.Count)
    $offset = 6 + 16 * $images.Count
    foreach ($entry in $images) {
        $dimension = if ($entry.Size -eq 256) { 0 } else { $entry.Size }
        $writer.Write([byte]$dimension); $writer.Write([byte]$dimension)
        $writer.Write([byte]0); $writer.Write([byte]0)
        $writer.Write([uint16]1); $writer.Write([uint16]32)
        $writer.Write([uint32]$entry.Bytes.Length); $writer.Write([uint32]$offset)
        $offset += $entry.Bytes.Length
    }
    foreach ($entry in $images) { $writer.Write([byte[]]$entry.Bytes) }
    $writer.Flush()
    [IO.File]::WriteAllBytes([IO.Path]::GetFullPath($DestinationIco), $output.ToArray())
} finally { $writer.Dispose(); $output.Dispose() }
