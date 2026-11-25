# Public delivery verification

[中文验收记录](VERIFICATION.md)

## Bilingual release checks

A signed-out browser opened the public project directory and both contribution guides. Each edit link led to GitHub sign-in with the corresponding handbook file as the return destination. The access check reached the sign-in screen. The procedure for a contributor to submit a pull request follows GitHub's documented workflow. [Editing files in another user's repository](https://docs.github.com/en/repositories/working-with-files/managing-files/editing-files#editing-files-in-another-users-repository)

On the live English prototype the same request key was submitted twice. The first request charged $2.00 and the second replayed the result. The downloaded CSV contained one row for TEN-017 with $82.40 due. Switching handbook languages preserved the pilot section. The customer budgets screen opened in the 390 CSS-pixel mobile preview. The published English PDF and bilingual ZIP matched the release files byte for byte. [Tested revision](https://github.com/69755354/newme-skills/commit/d7b75e8042d278f8af371bf65b7393b3203b3b98)

The English and Chinese handbooks have the same 12 chapter anchors, 10 implementation tables and three diagrams. Both PDFs render to 12 A4 pages, with the two-customer pilot on page 10. All six deliverables in the bilingual ZIP matched the separate files. The seventh file, `START.html`, opens the offline language menu.

The prototype passed the same 25 behaviour checks in each language. They cover request replay, limits, egress selection, suspension, customer isolation and billing. In the English demo, a sample CUR export for TEN-017 produced one customer row with $62.40 in usage, a $20.00 fee and $82.40 due.

The project repository is public and permits forks. The contribution page gives teammates the editable files and the intended pull-request base branch.

## Engineering handbook v1.1

On 25 November 2026 (Dubai), a signed-out browser followed the GitHub README link to the two-customer pilot. The page displayed v1.1, the division of responsibilities between the gateway and Bedrock, the two billing paths and the tests assigned to four roles. [Engineering revision](https://github.com/69755354/newme-skills/commit/77ff89f9e36c173e6d53c77bf4ed0dc1c57a4f5e)

The published Chinese PDF and ZIP in that revision matched the release files byte for byte. Page 10 of the 12-page Chinese PDF contained the pilot. The ZIP included the same PDF and a Word copy with that section. The two historical SHA-256 digests are listed in the [Chinese record](VERIFICATION.md).

## Prototype v1.0

These observations refer to the Chinese demo and its published files on 25 November 2026 (Dubai). [Tested revision](https://github.com/69755354/newme-skills/commit/4878baef03d87a3e31f6461b59a48350074f927c)

| Check | Observed result |
| --- | --- |
| Public entry and downloads | The GitHub project and README opened while signed out. Both the README and handbook opened the interactive demo. The PDF, Word document and ZIP matched their published checksums. |
| Request and replay | Customer A submitted a request with a $2.50 reservation ceiling. The first submission charged $2.00. Repeating the key replayed that result and total usage charges held at $94.80. |
| Over-budget request | A new key with a $999.00 reservation received 429. The screen showed $19.80 available and the request was withheld. |
| Budget change | Raising the daily budget from $100.00 to $120.00 and confirming the change produced $37.80 available. |
| Customer invoice | Importing the sample CUR and exporting Customer A produced a CSV with one header and one data row. TEN-017 had $62.40 in usage, a $20.00 fixed fee and $82.40 due. |
| Customer isolation | In a 390 CSS-pixel browser viewport, Customer A's portal showed only its own balances, bill and services. Customer B was absent. |
| Route failure | After disconnecting DXB-01, Customer A's fixed route stopped sending. Customer B used its approved standby, DXB-02. |
| Reset | After confirming reset and re-entering from GitHub, the three sample customers and initial $92.80 total were restored. |

The tests covered public materials, sample data and browser exports. Mobile layout was exercised in a desktop browser. The deployment pilot covers real AWS billing, physical Dubai egress and production isolation.
