# QATrack+ Release Notes #

Release notes are located at http://docs.qatrackplus.com/en/latest/release_notes.html

## v4.0.0 Recent Fixes

* **Service Log**: Match Service Event Template Return to Service (RTS) QC by unit intersection instead of requiring a strict subset, allowing polymorphic templates across multiple machines and modalities ([#829](https://github.com/qatrackplus/qatrackplus/issues/829)).
* **QA**: Parse autosaved date/time strings with Moment before setting Flatpickr values to prevent date corruption across locales and custom formats.
