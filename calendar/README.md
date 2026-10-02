# District calendar reference

`Pearland_2026-27_SchoolDays.json` contains the public instructional dates from the reviewed district `SchoolDays` sheet: 171 school days, including two early-release days.

This reference has no personal data, local source paths, workbook author metadata, runtime approvals, or freshness timestamps. It does not enable live submission. The production runner still requires its separate approved private snapshot and verifies the original workbook hash, freshness, and date coverage.

To regenerate the public reference from the configured, reviewed local workbook snapshot:

```powershell
& 'outputs/.venv/Scripts/python.exe' -m tools.export_public_calendar
```

The exporter copies only explicitly permitted fields and leaves the private source and its approvals unchanged.
