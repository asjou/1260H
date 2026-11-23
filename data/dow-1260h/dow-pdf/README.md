# The Department of Defense (now also styled Department of War) list PDFs

Each annual list the Department posts as a PDF, kept as three files:

    dow-2024-01-31.pdf     the PDF, exactly as downloaded
    dow-2024-01-31.txt     its text, made once with `pdftotext -layout` (pages separated by form feeds)
    dow-2024-01-31.json    where it came from: the official media.defense.gov address, the address of
                           a Wayback Machine capture of it, and the SHA-256 of the PDF and of the text

Defense.gov blocks scripts, so nothing here downloads these: they were saved by hand from a browser.
When saved, each had the same SHA-256 as its Wayback Machine capture; download the capture to check.

The scripts read the saved text, never the PDF file, and check both fingerprints first. They use
that text for two things only: the 2022 list (which was never printed in the Federal Register) and the
removal sections, where the PDF sometimes gives a reason the Federal Register leaves out. The PDF
itself is for the person checking: `replay` and `decide` list each one next to a difference.

To add a new one: save it as `dow-<date on its web address>.pdf`, then make its text with
`pdftotext -layout -enc UTF-8 dow-<date>.pdf dow-<date>.txt` and write its `.json` the same way as
the others (both SHA-256s, the official address, the Wayback copy).
