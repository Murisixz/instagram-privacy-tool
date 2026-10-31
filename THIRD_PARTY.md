# Third-party code and provenance

This project's [MIT License](LICENSE) covers its own code; it does not grant rights to Instagram, Meta, or other third-party materials. Dependencies retain their own licenses.

The repository imports [instagrapi](https://github.com/subzeroid/instagrapi), pinned in `requirements.txt`, rather than bundling its source or dependencies. instagrapi 3.2.2 is distributed under the [MIT license](https://github.com/subzeroid/instagrapi/blob/master/LICENSE). Its Python distributions contain its license. If redistributing it or other dependencies, preserve the applicable copyright and license notices and check the conditions of their bundled components; this file does not replace their license texts.

For the Linux dependency set installed during review, the package metadata reported the following. Dependency versions other than instagrapi are not locked, and other platforms may resolve different versions or bundled native libraries. Check the actual distributions when redistributing them.

| Dependency | Version reviewed | License reported by distribution |
| --- | --- | --- |
| instagrapi | 3.2.2 | MIT |
| curl_cffi | 0.17.0 | MIT; bundled native components may have additional notices |
| Pillow | 13.0.0 | MIT-CMU (PIL Software License) |
| requests | 2.34.2 | Apache-2.0; distribution includes a NOTICE file |
| certifi | 2026.10.23 | MPL-2.0 |
| pycryptodomex | 3.24.1 | BSD and public domain, according to its metadata |
| pydantic, pydantic_core, annotated-types, typing-inspection, charset-normalizer, urllib3 | 2.14.2, 2.50.2, 0.8.0, 0.4.4, 3.5.2, 2.8.0 | MIT |
| cffi | 2.1.1 | MIT-0 |
| idna, pycparser | 3.20, 3.12 | BSD-3-Clause |
| PySocks | 1.7.1 | BSD (distribution metadata) |
| typing_extensions | 4.16.0 | PSF-2.0 |

The setting names, GraphQL operation names, field names and client document identifiers were identified by inspecting a packaged app, not supplied by instagrapi. The repository does not include the IPA, its extracted files, or app binaries. Review the rights and terms surrounding publication and use of those identifiers separately; a license for this project's own code does not grant rights to third-party material. Source review found no identified copied third-party code in the tool, but provenance cannot be proven solely by inspection. If copied code is identified later, retain its applicable notices and reassess licensing.
