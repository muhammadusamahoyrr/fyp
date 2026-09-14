# FYP pilot dataset — content-free inventory

Document bytes, transcripts and drafts are gitignored by design. This file is
the tracked record that makes the ignored set RECOVERABLE and VERIFIABLE: ids,
hashes, family, page index, split and readiness. It contains no document text,
no transcript, no personal data and no absolute paths.

## Status

    dataset            fyp_pilot_2026_09_14
    executable manifest ABSENT by design — see manifest.draft.json
    readiness          0 of 6 slices; NOT READY

The draft manifest deliberately does NOT validate: `de_identified.confirmed`
and `consent.confirmed` are PENDING, and the schema requires them to be
literally true. The schema was not weakened to let incomplete data through.

## English control material (NOT OCR-representative)

Purpose: verifying native-text routing and extraction only. These pages carry
a real Unicode text layer, so they exercise the non-OCR path. They are NOT
representative of scanned or photographed OCR and must never be cited as
evidence about it.

| # | fixture_id | family | src page | split | sha256 |
|---|-----------|--------|----------|-------|--------|
| 1 | limitation_act_1908_p010 | limitation_act_1908 | 10 | train | `e72d735fc9f60798c18b59284f0cb7b73aefc56dbdb62d6cd135a445d66e41b2` |
| 2 | limitation_act_1908_p011 | limitation_act_1908 | 11 | train | `4a0f053cfccb726a2d3ceb23300882897374b481c85844ff4061caea0018f5ac` |
| 3 | limitation_act_1908_p012 | limitation_act_1908 | 12 | train | `921cdb5d5dd326cbc9f7c6aac6886fb10bd26bead80b699b354a015ab4802286` |
| 4 | ppc_1860_p040 | ppc_1860 | 40 | train | `a85524a3f65ca30dc94feb7648adeed403b2673ec9577229547d88ae37685e2f` |
| 5 | ppc_1860_p041 | ppc_1860 | 41 | train | `9fb74909460312fef773cefa56cccef51dee13a6950dada3f1d0a6db962de9fd` |
| 6 | ppc_1860_p042 | ppc_1860 | 42 | train | `71a150610d204fc833c805f3b328bfa7564fcdcf0a87ab718700a0d11c5eb9ad` |
| 7 | crpc_1898_p060 | crpc_1898 | 60 | holdout | `579229eacd7487d8daea0dee204c106bbc52f650f6e9a9aa398c5eade9dbfd4f` |
| 8 | crpc_1898_p061 | crpc_1898 | 61 | holdout | `dd8b5678b67c208cca091b68fcfd47fbd9d896d05c528a333c10e7b83a272193` |
| 9 | crpc_1898_p062 | crpc_1898 | 62 | holdout | `c3ebdaebdb273ead0597ed5418b2e4212651fa51dafa84d8b97eacb16462a116` |
| 10 | qanun_e_shahadat_1984_p020 | qanun_e_shahadat_1984 | 20 | holdout | `ed5b62e0d27177c7ed17d9a90aef9ca8358023b79dfe288900d42aafbd767f1c` |
| 11 | qanun_e_shahadat_1984_p021 | qanun_e_shahadat_1984 | 21 | holdout | `ec274babe26112ef4754ffea4a5f2d696789ec8abbfbbfc2746c9aa12e9aa842` |
| 12 | qanun_e_shahadat_1984_p022 | qanun_e_shahadat_1984 | 22 | holdout | `ba93aaf0aa868068d250c131b4fd97c2fae098250091dd497b3d9d4e717c3bc2` |

Split is assigned per document FAMILY. Families: limitation_act_1908 (train),
ppc_1860 (train), crpc_1898 (holdout), qanun_e_shahadat_1984 (holdout).
No family appears on both sides.

## Urdu candidates acquired

Official Punjab government Urdu translations. Vector text in NOORI NASTALIQ
(InPage) fonts: zero embedded images, and ZERO Unicode Urdu characters, so the
text layer extracts as mojibake and is USELESS as ground truth. A human
transcript is mandatory for every one of these.

| file | bytes | sha256 | source |
|------|-------|--------|--------|
| PCS_Act_1974.pdf | 337040 | `18551cbdd87c26960ffa22e6ffdf01cff3abbfbe0475f0f0b426ff6c2f4af4c0` | https://regulationswing.punjab.gov.pk/system/files/PCS_Act_1974.pdf |
| PCS_(ACS)_Rules_1974.pdf | 417827 | `7c61c4c14fcb72b5eedae23e398fd8debc63854fb0f41e340f65a4e708de9bc1` | https://regulationswing.punjab.gov.pk/system/files/PCS_%28ACS%29_Rules_1974.pdf |
| PEEDA_2006.pdf | 414602 | `76e357580680e620f1367b95b6de68c830b288b2d950b3e980c0fe0cc0177804` | https://regulationswing.punjab.gov.pk/system/files/PEEDA_2006.pdf |

Usage basis: published by the Government of the Punjab, Regulations/O&M Wing,
S&GAD, for public access. Official legislation translations; no personal data.

## Provenance of the English control families

| family | status | evidence |
|--------|--------|----------|
| limitation_act_1908 | **VERIFIED** | byte-identical SHA-256 to https://punjabcode.punjab.gov.pk/uploads/articles/2-limitation-act-1908-pdf.pdf |
| qanun_e_shahadat_1984 | **BLOCKED** | three official candidates fetched; all differ by hash. Exact origin not established |
| ppc_1860 | **BLOCKED** | generic local filename; no candidate verified |
| crpc_1898 | **BLOCKED** | generic local filename; no candidate verified |

BLOCKED means not established. It is not a guess recorded as a fact.

## Recovery

    archive   _backup_2026_09_14.tar   (2140160 bytes)
    sha256    b66addd2cf41aa95182f126cb8709dad81fc00c83ff7b851d37394d3db4ad05f

NOT uploaded anywhere. Store it wherever the project keeps large artefacts and
verify against this hash before reuse.

## Human work outstanding

  1. 12 English control transcripts — drafts exist in transcripts_draft/ from
     the embedded text layer. They are MACHINE output and must be visually
     verified page by page before promotion to transcripts/.
  2. 3 Urdu transcripts — NO draft is possible; the NOORI text layer is
     mojibake. These must be typed by a fluent Urdu reader from the page.
  3. Critical-field annotation for all 15 — pending, not decided.
  4. Provenance for 3 BLOCKED English families.
  5. Still to acquire: 2 Urdu scanned/scan-like, 2 mixed Urdu/English.
