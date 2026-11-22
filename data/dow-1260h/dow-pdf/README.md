# The Department of Defense (aka War) list PDFs

Each annual list the Department posts as a PDF, kept as three files:

    dow-2024-01-31.pdf     the PDF, exactly as downloaded
    dow-2024-01-31.txt     its text, made once with `pdftotext -layout` (pages separated by form feeds)
    dow-2024-01-31.json    where it came from: the official media.defense.gov address, a Wayback
                           Machine copy of that address, and the SHA-256 of both the PDF and the text

Defense.gov blocks scripts, so nothing here downloads these: they were saved by hand from a browser,
and each matches its Wayback Machine copy byte for byte.

The scripts read the saved text, never the PDF, and check both fingerprints first. They read the
PDFs for two things only: the 2022 list (which was never printed in the Federal Register) and the
removal sections, where the PDF sometimes gives a reason the Federal Register leaves out. The PDF
itself is for the person checking: `replay` and `decide` list each one next to a difference.

To add a new one: save it as `dow-<date on its web address>.pdf`, then make its text with
`pdftotext -layout -enc UTF-8 dow-<date>.pdf dow-<date>.txt` and write its `.json` the same way as
the others (both SHA-256s, the official address, the Wayback copy).
