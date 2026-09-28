import AppKit

let image = NSImage(size: NSSize(width: 1024, height: 1024))
image.lockFocus()
let rect = NSRect(x: 88, y: 88, width: 848, height: 848)
let background = NSBezierPath(roundedRect: rect, xRadius: 190, yRadius: 190)
NSGradient(starting: NSColor(srgbRed: 0.18, green: 0.48, blue: 1, alpha: 1),
           ending: NSColor(srgbRed: 0.12, green: 0.29, blue: 0.85, alpha: 1))!.draw(in: background, angle: -90)
let circle = NSBezierPath(ovalIn: NSRect(x: 200, y: 200, width: 624, height: 624))
NSColor.white.withAlphaComponent(0.12).setFill()
circle.fill()
let arrow = NSBezierPath()
arrow.lineWidth = 58
arrow.lineCapStyle = .round
arrow.lineJoinStyle = .round
arrow.move(to: NSPoint(x: 512, y: 730))
arrow.line(to: NSPoint(x: 512, y: 380))
arrow.move(to: NSPoint(x: 360, y: 522))
arrow.line(to: NSPoint(x: 512, y: 370))
arrow.line(to: NSPoint(x: 664, y: 522))
arrow.move(to: NSPoint(x: 345, y: 290))
arrow.line(to: NSPoint(x: 679, y: 290))
NSColor.white.setStroke()
arrow.stroke()
image.unlockFocus()
let bitmap = NSBitmapImageRep(data: image.tiffRepresentation!)!
try bitmap.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: CommandLine.arguments[1]))
