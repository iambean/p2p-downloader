import Foundation
import XCTest
import UniformTypeIdentifiers
@testable import P2PCore

final class DropSourcesTests: XCTestCase {
    let ed2k = "ed2k://|file|open%20fixture.txt|25|0123456789abcdef0123456789abcdef|/"
    let magnet = "magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567&dn=Open%20fixture"

    func testRealTextProvidersPreserveLinksAndDeduplicate() async throws {
        let providers = [NSItemProvider(object: (ed2k + "\r\n" + magnet) as NSString),
                         NSItemProvider(object: ed2k as NSString)]
        let batch = await DropSources.read(providers)
        XCTAssertEqual(batch.sources, [ed2k, magnet])
        XCTAssertTrue(batch.errors.isEmpty)
    }

    func testFinderURLWithSpacesAndUnicodeIsReadable() async throws {
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: folder) }
        let file = folder.appendingPathComponent("公开 示例.torrent")
        try Data("test fixture".utf8).write(to: file)
        let batch = await DropSources.read([NSItemProvider(object: file as NSURL)])
        XCTAssertEqual(batch.sources, [file.standardizedFileURL.path])
        XCTAssertTrue(batch.errors.isEmpty)
    }

    func testMalformedItemsDoNotDiscardValidItems() async {
        let batch = await DropSources.read([NSItemProvider(object: ("https://example.org/\n" + ed2k) as NSString)])
        XCTAssertEqual(batch.sources, [ed2k])
        XCTAssertEqual(batch.errors.count, 1)
    }

    func testMagnetURLProviderUsesTheSameRoute() async throws {
        let url = try XCTUnwrap(URL(string: magnet))
        let batch = await DropSources.read([NSItemProvider(object: url as NSURL)])
        XCTAssertEqual(batch.sources, [magnet])
        XCTAssertTrue(batch.errors.isEmpty)
    }

    func testBrowserURLWinsOverItsHumanReadableLabel() async {
        let provider = NSItemProvider(object: "下载开源示例" as NSString)
        let data = Data(magnet.utf8)
        provider.registerDataRepresentation(forTypeIdentifier: UTType.url.identifier, visibility: .all) { completion in
            completion(data, nil)
            return nil
        }
        let batch = await DropSources.read([provider])
        XCTAssertEqual(batch.sources, [magnet])
        XCTAssertTrue(batch.errors.isEmpty)
    }

    func testURLRepresentationDecodesSeparatorsWithoutChangingFilename() throws {
        let encoded = "ed2k://%7Cfile%7Copen%20fixture.txt%7C25%7C0123456789abcdef0123456789abcdef%7C/"
        XCTAssertEqual(try DropSources.normalize(encoded), ed2k)
        let namedPipe = encoded.replacingOccurrences(of: "open%20fixture.txt", with: "open%7Cfixture.txt")
        XCTAssertTrue(try DropSources.normalize(namedPipe).contains("|file|open%7Cfixture.txt|"))
    }

    func testDirectoriesAndMissingFilesAreRejected() throws {
        XCTAssertThrowsError(try DropSources.normalize("/missing-fixture.torrent"))
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + ".torrent")
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        XCTAssertThrowsError(try DropSources.normalize(directory.path))
        XCTAssertThrowsError(try DropSources.normalize("/tmp/movie.mp4"))
    }
}
