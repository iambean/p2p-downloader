# CI/CD and application updates

The repository contains only the P2P CLI and macOS application. Local downloads,
engine state, cached builds, credentials and unrelated download tools are excluded.

## Normal release

```sh
python3 scripts/bump_version.py 0.2.1
# Review and commit the intended source changes, including the version bump.
git push origin main
```

GitHub Actions runs Python tests, native Swift/bridge tests, an arm64 build, and
isolated aMule/aria2 integration tests. The integration download uses a loopback
web seed with generated data, not public P2P peers. Pull requests run this same
verification with read-only permissions and no signing secrets.

After a successful `main` build, the release job detects an unpublished version,
creates its tag, builds ZIP/DMG assets, signs the ZIP and update feed, verifies the
signature against the application's public key, uploads a draft release, and
publishes only after all assets are ready. It downloads the published assets again
and verifies their bytes. Before publication, an isolated older app bundle uses
the real Sparkle client to validate the signed feed and discover the update;
this probe does not install updates or touch the user's application. Pushes without a version increase run CI but do not
overwrite an existing release. `v*` tags and manual workflow runs are also supported.

Released versions and tags are immutable. For a regression, fix or revert the code,
increase both the version and build number with `bump_version.py`, and release the
new build. Do not replace an already-installed version's archive.

## App updates

The app uses Sparkle 2.10.0. The feed is:

`https://github.com/iambean/p2p-downloader/releases/latest/download/appcast.xml`

No GitHub access token is embedded in the application. Public Release assets serve
the signed feed and archive over HTTPS. Both signatures are required, and the
archive is verified before extraction. Automatic checking, download and background
installation are enabled by default; the app's settings menu has a toggle and
“检查更新…” command. Sparkle handles the installation timing and any macOS permission
prompt. Download engines and data remain outside the app bundle.

The old locally installed 0.1.0 app did not contain an updater. Install 0.2.0 once to
bootstrap automatic updates. Later releases can update it through Sparkle.

## Required GitHub secret

`SPARKLE_EDDSA_PRIVATE_KEY` is the private Ed25519 seed exported with Sparkle's
`generate_keys --account com.xinfan.p2p-downloads -x <protected-file>` tool. Store
the backup outside the repository. Upload it without printing it:

```sh
gh secret set SPARKLE_EDDSA_PRIVATE_KEY --repo iambean/p2p-downloader < /path/outside/repo/private-key
```

The corresponding public key is in `mac/Resources/Info.plist`. Preserve this key
across releases; replacing it casually prevents existing applications from
verifying future updates. The pipeline fails when the signing secret is absent or
does not match the public key. No signing secrets are provided to PR jobs.

## Optional Apple signing and notarization

Without an Apple Developer ID identity, releases are explicitly **ad-hoc signed
and not Apple-notarized**. Sparkle's EdDSA signatures still authenticate automatic
updates. A fresh download may require the normal macOS Privacy & Security approval
before first launch. The updater does not disable Gatekeeper or remove quarantine.

To enable Apple Developer ID signing and notarization, configure all five secrets:

| Secret | Value |
| --- | --- |
| `APPLE_CERTIFICATE_P12` | Base64-encoded Developer ID Application P12 |
| `APPLE_CERTIFICATE_PASSWORD` | P12 export password |
| `APPLE_API_KEY_P8` | App Store Connect API private key contents |
| `APPLE_API_KEY_ID` | API key ID |
| `APPLE_API_ISSUER_ID` | API issuer ID |

The release job imports the certificate into a temporary runner keychain, signs
the app and helpers, notarizes and staples the artifacts, and removes temporary
credentials even on failure. Partially configured Apple secrets fail explicitly.
Until these credentials are supplied and a run succeeds, notarization is not verified.

## Local release checks

```sh
python3 -m unittest discover -s tests -v
(cd mac && swift test --arch arm64)
zsh mac/scripts/build.sh
python3 scripts/release.py package
```

Release assets include `SHA256SUMS.txt`, a signed `appcast.xml`, and
`release-manifest.json` with the source commit and signing mode. CI artifacts are
for validation; GitHub Releases are the supported automatic-update channel.
