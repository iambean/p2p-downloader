import CryptoKit
import Foundation

guard CommandLine.arguments.count == 4 else {
    fputs("Usage: VerifyUpdate archive signature public-key\n", stderr)
    exit(2)
}
let archive = try Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[1]))
guard let signature = Data(base64Encoded: CommandLine.arguments[2]),
      let publicData = Data(base64Encoded: CommandLine.arguments[3]) else { exit(2) }
let key = try Curve25519.Signing.PublicKey(rawRepresentation: publicData)
guard key.isValidSignature(signature, for: archive) else {
    fputs("Update signature does not match the application's public key.\n", stderr)
    exit(1)
}
print("Update archive signature verified using the embedded public key.")
