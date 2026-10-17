# Export failures

## Error E_4210

`E_4210` means the export exceeded the 15-minute processing limit. It is almost
always caused by an unfiltered date range.

### Fix

Narrow the date range to 90 days or fewer and retry. For larger exports, use
the scheduled export feature, which runs without a time limit.

## Exports that silently produce no file

If an export completes but no file appears, check that the destination storage
credentials have not expired. Expired credentials produce a successful job with
an empty result.
