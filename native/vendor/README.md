# Pinned Watch upload protocol

`streaming_zip_conduit.py` is the unmodified service module from pymobiledevice3
11.25.0, commit `0758de52b85f1bce04193cd43aa488ae2545e347`. The adjacent manifest
records its SHA-256 and the upstream license. Copyright belongs to the upstream
contributors; the code is licensed under GPL-3.0, included in
`PYMOBILEDEVICE3-LICENSE`.

Source: https://github.com/doronz88/pymobiledevice3/blob/0758de52b85f1bce04193cd43aa488ae2545e347/pymobiledevice3/services/streaming_zip_conduit.py

The existing shared inspector environment uses 11.9.2 and lacks this service.
Keeping this compatible protocol module local avoids changing other projects'
installed dependencies. It uses the existing lockdown service API. No component
here is embedded in the iPhone or Watch app.

Watch companion validation and the distinction from unsupported AFC upload:
https://github.com/xtool-org/xtool/pull/350
