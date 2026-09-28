import Foundation

struct Request: Decodable { let paths: [String] }
struct Reply: Encodable { var moved: [String] = []; var errors: [String] = [] }

var reply = Reply()
do {
    let input = FileHandle.standardInput.readDataToEndOfFile()
    let request = try JSONDecoder().decode(Request.self, from: input)
    for path in request.paths {
        do {
            let url = URL(fileURLWithPath: path)
            let values = try url.resourceValues(forKeys: [.isRegularFileKey, .isSymbolicLinkKey])
            guard values.isRegularFile == true, values.isSymbolicLink != true else {
                throw NSError(domain: "P2PFileOps", code: 1, userInfo: [NSLocalizedDescriptionKey: "只接受普通文件"])
            }
            try FileManager.default.trashItem(at: url, resultingItemURL: nil)
            reply.moved.append(path)
        } catch { reply.errors.append(URL(fileURLWithPath: path).lastPathComponent + ": " + error.localizedDescription) }
    }
} catch { reply.errors.append(error.localizedDescription) }
let data = try! JSONEncoder().encode(reply)
FileHandle.standardOutput.write(data)
exit(reply.errors.isEmpty ? 0 : 1)
