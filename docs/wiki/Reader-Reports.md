# Reporting an error

Anyone who finds something wrong on the site can say so with "Raportează o eroare", at
the bottom of every page and in the source panel of every record.

## What happens to a report

```
 A reader writes ──► the report waits ──► a person reads it
                     in a queue                │
                                 ┌─────────────┴─────────────┐
                          the data is wrong             it is not an error
                                 │                           │
                  the data is corrected, and a        nothing is shown
                  short note is published under
                  "Surse" → "Corecturi"
```

- **A report changes nothing by itself.** It waits until a person has checked it.
- **Only the reviewer's note is published**, with the page it is about, never what the
  reader wrote.
- The list of corrections is public, so anyone can see what was fixed and when.

## Privacy and fairness

- Personal ID numbers are removed from a report before it is saved, and the form asks
  readers not to write personal data.
- A reader can send at most **5 reports an hour**, and the queue holds at most **60**, so
  nobody can flood it.
- To count reports per reader, the reader's internet address is turned into a scrambled
  code that cannot be turned back. The address itself is never saved.

## Not yet

A request to remove personal data needs its own procedure (a way to answer the person and
a written process), planned for a later release. Until then, the form takes errors only.

How a reviewer works through the queue is in the
[README](https://github.com/CristianPopa96/date-romania-api#reader-reports).
