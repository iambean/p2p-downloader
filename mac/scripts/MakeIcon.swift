import AppKit

let image = NSImage(size: NSSize(width: 1024, height: 1024))
image.lockFocus()
let rect = NSRect(x: 88, y: 88, width: 848, height: 848)
let background = NSBezierPath(roundedRect: rect, xRadius: 190, yRadius: 190)
NSColor(srgbRed: 0.153, green: 0.129, blue: 0.173, alpha: 1).setFill()
background.fill()
let glyph = "M" as NSString
let font = NSFont(name: "Baskerville-BoldItalic", size: 640) ?? NSFont.systemFont(ofSize: 640, weight: .semibold)
let attributes: [NSAttributedString.Key: Any] = [.font: font, .foregroundColor: NSColor(srgbRed: 0.945, green: 0.631, blue: 0.533, alpha: 1)]
let size = glyph.size(withAttributes: attributes)
glyph.draw(at: NSPoint(x: (1024 - size.width) / 2 - 12, y: (1024 - size.height) / 2 + 8), withAttributes: attributes)
image.unlockFocus()
let bitmap = NSBitmapImageRep(data: image.tiffRepresentation!)!
try bitmap.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: CommandLine.arguments[1]))
