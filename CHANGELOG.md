# Changelog

All notable changes to this project are documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.1] - 2026-11-27

### Fixed
- Name normalization no longer takes quadratic time on large graphs, so scanning big graphs stays fast.
- CSV plan errors now name the file, and an empty CSV gets its own message.
- The performance test measures CPU time with a 15 s budget so it is stable on shared CI machines.

## [0.1.0] - 2026-11-27

### Added
- `scan`: read-only analysis of a LightRAG working directory (graphml, standard library only) that
  writes a reproducible `plan.json` (and optional `plan.csv`) with per-rule evidence.
- Deterministic name normalization: NFKC, case folding, repeated corporate suffix/prefix removal
  (`Inc.`, `Co., Ltd.`, `주식회사`, `(주)`, `㈜`), Korean particle removal only when the remaining
  stem exists as another node or alias, spacing/punctuation removal, alias CSV, short-name guard.
- Groups by identical key (no chains), `type_conflict` groups never applied by default, trigram
  near pairs listed for review only.
- Deterministic target choice (alias canonical, no surface rules, most source chunks, degree, shorter).
- `explain`: shows the rule chain for a node and the nodes sharing its key.
- `apply`: dry-run by default; Python path (`--rag FILE.py:FUNC`) through `amerge_entities` and server
  path (`--server URL`) through `POST /graph/entities/merge`; pre-check of every source name,
  working-directory backup with sha256 manifest, resumable `apply-log.jsonl`, `--limit`.
- `restore`: verify a backup against its manifest and copy it back.
- `demo`: practice-mock run of scan, apply and rescan on real LightRAG 1.5.8, fully offline.
- English and Korean screens (`--lang`, `LIGHTRAG_DEDUPE_LANG`, `LC_ALL`/`LC_MESSAGES`/`LANG`).
